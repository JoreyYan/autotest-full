import serial, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ser = serial.Serial('COM4', 9600, timeout=0.2)
time.sleep(0.5)
ser.reset_input_buffer()

# IDN
ser.write(b'*IDN?\r\n')
time.sleep(0.5)
print(f'IDN: {ser.read(ser.in_waiting).decode("ascii", errors="replace").strip()}')

# 加载配置 - 只等 2 秒，不等完整11264字节
print('\n加载配置 (等2秒)...')
ser.reset_input_buffer()
ser.write(b'mmem:load:trs 2\r\n')
time.sleep(2.0)
n = ser.in_waiting
junk = ser.read(n)
print(f'清空缓冲区: {len(junk)} 字节')

# 不再等待，直接触发
time.sleep(0.2)
ser.reset_input_buffer()

print('\n发送 *TRG...')
ser.write(b'*TRG\r\n')
t0 = time.time()

print('监听 10 秒...')
all_data = bytearray()
while time.time() - t0 < 10:
    if ser.in_waiting:
        chunk = ser.read(ser.in_waiting)
        all_data += chunk
        ts = time.time() - t0
        print(f'  [{ts:.2f}s] +{len(chunk)}B  hex:{chunk[:20].hex()}')
    time.sleep(0.05)

print(f'\n共收到: {len(all_data)} 字节')
if all_data:
    print(f'前100hex: {all_data[:100].hex()}')
    printable = sum(32<=b<=126 for b in all_data)/len(all_data)
    print(f'可打印: {printable:.1%}')
    if b';' in all_data:
        print('有分号 → CSV!')
        print(all_data.decode('ascii', errors='replace')[:400])

ser.close()
