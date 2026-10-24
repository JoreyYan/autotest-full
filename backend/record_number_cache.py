"""
record_number_cache.py — 扫码标签(序列码/飞书链接) → 序号 的本地解析与缓存

旧码扫码慢的主因之一：每次扫码都要同步等 ERP + 飞书分享页两次网络请求
（最长 ~11s）。这里：
- 正向缓存（token→序号）命中直接返回，持久化到工作目录 record_number_cache.json
- 未命中(负向)缓存 10 分钟内存 TTL：标签库后补的码最多等 10 分钟就能查到
- 解析走复用的 HTTPS 连接（keep-alive），省掉每次扫码的 TLS 握手
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests

ERP_RESOLVE_URL = 'https://www.soaipower.com/api/erp/production/resolve-serial'

_NEG_TTL = 600.0   # 负向缓存 10 分钟
_POS_CAP = 2000    # 持久化正向缓存上限（超出丢最旧的）

_lock = threading.Lock()
_pos: dict[str, str] = {}
_neg: dict[str, float] = {}
_loaded = False
_session: Optional[requests.Session] = None

_TOKEN_RE = re.compile(r'feishu\.cn/record/([A-Za-z0-9]{8,})')

_cache_file = Path('record_number_cache.json')


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        from requests.adapters import HTTPAdapter
        s = requests.Session()
        s.mount('https://', HTTPAdapter(pool_connections=4, pool_maxsize=8))
        _session = s
    return _session


def _key(url_or_token: str) -> str:
    """缓存键：飞书链接取 record token，其余用原文。"""
    m = _TOKEN_RE.search(url_or_token or '')
    return m.group(1) if m else (url_or_token or '').strip()


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if _cache_file.exists():
            data = json.loads(_cache_file.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(k, str) and isinstance(v, str) and v:
                        _pos[k] = v
    except Exception:
        pass


def _save_locked():
    try:
        _cache_file.write_text(json.dumps(_pos, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _fetch(url_or_token: str) -> tuple[Optional[str], str, str]:
    """先问 ERP 标签库映射，失败兜底爬飞书分享页。返回 (序号, 错误, 来源)。"""
    s = _get_session()
    err = ''
    try:
        r = s.get(ERP_RESOLVE_URL, params={'token': url_or_token}, timeout=(5, 6))
        d = r.json()
        if d.get('ok') and d.get('number'):
            return str(d['number']), '', 'erp'
        err = str(d.get('error') or '')
    except Exception as e:
        err = str(e)
    if str(url_or_token or '').startswith('http'):
        try:
            r = s.get(url_or_token, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(5, 5))
            m = re.search(r'window\.SERVER_DATA\.shareRecord\s*=\s*Object\((\{.*?\})\);',
                          r.text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                rs = json.loads(data.get('RecordShare', '{}'))
                pk = rs.get('primaryKey')
                v = (rs.get('recordData') or {}).get(pk, {}).get('value')
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    num = v[0].get('number') or v[0].get('text') or v[0].get('sequence')
                    return (str(num), '', 'feishu') if num else (None, err or '分享页无序号', '')
                return (str(v), '', 'feishu') if v is not None else (None, err or '分享页无序号', '')
        except Exception as e2:
            err = f'{err}; {e2}'
    return None, err or '标签库未命中', ''


def resolve(url_or_token: str) -> tuple[Optional[str], str, str]:
    """解析序号。返回 (序号, 错误信息, 来源)。来源: cache/erp/feishu。"""
    key = _key(url_or_token)
    if not key:
        return None, '空的序列码', ''
    with _lock:
        _load()
        if key in _pos:
            return _pos[key], '', 'cache'
        t = _neg.get(key)
        if t and time.time() - t < _NEG_TTL:
            return None, '标签库未命中(本地缓存)', ''
    num, err, src = _fetch(url_or_token)
    with _lock:
        if num:
            if key not in _pos:
                _pos[key] = num
                while len(_pos) > _POS_CAP:
                    _pos.pop(next(iter(_pos)))
                _save_locked()
            _neg.pop(key, None)
        else:
            _neg[key] = time.time()
    return num, err, src


def cached_count() -> int:
    with _lock:
        _load()
        return len(_pos)
