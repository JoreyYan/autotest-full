"""UC2910 系列变压器综合测试仪驱动。

协议依据《2910变压器扫描数据发送格式.docx》：
- 上位机发 `TRIG;:FETCh?` 一次性触发扫描并取回结果
- 仪器回定长二进制包：包头 40 字节（#、00H、条码30B、主绕组数、保留7B），
  随后 8 组测量值(float32 × PMAX×10)、相位(char × PMAX×10)、
  10 组判定码(char × PMAX×10：Turn/Lx/Lk/Cx/Dcr/Q/Acr/Zx/Bal/Ps)、
  LED 结果与判定、总判定、结束符 0x0A。
  包长 = 42 + PMAX×450（PMAX=最大初级组数，由包长反推）。
- 判定码：0=未测，1=GO 合格，2=LO 偏低，3=HI 偏高，4=NG

与 2866 的差异及本驱动的约定：
- 测试条件（设置文件）需在仪器面板载入，暂无已验证的远程载入指令，
  load_config() 直接放行（拿到 SCPI 指令集后可补真实现）。
- 二进制包按数组索引回数、不带引脚号，引脚由 set_pin_map() 映射：
  按产品 JSON 中各类型测试项的先后顺序对应仪器扫描顺序（须保持一致）。
- 字节序文档未注明：解析时小端/大端各试一次，用数值合理性自检选定。
"""
from __future__ import annotations

import math
import struct
import time

from .base_instrument import BaseInstrument
from .serial_conn import SerialConn

# 数值数组与判定数组在包中的先后顺序（文档表1）
VAL_ORDER = ["Turn", "Lx", "Lk", "Cx", "Dcr", "Q", "Acr", "Zx"]
JUDGE_ORDER = ["Turn", "Lx", "Lk", "Cx", "Dcr", "Q", "Acr", "Zx", "Bal", "Ps"]
JUDGE_NAMES = {0: "None", 1: "GO", 2: "LO", 3: "HI", 4: "NG"}

HEADER_LEN = 40
BYTES_PER_PMAX = 450  # 8×40(值) + 10(相位) + 10×10(判定) + 16(LED值) + 4(LED判定)


def parse_packet(raw: bytes) -> dict:
    """解析二进制结果包。返回 {pmax, pri, barcode, vals, judges, phs, whole, endian}。
    字节序自检：先小端后大端，已测项的数值必须有限且量级合理。"""
    start = raw.find(b"#\x00")
    if start < 0:
        raise ValueError(f"未找到包头 23 00: {raw[:8].hex(' ')}")
    raw = raw[start:]
    if len(raw) < HEADER_LEN + 2 or (len(raw) - 42) % BYTES_PER_PMAX != 0:
        raise ValueError(f"包长无效: {len(raw)}")
    pmax = (len(raw) - 42) // BYTES_PER_PMAX
    if pmax < 1 or pmax > 20:
        raise ValueError(f"PMAX 反推异常: {pmax}")
    barcode = raw[2:32].split(b"\x00")[0].decode("ascii", errors="replace")
    pri = raw[32]

    last_err = None
    for endian in ("<", ">"):
        off = HEADER_LEN
        vals: dict[str, tuple] = {}
        for t in VAL_ORDER:
            n = pmax * 10
            vals[t] = struct.unpack(f"{endian}{n}f", raw[off:off + 4 * n])
            off += 4 * n
        phs = raw[off:off + pmax * 10]
        off += pmax * 10
        judges: dict[str, bytes] = {}
        for t in JUDGE_ORDER:
            judges[t] = raw[off:off + pmax * 10]
            off += pmax * 10
        off += pmax * 16 + pmax * 4  # LED 结果 + LED 判定
        whole = raw[off]

        ok = True
        for t in VAL_ORDER:
            for i in range(pmax * 10):
                if judges[t][i] != 0:
                    v = vals[t][i]
                    if math.isnan(v) or math.isinf(v) or abs(v) > 1e15:
                        ok = False
                        break
            if not ok:
                break
        if ok:
            return {"pmax": pmax, "pri": pri, "barcode": barcode, "vals": vals,
                    "judges": judges, "phs": phs, "whole": whole, "endian": endian}
        last_err = f"{endian} 字节序数值不合理"
    raise ValueError(f"字节序解析失败: {last_err}")


def to_csv(parsed: dict, pin_map: dict[str, list[str]] | None) -> str:
    """转成 test_runner 兼容的 CSV 行：`1,<type>,'<pins>,<val>,<lo>,<hi>,<Pass|Fail>;...`
    仅输出已测项（判定码非 0）。引脚按 pin_map 中该类型的顺序取；缺映射时用 `p<初级>-<序>` 占位。"""
    pin_map = pin_map or {}
    rows: list[str] = []
    counters: dict[str, int] = {}
    pmax = parsed["pmax"]
    for t in VAL_ORDER:
        for i in range(pmax * 10):
            j = parsed["judges"][t][i]
            if j == 0:
                continue
            idx = counters.get(t, 0)
            counters[t] = idx + 1
            pins_list = pin_map.get(t) or []
            pins = pins_list[idx] if idx < len(pins_list) else f"p{i // 10 + 1}-{i % 10 + 1}"
            v = parsed["vals"][t][i]
            res = "Pass" if j == 1 else "Fail"
            rows.append(f"1,{t},'{pins},{v:+.6e},0.000000e+00,0.000000e+00,{res}")
    return ";".join(rows)


class UC2910Instrument(BaseInstrument):
    IDN_SIGNATURE = "2910"  # IDN 回复须含此子串；拿到真机后按实际 *IDN? 输出修正

    def __init__(self, port: str, baudrate: int = 115200):
        self._conn = SerialConn(port, baudrate)
        self._pin_map: dict[str, list[str]] = {}

    def connect(self) -> bool:
        return self._conn.connect()

    def disconnect(self):
        self._conn.disconnect()

    @property
    def connected(self) -> bool:
        return self._conn.connected

    def idn(self) -> str:
        self._conn.clear()
        self._conn.send("*IDN?")
        resp = self._conn.recv(timeout=2.0)
        return resp.decode("ascii", errors="replace").strip()

    def set_pin_map(self, pin_map: dict[str, list[str]]):
        """{测试类型: [引脚, ...]}，顺序须与仪器设置文件内该项目的扫描顺序一致。"""
        self._pin_map = {k: list(v) for k, v in (pin_map or {}).items()}

    def load_config(self, config_id: int) -> bytes:
        # 2910 的设置文件需在仪器面板载入（暂无已验证的远程载入指令）。
        # 返回占位使初始化流程继续；后续拿到 SCPI 指令集可替换为真实现。
        return b"__PANEL_CONFIG__"

    def _read_packet(self, timeout: float = 20.0) -> bytes:
        """按长度规则收包（二进制含 0x0A，不能按结束符切）。"""
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self._conn.recv(timeout=1.0)
            if chunk:
                buf += chunk
            start = buf.find(b"#\x00")
            if start >= 0:
                body = len(buf) - start
                if body >= 42 and (body - 42) % BYTES_PER_PMAX == 0:
                    return buf[start:]
            if not chunk and buf:
                # 静默一轮仍未对齐，再等下一轮；超时由外层控制
                continue
        return buf

    def run_test(self) -> tuple[bool, str]:
        self._conn.clear()
        self._conn.send("TRIG;:FETCh?")
        raw = self._read_packet(timeout=20.0)
        if not raw:
            return False, "__NO_CSV__"
        try:
            parsed = parse_packet(raw)
        except ValueError:
            return False, "__NO_CSV__"
        csv = to_csv(parsed, self._pin_map)
        if not csv:
            return False, "__NO_CSV__"
        return True, csv
