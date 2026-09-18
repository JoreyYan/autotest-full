"""飞书 _build_fields 抽出共用函数后输出不变（规格 §2.3：飞书输出不得变化）。"""
import ast
import json
import math
import subprocess
import textwrap
import time
from datetime import datetime

import pytest

from backend import feishu_uploader as fu
from conftest import ROOT

V174_COMMIT = '740e067'   # v1.7.4 发版提交


# ── 1.7.4 的原样实现（逐字拷贝自 v1.7.4 backend/feishu_uploader.py）──────────────
def _legacy_item_label(item: dict) -> str:
    t = item.get('type', '')
    if t == 'EqN':
        return '等效n'
    base = f"{t}_{item.get('pins', '')}"
    unit = item.get('unit')
    return f"{base}({unit})" if unit else base


def _legacy_is_finite(v) -> bool:
    if v is None:
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(x) or math.isinf(x))


def _legacy_build_fields(record_dict: dict) -> dict:
    items = record_dict.get('items') or []
    ts_str = record_dict.get('timestamp', '')
    try:
        ts_ms = int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
    except Exception:
        ts_ms = int(time.time() * 1000)

    fields: dict = {
        '测试时间': ts_ms,
        '公司': record_dict.get('company', '') or '',
        '产线': record_dict.get('line', '') or '',
        '工段': record_dict.get('station', '') or '',
        '序列码': record_dict.get('serial_code', '') or '',
        '序号': record_dict.get('record_number', '') or '',
        '磁芯编号': record_dict.get('core_number', '') or '',
        '产品': record_dict.get('product_code', '') or '',
        '产品结果': record_dict.get('overall', '') or '',
        '扣偏校验ID': record_dict.get('calibration_id', '') or '',
    }

    for it in items:
        label = _legacy_item_label(it)
        v = it.get('value_display')
        if not _legacy_is_finite(v):
            v = it.get('value')
        if _legacy_is_finite(v):
            fields[label] = float(v)

    return fields


def _load_v174_build_fields():
    """从 git 里取 v1.7.4 的 _item_label / _is_finite / _build_fields 源码直接执行，作为第二份对照。"""
    try:
        src = subprocess.run(
            ['git', '-C', str(ROOT), 'show', f'{V174_COMMIT}:backend/feishu_uploader.py'],
            capture_output=True, timeout=30, check=True).stdout.decode('utf-8')
    except Exception as e:
        pytest.skip(f'取不到 v1.7.4 源码（git 不可用）: {e}')
    tree = ast.parse(src)
    ns = {'math': math, 'datetime': datetime, 'time': time}
    wanted = {'_item_label', '_is_finite'}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.get_source_segment(src, node), 'v174', 'exec'), ns)
        if isinstance(node, ast.ClassDef) and node.name == 'FeishuUploader':
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == '_build_fields':
                    seg = textwrap.dedent('    ' + ast.get_source_segment(src, fn))
                    exec(compile(seg, 'v174', 'exec'), ns)
    assert {'_item_label', '_is_finite', '_build_fields'} <= set(ns)
    return lambda rec: ns['_build_fields'](None, rec)


def _records(items):
    base = {
        'timestamp': '2026-09-17 10:11:12',
        'product_code': 'ZZ-H2500011',
        'serial_code': 'RqK8bW3xYtZ2mN7pLc4VdF9sHjA',
        'record_number': '260YN0062',
        'core_number': 'C-0001',
        'overall': 'FAIL',
        'passed': 5,
        'failed': 1,
        'items': items,
        'company': '汉润',
        'line': 'L1',
        'station': '总测',
        'deployment_id': '汉润-L1-总测',
        'calibration_id': '20260917-101010',
    }
    empty = dict(base, serial_code='', record_number=None, core_number='', calibration_id='',
                 company=None, overall='PASS', items=[])
    bad_ts = dict(base, timestamp='not-a-time')
    no_ts = {k: v for k, v in base.items() if k != 'timestamp'}
    none_items = dict(base, items=None)
    return [base, empty, bad_ts, no_ts, none_items]


def _uploader(tmp_path):
    return fu.FeishuUploader('app', 'secret', 'token', tmp_path)


def _assert_identical(new: dict, old: dict):
    assert list(new.items()) == list(old.items())
    assert (json.dumps(new, ensure_ascii=False).encode('utf-8')
            == json.dumps(old, ensure_ascii=False).encode('utf-8'))


def test_build_fields_identical_to_legacy_copy(tmp_path, monkeypatch, sample_items):
    monkeypatch.setattr(time, 'time', lambda: 1789000000.123)
    up = _uploader(tmp_path)
    for rec in _records(sample_items):
        _assert_identical(up._build_fields(rec), _legacy_build_fields(rec))


def test_build_fields_identical_to_v174_source(tmp_path, monkeypatch, sample_items):
    legacy = _load_v174_build_fields()
    monkeypatch.setattr(time, 'time', lambda: 1789000000.123)
    up = _uploader(tmp_path)
    for rec in _records(sample_items):
        _assert_identical(up._build_fields(rec), legacy(rec))


def test_representative_item_columns(tmp_path, sample_items):
    fields = _uploader(tmp_path)._build_fields(_records(sample_items)[0])
    items_part = {k: v for k, v in fields.items() if k in fu.item_values(sample_items)}
    assert items_part == {
        'Lx_1-2(uH)': 99.5,        # 重复测项后者覆盖；value_display=-inf 退回 value
        'Lk_1-2(uH)': 1.2,
        'Q_3-4': 45.6,             # NA 项、无单位
        'Turn_5-6': 12.0,          # 缺 unit 键
        'Dcr_7-8(mΩ)': 12.3,       # 值是字符串
        '等效n': 0.0,              # EqN 的 NaN 退回 value
    }
    assert 'Cx_1-5(pF)' not in fields and 'Zx_2-6(Ω)' not in fields
    # 列顺序：公共前缀 → 测试项（首次出现顺序）
    assert list(fields)[10:] == ['Lx_1-2(uH)', 'Lk_1-2(uH)', 'Q_3-4', 'Turn_5-6', 'Dcr_7-8(mΩ)', '等效n']


def test_record_time_ms_matches_legacy():
    ts = '2026-09-17 10:11:12'
    assert fu.record_time_ms(ts) == int(datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
    for bad in ('', 'x', None, 20260917, '2026-09-17T10:11:12'):
        assert fu.record_time_ms(bad) is None
