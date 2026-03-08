"""
测试仪器在 115200 bps 下测试完成后是否主动推送 CSV 数据
"""
import serial, threading, queue, time

PORT, BAUD = 'COM4', 115200

rx_buf = bytearray()
rx_q = queue.Queue()
last_rx = [0.0]
stop = threading.Event()

# 捕获模式：normal=封包入队，capture=原始记录所有字节
mode = ['normal']
captured = bytearray()
cap_start = [0.0]

def rx_loop(ser):
    while not stop.is_set():
        data = ser.read(4096)
        if data:
            last_rx[0] = time.monotonic()
            if mode[0] == 'normal':
                rx_buf.extend(data)
            else:
                captured.extend(data)
                ts = time.time() - cap_start[0]
                printable = sum(32 <= b <= 126 for b in data) / len(data)
                print(f'  [{ts:.2f}s] +{len(data)}B 可打印:{printable:.0%} hex:{data[:20].hex()}')
        else:
            if mode[0] == 'normal' and rx_buf and (time.monotonic() - last_rx[0]) * 1000 >= 300:
                rx_q.put(bytes(rx_buf))
                rx_buf.clear()
        time.sleep(0.005)

ser = serial.Serial(PORT, BAUD, timeout=0.05)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.3)

def send(cmd):
    ser.write((cmd + '\r\n').encode('ascii'))

def recv(timeout=10):
    return rx_q.get(timeout=timeout)

def clear():
    rx_buf.clear()
    while not rx_q.empty():
        rx_q.get_nowait()

# 1. 加载配置
print('[1] 加载 mmem:load:trs 2 ...')
send('mmem:load:trs 2')
pkt = recv(timeout=10)
print(f'    配置: {len(pkt)} 字节 OK')

# 2. 触发
print('[2] 触发 *TRG ...')
send('*TRG')

# 3. 等待完成
print('[3] 等待 *OPC? ...')
t0 = time.time()
while True:
    time.sleep(0.3)
    send('*OPC?')
    try:
        p = recv(timeout=1)
        if b'1' in p:
            print(f'    测试完成！({time.time()-t0:.1f}s)')
            break
    except queue.Empty:
        pass
    if time.time() - t0 > 30:
        print('    超时'); stop.set(); ser.close(); exit()

# 清空 OPC 残留，切换到捕获模式
clear()
mode[0] = 'capture'
captured.clear()
cap_start[0] = time.time()

print('\n[4] 切换到原始捕获模式，等待 8 秒（什么都不发）...')
time.sleep(8.0)

stop.set()
ser.close()

# 分析结果
print(f'\n共捕获: {len(captured)} 字节')

if len(captured) == 0:
    print('仪器没有主动推送任何数据')
else:
    printable = sum(32 <= b <= 126 for b in captured) / len(captured)
    print(f'可打印字符比例: {printable:.1%}')
    print(f'前50字节 hex: {captured[:50].hex()}')

    if b';' in captured:
        idx = captured.index(b';')
        print(f'\n发现分号 → CSV 格式！')
        start = max(0, idx - 200)
        print(f'内容:\n{captured[start:start+500].decode("ascii", errors="replace")}')
    else:
        print('无分号 → 非 CSV 格式')
