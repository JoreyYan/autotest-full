import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type InspectionItemResult, type InspectionStepResult, type LogItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type StepPhase = "idle" | "ready" | "await_next" | "finished";

function formatNumber(value?: number | null, unit?: string | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const text = Number(value.toFixed(6)).toString();
  return unit ? `${text} ${unit}` : text;
}

function formatRange(lower?: number | null, upper?: number | null, unit?: string | null) {
  const low = formatNumber(lower, unit);
  const high = formatNumber(upper, unit);
  if (low === "-" && high === "-") return "-";
  return `${low} ~ ${high}`;
}

export default function IncomingInspectionPage() {
  const [selectedProduct, setSelectedProduct] = useState("");
  const [port, setPort] = useState("COM5");
  const [logCursor, setLogCursor] = useState(0);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [history, setHistory] = useState<InspectionItemResult[]>([]);
  const [lastStep, setLastStep] = useState<InspectionStepResult | null>(null);
  const [phase, setPhase] = useState<StepPhase>("idle");

  const { data: products = [] } = useQuery({ queryKey: ["products"], queryFn: api.getProducts });
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["inspection-status"],
    queryFn: api.getInspectionStatus,
    refetchInterval: 1500,
  });
  const { data: results = [] } = useQuery({
    queryKey: ["results"],
    queryFn: api.getResults,
    refetchInterval: 10000,
  });
  const logsQuery = useQuery({
    queryKey: ["inspection-logs", logCursor],
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

  const inspectionProducts = useMemo(
    () => products.filter((p) => p.workflow_type === "incoming_inspection" || p.instrument_driver === "lcr_2836"),
    [products]
  );

  const initializeMutation = useMutation({
    mutationFn: () => api.initializeInspection(selectedProduct, port),
    onMutate: () => {
      setHistory([]);
      setLastStep(null);
      setLogs([]);
      setLogCursor(0);
      setPhase("idle");
    },
    onSuccess: () => {
      setPhase("ready");
      refetchStatus();
    },
  });

  const runStepMutation = useMutation({
    mutationFn: api.runInspectionStep,
    onSuccess: (data) => {
      setLastStep(data);
      setHistory((prev) => [...prev, ...data.items]);
      setPhase(data.finished ? "finished" : "await_next");
      refetchStatus();
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: api.disconnect,
    onSuccess: () => {
      setPhase("idle");
      refetchStatus();
    },
  });

  const ready = Boolean(status?.ready && status?.product_code === selectedProduct);
  const productName = inspectionProducts.find((p) => p.product_code === selectedProduct)?.product_name;
  const recentInspectionFiles = results.filter((r) => r.filename.includes("_inspection_")).slice(0, 10);
  const overall = lastStep?.overall || "-";
  const currentPrompt = useMemo(() => {
    if (phase === "await_next" && lastStep?.next_prompt) return lastStep.next_prompt;
    return initializeMutation.data?.next_prompt || status?.next_prompt || "请选择产品并初始化";
  }, [phase, lastStep, initializeMutation.data, status]);

  const currentAction = useMemo(() => {
    if (!ready) {
      return { label: "开始本脚位", disabled: true, helper: "请先完成初始化连接" };
    }
    if (runStepMutation.isPending) {
      return { label: "执行当前脚位中...", disabled: true, helper: "正在测量，请勿切换脚位" };
    }
    if (phase === "finished") {
      return { label: "检验已完成", disabled: true, helper: "本轮检验已结束，可查看结果和 CSV" };
    }
    if (phase === "await_next") {
      return { label: "进入下一脚位", disabled: false, helper: "请先切换夹具到下一脚位，再进入下一步" };
    }
    return { label: "开始本脚位", disabled: false, helper: "确认夹具已接好后，开始测量当前脚位" };
  }, [ready, runStepMutation.isPending, phase]);

  function handlePrimaryAction() {
    if (phase === "await_next") {
      setLastStep(null);
      setPhase("ready");
      return;
    }
    if (phase === "ready" || phase === "idle") {
      runStepMutation.mutate();
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <Card className="panel">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>入料检验控制台</span>
              <Badge variant={ready ? "default" : "secondary"}>
                {ready ? `就绪 · ${status?.port}` : status?.port ? `已连接(未就绪) · ${status.port}` : "未连接"}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <label className="text-sm font-medium">检验产品</label>
              <select className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={selectedProduct} onChange={(e) => setSelectedProduct(e.target.value)}>
                <option value="">请选择入料产品...</option>
                {inspectionProducts.map((p) => (
                  <option key={p.product_code} value={p.product_code}>
                    {p.product_code} - {p.product_name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">仪器端口</label>
              <Input value={port} onChange={(e) => setPort(e.target.value.trim().toUpperCase())} placeholder="例如 COM5" className="h-11" />
            </div>

            <div className="flex gap-2">
              <Button onClick={() => initializeMutation.mutate()} disabled={!selectedProduct || !port || initializeMutation.isPending}>
                {initializeMutation.isPending ? "初始化中..." : "初始化检验"}
              </Button>
              <Button variant="outline" onClick={() => disconnectMutation.mutate()} disabled={disconnectMutation.isPending}>
                断开
              </Button>
            </div>

            {initializeMutation.data && <div className={`rounded-lg border p-3 text-sm ${initializeMutation.data.ok ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"}`}>{initializeMutation.data.message}</div>}
            {initializeMutation.error && <div className="rounded-lg border p-3 text-sm bg-rose-50 border-rose-200 text-rose-700">{(initializeMutation.error as Error).message}</div>}

            <div className="rounded-xl border bg-secondary p-4 space-y-2">
              <div className="text-xs text-muted-foreground">当前提示</div>
              <div className="text-lg font-semibold">{currentPrompt}</div>
              <div className="text-xs text-muted-foreground">已完成步骤 {status?.completed_steps ?? 0} / {status?.total_steps ?? 0}</div>
            </div>

            <div className="rounded-xl border p-4 space-y-2 bg-card">
              <div className="text-xs text-muted-foreground">当前动作</div>
              <div className="font-medium">{currentAction.label}</div>
              <div className="text-xs text-muted-foreground">{currentAction.helper}</div>
            </div>
            {lastStep && (
              <div className={`rounded-xl border p-4 space-y-2 ${lastStep.step_result === "Pass" ? "bg-emerald-50 border-emerald-200" : "bg-rose-50 border-rose-200"}`}>
                <div className="text-xs text-muted-foreground">上一步完成</div>
                <div className="font-medium">脚位 {lastStep.pins} · {lastStep.step_result}</div>
                <div className="text-xs text-muted-foreground">{lastStep.finished ? "本轮检验已完成" : `下一步：${lastStep.next_prompt}`}</div>
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-3 text-sm">
              <div className="rounded-lg border p-3 bg-card">
                <div className="text-xs text-muted-foreground">当前产品</div>
                <div className="mt-1 font-semibold">{selectedProduct || "-"}</div>
                <div className="text-xs text-muted-foreground">{productName || "-"}</div>
              </div>
              <div className="rounded-lg border p-3 bg-card">
                <div className="text-xs text-muted-foreground">工作流</div>
                <div className="mt-1 font-semibold">incoming_inspection</div>
                <div className="text-xs text-muted-foreground">LCR 表分步检验</div>
              </div>
              <div className="rounded-lg border p-3 bg-card">
                <div className="text-xs text-muted-foreground">整体结果</div>
                <div className={`mt-1 font-semibold ${overall === "FAIL" ? "text-rose-600" : overall === "PASS" ? "text-emerald-600" : ""}`}>{overall}</div>
                <div className="text-xs text-muted-foreground">{lastStep?.csv_file || "-"}</div>
              </div>
            </div>

            <Button size="lg" className="w-full h-14 text-lg" disabled={currentAction.disabled} onClick={handlePrimaryAction}>
              {currentAction.label}
            </Button>
          </CardContent>
        </Card>

        <Card className="panel">
          <CardHeader>
            <CardTitle>检验结果</CardTitle>
          </CardHeader>
          <CardContent>
            {history.length === 0 ? (
              <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">还没有检验结果。初始化后按提示完成每个脚位。</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>脚位</TableHead>
                    <TableHead>项目</TableHead>
                    <TableHead>功能</TableHead>
                    <TableHead>主参数</TableHead>
                    <TableHead>主参数范围</TableHead>
                    <TableHead>副参数</TableHead>
                    <TableHead>副参数范围</TableHead>
                    <TableHead className="text-right">结果</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((item, idx) => (
                    <TableRow key={`${item.pins}-${item.name}-${idx}`}>
                      <TableCell className="font-mono">{item.pins}</TableCell>
                      <TableCell>{item.name}</TableCell>
                      <TableCell className="font-mono text-xs">{item.function_code || "-"}</TableCell>
                      <TableCell>{item.error ? `ERR(${item.error})` : `${item.primary_label}: ${formatNumber(item.primary_value_display, item.primary_unit)}`}</TableCell>
                      <TableCell>{formatRange(item.primary_lower, item.primary_upper, item.primary_unit)}</TableCell>
                      <TableCell>{item.secondary_label ? `${item.secondary_label}: ${formatNumber(item.secondary_value_display, item.secondary_unit)}` : "-"}</TableCell>
                      <TableCell>{item.secondary_label ? formatRange(item.secondary_lower, item.secondary_upper, item.secondary_unit) : "-"}</TableCell>
                      <TableCell className={`text-right font-semibold ${item.result !== "Pass" ? "text-rose-600" : "text-emerald-600"}`}>{item.result}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
        <Card className="panel">
          <CardHeader>
            <CardTitle>最近文件</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {recentInspectionFiles.length === 0 ? <div className="rounded-lg border border-dashed p-6 text-center text-muted-foreground">暂无入料检验文件</div> : null}
            {recentInspectionFiles.map((r) => (
              <div key={r.filename} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                <div>
                  <div className="font-mono">{r.filename}</div>
                  <div className="text-xs text-muted-foreground">大小 {Math.max(1, Math.round(r.size / 1024))} KB</div>
                </div>
                <Badge variant="secondary">CSV</Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="panel">
          <CardHeader>
            <CardTitle>运行日志</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-lg border bg-slate-950 text-slate-100 p-3 h-[320px] overflow-auto text-xs font-mono">
              {logs.length === 0 ? <div className="text-slate-400">暂无日志</div> : null}
              {logs.map((entry) => (
                <div key={entry.id} className="leading-5">[{entry.ts}] {entry.message}</div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
