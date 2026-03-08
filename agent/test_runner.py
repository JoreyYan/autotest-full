"""
test_runner.py — 测试流程控制层
职责：实现完整的7步初始化流程 + 循环测试
对外暴露：初始化状态、每次测试结果
"""
import json
import time
import math
from dataclasses import dataclass, field
from pathlib import Path
from .serial_conn import find_instrument
from .instrument import Instrument
from .config_checker import check, CheckResult


# ── 测试记录 ─────────────────────────────────────────────────────

@dataclass
class TestRecord:
    """单次测试结果"""
    timestamp: str
    product_code: str
    items: list[dict]        # [{type, pins, value, lo, hi, result}]
    passed: int = 0
    failed: int = 0
    overall: str = 'FAIL'   # 'PASS' or 'FAIL'
    csv_raw: str = ''        # 原始CSV（备用）


def parse_csv(csv_text: str) -> list[dict]:
    """把 CSV 文本解析成结构化列表"""
    records = []
    for seg in csv_text.split(';'):
        seg = seg.strip().lstrip('!')
        parts = seg.split(',')
        if len(parts) >= 7:
            try:
                records.append({
                    'type':   parts[1].strip(),
                    'pins':   parts[2].strip().lstrip("'"),
                    'value':  float(parts[3]),
                    'lo':     float(parts[4]),
                    'hi':     float(parts[5]),
                    'result': parts[6].strip()
                })
            except (ValueError, IndexError):
                pass
    return records


def _normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip()
    if not u:
        return None
    return (
        u.replace("μ", "u")
        .replace("µ", "u")
        .replace("渭", "u")
        .replace("Ω", "Ohm")
        .replace("惟", "Ohm")
    )


def _convert_si_to_display(value: float, unit: str | None) -> float:
    u = _normalize_unit(unit)
    if not u:
        return value
    scale = {
        "H": 1.0,
        "mH": 1e3,
        "uH": 1e6,
        "nH": 1e9,
        "F": 1.0,
        "mF": 1e3,
        "uF": 1e6,
        "nF": 1e9,
        "pF": 1e12,
        "Ohm": 1.0,
        "mOhm": 1e3,
        "kOhm": 1e-3,
    }
    return value * scale.get(u, 1.0)


def _index_to_symbol(idx: int) -> str:
    n = idx
    out = ""
    while True:
        out = chr(65 + (n % 26)) + out
        n = n // 26 - 1
        if n < 0:
            return out



class TestRunner:
    """
    使用方式：
        runner = TestRunner('products/ZZ-T250005A.json')
        status = runner.initialize()   # 返回初始化状态字典
        if status['ok']:
            record = runner.run()      # 每次测试调用一次
    """

    def __init__(self, product_json_path: str, logger=None):
        with open(product_json_path, encoding='utf-8') as f:
            self.product = json.load(f)
        self._instr: Instrument | None = None
        self._ready = False
        self._log = logger or (lambda *args, **kwargs: None)

    def _emit(self, message: str):
        self._log(message)

    # ── 初始化（7步）────────────────────────────────────────────

    def initialize(self, port: str = None, baudrate: int = 115200) -> dict:
        """
        执行7步初始化流程。
        返回字典：{ok, port, idn, config_check, message}
        """
        status = {'ok': False, 'port': None, 'idn': '', 'config_check': None, 'message': ''}

        # 步骤1+2：找端口
        self._emit('扫描串口，查找 UC2866XB...')
        found_port = find_instrument(baudrate=baudrate, preferred_port=port)
        if not found_port:
            status['message'] = '未找到 UC2866XB 仪器，请检查连接'
            self._emit(status['message'])
            return status
        status['port'] = found_port
        self._emit(f'已找到端口：{found_port}')

        # 连接
        self._emit(f'连接串口 {found_port} @ {baudrate} bps')
        self._instr = Instrument(found_port, baudrate)
        if not self._instr.connect():
            status['message'] = f'串口 {found_port} 连接失败'
            self._emit(status['message'])
            return status

        # 步骤2：确认IDN
        self._emit('发送 *IDN?')
        idn = self._instr.idn()
        status['idn'] = idn
        self._emit(f'IDN = {idn}')

        # 步骤3：加载配置（等收完，丢弃）
        config_id = self.product['instrument_config_id']
        self._emit(f'发送 mmem:load:trs {config_id}')
        cfg_data = self._instr.load_config(config_id)
        if not cfg_data:
            status['message'] = f'加载配置 {config_id} 失败'
            self._emit(status['message'])
            return status
        self._emit(f'配置包已接收：{len(cfg_data)} 字节（丢弃）')

        # 步骤4+5：初始化 *TRG（验证 + 让操作员看到机器动）
        self._emit('发送 *TRG（初始化触发）')
        ok, csv = self._instr.run_test()
        if not ok:
            status['message'] = '初始化 *TRG 无响应，请检查仪器状态'
            self._emit(status['message'])
            return status
        self._emit(f'收到 CSV：{len(csv)} 字符')

        # 步骤4：配置比对
        self._emit('开始配置校验')
        check_result: CheckResult = check(csv, self.product)
        status['config_check'] = {
            'ok':      check_result.ok,
            'missing': check_result.missing,
            'extra':   check_result.extra,
            'message': check_result.message
        }

        if check_result.ok:
            self._emit('配置校验通过')
        else:
            self._emit(f'配置校验异常：{check_result.message}')

        if not check_result.ok:
            status['message'] = f'配置不匹配：{check_result.message}'
            return status

        # 步骤6：就绪
        self._ready = True
        status['ok'] = True
        status['message'] = f'初始化完成，仪器 {idn.split(",")[1] if "," in idn else idn}，配置验证通过，可以开始测试'
        self._emit('初始化完成，设备就绪')
        return status

    # ── 单次测试 ─────────────────────────────────────────────────

    def run(self) -> TestRecord | None:
        """
        执行一次测试，返回 TestRecord。
        必须先调用 initialize() 成功后才能调用。
        """
        if not self._ready or not self._instr:
            return None

        self._emit('发送 *TRG（开始测试）')
        ok, csv = self._instr.run_test()
        if not ok:
            self._emit('测试失败：*TRG 无响应')
            return None
        self._emit(f'收到 CSV：{len(csv)} 字符')

        raw_items = parse_csv(csv)
        config_items = self.product.get("test_items", [])
        config_map: dict[tuple[str, str], dict] = {}
        for i, cfg in enumerate(config_items):
            t = str(cfg.get("test_type", "")).strip()
            p2 = str(cfg.get("pins", "")).strip()
            if not t or not p2:
                continue
            cfg2 = dict(cfg)
            cfg2.setdefault("symbol", _index_to_symbol(i))
            config_map[(t, p2)] = cfg2

        items: list[dict] = []
        symbols: dict[str, float] = {}
        for item in raw_items:
            cfg = config_map.get((item["type"], item["pins"]), {})
            unit = _normalize_unit(cfg.get("unit"))
            value_display = _convert_si_to_display(float(item["value"]), unit)
            symbol = str(cfg.get("symbol", "")).strip().upper()
            if symbol:
                symbols[symbol] = value_display
            lo_display = cfg.get("lower_limit")
            hi_display = cfg.get("upper_limit")

            items.append(
                {
                    **item,
                    "unit": unit,
                    "value_display": value_display,
                    "lo_display": lo_display if isinstance(lo_display, (int, float)) else None,
                    "hi_display": hi_display if isinstance(hi_display, (int, float)) else None,
                    "symbol": symbol or None,
                }
            )

        # ???????n = sqrt((A - B) / C)?????(???)??
        # ???????n = sqrt((A - B) / C)????????????????
        enable_eq_n = bool(self.product.get("enable_eq_n", False))
        eq_cfg = self.product.get("eq_n_vars") or {}
        a_key = str(eq_cfg.get("l_raw", "A")).strip().upper() or "A"
        b_key = str(eq_cfg.get("lk_raw", "B")).strip().upper() or "B"
        c_key = str(eq_cfg.get("l_aux", "C")).strip().upper() or "C"
        if enable_eq_n and all(k in symbols for k in (a_key, b_key, c_key)):
            try:
                numerator = symbols[a_key] - symbols[b_key]
                denominator = symbols[c_key]
                if denominator == 0:
                    raise ValueError("C=0")
                ratio = numerator / denominator
                if ratio < 0:
                    raise ValueError("sqrt_arg_negative")
                neq = math.sqrt(ratio)
                items.append(
                    {
                        "type": "EqN",
                        "pins": "-",
                        "value": neq,
                        "lo": 0.0,
                        "hi": 0.0,
                        "result": "Pass",
                        "unit": "",
                        "value_display": neq,
                        "lo_display": None,
                        "hi_display": None,
                        "symbol": "N",
                    }
                )
            except Exception as exc:
                items.append(
                    {
                        "type": "EqN",
                        "pins": "-",
                        "value": 0.0,
                        "lo": 0.0,
                        "hi": 0.0,
                        "result": "Fail",
                        "unit": "",
                        "value_display": float("nan"),
                        "lo_display": None,
                        "hi_display": None,
                        "error": str(exc),
                        "symbol": "N",
                    }
                )


        passed = sum(1 for i in items if i["result"] == "Pass")
        failed = len(items) - passed
        self._emit(f"??????? {passed}/{len(items)}??? {failed}")


        from datetime import datetime
        return TestRecord(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            product_code=self.product['product_code'],
            items=items,
            passed=passed,
            failed=failed,
            overall='PASS' if failed == 0 else 'FAIL',
            csv_raw=csv
        )

    # ── 收尾 ─────────────────────────────────────────────────────

    def close(self):
        if self._instr:
            self._instr.disconnect()
        self._ready = False
