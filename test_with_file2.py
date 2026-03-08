import serial, threading, queue, time

PORT, BAUD = 'COM4', 115200
rx_buf = bytearray()
rx_q = queue.Queue()
last_rx = [0.0]
stop = threading.Event()

def rx_loop(ser):
    while not stop.is_set():
        try: data = ser.read(4096)
        except: break
        if data:
            rx_buf.extend(data)
            last_rx[0] = time.monotonic()
        else:
            if rx_buf and (time.monotonic() - last_rx[0]) * 1000 >= 300:
                rx_q.put(bytes(rx_buf))
                rx_buf.clear()

ser = serial.Serial(PORT, BAUD, timeout=0.05)
threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
time.sleep(0.2)

# 1. 加载文件2
print('[1] 加载 mmem:load:trs 2 ...')
ser.write(b'mmem:load:trs 2\r\n')
pkt = rx_q.get(timeout=10)
print(f'    配置文件: {len(pkt)} 字节 OK')
time.sleep(0.1)

# 2. 触发测试
print('[2] 触发 *TRG ...')
ser.write(b'*TRG\r\n')

# 3. 等待完成
print('[3] 等待完成...')
t0 = time.time()
while True:
    time.sleep(0.3)
    ser.write(b'*OPC?\r\n')
    try:
        pkt = rx_q.get(timeout=1)
        if b'1' in pkt:
            print(f'    完成！耗时 {time.time()-t0:.1f}s')
            break
    except queue.Empty:
        pass
    if time.time() - t0 > 30:
        print('    超时！')
        stop.set(); ser.close(); exit()

# 4. 清空残留
time.sleep(0.2)
while not rx_q.empty(): rx_q.get_nowait()

# 5. 读取结果
print('[4] 读取 TRS:DATA? ...')
ser.write(b'TRS:DATA?\r\n')
pkt = rx_q.get(timeout=10)
print(f'    收到: {len(pkt)} 字节')
print(f'    前100字节hex: {pkt[:100].hex()}')
print()

# 尝试作为文本解析
text = pkt.decode('ascii', errors='replace')
print('--- 原始文本 (前500字符) ---')
print(text[:500])
print()

# 找分号分隔的CSV记录
records = []
for seg in text.split(';'):
    seg = seg.strip()
    if not seg:
        continue
    parts = seg.split(',')
    if len(parts) >= 7:
        try:
            r = {
                'type': parts[1],
                'pins': parts[2].lstrip("'"),
                'val':  float(parts[3]),
                'lo':   float(parts[4]),
                'hi':   float(parts[5]),
                'result': parts[6].strip()
            }
            records.append(r)
        except:
            pass

if records:
    print(f'=== 解析到 {len(records)} 条记录 ===')
    print(f'{"类型":<6} {"引脚":<8} {"测量值":<20} {"结果"}')
    print('-' * 45)
    for r in records:
        t, v = r['type'], r['val']
        if t in ('Lx', 'Lk'):   disp = f'{v*1000:.4f} mH'
        elif t == 'Dcr':        disp = f'{v:.5f} Ohm'
        elif t == 'Cx':         disp = f'{v*1e12:.2f} pF'
        else:                   disp = f'{v:.6f}'
        print(f'{t:<6} {r["pins"]:<8} {disp:<20} {r["result"]}')
else:
    print('未解析到CSV记录，数据可能是二进制格式')

stop.set()
ser.close()
