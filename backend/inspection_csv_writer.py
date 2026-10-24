from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path

from agent.inspection_runner import InspectionSessionRecord


def _fmt_num(v) -> str:
    if v is None:
        return ""
    try:
        x = float(v)
    except Exception:
        return ""
    if math.isnan(x) or math.isinf(x):
        return ""
    return f"{x:.6f}"


def _label(item: dict, which: str) -> str:
    label = item.get(f"{which}_label") or which.upper()
    unit = item.get(f"{which}_unit") or ""
    base = f"{item.get('pins', '')}_{item.get('name', '')}_{label}"
    return f"{base}({unit})" if unit else base


def _same_layout(filepath: Path, header1: list[str], header2: list[str], header3: list[str]) -> bool:
    if not filepath.exists():
        return False
    with open(filepath, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        return False
    return rows[0] == header1 and rows[1] == header2 and rows[2] == header3


def save(record: InspectionSessionRecord, results_dir: Path):
    today = datetime.now().strftime("%Y%m%d")
    filepath = results_dir / f"{record.product_code}_{today}_inspection_v1.csv"

    labels = []
    highs = []
    lows = []
    for item in record.items:
        labels.append(_label(item, "primary"))
        highs.append(_fmt_num(item.get("primary_upper")))
        lows.append(_fmt_num(item.get("primary_lower")))
        if any(v is not None for v in (item.get("secondary_lower"), item.get("secondary_upper"))):
            labels.append(_label(item, "secondary"))
            highs.append(_fmt_num(item.get("secondary_upper")))
            lows.append(_fmt_num(item.get("secondary_lower")))

    header1 = ["类型", "产品", *labels, "产品结果"]
    header2 = ["上限", "", *highs, ""]
    header3 = ["下限", "", *lows, ""]

    file_exists = filepath.exists()
    if file_exists and not _same_layout(filepath, header1, header2, header3):
        filepath = results_dir / f"{record.product_code}_{today}_inspection_v1_2.csv"
        file_exists = filepath.exists()

    with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header1)
            writer.writerow(header2)
            writer.writerow(header3)

        values = []
        for item in record.items:
            values.append(_fmt_num(item.get("primary_value_display")))
            if any(v is not None for v in (item.get("secondary_lower"), item.get("secondary_upper"))):
                values.append(_fmt_num(item.get("secondary_value_display")))
        writer.writerow([record.timestamp, record.product_code, *values, record.overall])

    return str(filepath)
