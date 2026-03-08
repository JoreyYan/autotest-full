import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

PORT, BAUD = 'COM4', 115200

def single_trg():
    """发一次 *TRG，返回是否成功"""
    collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
    collector.start()
    time.sleep(0.2)
    collector.clear_queue()
    collector.send('*TRG', ending='\r\n')
    try:
        collector.recv_packet(timeout=3.0)  # !
        collector.recv_packet(timeout=5.0)  # CSV
        collector.close()
        return True
    except queue.Empty:
        collector.close()
        return False

# 先做一次初始化（加载配置+触发）
print('初始化...')
collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
collector.start()
time.sleep(0.2)
collector.clear_queue()
collector.send('mmem:load:trs 2', ending='\r\n')
collector.recv_packet(timeout=5.0)
collector.send('*TRG', ending='\r\n')
collector.recv_packet(timeout=3.0)
collector.recv_packet(timeout=5.0)
collector.close()
print('初始化完成，开始测试不同等待时间\n')

# 等待不同时间后发 *TRG
for wait in [10, 30, 60]:
    print(f'等待 {wait} 秒...', flush=True)
    time.sleep(wait)
    ok = single_trg()
    print(f'等 {wait}s 后 *TRG -> {"✅ 成功" if ok else "❌ 失败"}')
