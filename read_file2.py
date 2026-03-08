import serial, threading, queue, time, sys, io, struct, json

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

# 读文件2
print('读取仪器文件2...')
ser.write(b'mmem:load:trs 2\r\n')
try:
    pkt = rx_q.get(timeout=10)
    print(f'文件2: {len(pkt)} 字节')
    print(f'文件头: {pkt[:20]}')
except queue.Empty:
    print('文件2无响应')
    stop.set(); ser.close(); exit()

cfg = pkt

print()
print('=== 仪器文件2 配置解析 ===')
print(f'设备型号: {cfg[2:10].rstrip(b"\\x00").decode("ascii", errors="replace")}')
print(f'初级数:   {cfg[0x1A]}')
print(f'次级数:   {cfg[0x1B]}')
pinscount = cfg[0x24BF] if len(cfg) > 0x24BF else 'N/A'
print(f'引脚总数: {pinscount}')

print()
print('脚位设置 TrPin[pri][sec][+/-]:')
pin_pairs = []
for p in range(4):
    for s in range(10):
        off = 0x34 + (p * 10 + s) * 2
        plus_pin = cfg[off]
        minus_pin = cfg[off + 1]
        if plus_pin != 0 or minus_pin != 0:
            print(f'  Pri[{p}] Sec[{s}]: {plus_pin}-{minus_pin}')
            pin_pairs.append(f'{plus_pin}-{minus_pin}')

print()
seq = list(cfg[0x24D4:0x24DE])
print(f'扫描序列: {[x for x in seq if x != 0]}')

print()
print('测试项开关:')
tests = [
    ('Turn(匝比)', 0x3F4),
    ('Lx(电感)',   0x680),
    ('DCR(直流电阻)', 0x1282),
    ('Lk(漏感)',   0x15AC),
    ('Cx(电容)',   0x1B30),
    ('PS(短路)',   0x235C),
]
enabled = []
for name, off in tests:
    if len(cfg) > off:
        on = cfg[off]
        print(f'  {name}: {"ON" if on else "OFF"}')
        if on:
            enabled.append(name)

print()
print('=== 对比 ZZ-T250005A.json ===')
json_path = r'D:\公司文件\设备\transformer_test_system\backend\data\products\ZZ-T250005A.json'
with open(json_path, 'r', encoding='utf-8') as f:
    js = json.load(f)

json_pins = list(set(item['pins'] for item in js['test_items']))
json_types = list(set(item['test_type'] for item in js['test_items']))

print(f'JSON 产品:    {js["product_name"]}')
print(f'JSON 配置ID:  {js["instrument_config_id"]}')
print(f'JSON 测试项:  {len(js["test_items"])} 项')
print(f'JSON 引脚对:  {sorted(json_pins)}')
print(f'JSON 测试类型: {sorted(json_types)}')
print()
print(f'仪器 脚位对:  {pin_pairs}')
print(f'仪器 启用项:  {enabled}')

stop.set()
ser.close()
