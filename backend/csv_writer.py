"""
csv_writer.py - Save test records to daily CSV files (v3 layout).
"""

from __future__ import annotations

import csv
import itertools
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
    t = item.get('type', '')
    if t == 'EqN':
        return '等效n'
    base = f"{t}_{item.get('pins', '')}"
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
    # 只读前 3 行比对表头（旧实现全量读整个文件，测试数多了每次测试都全量解析越来越慢）
    with open(filepath, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(itertools.islice(csv.reader(f), 3))
    if len(rows) < 3:
        return False
    return rows[0] == header1 and rows[1] == header2 and rows[2] == header3


def save(record: TestRecord, results_dir: Path):
    """Append one test record to CSV and return path."""
    today = datetime.now().strftime("%Y%m%d")
    base_name = f"{record.product_code}_{today}_v5"

    labels = [_label(item) for item in record.items]
    highs = [_fmt_num(_hi(item)) for item in record.items]
    lows = [_fmt_num(_lo(item)) for item in record.items]

    # 3-row fixed header.
    header_row_1 = ["类型", "序列码", "序号", "磁芯编号", "产品", *labels, "产品结果"]
    header_row_2 = ["上限", "", "", "", "", *highs, ""]
    header_row_3 = ["下限", "", "", "", "", *lows, ""]

    # Find a file whose header matches, or create a new one with incremented suffix.
    filepath = results_dir / f"{base_name}.csv"
    suffix = 1
    while filepath.exists() and not _same_layout(filepath, header_row_1, header_row_2, header_row_3):
        suffix += 1
        filepath = results_dir / f"{base_name}_{suffix}.csv"

    file_exists = filepath.exists()

    with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(header_row_1)
            w.writerow(header_row_2)
            w.writerow(header_row_3)

        values = [_fmt_num(_value(item)) for item in record.items]
        w.writerow([record.timestamp, record.serial_code, record.record_number, record.core_number, record.product_code, *values, record.overall])

    return str(filepath)
