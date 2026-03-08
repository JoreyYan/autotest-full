import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

PORT, BAUD = 'COM4', 115200

collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
collector.start()
time.sleep(0.3)
collector.clear_queue()

# 初始化：等配置文件传完，不用 sleep，直接 recv_packet
print('[初始化] mmem:load:trs 2 ...')
t0 = time.time()
collector.send('mmem:load:trs 2', ending='\r\n')
cfg = collector.recv_packet(timeout=5.0)   # 等传完，丢弃
print(f'    配置文件 {len(cfg)} 字节，耗时 {time.time()-t0:.2f}s\n')

# 测试（连续两次，验证第二次也正常）
for i in range(2):
    print(f'[第{i+1}次测试] *TRG ...')
    t0 = time.time()
    collector.send('*TRG', ending='\r\n')

    pkt1 = collector.recv_packet(timeout=3.0)
    pkt2 = collector.recv_packet(timeout=10.0)
    elapsed = time.time() - t0

    text = pkt2.decode('ascii', errors='replace')
    records = []
    for seg in text.split(';'):
        seg = seg.strip().lstrip('!')
        parts = seg.split(',')
        if len(parts) >= 7:
            try:
                records.append({'type': parts[1], 'result': parts[6].strip()})
            except: pass

    passed = sum(1 for r in records if r['result'] == 'Pass')
    print(f'    {len(records)} 条记录，通过 {passed}/{len(records)}，耗时 {elapsed:.2f}s\n')

    if i == 0:
        print('    等待5秒模拟换产品...')
        time.sleep(5)
        print()

collector.close()
