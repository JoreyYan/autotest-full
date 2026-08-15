import { useState } from "react";
import { type MeasuredItem, type TestResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { GapCalcPanel } from "./TestPage";

/** 演示页（/test-preview）：不连仪器，用一份模拟的磁芯检 FAIL 数据渲染
 *  「测试结果 + 字号调节 + 气隙研磨计算」，供无设备时查看界面效果。 */

function mk(type: string, pins: string, vd: number, lo: number | null, hi: number | null, result: string, unit: string | null): MeasuredItem {
  return { type, pins, value: vd, lo: lo ?? 0, hi: hi ?? 0, result, unit, value_display: vd, lo_display: lo, hi_display: hi };
}

const MOCK_ITEMS: MeasuredItem[] = [
  mk("Turn", "2-3", 1.0, 1, 1, "Pass", null),
  mk("Turn", "6-5", 0.722865, 0.657, 0.803, "Pass", null),
  mk("Lx", "2-3", 62.95, 63.448, 69.0375, "Fail", "uH"),
  mk("Lx", "6-5", 38.9, 39.082, 42.525, "Fail", "uH"),
  mk("Q", "2-3", 81.8267, 1, null, "Pass", null),
  mk("Q", "6-5", 235.824, 1, null, "Pass", null),
  mk("Lk", "2-3", 8.96, 8.573, 9.3282, "Pass", "uH"),
  mk("Lk", "6-5", 5.6, 5.281, 5.74665, "Pass", "uH"),
  mk("Cx", "2-6", 2.2397, 1.87, 2.53, "Pass", "nF"),
  mk("Cx", "3-5", 2.24, 1.87, 2.53, "Pass", "nF"),
  mk("Dcr", "2-3", 18.146, null, 24.5, "Pass", "mOhm"),
  mk("Dcr", "6-5", 11.497, null, 16.5, "Pass", "mOhm"),
  mk("EqN", "-", 1.185775, 1.14, 1.23, "Pass", null),
];

const MOCK_RESULT: TestResult = {
  ok: true,
  timestamp: "2026-08-14 18:30:00",
  product_code: "ZZ-H2500011-磁芯检",
  serial_code: "DEMO-0001",
  overall: "FAIL",
  passed: 11,
  failed: 2,
  items: MOCK_ITEMS,
  csv_file: "demo.csv",
};

const TYPE_ORDER = ["Turn", "Lx", "Q", "Lk", "Cx", "Dcr", "EqN"];
const typeLabel = (t: string) => (t === "EqN" ? "等效n" : t);

export default function TestPagePreview() {
  const [showLimits, setShowLimits] = useState(true);
  const [fontScale, setFontScale] = useState<"md" | "lg" | "xl">("md");

  const types = TYPE_ORDER.filter((t) => MOCK_ITEMS.some((x) => x.type === t));
  const pinsList = Array.from(new Set(MOCK_ITEMS.map((x) => x.pins)));
  const matrix = new Map(MOCK_ITEMS.map((x) => [`${x.pins}::${x.type}`, x]));
  const unitOf: Record<string, string> = { Lx: "uH", Lk: "uH", Cx: "nF", Dcr: "mOhm" };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
        <b>演示页</b> · 模拟数据（Lx 两项故意设为 Fail），仅用于查看界面效果；正式测试请回「测试」页。
      </div>

      <Card className="panel">
        <CardHeader>
          <CardTitle className="flex items-center gap-3">
            测试结果
            <Badge variant="destructive">FAIL</Badge>
            <span className="text-xs text-muted-foreground font-normal">11/13 项通过 · {MOCK_RESULT.timestamp}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border p-3 text-sm bg-rose-50 border-rose-200">
            <div className={`font-bold ${fontScale === "xl" ? "text-4xl" : fontScale === "lg" ? "text-2xl" : "text-lg"} text-rose-700`}>总判定：FAIL</div>
            <div className="text-xs text-muted-foreground mt-1">规则：任一单元格 Fail，即总结果 Fail。</div>
          </div>
          <div className="flex items-center gap-2">
            <Switch checked={showLimits} onCheckedChange={setShowLimits} />
            <span className="text-sm text-muted-foreground">显示限值（Fail 项始终显示）</span>
            <div className="ml-auto flex items-center gap-1">
              <span className="text-xs text-muted-foreground mr-1">字号</span>
              {(["md", "lg", "xl"] as const).map((v) => (
                <Button key={v} size="sm" variant={fontScale === v ? "default" : "outline"} className="h-7 px-2.5 text-xs" onClick={() => setFontScale(v)}>
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
                  {types.map((t) => (
                    <TableHead key={t} className="text-center">
                      {typeLabel(t)}
                      {unitOf[t] ? ` (${unitOf[t]})` : ""}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {pinsList.map((pins) => (
                  <TableRow key={pins}>
                    <TableCell className="mono font-semibold">{pins}</TableCell>
                    {types.map((type) => {
                      const cell = matrix.get(`${pins}::${type}`);
                      if (!cell) return <TableCell key={`${pins}-${type}`} className="text-center text-muted-foreground">-</TableCell>;
                      const fail = cell.result !== "Pass";
                      return (
                        <TableCell key={`${pins}-${type}`} className={`text-center mono ${fail ? "bg-rose-50 text-rose-700 font-semibold" : "text-foreground"}`}>
                          <div>{cell.value_display}</div>
                          {(showLimits || fail) && (
                            <div className="text-[0.55em] font-normal leading-snug text-muted-foreground">
                              {cell.lo_display ?? "-"} ~ {cell.hi_display ?? "-"}
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
        </CardContent>
      </Card>

      <GapCalcPanel productCode="ZZ-H2500011-磁芯检" result={MOCK_RESULT} />
    </div>
  );
}
