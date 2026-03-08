import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, type TestResult, type MeasuredItem, type InitStatus, type LogItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";

function normalizeUnit(unit: string): string {
  return unit.replace("μ", "u").replace("渭", "u").replace("惟", "Ohm");
}

function convertSiToUnit(value: number, unit?: string | null): number {
  if (!unit) return value;
  const u = normalizeUnit(unit);
  if (u === "H") return value;
  if (u === "mH") return value * 1e3;
  if (u === "uH") return value * 1e6;
  if (u === "nH") return value * 1e9;
  if (u === "F") return value;
  if (u === "mF") return value * 1e3;
  if (u === "uF") return value * 1e6;
  if (u === "nF") return value * 1e9;
  if (u === "pF") return value * 1e12;
  if (u === "Ohm") return value;
  if (u === "mOhm") return value * 1e3;
  if (u === "kOhm") return value / 1e3;
  return value;
}

function formatDisplayValue(item: MeasuredItem, unit?: string | null): string {
  if (item.error) return `ERR(${item.error})`;
  const u = item.unit ?? unit ?? null;
  const hasDisplay = typeof item.value_display === "number" && !Number.isNaN(item.value_display);
  if (!hasDisplay && (typeof item.value !== "number" || Number.isNaN(item.value))) return "ERR";
  const converted = hasDisplay ? (item.value_display as number) : convertSiToUnit(item.value, u);
  if (item.type === "Turn" || item.type === "Q" || !u) return Number(converted.toFixed(6)).toString();
  return `${Number(converted.toFixed(6)).toString()} ${normalizeUnit(u)}`;
}

function typeLabel(type: string): string {
  return type === "EqN" ? "等效n" : type;
}

function limitText(value: number | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return unit ? `${value} ${unit}` : `${value}`;
}

function renderConfigCheck(initData?: InitStatus) {
  if (!initData?.config_check) return null;
  const { ok, missing, extra } = initData.config_check;
  return (
    <div className={`rounded-lg border p-3 text-sm ${ok ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-amber-50 border-amber-200 text-amber-700"}`}>
      <div className="font-medium">{ok ? "配置校验通过" : "配置校验提醒"}</div>
      {!ok && (
        <div className="mt-2 space-y-1">
          {missing.length > 0 && <div>缺少项：{missing.join(", ")}</div>}
          {extra.length > 0 && <div>多余项：{extra.join(", ")}</div>}
        </div>
      )}
    </div>
  );
}

function getRealtimeState(args: { hasPort: boolean; ready: boolean; initPending: boolean; testPending: boolean }) {
  if (args.initPending) return { text: "扫描端口并建立连接中...", dot: "bg-amber-500" };
  if (args.testPending) return { text: "测试执行中...", dot: "bg-blue-500" };
  if (args.ready) return { text: "设备就绪", dot: "bg-emerald-500" };
  if (args.hasPort) return { text: "已连接但未就绪", dot: "bg-orange-500" };
  return { text: "未连接", dot: "bg-red-500" };
}

const TYPE_ORDER = ["Turn", "Lx", "Q", "Lk", "Cx", "Dcr"];

export default function TestPage() {
  const [activeTab, setActiveTab] = useState("console");
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [lastResult, setLastResult] = useState<TestResult | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [logCursor, setLogCursor] = useState(0);
  const [showLimits, setShowLimits] = useState(false);

  const { data: products = [] } = useQuery({ queryKey: ["products"], queryFn: api.getProducts });
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 2000,
  });
  const { data: results = [] } = useQuery({
    queryKey: ["results"],
    queryFn: api.getResults,
    refetchInterval: 10000,
  });
  const { data: productDetail } = useQuery({
    queryKey: ["product-detail", selectedProduct],
    queryFn: () => api.getProduct(selectedProduct),
    enabled: Boolean(selectedProduct),
  });

  const logsQuery = useQuery({
    queryKey: ["logs", logCursor],
    queryFn: () => api.getLogs(logCursor),
    refetchInterval: 1000,
  });

  useEffect(() => {
    const data = logsQuery.data;
    if (!data) return;
    if (data.last_id < logCursor) {
      setLogCursor(0);
      setLogs([]);
      return;
    }
    if (data.items.length > 0) {
      setLogs((prev) => [...prev, ...data.items].slice(-300));
    }
    setLogCursor(data.last_id);
  }, [logsQuery.data, logCursor]);

  const initMutation = useMutation({
    mutationFn: () => api.initialize(selectedProduct),
    onMutate: () => {
      setLogs([]);
      setLogCursor(0);
    },
    onSuccess: () => refetchStatus(),
  });

  const testMutation = useMutation({
    mutationFn: api.runTest,
    onSuccess: (data) => {
      setLastResult(data);
      setActiveTab("test");
    },
  });
  const disconnectMutation = useMutation({ mutationFn: api.disconnect, onSuccess: () => refetchStatus() });

  const isReady = Boolean(status?.ready && status?.product_code === selectedProduct);
  const selectedName = useMemo(
    () => products.find((p) => p.product_code === selectedProduct)?.product_name,
    [products, selectedProduct]
  );

  const hasPort = Boolean(status?.port);
  const realtime = getRealtimeState({
    hasPort,
    ready: Boolean(status?.ready),
    initPending: initMutation.isPending,
    testPending: testMutation.isPending,
  });

  const matrixTypes = useMemo(() => {
    if (!lastResult) return TYPE_ORDER;
    const existing = new Set(lastResult.items.map((x) => x.type));
    const ordered = TYPE_ORDER.filter((t) => existing.has(t));
    const extra = Array.from(existing).filter((t) => !TYPE_ORDER.includes(t));
    return [...ordered, ...extra];
  }, [lastResult]);

  const matrixRows = useMemo(() => {
    if (!lastResult) return [] as string[];
    const set = new Set(lastResult.items.map((x) => x.pins));
    return Array.from(set);
  }, [lastResult]);

  const matrix = useMemo(() => {
    const m = new Map<string, MeasuredItem>();
    if (!lastResult) return m;
    for (const item of lastResult.items) {
      m.set(`${item.pins}::${item.type}`, item);
    }
    return m;
  }, [lastResult]);

  const typeUnits = useMemo(() => {
    const m = new Map<string, string | null>();
    const items = productDetail?.test_items ?? [];
    for (const t of matrixTypes) {
      const found = items.find((x) => x.test_type === t && x.unit);
      m.set(t, found?.unit ?? null);
    }
    return m;
  }, [productDetail, matrixTypes]);

  const overall = useMemo(() => {
    if (!lastResult) return "-";
    return lastResult.items.some((x) => x.result !== "Pass") ? "FAIL" : "PASS";
  }, [lastResult]);

  const statusBadge = (
    <div className="flex items-center gap-2">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${status?.ready ? "bg-emerald-500" : hasPort ? "bg-orange-500" : "bg-red-500"}`} />
      <Badge variant={status?.ready ? "default" : "secondary"} className="text-xs">
        {status?.ready ? `连接状态：就绪 · ${status?.port}` : hasPort ? `连接状态：已连接(未就绪) · ${status?.port}` : "连接状态：未连接"}
      </Badge>
    </div>
  );

  return (
    <div className="space-y-6">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="console">控制台</TabsTrigger>
          <TabsTrigger value="test">测试</TabsTrigger>
          <TabsTrigger value="files">最近文件</TabsTrigger>
          <TabsTrigger value="logs">日志</TabsTrigger>
        </TabsList>

        <TabsContent value="console" className="space-y-6 mt-4">
          <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <Card className="panel">
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>测试控制台</span>
                  {statusBadge}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-4 md:grid-cols-[1fr_auto] items-end">
                  <div>
                    <label className="text-sm font-medium mb-2 block">选择产品</label>
                    <Select value={selectedProduct} onValueChange={setSelectedProduct}>
                      <SelectTrigger className="h-11">
                        <SelectValue placeholder="请选择产品..." />
                      </SelectTrigger>
                      <SelectContent>
                        {products.map((p) => (
                          <SelectItem key={p.product_code} value={p.product_code}>
                            {p.product_code} - {p.product_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex gap-2">
                    <Button className="h-11 px-6" onClick={() => initMutation.mutate()} disabled={!selectedProduct || initMutation.isPending}>
                      {initMutation.isPending ? "初始化中..." : "初始化连接"}
                    </Button>
                    <Button className="h-11" variant="outline" onClick={() => disconnectMutation.mutate()} disabled={disconnectMutation.isPending}>
                      断开
                    </Button>
                  </div>
                </div>

                {initMutation.data && (
                  <div className={`rounded-lg border p-3 text-sm ${initMutation.data.ok ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"}`}>
                    {initMutation.data.message}
                  </div>
                )}
                {initMutation.error && (
                  <div className="rounded-lg border p-3 text-sm bg-rose-50 border-rose-200 text-rose-700">{(initMutation.error as Error).message}</div>
                )}

                {renderConfigCheck(initMutation.data)}

                <Separator />

                <div className="grid gap-3 md:grid-cols-3 text-sm">
                  <div className="rounded-lg border p-3 bg-secondary">
                    <div className="text-xs text-muted-foreground">当前产品</div>
                    <div className="mt-1 font-semibold">{selectedProduct || "未选择"}</div>
                    <div className="text-xs text-muted-foreground">{selectedName || "-"}</div>
                  </div>
                  <div className="rounded-lg border p-3 bg-secondary">
                    <div className="text-xs text-muted-foreground">仪器端口</div>
                    <div className="mt-1 font-semibold mono">{status?.port || "-"}</div>
                    <div className="text-xs text-muted-foreground">{status?.ready ? "就绪" : "未就绪"}</div>
                  </div>
                  <div className="rounded-lg border p-3 bg-secondary">
                    <div className="text-xs text-muted-foreground">最近结果</div>
                    <div className="mt-1 font-semibold">{lastResult?.overall || "-"}</div>
                    <div className="text-xs text-muted-foreground">{lastResult?.timestamp || "-"}</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="panel">
              <CardHeader>
                <CardTitle>操作流程</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3">
                  {["选择产品并初始化连接", "确认状态为就绪", "进入测试页执行测试", "结果自动保存到 CSV"].map((step, i) => (
                    <div key={step} className="flex items-center gap-3 rounded-lg border p-3 bg-card">
                      <div className="w-8 h-8 rounded-full border bg-primary text-primary-foreground flex items-center justify-center text-sm mono">0{i + 1}</div>
                      <div className="text-sm">{step}</div>
                    </div>
                  ))}
                </div>
                <Button size="lg" className="w-full h-16 text-xl" onClick={() => setActiveTab("test")}>
                  前往测试
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="test" className="space-y-4 mt-4">
          <Card className="panel">
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>测试结果</span>
                <div className="flex items-center gap-2">
                  {statusBadge}
                  <Button disabled={!isReady || testMutation.isPending} onClick={() => testMutation.mutate()}>
                    {testMutation.isPending ? "测试中..." : "开始测试"}
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {!lastResult ? (
                <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">还没有测试结果。完成一次测试后将在此展示。</div>
              ) : (
                <>
                  <div className="rounded-lg border p-3 text-sm bg-card">
                    <div className="font-medium">总判定：{overall}</div>
                    <div className="text-xs text-muted-foreground mt-1">规则：任一单元格 Fail，即总结果 Fail。</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch checked={showLimits} onCheckedChange={setShowLimits} />
                    <span className="text-sm text-muted-foreground">显示限值（Fail 项始终显示）</span>
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-28">引脚</TableHead>
                        {matrixTypes.map((t) => (
                          <TableHead key={t} className="text-center">
                            {typeLabel(t)}
                            {typeUnits.get(t) ? ` (${normalizeUnit(typeUnits.get(t) as string)})` : ""}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {matrixRows.map((pins) => (
                        <TableRow key={pins}>
                          <TableCell className="mono font-semibold">{pins}</TableCell>
                          {matrixTypes.map((type) => {
                            const cell = matrix.get(`${pins}::${type}`);
                            if (!cell) return <TableCell key={`${pins}-${type}`} className="text-center text-muted-foreground">-</TableCell>;
                            const fail = cell.result !== "Pass";
                            const cfg = (productDetail?.test_items ?? []).find((x) => x.pins === pins && x.test_type === type);
                            const lowText = limitText(cfg?.lower_limit ?? null, cfg?.unit ?? null);
                            const highText = limitText(cfg?.upper_limit ?? null, cfg?.unit ?? null);
                            return (
                              <TableCell key={`${pins}-${type}`} className={`text-center mono ${fail ? "bg-rose-50 text-rose-700 font-semibold" : "text-foreground"}`}>
                                <div>{formatDisplayValue(cell, cfg?.unit ?? null)}</div>
                                {(showLimits || fail) && <div className="text-[10px] font-normal leading-4 text-muted-foreground">{lowText} ~ {highText}</div>}
                              </TableCell>
                            );
                          })}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="files" className="mt-4">
          <Card className="panel">
            <CardHeader>
              <CardTitle>最近 CSV 结果</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {results.length === 0 && <div className="rounded-lg border border-dashed p-6 text-center text-muted-foreground">暂无结果文件</div>}
              {results.slice(0, 12).map((r) => (
                <div key={r.filename} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                  <div>
                    <div className="mono">{r.filename}</div>
                    <div className="text-xs text-muted-foreground">大小 {Math.max(1, Math.round(r.size / 1024))} KB</div>
                  </div>
                  <Badge variant="secondary">CSV</Badge>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="logs" className="mt-4">
          <Card className="panel">
            <CardHeader>
              <CardTitle className="text-base">运行日志</CardTitle>
              <div className="text-xs text-muted-foreground">运行状态：{realtime.text}</div>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg border bg-slate-950 text-slate-100 p-3 h-[360px] overflow-auto text-xs mono">
                {logs.length === 0 ? <div className="text-slate-400">暂无日志</div> : null}
                {logs.map((entry) => (
                  <div key={entry.id} className="leading-5">[{entry.ts}] {entry.message}</div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
