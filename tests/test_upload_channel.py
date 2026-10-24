"""按工位直推 ERP:规格里 upload_channel=erp 时,旧码/只有磁芯号的记录也直推、不经飞书;没开照旧推飞书。"""
import json

import pytest

from backend import main
from backend import record_number_cache as rnc
from tests.test_run_test_routing import env, _run, _pending, FEISHU_TOKEN  # noqa: F401  (env 是夹具)

OLD = '260YN0108'


def _set_channel(env, value):
    env.runner.product = {**env.runner.product, 'upload_channel': value}


def test_switch_off_old_code_goes_to_feishu(env):
    _run(serial_code=FEISHU_TOKEN, record_number=OLD)
    assert len(env.feishu.pushed) == 1 and env.feishu.pushed[0]['record_number'] == OLD
    assert _pending(env.tmp) == []


@pytest.mark.parametrize('value', ['erp', 'ERP', ' erp '])
def test_switch_on_old_code_goes_to_cloud_only(env, value):
    _set_channel(env, value)
    _run(serial_code=FEISHU_TOKEN, record_number=OLD, core_number='1767')
    assert env.feishu.pushed == [] and env.get_uploader_calls == []
    [r] = _pending(env.tmp)
    assert r['record_number'] == OLD and r['serial_code'] == FEISHU_TOKEN and r['core_number'] == '1767'
    assert r['company'] == '汉润' and r['deployment_id'] == '汉润-L1-总测'
    assert env.sent == []


def test_switch_on_core_only_record_goes_to_cloud(env):
    _set_channel(env, 'erp')
    _run(core_number='1767')
    assert env.feishu.pushed == []
    [r] = _pending(env.tmp)
    assert r['core_number'] == '1767' and r['record_number'] is None and r['serial_code'] is None


def test_switch_on_fills_record_number_from_local_cache_only(env, monkeypatch):
    _set_channel(env, 'erp')
    monkeypatch.setattr(rnc, '_fetch', lambda *a, **k: pytest.fail('直推时不该联网反查序号'))
    with rnc._lock:
        rnc._load()
        rnc._pos[FEISHU_TOKEN] = OLD
    try:
        _run(serial_code=FEISHU_TOKEN)
    finally:
        with rnc._lock:
            rnc._pos.pop(FEISHU_TOKEN, None)
    [r] = _pending(env.tmp)
    assert r['record_number'] == OLD


def test_switch_on_cache_miss_keeps_empty_record_number(env, monkeypatch):
    _set_channel(env, 'erp')
    monkeypatch.setattr(rnc, '_fetch', lambda *a, **k: pytest.fail('直推时不该联网反查序号'))
    _run(serial_code=FEISHU_TOKEN)
    [r] = _pending(env.tmp)
    assert r['record_number'] is None and r['serial_code'] == FEISHU_TOKEN


@pytest.mark.parametrize('value', ['', 'feishu', None, 'erpx'])
def test_other_values_keep_feishu(env, value):
    _set_channel(env, value)
    _run(serial_code=FEISHU_TOKEN, record_number=OLD)
    assert len(env.feishu.pushed) == 1
    assert _pending(env.tmp) == []


def test_new_code_still_cloud_with_switch_off(env):
    _run(record_number='26HK04426')
    assert env.feishu.pushed == []
    [r] = _pending(env.tmp)
    assert r['record_number'] == '26HK04426'


def test_log_line_names_the_record(env):
    _set_channel(env, 'erp')
    _run(serial_code=FEISHU_TOKEN, record_number=OLD)
    text = json.dumps(main.logs.get_since(0, 500), ensure_ascii=False)
    assert '记录 260YN0108 已写入直推队列' in text
