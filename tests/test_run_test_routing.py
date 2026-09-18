"""run_test 编号归一化 + 新码/旧码分流（规格 §2.1 / §2.2 / §2.4 接口 / §2.5）。"""
import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.test_runner import TestRecord as Record   # 别名：免得 pytest 把 Test* 当用例类收集
from backend import cloud_uploader as cu
from backend import logs
from backend import main
from backend import state

NEW = '26HK04426'
FEISHU_TOKEN = 'RqK8bW3xYtZ2mN7pLc4VdF9sHjA'

DEPLOYMENT = {'deployment_id': '汉润-L1-总测', 'company': '汉润', 'line': 'L1', 'station': '总测'}


class FakeRunner:
    _ready = True

    def __init__(self, items):
        self.product = {'product_code': 'ZZ-H2500011', 'test_items': []}
        self.items = items
        self.records = []

    def run(self):
        rec = Record(timestamp='2026-09-17 10:11:12', product_code='ZZ-H2500011',
                     items=self.items, passed=5, failed=1, overall='FAIL')
        self.records.append(rec)
        return rec


class FakeFeishu:
    def __init__(self):
        self.pushed = []

    def push_async(self, record_dict):
        self.pushed.append(record_dict)


@pytest.fixture
def env(tmp_path, monkeypatch, sample_items):
    cfg = {'products_dir': 'products', 'results_dir': 'results', **DEPLOYMENT}
    (tmp_path / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    runner = FakeRunner(sample_items)
    monkeypatch.setattr(state, 'runner', runner)
    monkeypatch.setattr(state, 'current_product', 'ZZ-H2500011')
    monkeypatch.setitem(state.calibration, 'id', '20260917-090000')
    monkeypatch.setitem(state.calibration, 'passed', True)

    feishu = FakeFeishu()
    get_uploader_calls = []

    def fake_get_uploader(work_dir=None):
        get_uploader_calls.append(work_dir)
        return feishu

    monkeypatch.setattr(main, 'get_uploader', fake_get_uploader)

    # 直推不能真的发：线程不启动；万一有人发，也只会打到替身
    sent = []
    monkeypatch.setattr(cu.requests, 'post', lambda *a, **k: sent.append((a, k)) or pytest.fail('不应发送'))

    class Env:
        pass

    e = Env()
    e.tmp = tmp_path
    e.runner = runner
    e.feishu = feishu
    e.get_uploader_calls = get_uploader_calls
    e.sent = sent
    return e


def _run(serial_code='', record_number='', core_number=''):
    return main.run_test(main.RunTestRequest(serial_code=serial_code, record_number=record_number,
                                             core_number=core_number))


def _pending(tmp: Path):
    p = tmp / 'cloud_pending.jsonl'
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]


def _csv_last_row(result):
    with open(result.csv_file, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))
    header = rows[0]
    return dict(zip(header, rows[-1]))


# ── 新码：只进直推队列，不调飞书 ─────────────────────────────
@pytest.mark.parametrize('req, core', [
    ({'record_number': NEW}, ''),
    ({'record_number': '26hk04426'}, ''),
    ({'record_number': ' https://www.soaipower.com/t/26hk04426/ '}, ''),
    ({'record_number': NEW, 'serial_code': FEISHU_TOKEN}, ''),          # 序号框新码优先，序列码原样保留
    ({'serial_code': 'https://www.soaipower.com/t/26HK04426'}, ''),      # 前端旧流程把整段文字当序列码
    ({'serial_code': 'http://soaipower.com/t/26hk04426/'}, 'C-0001'),
    ({'serial_code': '26HK04426', 'record_number': '260YN0062'}, ''),  # 序列码是新码：序号被新码替换
])
def test_new_code_goes_to_cloud_queue_only(env, req, core):
    result = _run(core_number=core, **req)
    rec = env.runner.records[-1]

    assert rec.record_number == NEW
    serial_in = req.get('serial_code', '')
    if main.parse_finished_code(req.get('record_number', '')):
        assert rec.serial_code == serial_in
    else:
        assert rec.serial_code == ''
    assert result.serial_code == rec.serial_code

    # 飞书一律不碰
    assert env.feishu.pushed == []
    assert env.get_uploader_calls == []

    # 返回前已落盘
    [r] = _pending(env.tmp)
    assert r['record_number'] == NEW
    assert r['serial_code'] == (rec.serial_code or None)
    assert r['core_number'] == (core or None)
    assert r['product_code'] == 'ZZ-H2500011'
    assert r['overall'] == 'FAIL'
    assert r['company'] == '汉润' and r['line'] == 'L1' and r['station'] == '总测'
    assert r['deployment_id'] == '汉润-L1-总测'
    assert r['calibration_id'] == '20260917-090000'
    assert r['items']['Lk_1-2(uH)'] == 1.2
    assert env.sent == []

    # CSV 写的是归一化后的值
    row = _csv_last_row(result)
    assert row['序号'] == NEW
    assert row['序列码'] == rec.serial_code
    assert row['磁芯编号'] == core


def test_new_code_pushed_even_without_feishu_credentials(env, monkeypatch):
    monkeypatch.setattr(main, 'get_uploader', lambda work_dir=None: None)
    _run(record_number=NEW)
    assert len(_pending(env.tmp)) == 1


def _capture_logs(monkeypatch):
    captured = []
    real = logs.log
    monkeypatch.setattr(logs, 'log', lambda m, level='INFO', sticky=False:
                        captured.append((level, m, sticky)) or real(m, level, sticky=sticky))
    return captured


@pytest.mark.parametrize('exc, hint', [
    (OSError('disk full'), '写入直推队列失败'),
    (cu.NotPersistedError('disk full'), '暂存内存'),
])
def test_enqueue_failure_does_not_break_test(env, monkeypatch, exc, hint):
    """直推队列写不进时测试结果照常返回（前端不显示 run_test 的报错，抛错会让屏幕停在上一台的结果），
    但必须留一条不会被清掉的 ERROR 日志，且不改走飞书。"""
    captured = _capture_logs(monkeypatch)

    def boom(record_dict):
        raise exc

    monkeypatch.setattr(cu, 'enqueue', boom)
    result = _run(record_number=NEW)
    assert result.ok and env.feishu.pushed == []
    assert any(level == 'ERROR' and sticky and hint in m and NEW in m for level, m, sticky in captured)


def test_enqueue_uses_fallback_file_when_pending_locked(env, monkeypatch):
    """端到端：待传文件被占用时，run_test 返回前记录已落在备用文件里。"""
    real = cu.CloudUploader._append_lines

    def guarded(path, lines):
        if Path(path).name == 'cloud_pending.jsonl':
            raise PermissionError(13, 'locked by another process')
        return real(path, lines)

    monkeypatch.setattr(cu.CloudUploader, '_append_lines', staticmethod(guarded))
    result = _run(record_number=NEW)
    assert result.ok and env.feishu.pushed == []
    fb = env.tmp / 'cloud_pending_fallback.jsonl'
    [rec] = [json.loads(ln) for ln in fb.read_text(encoding='utf-8').splitlines() if ln.strip()]
    assert rec['record_number'] == NEW
    assert cu.status()['pending'] == 1


# ── 旧码：与 1.7.4 完全一致地推飞书，直推队列不动 ────────────────
@pytest.mark.parametrize('req', [
    {'serial_code': FEISHU_TOKEN},
    {'serial_code': f'https://smartonep.feishu.cn/record/{FEISHU_TOKEN}'},
    {'serial_code': FEISHU_TOKEN, 'record_number': '2602N0118'},
    {'record_number': '260YN0062'},
    {'record_number': '2602N0186'},
    {'core_number': 'C-0001'},
    {},
    {'record_number': '26HK04427'},                          # 校验位错不算新码，原样走飞书
    {'serial_code': 'https://www.soaipower.com/t/26HK04427'},
    {'record_number': 'https://smartonep.feishu.cn/record/26HK04426'},
])
def test_old_code_goes_to_feishu_exactly_as_before(env, req):
    result = _run(**req)
    rec = env.runner.records[-1]
    serial = req.get('serial_code', '')
    number = req.get('record_number', '')
    core = req.get('core_number', '')

    assert (rec.serial_code, rec.record_number, rec.core_number) == (serial, number, core)
    assert result.serial_code == serial

    assert len(env.get_uploader_calls) == 1 and env.get_uploader_calls[0] == Path.cwd()
    [pushed] = env.feishu.pushed
    expected = {
        'timestamp': '2026-09-17 10:11:12',
        'product_code': 'ZZ-H2500011',
        'serial_code': serial,
        'record_number': number,
        'core_number': core,
        'overall': 'FAIL',
        'passed': 5,
        'failed': 1,
        'items': rec.items,
        'company': '汉润',
        'line': 'L1',
        'station': '总测',
        'deployment_id': '汉润-L1-总测',
        'calibration_id': '20260917-090000',
    }
    assert list(pushed) == list(expected)      # 键和顺序都不变
    assert pushed == expected
    assert pushed['items'] is rec.items

    assert not (env.tmp / 'cloud_pending.jsonl').exists()

    row = _csv_last_row(result)
    assert (row['序列码'], row['序号'], row['磁芯编号']) == (serial, number, core)


def test_old_code_without_feishu_credentials_silently_skips(env, monkeypatch):
    monkeypatch.setattr(main, 'get_uploader', lambda work_dir=None: None)
    result = _run(record_number='260YN0062')
    assert result.ok
    assert not (env.tmp / 'cloud_pending.jsonl').exists()


# ── 接口 / 启动 / 版本 ─────────────────────────────────────
def test_cloud_upload_endpoints(tmp_path):
    client = TestClient(main.app)          # 不进 with：不触发 startup
    s = client.get('/api/cloud-upload/status')
    assert s.status_code == 200
    assert s.json() == {'url': cu.DEFAULT_INGEST_URL, 'pending': 0, 'rejected': 0,
                        'last_ok_at': None, 'last_error': None, 'running': False}
    cu.get_cloud_uploader().enqueue({'timestamp': '2026-09-17 10:11:12', 'product_code': 'P',
                                     'record_number': NEW, 'overall': 'PASS', 'items': []})
    cu.get_cloud_uploader()._wake.clear()
    r = client.post('/api/cloud-upload/retry')
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'triggered': True, 'pending': 1}
    assert cu.get_cloud_uploader()._wake.is_set()
    assert client.get('/api/cloud-upload/status').json()['pending'] == 1


def test_startup_starts_cloud_uploader_without_feishu(tmp_path, monkeypatch):
    lines = []
    for i in range(2):
        lines.append(json.dumps({'upload_id': f'{i:032x}', 'product_code': 'P', 'items': {}}))
    (tmp_path / 'cloud_pending.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    monkeypatch.setattr(cu, 'START_DELAY_SEC', 3600)     # 线程拉起但不真的发
    captured = []
    real = logs.log
    monkeypatch.setattr(logs, 'log', lambda m, level='INFO', sticky=False:
                        captured.append((level, m, sticky)) or real(m, level, sticky=sticky))
    from backend.feishu_uploader import get_uploader
    assert get_uploader(Path.cwd()) is None               # 临时目录里没有飞书凭证
    main._startup_cloud_uploader()
    up = cu.get_cloud_uploader()
    assert up.status()['running'] is True
    assert up.app_version == '1.7.5'
    assert any('2 条待传' in m and sticky for _, m, sticky in captured)


def test_version_and_serial_code_removed():
    assert main.APP_VERSION == '1.7.5'
    client = TestClient(main.app)
    assert client.get('/api/version').json()['version'] == '1.7.5'
    paths = {getattr(r, 'path', '') for r in main.app.routes}
    assert '/api/cloud-upload/status' in paths and '/api/cloud-upload/retry' in paths
    assert not any(p.startswith('/api/serial-code') for p in paths)
    assert not hasattr(main, 'serial_code')
    root = Path(main.__file__).resolve().parent
    assert not (root / 'serial_code.py').exists()
    assert not hasattr(state, 'get_code_state') and not hasattr(state, 'save_code_state')
    from backend import feishu_uploader as fu
    assert not hasattr(fu.FeishuUploader, 'CODE_BLOCK_TABLE')
    assert not hasattr(fu.FeishuUploader, 'create_code_block')


def test_empty_core_number_not_auto_assigned(env):
    _run(record_number='260YN0062')
    assert env.runner.records[-1].core_number == ''
    assert env.feishu.pushed[0]['core_number'] == ''
