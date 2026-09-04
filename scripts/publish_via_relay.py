# -*- coding: utf-8 -*-
"""发版(中继版):本机直传 open.feishu.cn 的大包经常被掐断时用。

用法:
    python scripts/publish_via_relay.py --version 1.7.4 --notes "..."

做法:和 publish_release.py 打同一个 zip,切成 1MB 小块传到 ERP(Railway),
由 ERP 分片传飞书并在 _软件版本 表建记录。每块独立重试,断了接着传。
"""
import argparse
import hashlib
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from publish_release import build_zip  # noqa: E402

ERP = 'https://soai-production.up.railway.app'
CHUNK = 1024 * 1024


def post_retry(url, tries=8, **kw):
    last = None
    for i in range(tries):
        try:
            r = requests.post(url, timeout=120, **kw)
            d = r.json()
            if d.get('ok'):
                return d
            last = d
        except Exception as e:
            last = str(e)
        time.sleep(3 * (i + 1))
    raise SystemExit(f'失败: {url} → {last}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True)
    ap.add_argument('--notes', default='')
    a = ap.parse_args()
    data = build_zip(a.version)
    name = f'smarton-release-v{a.version}.zip'
    sha = hashlib.sha256(data).hexdigest()
    uid = f'rel-{a.version.replace(".", "_")}-{uuid.uuid4().hex[:8]}'
    total = (len(data) + CHUNK - 1) // CHUNK
    print(f'中继上传 {name} {len(data) / 1024 / 1024:.1f}MB → {total} 块 (upload_id={uid})')
    for seq in range(total):
        chunk = data[seq * CHUNK:(seq + 1) * CHUNK]
        post_retry(f'{ERP}/api/erp/admin/relay-upload/chunk',
                   data={'upload_id': uid, 'seq': seq}, files={'file': ('part', chunk)})
        if (seq + 1) % 10 == 0 or seq + 1 == total:
            print(f'  已传 {seq + 1}/{total}')
    st = requests.get(f'{ERP}/api/erp/admin/relay-upload/status', params={'upload_id': uid}, timeout=60).json()
    if st.get('count') != total:
        raise SystemExit(f'服务器只收到 {st.get("count")}/{total} 块')
    print('服务器拼包并上传飞书…')
    r = requests.post(f'{ERP}/api/erp/admin/relay-upload/publish', json={
        'upload_id': uid, 'total': total, 'file_name': name, 'version': a.version,
        'notes': a.notes, 'sha256': sha}, timeout=1500).json()
    if not r.get('ok'):
        raise SystemExit(f'发布失败: {r}')
    print(f"发布成功 v{a.version}: file_token={r.get('file_token')} record={r.get('record_id')} blocks={r.get('blocks')}")


if __name__ == '__main__':
    main()
