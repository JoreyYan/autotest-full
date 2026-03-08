import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

PORT, BAUD = 'COM4', 115200

collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
collector.start()
time.sleep(0.5)
collector.clear_queue()

# 初始化：加载配置
print('[初始化] mmem:load:trs 2 ...')
collector.send('mmem:load:trs 2', ending='\r\n')
time.sleep(2.0)
collector.clear_queue()
print('    OK\n')

# 测试
print('[测试] 发送 *TRG ...')
t0 = time.time()
collector.send('*TRG', ending='\r\n')

# 第1包: !
pkt1 = collector.recv_packet(timeout=3.0)
print(f'    第1包: {repr(pkt1)} ({time.time()-t0:.2f}s)')

# 第2包: CSV
pkt2 = collector.recv_packet(timeout=10.0)
print(f'    第2包: {len(pkt2)} 字节 ({time.time()-t0:.2f}s)')
print()

# 解析
text = pkt2.decode('ascii', errors='replace')
records = []
for seg in text.split(';'):
    seg = seg.strip().lstrip('!')
    parts = seg.split(',')
    if len(parts) >= 7:
        try:
            records.append({
                'type': parts[1], 'pins': parts[2].lstrip("'"),
                'value': float(parts[3]), 'result': parts[6].strip()
            })
        except: pass

print(f'解析到 {len(records)} 条记录:')
print(f'{"类型":<6} {"引脚":<8} {"测量值":<20} {"结果"}')
print('-'*45)
for r in records:
    t, v = r['type'], r['value']
    if t in ('Lx','Lk'):   disp = f'{v*1000:.4f} mH'
    elif t == 'Dcr':       disp = f'{v:.5f} Ohm'
    elif t == 'Cx':        disp = f'{v*1e12:.2f} pF'
    else:                  disp = f'{v:.6f}'
    print(f'{t:<6} {r["pins"]:<8} {disp:<20} {r["result"]}')

passed = sum(1 for r in records if r['result'] == 'Pass')
print(f'\n通过: {passed}/{len(records)}')

collector.close()
