import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type ProductBody, type TestItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerFooter } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const TEST_TYPES = ["Turn", "Lx", "Q", "Lk", "Cx", "Dcr"];
const UNITS: Record<string, string[]> = {
  Turn: [],
  Q: [],
  Lx: ["H", "mH", "μH", "nH"],
  Lk: ["H", "mH", "μH", "nH"],
  Cx: ["F", "mF", "μF", "nF", "pF"],
  Dcr: ["Ω", "mΩ", "kΩ"],
};

function emptyProduct(): ProductBody {
  return {
    product_code: "",
    product_name: "",
    instrument_config_id: 1,
    description: "",
    test_items: [],
    enable_eq_n: false,
    eq_n_vars: { l_raw: "A", lk_raw: "B", l_aux: "C" },
  };
}

function emptyItem(): TestItem {
  return {
    test_type: "Turn",
    pins: "",
    description: "",
    symbol: null,
    lower_limit: null,
    upper_limit: null,
    standard_value: null,
    unit: null,
    tolerance_mode: "pm",
    tolerance_pct: null,
  };
}

function indexToSymbol(index: number): string {
  let n = index;
  let out = "";
  do {
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}

function ensureSymbols(items: TestItem[]): TestItem[] {
  return items.map((item, i) => ({
    ...item,
    symbol: (item.symbol ?? "").trim().toUpperCase() || indexToSymbol(i),
  }));
}

function normalizeItem(item: TestItem): TestItem {
  const mode = item.tolerance_mode ?? (item.lower_limit != null && item.upper_limit == null ? "min" : item.upper_limit != null && item.lower_limit == null ? "max" : "pm");
  return {
    ...item,
    symbol: (item.symbol ?? "").trim().toUpperCase() || null,
    tolerance_mode: mode,
    tolerance_pct: item.tolerance_pct ?? null,
  };
}

function round6(n: number) {
  return Number(n.toFixed(6));
}

function splitPins(pins: string): [string, string] {
  const [a, b] = pins.split("-");
  return [a ?? "", b ?? ""];
}

function joinPins(a: string, b: string): string {
  const left = a.trim();
  const right = b.trim();
  if (!left && !right) return "";
  return `${left}-${right}`;
}

export default function AdminPage() {
  const qc = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isEdit, setIsEdit] = useState(false);
  const [form, setForm] = useState<ProductBody>(emptyProduct());
  const [keyword, setKeyword] = useState("");

  const { data: products = [], isLoading } = useQuery({
    queryKey: ["products"],
    queryFn: api.getProducts,
  });

  const saveMutation = useMutation({
    mutationFn: (data: ProductBody) =>
      isEdit ? api.updateProduct(data.product_code, data) : api.createProduct(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setDrawerOpen(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteProduct,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return products;
    return products.filter(
      (p) =>
        p.product_code.toLowerCase().includes(q) ||
        p.product_name.toLowerCase().includes(q)
    );
  }, [keyword, products]);

  function openCreate() {
    setForm(emptyProduct());
    setIsEdit(false);
    setDrawerOpen(true);
  }

  async function openEdit(code: string) {
    const product = await api.getProduct(code);
    setForm({
      ...product,
      enable_eq_n: Boolean(product.enable_eq_n),
      eq_n_vars: {
        l_raw: product.eq_n_vars?.l_raw ?? "A",
        lk_raw: product.eq_n_vars?.lk_raw ?? "B",
        l_aux: product.eq_n_vars?.l_aux ?? "C",
      },
      test_items: ensureSymbols((product.test_items ?? []).map(normalizeItem)),
    });
    setIsEdit(true);
    setDrawerOpen(true);
  }

  function updateItem(index: number, field: keyof TestItem, value: unknown) {
    const items = [...form.test_items];
    items[index] = { ...items[index], [field]: value };
    setForm((f) => ({ ...f, test_items: items }));
  }

  function recalcLimits(index: number, patch: Partial<TestItem>) {
    const items = [...form.test_items];
    const next = { ...items[index], ...patch };
    const mode = next.tolerance_mode ?? "pm";
    const center = typeof next.standard_value === "number" ? next.standard_value : null;

    if (mode === "pm") {
      const pct = typeof next.tolerance_pct === "number" ? next.tolerance_pct : null;
      if (center != null && pct != null) {
        const delta = Math.abs(center) * (pct / 100);
        next.lower_limit = round6(center - delta);
        next.upper_limit = round6(center + delta);
      } else {
        next.lower_limit = null;
        next.upper_limit = null;
      }
    } else if (mode === "max") {
      next.tolerance_pct = null;
      next.upper_limit = center != null ? round6(center) : null;
      next.lower_limit = null;
    } else {
      next.tolerance_pct = null;
      next.lower_limit = center != null ? round6(center) : null;
      next.upper_limit = null;
    }

    items[index] = next;
    setForm((f) => ({ ...f, test_items: items }));
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-[1.4fr_0.6fr]">
        <Card className="panel">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>产品配置管理</span>
              <Button onClick={openCreate}>新建产品</Button>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-3 items-center justify-between">
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索产品料号或名称"
                className="max-w-xs"
              />
              <div className="text-sm text-muted-foreground">
                共 {products.length} 个产品，当前显示 {filtered.length} 个
              </div>
            </div>

            {isLoading ? (
              <div className="text-sm text-muted-foreground">加载中...</div>
            ) : (
              <div className="overflow-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-secondary">
                      <TableHead>料号</TableHead>
                      <TableHead>名称</TableHead>
                      <TableHead className="text-center">配置编号</TableHead>
                      <TableHead className="text-center">测试项</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((p) => (
                      <TableRow key={p.product_code}>
                        <TableCell className="mono font-medium">{p.product_code}</TableCell>
                        <TableCell>{p.product_name}</TableCell>
                        <TableCell className="text-center">{p.instrument_config_id}</TableCell>
                        <TableCell className="text-center">
                          <Badge variant="outline">{p.test_items_count ?? p.test_items?.length ?? 0} 项</Badge>
                        </TableCell>
                        <TableCell className="text-right space-x-2">
                          <Button size="sm" variant="outline" onClick={() => openEdit(p.product_code)}>
                            编辑
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => {
                              if (confirm(`删除 ${p.product_code}？`)) deleteMutation.mutate(p.product_code);
                            }}
                          >
                            删除
                          </Button>
                        </TableCell>
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
            <CardTitle>配置要点</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="rounded-lg border p-3 bg-secondary">
              料号、名称与仪器配置编号需与实际工艺一致。
            </div>
            <div className="rounded-lg border p-3 bg-secondary">
              JSON 要求必须全有，多余项不会影响测试。
            </div>
            <div className="rounded-lg border p-3 bg-secondary">
              单位只影响显示，不影响仪器判定结果。
            </div>
          </CardContent>
        </Card>
      </div>

      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} direction="right" modal={false}>
        <DrawerContent className="w-[92vw] max-w-none h-full flex flex-col ml-auto">
          <DrawerHeader>
            <DrawerTitle>{isEdit ? "编辑产品配置" : "新建产品配置"}</DrawerTitle>
          </DrawerHeader>

          <div className="flex-1 overflow-y-auto px-6 space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>产品料号</Label>
                <Input
                  value={form.product_code}
                  disabled={isEdit}
                  onChange={(e) => setForm((f) => ({ ...f, product_code: e.target.value }))}
                />
              </div>
              <div>
                <Label>产品名称</Label>
                <Input
                  value={form.product_name}
                  onChange={(e) => setForm((f) => ({ ...f, product_name: e.target.value }))}
                />
              </div>
              <div>
                <Label>仪器配置编号</Label>
                <Input
                  type="number"
                  value={form.instrument_config_id}
                  onChange={(e) => setForm((f) => ({ ...f, instrument_config_id: +e.target.value }))}
                />
              </div>
              <div>
                <Label>描述（选填）</Label>
                <Input
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
            </div>

            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center gap-2">
                <input
                  id="enable_eq_n"
                  type="checkbox"
                  checked={Boolean(form.enable_eq_n)}
                  onChange={(e) => setForm((f) => ({ ...f, enable_eq_n: e.target.checked }))}
                />
                <Label htmlFor="enable_eq_n">启用等效n计算（sqrt((A-B)/C)）</Label>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label>L原变量</Label>
                  <Input
                    className="h-9 text-sm mono"
                    value={form.eq_n_vars?.l_raw ?? "A"}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        eq_n_vars: { ...(f.eq_n_vars ?? {}), l_raw: e.target.value.toUpperCase() },
                      }))
                    }
                    disabled={!form.enable_eq_n}
                  />
                </div>
                <div>
                  <Label>Lk变量</Label>
                  <Input
                    className="h-9 text-sm mono"
                    value={form.eq_n_vars?.lk_raw ?? "B"}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        eq_n_vars: { ...(f.eq_n_vars ?? {}), lk_raw: e.target.value.toUpperCase() },
                      }))
                    }
                    disabled={!form.enable_eq_n}
                  />
                </div>
                <div>
                  <Label>L副变量</Label>
                  <Input
                    className="h-9 text-sm mono"
                    value={form.eq_n_vars?.l_aux ?? "C"}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        eq_n_vars: { ...(f.eq_n_vars ?? {}), l_aux: e.target.value.toUpperCase() },
                      }))
                    }
                    disabled={!form.enable_eq_n}
                  />
                </div>
              </div>
            </div>

            <Separator />

            <div>
              <div className="flex justify-between items-center mb-2">
                <Label className="text-base">测试项目（{form.test_items.length} 项）</Label>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setForm((f) => ({
                      ...f,
                      test_items: ensureSymbols([...f.test_items, emptyItem()]),
                    }))
                  }
                >
                  添加测试项
                </Button>
              </div>

              <div className="border rounded overflow-x-auto overflow-y-auto max-h-[420px]">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-secondary">
                      <TableHead>变量</TableHead>
                      <TableHead>类型</TableHead>
                      <TableHead>引脚</TableHead>
                      <TableHead>说明</TableHead>
                      <TableHead>单位</TableHead>
                      <TableHead>误差方式</TableHead>
                      <TableHead>中心值</TableHead>
                      <TableHead>误差(%)</TableHead>
                      <TableHead>下限(自动)</TableHead>
                      <TableHead>上限(自动)</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {form.test_items.map((item, i) => (
                      <TableRow key={i}>
                        <TableCell>
                          <Input
                            className="h-8 text-xs w-14 text-center mono"
                            value={(item.symbol ?? "").toUpperCase()}
                            onChange={(e) => updateItem(i, "symbol", e.target.value.toUpperCase())}
                            placeholder={indexToSymbol(i)}
                          />
                        </TableCell>
                        <TableCell>
                          <Select value={item.test_type} onValueChange={(v) => updateItem(i, "test_type", v)}>
                            <SelectTrigger className="h-8 text-xs w-24">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {TEST_TYPES.map((t) => (
                                <SelectItem key={t} value={t}>{t}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell>
                          {(() => {
                            const [a, b] = splitPins(item.pins);
                            return (
                              <div className="flex items-center gap-1">
                                <Input
                                  className="h-8 text-xs w-12 text-center"
                                  value={a}
                                  onChange={(e) => updateItem(i, "pins", joinPins(e.target.value, b))}
                                  placeholder="3"
                                />
                                <span className="text-xs text-muted-foreground">-</span>
                                <Input
                                  className="h-8 text-xs w-12 text-center"
                                  value={b}
                                  onChange={(e) => updateItem(i, "pins", joinPins(a, e.target.value))}
                                  placeholder="1"
                                />
                              </div>
                            );
                          })()}
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-8 text-xs w-32"
                            value={item.description}
                            onChange={(e) => updateItem(i, "description", e.target.value)}
                          />
                        </TableCell>
                        <TableCell>
                          <Select value={item.unit ?? "__none__"} onValueChange={(v) => updateItem(i, "unit", v === "__none__" ? null : v)}>
                            <SelectTrigger className="h-8 text-xs w-20">
                              <SelectValue placeholder="-" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__none__">-</SelectItem>
                              {(UNITS[item.test_type] ?? []).map((u) => (
                                <SelectItem key={u} value={u}>{u}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell>
                          <Select
                            value={item.tolerance_mode ?? "pm"}
                            onValueChange={(v) => recalcLimits(i, { tolerance_mode: v as TestItem["tolerance_mode"] })}
                          >
                            <SelectTrigger className="h-8 text-xs w-24">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="pm">±</SelectItem>
                              <SelectItem value="max">max</SelectItem>
                              <SelectItem value="min">min</SelectItem>
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-8 text-xs w-28"
                            type="number"
                            value={item.standard_value ?? ""}
                            onChange={(e) =>
                              recalcLimits(i, {
                                standard_value: e.target.value ? +e.target.value : null,
                              })
                            }
                          />
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-8 text-xs w-24"
                            type="number"
                            disabled={(item.tolerance_mode ?? "pm") !== "pm"}
                            value={item.tolerance_pct ?? ""}
                            onChange={(e) =>
                              recalcLimits(i, {
                                tolerance_pct: e.target.value ? +e.target.value : null,
                              })
                            }
                          />
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-8 text-xs w-24"
                            type="number"
                            value={item.lower_limit ?? ""}
                            readOnly
                          />
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-8 text-xs w-24"
                            type="number"
                            value={item.upper_limit ?? ""}
                            readOnly
                          />
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 text-destructive px-2"
                            onClick={() => setForm((f) => ({ ...f, test_items: f.test_items.filter((_, j) => j !== i) }))}
                          >
                            删除
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          </div>

          <DrawerFooter className="border-t mt-auto">
            <Button
              onClick={() =>
                saveMutation.mutate({
                  ...form,
                  test_items: ensureSymbols(form.test_items),
                  enable_eq_n: Boolean(form.enable_eq_n),
                  eq_n_vars: {
                    l_raw: (form.eq_n_vars?.l_raw ?? "A").trim().toUpperCase() || "A",
                    lk_raw: (form.eq_n_vars?.lk_raw ?? "B").trim().toUpperCase() || "B",
                    l_aux: (form.eq_n_vars?.l_aux ?? "C").trim().toUpperCase() || "C",
                  },
                })
              }
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? "保存中..." : "保存"}
            </Button>
            <Button variant="outline" onClick={() => setDrawerOpen(false)}>
              取消
            </Button>
            {saveMutation.error && (
              <p className="text-destructive text-sm">{(saveMutation.error as Error).message}</p>
            )}
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    </div>
  );
}
