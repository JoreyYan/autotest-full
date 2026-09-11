"""磁芯流水码 —— 全局唯一、工位内严格递增、断网可用。

编码规则
  字符集 32 个：23456789ABCDEFGHJKLMNPQRSTUVWXYZ（去掉易混的 0/O/1/I）
  4 位起步 = 1,048,576 个；用满自动扩到 5 位（33,554,432），不用改系统

全局唯一怎么保证
  号段预分配：每个工位首次发号时去飞书 _编码段 表领一段（默认 1 万个），
  各工位号段互不重叠。领到段后本机自己发号，断网照常工作；发完再领下一段。
  本机进度存 config.json（code_next / code_block_end），断电不丢号。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from . import state

ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'  # 32 个，无 0 O 1 I
BASE = len(ALPHABET)
MIN_WIDTH = 4
BLOCK_SIZE = 10000          # 每次领取的号段大小
LOW_WATER = 50              # 剩余不足这么多时提前续领（趁还有网）

_lock = threading.Lock()


def encode(n: int, width: int = MIN_WIDTH) -> str:
    """序号 → 码。不足 width 位左补字符集首位；超出自动加长。"""
    if n < 0:
        raise ValueError('序号不能为负')
    s = ''
    while n > 0:
        n, r = divmod(n, BASE)
        s = ALPHABET[r] + s
    return s.rjust(width, ALPHABET[0])


def decode(code: str) -> int:
    """码 → 序号（校验用）。"""
    n = 0
    for ch in code.strip().upper():
        idx = ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f'非法字符: {ch}')
        n = n * BASE + idx
    return n


def _alloc_block(uploader, deployment_id: str, size: int = BLOCK_SIZE) -> tuple[int, int]:
    """去飞书 _编码段 领一段：取现有最大段止之后接着开。返回 (段起, 段止)。"""
    records = uploader.list_code_blocks()
    max_end = -1
    for f in records:
        try:
            e = int(f.get('段止') or -1)
        except (TypeError, ValueError):
            continue
        max_end = max(max_end, e)
    start = max_end + 1
    end = start + size - 1
    uploader.create_code_block(deployment_id, start, end, encode(start))
    return start, end


def _ensure_block(force: bool = False) -> Optional[str]:
    """确保本机有可用号段；需要时去飞书领。返回错误信息，None 表示正常。"""
    cfg = state.get_code_state()
    nxt, end = cfg['code_next'], cfg['code_block_end']
    if not force and nxt is not None and end is not None and nxt <= end:
        return None

    dep = state.get_deployment().get('deployment_id')
    if not dep:
        return '尚未注册工位，无法领取号段'
    from pathlib import Path
    from .feishu_uploader import get_uploader
    uploader = get_uploader(Path.cwd())
    if not uploader:
        return '飞书未配置，无法领取号段'
    try:
        start, new_end = _alloc_block(uploader, dep)
    except Exception as e:
        return f'领取号段失败: {e}'
    state.save_code_state(start, new_end)
    return None


def next_code() -> tuple[Optional[str], Optional[str]]:
    """取下一个流水码。返回 (码, 错误)。断网且本机号段未用完时照常发号。"""
    with _lock:
        err = _ensure_block()
        if err:
            return None, err
        cfg = state.get_code_state()
        n = cfg['code_next']
        code = encode(n)
        state.save_code_state(cfg['code_block_start'], cfg['code_block_end'], n + 1)
        # 余量不足且有网时，后台提前续领，避免用尽时正好断网
        if cfg['code_block_end'] - n < LOW_WATER:
            threading.Thread(target=_prefetch, daemon=True).start()
        return code, None


def _prefetch():
    try:
        cfg = state.get_code_state()
        if cfg['code_next'] is not None and cfg['code_next'] > cfg['code_block_end']:
            _ensure_block(force=True)
    except Exception:
        pass


def status() -> dict:
    cfg = state.get_code_state()
    nxt, end = cfg['code_next'], cfg['code_block_end']
    return {
        'has_block': nxt is not None and end is not None,
        'block_start': cfg['code_block_start'],
        'block_end': end,
        'next_seq': nxt,
        'next_code': encode(nxt) if nxt is not None else None,
        'remaining': (end - nxt + 1) if (nxt is not None and end is not None) else 0,
        'alphabet': ALPHABET,
        'width': MIN_WIDTH,
        'capacity': BASE ** MIN_WIDTH,
    }
