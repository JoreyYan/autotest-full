# 测试数据同步到 ERP — 功能规格说明

本文档供 ERP 系统的开发者/AI 阅读，用于在 ERP 中实现"从测试数据表同步到 ERP 主表"的功能。

---

## 一、背景

### 数据流向
```
变压器测试系统 → 飞书 [测试数据 base] → ERP [主表]
（每次测试一条）   （历史所有测试都在）   （需要写入最新一次的结果）
```

### 关键名词
- **序列码 (serial_code)**：飞书记录 ID，扫码枪从二维码扫到的值。形如 `A4onrJnspex6EvcMCPNcIqsDntg`。是飞书 ERP 主表那条记录的 `record_id`，**直接等同于 ERP 主表那行的唯一标识**。
- **序号 (record_number)**：业务可读编号，形如 `2602N0186`。是 ERP 主表里某个文本字段的值（不是 record_id）。
- **测试数据表**：测试系统自动建的飞书表，记录每次测试的所有指标。表里**已经包含**序列码列，序号列可能为空。

### 飞书侧 base 与表
- **测试数据 base**: `app_token = HvqibKLVkaeORss7K9tcLpCZnpg`
- **测试数据表（每产品一张）**: 例如产品 `ZZ-H2500011` 对应一张同名表
- **ERP 主表**: 由 ERP AI 自己确认（自己的 base + 表 ID）

### 测试数据表字段
| 字段名 | 类型 | 说明 |
|--------|------|------|
| 测试时间 | DateTime | unix 毫秒 |
| 序列码 | Text | = ERP 主表那行的 record_id |
| 序号 | Text | 业务编号（部分行可能为空，因为扫码枪失败或网络问题） |
| 磁芯编号 | Text | 可空 |
| 产品 | Text | 产品料号 |
| Lx_2-3(uH), Q_2-3, ... | Number | 各测试项的实测值（3 位小数） |
| 等效n | Number | 计算字段 |
| 产品结果 | SingleSelect | PASS / FAIL |

---

## 二、同步功能设计

### 入口

在 ERP 里加一个按钮，比如叫**"同步测试数据"**。

### 流程

```
点击同步按钮
   │
   ▼
1. 拉取测试数据表全部记录
2. 按"序列码"分组，每组只保留"测试时间"最大的那条
3. 拆成两堆：
   ┌─────────────────────┐     ┌──────────────────────┐
   │  有序列码的（A堆）  │     │  没有序列码的（B堆） │
   └─────────────────────┘     └──────────────────────┘
   │                            │
   ▼                            ▼
   全自动处理：                  列出来让人手输序号：
   - 序列码=ERP record_id        - 显示测试时间、关键测试值
   - 直接 PUT 写 ERP             - 旁边一个输入框
                                 - 用户输 "2602N0186"
                                 - 系统按序号查 ERP record_id
                                 - 再 PUT 写 ERP
```

### A 堆（有序列码）自动同步

伪代码：
```python
for sn, latest_test_record in grouped_data.items():
    if not sn:
        continue
    # sn 就是 ERP 表里那条记录的 record_id
    fields_to_update = {
        'Lx_2-3(uH)': latest_test_record['Lx_2-3(uH)'],
        'Q_2-3':      latest_test_record['Q_2-3'],
        # ... 其他测试字段（按 ERP 表字段名映射）
        '产品结果':    latest_test_record['产品结果'],
        '最近测试时间': latest_test_record['测试时间'],
    }
    feishu_api.put(
        f'/bitable/v1/apps/{ERP_APP_TOKEN}/tables/{ERP_TABLE_ID}/records/{sn}',
        json={'fields': fields_to_update}
    )
```

⚠️ 如果 ERP 主表里没有这个 `record_id` 的记录（已经被删了 / 序列码扫错了），PUT 会返回错误，需要捕获并跳过。

### B 堆（无序列码）手动同步

UI 上列出每条无序列码的测试记录：

```
┌────────────┬──────────────────┬──────┬──────────────┬──────────────┐
│ 测试时间    │ 关键指标         │ 结果 │ 输入序号     │ 操作         │
├────────────┼──────────────────┼──────┼──────────────┼──────────────┤
│ 18:31:06   │ Lx=65.36 Q=261.7 │ PASS │ [输入框    ] │ [关联并写入] │
│ 18:31:10   │ Lx=65.37 Q=255.7 │ PASS │ [输入框    ] │ [关联并写入] │
│ ...        │                  │      │              │              │
└────────────┴──────────────────┴──────┴──────────────┴──────────────┘
```

用户输入 `2602N0186` 后点击"关联并写入"，后端：

```python
# 1. 按序号查 ERP record_id
recs = feishu_api.post(
    f'/bitable/v1/apps/{ERP_APP_TOKEN}/tables/{ERP_TABLE_ID}/records/search',
    json={'filter': {'conjunction': 'and', 'conditions': [
        {'field_name': '序号', 'operator': 'is', 'value': ['2602N0186']}
    ]}}
)
if not recs:
    return error('找不到序号 2602N0186 对应的 ERP 记录')

record_id = recs[0]['record_id']

# 2. PUT 写入测试值（同 A 堆逻辑）
feishu_api.put(f'.../records/{record_id}', json={'fields': test_values})
```

---

## 三、飞书 API 用法速查

### 认证
```python
r = requests.post(
    'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    json={'app_id': APP_ID, 'app_secret': APP_SECRET}
)
TOKEN = r.json()['tenant_access_token']  # 有效期 2h，自己缓存
```

### 拉测试数据表所有记录
```
GET /open-apis/bitable/v1/apps/HvqibKLVkaeORss7K9tcLpCZnpg/tables/{TEST_DATA_TABLE_ID}/records?page_size=500
Header: Authorization: Bearer {TOKEN}
```
分页：返回的 `data.page_token` 不空就继续传。

> 测试数据表 ID 可通过 `GET /apps/{app_token}/tables` 列出所有表，找到 `name == 'ZZ-H2500011'` 那张。

### 按字段值查询（用于 B 堆按序号查 ERP）
```
POST /open-apis/bitable/v1/apps/{ERP_APP_TOKEN}/tables/{ERP_TABLE_ID}/records/search
Body: {"filter": {"conjunction": "and", "conditions": [
    {"field_name": "序号", "operator": "is", "value": ["2602N0186"]}
]}}
```

### 更新记录
```
PUT /open-apis/bitable/v1/apps/{ERP_APP_TOKEN}/tables/{ERP_TABLE_ID}/records/{record_id}
Body: {"fields": {"Lx_2-3(uH)": 65.812, "产品结果": "PASS", ...}}
```

---

## 四、字段映射

请 ERP AI 自己确认 ERP 主表里和测试数据对应的字段名。常见情况：
- ERP 字段名 = 测试数据表字段名（推荐，最简单）
- ERP 字段名不同（如 `主电感`），需要写个映射 dict

可选写入的 ERP 字段：
- 各测试值字段（Lx、Q、Lk、Cx、Dcr、Turn）
- 等效n
- 产品结果
- 测试时间（建议加，记录这次同步是哪次测试的结果）
- 磁芯编号（可选）

---

## 五、配套数据：序列码↔序号 映射 CSV

我已经生成一份 `sn_to_number_map.csv`（两列：序列码, 序号），覆盖了昨天 28 个唯一序列码。ERP AI 可以用它作为本地索引，加速 B 堆的查询验证（输入 2602N0186 时先在这个本地映射里看看有没有对应的序列码）。

但这份 CSV 是历史快照，长期还是要走飞书 search API。

---

## 六、边界情况

| 情况 | 处理 |
|------|------|
| 序列码在 ERP 表找不到对应记录 | 跳过，日志记录 |
| 同一序列码在测试数据表里有多次测试 | 只取最近一次 |
| 用户输入的序号在 ERP 找不到 | UI 报错"找不到序号 XXXX" |
| 测试结果 FAIL 也要写吗？ | 推荐写（业务可见不良率） |
| 测试值字段在 ERP 表里类型不匹配 | 检查 ERP 表字段类型，统一用 Number |
| 同步进行中网络中断 | 本批已成功的不回滚，重试时跳过已写过的（按测试时间判重） |

---

## 七、安全 & 凭证

- 不要在前端代码里暴露 `app_secret`
- 用环境变量或服务端凭证管理
- token 缓存 1~2 小时，到期前刷新

---

## 八、推荐实现顺序

1. **先做 A 堆自动同步**（最有价值，覆盖 ~65% 测试）
2. **再做 B 堆手动 UI**（覆盖剩下扫码失败的）
3. **加同步日志页**（看哪些写了、哪些跳了、上次同步时间）
4. **可选：定时自动同步**（每小时跑一次 A 堆）

---

## 九、问题反馈

如果 ERP AI 实现中遇到字段映射或 API 行为不一致的问题，把测试数据表的 schema 和 ERP 表的 schema 列出来，对照排查即可。
