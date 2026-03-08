import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

collector = SerialCollector(port='COM4', baudrate=9600, idle_ms=300)
collector.start()
time.sleep(0.5)
collector.clear_queue()

print('发送 *TRG...')
t0 = time.time()
collector.send('*TRG', ending='\r\n')

# 第1包
pkt1 = collector.recv_packet(timeout=3.0)
t1 = time.time() - t0
print(f'第1包: {len(pkt1)}字节，{t1:.2f}s后到  内容={pkt1}')
print()

# 第2包
pkt2 = collector.recv_packet(timeout=10.0)
t2 = time.time() - t0
print(f'第2包: {len(pkt2)}字节，{t2:.2f}s后到')
print()

# 分析第2包
print('=== 原始数据分析 ===')
print(f'总字节数: {len(pkt2)}')
print(f'可打印字符: {sum(32<=b<=126 for b in pkt2)} 字节 ({sum(32<=b<=126 for b in pkt2)/len(pkt2)*100:.1f}%)')
print(f'分号数量: {pkt2.count(b";")}')
print(f'逗号数量: {pkt2.count(b",")}')
print()

# 截断到第一个非打印字符
text = pkt2.decode('ascii', errors='replace')
clean_end = len(text)
for i, c in enumerate(text):
    if ord(c) < 32 and c not in '\r\n\t':
        clean_end = i
        break
text = text[:clean_end]

# 按分号分割
records = [r.strip() for r in text.split(';') if r.strip()]
print(f'=== 解析到 {len(records)} 条记录 ===')
print()
print(f'{"序号":<4} {"类型":<6} {"引脚":<8} {"测量值":<20} {"下限":<15} {"上限":<15} {"结果"}')
print('-'*80)
for i, r in enumerate(records):
    parts = r.lstrip('!').split(',')
    if len(parts) >= 7:
        typ   = parts[1]
        pins  = parts[2].lstrip("'")
        val   = parts[3]
        lo    = parts[4]
        hi    = parts[5]
        res   = parts[6]
        print(f'{i+1:<4} {typ:<6} {pins:<8} {val:<20} {lo:<15} {hi:<15} {res}')

collector.close()
