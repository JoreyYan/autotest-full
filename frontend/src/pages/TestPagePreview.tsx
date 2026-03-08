import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type LogItem, type MeasuredItem, type TestResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";

function limitText(value: number | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return unit ? `${value} ${unit}` : `${value}`;
}

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
  const converted = hasDisplay ? item.value_display as number : convertSiToUnit(item.value, u);
  if (item.type === "Turn" || item.type === "Q" || !u) return Number(converted.toFixed(6)).toString();
  return `${Number(converted.toFixed(6)).toString()} ${normalizeUnit(u)}`;
}

const TYPE_ORDER = ["Turn", "Lx", "Q", "Lk", "Cx", "Dcr"];

function typeLabel(type: string): string {
  return type === "EqN" ? "等效n" : type;
}

type UiStage = "idle" | "initializing" | "testing" | "done";

function getConnState(ready: boolean, hasPort: boolean) {
  if (ready) return { dot: "bg-emerald-500", text: "就绪" };
  if (hasPort) return { dot: "bg-amber-500", text: "已连接未就绪" };
  return { dot: "bg-red-500", text: "未连接" };
}

export default function TestPagePreview() {
  const [selectedProduct, setSelectedProduct] = useState("");
  const [lastResult, setLastResult] = useState<TestResult | null>(null);
  const [stage, setStage] = useState<UiStage>("idle");
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [cursor, setCursor] = useState(0);
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
    queryKey: ["logs-preview", cursor],
    queryFn: () => api.getLogs(cursor),
    refetchInterval: 1000,
  });

  useEffect(() => {
    const data = logsQuery.data;
    if (!data) return;
    if (data.last_id < cursor) {
      setCursor(0);
      setLogs([]);
      return;
    }
    if (data.items.length > 0) {
      setLogs((prev) => [...prev, ...data.items].slice(-300));
    }
    setCursor(data.last_id);
  }, [logsQuery.data, cursor]);

  const initMutation = useMutation({
    mutationFn: () => api.initialize(selectedProduct),
    onMutate: () => {
      setStage("initializing");
      setLogs([]);
      setCursor(0);
    },
    onSuccess: () => {
      setStage("idle");
      refetchStatus();
    },
    onError: () => setStage("idle"),
  });

  const testMutation = useMutation({
    mutationFn: api.runTest,
    onMutate: () => setStage("testing"),
    onSuccess: (data) => {
      setLastResult(data);
      setStage("done");
    },
    onError: () => setStage("idle"),
  });

  const disconnectMutation = useMutation({
    mutationFn: api.disconnect,
    onSuccess: () => {
      refetchStatus();
      setStage("idle");
    },
  });

  const hasPort = Boolean(status?.port);
  const conn = getConnState(Boolean(status?.ready), hasPort);
  const selectedName = useMemo(() => products.find((p) => p.product_code === selectedProduct)?.product_name, [products, selectedProduct]);
  const canRun = Boolean(status?.ready && status?.product_code === selectedProduct);
  const latestLog = logs.length > 0 ? logs[logs.length - 1].message : "暂无过程";
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

  const overall = useMemo(() => {
    if (!lastResult) return "-";
    return lastResult.items.some((x) => x.result !== "Pass") ? "FAIL" : "PASS";
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

  return (
    <div className="space-y-6">
      <Card className="panel">
        <CardContent className="pt-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${conn.dot}`} />
              <span className="text-sm font-medium">连接状态：{conn.text}{hasPort ? ` · ${status?.port}` : ""}</span>
              <Badge variant="secondary">预览页</Badge>
            </div>
            <div className="text-sm text-muted-foreground">当前产品：{selectedProduct || "未选择"}{selectedName ? ` - ${selectedName}` : ""}</div>
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_auto] items-end">
            <div>
              <label className="text-sm font-medium mb-2 block">选择产品</label>
              <Select value={selectedProduct} onValueChange={setSelectedProduct}>
                <SelectTrigger className="h-11">
                  <SelectValue placeholder="请选择产品..." />
                </SelectTrigger>
                <SelectContent>
                  {products.map((p) => (
                    <SelectItem key={p.product_code} value={p.product_code}>{p.product_code} - {p.product_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-2">
              <Button className="h-11" onClick={() => initMutation.mutate()} disabled={!selectedProduct || initMutation.isPending || testMutation.isPending}>初始化连接</Button>
              <Button className="h-11" onClick={() => testMutation.mutate()} disabled={!canRun || testMutation.isPending || initMutation.isPending}>开始测试</Button>
              <Button className="h-11" variant="outline" onClick={() => disconnectMutation.mutate()} disabled={disconnectMutation.isPending}>断开</Button>
            </div>
          </div>

          <div className="rounded-lg border p-3 bg-slate-50">
            <div className="text-sm font-medium">运行阶段：{stage === "idle" ? "待机" : stage === "initializing" ? "初始化中" : stage === "testing" ? "测试中" : "完成"}</div>
            <div className="text-xs text-muted-foreground mt-1">{latestLog}</div>
            <Progress className="mt-2" value={stage === "idle" ? 0 : stage === "initializing" ? 35 : stage === "testing" ? 70 : 100} />
          </div>

          {initMutation.data && (
            <div className={`rounded-lg border p-3 text-sm ${initMutation.data.ok ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"}`}>
              {initMutation.data.message}
            </div>
          )}
          {initMutation.error && <div className="rounded-lg border p-3 text-sm bg-rose-50 border-rose-200 text-rose-700">{(initMutation.error as Error).message}</div>}
        </CardContent>
      </Card>

      <Card className="panel">
        <CardHeader>
          <CardTitle className="flex items-center gap-3">
            测试结果
            {lastResult && <Badge variant={overall === "PASS" ? "default" : "destructive"}>{overall}</Badge>}
            {lastResult && <span className="text-xs text-muted-foreground">{lastResult.passed}/{lastResult.passed + lastResult.failed} 项通过 · {lastResult.timestamp}</span>}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!lastResult ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">完成一次测试后在这里显示完整结果。</div>
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
              <div>
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
                            <TableCell
                              key={`${pins}-${type}`}
                              className={`text-center mono ${fail ? "bg-rose-50 text-rose-700 font-semibold" : "text-foreground"}`}
                              title={cell.result}
                            >
                              <div>{formatDisplayValue(cell, cfg?.unit ?? null)}</div>
                              {(showLimits || fail) && (
                                <div className="text-[10px] font-normal leading-4 text-muted-foreground">
                                  {lowText} ~ {highText}
                                </div>
                              )}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <details className="panel rounded-lg border">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">日志与历史（次要信息，默认折叠）</summary>
        <div className="px-4 pb-4 space-y-4">
          <div className="rounded-lg border bg-slate-950 text-slate-100 p-3 h-[220px] overflow-auto text-xs mono">
            {logs.length === 0 ? <div className="text-slate-400">暂无日志</div> : null}
            {logs.map((entry) => (
              <div key={entry.id} className="leading-5">[{entry.ts}] {entry.message}</div>
            ))}
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {results.slice(0, 6).map((r) => (
              <div key={r.filename} className="rounded-lg border p-3 text-sm flex items-center justify-between">
                <div>
                  <div className="mono">{r.filename}</div>
                  <div className="text-xs text-muted-foreground">大小 {Math.max(1, Math.round(r.size / 1024))} KB</div>
                </div>
                <Badge variant="secondary">CSV</Badge>
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}
