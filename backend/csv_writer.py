"""
csv_writer.py - Save test records to daily CSV files (v3 layout).
"""

from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path

from agent.test_runner import TestRecord


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


def _unit(item: dict) -> str:
    u = item.get("unit")
    return str(u) if u else ""


def _label(item: dict) -> str:
    base = f"{item.get('type', '')}_{item.get('pins', '')}"
    u = _unit(item)
    return f"{base}({u})" if u else base


def _value(item: dict):
    return item.get("value_display", item.get("value"))


def _lo(item: dict):
    return item.get("lo_display", item.get("lo"))


def _hi(item: dict):
    return item.get("hi_display", item.get("hi"))


def _same_layout(filepath: Path, header1: list[str], header2: list[str], header3: list[str]) -> bool:
    if not filepath.exists():
        return False
    with open(filepath, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        return False
    return rows[0] == header1 and rows[1] == header2 and rows[2] == header3


def save(record: TestRecord, results_dir: Path):
    """Append one test record to CSV and return path."""
    today = datetime.now().strftime("%Y%m%d")
    filepath = results_dir / f"{record.product_code}_{today}_v3.csv"

    labels = [_label(item) for item in record.items]
    highs = [_fmt_num(_hi(item)) for item in record.items]
    lows = [_fmt_num(_lo(item)) for item in record.items]

    # 3-row fixed header per request.
    header_row_1 = ["类型", "产品", *labels, "产品结果"]
    header_row_2 = ["上限", "", *highs, ""]
    header_row_3 = ["下限", "", *lows, ""]

    file_exists = filepath.exists()
    if file_exists and not _same_layout(filepath, header_row_1, header_row_2, header_row_3):
        # same day but item layout changed: use a rotated file name
        filepath = results_dir / f"{record.product_code}_{today}_v3_2.csv"
        file_exists = filepath.exists()

    with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(header_row_1)
            w.writerow(header_row_2)
            w.writerow(header_row_3)

        values = [_fmt_num(_value(item)) for item in record.items]
        w.writerow([record.timestamp, record.product_code, *values, record.overall])

    return str(filepath)
