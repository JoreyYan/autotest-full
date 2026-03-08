"""
*TRG 之后持续收包，不截断，等所有数据
"""
import serial, threading, queue, time

PORT, BAUD = 'COM4', 115200

rx_buf = bytearray()
rx_q = queue.Queue()
last_rx = [0.0]
stop = threading.Event()

def rx_loop(ser):
    while not stop.is_set():
        data = ser.read(4096)
        if data:
            rx_buf.extend(data)
            last_rx[0] = time.monotonic()
            ts = time.time() - t_ref[0]
            printable = sum(32 <= b <= 126 for b in data) / len(data)
            print(f'  [{ts:.2f}s] +{len(data)}B 可打印:{printable:.0%}  hex:{data[:16].hex()}')
        else:
            if rx_buf and (time.monotonic() - last_rx[0]) * 1000 >= 300:
                rx_q.put(bytes(rx_buf))
                rx_buf.clear()
        time.sleep(0.005)

t_ref = [time.time()]
ser = serial.Serial(PORT, BAUD, timeout=0.05)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.3)

# 1. 加载配置
print('[1] 加载 mmem:load:trs 2 ...')
t_ref[0] = time.time()
ser.write(b'mmem:load:trs 2\r\n')
rx_q.get(timeout=10)
print('    OK\n')
time.sleep(0.2)
rx_buf.clear()
while not rx_q.empty(): rx_q.get_nowait()

# 2. 发 *TRG，持续收所有包，直到 10 秒没有新数据
print('[2] 发送 *TRG，收集所有返回数据（等待10秒无新数据结束）...\n')
t_ref[0] = time.time()
ser.write(b'*TRG\r\n')

all_packets = []
while True:
    try:
        pkt = rx_q.get(timeout=10.0)  # 10秒等下一包
        all_packets.append(pkt)
        print(f'  -> 收到第 {len(all_packets)} 包: {len(pkt)} 字节')
    except queue.Empty:
        print('  -> 10秒无新数据，结束\n')
        break

stop.set()
ser.close()

# 分析所有收到的数据
print(f'共收到 {len(all_packets)} 个数据包')
combined = b''.join(all_packets)
print(f'合计: {len(combined)} 字节\n')

for i, pkt in enumerate(all_packets):
    printable = sum(32 <= b <= 126 for b in pkt) / len(pkt) if pkt else 0
    has_semi = b';' in pkt
    print(f'包{i+1}: {len(pkt)}字节  可打印:{printable:.0%}  分号:{has_semi}  hex前20:{pkt[:20].hex()}')
    if has_semi:
        text = pkt.decode('ascii', errors='replace')
        for j, c in enumerate(text):
            if c.isdigit():
                print(f'  CSV内容:\n{text[j:j+400]}')
                break
