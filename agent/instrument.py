"""
instrument.py — 仪器指令层
职责：封装对仪器的所有操作，不关心业务逻辑
"""
from .serial_conn import SerialConn
import time


class Instrument:

    def __init__(self, port: str, baudrate: int = 115200):
        self._conn = SerialConn(port, baudrate)

    # ── 连接 / 断开 ──────────────────────────────────────────────

    def connect(self) -> bool:
        return self._conn.connect()

    def disconnect(self):
        self._conn.disconnect()

    @property
    def connected(self) -> bool:
        return self._conn.connected

    # ── 基础指令 ─────────────────────────────────────────────────

    def idn(self) -> str:
        """查询设备身份，返回字符串"""
        self._conn.clear()
        self._conn.send('*IDN?')
        resp = self._conn.recv(timeout=2.0)
        return resp.decode('ascii', errors='replace').strip()

    # ── 配置加载 ─────────────────────────────────────────────────

    def load_config(self, config_id: int) -> bytes:
        """
        加载仪器配置文件 N。
        仪器会返回 11264 字节配置数据（等收完，调用方可丢弃）。
        """
        self._conn.clear()
        self._conn.send(f'mmem:load:trs {config_id}')
        data = self._conn.recv(timeout=5.0)
        return data   # 调用方决定是否解析

    # ── 触发测试 ─────────────────────────────────────────────────

    def trigger(self) -> bool:
        """
        发送 *TRG，等待确认字节 '!'。
        返回 True 表示仪器已确认开始测试。
        """
        self._conn.clear()
        self._conn.send('*TRG')
        ack = self._conn.recv(timeout=3.0)
        return ack == b'!'

    def recv_csv(self, timeout: float = 10.0) -> str:
        """
        等待仪器推送的 CSV 测试数据（触发后调用）。
        返回解码后的文本，已去掉首字符 '!'。
        """
        raw = self._conn.recv(timeout=timeout)
        if not raw:
            return ''
        text = raw.decode('ascii', errors='replace')
        # 去掉第一条记录前的 '!'
        return text.lstrip('!')

    # ── 完整测试（触发 + 等待两包）────────────────────────────────

    def run_test(self) -> tuple[bool, str]:
        """
        触发一次完整测试，返回 (成功, csv文本)。
        成功: trigger确认 且 收到CSV数据
        """
        if not self.trigger():
            return False, ''
        csv = self.recv_csv(timeout=10.0)
        return bool(csv), csv
