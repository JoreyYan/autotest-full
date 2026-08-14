from __future__ import annotations

from .base_instrument import BaseInstrument
from .serial_conn import SerialConn


class UCEInstrument(BaseInstrument):
    IDN_SIGNATURE = "YouCe Electronics,UC2866XB"

    def __init__(self, port: str, baudrate: int = 115200):
        self._conn = SerialConn(port, baudrate)

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

    def load_config(self, config_id: int) -> bytes:
        self._conn.clear()
        self._conn.send(f"mmem:load:trs {config_id}")
        return self._conn.recv(timeout=5.0)

    def trigger(self) -> bool:
        self._conn.clear()
        self._conn.send("*TRG")
        ack = self._conn.recv(timeout=3.0)
        # 部分固件在确认字节 "!" 后会多发 1 个尾字节（实测 0x9F），只认开头
        return bool(ack) and ack.startswith(b"!")

    def recv_csv(self, timeout: float = 10.0) -> str:
        raw = self._conn.recv(timeout=timeout)
        if not raw:
            return ""
        text = raw.decode("ascii", errors="replace")
        return text.lstrip("!")

    def run_test(self) -> tuple[bool, str]:
        # 两种固件行为：
        #   旧固件：先回单独确认字节 "!"，约 1.7s 后另发一包 CSV
        #   新固件（如 Ver 1.0.0/T5-526-10756）：一次性回 "!" + CSV + 0x9F 结束标记
        self._conn.clear()
        self._conn.send("*TRG")
        first = self._conn.recv(timeout=3.0)
        if not first or not first.startswith(b"!"):
            return False, "__NO_ACK__"
        raw = first[1:]
        if not raw.strip(b"\x9f\r\n \t"):
            # 首包只有确认字节（旧固件路径）：CSV 在后续包
            csv = self.recv_csv(timeout=10.0)
            if not csv:
                return False, "__NO_CSV__"
            return True, csv
        # 首包已带数据（新固件路径）：0x9F 尾标记未到就继续收
        while not raw.rstrip(b"\r\n \t").endswith(b"\x9f"):
            more = self._conn.recv(timeout=10.0)
            if not more:
                break
            raw += more
        text = raw.strip(b"\x9f\r\n \t").decode("ascii", errors="replace").strip()
        if not text:
            return False, "__NO_CSV__"
        return True, text
