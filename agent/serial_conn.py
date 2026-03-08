"""
serial_conn.py — 串口连接层
职责：连接/断开、后台持续读取、300ms空闲封包入队
"""
import serial
import serial.tools.list_ports
import threading
import queue
import time


IDLE_MS = 300        # 多少ms无新数据视为一包结束
READ_CHUNK = 4096    # 每次读取字节数
READ_TIMEOUT = 0.05  # serial read超时（秒）
UC2866_IDN = 'YouCe Electronics,UC2866XB'


class SerialConn:

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
                timeout=READ_TIMEOUT,
                xonxoff=False, rtscts=False, dsrdtr=False
            )
            self._stop.clear()
            self._thread = threading.Thread(target=self._rx_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f'[串口] 连接失败 {self.port}: {e}')
            return False

    def disconnect(self):
        self._stop.set()
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def connected(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    # ── 发送 ─────────────────────────────────────────────────────

    def send(self, cmd: str):
        if not self.connected:
            raise RuntimeError('串口未连接')
        self._ser.write((cmd + '\r\n').encode('ascii'))

    # ── 接收 ─────────────────────────────────────────────────────

    def recv(self, timeout: float = 5.0) -> bytes:
        """阻塞等待下一个完整数据包，超时返回 b''"""
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
                data = self._ser.read(READ_CHUNK)
            except Exception:
                break
            if data:
                self._buf.extend(data)
                self._last_rx = time.monotonic()
            else:
                if self._buf and (time.monotonic() - self._last_rx) * 1000 >= IDLE_MS:
                    self.rx_queue.put(bytes(self._buf))
                    self._buf.clear()


# ── 自动扫描找仪器 ────────────────────────────────────────────────

def find_instrument(baudrate: int = 115200, preferred_port: str = None) -> str | None:
    """
    扫描所有 COM 口，发 *IDN? 找 UC2866XB。
    优先检查 preferred_port（上次用的端口）。
    返回找到的端口号，找不到返回 None。
    """
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        return None

    # 优先检查上次用的端口
    if preferred_port and preferred_port in ports:
        ports = [preferred_port] + [p for p in ports if p != preferred_port]

    for port in ports:
        try:
            conn = SerialConn(port, baudrate)
            if not conn.connect():
                continue
            conn.send('*IDN?')
            resp = conn.recv(timeout=1.5)
            conn.disconnect()
            if resp and UC2866_IDN.encode() in resp:
                return port
        except Exception:
            pass
    return None
