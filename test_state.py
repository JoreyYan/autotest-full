import sys, io, time, queue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

PORT, BAUD = 'COM4', 115200

def try_trg(label):
    collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
    collector.start()
    time.sleep(0.2)
    collector.clear_queue()
    collector.send('*TRG', ending='\r\n')
    try:
        collector.recv_packet(timeout=3.0)
        collector.recv_packet(timeout=5.0)
        collector.close()
        print(f'{label} -> ✅ 成功')
        return True
    except queue.Empty:
        collector.close()
        print(f'{label} -> ❌ 失败')
        return False

# 场景1：加载配置后，不发 *TRG，等30秒再试
print('=== 场景1：加载配置后不发 *TRG，等30秒 ===')
collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
collector.start()
time.sleep(0.2)
collector.clear_queue()
collector.send('mmem:load:trs 2', ending='\r\n')
collector.recv_packet(timeout=5.0)  # 等配置包收完，丢弃
collector.close()
print('配置已收到，不发 *TRG，等30秒...')
time.sleep(30)
try_trg('等30秒后 *TRG')

print()

# 场景2：加载配置后，先发一次 *TRG，再等30秒
print('=== 场景2：加载配置后先发一次 *TRG，再等30秒 ===')
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
print('第一次 *TRG 完成，等30秒...')
time.sleep(30)
try_trg('等30秒后第二次 *TRG')
