import serial, threading, queue, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PORT, BAUD, IDLE_MS = 'COM4', 9600, 300

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

ser = serial.Serial(PORT, BAUD, timeout=0.05,
                    bytesize=8, parity='N', stopbits=1,
                    xonxoff=False, rtscts=False, dsrdtr=False)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.5)

# 1. IDN
send('*IDN?')
pkt = rx_q.get(timeout=3)
print(f'[IDN] {pkt.decode("ascii", errors="replace").strip()}\n')

# 2. 加载配置
print('[1] 加载 mmem:load:trs 2 ...')
t0 = time.time()
send('mmem:load:trs 2')
pkt = rx_q.get(timeout=20)
print(f'    配置文件: {len(pkt)} 字节，耗时 {time.time()-t0:.1f}s')
time.sleep(0.5)
clear()

# 3. 触发测试
print('\n[2] 触发 *TRG ...')
send('*TRG')
try:
    pkt = rx_q.get(timeout=2)
    print(f'    仪器回: {pkt} ({pkt.hex()})')
except queue.Empty:
    print('    (无立即响应)')

# 4. 等待 OPC
print('\n[3] 等待 *OPC? ...')
t0 = time.time()
clear()
while True:
    time.sleep(0.3)
    send('*OPC?')
    try:
        p = rx_q.get(timeout=0.8)
        if b'1' in p:
            print(f'    完成！耗时 {time.time()-t0:.1f}s')
            break
    except queue.Empty:
        pass
    if time.time()-t0 > 30:
        print('    超时'); break

# 5. 清空残留
time.sleep(0.5)
clear()

# 6. 读结果
print('\n[4] 发送 TRS:DATA? ...')
t0 = time.time()
send('TRS:DATA?')
pkt = rx_q.get(timeout=10)
print(f'    收到: {len(pkt)} 字节，耗时 {time.time()-t0:.1f}s')
print(f'    前50字节hex: {pkt[:50].hex()}')
printable = sum(32 <= b <= 126 for b in pkt) / len(pkt)
print(f'    可打印比例: {printable:.1%}')

stop.set()
ser.close()

# 7. 解析
print()
if b';' in pkt and b',' in pkt:
    print('CSV 格式！解析中...')
    text = pkt.decode('ascii', errors='replace')
    # 截到第一个非打印字符
    clean = ''
    for c in text:
        if ord(c) < 32 and c not in '\r\n\t;,':
            break
        clean += c

    records = []
    for seg in clean.split(';'):
        seg = seg.strip()
        if not seg: continue
        parts = seg.split(',')
        if len(parts) >= 7:
            try:
                records.append({
                    'type': parts[1],
                    'pins': parts[2].lstrip("'"),
                    'val': float(parts[3]),
                    'result': parts[6].strip()
                })
            except: pass

    print(f'\n共 {len(records)} 条记录:')
    print(f'{"类型":<6} {"引脚":<8} {"测量值":<20} {"结果"}')
    print('-'*45)
    for r in records:
        t, v = r['type'], r['val']
        if t in ('Lx','Lk'):   disp = f'{v*1000:.4f} mH'
        elif t == 'Dcr':       disp = f'{v:.5f} Ohm'
        elif t == 'Cx':        disp = f'{v*1e12:.2f} pF'
        else:                  disp = f'{v:.6f}'
        print(f'{t:<6} {r["pins"]:<8} {disp:<20} {r["result"]}')
else:
    print(f'非CSV格式，前100字节: {pkt[:100]}')
