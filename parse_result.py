import serial, threading, queue, time, struct, json

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

# 加载文件2 + 触发 + 等完成
ser.write(b'mmem:load:trs 2\r\n')
rx_q.get(timeout=10)
print('配置 OK')

ser.write(b'*TRG\r\n')
t0 = time.time()
while True:
    time.sleep(0.3)
    ser.write(b'*OPC?\r\n')
    try:
        p = rx_q.get(timeout=1)
        if b'1' in p:
            print(f'测试完成 ({time.time()-t0:.1f}s)')
            break
    except queue.Empty:
        pass

time.sleep(0.2)
while not rx_q.empty(): rx_q.get_nowait()

# 读结果
ser.write(b'TRS:DATA?\r\n')
pkt = rx_q.get(timeout=10)
stop.set(); ser.close()

# 找 #\x01 提取 payload
idx = pkt.index(b'#')
payload = pkt[idx+2:]
print(f'Payload: {len(payload)} 字节')
print()

def f(off):
    if off+4 > len(payload): return None
    return struct.unpack('<f', payload[off:off+4])[0]

# 按 DATA_OFFSET_MAP.md 解析
print('=== 测量结果 ===')
print()

print('【匝比 Turns】')
print(f'  N1参考值:    {f(0x0008):.6f}')
print(f'  N1:N2 = {f(0x000C):.6f}')
print(f'  N1:N3 = {f(0x0010):.6f}')
print(f'  N1:N4 = {f(0x0014):.6f}')
print(f'  N1:N5 = {f(0x0018):.6f}')
print(f'  N1:N6 = {f(0x001C):.6f}')
print()

print('【电感 Lx (mH)】')
for i, name in enumerate(['Ls1(3-1)','Ls2(4-5)','Ls3(6-7)','Ls4(8-10)','Ls5(13-12)','Ls6(14-13)']):
    v = f(0x00A8 + i*4)
    print(f'  {name}: {v*1000:.4f} mH' if v else f'  {name}: 0')
print()

print('【漏感 Lk (mH)】')
print(f'  Lk: {f(0x0148)*1000:.4f} mH')
print()

print('【电容 Cx (pF)】')
for i, name in enumerate(['Cx1(1-12)','Cx2(4-8)','Cx3(6-8)']):
    v = f(0x01E8 + i*4)
    print(f'  {name}: {v*1e12:.2f} pF' if v else f'  {name}: 0')
print()

print('【直流电阻 DCR (Ohm)】')
for i, name in enumerate(['DCR1(3-1)','DCR2(4-5)','DCR3(6-7)','DCR4(8-10)','DCR5(13-12)','DCR6(14-13)']):
    v = f(0x0288 + i*4)
    print(f'  {name}: {v:.5f} Ohm' if v else f'  {name}: 0')
print()

print('【品质因数 Q】')
for i, name in enumerate(['Q1(3-1)','Q2(4-5)','Q3(6-7)','Q4(8-10)','Q5(13-12)','Q6(14-13)']):
    v = f(0x0328 + i*4)
    print(f'  {name}: {v:.2f}' if v else f'  {name}: 0')
