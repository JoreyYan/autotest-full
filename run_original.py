"""
完全复刻 direct_test_v5.py 的逻辑，只改端口和波特率
"""
import serial, threading, queue, time

PORT, BAUD = 'COM4', 115200
IDLE_MS = 300

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
        else:
            if rx_buf and (time.monotonic() - last_rx[0]) * 1000 >= IDLE_MS:
                rx_q.put(bytes(rx_buf))
                rx_buf.clear()
        time.sleep(0.005)

def send(cmd):
    ser.write((cmd + '\r\n').encode('ascii'))
    time.sleep(0.05)

def clear():
    rx_buf.clear()
    while not rx_q.empty():
        rx_q.get_nowait()

ser = serial.Serial(PORT, BAUD, timeout=0.05)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.5)

print('='*60)
print('复刻 direct_test_v5.py')
print('='*60)

# 步骤1: 清空缓冲区
print('\n1. 清空缓冲区...')
time.sleep(1.0)
clear()
print('   OK')

# 步骤2: 加载配置
print('\n2. 加载 mmem:load:trs 2 ...')
send('mmem:load:trs 2')
time.sleep(2.0)
clear()
print('   OK')

# 步骤3: 触发测试，然后等待自动推送（不发任何命令）
print('\n3. 触发 *TRG，等待自动推送（60秒超时）...')
start = time.time()
send('*TRG')

# 持续接收所有包，直到 15 秒无新包
all_pkts = []
while True:
    try:
        pkt = rx_q.get(timeout=15.0)
        elapsed = time.time() - start
        printable = sum(32 <= b <= 126 for b in pkt) / len(pkt)
        print(f'   包{len(all_pkts)+1}: {len(pkt)}B  可打印:{printable:.0%}  {elapsed:.1f}s  hex:{pkt[:12].hex()}')
        all_pkts.append(pkt)

        # 检查是否是 CSV
        if b';' in pkt and b',' in pkt:
            print('   → 发现 CSV！')
            break
        # 如果只是 ! 继续等
    except queue.Empty:
        print('   15秒无新数据，结束')
        break

stop.set()
ser.close()

# 分析结果
print()
if not all_pkts:
    print('没有收到任何数据')
else:
    for i, pkt in enumerate(all_pkts):
        if b';' in pkt and b',' in pkt:
            print(f'包{i+1} 是 CSV 格式:')
            text = pkt.decode('ascii', errors='replace')
            # 找第一个数字开头的位置
            for j, c in enumerate(text):
                if c.isdigit():
                    print(text[j:j+600])
                    break
        else:
            print(f'包{i+1}: {len(pkt)}字节, hex={pkt[:20].hex()}')
