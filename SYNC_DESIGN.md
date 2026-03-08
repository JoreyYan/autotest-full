# 测试数据同步设计文档

**版本：** 1.0
**日期：** 2026-03-07
**状态：** 设计完成，待实现

---

## 一、需求

1. **CSV 永远可用**：无论网络状态如何，每次测试结果必须保存到本地 CSV
2. **网络通时实时上传**：测试完成后立即同步到云端数据库
3. **网络断时不丢数据**：积累到本地队列，网络恢复后自动补传
4. **手动补传兜底**：提供脚本，可以用 CSV 手动批量补传

---

## 二、整体架构

```
每次测试完成（TestRecord）
        │
        ├──① 写 CSV（永远执行）
        │      results/ZZ-T250005A_20260307.csv
        │
        └──② 尝试上传 Supabase
               │
               ├── 网络通 → HTTP POST → Supabase ✓
               │
               └── 网络断 → 写入本地队列
                          results/pending_sync.jsonl

后台线程（每 60 秒）
        │
        ├── 检查 pending_sync.jsonl
        ├── 网络通 → 批量上传 → 清空队列
        └── 网络断 → 继续等待
```

---

## 三、云端数据库：Supabase

### 为什么选 Supabase

- 免费版足够用（500MB 存储，每月 2GB 流量）
- PostgreSQL，数据可靠
- 有 REST API，Python 直接 HTTP 调用，不需要安装驱动
- 可以在网页上查看、导出数据
- 将来可以在 Supabase 上做数据看板

### 注册和创建项目

1. 访问 https://supabase.com，注册账号
2. 新建项目，记住：
   - Project URL：`https://xxxxx.supabase.co`
   - anon public key：`eyJxxx...`（在 Settings → API 里找）

### 数据库表结构

在 Supabase 的 SQL Editor 里执行以下 SQL：

```sql
-- 测试记录主表
CREATE TABLE test_records (
    id           BIGSERIAL PRIMARY KEY,
    timestamp    TIMESTAMP NOT NULL,          -- 测试时间
    product_code TEXT NOT NULL,               -- 产品料号，如 ZZ-T250005A
    overall      TEXT NOT NULL,               -- PASS 或 FAIL
    passed       INTEGER NOT NULL,            -- 通过项数
    failed       INTEGER NOT NULL,            -- 失败项数
    total        INTEGER NOT NULL,            -- 总项数
    sn           TEXT,                        -- 预留：将来的二维码/SN号
    created_at   TIMESTAMP DEFAULT NOW()
);

-- 测试明细表（每条记录对应 test_records 里的一行）
CREATE TABLE test_items (
    id           BIGSERIAL PRIMARY KEY,
    record_id    BIGINT REFERENCES test_records(id) ON DELETE CASCADE,
    item_type    TEXT NOT NULL,   -- Turn / Lx / Q / Lk / Cx / Dcr
    pins         TEXT NOT NULL,   -- 如 3-1
    value        REAL NOT NULL,   -- 测量值（SI 单位）
    lo           REAL NOT NULL,   -- 下限
    hi           REAL NOT NULL,   -- 上限
    result       TEXT NOT NULL    -- Pass 或 Fail
);

-- 加索引，查询快
CREATE INDEX idx_records_product ON test_records(product_code);
CREATE INDEX idx_records_timestamp ON test_records(timestamp);
CREATE INDEX idx_records_overall ON test_records(overall);
CREATE INDEX idx_items_record ON test_items(record_id);
```

---

## 四、本地文件结构

```
D:\code\autotest\
├── results\
│   ├── ZZ-T250005A_20260307.csv   ← CSV 本地备份（每天一个文件）
│   ├── ZZ-T250005A_20260308.csv
│   └── pending_sync.jsonl         ← 待同步队列（网络恢复后自动清空）
├── backend\
│   ├── main.py
│   ├── state.py
│   ├── csv_writer.py              ← 现有，不变
│   └── sync_writer.py             ← 新增
└── config.json                    ← 加入 Supabase 配置
```

### pending_sync.jsonl 格式

每行一条 JSON，网络恢复后逐行上传：

```jsonl
{"timestamp": "2026-03-07 20:40:28", "product_code": "ZZ-T250005A", "overall": "FAIL", "passed": 21, "failed": 7, "total": 28, "sn": null, "items": [...]}
{"timestamp": "2026-03-07 20:43:11", "product_code": "ZZ-T250005A", "overall": "PASS", "passed": 28, "failed": 0, "total": 28, "sn": null, "items": [...]}
```

---

## 五、config.json 配置项

```json
{
  "port": "COM4",
  "baudrate": 115200,
  "products_dir": "products",
  "results_dir": "results",
  "supabase": {
    "enabled": true,
    "url": "https://xxxxx.supabase.co",
    "key": "eyJxxx...",
    "retry_interval_seconds": 60
  }
}
```

`enabled: false` 时完全跳过云端同步，只写 CSV。

---

## 六、sync_writer.py 实现

新建 `backend/sync_writer.py`：

```python
"""
sync_writer.py — 离线优先的云端同步模块

策略：
  - 每次测试后先写 CSV（由 csv_writer.py 负责，本模块不管）
  - 再尝试实时上传 Supabase
  - 失败则写入 pending_sync.jsonl
  - 后台线程每 60 秒重试一次
"""

import json
import threading
import time
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ── 配置（由 state.py 在启动时注入）─────────────────────────────
_config: dict = {}
_pending_file: Path = Path('results/pending_sync.jsonl')


def configure(supabase_cfg: dict, results_dir: Path):
    """由 backend/main.py 启动时调用，注入配置"""
    global _config, _pending_file
    _config = supabase_cfg
    _pending_file = results_dir / 'pending_sync.jsonl'
    _pending_file.parent.mkdir(exist_ok=True)

    if _config.get('enabled'):
        # 启动后台重试线程
        t = threading.Thread(target=_retry_loop, daemon=True)
        t.start()
        logger.info('云端同步已启用，后台线程已启动')
    else:
        logger.info('云端同步未启用，仅保存 CSV')


# ── 主调用入口 ────────────────────────────────────────────────────

def save_and_sync(record_dict: dict):
    """
    测试完成后调用此函数。
    - 若网络通：直接上传 Supabase
    - 若网络断：写入 pending 队列，后台线程稍后重试
    """
    if not _config.get('enabled'):
        return

    if _upload_one(record_dict):
        logger.info(f'实时上传成功：{record_dict.get("product_code")} {record_dict.get("timestamp")}')
    else:
        _enqueue(record_dict)
        logger.warning('网络不通，已写入待同步队列')


# ── Supabase 上传 ─────────────────────────────────────────────────

def _upload_one(record_dict: dict) -> bool:
    """
    上传一条测试记录到 Supabase。
    先插入 test_records 主记录，再插入 test_items 明细。
    成功返回 True，失败返回 False。
    """
    url = _config.get('url', '').rstrip('/')
    key = _config.get('key', '')
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'  # 返回插入后的记录（含 id）
    }

    try:
        # 1. 插入主记录
        main_record = {
            'timestamp':    record_dict['timestamp'],
            'product_code': record_dict['product_code'],
            'overall':      record_dict['overall'],
            'passed':       record_dict['passed'],
            'failed':       record_dict['failed'],
            'total':        record_dict['passed'] + record_dict['failed'],
            'sn':           record_dict.get('sn'),
        }

        r = requests.post(
            f'{url}/rest/v1/test_records',
            headers=headers,
            json=main_record,
            timeout=8
        )

        if r.status_code not in (200, 201):
            logger.error(f'上传主记录失败：{r.status_code} {r.text[:200]}')
            return False

        record_id = r.json()[0]['id']

        # 2. 插入明细记录
        items = [
            {
                'record_id': record_id,
                'item_type': item['type'],
                'pins':      item['pins'],
                'value':     item['value'],
                'lo':        item['lo'],
                'hi':        item['hi'],
                'result':    item['result'],
            }
            for item in record_dict.get('items', [])
        ]

        if items:
            r2 = requests.post(
                f'{url}/rest/v1/test_items',
                headers=headers,
                json=items,
                timeout=8
            )
            if r2.status_code not in (200, 201):
                logger.error(f'上传明细失败：{r2.status_code} {r2.text[:200]}')
                # 主记录已插入，明细失败不回滚（避免复杂事务）
                # 可以后续补传明细，或接受少量不完整记录
                return False

        return True

    except requests.exceptions.ConnectionError:
        return False  # 网络断开，正常情况
    except requests.exceptions.Timeout:
        logger.warning('上传超时（8秒），写入待同步队列')
        return False
    except Exception as e:
        logger.error(f'上传异常：{e}')
        return False


# ── 本地队列操作 ──────────────────────────────────────────────────

def _enqueue(record_dict: dict):
    """追加到待同步队列文件"""
    with open(_pending_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record_dict, ensure_ascii=False) + '\n')


def _retry_loop():
    """
    后台线程：每 N 秒检查 pending 队列，网络通时批量上传
    """
    interval = _config.get('retry_interval_seconds', 60)

    while True:
        time.sleep(interval)

        if not _pending_file.exists():
            continue

        lines = _pending_file.read_text(encoding='utf-8').strip().splitlines()
        if not lines:
            continue

        logger.info(f'发现 {len(lines)} 条待同步记录，开始重试...')

        failed_lines = []
        success_count = 0

        for line in lines:
            try:
                record = json.loads(line)
                if _upload_one(record):
                    success_count += 1
                else:
                    failed_lines.append(line)  # 还是失败，留着下次重试
            except json.JSONDecodeError:
                logger.error(f'队列文件损坏，跳过此行：{line[:50]}')
                # 损坏的行直接丢弃，不影响其他记录

        # 把还没成功的写回去
        if failed_lines:
            _pending_file.write_text('\n'.join(failed_lines) + '\n', encoding='utf-8')
            logger.warning(f'本次上传 {success_count} 条，剩余 {len(failed_lines)} 条待重试')
        else:
            _pending_file.unlink()
            logger.info(f'队列已清空，共上传 {success_count} 条')


# ── 手动补传（供脚本调用）────────────────────────────────────────

def upload_from_pending() -> tuple[int, int]:
    """
    手动触发一次完整同步，返回 (成功数, 失败数)。
    可以在命令行手动执行，或在管理界面提供"立即同步"按钮。
    """
    if not _pending_file.exists():
        return 0, 0

    lines = _pending_file.read_text(encoding='utf-8').strip().splitlines()
    failed_lines = []
    success = 0

    for line in lines:
        try:
            if _upload_one(json.loads(line)):
                success += 1
            else:
                failed_lines.append(line)
        except Exception:
            failed_lines.append(line)

    if failed_lines:
        _pending_file.write_text('\n'.join(failed_lines) + '\n', encoding='utf-8')
    elif _pending_file.exists():
        _pending_file.unlink()

    return success, len(failed_lines)
```

---

## 七、修改 backend/main.py

只需改两处：

### 1. 启动时注入配置（在 `if __name__ == '__main__':` 前面加）

```python
# 在文件顶部加 import
from . import sync_writer

# 在 app 定义后，uvicorn.run 前加
@app.on_event('startup')
async def startup():
    cfg = json.loads(Path('config.json').read_text(encoding='utf-8'))
    supabase_cfg = cfg.get('supabase', {'enabled': False})
    results_dir = Path(cfg.get('results_dir', 'results'))
    sync_writer.configure(supabase_cfg, results_dir)
```

### 2. run_test 里加一行

```python
@app.post('/api/test/run')
def run_test():
    # ... 现有代码 ...
    csv_file = save(record, state.get_results_dir())   # 现有，不变

    sync_writer.save_and_sync({                         # 新增
        'timestamp':    record.timestamp,
        'product_code': record.product_code,
        'overall':      record.overall,
        'passed':       record.passed,
        'failed':       record.failed,
        'sn':           None,  # 预留二维码位置
        'items':        record.items,
    })

    return TestResult(...)  # 现有，不变
```

### 3. 新增手动同步接口（可选）

```python
@app.post('/api/sync/retry')
def retry_sync():
    """手动触发待同步队列上传（管理页可以加个按钮）"""
    success, failed = sync_writer.upload_from_pending()
    return {'success': success, 'failed': failed}

@app.get('/api/sync/status')
def sync_status():
    """查看待同步队列状态"""
    pending_file = state.get_results_dir() / 'pending_sync.jsonl'
    if not pending_file.exists():
        return {'pending_count': 0, 'status': '已同步'}
    lines = [l for l in pending_file.read_text(encoding='utf-8').splitlines() if l.strip()]
    return {'pending_count': len(lines), 'status': f'有 {len(lines)} 条待同步'}
```

---

## 八、各种场景行为

| 场景 | CSV | Supabase | pending.jsonl |
|------|-----|----------|---------------|
| 网络通，测试正常 | ✅ 写入 | ✅ 实时上传 | 不存在 |
| 网络断，测试正常 | ✅ 写入 | ❌ 失败 | ✅ 积累记录 |
| 网络恢复 | 不变 | ✅ 后台自动补传 | ✅ 自动清空 |
| Supabase 故障 | ✅ 写入 | ❌ 失败 | ✅ 积累，故障恢复后补传 |
| `enabled: false` | ✅ 写入 | 跳过 | 不存在 |

---

## 九、手动用 CSV 补传（终极兜底）

如果 pending.jsonl 丢失但 CSV 还在，可以用这个脚本从 CSV 补传：

```python
# scripts/upload_from_csv.py
"""
从 CSV 文件手动补传历史数据到 Supabase
用法：python scripts/upload_from_csv.py results/ZZ-T250005A_20260307.csv
"""
import sys, csv, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from backend import sync_writer

def upload_csv(csv_path: str):
    cfg = json.loads(Path('config.json').read_text(encoding='utf-8'))
    sync_writer.configure(cfg.get('supabase', {}), Path('results'))

    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f'共 {len(rows)} 行，开始上传...')
    success = 0

    for row in rows:
        # 从 CSV 重建 record_dict
        items = []
        for col, val in row.items():
            if '_结果' in col or col in ('时间', '产品料号', '总判定', '通过数', '失败数'):
                continue
            if val and val != 'N/A':
                type_pin = col.split('_', 1)
                if len(type_pin) == 2:
                    result_key = col + '_结果'
                    items.append({
                        'type': type_pin[0],
                        'pins': type_pin[1],
                        'value': float(val),
                        'lo': 0,
                        'hi': 0,
                        'result': row.get(result_key, '')
                    })

        record = {
            'timestamp':    row.get('时间', ''),
            'product_code': row.get('产品料号', ''),
            'overall':      row.get('总判定', ''),
            'passed':       int(row.get('通过数', 0)),
            'failed':       int(row.get('失败数', 0)),
            'sn':           None,
            'items':        items,
        }

        if sync_writer._upload_one(record):
            success += 1
            print(f'  ✓ {record["timestamp"]}')
        else:
            print(f'  ✗ {record["timestamp"]} 失败')

    print(f'\n完成：{success}/{len(rows)} 条上传成功')

if __name__ == '__main__':
    upload_csv(sys.argv[1])
```

运行方式：
```bash
cd D:\code\autotest
python scripts/upload_from_csv.py results/ZZ-T250005A_20260307.csv
```

---

## 十、实施步骤

1. **注册 Supabase**，创建项目，执行第三节的 SQL 建表
2. **填写 config.json**，把 url 和 key 填进去
3. **新建 `backend/sync_writer.py`**（第六节代码）
4. **修改 `backend/main.py`**（第七节，共改两处）
5. **重启后端**，测试一次，检查 Supabase 后台是否有数据
6. **断网测试**：关闭 WiFi，测试一次，看 pending_sync.jsonl 是否生成；恢复网络，等 60 秒，看文件是否自动清空

---

## 十一、注意事项

1. **API Key 安全**：不要把 Supabase key 提交到 git，config.json 加入 .gitignore
2. **明细失败不回滚**：主记录插入成功、明细插入失败时，数据库会有不完整记录。这种情况很罕见（超时时更可能发生），可以接受，或者用 CSV 补传明细
3. **时钟同步**：工厂电脑时间要准确，Supabase 里按时间查询依赖本地时间
4. **SN 字段预留**：将来二维码功能上线时，在这里填入扫描到的 SN 号即可，数据库结构不需要改

---

*本文档对应代码改动量：新增 1 个文件（sync_writer.py），修改 1 个文件（main.py 共 15 行），新增 1 个脚本（upload_from_csv.py）。CSV 生成逻辑完全不变。*
