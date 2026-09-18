import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, type TestResult, type MeasuredItem, type InitStatus, type LogItem } from "@/lib/api";
import { parseFinishedCode } from "@/lib/finishedCode";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";

/** 气隙研磨计算面板（磁芯检产品专用）：FAIL 磁芯自动带入实测电感，调云端算法给研磨建议。 */
const GAP_DEFAULTS = { np1: 9, ns1: 3, np2: -6, ns2: -6, n: 1.185, lk: 8.884, lm: 56.866, hgPri: 5.56, hgSec: 1.36, hgFilm: 0.6 };

export function GapCalcPanel({ productCode, result }: { productCode: string; result: TestResult | null }) {
  const storeKey = `gapCalc:${productCode}`;
  const [cfg, setCfg] = useState<typeof GAP_DEFAULTS & { enabled: boolean }>(() => {
    try {
      const saved = localStorage.getItem(storeKey);
      if (saved) return { ...GAP_DEFAULTS, enabled: false, ...JSON.parse(saved) };
    } catch { /* ignore */ }
    return { ...GAP_DEFAULTS, enabled: false };
  });
  const [calcText, setCalcText] = useState("");
  const [calcErr, setCalcErr] = useState("");
  const [calcing, setCalcing] = useState(false);
  const [calcedFor, setCalcedFor] = useState("");

  const upd = (patch: Partial<typeof cfg>) => {
    setCfg((prev) => {
      const next = { ...prev, ...patch };
      localStorage.setItem(storeKey, JSON.stringify(next));
      return next;
    });
  };

  const pick = (type: string, pins: string): number | null => {
    const it = result?.items.find((x) => x.type === type && x.pins === pins);
    if (!it) return null;
    const v = it.value_display ?? it.value;
    return typeof v === "number" && !Number.isNaN(v) ? v : null;
  };
  const lOc1 = pick("Lx", "2-3");
  const lOc2 = pick("Lx", "6-5");
  const lSc1 = pick("Lk", "2-3");
  const lSc2 = pick("Lk", "6-5");
  const measuredOk = lOc1 != null && lOc2 != null && lSc1 != null && lSc2 != null;

  const runCalc = async () => {
    if (!measuredOk) return;
    setCalcing(true);
    setCalcErr("");
    setCalcText("");
    try {
      const d = await api.gapCalc({
        NNv: [[cfg.np1, cfg.ns1], [cfg.np2, cfg.ns2]],
        params_target: [cfg.n, cfg.lk, cfg.lm],
        current_Locsc_uH: [lOc1 as number, lOc2 as number, lSc1 as number, lSc2 as number],
        hg_pri_mm: cfg.hgPri,
        hg_sec_mm: cfg.hgSec,
        hg_film_mm: cfg.hgFilm,
      });
      setCalcText(d.result);
    } catch (e) {
      setCalcErr((e as Error).message);
    } finally {
      setCalcing(false);
    }
  };

  // FAIL 结果出来后自动计算一次（同一份结果不重复算）
  useEffect(() => {
    const stamp = result?.timestamp || "";
    if (cfg.enabled && result?.overall === "FAIL" && measuredOk && stamp && stamp !== calcedFor) {
      setCalcedFor(stamp);
      runCalc();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.timestamp, cfg.enabled]);

  const numInput = (label: string, key: keyof typeof GAP_DEFAULTS, step = 0.01, wide = false) => (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <Input type="number" step={step} className={`h-8 ${wide ? "w-24" : "w-20"} text-right mono`}
        value={cfg[key]} onChange={(e) => upd({ [key]: Number(e.target.value || 0) } as Partial<typeof cfg>)} />
    </div>
  );

  return (
    <Card className="panel border-amber-200">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span>气隙研磨计算（磁芯检）</span>
          <div className="flex items-center gap-2">
            <span className="text-xs font-normal text-muted-foreground">{cfg.enabled ? "已开启：FAIL 自动计算" : "已关闭"}</span>
            <Switch checked={cfg.enabled} onCheckedChange={(v) => upd({ enabled: v })} />
          </div>
        </CardTitle>
      </CardHeader>
      {cfg.enabled && (
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border p-3">
              <div className="text-xs font-medium mb-2">实测电感 μH（自动带入本次结果）</div>
              <div className="grid grid-cols-2 gap-2 text-sm mono">
                <div>原电感 Lx2-3：<b>{lOc1 ?? "—"}</b></div>
                <div>副电感 Lx6-5：<b>{lOc2 ?? "—"}</b></div>
                <div>原漏感 Lk2-3：<b>{lSc1 ?? "—"}</b></div>
                <div>副漏感 Lk6-5：<b>{lSc2 ?? "—"}</b></div>
              </div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="text-xs font-medium mb-2">当前气隙尺寸 (mm)（可修改）</div>
              <div className="flex flex-wrap gap-3">
                {numInput("原边月牙中柱", "hgPri", 0.01, true)}
                {numInput("副边圆形中柱", "hgSec", 0.01, true)}
                {numInput("边柱胶带厚度", "hgFilm", 0.01, true)}
              </div>
            </div>
          </div>
          <details className="rounded-lg border p-3">
            <summary className="text-xs font-medium cursor-pointer select-none">匝数与目标参数（默认已按模板填好，一般不用改）</summary>
            <div className="flex flex-wrap gap-3 mt-3">
              {numInput("Np1", "np1", 1)}
              {numInput("Ns1", "ns1", 1)}
              {numInput("Np2", "np2", 1)}
              {numInput("Ns2", "ns2", 1)}
              {numInput("等效匝比n", "n", 0.001, true)}
              {numInput("漏感Lk", "lk", 0.001, true)}
              {numInput("励磁Lm", "lm", 0.001, true)}
            </div>
          </details>
          <div className="flex items-center gap-3">
            <Button onClick={runCalc} disabled={!measuredOk || calcing}>
              {calcing ? "计算中..." : "计算研磨建议"}
            </Button>
            {!measuredOk && <span className="text-xs text-muted-foreground">测一发后自动带入实测电感</span>}
            {calcErr && <span className="text-xs text-rose-600">计算失败：{calcErr}</span>}
          </div>
          {calcText && (
            <pre className="whitespace-pre-wrap text-sm mono bg-slate-50 border rounded-lg p-4 leading-relaxed overflow-x-auto">{calcText}</pre>
          )}
        </CardContent>
      )}
    </Card>
  );
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

/** 扣偏校验(金样)标签页:控制台→扣偏校验→测试 流水线的中间环节。 */
function CalibrationPanel({ cal, onRefetch, onPassed }: {
  cal: { enabled: boolean; tolerance_pct: number; passed: boolean; checked_at: string | null; detail: import("@/lib/api").CalibrationRow[]; id?: string | null } | undefined;
  onRefetch: () => void;
  onPassed: () => void;
}) {
  const [showGuide, setShowGuide] = useState(false);
  const calMutation = useMutation({
    mutationFn: api.calibrationRun,
    onSuccess: (d) => {
      onRefetch();
      if (d.passed) window.setTimeout(onPassed, 1500);
    },
  });
  const tol = cal?.tolerance_pct ?? 0.5;
  const passed = Boolean(cal?.passed);
  const detail = calMutation.data?.detail ?? cal?.detail ?? [];

  return (
    <div className="space-y-4">
      <div className={`rounded-lg border p-4 ${passed ? "bg-emerald-50 border-emerald-300" : "bg-amber-50 border-amber-300"}`}>
        <div className={`text-lg font-bold ${passed ? "text-emerald-700" : "text-amber-700"}`}>
          {passed ? `校验已通过 ✓  ${cal?.checked_at || ""}` : "校验未通过 — 正式测试已锁定"}
        </div>
        {passed && cal?.id ? (
          <div className="text-xs text-muted-foreground mt-1 mono">校验ID：{cal.id}（本次校验后的测试记录都会带上此ID）</div>
        ) : null}
        {passed && calMutation.data?.passed && (
          <div className="text-sm text-emerald-700 mt-1">即将自动进入「测试」…</div>
        )}
      </div>

      <div className="rounded-lg border p-4 text-sm space-y-1.5">
        <div className="font-semibold mb-1">操作规程（阈值 ±{tol}%）</div>
        <div>① 仪器面板进入「偏差扣除」设置页：总开关 ON，需要扣除的项逐个打 ON（√）</div>
        <div>② 选好后返回测量显示页面</div>
        <div>③ 把<b>标准磁芯</b>放上夹具，按仪器实体 <b>TRIGGER</b> 键执行一次偏差扣除</div>
        <div>④ 标准磁芯保持在夹具上，点击下方「扣偏校验测试」——软件测量并与标称值比对</div>
        <div>⑤ 全部误差 ≤{tol}% 即通过，自动进入测试；不通过可重新扣除后再校验，不限次数</div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <Button size="lg" disabled={calMutation.isPending} onClick={() => calMutation.mutate()}>
          {calMutation.isPending ? "校验中..." : "扣偏校验测试"}
        </Button>
        <Button variant="outline" onClick={() => setShowGuide(v => !v)}>
          {showGuide ? "收起图文教程" : "查看图文教程"}
        </Button>
        <a href="/guide/uc2866xb-offset.html" target="_blank" rel="noreferrer"
          className="text-sm text-muted-foreground underline">新窗口打开教程</a>
      </div>

      {calMutation.error ? (
        <div className="rounded-lg border p-3 text-sm bg-rose-50 border-rose-200 text-rose-700">
          {(calMutation.error as Error).message}
        </div>
      ) : null}

      {detail.length > 0 && (
        <table className="text-sm w-full">
          <thead>
            <tr className="text-muted-foreground text-xs">
              <th className="text-left pr-3 py-1">项目</th>
              <th className="text-right pr-3">标准值</th>
              <th className="text-right pr-3">实测</th>
              <th className="text-right pr-3">误差%</th>
              <th className="text-center">判定</th>
            </tr>
          </thead>
          <tbody>
            {detail.map((r, i) => (
              <tr key={i} className="border-t">
                <td className="pr-3 py-1 mono">{r.test_type} {r.pins}</td>
                <td className="text-right pr-3 mono">{r.standard ?? "-"}</td>
                <td className="text-right pr-3 mono">{r.measured != null ? Number(r.measured).toFixed(5) : "-"}</td>
                <td className={`text-right pr-3 mono ${r.ok ? "text-emerald-600" : "text-rose-600 font-bold"}`}>{r.error_pct ?? "-"}</td>
                <td className={`text-center font-bold ${r.ok ? "text-emerald-600" : "text-rose-600"}`}>{r.ok ? "OK" : "NG"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showGuide && (
        <iframe src="/guide/uc2866xb-offset.html" title="UC2866XB 偏差扣除操作说明"
          className="w-full rounded-lg border" style={{ height: "76vh" }} />
      )}
    </div>
  );
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
  const [scanHint, setScanHint] = useState(""); // 扫码后的识别提示(识别中/失败原因)
  const [lastScanCode, setLastScanCode] = useState("");
  const [lastRecordNumber, setLastRecordNumber] = useState<string | null>(null);
  const [lastScanUrl, setLastScanUrl] = useState("");
  const [manualRecordNumber, setManualRecordNumber] = useState("");
  const [manualCoreNumber, setManualCoreNumber] = useState("");

  const { data: products = [] } = useQuery({ queryKey: ["products"], queryFn: api.getProducts, refetchInterval: 15000 });
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
    refetchInterval: 15000,
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
    onSuccess: async (data) => {
      refetchStatus();
      // 初始化成功:启用扣偏校验的产品自动进入「扣偏校验」标签,否则直接去「测试」
      if (data?.ok) {
        try {
          const cal = await api.calibrationStatus();
          setActiveTab(cal.enabled && !cal.passed ? "calibration" : "test");
        } catch {
          setActiveTab("test");
        }
      }
    },
  });

  const disconnectMutation = useMutation({ mutationFn: api.disconnect, onSuccess: () => refetchStatus() });

  const isReady = Boolean(status?.ready && status?.product_code === selectedProduct);

  // 扣偏校验(金样):启用了 golden_sample 的产品,校验通过前不允许正式测试
  const calQuery = useQuery({
    queryKey: ["calibration", selectedProduct, isReady],
    queryFn: api.calibrationStatus,
    enabled: isReady,
    refetchInterval: 30000,
  });
  const calEnabled = Boolean(calQuery.data?.enabled);
  const calPassed = Boolean(calQuery.data?.passed);

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
      // 新成品码(铝壳二维码 soaipower.com/t/<9位码> 或裸码):码本身就是序号,序列码留空,不走飞书序号识别
      const finishedCode = parseFinishedCode(rawUrl);
      const code = finishedCode ? "" : extractSerialCode(rawUrl);

      // 扫码模式下也尊重产品配置的必填项
      const reqRec = productDetail?.require_record_number !== false;
      const reqCore = Boolean(productDetail?.require_core_number);
      const recVal = manualRecordNumber.trim();
      const coreVal = manualCoreNumber.trim();
      const isFeishuLabel = rawUrl.includes("feishu.cn/record/");
      // 序号必填:没手填但扫的是标签二维码/新成品码 → 自动拿序号再测;既没手填又不是标签 → 提示
      if (reqRec && !recVal && !isFeishuLabel && !finishedCode) {
        console.warn('[scanner] 序号必填但未填，且扫的不是标签二维码');
        setScanHint("序号必填：请扫产品标签二维码，或先手动填序号再扫");
        return;
      }
      if (reqCore && !coreVal) {
        console.warn('[scanner] 磁芯编号必填但未填，本次扫码忽略');
        setScanHint("磁芯编号必填，请先填磁芯编号");
        return;
      }

      if (calEnabled && !calPassed) {
        console.warn('[scanner] 扣偏校验未通过，扫码测试忽略');
        setScanHint("扣偏校验未通过，请先完成扣偏校验");
        return;
      }
      const run = (recNum: string) => {
        setScanHint("");
        setLastScanCode(code);
        setLastRecordNumber(recNum || null);
        setLastScanUrl(rawUrl);
        if (!testMutation.isPending) {
          testMutation.mutate({ serialCode: code, recordNumber: recNum, coreNumber: coreVal });
        }
      };
      if (finishedCode) {
        if (testMutation.isPending) {
          // 上一台还在测:这次不开测,也不改「最近扫码/序号」,免得把没测的这台显示在上一台结果旁、被补写进上一台的 CSV
          console.warn('[scanner] 测试进行中，新成品码扫码忽略');
          setScanHint("上一台还在测，这次扫码未开测，请测完后重扫");
          return;
        }
        // 新成品码:序号 = 该码(以扫到的码为准),直接开测
        run(finishedCode);
        return;
      }
      if (recVal || !isFeishuLabel) {
        run(recVal);
        return;
      }
      // 没手填序号:向 ERP 查标签对应的序号(飞书分享页已需登录,软件后端会先问 ERP 再兜底爬页)
      setScanHint("正在识别标签序号…");
      api.getFeishuRecordNumber(rawUrl).then((res) => {
        const num = res.ok && res.record_number != null ? String(res.record_number) : "";
        if (num) {
          run(num);
        } else if (reqRec) {
          setScanHint(`标签未识别（${res.message || "标签库里没有这个序列码"}），请手动填序号后重扫`);
        } else {
          run("");
        }
      }).catch(() => {
        if (reqRec) setScanHint("序号识别失败（网络），请手动填序号后重扫");
        else run("");
      });
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
      // 新成品码:后端写 CSV 前已归一化成 9 位大写码,不再补写(补写会用手填原文/链接覆盖掉归一化后的序号)
      if (parseFinishedCode(lastRecordNumber)) return;
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
    // NA(未配置仅展示)不算失败,与后端判定一致
    return lastResult.items.some((x) => x.result === "Fail") ? "FAIL" : "PASS";
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
        <TabsList className={`grid w-full ${calEnabled ? "grid-cols-5" : "grid-cols-4"}`}>
          <TabsTrigger value="console">控制台</TabsTrigger>
          {calEnabled && (
            <TabsTrigger value="calibration" className={!calPassed ? "text-amber-600 data-[state=active]:text-amber-700" : ""}>
              扣偏校验{calPassed ? " ✓" : " ⚠"}
            </TabsTrigger>
          )}
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
                            {p.product_code} - {p.product_name}{p.config_version ? ` (配置v${p.config_version})` : ""}
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
                    <div className="text-xs text-muted-foreground">
                      {selectedName || "-"}
                      {status?.config_version ? <span className="ml-2 text-primary font-medium">运行中配置 v{status.config_version}</span> : null}
                    </div>
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

        {calEnabled && (
          <TabsContent value="calibration" className="mt-4">
            <Card className="panel">
              <CardHeader>
                <CardTitle className="flex items-center justify-between flex-wrap gap-2">
                  <span>扣偏校验（金样）</span>
                  {status?.config_version ? (
                    <span className="text-xs font-normal text-muted-foreground">{status?.product_code} · 配置 v{status.config_version}</span>
                  ) : null}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {!isReady ? (
                  <div className="rounded-lg border bg-amber-50 border-amber-300 text-amber-800 p-4 text-sm">
                    仪器尚未初始化。请先到「控制台」完成初始化，再进行扣偏校验。
                  </div>
                ) : (
                  <CalibrationPanel cal={calQuery.data} onRefetch={() => calQuery.refetch()}
                    onPassed={() => setActiveTab("test")} />
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}

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
                      const recOk = true; // 扫码枪模式:序号由标签二维码自动识别,不要求先手填
                      const coreOk = !reqCore || manualCoreNumber.trim().length > 0;
                      const ready = isReady && recOk && coreOk;
                      let badgeText: string;
                      if (testMutation.isPending) badgeText = "测试中...";
                      else if (!isReady) badgeText = "未就绪";
                      else if (!recOk) badgeText = "请先填序号";
                      else if (!coreOk) badgeText = "请先填磁芯编号";
                      else badgeText = scanHint || "等待扫码（自动识别序号）...";
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
                      const canRun = isReady && !testMutation.isPending && recOk && coreOk && (!calEnabled || calPassed);
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
              {isReady && calEnabled && (
                <div className={`rounded-lg border p-3 text-sm flex items-center gap-3 flex-wrap ${calPassed ? "bg-emerald-50 border-emerald-200" : "bg-amber-50 border-amber-300"}`}>
                  <span className={`font-bold ${calPassed ? "text-emerald-700" : "text-amber-700"}`}>
                    {calPassed ? `扣偏校验已通过 ✓ ${calQuery.data?.checked_at || ""}` : "⚠ 扣偏校验未通过 — 正式测试已锁定"}
                  </span>
                  {calPassed && calQuery.data?.id ? (
                    <span className="text-xs text-muted-foreground mono">校验ID：{calQuery.data.id}</span>
                  ) : null}
                  <Button size="sm" className="ml-auto" variant={calPassed ? "outline" : "default"}
                    onClick={() => setActiveTab("calibration")}>
                    {calPassed ? "重新校验" : "前往扣偏校验"}
                  </Button>
                </div>
              )}
              {(lastScanCode || lastScanUrl) && (
                <div className="rounded-lg border p-3 text-sm bg-blue-50 border-blue-200 text-blue-700 flex items-center gap-4">
                  {/* 新成品码没有序列码,只显示序号 */}
                  {lastScanCode && (
                    <div><span className="font-medium">序列码：</span><span className="mono">{lastScanCode}</span></div>
                  )}
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
                            const isNA = cell.result === "NA";   // 配置外的项(仪器多测的):仅展示读数,不参与判定
                            const fail = !isNA && cell.result !== "Pass";
                            const cfg = (productDetail?.test_items ?? []).find((x) => x.pins === pins && x.test_type === type);
                            const lowText = limitText(cfg?.lower_limit ?? cell.lo_display ?? null, cfg?.unit ?? cell.unit ?? null);
                            const highText = limitText(cfg?.upper_limit ?? cell.hi_display ?? null, cfg?.unit ?? cell.unit ?? null);
                            return (
                              <TableCell key={`${pins}-${type}`} className={`text-center mono ${fail ? "bg-rose-50 text-rose-700 font-semibold" : isNA ? "text-muted-foreground" : "text-foreground"}`}>
                                <div>{formatDisplayValue(cell, cfg?.unit ?? null)}</div>
                                {isNA
                                  ? <div className="text-[0.55em] font-normal leading-snug text-muted-foreground">仅展示·不判定</div>
                                  : (showLimits || fail) && <div className="text-[0.55em] font-normal leading-snug text-muted-foreground">{lowText} ~ {highText}</div>}
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

          {selectedProduct.includes("磁芯检") && (
            <GapCalcPanel productCode={selectedProduct} result={lastResult} />
          )}
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
