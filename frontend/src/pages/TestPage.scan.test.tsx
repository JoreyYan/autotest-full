import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TestPage from "./TestPage";

// Radix Select 在 jsdom 里不好点,换成简单按钮:点 pick-<料号> 即选中该产品
vi.mock("@/components/ui/select", async () => {
  const React = await import("react");
  const Ctx = React.createContext<(v: string) => void>(() => {});
  return {
    Select: ({ onValueChange, children }: { onValueChange: (v: string) => void; children: React.ReactNode }) =>
      React.createElement(Ctx.Provider, { value: onValueChange }, children),
    SelectTrigger: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
    SelectValue: () => null,
    SelectContent: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
    SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => {
      const pick = React.useContext(Ctx);
      return React.createElement("button", { type: "button", "data-testid": `pick-${value}`, onClick: () => pick(value) }, children);
    },
  };
});

type Call = { url: string; method: string; body: Record<string, unknown> | undefined };

const heldRuns: Array<() => void> = [];

function setupBackend(opts: { requireRecord?: boolean; requireCore?: boolean; feishuNumber?: string | null; holdRun?: boolean } = {}) {
  const calls: Call[] = [];
  // holdRun:测试请求先挂起,调 releaseRuns() 才返回(模拟「上一台还在测」)
  heldRuns.length = 0;
  const reply = (data: unknown) => ({
    ok: true,
    status: 200,
    json: async () => data,
    text: async () => JSON.stringify(data),
  });
  const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    const path = url.split("?")[0];
    if (path === "/api/products") {
      return reply([{ product_code: "P1", product_name: "产品1", instrument_config_id: 1, workflow_type: "fixture_test", description: "", test_items: [] }]);
    }
    if (path === "/api/products/P1") {
      return reply({
        product_code: "P1", product_name: "产品1", instrument_config_id: 1, workflow_type: "fixture_test", description: "", test_items: [],
        require_record_number: opts.requireRecord ?? true,
        require_core_number: opts.requireCore ?? false,
      });
    }
    if (path === "/api/status") return reply({ ready: true, product_code: "P1", port: "COM3" });
    if (path === "/api/results") return reply([]);
    if (path === "/api/logs") return reply({ items: [], last_id: 0, file: "" });
    if (path === "/api/calibration/status") return reply({ enabled: false, tolerance_pct: 0.5, passed: false, checked_at: null, detail: [] });
    if (path === "/api/feishu/record-number") {
      const num = opts.feishuNumber ?? null;
      return reply({ ok: num != null, record_number: num, message: num ? "" : "标签库里没有这个序列码" });
    }
    if (path === "/api/test/run") {
      if (opts.holdRun) await new Promise<void>((r) => heldRuns.push(r));
      return reply({
        ok: true, timestamp: "2026-09-17 10:00:00", product_code: "P1", serial_code: body?.serial_code ?? "",
        overall: "PASS", passed: 0, failed: 0, items: [], csv_file: "results/P1.csv",
      });
    }
    return reply({ ok: true });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function releaseRuns() {
  // 放行所有挂起的测试请求
  const fns = heldRuns.splice(0);
  fns.forEach((f) => f());
}

async function renderReady(calls: Call[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TestPage />
    </QueryClientProvider>
  );
  fireEvent.click(await screen.findByTestId("pick-P1"));
  // 等产品详情(必填项)与连接状态都拿到,扫码监听才按正确规则挂上
  await waitFor(() => expect(calls.some((c) => c.url === "/api/products/P1")).toBe(true));
  await screen.findAllByText(/连接状态：就绪/);
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

function scan(text: string) {
  for (const ch of text) fireEvent.keyDown(document.body, { key: ch });
  fireEvent.keyDown(document.body, { key: "Enter" });
}

const runCalls = (calls: Call[]) => calls.filter((c) => c.url === "/api/test/run" && c.method === "POST");
const feishuCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/feishu/record-number"));
const patchCalls = (calls: Call[]) => calls.filter((c) => c.url === "/api/test/patch-record-number");

// 「测试」标签页只在测完后自动切过去;测试进行中/手动模式要先手动切过去才能看到按钮、徽标和扫码结果
async function openTestTab() {
  fireEvent.mouseDown(screen.getByRole("tab", { name: "测试" }), { button: 0 });
  await screen.findByText("测试结果");
}

async function settle(ms = 100) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

describe("TestPage 扫码枪:新成品码直接当序号开测", () => {
  beforeEach(() => {
    if (!("ResizeObserver" in window)) {
      vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    }
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("扫成品码二维码链接 → record_number=码、serial_code 为空,不走飞书识别", async () => {
    const calls = setupBackend();
    await renderReady(calls);
    scan("https://www.soaipower.com/t/26HK04426");
    await waitFor(() => expect(runCalls(calls)).toHaveLength(1));
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "", record_number: "26HK04426", core_number: "" });
    await settle();
    expect(feishuCalls(calls)).toHaveLength(0);
  });

  it("扫裸码(小写)也识别为成品码", async () => {
    const calls = setupBackend();
    await renderReady(calls);
    scan("26hk04426");
    await waitFor(() => expect(runCalls(calls)).toHaveLength(1));
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "", record_number: "26HK04426", core_number: "" });
    expect(feishuCalls(calls)).toHaveLength(0);
  });

  it("产品要求磁芯编号但没填 → 成品码也不开测(沿用原规则)", async () => {
    const calls = setupBackend({ requireCore: true });
    await renderReady(calls);
    scan("https://www.soaipower.com/t/26HK04426");
    await settle(200);
    expect(runCalls(calls)).toHaveLength(0);
    expect(feishuCalls(calls)).toHaveLength(0);
  });

  it("校验位不对的码按普通文字处理:序号必填且没手填 → 不开测", async () => {
    const calls = setupBackend();
    await renderReady(calls);
    scan("https://www.soaipower.com/t/26HK04427");
    await settle(200);
    expect(runCalls(calls)).toHaveLength(0);
    expect(feishuCalls(calls)).toHaveLength(0);
  });

  it("上一台还在测时扫下一台成品码 → 不开测、不改显示的序号、不补写 CSV,并提示重扫", async () => {
    const calls = setupBackend({ holdRun: true });
    await renderReady(calls);
    await openTestTab();
    scan("https://www.soaipower.com/t/26HK04426");
    await waitFor(() => expect(runCalls(calls)).toHaveLength(1));
    await screen.findAllByText("测试中...");
    await settle(20);
    scan("26HK04439");
    await settle(100);
    expect(runCalls(calls)).toHaveLength(1);
    // 挂起期间显示的序号仍是正在测的这台
    expect(screen.getByText("26HK04426")).toBeTruthy();
    expect(screen.queryByText("26HK04439")).toBeNull();
    await act(async () => {
      releaseRuns();
    });
    await screen.findByText("上一台还在测，这次扫码未开测，请测完后重扫");
    await settle(100);
    expect(runCalls(calls)).toHaveLength(1);
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "", record_number: "26HK04426", core_number: "" });
    expect(screen.getByText("26HK04426")).toBeTruthy();
    expect(screen.queryByText("26HK04439")).toBeNull();
    // 新码由后端写 CSV 时归一化,前端不补写
    expect(patchCalls(calls)).toHaveLength(0);
  });
});

describe("TestPage 扫码枪:旧码保持 1.7.4 行为", () => {
  beforeEach(() => {
    if (!("ResizeObserver" in window)) {
      vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    }
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("飞书标签链接 → 先查序号,再以 token 为序列码开测", async () => {
    const calls = setupBackend({ feishuNumber: "260YN0062" });
    await renderReady(calls);
    const link = "https://smartonep.feishu.cn/record/RIHurixiWeFAwaceOSocl0uenIe";
    scan(link);
    await waitFor(() => expect(runCalls(calls)).toHaveLength(1));
    expect(feishuCalls(calls)).toHaveLength(1);
    expect(feishuCalls(calls)[0].url).toBe(`/api/feishu/record-number?url=${encodeURIComponent(link)}`);
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "RIHurixiWeFAwaceOSocl0uenIe", record_number: "260YN0062", core_number: "" });
    // 旧码:测完照旧补写序号到 CSV(与 1.7.4 相同)
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body).toEqual({ csv_file: "results/P1.csv", record_number: "260YN0062" });
  });

  it("其他文字 + 序号必填 + 没手填 → 不开测", async () => {
    const calls = setupBackend();
    await renderReady(calls);
    scan("260YN0062");
    await settle(200);
    expect(runCalls(calls)).toHaveLength(0);
    expect(feishuCalls(calls)).toHaveLength(0);
  });

  it("其他文字 + 序号非必填 → 原文当序列码开测", async () => {
    const calls = setupBackend({ requireRecord: false });
    await renderReady(calls);
    scan("260YN0062");
    await waitFor(() => expect(runCalls(calls)).toHaveLength(1));
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "260YN0062", record_number: "", core_number: "" });
    expect(feishuCalls(calls)).toHaveLength(0);
  });
});

describe("TestPage 手动模式:序号框填新码", () => {
  beforeEach(() => {
    if (!("ResizeObserver" in window)) {
      vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    }
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function manualRun(calls: Call[], recordNumber: string) {
    await renderReady(calls);
    fireEvent.click(screen.getByRole("switch"));
    await openTestTab();
    const input = await screen.findByPlaceholderText("序号");
    fireEvent.change(input, { target: { value: recordNumber } });
    fireEvent.click(screen.getByRole("button", { name: "开始测试" }));
    await waitFor(() => expect(runCalls(calls)).toHaveLength(1));
    await settle(150);
  }

  it("填成品码链接(小写)→ 原文交后端归一化,测完不补写 CSV(不用原文覆盖归一化后的序号)", async () => {
    const calls = setupBackend();
    const raw = "https://www.soaipower.com/t/26hk04426";
    await manualRun(calls, raw);
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "", record_number: raw, core_number: "" });
    expect(patchCalls(calls)).toHaveLength(0);
  });

  it("填旧序号 → 测完照旧补写序号到 CSV(与 1.7.4 相同)", async () => {
    const calls = setupBackend();
    await manualRun(calls, "260YN0062");
    expect(runCalls(calls)[0].body).toEqual({ serial_code: "", record_number: "260YN0062", core_number: "" });
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body).toEqual({ csv_file: "results/P1.csv", record_number: "260YN0062" });
  });
});
