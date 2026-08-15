import { useEffect, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, MapPin, ArrowUpCircle } from "lucide-react";

/** 首次启动门控：未注册工位时挡住整个应用，显示注册页。 */
export function DeploymentGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading, refetch } = useQuery({ queryKey: ["deployment"], queryFn: api.getDeployment });
  const [company, setCompany] = useState("");
  const [line, setLine] = useState("");
  const [station, setStation] = useState("");
  const reg = useMutation({
    mutationFn: () => api.registerDeployment(company.trim(), line.trim(), station.trim()),
    onSuccess: () => refetch(),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }
  if (data?.deployment_id) return <>{children}</>;

  const ready = company.trim() && line.trim() && station.trim();
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><MapPin className="h-5 w-5" />首次启动 · 注册工位</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-slate-500">
            这台设备属于哪个工位？注册后，产品参数由 ERP 统一下发，本机<b>只读、不可编辑</b>。此信息只填一次。
          </p>
          <div><Label>公司</Label><Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="如 汉润" /></div>
          <div><Label>产线</Label><Input value={line} onChange={(e) => setLine(e.target.value)} placeholder="如 X产线" /></div>
          <div><Label>工段</Label><Input value={station} onChange={(e) => setStation(e.target.value)} placeholder="如 磁芯检" /></div>
          {reg.error && <div className="text-sm text-rose-600">{(reg.error as Error).message}</div>}
          <Button className="w-full h-11" disabled={!ready || reg.isPending} onClick={() => reg.mutate()}>
            {reg.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
            注册工位
          </Button>
          <p className="text-xs text-slate-400">
            注册后请到 ERP「工位参数下发」给本工位下发产品参数，否则无产品可测。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

/** 发现新版本时的顶部横幅：点「立即更新」→ 后端下载替换自动重启 → 检测到新版本号后刷新页面。 */
export function UpdateBanner() {
  const { data } = useQuery({
    queryKey: ["update-check"],
    queryFn: api.checkUpdate,
    refetchInterval: 30 * 60 * 1000,
    retry: false,
  });
  const [phase, setPhase] = useState<"idle" | "applying" | "waiting" | "failed">("idle");
  const [errMsg, setErrMsg] = useState("");

  useEffect(() => {
    if (phase !== "waiting" || !data?.latest) return;
    const timer = setInterval(async () => {
      try {
        const v = await api.getVersion();
        if (v.version === data.latest) window.location.reload();
      } catch {
        /* 后端重启中，继续等 */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [phase, data?.latest]);

  if (!data?.available) return null;
  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center gap-3 text-sm">
      <ArrowUpCircle className="h-4 w-4 text-amber-600 shrink-0" />
      {phase === "waiting" ? (
        <span className="text-amber-800 flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在更新到 v{data.latest}，软件将自动重启，请稍候（约 30 秒）...
        </span>
      ) : (
        <>
          <span className="text-amber-800">
            发现新版本 <b>v{data.latest}</b>（当前 v{data.current}）{data.notes ? ` · ${data.notes}` : ""}
          </span>
          <Button
            size="sm"
            className="h-7 ml-auto"
            disabled={phase === "applying"}
            onClick={async () => {
              setPhase("applying");
              setErrMsg("");
              try {
                await api.applyUpdate();
                setPhase("waiting");
              } catch (e) {
                setPhase("failed");
                setErrMsg((e as Error).message);
              }
            }}
          >
            {phase === "applying" ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}
            立即更新
          </Button>
          {phase === "failed" && <span className="text-rose-600 text-xs">更新失败：{errMsg}</span>}
        </>
      )}
    </div>
  );
}

/** 顶部显示当前工位（公司/产线/工段）+ 软件版本号。 */
export function StationBadge() {
  const { data } = useQuery({ queryKey: ["version"], queryFn: api.getVersion, refetchInterval: 60000 });
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      {data?.deployment_id && (
        <span className="flex items-center gap-1">
          <MapPin className="h-3.5 w-3.5" />
          <span className="font-medium text-foreground">{data.company}</span>
          <span>/ {data.line} / {data.station}</span>
        </span>
      )}
      {data?.version && <span className="px-1.5 py-0.5 rounded bg-secondary text-[10px] font-mono">v{data.version}</span>}
    </div>
  );
}
