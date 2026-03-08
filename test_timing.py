"""
测试：mmem:load:trs 2 发出后，等多久再发 *TRG 还能收到 ! ?
"""
import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

def test_with_delay(delay_seconds):
    collector = SerialCollector(port='COM4', baudrate=9600, idle_ms=300)
    collector.start()
    time.sleep(0.3)
    collector.clear_queue()

    # 加载配置
    collector.send('mmem:load:trs 2', ending='\r\n')

    # 等指定时间
    time.sleep(delay_seconds)
    collector.clear_queue()

    # 发 *TRG
    collector.send('*TRG', ending='\r\n')

    # 等第1包 (!)
    try:
        pkt = collector.recv_packet(timeout=3.0)
        result = f'✅ 收到 {repr(pkt)}'
    except queue.Empty:
        result = '❌ 超时，没收到 !'

    collector.close()
    return result

# 测试不同等待时间
delays = [2, 5, 10, 13, 15, 20]

for d in delays:
    print(f'等待 {d:2d} 秒后发 *TRG -> ', end='', flush=True)
    r = test_with_delay(d)
    print(r)
    time.sleep(2)  # 两次测试之间间隔
