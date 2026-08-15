# -*- coding: utf-8 -*-
"""发版脚本：把 release/ 打成干净 zip，上传飞书 _软件版本 表，产线设备即可一键更新。

用法（在项目根目录 D:/code/autotest 运行）:
    python scripts/publish_release.py --version 1.5.0 --notes "自动更新+字号调节"

打包内容：smarton.exe / smarton-backend.exe / frontend/dist / 使用说明 / 更新日志 / 飞书凭据
排除：config.json 里的工位身份(重置为干净模板)、products/、results/、backup/、update_tmp/
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / 'release'
BASE_TOKEN = 'HvqibKLVkaeORss7K9tcLpCZnpg'
RELEASE_TABLE = 'tbltEfMJtSFPU3mO'  # _软件版本
API = 'https://open.feishu.cn/open-apis'

CLEAN_CONFIG = {
    'port': 'COM3',
    'baudrate': 115200,
    'products_dir': 'products',
    'results_dir': 'results',
}


def get_token() -> str:
    cfg = json.loads((RELEASE / 'feishu_config.json').read_text(encoding='utf-8'))
    r = requests.post(f'{API}/auth/v3/tenant_access_token/internal',
                      json={'app_id': cfg['app_id'], 'app_secret': cfg['app_secret']}, timeout=15)
    d = r.json()
    assert d.get('code') == 0, d
    return d['tenant_access_token']


def build_zip(version: str) -> bytes:
    buf = io.BytesIO()
    include_files = ['smarton.exe', 'smarton-backend.exe', '使用说明.md', '更新日志.md',
                     'feishu_config.json', 'feishu_table_mapping.json']
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in include_files:
            p = RELEASE / name
            if p.exists():
                z.write(p, name)
        for p in (RELEASE / 'frontend' / 'dist').rglob('*'):
            if p.is_file():
                z.write(p, str(p.relative_to(RELEASE)))
        # 干净 config（新装机器首次启动会弹注册页；老机器更新时 bat 不会碰 config）
        z.writestr('config.json', json.dumps(CLEAN_CONFIG, ensure_ascii=False, indent=2))
    data = buf.getvalue()
    print(f'打包完成: {len(data) / 1024 / 1024:.1f} MB')
    return data


def upload_to_feishu(token: str, name: str, data: bytes) -> str:
    H = {'Authorization': f'Bearer {token}'}
    size = len(data)
    r = requests.post(f'{API}/drive/v1/medias/upload_prepare', headers=H, json={
        'file_name': name, 'parent_type': 'bitable_file', 'parent_node': BASE_TOKEN, 'size': size,
    }, timeout=30).json()
    assert r.get('code') == 0, r
    upload_id = r['data']['upload_id']
    block_size = r['data']['block_size']
    block_num = r['data']['block_num']
    print(f'分片上传: {block_num} 片 x {block_size // 1024 // 1024}MB')
    for seq in range(block_num):
        chunk = data[seq * block_size:(seq + 1) * block_size]
        rr = requests.post(f'{API}/drive/v1/medias/upload_part', headers=H,
                           data={'upload_id': upload_id, 'seq': seq, 'size': len(chunk)},
                           files={'file': chunk}, timeout=300).json()
        assert rr.get('code') == 0, rr
        print(f'  片 {seq + 1}/{block_num} OK')
    r2 = requests.post(f'{API}/drive/v1/medias/upload_finish', headers=H,
                       json={'upload_id': upload_id, 'block_num': block_num}, timeout=60).json()
    assert r2.get('code') == 0, r2
    return r2['data']['file_token']


def create_record(token: str, version: str, notes: str, file_token: str, file_name: str, size: int):
    import time
    H = {'Authorization': f'Bearer {token}'}
    r = requests.post(f'{API}/bitable/v1/apps/{BASE_TOKEN}/tables/{RELEASE_TABLE}/records',
                      headers=H, json={'fields': {
                          '版本号': version,
                          '说明': notes,
                          '安装包': [{'file_token': file_token}],
                          '发布时间': int(time.time() * 1000),
                      }}, timeout=30).json()
    assert r.get('code') == 0, r
    print('版本记录已创建:', r['data']['record']['record_id'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True, help='如 1.5.0')
    ap.add_argument('--notes', default='', help='更新说明(显示在设备横幅上)')
    args = ap.parse_args()
    version = args.version.lstrip('vV')

    data = build_zip(version)
    token = get_token()
    name = f'smarton-release-v{version}.zip'
    file_token = upload_to_feishu(token, name, data)
    print('附件 file_token:', file_token)
    create_record(token, version, args.notes, file_token, name, len(data))
    print(f'发版完成 v{version} — 各设备 1 小时内提示更新（或立即刷新页面可见）')


if __name__ == '__main__':
    main()
