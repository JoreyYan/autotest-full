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
import { Input } from "@/components/ui/input";

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
  const v = Number(parseFloat(value.toPrecision(10)));
  return unit ? `${v} ${unit}` : `${v}`;
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

// 从飞书链接中提取唯一记录 ID
function extractSerialCode(raw: string): string {
  const trimmed = raw.trim();
  // 飞书记录链接: https://smartonep.feishu.cn/record/RIHurixiWeFAwaceOSocl0uenIe?...
  const m = trimmed.match(/\/record\/([A-Za-z0-9]+)/);
  if (m) return m[1];
  // 如果不是飞书链接，直接用原文作为序列码
  return trimmed;
}

export default function TestPage() {
  const [activeTab, setActiveTab] = useState("console");
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [lastResult, setLastResult] = useState<TestResult | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [logCursor, setLogCursor] = useState(0);
  const [showLimits, setShowLimits] = useState(false);
  const [fontScale, setFontScale] = useState<"md" | "lg" | "xl">(
    () => (localStorage.getItem("resultFontScale") as "md" | "lg" | "xl") || "md"
  );
  const changeFontScale = (v: "md" | "lg" | "xl") => {
    setFontScale(v);
    localStorage.setItem("resultFontScale", v);
  };
  const [scannerMode, setScannerMode] = useState(true); // 默认扫码枪模式
  const [lastScanCode, setLastScanCode] = useState("");
  const [lastRecordNumber, setLastRecordNumber] = useState<string | null>(null);
  const [lastScanUrl, setLastScanUrl] = useState("");
  const [manualRecordNumber, setManualRecordNumber] = useState("");
  const [manualCoreNumber, setManualCoreNumber] = useState("");

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

  const fixtureProducts = useMemo(
    () => products.filter((p) => (p.workflow_type ?? "fixture_test") !== "incoming_inspection"),
    [products]
  );

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

  const disconnectMutation = useMutation({ mutationFn: api.disconnect, onSuccess: () => refetchStatus() });

  const isReady = Boolean(status?.ready && status?.product_code === selectedProduct);

  const testMutation = useMutation({
    mutationFn: (params?: { serialCode?: string; recordNumber?: string; coreNumber?: string }) => api.runTest(params),
    onSuccess: (data) => {
      setLastResult(data);
      setActiveTab("test");
      // 测试完成后清空手输字段，下一台重新输入
      setManualRecordNumber("");
      setManualCoreNumber("");
    },
  });

  // 扫码枪监听：扫码枪模拟键盘快速输入，以 Enter 结束
  useEffect(() => {
    if (!scannerMode || !isReady) return;
    let buffer = "";
    let timer: ReturnType<typeof setTimeout> | null = null;

    function triggerScan(raw: string) {
      const rawUrl = raw.trim();
      const code = extractSerialCode(rawUrl);

      // 扫码模式下也尊重产品配置的必填项
      const reqRec = productDetail?.require_record_number !== false;
      const reqCore = Boolean(productDetail?.require_core_number);
      const recVal = manualRecordNumber.trim();
      const coreVal = manualCoreNumber.trim();
      if (reqRec && !recVal) {
        console.warn('[scanner] 序号必填但未填，本次扫码忽略');
        return;
      }
      if (reqCore && !coreVal) {
        console.warn('[scanner] 磁芯编号必填但未填，本次扫码忽略');
        return;
      }

      setLastScanCode(code);
      setLastRecordNumber(recVal || null);
      setLastScanUrl(rawUrl);
      if (!testMutation.isPending) {
        testMutation.mutate({ serialCode: code, recordNumber: recVal, coreNumber: coreVal });
      }
      // 仅当用户没手动填序号时才异步查飞书
      if (!recVal && rawUrl.includes("feishu.cn/record/")) {
        api.getFeishuRecordNumber(rawUrl).then((res) => {
          if (res.ok && res.record_number !== null) {
            setLastRecordNumber(String(res.record_number));
          }
        }).catch(() => {});
      }
    }

    function handleKeyDown(e: KeyboardEvent) {
      // 忽略来自 input/textarea 的事件
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === "Enter" && buffer.length > 5) {
        e.preventDefault();
        triggerScan(buffer);
        buffer = "";
      } else if (e.key.length === 1) {
        buffer += e.key;
        // 超过 500ms 没有新输入：如果 buffer 够长则自动触发（兼容不发 Enter 的扫码枪）
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
          console.log(`[scanner] timeout fired, buffer="${buffer}" len=${buffer.length}`);
          if (buffer.length > 5) {
            triggerScan(buffer);
          }
          buffer = "";
        }, 500);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (timer) clearTimeout(timer);
    };
  }, [scannerMode, isReady, testMutation.isPending, productDetail?.require_record_number, productDetail?.require_core_number, manualRecordNumber, manualCoreNumber]);

  // 序号和CSV都就绪后，补写序号到CSV
  const [patchedCsv, setPatchedCsv] = useState("");
  useEffect(() => {
    if (lastRecordNumber && lastResult?.csv_file && lastResult.csv_file !== patchedCsv) {
      setPatchedCsv(lastResult.csv_file);
      api.patchRecordNumber(lastResult.csv_file, lastRecordNumber).catch(() => {});
    }
  }, [lastRecordNumber, lastResult?.csv_file]);

  const selectedName = useMemo(
    () => fixtureProducts.find((p) => p.product_code === selectedProduct)?.product_name,
    [fixtureProducts, selectedProduct]
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
                        {fixtureProducts.map((p) => (
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

                <div className="flex items-center gap-3">
                  <Switch checked={scannerMode} onCheckedChange={setScannerMode} />
                  <span className="text-sm font-medium">扫码枪模式</span>
                  <span className="text-xs text-muted-foreground">{scannerMode ? "已开启：扫码即测试，测试按钮隐藏" : "已关闭：手动点击测试按钮"}</span>
                </div>

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
                  {scannerMode ? (
                    (() => {
                      const reqRec = productDetail?.require_record_number !== false;
                      const reqCore = Boolean(productDetail?.require_core_number);
                      const recOk = !reqRec || manualRecordNumber.trim().length > 0;
                      const coreOk = !reqCore || manualCoreNumber.trim().length > 0;
                      const ready = isReady && recOk && coreOk;
                      let badgeText: string;
                      if (testMutation.isPending) badgeText = "测试中...";
                      else if (!isReady) badgeText = "未就绪";
                      else if (!recOk) badgeText = "请先填序号";
                      else if (!coreOk) badgeText = "请先填磁芯编号";
                      else badgeText = "等待扫码...";
                      return (
                        <>
                          {reqRec && (
                            <Input
                              placeholder="序号"
                              value={manualRecordNumber}
                              onChange={(e) => setManualRecordNumber(e.target.value)}
                              className="h-10 w-32"
                              disabled={testMutation.isPending}
                            />
                          )}
                          {reqCore && (
                            <Input
                              placeholder="磁芯编号"
                              value={manualCoreNumber}
                              onChange={(e) => setManualCoreNumber(e.target.value)}
                              className="h-10 w-32"
                              disabled={testMutation.isPending}
                            />
                          )}
                          <Badge variant={ready ? "default" : "secondary"} className="text-sm px-4 py-2">
                            {badgeText}
                          </Badge>
                        </>
                      );
                    })()
                  ) : (
                    (() => {
                      const reqRec = productDetail?.require_record_number !== false; // 默认 true
                      const reqCore = Boolean(productDetail?.require_core_number);
                      const recOk = !reqRec || manualRecordNumber.trim().length > 0;
                      const coreOk = !reqCore || manualCoreNumber.trim().length > 0;
                      const canRun = isReady && !testMutation.isPending && recOk && coreOk;
                      return (
                        <>
                          {reqRec && (
                            <Input
                              placeholder="序号"
                              value={manualRecordNumber}
                              onChange={(e) => setManualRecordNumber(e.target.value)}
                              className="h-10 w-32"
                              disabled={testMutation.isPending}
                            />
                          )}
                          {reqCore && (
                            <Input
                              placeholder="磁芯编号"
                              value={manualCoreNumber}
                              onChange={(e) => setManualCoreNumber(e.target.value)}
                              className="h-10 w-32"
                              disabled={testMutation.isPending}
                            />
                          )}
                          <Button
                            disabled={!canRun}
                            onClick={() => {
                              const num = manualRecordNumber.trim();
                              const core = manualCoreNumber.trim();
                              setLastScanCode("");
                              setLastRecordNumber(num || null);
                              setLastScanUrl("");
                              testMutation.mutate({ recordNumber: num, coreNumber: core });
                            }}
                          >
                            {testMutation.isPending ? "测试中..." : "开始测试"}
                          </Button>
                        </>
                      );
                    })()
                  )}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {lastScanCode && (
                <div className="rounded-lg border p-3 text-sm bg-blue-50 border-blue-200 text-blue-700 flex items-center gap-4">
                  <div><span className="font-medium">序列码：</span><span className="mono">{lastScanCode}</span></div>
                  {lastRecordNumber !== null && (
                    <div><span className="font-medium">序号：</span><span className="mono text-lg font-bold">{lastRecordNumber}</span></div>
                  )}
                </div>
              )}
              {!lastResult ? (
                <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
                  {scannerMode && isReady ? "扫码枪模式已开启，请扫描产品二维码开始测试" : "还没有测试结果。完成一次测试后将在此展示。"}
                </div>
              ) : (
                <>
                  <div className={`rounded-lg border p-3 text-sm ${overall === "PASS" ? "bg-emerald-50 border-emerald-200" : "bg-rose-50 border-rose-200"}`}>
                    <div className={`font-bold ${fontScale === "xl" ? "text-4xl" : fontScale === "lg" ? "text-2xl" : "text-lg"} ${overall === "PASS" ? "text-emerald-700" : "text-rose-700"}`}>总判定：{overall}</div>
                    <div className="text-xs text-muted-foreground mt-1">规则：任一单元格 Fail，即总结果 Fail。</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch checked={showLimits} onCheckedChange={setShowLimits} />
                    <span className="text-sm text-muted-foreground">显示限值（Fail 项始终显示）</span>
                    <div className="ml-auto flex items-center gap-1">
                      <span className="text-xs text-muted-foreground mr-1">字号</span>
                      {(["md", "lg", "xl"] as const).map((v) => (
                        <Button key={v} size="sm" variant={fontScale === v ? "default" : "outline"} className="h-7 px-2.5 text-xs" onClick={() => changeFontScale(v)}>
                          {v === "md" ? "标准" : v === "lg" ? "大" : "特大"}
                        </Button>
                      ))}
                    </div>
                  </div>
                  <div className={fontScale === "xl" ? "[&_td]:text-3xl [&_td]:py-4 [&_th]:text-xl" : fontScale === "lg" ? "[&_td]:text-xl [&_td]:py-3 [&_th]:text-base" : ""}>
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
                            const lowText = limitText(cfg?.lower_limit ?? cell.lo_display ?? null, cfg?.unit ?? cell.unit ?? null);
                            const highText = limitText(cfg?.upper_limit ?? cell.hi_display ?? null, cfg?.unit ?? cell.unit ?? null);
                            return (
                              <TableCell key={`${pins}-${type}`} className={`text-center mono ${fail ? "bg-rose-50 text-rose-700 font-semibold" : "text-foreground"}`}>
                                <div>{formatDisplayValue(cell, cfg?.unit ?? null)}</div>
                                {(showLimits || fail) && <div className="text-[0.55em] font-normal leading-snug text-muted-foreground">{lowText} ~ {highText}</div>}
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
