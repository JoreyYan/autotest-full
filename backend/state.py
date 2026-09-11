"""
state.py — 全局状态
backend 唯一操作 agent 的入口，TestRunner 单例在这里管理
"""
from pathlib import Path
import json


# TestRunner 单例（backend 启动时为 None，初始化后才有值）
runner = None
inspection_runner = None

# 当前产品配置
current_product: dict | None = None
current_inspection_product: dict | None = None

# 扣偏校验状态(金样校验):初始化/切产品/同步参数后重置,需重新校验
# id: 本次校验的追溯ID(通过后测试记录都带上它)
calibration = {'passed': False, 'checked_at': None, 'detail': [], 'id': None}


def reset_calibration():
    calibration['passed'] = False
    calibration['checked_at'] = None
    calibration['detail'] = []
    calibration['id'] = None


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


def get_deployment() -> dict:
    """当前工位信息（公司/产线/工段/工位ID）。未注册时字段为空。"""
    cfg = _load_config()
    return {
        'deployment_id': cfg.get('deployment_id', ''),
        'company': cfg.get('company', ''),
        'line': cfg.get('line', ''),
        'station': cfg.get('station', ''),
    }


def save_deployment(deployment_id: str, company: str, line: str, station: str):
    cfg = _load_config()
    cfg['deployment_id'] = deployment_id
    cfg['company'] = company
    cfg['line'] = line
    cfg['station'] = station
    _save_config(cfg)


def get_code_state() -> dict:
    """本机流水码号段进度（未领号段时各字段为 None）。"""
    cfg = _load_config()
    return {
        'code_block_start': cfg.get('code_block_start'),
        'code_block_end': cfg.get('code_block_end'),
        'code_next': cfg.get('code_next'),
    }


def save_code_state(block_start: int, block_end: int, next_seq: int | None = None):
    cfg = _load_config()
    cfg['code_block_start'] = block_start
    cfg['code_block_end'] = block_end
    cfg['code_next'] = block_start if next_seq is None else next_seq
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
