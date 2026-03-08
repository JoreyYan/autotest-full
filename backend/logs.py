from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
from typing import List, Dict, Optional


_lock = threading.Lock()
_entries: List[Dict] = []
_next_id = 1
_log_file: Optional[Path] = None


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def start_session(product_code: str, phase: str):
    """Start a new log file for a session and clear memory buffer."""
    global _entries, _next_id, _log_file
    with _lock:
        _entries = []
        _next_id = 1
        logs_dir = Path('results') / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        _log_file = logs_dir / f'{product_code}_{ts}_{phase}.log'
        _append_to_file(f'[{_now()}] [INFO] 开始记录日志（{phase}）')


def _append_to_file(line: str):
    if not _log_file:
        return
    with _log_file.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def log(message: str, level: str = 'INFO'):
    global _next_id
    with _lock:
        entry = {
            'id': _next_id,
            'ts': _now(),
            'level': level,
            'message': message,
        }
        _entries.append(entry)
        _next_id += 1
        _append_to_file(f"[{entry['ts']}] [{level}] {message}")


def get_since(since_id: int = 0, limit: int = 200) -> Dict:
    with _lock:
        items = [e for e in _entries if e['id'] > since_id][:limit]
        last_id = _entries[-1]['id'] if _entries else since_id
        return {
            'items': items,
            'last_id': last_id,
            'file': _log_file.name if _log_file else ''
        }
