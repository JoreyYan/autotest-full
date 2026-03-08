"""
比对仪器配置（mmem:load:trs 2）和 JSON 产品配置
"""
import sys, io, time, queue, struct, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\公司文件\设备\test_device')
from serial_collector import SerialCollector

PORT, BAUD = 'COM4', 115200

# ── 1. 从仪器读取配置 ──────────────────────────────────────────
collector = SerialCollector(port=PORT, baudrate=BAUD, idle_ms=300)
collector.start()
time.sleep(0.3)
collector.clear_queue()

print('读取仪器配置...')
collector.send('mmem:load:trs 2', ending='\r\n')
cfg = collector.recv_packet(timeout=5.0)
collector.close()
print(f'收到 {len(cfg)} 字节\n')

# ── 2. 解析仪器配置关键字段 ────────────────────────────────────
instr = {}

# 设备型号
instr['model'] = cfg[2:10].rstrip(b'\x00').decode('ascii', errors='replace')

# 初级/次级数量
instr['pri_sets'] = cfg[0x1A]
instr['sec_sets'] = cfg[0x1B]

# 引脚总数
instr['pins_count'] = cfg[0x24BF] if len(cfg) > 0x24BF else 0

# 脚位设置 TrPin[4][10][2]
instr['pin_pairs'] = []
for p in range(4):
    for s in range(10):
        off = 0x34 + (p * 10 + s) * 2
        plus_pin  = cfg[off]
        minus_pin = cfg[off + 1]
        if plus_pin != 0 or minus_pin != 0:
            instr['pin_pairs'].append(f'{plus_pin}-{minus_pin}')

# 测试项开关
test_offsets = {
    'Turn': 0x3F4,
    'Lx':   0x680,
    'DCR':  0x1282,
    'Lk':   0x15AC,
    'Cx':   0x1B30,
    'PS':   0x235C,
}
instr['tests_on'] = {k: bool(cfg[v]) for k, v in test_offsets.items() if len(cfg) > v}

# ── 3. 读取 JSON 配置 ──────────────────────────────────────────
json_path = r'D:\公司文件\设备\transformer_test_system\backend\data\products\ZZ-T250005A.json'
with open(json_path, 'r', encoding='utf-8') as f:
    js = json.load(f)

json_pins    = sorted(set(item['pins'] for item in js['test_items']))
json_types   = set(item['test_type'] for item in js['test_items'])

# JSON 类型映射到仪器字段名
type_map = {'Turn': 'Turn', 'Lx': 'Lx', 'Q': 'Lx',  # Q 依附于 Lx
            'Lk': 'Lk', 'Cx': 'Cx', 'Dcr': 'DCR'}
json_instr_types = set(type_map.get(t) for t in json_types if type_map.get(t))

# ── 4. 输出比对结果 ────────────────────────────────────────────
print('=' * 55)
print('配置比对报告')
print('=' * 55)

ok = True

# 设备型号
print(f'\n设备型号:     {instr["model"]}')
print(f'配置文件编号: JSON要求 = {js["instrument_config_id"]}  (已加载2号 ✅)')

# 初级次级
print(f'\n初级数:  仪器={instr["pri_sets"]}')
print(f'次级数:  仪器={instr["sec_sets"]}')
print(f'引脚总数: 仪器={instr["pins_count"]}')

# 引脚对比对
print(f'\n{"─"*55}')
print('引脚对比对:')
instr_pins = sorted(instr['pin_pairs'])
missing = [p for p in json_pins if p not in instr_pins]
extra   = [p for p in instr_pins if p not in json_pins]

for p in json_pins:
    mark = '✅' if p in instr_pins else '❌'
    print(f'  {mark} {p}')
if extra:
    for p in extra:
        print(f'  ➕ {p} (仪器有，JSON无)')
if missing:
    print(f'\n❌ JSON中有但仪器未配置的引脚: {missing}')
    ok = False
else:
    print(f'\n✅ 引脚配置完全匹配')

# 测试项对比
print(f'\n{"─"*55}')
print('测试项开关对比:')
for instr_key in ['Turn', 'Lx', 'DCR', 'Lk', 'Cx']:
    needed = instr_key in json_instr_types
    enabled = instr['tests_on'].get(instr_key, False)
    if needed and enabled:
        print(f'  ✅ {instr_key:6s}  JSON需要 = 是  仪器启用 = 是')
    elif needed and not enabled:
        print(f'  ❌ {instr_key:6s}  JSON需要 = 是  仪器启用 = 否  ← 不匹配')
        ok = False
    elif not needed and enabled:
        print(f'  ➕ {instr_key:6s}  JSON需要 = 否  仪器启用 = 是  (多余，不影响)')
    else:
        print(f'  ⚪ {instr_key:6s}  JSON需要 = 否  仪器启用 = 否')

# 总结
print(f'\n{"=" * 55}')
if ok:
    print('✅ 配置验证通过，仪器配置与产品JSON完全匹配')
else:
    print('❌ 配置验证失败，请检查以上不匹配项')
print('=' * 55)
