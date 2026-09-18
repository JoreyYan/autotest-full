import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminPage from "./AdminPage";

function setupBackend(cloud: "ok" | "error" | "time-number") {
  const reply = (data: unknown, status = 200) => ({
    ok: status < 400,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  });
  const fetchMock = vi.fn(async (input: unknown) => {
    const path = String(input).split("?")[0];
    if (path === "/api/products") return reply([]);
    if (path === "/api/cloud-upload/status") {
      if (cloud === "error") return reply({ detail: "Not Found" }, 404);
      return reply({
        url: "http://127.0.0.1:9/ingest",
        pending: 3,
        rejected: 1,
        last_ok_at: cloud === "time-number" ? null : "2026-09-17 10:20:30",
        last_error: null,
        running: true,
      });
    }
    return reply({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AdminPage />
    </QueryClientProvider>
  );
}

describe("AdminPage 新码直推云端状态行", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("显示待传/退回/最近成功", async () => {
    setupBackend("ok");
    renderPage();
    expect(await screen.findByText("新码直推云端：待传 3 条 · 退回 1 条 · 最近成功 2026-09-17 10:20:30")).toBeInTheDocument();
  });

  it("还没成功过显示「暂无」", async () => {
    setupBackend("time-number");
    renderPage();
    expect(await screen.findByText(/最近成功 暂无/)).toBeInTheDocument();
  });

  it("接口不可用时不显示、页面照常", async () => {
    const fetchMock = setupBackend("error");
    renderPage();
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/cloud-upload/status")).toBe(true));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.queryByText(/新码直推云端/)).toBeNull();
    expect(screen.getByText("产品参数（只读）")).toBeInTheDocument();
  });
});
