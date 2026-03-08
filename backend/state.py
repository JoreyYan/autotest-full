"""
state.py — 全局状态
backend 唯一操作 agent 的入口，TestRunner 单例在这里管理
"""
from pathlib import Path
import json


# TestRunner 单例（backend 启动时为 None，初始化后才有值）
runner = None

# 当前产品配置
current_product: dict | None = None


def get_products_dir() -> Path:
    cfg = _load_config()
    return Path(cfg.get('products_dir', 'products'))


def get_results_dir() -> Path:
    cfg = _load_config()
    d = Path(cfg.get('results_dir', 'results'))
    d.mkdir(exist_ok=True)
    return d


def get_port() -> str:
    return _load_config().get('port', None)


def get_baudrate() -> int:
    return _load_config().get('baudrate', 115200)


def save_port(port: str):
    cfg = _load_config()
    cfg['port'] = port
    _save_config(cfg)


def _load_config() -> dict:
    p = Path('config.json')
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return {}


def _save_config(cfg: dict):
    Path('config.json').write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
