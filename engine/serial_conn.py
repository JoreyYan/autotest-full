"""
第一层：串口连接
职责：建立/断开连接，后台线程持续读取，按空闲超时封包
"""
import serial
import threading
import queue
import time


class SerialConn:
    IDLE_MS = 200  # 连续多少ms无新数据视为一包结束

    def __init__(self, port: str, baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self._ser: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._buf = bytearray()
        self._last_rx = 0.0
        self.rx_queue: queue.Queue[bytes] = queue.Queue()

    # ── 连接 / 断开 ──────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(
                self.port, self.baudrate,
                bytesize=8, parity='N', stopbits=1,
                timeout=0.05, write_timeout=2
            )
            self._stop.clear()
            self._thread = threading.Thread(target=self._rx_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f"[串口] 连接失败: {e}")
            return False

    def disconnect(self):
        self._stop.set()
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ── 发送 ─────────────────────────────────────────────────────

    def send(self, cmd: str):
        """发送 ASCII 指令，自动加 CRLF"""
        if not self.connected:
            raise RuntimeError("串口未连接")
        self._ser.write((cmd + '\r\n').encode('ascii'))

    # ── 接收 ─────────────────────────────────────────────────────

    def recv(self, timeout: float = 5.0) -> bytes:
        """阻塞等待下一个完整数据包"""
        try:
            return self.rx_queue.get(timeout=timeout)
        except queue.Empty:
            return b''

    def clear(self):
        """清空接收队列"""
        while not self.rx_queue.empty():
            try:
                self.rx_queue.get_nowait()
            except queue.Empty:
                break

    # ── 后台读取线程 ──────────────────────────────────────────────

    def _rx_loop(self):
        while not self._stop.is_set():
            try:
                data = self._ser.read(4096)
            except Exception:
                break

            if data:
                self._buf.extend(data)
                self._last_rx = time.monotonic()
            else:
                # 无新数据，检查是否超时封包
                if self._buf and (time.monotonic() - self._last_rx) * 1000 >= self.IDLE_MS:
                    self.rx_queue.put(bytes(self._buf))
                    self._buf.clear()
