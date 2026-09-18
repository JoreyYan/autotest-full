import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { InspectionMeasurement, InspectionStep, ProductBody, TestItem } from "@/lib/api";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Drawer, DrawerContent, DrawerFooter, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const TEST_TYPES = ["Turn", "Lx", "Q", "Lk", "Cx", "Dcr"] as const;
const UNIT_OPTIONS: Record<string, string[]> = {
  Turn: [],
  Q: [],
  Lx: ["H", "mH", "uH", "nH"],
  Lk: ["H", "mH", "uH", "nH"],
  Cx: ["F", "mF", "uF", "nF", "pF"],
  Dcr: ["Ohm", "mOhm", "kOhm"],
};
const APERTURE_OPTIONS = ["FAST", "MED", "SLOW"] as const;

function emptyTestItem(): TestItem {
  return { test_type: "Turn", pins: "", description: "", symbol: null, lower_limit: null, upper_limit: null, standard_value: null, unit: null, tolerance_mode: "pm", tolerance_pct: null };
}

function emptyInspectionMeasurement(): InspectionMeasurement {
  return { name: "", function_code: "LSRS", frequency_hz: 100000, voltage_v: 1, aperture_mode: "MED", average_count: 1, primary_label: "Ls", primary_unit: "uH", primary_lower: null, primary_upper: null, secondary_label: "Rs", secondary_unit: "Ohm", secondary_lower: null, secondary_upper: null };
}

function emptyInspectionStep(): InspectionStep {
  return { pins: "", prompt: "", measurements: [emptyInspectionMeasurement()] };
}

function emptyProduct(): ProductBody {
  return { product_code: "", product_name: "", instrument_config_id: 1, instrument_driver: "uce", workflow_type: "fixture_test", description: "", test_items: [], inspection_steps: [], enable_eq_n: false, eq_n_vars: { l_raw: "A", lk_raw: "B", l_aux: "C" }, require_record_number: true, require_core_number: false };
}

function indexToSymbol(index: number): string {
  let n = index;
  let out = "";
  do {
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}

function ensureSymbols(items: TestItem[]): TestItem[] {
  return items.map((item, i) => ({ ...item, symbol: (item.symbol ?? "").trim().toUpperCase() || indexToSymbol(i) }));
}

function splitPins(pins: string): [string, string] {
  const [left, right] = pins.split("-");
  return [left ?? "", right ?? ""];
}

function joinPins(left: string, right: string) {
  const a = left.trim();
  const b = right.trim();
  if (!a && !b) return "";
  return `${a}-${b}`;
}

function round6(value: number) {
  return Number(value.toFixed(6));
}

function workflowLabel(value?: string) {
  return value === "incoming_inspection" ? "入料检验" : "成品测试";
}

// 最近成功时间:后端可能给字符串(原样/ISO)或时间戳(秒/毫秒),都转成本地时间显示
function formatCloudTime(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无";
  const pad = (n: number) => String(n).padStart(2, "0");
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  if (typeof value === "number" && Number.isFinite(value)) return fmt(new Date(value > 1e12 ? value : value * 1000));
  if (typeof value === "string") {
    if (value.includes("T")) {
      const d = new Date(value);
      if (!Number.isNaN(d.getTime())) return fmt(d);
    }
    return value;
  }
  return "暂无";
}

/** 新码直推云端状态(只读):每 30 秒刷新一次;接口不可用时什么都不显示,不影响页面。 */
function CloudUploadStatusLine() {
  const { data, isError } = useQuery({
    queryKey: ["cloud-upload-status"],
    queryFn: api.getCloudUploadStatus,
    refetchInterval: 30000,
    retry: false,
  });
  if (isError || !data || typeof data !== "object") return null;
  const pending = Number(data.pending) || 0;
  const rejected = Number(data.rejected) || 0;
  const tip = [data.url ? `地址：${data.url}` : "", data.last_error ? `最近错误：${data.last_error}` : ""].filter(Boolean).join("\n");
  return (
    <div className="text-sm text-muted-foreground" title={tip || undefined}>
      新码直推云端：待传 {pending} 条 · 退回 {rejected} 条 · 最近成功 {formatCloudTime(data.last_ok_at)}
    </div>
  );
}

export default function AdminPage() {
  const qc = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isEdit, setIsEdit] = useState(false);
  const [form, setForm] = useState<ProductBody>(emptyProduct());
  const [keyword, setKeyword] = useState("");

  const { data: products = [], isLoading } = useQuery({ queryKey: ["products"], queryFn: api.getProducts });
  const saveMutation = useMutation({ mutationFn: (data: ProductBody) => (isEdit ? api.updateProduct(data.product_code, data) : api.createProduct(data)), onSuccess: () => { qc.invalidateQueries({ queryKey: ["products"] }); setDrawerOpen(false); } });
  const deleteMutation = useMutation({ mutationFn: api.deleteProduct, onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }) });
  const syncParamsMutation = useMutation({
    mutationFn: api.syncParams,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return products;
    return products.filter((p) => p.product_code.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q));
  }, [keyword, products]);

  function openCreate() {
    setForm(emptyProduct());
    setIsEdit(false);
    setDrawerOpen(true);
  }

  async function openEdit(code: string) {
    const product = await api.getProduct(code);
    setForm({
      ...emptyProduct(),
      ...product,
      workflow_type: product.workflow_type ?? "fixture_test",
      instrument_driver: product.instrument_driver ?? (product.workflow_type === "incoming_inspection" ? "lcr_2836" : "uce"),
      inspection_steps: Array.isArray(product.inspection_steps)
        ? product.inspection_steps.map((step) => ({
            pins: step?.pins ?? "",
            prompt: step?.prompt ?? "",
            measurements:
              Array.isArray(step?.measurements) && step.measurements.length > 0
                ? step.measurements.map((measurement) => ({
                    ...emptyInspectionMeasurement(),
                    ...measurement,
                  }))
                : [emptyInspectionMeasurement()],
          }))
        : [],
      test_items: ensureSymbols(product.test_items ?? []),
      enable_eq_n: Boolean(product.enable_eq_n),
      eq_n_vars: { l_raw: product.eq_n_vars?.l_raw ?? "A", lk_raw: product.eq_n_vars?.lk_raw ?? "B", l_aux: product.eq_n_vars?.l_aux ?? "C", n_standard: product.eq_n_vars?.n_standard, n_tolerance_pct: product.eq_n_vars?.n_tolerance_pct, n_lower: product.eq_n_vars?.n_lower, n_upper: product.eq_n_vars?.n_upper },
      require_record_number: product.require_record_number !== false,
      require_core_number: Boolean(product.require_core_number),
    });
    setIsEdit(true);
    setDrawerOpen(true);
  }

  async function openCopy(code: string) {
    const product = await api.getProduct(code);
    setForm({
      ...emptyProduct(),
      ...product,
      product_code: "",                    // 料号清空，强制用户填新的
      product_name: product.product_name ? `${product.product_name}（副本）` : "",
      workflow_type: product.workflow_type ?? "fixture_test",
      instrument_driver: product.instrument_driver ?? (product.workflow_type === "incoming_inspection" ? "lcr_2836" : "uce"),
      inspection_steps: Array.isArray(product.inspection_steps)
        ? product.inspection_steps.map((step) => ({
            pins: step?.pins ?? "",
            prompt: step?.prompt ?? "",
            measurements:
              Array.isArray(step?.measurements) && step.measurements.length > 0
                ? step.measurements.map((measurement) => ({ ...emptyInspectionMeasurement(), ...measurement }))
                : [emptyInspectionMeasurement()],
          }))
        : [],
      test_items: ensureSymbols(product.test_items ?? []),
      enable_eq_n: Boolean(product.enable_eq_n),
      eq_n_vars: { l_raw: product.eq_n_vars?.l_raw ?? "A", lk_raw: product.eq_n_vars?.lk_raw ?? "B", l_aux: product.eq_n_vars?.l_aux ?? "C", n_standard: product.eq_n_vars?.n_standard, n_tolerance_pct: product.eq_n_vars?.n_tolerance_pct, n_lower: product.eq_n_vars?.n_lower, n_upper: product.eq_n_vars?.n_upper },
      require_record_number: product.require_record_number !== false,
      require_core_number: Boolean(product.require_core_number),
    });
    setIsEdit(false);                      // 走"新建"流程，提交后会创建新产品
    setDrawerOpen(true);
  }

  function setWorkflowType(value: string) {
    setForm((prev) => ({
      ...prev,
      workflow_type: value,
      instrument_driver: value === "incoming_inspection" ? "lcr_2836" : "uce",
      instrument_config_id: value === "incoming_inspection" ? 0 : Math.max(1, prev.instrument_config_id || 1),
      test_items: value === "fixture_test" ? prev.test_items : [],
      inspection_steps: value === "incoming_inspection" ? (prev.inspection_steps?.length ? prev.inspection_steps : [emptyInspectionStep()]) : [],
      enable_eq_n: value === "fixture_test" ? prev.enable_eq_n : false,
    }));
  }

  function updateTestItem(index: number, patch: Partial<TestItem>) {
    setForm((prev) => {
      const test_items = [...prev.test_items];
      test_items[index] = { ...test_items[index], ...patch };
      return { ...prev, test_items };
    });
  }

  function recalcLimits(index: number, patch: Partial<TestItem>) {
    setForm((prev) => {
      const test_items = [...prev.test_items];
      const next = { ...test_items[index], ...patch };
      const center = typeof next.standard_value === "number" ? next.standard_value : null;
      const mode = next.tolerance_mode ?? "pm";
      if (mode === "pm") {
        const pct = typeof next.tolerance_pct === "number" ? next.tolerance_pct : null;
        if (center != null && pct != null) {
          const delta = Math.abs(center) * (pct / 100);
          next.lower_limit = round6(center - delta);
          next.upper_limit = round6(center + delta);
        } else {
          next.lower_limit = null;
          next.upper_limit = null;
        }
      } else if (mode === "max") {
        next.tolerance_pct = null;
        next.lower_limit = null;
        next.upper_limit = center != null ? round6(center) : null;
      } else {
        next.tolerance_pct = null;
        next.lower_limit = center != null ? round6(center) : null;
        next.upper_limit = null;
      }
      test_items[index] = next;
      return { ...prev, test_items };
    });
  }
  function updateInspectionStep(stepIndex: number, patch: Partial<InspectionStep>) {
    setForm((prev) => {
      const inspection_steps = [...(prev.inspection_steps ?? [])];
      inspection_steps[stepIndex] = { ...inspection_steps[stepIndex], ...patch };
      return { ...prev, inspection_steps };
    });
  }

  function updateInspectionMeasurement(stepIndex: number, measurementIndex: number, patch: Partial<InspectionMeasurement>) {
    setForm((prev) => {
      const inspection_steps = [...(prev.inspection_steps ?? [])];
      const step = inspection_steps[stepIndex];
      const measurements = [...step.measurements];
      measurements[measurementIndex] = { ...measurements[measurementIndex], ...patch };
      inspection_steps[stepIndex] = { ...step, measurements };
      return { ...prev, inspection_steps };
    });
  }

  function buildPayload(): ProductBody {
    const workflow_type = form.workflow_type ?? "fixture_test";
    return {
      ...form,
      workflow_type,
      instrument_driver: workflow_type === "incoming_inspection" ? "lcr_2836" : "uce",
      instrument_config_id: workflow_type === "incoming_inspection" ? 0 : Number(form.instrument_config_id || 1),
      test_items: workflow_type === "fixture_test" ? ensureSymbols(form.test_items) : [],
      inspection_steps: workflow_type === "incoming_inspection" ? (form.inspection_steps ?? []) : [],
      enable_eq_n: workflow_type === "fixture_test" ? Boolean(form.enable_eq_n) : false,
      eq_n_vars: {
        l_raw: (form.eq_n_vars?.l_raw ?? "A").trim().toUpperCase() || "A",
        lk_raw: (form.eq_n_vars?.lk_raw ?? "B").trim().toUpperCase() || "B",
        l_aux: (form.eq_n_vars?.l_aux ?? "C").trim().toUpperCase() || "C",
        n_standard: form.eq_n_vars?.n_standard,
        n_tolerance_pct: form.eq_n_vars?.n_tolerance_pct,
        n_lower: form.eq_n_vars?.n_lower,
        n_upper: form.eq_n_vars?.n_upper,
      },
      require_record_number: form.require_record_number !== false,
      require_core_number: Boolean(form.require_core_number),
    };
  }

  return (
    <div className="space-y-6">
      <CloudUploadStatusLine />
      <div className="grid gap-4 md:grid-cols-[1.4fr_0.6fr]">
        <Card className="panel">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>产品参数（只读）</span>
              <Button
                variant="outline"
                disabled={syncParamsMutation.isPending}
                onClick={() => syncParamsMutation.mutate()}
              >
                {syncParamsMutation.isPending ? "同步中..." : "同步参数"}
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border bg-amber-50 border-amber-200 text-amber-800 text-sm p-3">
              ⚠️ 参数由 ERP 统一管理，本机<b>只读、不可编辑</b>。如需修改中心值/公差，请在 ERP「工位参数下发」调整，改后点上方「同步参数」拉取。
            </div>
            {syncParamsMutation.data && (
              <div className="rounded-lg border bg-emerald-50 border-emerald-200 text-emerald-700 text-sm p-3">
                同步完成：更新 {syncParamsMutation.data.updated.length} 个
                {syncParamsMutation.data.updated.length > 0 && `（${syncParamsMutation.data.updated.map((u) => `${u.product_code} v${u.version}`).join("、")}）`}
                {syncParamsMutation.data.archived.length > 0 && `，归档未下发 ${syncParamsMutation.data.archived.length} 个`}
                {syncParamsMutation.data.updated.length === 0 && syncParamsMutation.data.archived.length === 0 &&
                  `，已是最新${(syncParamsMutation.data as any).local_versions ? `（${Object.entries((syncParamsMutation.data as any).local_versions).map(([c, v]) => `${c} v${v}`).join("、")}）` : ""}`}
              </div>
            )}
            {syncParamsMutation.error && (
              <div className="rounded-lg border bg-rose-50 border-rose-200 text-rose-700 text-sm p-3">
                同步失败：{(syncParamsMutation.error as Error).message}
              </div>
            )}
            <div className="flex items-center justify-between gap-3">
              <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索料号或名称" className="max-w-xs" />
              <div className="text-sm text-muted-foreground">共 {products.length} 个产品，当前显示 {filtered.length} 个</div>
            </div>

            {isLoading ? (
              <div className="text-sm text-muted-foreground">加载中...</div>
            ) : (
              <div className="overflow-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-secondary">
                      <TableHead>料号</TableHead>
                      <TableHead>名称</TableHead>
                      <TableHead>流程</TableHead>
                      <TableHead>设备</TableHead>
                      <TableHead className="text-center">配置号</TableHead>
                      <TableHead className="text-center">项目数</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((p) => {
                      const workflow_type = p.workflow_type ?? "fixture_test";
                      const count = workflow_type === "incoming_inspection" ? p.inspection_steps_count ?? p.inspection_steps?.length ?? 0 : p.test_items_count ?? p.test_items?.length ?? 0;
                      return (
                        <TableRow key={p.product_code}>
                          <TableCell className="font-mono font-medium">{p.product_code}</TableCell>
                          <TableCell>{p.product_name}</TableCell>
                          <TableCell><Badge variant="outline">{workflowLabel(workflow_type)}</Badge></TableCell>
                          <TableCell><Badge variant="secondary">{p.instrument_driver ?? (workflow_type === "incoming_inspection" ? "lcr_2836" : "uce")}</Badge></TableCell>
                          <TableCell className="text-center">{p.instrument_config_id ?? 0}</TableCell>
                          <TableCell className="text-center">{count}</TableCell>
                          <TableCell className="text-right">
                            <Button size="sm" variant="ghost" onClick={() => openEdit(p.product_code)}>查看</Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="panel">
          <CardHeader><CardTitle>配置说明</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="rounded-lg border p-3 bg-secondary">成品测试使用治具配置号与测试项。</div>
            <div className="rounded-lg border p-3 bg-secondary">入料检验使用脚位步骤，每个脚位下可以配置多个测量项目。</div>
            <div className="rounded-lg border p-3 bg-secondary">设备会跟随流程类型自动切换：成品测试用 uce，入料检验用 lcr_2836。</div>
          </CardContent>
        </Card>
      </div>

      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} direction="right" modal={false}>
        <DrawerContent className="w-[92vw] max-w-none h-full flex flex-col ml-auto">
          <DrawerHeader><DrawerTitle>查看产品参数（只读 · 由 ERP 管理）</DrawerTitle></DrawerHeader>
          <div className="flex-1 overflow-y-auto px-6 space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div><Label>产品料号</Label><Input value={form.product_code} disabled={isEdit} onChange={(e) => setForm((prev) => ({ ...prev, product_code: e.target.value }))} /></div>
              <div><Label>产品名称</Label><Input value={form.product_name} onChange={(e) => setForm((prev) => ({ ...prev, product_name: e.target.value }))} /></div>
              <div>
                <Label>流程类型</Label>
                <select className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.workflow_type ?? "fixture_test"} onChange={(e) => setWorkflowType(e.target.value)}>
                  <option value="fixture_test">成品测试</option>
                  <option value="incoming_inspection">入料检验</option>
                </select>
              </div>
              <div>
                <Label>设备类型</Label>
                <Input className="mt-2" value={form.workflow_type === "incoming_inspection" ? "lcr_2836" : "uce"} readOnly />
              </div>
              <div>
                <Label>仪器配置号</Label>
                <Input className="mt-2" type="number" value={form.workflow_type === "incoming_inspection" ? 0 : form.instrument_config_id} disabled={form.workflow_type === "incoming_inspection"} onChange={(e) => setForm((prev) => ({ ...prev, instrument_config_id: Number(e.target.value || 0) }))} />
              </div>
              <div><Label>描述</Label><Input className="mt-2" value={form.description} onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))} /></div>
            </div>
            {form.workflow_type === "fixture_test" ? (
              <>
                <div className="rounded-lg border p-4 space-y-2">
                  <Label className="font-medium">非扫码模式必填项</Label>
                  <div className="flex items-center gap-6">
                    <div className="flex items-center gap-2">
                      <input id="require_record_number" type="checkbox" checked={form.require_record_number !== false} onChange={(e) => setForm((prev) => ({ ...prev, require_record_number: e.target.checked }))} />
                      <Label htmlFor="require_record_number">必填序号</Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <input id="require_core_number" type="checkbox" checked={Boolean(form.require_core_number)} onChange={(e) => setForm((prev) => ({ ...prev, require_core_number: e.target.checked }))} />
                      <Label htmlFor="require_core_number">必填磁芯编号</Label>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">扫码枪模式不受此设置影响</p>
                </div>
                <div className="rounded-lg border p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <input id="enable_eq_n" type="checkbox" checked={Boolean(form.enable_eq_n)} onChange={(e) => setForm((prev) => ({ ...prev, enable_eq_n: e.target.checked }))} />
                    <Label htmlFor="enable_eq_n">启用等效 n 计算</Label>
                  </div>
                  <p className="text-xs text-muted-foreground ml-6">n = √((A − B) / C)，其中 A = 原边电感，B = 原边漏感，C = 副边电感（对应测试项的变量符号）</p>
                  <div className="flex items-center gap-4 ml-6 flex-wrap">
                    <div className="flex items-center gap-2">
                      <Label className={!form.enable_eq_n ? "text-muted-foreground" : ""}>N 标称值</Label>
                      <Input className="w-28" type="number" step="any" disabled={!form.enable_eq_n} value={form.eq_n_vars?.n_standard ?? ""} onChange={(e) => setForm((prev) => {
                        const std = e.target.value ? Number(e.target.value) : undefined;
                        const pct = prev.eq_n_vars?.n_tolerance_pct;
                        const lo = std != null && pct != null ? std * (1 - pct / 100) : prev.eq_n_vars?.n_lower;
                        const hi = std != null && pct != null ? std * (1 + pct / 100) : prev.eq_n_vars?.n_upper;
                        return { ...prev, eq_n_vars: { ...prev.eq_n_vars, n_standard: std, n_lower: lo, n_upper: hi } };
                      })} placeholder="必填" />
                    </div>
                    <div className="flex items-center gap-2">
                      <Label className={!form.enable_eq_n ? "text-muted-foreground" : ""}>误差(%)</Label>
                      <Input className="w-20" type="number" step="any" disabled={!form.enable_eq_n} value={form.eq_n_vars?.n_tolerance_pct ?? ""} onChange={(e) => setForm((prev) => {
                        const pct = e.target.value ? Number(e.target.value) : undefined;
                        const std = prev.eq_n_vars?.n_standard;
                        const lo = std != null && pct != null ? std * (1 - pct / 100) : prev.eq_n_vars?.n_lower;
                        const hi = std != null && pct != null ? std * (1 + pct / 100) : prev.eq_n_vars?.n_upper;
                        return { ...prev, eq_n_vars: { ...prev.eq_n_vars, n_tolerance_pct: pct, n_lower: lo, n_upper: hi } };
                      })} placeholder="必填" />
                    </div>
                    <div className="flex items-center gap-2">
                      <Label className={!form.enable_eq_n ? "text-muted-foreground" : ""}>N 下限</Label>
                      <Input className="w-28" type="number" step="any" disabled={!form.enable_eq_n} value={form.eq_n_vars?.n_lower ?? ""} readOnly />
                    </div>
                    <div className="flex items-center gap-2">
                      <Label className={!form.enable_eq_n ? "text-muted-foreground" : ""}>N 上限</Label>
                      <Input className="w-28" type="number" step="any" disabled={!form.enable_eq_n} value={form.eq_n_vars?.n_upper ?? ""} readOnly />
                    </div>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="flex items-center justify-between"><Label className="text-base">测试项目（{form.test_items.length} 项）</Label><Button size="sm" variant="outline" onClick={() => setForm((prev) => ({ ...prev, test_items: ensureSymbols([...(prev.test_items ?? []), emptyTestItem()]) }))}>添加测试项</Button></div>
                  {form.test_items.map((item, index) => {
                    const [leftPin, rightPin] = splitPins(item.pins);
                    return (
                      <div key={index} className="rounded-lg border p-4 grid grid-cols-6 gap-3 items-end">
                        <div><Label>变量</Label><Input className="mt-2" value={(item.symbol ?? "").toUpperCase()} onChange={(e) => updateTestItem(index, { symbol: e.target.value.toUpperCase() })} placeholder={indexToSymbol(index)} /></div>
                        <div><Label>类型</Label><select className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={item.test_type} onChange={(e) => updateTestItem(index, { test_type: e.target.value, unit: null })}>{TEST_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></div>
                        <div>
                          <Label>引脚</Label>
                          <div className="mt-2 flex items-center gap-1">
                            <Input value={leftPin} onChange={(e) => updateTestItem(index, { pins: joinPins(e.target.value, rightPin) })} />
                            <span>-</span>
                            <Input value={rightPin} onChange={(e) => updateTestItem(index, { pins: joinPins(leftPin, e.target.value) })} />
                          </div>
                        </div>
                        <div><Label>说明</Label><Input className="mt-2" value={item.description} onChange={(e) => updateTestItem(index, { description: e.target.value })} /></div>
                        <div><Label>单位</Label><select className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={item.unit ?? ""} onChange={(e) => updateTestItem(index, { unit: e.target.value || null })}><option value="">-</option>{(UNIT_OPTIONS[item.test_type] ?? []).map((unit) => <option key={unit} value={unit}>{unit}</option>)}</select></div>
                        <div className="text-right"><Button size="sm" variant="ghost" className="text-destructive" onClick={() => setForm((prev) => ({ ...prev, test_items: prev.test_items.filter((_, rowIndex) => rowIndex !== index) }))}>删除</Button></div>
                        <div><Label>误差方式</Label><select className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={item.tolerance_mode ?? "pm"} onChange={(e) => recalcLimits(index, { tolerance_mode: e.target.value as TestItem["tolerance_mode"] })}><option value="pm">±</option><option value="max">max</option><option value="min">min</option></select></div>
                        <div><Label>中心值</Label><Input className="mt-2" type="number" value={item.standard_value ?? ""} onChange={(e) => recalcLimits(index, { standard_value: e.target.value ? Number(e.target.value) : null })} /></div>
                        <div><Label>误差(%)</Label><Input className="mt-2" type="number" disabled={(item.tolerance_mode ?? "pm") !== "pm"} value={item.tolerance_pct ?? ""} onChange={(e) => recalcLimits(index, { tolerance_pct: e.target.value ? Number(e.target.value) : null })} /></div>
                        <div><Label>下限</Label><Input className="mt-2" type="number" value={item.lower_limit ?? ""} readOnly /></div>
                        <div><Label>上限</Label><Input className="mt-2" type="number" value={item.upper_limit ?? ""} readOnly /></div>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="space-y-4 pb-6">
                <div className="flex items-center justify-between"><Label className="text-base">入料检验步骤（{form.inspection_steps?.length ?? 0} 个脚位）</Label><Button size="sm" variant="outline" onClick={() => setForm((prev) => ({ ...prev, inspection_steps: [...(prev.inspection_steps ?? []), emptyInspectionStep()] }))}>添加脚位步骤</Button></div>
                {(form.inspection_steps ?? []).map((step, stepIndex) => {
                  const [leftPin, rightPin] = splitPins(step.pins);
                  return (
                    <Card key={stepIndex} className="border-dashed">
                      <CardHeader className="pb-3"><CardTitle className="flex items-center justify-between text-base"><span>脚位步骤 {stepIndex + 1}</span><Button size="sm" variant="ghost" className="text-destructive" onClick={() => setForm((prev) => ({ ...prev, inspection_steps: (prev.inspection_steps ?? []).filter((_, idx) => idx !== stepIndex) }))}>删除脚位</Button></CardTitle></CardHeader>
                      <CardContent className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                          <div><Label>脚位</Label><div className="mt-2 flex items-center gap-1"><Input value={leftPin} onChange={(e) => updateInspectionStep(stepIndex, { pins: joinPins(e.target.value, rightPin) })} /><span>-</span><Input value={rightPin} onChange={(e) => updateInspectionStep(stepIndex, { pins: joinPins(leftPin, e.target.value) })} /></div></div>
                          <div><Label>提示语</Label><Input className="mt-2" value={step.prompt ?? ""} onChange={(e) => updateInspectionStep(stepIndex, { prompt: e.target.value })} placeholder="例如：请测量 1-3 脚位" /></div>
                        </div>
                        <div className="flex items-center justify-between"><Label>测量项目（{step.measurements.length} 个）</Label><Button size="sm" variant="outline" onClick={() => updateInspectionStep(stepIndex, { measurements: [...step.measurements, emptyInspectionMeasurement()] })}>添加测量项目</Button></div>
                        {step.measurements.map((measurement, measurementIndex) => (
                          <div key={measurementIndex} className="rounded-lg border p-4 space-y-3">
                            <div className="flex items-center justify-between"><div className="font-medium">项目 {measurementIndex + 1}</div><Button size="sm" variant="ghost" className="text-destructive" onClick={() => updateInspectionStep(stepIndex, { measurements: step.measurements.filter((_, idx) => idx !== measurementIndex) })} disabled={step.measurements.length === 1}>删除项目</Button></div>
                            <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
                              <div><Label>项目名称</Label><Input className="mt-2" value={measurement.name} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { name: e.target.value })} /></div>
                              <div><Label>功能</Label><select className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={measurement.function_code} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { function_code: e.target.value })}><option value="LSRS">LSRS</option><option value="LSQ">LSQ</option><option value="LPQ">LPQ</option><option value="LPD">LPD</option><option value="LSDCR">LSDCR</option><option value="CPD">CPD</option><option value="CPQ">CPQ</option><option value="CSRS">CSRS</option><option value="RX">RX</option><option value="DCR">DCR</option></select></div>
                              <div><Label>频率(Hz)</Label><Input className="mt-2" type="number" value={measurement.frequency_hz ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { frequency_hz: e.target.value ? Number(e.target.value) : null })} /></div>
                              <div><Label>电压(V)</Label><Input className="mt-2" type="number" value={measurement.voltage_v ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { voltage_v: e.target.value ? Number(e.target.value) : null })} /></div>
                              <div><Label>速度</Label><select className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={measurement.aperture_mode ?? "MED"} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { aperture_mode: e.target.value })}>{APERTURE_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}</select></div>
                              <div><Label>平均次数</Label><Input className="mt-2" type="number" value={measurement.average_count ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { average_count: e.target.value ? Number(e.target.value) : null })} /></div>
                              <div><Label>主参数标签</Label><Input className="mt-2" value={measurement.primary_label ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { primary_label: e.target.value })} /></div>
                              <div><Label>主参数单位</Label><Input className="mt-2" value={measurement.primary_unit ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { primary_unit: e.target.value })} /></div>
                              <div><Label>主参数下限</Label><Input className="mt-2" type="number" value={measurement.primary_lower ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { primary_lower: e.target.value ? Number(e.target.value) : null })} /></div>
                              <div><Label>主参数上限</Label><Input className="mt-2" type="number" value={measurement.primary_upper ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { primary_upper: e.target.value ? Number(e.target.value) : null })} /></div>
                              <div><Label>副参数标签</Label><Input className="mt-2" value={measurement.secondary_label ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { secondary_label: e.target.value })} /></div>
                              <div><Label>副参数单位</Label><Input className="mt-2" value={measurement.secondary_unit ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { secondary_unit: e.target.value })} /></div>
                              <div><Label>副参数下限</Label><Input className="mt-2" type="number" value={measurement.secondary_lower ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { secondary_lower: e.target.value ? Number(e.target.value) : null })} /></div>
                              <div><Label>副参数上限</Label><Input className="mt-2" type="number" value={measurement.secondary_upper ?? ""} onChange={(e) => updateInspectionMeasurement(stepIndex, measurementIndex, { secondary_upper: e.target.value ? Number(e.target.value) : null })} /></div>
                            </div>
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
          <DrawerFooter className="border-t mt-auto">
            <p className="text-xs text-amber-700">参数只读，由 ERP 统一管理。如需修改请在 ERP「工位参数下发」调整后同步。</p>
            <Button variant="outline" onClick={() => setDrawerOpen(false)}>关闭</Button>
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    </div>
  );
}
