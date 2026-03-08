"""
完全复刻原来的读取方式，只改波特率 115200
idle_ms=3000，等待设备主动推送
"""
import serial, threading, queue, time

PORT, BAUD = 'COM4', 115200
IDLE_MS = 3000  # 和原代码一样

rx_buf = bytearray()
rx_q = queue.Queue()
last_rx = [time.time()]
stop = threading.Event()

def rx_loop(ser):
    while not stop.is_set():
        data = ser.read(4096)
        if data:
            rx_buf.extend(data)
            last_rx[0] = time.time()
            print(f'  RX: +{len(data)} bytes (total: {len(rx_buf)})')
        else:
            if rx_buf and (time.time() - last_rx[0]) * 1000 >= IDLE_MS:
                pkt = bytes(rx_buf)
                rx_buf.clear()
                rx_q.put(pkt)
                print(f'  封包: {len(pkt)} bytes')
            time.sleep(0.005)

ser = serial.Serial(PORT, BAUD, timeout=0.05)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.3)

# 1. 加载配置
print('[1] 加载 mmem:load:trs 2 ...')
ser.write(b'mmem:load:trs 2\r\n')
pkt = rx_q.get(timeout=15)
print(f'配置文件: {len(pkt)} 字节\n')

# 清空
while not rx_q.empty(): rx_q.get_nowait()
rx_buf.clear()

# 2. 触发
print('[2] 触发 *TRG ...')
ser.write(b'*TRG\r\n')
time.sleep(0.05)

# 3. 等待 OPC
print('[3] 等待完成 ...')
t0 = time.time()
while True:
    time.sleep(0.3)
    ser.write(b'*OPC?\r\n')
    time.sleep(0.05)
    try:
        p = rx_q.get(timeout=0.8)
        if b'1' in p:
            print(f'完成！耗时 {time.time()-t0:.1f}s\n')
            rx_buf.clear()
            break
    except queue.Empty:
        pass
    if time.time()-t0 > 30:
        print('超时'); break

# 等设备主动推送（原代码的方案A）
print('[4A] 等待设备主动推送数据（5秒）...')
while not rx_q.empty(): rx_q.get_nowait()
rx_buf.clear()

try:
    pkt = rx_q.get(timeout=5.0)
    print(f'主动推送: {len(pkt)} 字节')
    print(f'前30字节 hex: {pkt[:30].hex()}')
    printable = sum(32 <= b <= 126 for b in pkt) / len(pkt)
    print(f'可打印字符比例: {printable:.1%}')
    if b';' in pkt:
        print('包含分号 → CSV 格式！')
        print(f'内容前500字符:\n{pkt[:500].decode("ascii", errors="replace")}')
except queue.Empty:
    print('无主动推送')

# 方案B：主动查询 TRS:DATA?
print('\n[4B] 主动查询 TRS:DATA? ...')
rx_buf.clear()
while not rx_q.empty(): rx_q.get_nowait()
ser.write(b'TRS:DATA?\r\n')
time.sleep(0.05)

try:
    pkt = rx_q.get(timeout=10.0)
    print(f'TRS:DATA? 收到: {len(pkt)} 字节')
    print(f'前30字节 hex: {pkt[:30].hex()}')
    printable = sum(32 <= b <= 126 for b in pkt) / len(pkt)
    print(f'可打印字符比例: {printable:.1%}')
    if b';' in pkt:
        print('包含分号 → CSV 格式！')
        print(f'内容前500字符:\n{pkt[:500].decode("ascii", errors="replace")}')
    elif pkt[:2] == b'#\x01':
        print('二进制格式 (#\\x01 开头)')
except queue.Empty:
    print('TRS:DATA? 超时')

stop.set()
ser.close()
