// ===== Types =====

export interface Product {
  product_code: string;
  product_name: string;
  instrument_config_id: number;
  description: string;
  test_items: TestItem[];
  enable_eq_n?: boolean;
  eq_n_vars?: {
    l_raw?: string;
    lk_raw?: string;
    l_aux?: string;
  };
  test_items_count?: number;
}

export type ProductBody = Omit<Product, "test_items_count">;

export interface TestItem {
  test_type: string;
  pins: string;
  description: string;
  symbol?: string | null;
  lower_limit: number | null;
  upper_limit: number | null;
  standard_value: number | null;
  unit: string | null;
  tolerance_mode?: "pm" | "max" | "min";
  tolerance_pct?: number | null;
}

export interface InitStatus {
  ok: boolean;
  port?: string;
  idn?: string;
  config_check?: {
    ok: boolean;
    missing: string[];
    extra: string[];
    message: string;
  };
  message: string;
}

export interface SystemStatus {
  ready: boolean;
  product_code: string | null;
  port: string;
}

export interface MeasuredItem {
  type: string;
  pins: string;
  value: number;
  lo: number;
  hi: number;
  result: string;
  unit?: string | null;
  value_display?: number;
  lo_display?: number | null;
  hi_display?: number | null;
  error?: string;
}

export interface TestResult {
  ok: boolean;
  timestamp: string;
  product_code: string;
  overall: string;
  passed: number;
  failed: number;
  items: MeasuredItem[];
  csv_file: string;
}

export interface CsvResult {
  filename: string;
  size: number;
}

export interface LogItem {
  id: number;
  ts: string;
  level: string;
  message: string;
}

export interface LogResponse {
  items: LogItem[];
  last_id: number;
  file: string;
}

// ===== API calls =====

const BASE = "/api";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  getProducts: () => request<Product[]>("/products"),
  getProduct: (code: string) => request<Product>(`/products/${code}`),
  createProduct: (data: ProductBody) =>
    request<Product>("/products", { method: "POST", body: JSON.stringify(data) }),
  updateProduct: (code: string, data: ProductBody) =>
    request<Product>(`/products/${code}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProduct: (code: string) => request<void>(`/products/${code}`, { method: "DELETE" }),
  getStatus: () => request<SystemStatus>("/status"),
  initialize: (productCode: string, port?: string) =>
    request<InitStatus>("/initialize", {
      method: "POST",
      body: JSON.stringify({ product_code: productCode, port }),
    }),
  runTest: () => request<TestResult>("/test/run", { method: "POST" }),
  disconnect: () => request<void>("/disconnect", { method: "POST" }),
  getResults: () => request<CsvResult[]>("/results"),
  getLogs: (since = 0) => request<LogResponse>(`/logs?since=${since}`),
};

// ===== Unit conversion =====

export function formatValue(item: MeasuredItem): string {
  const display = item.value_display ?? item.value;
  const unit = item.unit;
  if (typeof display !== "number" || Number.isNaN(display)) return "-";
  if (unit) return `${Number(display.toFixed(6)).toString()} ${unit}`;
  return Number(display.toFixed(6)).toString();
}

export function formatMeasuredValue(type: string, value: number): string {
  return formatValue({ type, value } as MeasuredItem);
}

export function formatLimit(type: string, value: number): string {
  if (value === 0) return "-";
  return formatMeasuredValue(type, value);
}
