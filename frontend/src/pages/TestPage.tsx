import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, type TestResult, type MeasuredItem, type InitStatus, type LogItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function formatValue(item: MeasuredItem): string {
  if (item.error) return `ERR(${item.error})`;
  const display = item.value_display ?? item.value;
  if (typeof display !== "number" || Number.isNaN(display)) return "-";
  return item.unit ? `${Number(display.toFixed(6)).toString()} ${item.unit}` : Number(display.toFixed(6)).toString();
}

function typeLabel(type: string): string {
  return type === "EqN" ? "等效n" : type;
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

export default function TestPage() {
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [lastResult, setLastResult] = useState<TestResult | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [logCursor, setLogCursor] = useState(0);

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

  const logsQuery = useQuery({
    queryKey: ["logs", logCursor],
    queryFn: () => api.getLogs(logCursor),
    refetchInterval: 1000,
    enabled: true,
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

  const testMutation = useMutation({ mutationFn: api.runTest, onSuccess: (data) => setLastResult(data) });
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

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="panel">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>测试控制台</span>
              <div className="flex items-center gap-2">
                <span className={`inline-block h-2.5 w-2.5 rounded-full ${status?.ready ? "bg-emerald-500" : hasPort ? "bg-orange-500" : "bg-red-500"}`} />
                <Badge variant={status?.ready ? "default" : "secondary"} className="text-xs">
                  {status?.ready ? `就绪 · ${status?.port}` : hasPort ? `已连接(未就绪) · ${status?.port}` : "未连接"}
                </Badge>
              </div>
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
              {["选择产品并初始化连接", "确认状态为就绪", "点击开始测试并等待结果", "结果自动保存到 CSV"].map((step, i) => (
                <div key={step} className="flex items-center gap-3 rounded-lg border p-3 bg-card">
                  <div className="w-8 h-8 rounded-full border bg-primary text-primary-foreground flex items-center justify-center text-sm mono">0{i + 1}</div>
                  <div className="text-sm">{step}</div>
                </div>
              ))}
            </div>
            <Button size="lg" className="w-full h-16 text-xl" disabled={!isReady || testMutation.isPending} onClick={() => testMutation.mutate()}>
              {testMutation.isPending ? "测试中..." : "开始测试"}
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.5fr_0.9fr]">
        <Card className="panel">
          <CardHeader>
            <CardTitle className="flex items-center gap-3">
              测试结果
              {lastResult && <Badge variant={lastResult.overall === "PASS" ? "default" : "destructive"} className="text-sm px-3 py-1">{lastResult.overall}</Badge>}
              {lastResult && <span className="text-xs text-muted-foreground">{lastResult.passed}/{lastResult.passed + lastResult.failed} 项通过 · {lastResult.timestamp}</span>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!lastResult ? (
              <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">还没有测试结果。完成一次测试后将在此展示。</div>
            ) : (
              <div className="overflow-auto max-h-[420px]">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-24">类型</TableHead>
                      <TableHead className="w-24">引脚</TableHead>
                      <TableHead className="text-right">测量值</TableHead>
                      <TableHead className="text-center w-20">结果</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {lastResult.items.map((item, i) => (
                      <TableRow key={i}>
                        <TableCell className="mono">{typeLabel(item.type)}</TableCell>
                        <TableCell className="mono">{item.pins}</TableCell>
                        <TableCell className="text-right mono">{formatValue(item)}</TableCell>
                        <TableCell className="text-center"><Badge variant={item.result === "Pass" ? "outline" : "destructive"} className="text-xs">{item.result}</Badge></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="panel">
          <CardHeader>
            <CardTitle>最近 CSV 结果</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {results.length === 0 && <div className="rounded-lg border border-dashed p-6 text-center text-muted-foreground">暂无结果文件</div>}
            {results.slice(0, 6).map((r) => (
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
      </div>

      <Card className="panel">
        <CardHeader>
          <CardTitle className="text-base">运行日志</CardTitle>
          <div className="text-xs text-muted-foreground">运行状态：{realtime.text}</div>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border bg-slate-950 text-slate-100 p-3 h-[220px] overflow-auto text-xs mono">
            {logs.length === 0 ? <div className="text-slate-400">暂无日志</div> : null}
            {logs.map((entry) => (
              <div key={entry.id} className="leading-5">[{entry.ts}] {entry.message}</div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
