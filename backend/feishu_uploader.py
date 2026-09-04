"""
feishu_uploader.py — 飞书多维表格推送
- 每个产品对应一张飞书子表（首次推送自动建表 + 自动加字段）
- 推送失败的记录写入本地队列 (feishu_pending.jsonl)
- 后台线程定时重试

凭证读取顺序：
  1. 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_APP_TOKEN
  2. 工作目录下 feishu_config.json
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .logs import log


FEISHU_BASE = 'https://open.feishu.cn/open-apis'

# Field type codes (per Feishu Bitable API)
FIELD_TEXT = 1
FIELD_NUMBER = 2
FIELD_SINGLE_SELECT = 3
FIELD_DATETIME = 5

# 测试值字段统一用 3 位小数显示
NUMBER_FIELD_PROPERTY = {'formatter': '0.000'}


def _number_field_def(name: str) -> dict:
    return {'field_name': name, 'type': FIELD_NUMBER, 'property': dict(NUMBER_FIELD_PROPERTY)}

# 公共前缀字段（每个产品表都有，且排在测试项之前）
COMMON_PREFIX_FIELDS = [
    {'field_name': '测试时间', 'type': FIELD_DATETIME},
    {'field_name': '公司', 'type': FIELD_TEXT},
    {'field_name': '产线', 'type': FIELD_TEXT},
    {'field_name': '工段', 'type': FIELD_TEXT},
    {'field_name': '序列码', 'type': FIELD_TEXT},
    {'field_name': '序号', 'type': FIELD_TEXT},
    {'field_name': '磁芯编号', 'type': FIELD_TEXT},
    {'field_name': '产品', 'type': FIELD_TEXT},
]

# 公共后缀字段（每个产品表都有，且排在测试项之后）
COMMON_SUFFIX_FIELDS = [
    {'field_name': '产品结果', 'type': FIELD_SINGLE_SELECT,
     'property': {'options': [{'name': 'PASS'}, {'name': 'FAIL'}]}},
    {'field_name': '扣偏校验ID', 'type': FIELD_TEXT},
]

# 扣偏校验(金样)记录表
CAL_TABLE_NAME = '_扣偏校验记录'
CAL_TABLE_FIELDS = [
    {'field_name': '校验时间', 'type': FIELD_DATETIME},
    {'field_name': '校验ID', 'type': FIELD_TEXT},
    {'field_name': '工位ID', 'type': FIELD_TEXT},
    {'field_name': '公司', 'type': FIELD_TEXT},
    {'field_name': '产线', 'type': FIELD_TEXT},
    {'field_name': '工段', 'type': FIELD_TEXT},
    {'field_name': '产品', 'type': FIELD_TEXT},
    {'field_name': '结果', 'type': FIELD_SINGLE_SELECT,
     'property': {'options': [{'name': '通过'}, {'name': '未通过'}]}},
    {'field_name': '容差%', 'type': FIELD_NUMBER, 'property': dict(NUMBER_FIELD_PROPERTY)},
    {'field_name': '明细', 'type': FIELD_TEXT},
]

# 产品配置同步表
CONFIG_TABLE_NAME = '_产品配置'
CONFIG_TABLE_FIELDS = [
    {'field_name': '产品编号', 'type': FIELD_TEXT},
    {'field_name': '产品名称', 'type': FIELD_TEXT},
    {'field_name': '配置JSON', 'type': FIELD_TEXT},
    {'field_name': '更新时间', 'type': FIELD_DATETIME},
]


def _flatten_text(v) -> str:
    """飞书文本字段读出可能是 [{type:'text', text:'xxx'}] 列表，做兼容。"""
    if v is None:
        return ''
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        out = []
        for seg in v:
            if isinstance(seg, dict):
                out.append(seg.get('text', ''))
            else:
                out.append(str(seg))
        return ''.join(out)
    return str(v)


def _resolve_record_number(serial_id: str):
    """扫码序列码(飞书分享页token)反查序号:ERP 标签库映射优先;分享页解析兜底。"""
    try:
        r0 = requests.get('https://www.soaipower.com/api/erp/production/resolve-serial',
                          params={'token': serial_id}, timeout=6)
        d0 = r0.json()
        if d0.get('ok') and d0.get('number'):
            return str(d0['number'])
    except Exception:
        pass
    try:
        r = requests.get(f'https://smartonep.feishu.cn/record/{serial_id}',
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=6)
        m = re.search(r'window\.SERVER_DATA\.shareRecord\s*=\s*Object\((\{.*?\})\);', r.text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(1))
        rs = json.loads(data.get('RecordShare', '{}'))
        pk = rs.get('primaryKey')
        v = (rs.get('recordData') or {}).get(pk, {}).get('value')
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v[0].get('number') or v[0].get('text') or v[0].get('sequence')
        return str(v) if v is not None else None
    except Exception:
        return None


def _item_label(item: dict) -> str:
    """生成测试项的字段名：Lx_2-3(uH)；EqN 单独命名为 '等效n'。"""
    t = item.get('type', '')
    if t == 'EqN':
        return '等效n'
    base = f"{t}_{item.get('pins', '')}"
    unit = item.get('unit')
    return f"{base}({unit})" if unit else base


def _is_finite(v) -> bool:
    if v is None:
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(x) or math.isinf(x))


class FeishuUploader:
    def __init__(self, app_id: str, app_secret: str, app_token: str, work_dir: Path):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.work_dir = work_dir
        self.queue_file = work_dir / 'feishu_pending.jsonl'
        self.mapping_file = work_dir / 'feishu_table_mapping.json'
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._retry_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # 复用 HTTPS 连接，减少 SSL 握手抖动
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        self._session = requests.Session()
        # 网络层重试：连接错误/读取超时/5xx 自动重试，指数 backoff
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=4,
                connect=4,
                read=2,
                backoff_factor=0.6,        # 0.6, 1.2, 2.4, 4.8s
                status_forcelist=(500, 502, 503, 504),
                allowed_methods=('GET', 'POST', 'PUT', 'DELETE'),
            ),
            pool_connections=2,
            pool_maxsize=4,
        )
        self._session.mount('https://', adapter)

    # ── token ─────────────────────────────────────────────
    def _get_token(self) -> str:
        with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expires_at:
                return self._token
            # session 已挂了 Retry adapter，自动重试网络抖动
            r = self._session.post(
                f'{FEISHU_BASE}/auth/v3/tenant_access_token/internal',
                json={'app_id': self.app_id, 'app_secret': self.app_secret},
                timeout=(5, 15)
            )
            data = r.json()
            if data.get('code') != 0:
                raise RuntimeError(f'飞书 token 获取失败: {data}')
            self._token = data['tenant_access_token']
            self._token_expires_at = now + data.get('expire', 7200) - 300
            return self._token

    def _api(self, method: str, path: str, **kwargs):
        """飞书 API 调用：网络层用 Retry adapter 自动重试 5 次；业务错误（code!=0）应用层加一次轻重试。"""
        url = f'{FEISHU_BASE}{path}'
        # token 401 / 99991663 类业务错（token 过期）触发一次刷新重试
        last_err = None
        for attempt in range(2):
            try:
                token = self._get_token()
                headers = kwargs.pop('headers', {})
                headers['Authorization'] = f'Bearer {token}'
                r = self._session.request(method, url, headers=headers, timeout=(5, 20), **kwargs)
                try:
                    data = r.json()
                except Exception:
                    raise RuntimeError(f'飞书 API 非 JSON 响应 {method} {path}: {r.status_code} {r.text[:200]}')
                if data.get('code') == 99991663:
                    # token 失效，强制刷新
                    with self._token_lock:
                        self._token = None
                        self._token_expires_at = 0
                    last_err = RuntimeError(f'token 失效, 重试中: {data}')
                    continue
                if data.get('code') != 0:
                    raise RuntimeError(f'飞书 API 错误 {method} {path}: {data}')
                return data.get('data', {})
            except requests.exceptions.RequestException as e:
                # 网络层错误，Session adapter 重试已用尽，再起一次
                last_err = e
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                raise
        raise last_err if last_err else RuntimeError('unknown')

    # ── 表/字段管理 ────────────────────────────────────────
    def _load_mapping(self) -> dict:
        if not self.mapping_file.exists():
            return {}
        try:
            return json.loads(self.mapping_file.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def _save_mapping(self, mapping: dict):
        self.mapping_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')

    def _list_existing_field_names(self, table_id: str) -> set:
        try:
            data = self._api('GET', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields?page_size=100')
            return {f.get('field_name') for f in data.get('items', [])}
        except Exception as e:
            log(f'飞书获取字段列表失败 {table_id}: {e}', 'WARN')
            return set()

    def _add_field(self, table_id: str, field_def: dict):
        try:
            self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields', json=field_def)
        except Exception as e:
            # 已存在不算错误
            msg = str(e)
            if 'FieldNameRepeated' in msg or '1254003' in msg or 'already exists' in msg.lower():
                return
            log(f"飞书添加字段失败 {field_def.get('field_name')}: {e}", 'WARN')

    def _ensure_common_fields(self, table_id: str):
        """老表可能缺后来新增的公共列（如 公司/产线/工段）。
        每会话每表只核对一次，缺的补上，避免 FieldNameNotFound 拒收。"""
        checked = getattr(self, '_common_fields_checked', None)
        if checked is None:
            checked = self._common_fields_checked = set()
        if table_id in checked:
            return
        try:
            existing = self._list_existing_field_names(table_id)
            for f in COMMON_PREFIX_FIELDS:
                if f['field_name'] not in existing:
                    self._add_field(table_id, f)
                    log(f"老表补公共列: {f['field_name']} -> {table_id}")
            for f in COMMON_SUFFIX_FIELDS:
                if f['field_name'] not in existing:
                    self._add_field(table_id, f)
                    log(f"老表补公共列: {f['field_name']} -> {table_id}")
            checked.add(table_id)
        except Exception as e:
            log(f'核对公共列失败(不阻断): {e}', 'WARN')

    def _ensure_table(self, product_code: str, item_labels: list[str]) -> str:
        """返回 table_id；不存在则建表 + 加字段；存在但缺字段则补字段。"""
        mapping = self._load_mapping()
        entry = mapping.get(product_code)
        if entry and entry.get('table_id'):
            table_id = entry['table_id']
            self._ensure_common_fields(table_id)
            known = set(entry.get('item_labels', []))
            new_labels = [lab for lab in item_labels if lab not in known]
            if new_labels:
                # schema drift：测项加了/改了，补字段
                existing = self._list_existing_field_names(table_id)
                for lab in new_labels:
                    if lab not in existing:
                        self._add_field(table_id, _number_field_def(lab))
                entry['item_labels'] = list(set(entry.get('item_labels', []) + item_labels))
                mapping[product_code] = entry
                self._save_mapping(mapping)
            return table_id

        # 本地映射没记录 → 先看飞书是否已有同名表（防止重复建表撞名）
        existing_id = self._find_table_by_name(product_code)
        if existing_id:
            log(f'飞书已存在表 {product_code} -> {existing_id}，回填本地映射')
            mapping[product_code] = {'table_id': existing_id, 'item_labels': list(item_labels)}
            self._save_mapping(mapping)
            # 把缺的字段补上
            existing_fields = self._list_existing_field_names(existing_id)
            for f in COMMON_PREFIX_FIELDS:
                if f['field_name'] not in existing_fields:
                    self._add_field(existing_id, f)
            for lab in item_labels:
                if lab not in existing_fields:
                    self._add_field(existing_id, _number_field_def(lab))
            for f in COMMON_SUFFIX_FIELDS:
                if f['field_name'] not in existing_fields:
                    self._add_field(existing_id, f)
            return existing_id

        # 建表（撞名 1254013 → 兜底回去找现有表）
        try:
            result = self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables', json={
                'table': {'name': product_code}
            })
            table_id = result['table_id']
            log(f'飞书自动建表: {product_code} -> {table_id}')
        except Exception as e:
            if 'TableNameDuplicated' in str(e) or '1254013' in str(e):
                # 表其实已存在（首次 _find 没查到/竞态），重新查一次
                existing_id = self._find_table_by_name(product_code)
                if existing_id:
                    log(f'建表撞名，回退到现有表 {product_code} -> {existing_id}')
                    mapping[product_code] = {'table_id': existing_id, 'item_labels': list(item_labels)}
                    self._save_mapping(mapping)
                    existing_fields = self._list_existing_field_names(existing_id)
                    for f in COMMON_PREFIX_FIELDS:
                        if f['field_name'] not in existing_fields:
                            self._add_field(existing_id, f)
                    for lab in item_labels:
                        if lab not in existing_fields:
                            self._add_field(existing_id, _number_field_def(lab))
                    for f in COMMON_SUFFIX_FIELDS:
                        if f['field_name'] not in existing_fields:
                            self._add_field(existing_id, f)
                    return existing_id
            raise

        # 顺序：前缀字段 → 测试项字段 → 后缀字段（与 CSV 列顺序对齐）
        existing = self._list_existing_field_names(table_id)
        for f in COMMON_PREFIX_FIELDS:
            if f['field_name'] not in existing:
                self._add_field(table_id, f)
        for lab in item_labels:
            if lab not in existing:
                self._add_field(table_id, _number_field_def(lab))
        for f in COMMON_SUFFIX_FIELDS:
            if f['field_name'] not in existing:
                self._add_field(table_id, f)

        mapping[product_code] = {'table_id': table_id, 'item_labels': list(item_labels)}
        self._save_mapping(mapping)
        return table_id

    # ── 记录构造 ───────────────────────────────────────────
    def _build_fields(self, record_dict: dict) -> dict:
        items = record_dict.get('items') or []
        ts_str = record_dict.get('timestamp', '')
        try:
            ts_ms = int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        except Exception:
            ts_ms = int(time.time() * 1000)

        fields: dict = {
            '测试时间': ts_ms,
            '公司': record_dict.get('company', '') or '',
            '产线': record_dict.get('line', '') or '',
            '工段': record_dict.get('station', '') or '',
            '序列码': record_dict.get('serial_code', '') or '',
            '序号': record_dict.get('record_number', '') or '',
            '磁芯编号': record_dict.get('core_number', '') or '',
            '产品': record_dict.get('product_code', '') or '',
            '产品结果': record_dict.get('overall', '') or '',
            '扣偏校验ID': record_dict.get('calibration_id', '') or '',
        }

        for it in items:
            label = _item_label(it)
            v = it.get('value_display')
            if not _is_finite(v):
                v = it.get('value')
            if _is_finite(v):
                fields[label] = float(v)

        return fields

    # ── 推送 ──────────────────────────────────────────────
    def _push_one(self, record_dict: dict):
        items = record_dict.get('items') or []
        labels = [_item_label(it) for it in items]
        product_code = record_dict.get('product_code', '') or 'UNKNOWN'
        table_id = self._ensure_table(product_code, labels)
        fields = self._build_fields(record_dict)
        self._api(
            'POST',
            f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/records',
            json={'fields': fields}
        )

    def push_async(self, record_dict: dict):
        """非阻塞推送，失败入队等重试。
        推送前兜底解析序号:序号为空但有序列码(扫码token)时,反查飞书分享页拿序号带上——
        从源头保证测试表序号列有值,ERP不再依赖事后补全(海外服务器爬分享页常失败)。"""
        def _run():
            try:
                sid = str(record_dict.get('serial_code') or '')
                if not record_dict.get('record_number') and len(sid) > 15 and sid.isalnum():
                    num = _resolve_record_number(sid)
                    if num:
                        record_dict['record_number'] = num
                        log(f'序号已解析并随记录上传: {num}')
            except Exception:
                pass
            self._push_with_retry(record_dict)
        threading.Thread(target=_run, daemon=True).start()

    def _push_with_retry(self, record_dict: dict):
        # _api 本身已包含网络层重试(5次 backoff) + token 重试(1次)
        # 此处再加 1 次应用层重试，覆盖偶发 SSL/连接抖动
        last_err = None
        for attempt in range(2):
            try:
                self._push_one(record_dict)
                tag = '' if attempt == 0 else f' (重试{attempt}次后)'
                log(f"飞书推送成功{tag} {record_dict.get('product_code')} 序列码={record_dict.get('serial_code') or '-'}")
                return
            except Exception as e:
                last_err = e
                if attempt == 0:
                    time.sleep(3)
                    continue
        log(f'飞书推送失败(已重试2次)，加入重试队列: {last_err}', 'WARN')
        self._enqueue(record_dict)

    # ── 离线队列 ───────────────────────────────────────────
    def _enqueue(self, record_dict: dict):
        with self._queue_lock:
            try:
                with self.queue_file.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(record_dict, ensure_ascii=False) + '\n')
            except Exception as e:
                log(f'飞书写入待推送队列失败: {e}', 'ERROR')

    def retry_pending(self):
        """从队列里逐条重试，成功的剔除。
        并发安全：先把 pending 文件 rename 走再处理，期间新测试 append 到新的
        pending 文件不受影响；失败的条目处理完再 append 回去。"""
        if not self.queue_file.exists():
            return 0, 0
        processing = self.queue_file.with_suffix('.processing')
        # 持锁：把当前 pending 整体移走（原子）。新测试此后 append 到全新 pending 文件。
        with self._queue_lock:
            if not self.queue_file.exists():
                return 0, 0
            try:
                if processing.exists():
                    # 上次处理可能中断遗留，合并进来一起处理
                    with processing.open('a', encoding='utf-8') as pf, self.queue_file.open('r', encoding='utf-8') as qf:
                        pf.write(qf.read())
                    self.queue_file.unlink()
                else:
                    os.replace(str(self.queue_file), str(processing))
            except Exception as e:
                log(f'飞书重试：移动队列文件失败 {e}', 'WARN')
                return 0, 0

        try:
            content = processing.read_text(encoding='utf-8')
        except Exception:
            return 0, 0
        lines = [ln for ln in content.splitlines() if ln.strip()]
        if not lines:
            try:
                processing.unlink()
            except Exception:
                pass
            return 0, 0

        remaining: list[str] = []
        success = 0
        for ln in lines:
            try:
                record_dict = json.loads(ln)
                self._push_one(record_dict)
                success += 1
            except Exception:
                remaining.append(ln)

        # 失败的 append 回正式 pending（与期间新写入的并存，不覆盖）
        with self._queue_lock:
            if remaining:
                with self.queue_file.open('a', encoding='utf-8') as f:
                    f.write('\n'.join(remaining) + '\n')
            try:
                processing.unlink()
            except Exception:
                pass

        if success or remaining:
            log(f'飞书重试：成功 {success} 条，仍待推送 {len(remaining)} 条', sticky=True)
        return success, len(remaining)

    # ── 产品配置同步 ───────────────────────────────────────
    def _list_tables(self) -> list[dict]:
        """列出 base 下所有表，返回 [{table_id, name}, ...]"""
        data = self._api('GET', f'/bitable/v1/apps/{self.app_token}/tables?page_size=100')
        return data.get('items') or []

    def _find_table_by_name(self, name: str) -> Optional[str]:
        """按表名查 table_id；找不到返回 None"""
        for t in self._list_tables():
            if t.get('name') == name:
                return t.get('table_id')
        return None

    def _ensure_config_table(self) -> str:
        mapping = self._load_mapping()
        entry = mapping.get('__config__')
        if entry and entry.get('table_id'):
            return entry['table_id']

        # 本地映射没记录 → 先到飞书上看看表是否已存在（防止重复建表撞名）
        existing_id = self._find_table_by_name(CONFIG_TABLE_NAME)
        if existing_id:
            log(f'飞书已存在配置表 {CONFIG_TABLE_NAME} -> {existing_id}，回填本地映射')
            mapping['__config__'] = {'table_id': existing_id}
            self._save_mapping(mapping)
            return existing_id

        result = self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables', json={
            'table': {'name': CONFIG_TABLE_NAME}
        })
        table_id = result['table_id']
        log(f'飞书自动建配置表: {CONFIG_TABLE_NAME} -> {table_id}')

        existing = self._list_existing_field_names(table_id)
        for f in CONFIG_TABLE_FIELDS:
            if f['field_name'] not in existing:
                self._add_field(table_id, f)

        mapping['__config__'] = {'table_id': table_id}
        self._save_mapping(mapping)
        return table_id

    def _ensure_cal_table(self) -> str:
        """扣偏校验记录表：不存在则建，存在缺字段则补。"""
        mapping = self._load_mapping()
        entry = mapping.get('__calibration__')
        if entry and entry.get('table_id'):
            return entry['table_id']
        table_id = self._find_table_by_name(CAL_TABLE_NAME)
        if not table_id:
            result = self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables', json={
                'table': {'name': CAL_TABLE_NAME}
            })
            table_id = result['table_id']
            log(f'飞书自动建扣偏校验表: {CAL_TABLE_NAME} -> {table_id}')
        existing = self._list_existing_field_names(table_id)
        for f in CAL_TABLE_FIELDS:
            if f['field_name'] not in existing:
                self._add_field(table_id, f)
        mapping['__calibration__'] = {'table_id': table_id}
        self._save_mapping(mapping)
        return table_id

    def push_calibration(self, cal: dict):
        """异步推送一条扣偏校验记录（成败都记）。失败只记日志，不入重试队列。"""
        def _do():
            try:
                table_id = self._ensure_cal_table()
                detail = cal.get('detail') or []
                lines = []
                for d in detail:
                    err = d.get('error_pct')
                    lines.append(f"{d.get('test_type')} {d.get('pins')}: 标准{d.get('standard')} 实测{d.get('measured')} "
                                 f"误差{err if err is not None else '?'}% {'OK' if d.get('ok') else 'NG'}")
                fields = {
                    '校验时间': int(time.time() * 1000),
                    '校验ID': cal.get('id', '') or '',
                    '工位ID': cal.get('deployment_id', '') or '',
                    '公司': cal.get('company', '') or '',
                    '产线': cal.get('line', '') or '',
                    '工段': cal.get('station', '') or '',
                    '产品': cal.get('product_code', '') or '',
                    '结果': '通过' if cal.get('passed') else '未通过',
                    '容差%': float(cal.get('tolerance_pct') or 0),
                    '明细': '\n'.join(lines),
                }
                self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/records',
                          json={'fields': fields})
                log(f"扣偏校验记录已推飞书: {cal.get('id')} {'通过' if cal.get('passed') else '未通过'}")
            except Exception as e:
                log(f'扣偏校验记录推送失败(不阻断): {e}', 'WARN')
        threading.Thread(target=_do, daemon=True).start()

    def _list_records(self, table_id: str) -> list[dict]:
        records: list[dict] = []
        page_token = ''
        while True:
            qs = 'page_size=500'
            if page_token:
                qs += f'&page_token={page_token}'
            data = self._api('GET', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?{qs}')
            records.extend(data.get('items') or [])
            if not data.get('has_more'):
                break
            page_token = data.get('page_token') or ''
            if not page_token:
                break
        return records

    # ── 工位注册 + 参数下发（第2步：ERP集中管控）────────────
    DEPLOY_TABLE = 'tblWq5o4RzT9A4rk'   # _工位
    PARAM_TABLE = 'tblly75fVtVGiram'    # _产品参数
    RELEASE_TABLE = 'tbltEfMJtSFPU3mO'  # _软件版本（自动更新通道）

    def fetch_latest_release(self) -> Optional[dict]:
        """读 _软件版本 表，返回版本号最大的一行：
        {version, notes, file_token, file_name, file_size}；无可用版本返回 None。"""
        def _ver_key(v: str):
            try:
                return tuple(int(x) for x in v.strip().lstrip('vV').split('.'))
            except Exception:
                return (0,)
        best = None
        for r in self._list_records(self.RELEASE_TABLE):
            f = r.get('fields') or {}
            ver = _flatten_text(f.get('版本号')).strip().lstrip('vV')
            att = f.get('安装包') or []
            if not ver or not att:
                continue
            a = att[0]
            item = {
                'version': ver,
                'notes': _flatten_text(f.get('说明')).strip(),
                'file_token': a.get('file_token'),
                'file_name': a.get('name') or '',
                'file_size': int(a.get('size') or 0),
            }
            if best is None or _ver_key(item['version']) > _ver_key(best['version']):
                best = item
        return best

    def download_release_file(self, file_token: str, dest_path: Path) -> int:
        """下载 _软件版本 表附件到 dest_path，返回写入字节数。"""
        url = f'{FEISHU_BASE}/drive/v1/medias/{file_token}/download'
        headers = {'Authorization': f'Bearer {self._get_token()}'}
        with self._session.get(url, headers=headers, timeout=(10, 600),
                               stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            n = 0
            with open(dest_path, 'wb') as fh:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        fh.write(chunk)
                        n += len(chunk)
            return n

    def register_station(self, company: str, line: str, station: str) -> str:
        """注册工位到飞书 _工位 表，返回生成的 deployment_id（查重，重复加序号）。"""
        base = f'{company}-{line}-{station}'.strip('-')
        existing = set()
        for r in self._list_records(self.DEPLOY_TABLE):
            f = r.get('fields') or {}
            did = _flatten_text(f.get('工位ID'))
            if did:
                existing.add(did)
        dep_id = base
        n = 1
        while dep_id in existing:
            dep_id = f'{base}-{n:02d}'
            n += 1
        self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables/{self.DEPLOY_TABLE}/records', json={
            'fields': {
                '工位ID': dep_id, '公司': company, '产线': line, '工段': station,
                '启用': '启用', '注册时间': int(time.time() * 1000),
            }
        })
        log(f'工位已注册: {dep_id}', sticky=True)
        return dep_id

    def fetch_deployed_params(self, deployment_id: str) -> list[dict]:
        """拉飞书 _产品参数 表里本工位下发的所有产品参数。
        返回 [{product_code, version, config}]。"""
        out = []
        for r in self._list_records(self.PARAM_TABLE):
            f = r.get('fields') or {}
            if _flatten_text(f.get('工位ID')) != deployment_id:
                continue
            code = _flatten_text(f.get('产品编号'))
            if not code:
                continue
            try:
                cfg = json.loads(_flatten_text(f.get('配置JSON')) or '{}')
            except Exception:
                continue
            try:
                ver = int(f.get('版本') or 0)
            except (ValueError, TypeError):
                ver = 0
            try:
                upd = int(f.get('更新时间') or 0)
            except (ValueError, TypeError):
                upd = 0
            out.append({'product_code': code, 'version': ver, 'updated_at': upd, 'config': cfg})
        return out

    def upload_products(self, products_dir: Path) -> dict:
        """把本地 products/*.json 全部 upsert 到飞书。"""
        table_id = self._ensure_config_table()

        local: dict[str, dict] = {}
        for p in products_dir.glob('*.json'):
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                code = data.get('product_code') or p.stem
                local[code] = data
            except Exception as e:
                log(f'读取 {p.name} 失败: {e}', 'WARN')

        existing_map: dict[str, str] = {}
        for rec in self._list_records(table_id):
            fields = rec.get('fields') or {}
            code = _flatten_text(fields.get('产品编号'))
            rid = rec.get('record_id')
            if code and rid:
                existing_map[code] = rid

        now_ms = int(time.time() * 1000)
        created = 0
        updated = 0
        failed = 0
        for code, data in local.items():
            try:
                fields = {
                    '产品编号': code,
                    '产品名称': data.get('product_name', '') or '',
                    '配置JSON': json.dumps(data, ensure_ascii=False, indent=2),
                    '更新时间': now_ms,
                }
                if code in existing_map:
                    self._api('PUT', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{existing_map[code]}', json={'fields': fields})
                    updated += 1
                else:
                    self._api('POST', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/records', json={'fields': fields})
                    created += 1
            except Exception as e:
                log(f'上传产品 {code} 失败: {e}', 'WARN')
                failed += 1

        log(f'产品配置上传完成：新增 {created}，更新 {updated}，失败 {failed}')
        return {'created': created, 'updated': updated, 'failed': failed, 'total_local': len(local)}

    def download_products(self, products_dir: Path) -> dict:
        """从飞书拉所有产品配置写入本地 products/。本地多余的不动。"""
        table_id = self._ensure_config_table()
        records = self._list_records(table_id)
        products_dir.mkdir(parents=True, exist_ok=True)

        saved = 0
        failed = 0
        codes_synced: list[str] = []
        for rec in records:
            fields = rec.get('fields') or {}
            code = _flatten_text(fields.get('产品编号')).strip()
            if not code:
                continue
            try:
                config_text = _flatten_text(fields.get('配置JSON'))
                data = json.loads(config_text)
                target = products_dir / f'{code}.json'
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                saved += 1
                codes_synced.append(code)
            except Exception as e:
                log(f'下载产品 {code} 失败: {e}', 'WARN')
                failed += 1

        log(f'产品配置下载完成：保存 {saved} 个，失败 {failed}')
        return {'saved': saved, 'failed': failed, 'products': codes_synced}

    def migrate_number_formatters(self, target_formatter: str = '0.000') -> int:
        """一次性迁移：把所有产品表里的数字字段格式化精度改为 target_formatter。"""
        mapping = self._load_mapping()
        total = 0
        for key, entry in mapping.items():
            if key.startswith('__'):
                continue
            table_id = entry.get('table_id')
            if not table_id:
                continue
            try:
                data = self._api('GET', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields?page_size=200')
                for f in data.get('items') or []:
                    if f.get('type') != FIELD_NUMBER:
                        continue
                    current = (f.get('property') or {}).get('formatter')
                    if current == target_formatter:
                        continue
                    fid = f.get('field_id')
                    fname = f.get('field_name')
                    self._api('PUT', f'/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields/{fid}', json={
                        'field_name': fname,
                        'type': FIELD_NUMBER,
                        'property': {'formatter': target_formatter}
                    })
                    total += 1
                    log(f'飞书字段精度更新: {key}.{fname} -> {target_formatter}')
            except Exception as e:
                log(f'迁移 {key} 字段失败: {e}', 'WARN')
        return total

    def start_retry_loop(self, interval_sec: int = 120):
        if self._retry_thread and self._retry_thread.is_alive():
            return
        def _loop():
            # 启动后等 8 秒（让网络/token 就绪）就开始清积压，间隔 120s 一轮
            time.sleep(8)
            while not self._stop.is_set():
                try:
                    s, r = self.retry_pending()
                    # 还有大量积压时，缩短间隔尽快清空
                    if r > 0:
                        self._stop.wait(20)
                        continue
                except Exception as e:
                    log(f'飞书重试循环异常: {e}', 'ERROR')
                self._stop.wait(interval_sec)
        self._retry_thread = threading.Thread(target=_loop, daemon=True, name='feishu-retry')
        self._retry_thread.start()
        log(f'飞书后台重试线程已启动（间隔 {interval_sec}s）', sticky=True)


# ── 全局单例 ──────────────────────────────────────────────
_uploader: Optional[FeishuUploader] = None
_init_lock = threading.Lock()


def _read_credentials(work_dir: Path) -> tuple[Optional[str], Optional[str], Optional[str]]:
    app_id = os.environ.get('FEISHU_APP_ID')
    app_secret = os.environ.get('FEISHU_APP_SECRET')
    app_token = os.environ.get('FEISHU_APP_TOKEN')
    if app_id and app_secret and app_token:
        return app_id, app_secret, app_token
    cfg = work_dir / 'feishu_config.json'
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding='utf-8'))
            return (
                app_id or data.get('app_id'),
                app_secret or data.get('app_secret'),
                app_token or data.get('app_token'),
            )
        except Exception as e:
            log(f'读取 feishu_config.json 失败: {e}', 'WARN')
    return app_id, app_secret, app_token


def get_uploader(work_dir: Optional[Path] = None) -> Optional[FeishuUploader]:
    """返回单例。无凭证时返回 None（推送会被静默禁用）。"""
    global _uploader
    if _uploader is not None:
        return _uploader
    with _init_lock:
        if _uploader is not None:
            return _uploader
        wd = work_dir or Path.cwd()
        wd.mkdir(parents=True, exist_ok=True)
        app_id, app_secret, app_token = _read_credentials(wd)
        if not (app_id and app_secret and app_token):
            return None
        _uploader = FeishuUploader(app_id, app_secret, app_token, wd)
        _uploader.start_retry_loop()
        return _uploader
