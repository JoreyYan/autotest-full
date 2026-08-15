// ===== Types =====

export interface Product {
  product_code: string;
  product_name: string;
  instrument_config_id: number;
  instrument_driver?: string;
  workflow_type?: string;
  description: string;
  test_items: TestItem[];
  inspection_steps?: InspectionStep[];
  enable_eq_n?: boolean;
  eq_n_vars?: {
    l_raw?: string;
    lk_raw?: string;
    l_aux?: string;
    n_standard?: number;
    n_tolerance_pct?: number;
    n_lower?: number;
    n_upper?: number;
  };
  require_record_number?: boolean;
  require_core_number?: boolean;
  test_items_count?: number;
  inspection_steps_count?: number;
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

export interface InspectionMeasurement {
  name: string;
  function_code: string;
  frequency_hz?: number | null;
  voltage_v?: number | null;
  aperture_mode?: string | null;
  average_count?: number | null;
  primary_label?: string | null;
  primary_unit?: string | null;
  primary_lower?: number | null;
  primary_upper?: number | null;
  secondary_label?: string | null;
  secondary_unit?: string | null;
  secondary_lower?: number | null;
  secondary_upper?: number | null;
}

export interface InspectionStep {
  pins: string;
  prompt?: string;
  measurements: InspectionMeasurement[];
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
  workflow_type?: string;
  current_step_index?: number;
  total_steps?: number;
  next_prompt?: string;
  message: string;
}

export interface SystemStatus {
  ready: boolean;
  product_code: string | null;
  port: string;
}

export interface InspectionStatus {
  ready: boolean;
  product_code: string | null;
  port: string;
  workflow_type: string;
  current_step_index: number;
  total_steps: number;
  next_prompt: string;
  completed_steps: number;
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
  serial_code: string;
  overall: string;
  passed: number;
  failed: number;
  items: MeasuredItem[];
  csv_file: string;
}

export interface InspectionItemResult {
  pins: string;
  name: string;
  function_code?: string;
  primary_label: string;
  primary_unit: string;
  primary_value: number;
  primary_value_display: number;
  primary_lower?: number | null;
  primary_upper?: number | null;
  primary_result: string;
  secondary_label?: string;
  secondary_unit?: string;
  secondary_value?: number;
  secondary_value_display?: number;
  secondary_lower?: number | null;
  secondary_upper?: number | null;
  secondary_result?: string;
  instrument_status?: number;
  raw?: string;
  error?: string;
  result: string;
}

export interface InspectionStepResult {
  ok: boolean;
  step_index: number;
  pins: string;
  step_result: string;
  items: InspectionItemResult[];
  finished: boolean;
  next_prompt: string;
  overall: string;
  csv_file?: string;
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
  getInspectionStatus: () => request<InspectionStatus>("/inspection/status"),
  initializeInspection: (productCode: string, port: string) =>
    request<InitStatus>("/inspection/initialize", {
      method: "POST",
      body: JSON.stringify({ product_code: productCode, port }),
    }),
  runInspectionStep: () => request<InspectionStepResult>("/inspection/run-step", { method: "POST" }),
  runTest: (params?: { serialCode?: string; recordNumber?: string; coreNumber?: string }) =>
    request<TestResult>("/test/run", {
      method: "POST",
      body: JSON.stringify({
        serial_code: params?.serialCode || "",
        record_number: params?.recordNumber || "",
        core_number: params?.coreNumber || "",
      }),
    }),
  disconnect: () => request<void>("/disconnect", { method: "POST" }),
  getResults: () => request<CsvResult[]>("/results"),
  getLogs: (since = 0) => request<LogResponse>(`/logs?since=${since}`),
  patchRecordNumber: (csvFile: string, recordNumber: string) =>
    request<{ ok: boolean }>("/test/patch-record-number", {
      method: "POST",
      body: JSON.stringify({ csv_file: csvFile, record_number: recordNumber }),
    }),
  getFeishuRecordNumber: (url: string) =>
    request<{ ok: boolean; record_number: string | null; message?: string }>(
      `/feishu/record-number?url=${encodeURIComponent(url)}`
    ),
  uploadConfig: () =>
    request<{ ok: boolean; created: number; updated: number; failed: number; total_local: number }>(
      "/config/upload",
      { method: "POST", body: "{}" }
    ),
  downloadConfig: () =>
    request<{ ok: boolean; saved: number; failed: number; products: string[] }>(
      "/config/download",
      { method: "POST", body: "{}" }
    ),
  getDeployment: () =>
    request<{ deployment_id: string; company: string; line: string; station: string }>("/deployment"),
  getVersion: () =>
    request<{ version: string; deployment_id: string; company: string; line: string; station: string }>("/version"),
  registerDeployment: (company: string, line: string, station: string) =>
    request<{ ok: boolean; deployment_id: string }>("/deployment/register", {
      method: "POST",
      body: JSON.stringify({ company, line, station }),
    }),
  checkUpdate: () =>
    request<{ ok: boolean; current: string; latest?: string; notes?: string; file_size?: number; available: boolean; error?: string }>(
      "/update/check"
    ),
  applyUpdate: () =>
    request<{ ok: boolean; message: string }>("/update/apply", { method: "POST", body: "{}" }),
  syncParams: () =>
    request<{ ok: boolean; updated: { product_code: string; version: number }[]; archived: string[]; total_remote: number }>(
      "/deployment/sync-params",
      { method: "POST", body: "{}" }
    ),
};

export interface Deployment { deployment_id: string; company: string; line: string; station: string }

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
