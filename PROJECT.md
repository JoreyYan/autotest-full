# 变压器自动测试系统 — 完整项目文档

**最后更新：** 2026-03-07
**当前状态：** Backend 完成，Frontend 初始化完成，等待编写前端页面

---

## 一、项目目标

工厂现场：操作员把变压器放上夹具，按一次按钮（或点击网页），系统自动测试，把结果显示出来并保存成 CSV。工程师可以在任何地方通过网页管理产品配置。

---

## 二、整体架构

```
工厂电脑（本地）
┌─────────────────────────────────────────┐
│  浏览器                                  │
│  http://localhost:5173  (前端 React)     │
│    ├── 测试页  /           操作员用       │
│    └── 管理页  /admin      工程师用       │
└──────────────┬──────────────────────────┘
               │ HTTP REST API
┌──────────────▼──────────────────────────┐
│  FastAPI 后端  http://localhost:8000     │
│  D:\code\autotest\backend\main.py       │
└──────────────┬──────────────────────────┘
               │ Python 调用
┌──────────────▼──────────────────────────┐
│  Agent 层（串口代理，永远本地）            │
│  D:\code\autotest\agent\               │
│    serial_conn.py  → COM4, 115200 bps  │
│    instrument.py   → 仪器指令封装        │
│    config_checker.py → 配置比对         │
│    test_runner.py  → 完整测试流程        │
└──────────────┬──────────────────────────┘
               │ RS-232 / USB转串口
┌──────────────▼──────────────────────────┐
│  UC2866XB 变压器综合测试仪               │
│  + 扫描盒（已连接）                       │
└─────────────────────────────────────────┘
```

### 将来上服务器

后端 + 前端可以迁移到服务器，只需改 `config.json` 里的 backend_url。
Agent 层永远在工厂本地电脑运行（因为串口是物理连接）。

---

## 三、目录结构

```
D:\code\autotest\
│
├── agent\                    ← 串口代理层（已完成，不要修改）
│   ├── __init__.py
│   ├── serial_conn.py        串口通信 + 自动扫描仪器
│   ├── instrument.py         仪器指令（load/trigger/recv）
│   ├── config_checker.py     比对CSV结果 vs JSON配置
│   └── test_runner.py        7步初始化 + 单次测试流程
│
├── backend\                  ← FastAPI 后端（已完成）
│   ├── __init__.py
│   ├── main.py               所有 API 端点
│   ├── state.py              全局状态（runner单例、当前产品）
│   └── csv_writer.py         保存测试结果到 CSV
│
├── frontend\                 ← React + shadcn 前端（初始化完成，页面待写）
│   ├── src\
│   │   ├── pages\
│   │   │   ├── TestPage.tsx  测试页（待写）
│   │   │   └── AdminPage.tsx 管理页（待写）
│   │   ├── components\       各种组件（待写）
│   │   ├── lib\
│   │   │   └── api.ts        API 调用封装（待写）
│   │   ├── App.tsx           路由（待写）
│   │   └── main.tsx          入口
│   ├── package.json
│   └── vite.config.ts
│
├── products\                 ← 产品配置 JSON（已有）
│   └── ZZ-T250005A.json      乐马六端口辅助源变压器（已校正）
│
├── results\                  ← 测试结果 CSV（自动生成）
│   └── ZZ-T250005A_20260307.csv
│
├── config.json               ← 系统配置（端口、波特率等）
├── PROTOCOL_FINAL.md         ← 通讯协议完整说明（必读）
└── PROJECT.md                ← 本文件
```

---

## 四、已完成部分

### 4.1 Agent 层（D:\code\autotest\agent\）

**完全不要修改**，已通过实测验证。

#### serial_conn.py
- `SerialConn` 类：后台线程持续读取，300ms空闲封包
- `find_instrument()` 函数：扫描所有COM口，发 `*IDN?`，找到 UC2866XB 返回端口号

#### instrument.py
- `Instrument` 类
- `idn()` → 查询设备型号
- `load_config(n)` → 发 `mmem:load:trs N`，等配置包收完（丢弃）
- `trigger()` → 发 `*TRG`，等收到 `!`（确认字节）
- `recv_csv()` → 等收第2包CSV数据
- `run_test()` → trigger + recv_csv 组合

#### config_checker.py
- `check(csv_text, product_config)` → 比对
- 规则：JSON要求的必须全有，仪器多测无所谓
- 返回 `CheckResult(ok, missing, extra, message)`

#### test_runner.py
- `TestRunner(product_json_path)`
- `initialize(port, baudrate)` → 7步初始化，返回状态字典
- `run()` → 一次测试，返回 `TestRecord`
- `close()` → 断开连接

**7步初始化流程：**
1. 读 config.json 找上次端口
2. 扫描COM口，发 *IDN? 确认是 UC2866XB
3. 发 mmem:load:trs N，等收完配置包（丢弃）
4. 发 *TRG（初始化触发）
5. 比对返回CSV vs JSON（JSON要求的必须全有）
6. 验证通过 → ready = True
7. 操作员看到界面显示"就绪"

### 4.2 Backend（D:\code\autotest\backend\）

**FastAPI，运行在 localhost:8000**

启动命令（在 D:\code\autotest\ 目录下）：
```bash
python -m backend.main
```

#### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/products` | 产品列表 |
| GET | `/api/products/{code}` | 产品详情 |
| POST | `/api/products` | 新建产品 |
| PUT | `/api/products/{code}` | 更新产品 |
| DELETE | `/api/products/{code}` | 删除产品 |
| POST | `/api/initialize` | 初始化仪器 |
| GET | `/api/status` | 当前状态 |
| POST | `/api/test/run` | 执行一次测试 |
| POST | `/api/disconnect` | 断开连接 |
| GET | `/api/results` | 结果文件列表 |

API 文档：`http://localhost:8000/docs`

#### 重要设计

- `state.runner` 是 TestRunner 单例，初始化一次保持连接
- 测试结果保存在 `results/` 目录，按 `{产品码}_{日期}.csv` 命名
- `config.json` 记住上次成功的端口，下次优先尝试

### 4.3 产品配置

`products/ZZ-T250005A.json` — 已校正版本

**重要：** 原来旧系统的 JSON 里 Lk 和 Cx 引脚写错了，已在新 JSON 里修正：
- `Lk` 只有一条：引脚 `1-3`
- `Cx` 三条：引脚 `1-12`, `4-8`, `6-8`

---

## 五、待完成部分

### 5.1 Frontend（D:\code\autotest\frontend\）

**技术栈：** React + TypeScript + Vite + shadcn/ui + React Router + TanStack Query

**当前状态：** `npm install` 已完成，还没有安装 shadcn 和路由，页面文件待写。

#### 安装 shadcn（下一步）

```bash
cd D:\code\autotest\frontend
npx shadcn@latest init
npm install react-router-dom @tanstack/react-query
```

#### 页面规划

**测试页 `/`（操作员日常使用）**

布局：
```
┌─────────────────────────────────┐
│  顶部导航：测试 | 管理            │
├─────────────────────────────────┤
│  选择产品（下拉）                 │
│  [初始化连接]                    │
│  ─────────────────────────────  │
│  状态：● 就绪 / ○ 未连接         │
│  仪器：UC2866XB  端口：COM4      │
│  ─────────────────────────────  │
│  [开始测试]（大按钮）             │
│  ─────────────────────────────  │
│  测试结果（最新一次）             │
│  ✅ PASS  或  ❌ FAIL            │
│  28项：21通过/7失败              │
│  [详细列表 展开/收起]            │
└─────────────────────────────────┘
```

交互流程：
1. 页面打开 → 获取产品列表 → 显示下拉
2. 选产品 → 点"初始化" → loading → 显示状态
3. 初始化成功 → "开始测试"按钮激活
4. 点"开始测试" → loading（约2秒）→ 显示结果
5. 结果显示后，"开始测试"按钮立即可再次点击（下一个产品）

**管理页 `/admin`（工程师配置）**

布局：
```
┌─────────────────────────────────┐
│  顶部导航：测试 | 管理            │
├─────────────────────────────────┤
│  [+ 新建产品]                    │
│                                 │
│  产品列表（表格）                 │
│  料号 | 名称 | 配置ID | 测试项数  │
│  ZZ-T250005A | ... | 2 | 28    │
│  [编辑] [删除]                  │
└─────────────────────────────────┘

点编辑/新建 → 侧边抽屉（Drawer）：
  产品料号（新建可填，编辑不可改）
  产品名称
  仪器配置编号（对应仪器内的第几号文件）
  描述（选填）

  测试项列表（表格，可增删改排序）：
  类型 | 引脚 | 说明 | 单位 | 下限 | 上限 | 标准值 | [删除]
  Turn | 3-1  | 主绕组匝比 | - | - | - | - |
  Lx   | 3-1  | 主绕组电感 | mH | 0.9 | 1.1 | 1.0 |

  [保存] [取消]
```

#### 需要写的文件

```
frontend/src/
├── lib/
│   └── api.ts          所有 API 调用（fetch 封装）
├── pages/
│   ├── TestPage.tsx    测试页
│   └── AdminPage.tsx   管理页
├── components/
│   ├── StatusBadge.tsx  连接状态指示
│   ├── TestItems.tsx    测试项结果列表
│   └── ProductForm.tsx  产品编辑表单（Drawer内）
└── App.tsx             路由配置
```

#### 单位说明（前端显示用）

| 测试类型 | 仪器返回 SI单位 | 显示单位 | 换算 |
|---------|--------------|---------|------|
| Turn | 无量纲 | 直接显示 | × 1 |
| Lx | H（亨利） | mH | × 1000 |
| Q | 无量纲 | 直接显示 | × 1 |
| Lk | H（亨利） | μH | × 1,000,000 |
| Cx | F（法拉） | pF | × 1e12 |
| Dcr | Ω | Ω | × 1 |

---

## 六、开发规范

### 6.1 测试方式
- **单次触发**：操作员点一次"开始测试"→ 仪器测一次 → 返回结果
- **不自动连测**：每次都需要手动触发
- **初始化只做一次**：切换产品才需要重新初始化

### 6.2 比对规则
- JSON 要求的测试项必须全部有（缺了就报错）
- 仪器多测了无所谓（比如仪器多开了某项测试）

### 6.3 数据存储
- 现阶段：CSV 文件，`results/{产品码}_{日期}.csv`
- 每次测试追加一行
- 将来：迁移到数据库（接口不变，换底层实现）

### 6.4 二维码预留位置
- 每条测试记录将来需要一个唯一 SN
- SN 格式建议：`{产品码}-{日期}-{流水号}`，如 `ZZ-T250005A-20260307-00001`
- 现阶段用时间戳代替，接口里留 `sn` 字段

---

## 七、通讯协议关键点（详见 PROTOCOL_FINAL.md）

- 波特率：**115200**（不是9600）
- 仪器：COM4（自动扫描）
- 数据流：`*TRG` → 第1包`!`（确认）→ 第2包CSV（约1554字节，1.7秒）
- 不需要 `*OPC?` 轮询，不需要 `TRS:DATA?` 查询
- 初始化：`mmem:load:trs N` → 等包收完 → 发 `*TRG` → 验证

---

## 八、已知问题 / 注意事项

1. **旧系统 JSON 错误**：原 `ZZ-T250005A.json` 里 Cx 的引脚被错误标成了 Lk，已在 `D:\code\autotest\products\` 下的新版本修正
2. **agent 层不要动**：已完全测试验证，稳定可用
3. **端口记忆**：成功连接后端口写入 `config.json`，下次优先用
4. **115200 下 9600 的坑**：在9600时，`mmem:load:trs` 等全部传完再触发会失效；115200下没有这个问题（见 PROTOCOL_FINAL.md）

---

## 九、快速启动

```bash
# 1. 启动后端（在 D:\code\autotest\ 目录）
python -m backend.main

# 2. 启动前端（在 D:\code\autotest\frontend\ 目录）
npm run dev

# 3. 浏览器访问
http://localhost:5173
```

---

## 十、当前卡在哪里

**正在做：** 安装 shadcn/ui 和路由，写前端页面

**下一步具体操作：**
```bash
cd D:\code\autotest\frontend

# 安装 shadcn
npx shadcn@latest init
# 选择：TypeScript, CSS variables, 默认其他

# 安装路由和请求库
npm install react-router-dom @tanstack/react-query

# 安装需要的 shadcn 组件
npx shadcn@latest add button card select badge table drawer input label
```

然后按以下顺序写文件：
1. `src/lib/api.ts` — API 调用
2. `src/App.tsx` — 路由
3. `src/pages/TestPage.tsx` — 测试页
4. `src/pages/AdminPage.tsx` — 管理页
