# 交接文档 — 给接手开发者（Gemini）

**当前状态：** Backend 完成，Frontend 框架初始化完成，需要写前端页面

---

## 必读文档

在做任何事之前，请先读这两个文件：
1. `D:\code\autotest\PROTOCOL_FINAL.md` — 仪器通讯协议（非常重要，有很多坑）
2. `D:\code\autotest\PROJECT.md` — 完整项目规划

---

## 绝对不要动的文件

```
D:\code\autotest\agent\          ← 整个目录不要碰
D:\code\autotest\products\       ← 不要动现有JSON
D:\code\autotest\PROTOCOL_FINAL.md
```

---

## 当前目录结构

```
D:\code\autotest\
├── agent\              ✅ 完成
├── backend\            ✅ 完成
├── frontend\           🔄 框架初始化完成，页面待写
│   ├── node_modules\   ✅ npm install 完成
│   ├── src\
│   │   ├── App.tsx     ← 需要改成路由
│   │   └── main.tsx    ← 已有，不用动
│   ├── package.json
│   └── vite.config.ts
├── products\
│   └── ZZ-T250005A.json  ✅ 已校正
├── results\            ← 自动生成的 CSV 在这里
├── config.json
├── PROJECT.md
├── PROTOCOL_FINAL.md
└── HANDOFF.md          ← 本文件
```

---

## 第一步：安装前端依赖

在 `D:\code\autotest\frontend\` 目录执行：

```bash
# 1. 安装路由和请求库
npm install react-router-dom @tanstack/react-query

# 2. 初始化 shadcn/ui
npx shadcn@latest init
```

shadcn init 会问几个问题，按这样回答：
- Style: Default
- Base color: Slate
- CSS variables: Yes
- 其他默认

```bash
# 3. 安装需要的 shadcn 组件
npx shadcn@latest add button card select badge table drawer input label separator toast
```

---

## 第二步：配置 Vite 代理

编辑 `frontend/vite.config.ts`，加上代理让前端请求后端：

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

---

## 第三步：写 API 调用层

新建 `frontend/src/lib/api.ts`：

```typescript
const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || '请求失败')
  }
  return res.json()
}

// 产品管理
export const api = {
  getProducts: () =>
    request<Product[]>('/products'),

  getProduct: (code: string) =>
    request<Product>(`/products/${code}`),

  createProduct: (data: ProductBody) =>
    request('/products', { method: 'POST', body: JSON.stringify(data) }),

  updateProduct: (code: string, data: ProductBody) =>
    request(`/products/${code}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteProduct: (code: string) =>
    request(`/products/${code}`, { method: 'DELETE' }),

  // 仪器控制
  initialize: (product_code: string, port?: string) =>
    request<InitStatus>('/initialize', {
      method: 'POST',
      body: JSON.stringify({ product_code, port }),
    }),

  getStatus: () =>
    request<SystemStatus>('/status'),

  runTest: () =>
    request<TestResult>('/test/run', { method: 'POST' }),

  disconnect: () =>
    request('/disconnect', { method: 'POST' }),

  getResults: () =>
    request<ResultFile[]>('/results'),
}

// 类型定义
export interface TestItem {
  test_type: string
  pins: string
  description: string
  lower_limit: number | null
  upper_limit: number | null
  standard_value: number | null
  unit: string | null
}

export interface Product {
  product_code: string
  product_name: string
  instrument_config_id: number
  description: string
  test_items: TestItem[]
  test_items_count?: number
}

export type ProductBody = Omit<Product, 'test_items_count'>

export interface InitStatus {
  ok: boolean
  port?: string
  idn?: string
  config_check?: {
    ok: boolean
    missing: string[]
    extra: string[]
    message: string
  }
  message: string
}

export interface SystemStatus {
  ready: boolean
  product_code: string | null
  port: string
}

export interface MeasuredItem {
  type: string
  pins: string
  value: number
  lo: number
  hi: number
  result: string  // 'Pass' | 'Fail'
}

export interface TestResult {
  ok: boolean
  timestamp: string
  product_code: string
  overall: string  // 'PASS' | 'FAIL'
  passed: number
  failed: number
  items: MeasuredItem[]
  csv_file: string
}

export interface ResultFile {
  filename: string
  size: number
  modified: number
}
```

---

## 第四步：配置路由

替换 `frontend/src/App.tsx` 内容：

```tsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TestPage from './pages/TestPage'
import AdminPage from './pages/AdminPage'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <nav className="border-b px-6 py-3 flex gap-6 bg-white">
          <span className="font-semibold text-lg mr-4">变压器测试系统</span>
          <NavLink to="/" end className={({ isActive }) =>
            isActive ? 'text-blue-600 font-medium' : 'text-gray-500 hover:text-gray-900'
          }>测试</NavLink>
          <NavLink to="/admin" className={({ isActive }) =>
            isActive ? 'text-blue-600 font-medium' : 'text-gray-500 hover:text-gray-900'
          }>管理</NavLink>
        </nav>
        <main className="max-w-4xl mx-auto py-8 px-4">
          <Routes>
            <Route path="/" element={<TestPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

---

## 第五步：写测试页

新建 `frontend/src/pages/TestPage.tsx`：

```tsx
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api, type TestResult, type MeasuredItem } from '../lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'

// 单位换算（仪器返回SI单位，前端转换显示）
function formatValue(item: MeasuredItem): string {
  const { type, value } = item
  if (type === 'Lx')  return `${(value * 1000).toFixed(4)} mH`
  if (type === 'Lk')  return `${(value * 1e6).toFixed(4)} μH`
  if (type === 'Cx')  return `${(value * 1e12).toFixed(2)} pF`
  if (type === 'Dcr') return `${value.toFixed(5)} Ω`
  return value.toFixed(6)
}

export default function TestPage() {
  const [selectedProduct, setSelectedProduct] = useState<string>('')
  const [lastResult, setLastResult] = useState<TestResult | null>(null)

  // 获取产品列表
  const { data: products = [] } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  })

  // 获取系统状态
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ['status'],
    queryFn: api.getStatus,
    refetchInterval: 3000,  // 每3秒刷新一次状态
  })

  // 初始化
  const initMutation = useMutation({
    mutationFn: () => api.initialize(selectedProduct),
    onSuccess: () => refetchStatus(),
  })

  // 执行测试
  const testMutation = useMutation({
    mutationFn: api.runTest,
    onSuccess: (data) => setLastResult(data),
  })

  const isReady = status?.ready && status?.product_code === selectedProduct

  return (
    <div className="space-y-6">
      {/* 选产品 + 初始化 */}
      <Card>
        <CardHeader><CardTitle>连接设置</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-sm font-medium mb-1 block">选择产品</label>
              <Select value={selectedProduct} onValueChange={setSelectedProduct}>
                <SelectTrigger>
                  <SelectValue placeholder="请选择产品..." />
                </SelectTrigger>
                <SelectContent>
                  {products.map(p => (
                    <SelectItem key={p.product_code} value={p.product_code}>
                      {p.product_code} — {p.product_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              onClick={() => initMutation.mutate()}
              disabled={!selectedProduct || initMutation.isPending}
            >
              {initMutation.isPending ? '初始化中...' : '初始化连接'}
            </Button>
          </div>

          {/* 状态显示 */}
          {initMutation.data && (
            <div className={`p-3 rounded text-sm ${initMutation.data.ok ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
              {initMutation.data.message}
            </div>
          )}
          {initMutation.error && (
            <div className="p-3 rounded text-sm bg-red-50 text-red-800">
              {(initMutation.error as Error).message}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 测试按钮 */}
      <Card>
        <CardContent className="pt-6">
          <Button
            size="lg"
            className="w-full h-16 text-xl"
            disabled={!isReady || testMutation.isPending}
            onClick={() => testMutation.mutate()}
          >
            {testMutation.isPending ? '测试中...' : '开始测试'}
          </Button>
        </CardContent>
      </Card>

      {/* 测试结果 */}
      {lastResult && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3">
              测试结果
              <Badge variant={lastResult.overall === 'PASS' ? 'default' : 'destructive'} className="text-lg px-3 py-1">
                {lastResult.overall}
              </Badge>
              <span className="text-sm font-normal text-gray-500">
                {lastResult.passed}/{lastResult.passed + lastResult.failed} 项通过 · {lastResult.timestamp}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-500 border-b">
                  <tr>
                    <th className="text-left py-2 pr-4">类型</th>
                    <th className="text-left py-2 pr-4">引脚</th>
                    <th className="text-right py-2 pr-4">测量值</th>
                    <th className="text-center py-2">结果</th>
                  </tr>
                </thead>
                <tbody>
                  {lastResult.items.map((item, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1.5 pr-4 font-mono">{item.type}</td>
                      <td className="py-1.5 pr-4 font-mono">{item.pins}</td>
                      <td className="py-1.5 pr-4 text-right font-mono">{formatValue(item)}</td>
                      <td className="py-1.5 text-center">
                        <Badge variant={item.result === 'Pass' ? 'outline' : 'destructive'} className="text-xs">
                          {item.result}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
```

---

## 第六步：写管理页

新建 `frontend/src/pages/AdminPage.tsx`：

```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Product, type ProductBody, type TestItem } from '../lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerFooter } from '@/components/ui/drawer'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const TEST_TYPES = ['Turn', 'Lx', 'Q', 'Lk', 'Cx', 'Dcr']
const UNITS: Record<string, string[]> = {
  Turn: [], Q: [],
  Lx: ['H', 'mH', 'μH', 'nH'],
  Lk: ['H', 'mH', 'μH', 'nH'],
  Cx: ['F', 'mF', 'μF', 'nF', 'pF'],
  Dcr: ['Ω', 'mΩ', 'kΩ'],
}

function emptyProduct(): ProductBody {
  return { product_code: '', product_name: '', instrument_config_id: 1, description: '', test_items: [] }
}

function emptyItem(): TestItem {
  return { test_type: 'Turn', pins: '', description: '', lower_limit: null, upper_limit: null, standard_value: null, unit: null }
}

export default function AdminPage() {
  const qc = useQueryClient()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [isEdit, setIsEdit] = useState(false)
  const [form, setForm] = useState<ProductBody>(emptyProduct())

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: api.getProducts,
  })

  const saveMutation = useMutation({
    mutationFn: (data: ProductBody) =>
      isEdit ? api.updateProduct(data.product_code, data) : api.createProduct(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      setDrawerOpen(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: api.deleteProduct,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['products'] }),
  })

  function openCreate() {
    setForm(emptyProduct())
    setIsEdit(false)
    setDrawerOpen(true)
  }

  async function openEdit(code: string) {
    const product = await api.getProduct(code)
    setForm(product)
    setIsEdit(true)
    setDrawerOpen(true)
  }

  function updateItem(index: number, field: keyof TestItem, value: unknown) {
    const items = [...form.test_items]
    items[index] = { ...items[index], [field]: value }
    setForm(f => ({ ...f, test_items: items }))
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">产品配置管理</h2>
        <Button onClick={openCreate}>+ 新建产品</Button>
      </div>

      {isLoading ? (
        <p className="text-gray-500">加载中...</p>
      ) : (
        <table className="w-full text-sm border rounded">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr>
              <th className="text-left p-3">料号</th>
              <th className="text-left p-3">名称</th>
              <th className="text-center p-3">配置编号</th>
              <th className="text-center p-3">测试项数</th>
              <th className="text-right p-3">操作</th>
            </tr>
          </thead>
          <tbody>
            {products.map(p => (
              <tr key={p.product_code} className="border-t">
                <td className="p-3 font-mono">{p.product_code}</td>
                <td className="p-3">{p.product_name}</td>
                <td className="p-3 text-center">{p.instrument_config_id}</td>
                <td className="p-3 text-center">
                  <Badge variant="outline">{p.test_items_count} 项</Badge>
                </td>
                <td className="p-3 text-right space-x-2">
                  <Button size="sm" variant="outline" onClick={() => openEdit(p.product_code)}>编辑</Button>
                  <Button size="sm" variant="destructive"
                    onClick={() => { if (confirm(`删除 ${p.product_code}？`)) deleteMutation.mutate(p.product_code) }}>
                    删除
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} direction="right">
        <DrawerContent className="w-[700px] max-w-full h-full flex flex-col">
          <DrawerHeader>
            <DrawerTitle>{isEdit ? '编辑产品配置' : '新建产品配置'}</DrawerTitle>
          </DrawerHeader>

          <div className="flex-1 overflow-y-auto px-6 space-y-4">
            {/* 基本信息 */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>产品料号</Label>
                <Input value={form.product_code} disabled={isEdit}
                  onChange={e => setForm(f => ({ ...f, product_code: e.target.value }))} />
              </div>
              <div>
                <Label>产品名称</Label>
                <Input value={form.product_name}
                  onChange={e => setForm(f => ({ ...f, product_name: e.target.value }))} />
              </div>
              <div>
                <Label>仪器配置编号</Label>
                <Input type="number" value={form.instrument_config_id}
                  onChange={e => setForm(f => ({ ...f, instrument_config_id: +e.target.value }))} />
              </div>
              <div>
                <Label>描述（选填）</Label>
                <Input value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
              </div>
            </div>

            {/* 测试项 */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <Label className="text-base">测试项目（{form.test_items.length} 项）</Label>
                <Button size="sm" variant="outline"
                  onClick={() => setForm(f => ({ ...f, test_items: [...f.test_items, emptyItem()] }))}>
                  + 添加
                </Button>
              </div>

              <div className="border rounded overflow-auto max-h-96">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="p-2 text-left">类型</th>
                      <th className="p-2 text-left">引脚</th>
                      <th className="p-2 text-left">说明</th>
                      <th className="p-2 text-left">单位</th>
                      <th className="p-2 text-left">下限</th>
                      <th className="p-2 text-left">上限</th>
                      <th className="p-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.test_items.map((item, i) => (
                      <tr key={i} className="border-t">
                        <td className="p-1">
                          <Select value={item.test_type} onValueChange={v => updateItem(i, 'test_type', v)}>
                            <SelectTrigger className="h-7 text-xs w-20">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {TEST_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-1">
                          <Input className="h-7 text-xs w-16" value={item.pins}
                            onChange={e => updateItem(i, 'pins', e.target.value)} placeholder="3-1" />
                        </td>
                        <td className="p-1">
                          <Input className="h-7 text-xs w-28" value={item.description}
                            onChange={e => updateItem(i, 'description', e.target.value)} />
                        </td>
                        <td className="p-1">
                          <Select value={item.unit ?? ''} onValueChange={v => updateItem(i, 'unit', v || null)}>
                            <SelectTrigger className="h-7 text-xs w-16">
                              <SelectValue placeholder="-" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="">-</SelectItem>
                              {(UNITS[item.test_type] ?? []).map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-1">
                          <Input className="h-7 text-xs w-20" type="number" value={item.lower_limit ?? ''}
                            onChange={e => updateItem(i, 'lower_limit', e.target.value ? +e.target.value : null)} />
                        </td>
                        <td className="p-1">
                          <Input className="h-7 text-xs w-20" type="number" value={item.upper_limit ?? ''}
                            onChange={e => updateItem(i, 'upper_limit', e.target.value ? +e.target.value : null)} />
                        </td>
                        <td className="p-1">
                          <Button size="sm" variant="ghost" className="h-7 text-red-500 px-2"
                            onClick={() => setForm(f => ({ ...f, test_items: f.test_items.filter((_, j) => j !== i) }))}>
                            ×
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <DrawerFooter className="border-t">
            <Button onClick={() => saveMutation.mutate(form)} disabled={saveMutation.isPending}>
              {saveMutation.isPending ? '保存中...' : '保存'}
            </Button>
            <Button variant="outline" onClick={() => setDrawerOpen(false)}>取消</Button>
            {saveMutation.error && (
              <p className="text-red-500 text-sm">{(saveMutation.error as Error).message}</p>
            )}
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    </div>
  )
}
```

---

## 第七步：启动验证

```bash
# 终端1：启动后端
cd D:\code\autotest
python -m backend.main

# 终端2：启动前端
cd D:\code\autotest\frontend
npm run dev

# 浏览器打开
http://localhost:5173       测试页
http://localhost:5173/admin  管理页
```

---

## 注意事项

1. **shadcn 组件路径是 `@/components/ui/xxx`**，需要在 `vite.config.ts` 里配置路径别名：
   ```typescript
   resolve: {
     alias: { '@': path.resolve(__dirname, './src') }
   }
   ```
   并在 `tsconfig.json` 里加：
   ```json
   "paths": { "@/*": ["./src/*"] }
   ```

2. **测试页的"开始测试"按钮**：
   - `isReady` 的条件：`status.ready === true` 且 `status.product_code === selectedProduct`
   - 必须先初始化才能测试

3. **单位换算**在前端做，后端返回的都是 SI 单位（H, F, Ω）

4. **后端 API 地址**：通过 Vite proxy `/api` 转发到 `http://localhost:8000`，生产环境需要改

5. **仪器失去响应时**：可以在 TestPage 加一个"重新连接"按钮，调用 `POST /api/disconnect` 然后再 `POST /api/initialize`
