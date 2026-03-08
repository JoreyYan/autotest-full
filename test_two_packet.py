import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

collector = SerialCollector(port='COM4', baudrate=9600, idle_ms=300)
collector.start()
time.sleep(0.5)

# IDN 确认通讯
collector.clear_queue()
collector.send('*IDN?', ending='\r\n')
try:
    p = collector.recv_packet(timeout=3.0)
    print(f'IDN: {p.decode("ascii", errors="replace").strip()}')
except queue.Empty:
    print('IDN 无响应！')
    collector.close()
    exit()

# 加载配置
print('\n加载配置 mmem:load:trs 2...')
collector.clear_queue()
collector.send('mmem:load:trs 2', ending='\r\n')
time.sleep(15.0)
discarded = 0
while True:
    try:
        d = collector.recv_packet(timeout=1.0)
        discarded += len(d)
    except queue.Empty:
        break
print(f'丢弃配置数据: {discarded} 字节')

# 稳定等待
time.sleep(2.0)
collector.clear_queue()

# 触发
print('\n发送 *TRG...')
t0 = time.time()
collector.send('*TRG', ending='\r\n')

# 第1包: ack
print('等待第1包 (ack, 5秒)...')
try:
    ack = collector.recv_packet(timeout=5.0)
    print(f'第1包: {repr(ack)} ({len(ack)}字节) 耗时{time.time()-t0:.1f}s')
except queue.Empty:
    print('第1包超时！')
    collector.close()
    exit()

# 第2包: CSV
print('等待第2包 (CSV, 60秒)...')
try:
    csv_data = collector.recv_packet(timeout=60.0)
    elapsed = time.time() - t0
    print(f'第2包: {len(csv_data)}字节 耗时{elapsed:.1f}s')
    print(f'前50hex: {csv_data[:50].hex()}')
    printable = sum(32 <= b <= 126 for b in csv_data) / len(csv_data)
    print(f'可打印: {printable:.1%}')
    if b';' in csv_data:
        print('CSV格式！')
        text = csv_data.decode('ascii', errors='replace')
        for r in text.split(';')[:3]:
            if r.strip():
                print(' ', r.strip())
    else:
        print('非CSV')
except queue.Empty:
    print('第2包超时！')

collector.close()
