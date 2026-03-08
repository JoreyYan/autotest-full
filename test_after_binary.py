"""
TRS:DATA? 之后是否还有 CSV 文本跟着？
收集所有返回数据不截断
"""
import serial, threading, queue, time

PORT, BAUD = 'COM4', 115200

buf = bytearray()
rx_q = queue.Queue()
last_rx = [0.0]
stop = threading.Event()
all_data_after_trs = bytearray()
capture_mode = [False]
t_start = [0.0]

def rx_loop(ser):
    while not stop.is_set():
        data = ser.read(4096)
        if data:
            buf.extend(data)
            last_rx[0] = time.monotonic()
            if capture_mode[0]:
                all_data_after_trs.extend(data)
                ts = time.time() - t_start[0]
                print(f'  [{ts:.2f}s] +{len(data)} bytes  total={len(all_data_after_trs)}  preview={data[:20].hex()}')
        else:
            if buf and (time.monotonic() - last_rx[0]) * 1000 >= 300:
                rx_q.put(bytes(buf))
                buf.clear()
        time.sleep(0.005)

ser = serial.Serial(PORT, BAUD, timeout=0.05)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.2)

# 加载配置
print('[1] 加载配置...')
ser.write(b'mmem:load:trs 2\r\n')
rx_q.get(timeout=10)
print('    OK')

# 触发测试
print('[2] 触发 *TRG ...')
ser.write(b'*TRG\r\n')

# 等完成
print('[3] 等待完成...')
t0 = time.time()
while True:
    time.sleep(0.3)
    ser.write(b'*OPC?\r\n')
    try:
        p = rx_q.get(timeout=1)
        if b'1' in p:
            print(f'    完成 ({time.time()-t0:.1f}s)')
            break
    except queue.Empty:
        pass
    if time.time()-t0 > 30:
        print('    超时'); break

# 清空残留
time.sleep(0.2)
while not rx_q.empty(): rx_q.get_nowait()
buf.clear()

# 开启原始捕获模式，监听 5 秒内所有数据
print('\n[4] 发送 TRS:DATA?，监听 5 秒内所有返回数据...')
capture_mode[0] = True
t_start[0] = time.time()
ser.write(b'TRS:DATA?\r\n')
time.sleep(5.0)
capture_mode[0] = False

stop.set()
ser.close()

# 分析
total = all_data_after_trs
print(f'\n共捕获: {len(total)} 字节')
print(f'前30字节: {total[:30].hex()}')

# 有没有分号（CSV标志）
if b';' in total:
    idx = total.index(b';')
    print(f'\n发现分号！位置: {idx}')
    print(f'分号周围: {total[max(0,idx-50):idx+50]}')
    # 找CSV起始位置
    for i in range(max(0, idx-200), idx):
        if total[i:i+2].decode('ascii', errors='replace').isprintable():
            pass
else:
    print('\n没有分号 → 确认是纯二进制，无CSV文本跟随')

# 显示后半部分（二进制块之后）
if len(total) > 1733:
    rest = total[1733:]
    print(f'\n1733字节之后还有 {len(rest)} 字节:')
    print(f'hex: {rest[:100].hex()}')
    try:
        print(f'text: {rest[:200].decode("ascii", errors="replace")}')
    except: pass
