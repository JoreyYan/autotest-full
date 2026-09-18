"""新码直推本地队列 backend/cloud_uploader.py（规格 §2.3 / §2.4）。"""
import json
import math
import os
import re
import time
from datetime import datetime

import pytest
import requests

from backend import cloud_uploader as cu
from backend import feishu_uploader as fu
from backend import logs


# ── 工具 ──────────────────────────────────────────────────
def _record(items, **over):
    rec = {
        'timestamp': '2026-09-17 10:11:12',
        'product_code': 'ZZ-H2500011',
        'serial_code': '',
        'record_number': '26HK04426',
        'core_number': '',
        'overall': 'PASS',
        'passed': 6,
        'failed': 0,
        'items': items,
        'company': '汉润',
        'line': 'L1',
        'station': '总测',
        'deployment_id': '汉润-L1-总测',
        'calibration_id': '',
    }
    rec.update(over)
    return rec


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._json_error:
            raise ValueError('Expecting value: line 1 column 1 (char 0)')
        return self._payload


class FakeServer:
    """替身接收端：记录每次请求，按 handler 决定响应。"""

    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or self.accept_all

    @staticmethod
    def accept_all(body):
        return FakeResponse(200, {'ok': True, 'accepted': [r['upload_id'] for r in body['records']],
                                  'rejected': []})

    def __call__(self, url, data=None, headers=None, timeout=None, **kwargs):
        assert isinstance(data, bytes), '载荷应由我们自己序列化成 bytes（保证 allow_nan=False）'
        body = json.loads(data.decode('utf-8'),
                          parse_constant=lambda c: pytest.fail(f'载荷里出现 {c}'))
        self.calls.append({'url': url, 'body': body, 'raw': data, 'headers': headers,
                           'timeout': timeout, 'kwargs': kwargs})
        return self.handler(body)

    def sent_ids(self):
        return [r['upload_id'] for c in self.calls for r in c['body']['records']]


@pytest.fixture
def server(monkeypatch):
    s = FakeServer()
    monkeypatch.setattr(requests, 'post', s)
    return s


@pytest.fixture
def up(tmp_path):
    return cu.CloudUploader(tmp_path, app_version='1.7.5')


@pytest.fixture
def captured_logs(monkeypatch):
    out = []
    real = logs.log

    def spy(message, level='INFO', sticky=False):
        out.append((level, message))
        return real(message, level, sticky=sticky)

    monkeypatch.setattr(logs, 'log', spy)
    return out


def _pending_lines(up):
    if not up.pending_file.exists():
        return []
    return [ln for ln in up.pending_file.read_bytes().split(b'\n') if ln.strip()]


def _rejected_entries(up):
    if not up.rejected_file.exists():
        return []
    return [json.loads(ln) for ln in up.rejected_file.read_text(encoding='utf-8').splitlines() if ln.strip()]


# ── 载荷 ──────────────────────────────────────────────────
def test_record_payload_fields(up, sample_items):
    rec = _record(sample_items, serial_code='', core_number='', calibration_id='20260917-101010',
                  overall='FAIL')
    uid = up.enqueue(rec)
    assert re.fullmatch(r'[0-9a-f]{32}', uid)
    [line] = _pending_lines(up)
    r = json.loads(line)
    assert set(r) == {'upload_id', 'product_code', 'test_time_ms', 'company', 'line', 'station',
                      'deployment_id', 'serial_code', 'record_number', 'core_number', 'overall',
                      'items', 'calibration_id'}
    assert r['upload_id'] == uid
    assert r['product_code'] == 'ZZ-H2500011'
    assert r['company'] == '汉润' and r['line'] == 'L1' and r['station'] == '总测'
    assert r['deployment_id'] == '汉润-L1-总测'
    assert r['serial_code'] is None and r['core_number'] is None      # 空串转 null
    assert r['record_number'] == '26HK04426'
    assert r['overall'] == 'FAIL'
    assert r['calibration_id'] == '20260917-101010'
    assert '"items"' in line.decode('utf-8')


def test_items_and_time_equal_feishu(up, tmp_path, sample_items):
    rec = _record(sample_items, calibration_id='')
    up.enqueue(rec)
    r = json.loads(_pending_lines(up)[0])
    feishu = fu.FeishuUploader('a', 'b', 'c', tmp_path)._build_fields(rec)
    assert r['test_time_ms'] == feishu['测试时间']
    assert r['test_time_ms'] == int(datetime.strptime('2026-09-17 10:11:12', '%Y-%m-%d %H:%M:%S')
                                    .timestamp() * 1000)
    assert isinstance(r['test_time_ms'], int)
    feishu_items = {k: v for k, v in feishu.items() if k in r['items']}
    assert r['items'] == feishu_items
    assert list(r['items']) == list(feishu)[10:]          # 飞书测试项列 = 直推 items，一个不多一个不少
    assert r['items']['Q_3-4'] == 45.6                     # NA 项照样包含
    assert r['items']['等效n'] == 0.0
    assert r['calibration_id'] is None                     # 与飞书「扣偏校验ID」同源，空时 null


def test_bad_timestamp_uses_now_and_warns(up, monkeypatch, captured_logs, sample_items):
    monkeypatch.setattr(time, 'time', lambda: 1789000000.5)
    up.enqueue(_record(sample_items, timestamp='bad'))
    r = json.loads(_pending_lines(up)[0])
    assert r['test_time_ms'] == 1789000000500
    assert any(level == 'WARN' and '测试时间' in msg for level, msg in captured_logs)


def test_nan_never_serialized(up, server, sample_items):
    items = sample_items + [
        {'type': 'Lx', 'pins': '9-9', 'unit': 'uH', 'value': math.nan, 'value_display': math.nan},
        {'type': 'Lk', 'pins': '9-9', 'unit': 'uH', 'value': math.inf, 'value_display': -math.inf},
    ]
    up.enqueue(_record(items))
    raw = up.pending_file.read_bytes()
    for token in (b'NaN', b'Infinity'):
        assert token not in raw
    json.loads(raw.decode('utf-8').splitlines()[0], parse_constant=lambda c: pytest.fail(c))
    # 队列行被手工/意外写进 NaN：当损坏行隔离，绝不发出去
    good_uid = json.loads(raw)['upload_id']
    with open(up.pending_file, 'ab') as f:
        f.write(b'{"upload_id": "' + b'a' * 32 + b'", "items": {"x": NaN}}\n')
    st = up.run_once()
    assert st['quarantined'] == 1
    assert server.sent_ids() == [good_uid]
    for c in server.calls:
        assert b'NaN' not in c['raw'] and b'Infinity' not in c['raw']


def test_enqueue_is_on_disk_and_fsynced_before_return(up, monkeypatch, sample_items):
    events = []
    real_fsync = os.fsync

    def spy_fsync(fd):
        real_fsync(fd)
        # fsync 时这一行已经 flush 到文件里
        events.append(('fsync', up.pending_file.read_bytes()))

    monkeypatch.setattr(os, 'fsync', spy_fsync)
    uid = up.enqueue(_record(sample_items))
    events.append(('returned', None))
    assert [e[0] for e in events] == ['fsync', 'returned']
    assert uid.encode() in events[0][1]
    assert events[0][1].endswith(b'\n')
    assert up._wake.is_set()                                    # 入队后唤醒发送线程
    uid2 = up.enqueue(_record(sample_items))
    lines = _pending_lines(up)
    assert [json.loads(ln)['upload_id'] for ln in lines] == [uid, uid2]


# ── 发送结果处理 ──────────────────────────────────────────
def test_accepted_removed(up, server, sample_items):
    ids = [up.enqueue(_record(sample_items)) for _ in range(3)]
    st = up.run_once()
    assert st == {'sent': 3, 'accepted': 3, 'rejected': 0, 'quarantined': 0, 'kept': 0, 'error': None}
    assert _pending_lines(up) == []
    assert not up.rejected_file.exists()
    [call] = server.calls
    assert call['url'] == cu.DEFAULT_INGEST_URL == 'https://www.soaipower.com/api/erp/production/ingest'
    assert call['timeout'] == (5, 30)
    assert call['headers']['Content-Type'].startswith('application/json')
    assert call['body']['source'] == 'autotest'
    assert call['body']['app_version'] == '1.7.5'
    assert [r['upload_id'] for r in call['body']['records']] == ids
    s = up.status()
    assert s['pending'] == 0 and s['rejected'] == 0 and s['last_error'] is None
    assert s['last_ok_at'] and s['running'] is False


def test_config_json_overrides_url(up, server, tmp_path, sample_items):
    (tmp_path / 'config.json').write_text(
        json.dumps({'cloud_ingest_url': 'http://127.0.0.1:9/ingest'}), encoding='utf-8')
    up.enqueue(_record(sample_items))
    up.run_once()
    assert server.calls[0]['url'] == 'http://127.0.0.1:9/ingest'
    assert up.status()['url'] == 'http://127.0.0.1:9/ingest'


def test_batches_of_50(up, server, sample_items):
    ids = [up.enqueue(_record(sample_items)) for _ in range(120)]
    st = up.run_once()
    assert [len(c['body']['records']) for c in server.calls] == [50, 50, 20]
    assert server.sent_ids() == ids
    assert st['accepted'] == 120 and _pending_lines(up) == []


def test_rejected_moved_to_rejected_file(up, server, sample_items):
    a = up.enqueue(_record(sample_items))
    b = up.enqueue(_record(sample_items, product_code=''))
    server.handler = lambda body: FakeResponse(200, {
        'ok': True, 'accepted': [a], 'rejected': [{'upload_id': b, 'error': 'product_code 为空'}]})
    st = up.run_once()
    assert st['accepted'] == 1 and st['rejected'] == 1 and st['kept'] == 0
    assert _pending_lines(up) == []
    [entry] = _rejected_entries(up)
    assert entry['error'] == 'product_code 为空'
    assert entry['record']['upload_id'] == b
    assert entry['record']['product_code'] == ''
    assert entry['rejected_at']
    assert up.status()['rejected'] == 1
    # 退回的不再重试
    server.calls.clear()
    up.run_once()
    assert server.calls == []


def _fail_non_json(body):
    return FakeResponse(200, None, text='<html>502 Bad Gateway</html>', json_error=True)


def _fail_500(body):
    return FakeResponse(500, {'ok': False, 'error': 'db down'})


def _fail_404(body):
    return FakeResponse(404, None, text='Not Found', json_error=True)


def _fail_ok_false(body):
    return FakeResponse(200, {'ok': False, 'error': 'x'})


def _fail_bad_shape(body):
    return FakeResponse(200, {'ok': True, 'accepted': 'all'})


def _fail_timeout(body):
    raise requests.exceptions.Timeout('read timed out')


def _fail_conn(body):
    raise requests.exceptions.ConnectionError('connection refused')


@pytest.mark.parametrize('handler', [_fail_non_json, _fail_500, _fail_404, _fail_ok_false,
                                     _fail_bad_shape, _fail_timeout, _fail_conn])
def test_failures_keep_everything(up, server, handler, sample_items):
    for _ in range(60):
        up.enqueue(_record(sample_items))
    before = up.pending_file.read_bytes()
    server.handler = handler
    st = up.run_once()
    assert st['kept'] == 60 and st['accepted'] == 0 and st['error']
    assert len(server.calls) == 1                  # 第一批失败后本轮不再硬发第二批
    assert up.pending_file.read_bytes() == before
    assert not up.rejected_file.exists()
    s = up.status()
    assert s['pending'] == 60 and s['last_error']


def test_unreal_network_is_blocked_and_kept(up, sample_items):
    """没有替身时 requests 被 conftest 拦截：记录保留，不会真的连 soaipower.com。"""
    import conftest
    up.enqueue(_record(sample_items))
    before = up.pending_file.read_bytes()
    st = up.run_once()
    assert st['kept'] == 1 and st['error']
    assert up.pending_file.read_bytes() == before
    assert conftest.BLOCKED_ATTEMPTS and 'soaipower.com' in conftest.BLOCKED_ATTEMPTS[0]
    conftest.BLOCKED_ATTEMPTS.clear()   # 这是预期内的拦截


def test_unknown_ids_kept(up, server, sample_items):
    a = up.enqueue(_record(sample_items))
    b = up.enqueue(_record(sample_items))
    foreign = 'f' * 32
    server.handler = lambda body: FakeResponse(200, {
        'ok': True, 'accepted': [a, foreign, 123],
        'rejected': [{'upload_id': foreign, 'error': 'x'}, 'junk', {'error': 'no id'}]})
    st = up.run_once()
    assert st['accepted'] == 1 and st['rejected'] == 0 and st['kept'] == 1
    assert [json.loads(ln)['upload_id'] for ln in _pending_lines(up)] == [b]
    assert not up.rejected_file.exists()


def test_accepted_wins_over_rejected_for_same_id(up, server, sample_items):
    a = up.enqueue(_record(sample_items))
    server.handler = lambda body: FakeResponse(200, {
        'ok': True, 'accepted': [a], 'rejected': [{'upload_id': a, 'error': 'dup'}]})
    up.run_once()
    assert _pending_lines(up) == [] and not up.rejected_file.exists()


def test_concurrent_enqueue_during_send_preserved(up, server, sample_items):
    a = up.enqueue(_record(sample_items))
    late = []

    def handler(body):
        # 发送期间（不持锁）又测完一台
        late.append(up.enqueue(_record(sample_items, record_number='27LT12346')))
        return FakeServer.accept_all(body)

    server.handler = handler
    up.run_once()
    assert server.sent_ids() == [a]
    lines = _pending_lines(up)
    assert [json.loads(ln)['upload_id'] for ln in lines] == late
    # 下一轮把后来的也发掉
    server.handler = FakeServer.accept_all
    up.run_once()
    assert server.sent_ids() == [a] + late and _pending_lines(up) == []


def test_corrupt_lines_quarantined(up, server, sample_items):
    a = up.enqueue(_record(sample_items))
    garbage = [
        b'this is not json',
        b'{"upload_id": "' + b'1' * 32 + b'", "items": {',       # 写一半
        b'{"product_code": "no id"}',
        b'{"upload_id": "NOT-HEX"}',
        b'[1, 2, 3]',
        b'\xff\xfe\xfa bad utf8',
    ]
    with open(up.pending_file, 'ab') as f:
        for g in garbage:
            f.write(g + b'\n')
    b = up.enqueue(_record(sample_items))
    st = up.run_once()
    assert st['quarantined'] == len(garbage)
    assert server.sent_ids() == [a, b]
    assert _pending_lines(up) == []
    entries = _rejected_entries(up)
    assert len(entries) == len(garbage)
    assert all(e['error'] == '本地队列行损坏' and 'raw' in e for e in entries)
    assert entries[0]['raw'] == 'this is not json'


def test_corrupt_line_quarantined_even_when_offline(up, server, sample_items):
    a = up.enqueue(_record(sample_items))
    with open(up.pending_file, 'ab') as f:
        f.write(b'garbage\n')
    server.handler = _fail_conn
    st = up.run_once()
    assert st['quarantined'] == 1 and st['kept'] == 1
    assert [json.loads(ln)['upload_id'] for ln in _pending_lines(up)] == [a]
    assert len(_rejected_entries(up)) == 1


def test_truncated_tail_does_not_glue_next_line(up, server, sample_items):
    up.pending_file.write_bytes(b'{"upload_id": "abc", "trunc')      # 断电写一半，没有换行
    a = up.enqueue(_record(sample_items))
    lines = _pending_lines(up)
    assert len(lines) == 2 and json.loads(lines[1])['upload_id'] == a
    st = up.run_once()
    assert st['quarantined'] == 1 and st['accepted'] == 1
    assert _pending_lines(up) == []


def test_upload_id_stable_across_retries_and_restart(up, server, tmp_path, sample_items):
    uid = up.enqueue(_record(sample_items))
    server.handler = _fail_timeout
    up.run_once()
    up.run_once()
    # 模拟重启：新实例读同一个文件
    up2 = cu.CloudUploader(tmp_path, app_version='1.7.5')
    up2.run_once()
    server.handler = FakeServer.accept_all
    up2.run_once()
    assert server.sent_ids() == [uid] * 4
    assert _pending_lines(up2) == []


def test_duplicate_lines_sent_once(up, server, sample_items):
    up.enqueue(_record(sample_items))
    line = up.pending_file.read_bytes()
    with open(up.pending_file, 'ab') as f:
        f.write(line)
    up.run_once()
    assert len(server.sent_ids()) == 1 and _pending_lines(up) == []


def test_status_shape(up, sample_items):
    s = up.status()
    assert set(s) == {'url', 'pending', 'rejected', 'last_ok_at', 'last_error', 'running'}
    assert s == {'url': cu.DEFAULT_INGEST_URL, 'pending': 0, 'rejected': 0, 'last_ok_at': None,
                 'last_error': None, 'running': False}
    up.enqueue(_record(sample_items))
    assert up.status()['pending'] == 1


# ── 后台线程 ──────────────────────────────────────────────
def _wait_until(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_worker_thread_sends_and_retries_on_trigger(up, server, monkeypatch, sample_items):
    monkeypatch.setattr(cu, 'START_DELAY_SEC', 0)
    monkeypatch.setattr(cu, 'FAIL_WAIT_SEC', 3600)       # 失败后只能靠唤醒提前重试
    server.handler = _fail_conn
    a = up.enqueue(_record(sample_items))
    up.start()
    try:
        assert up.status()['running'] is True
        assert _wait_until(lambda: len(server.calls) >= 1)
        assert _wait_until(lambda: up.last_error is not None)
        assert up.pending_count() == 1
        server.handler = FakeServer.accept_all
        up.trigger()                                       # 手动重试
        assert _wait_until(lambda: up.pending_count() == 0)
        b = up.enqueue(_record(sample_items))              # 新入队自动唤醒
        assert _wait_until(lambda: up.pending_count() == 0)
        assert server.sent_ids()[-2:] == [a, b]
    finally:
        up.stop()
        up._thread.join(timeout=5)
    assert not up._thread.is_alive()


def test_module_singleton_uses_cwd(tmp_path, server, sample_items):
    uid = cu.enqueue(_record(sample_items))
    assert (tmp_path / 'cloud_pending.jsonl').exists()
    assert cu.status()['pending'] == 1
    assert cu.get_cloud_uploader() is cu.get_cloud_uploader()
    cu.get_cloud_uploader().run_once()
    assert server.sent_ids() == [uid]


# ── 评审补测：异常不能让发送线程退出 / 不可重新序列化的行 / 退回不重复 / 写盘失败兜底 ──
def test_worker_survives_errors_outside_run_once(up, server, monkeypatch, sample_items):
    """一轮发送成功后查待传条数时读文件出错（Windows 上文件被别的进程短暂占用），线程不能就此退出。"""
    monkeypatch.setattr(cu, 'START_DELAY_SEC', 0)
    monkeypatch.setattr(cu, 'FAIL_WAIT_SEC', 3600)       # 出错后只能靠唤醒提前重试
    real_count = up.pending_count
    boom = {'left': 1}

    def flaky_count():
        if boom['left'] > 0:
            boom['left'] -= 1
            raise PermissionError(13, 'locked by another process')
        return real_count()

    monkeypatch.setattr(up, 'pending_count', flaky_count)
    a = up.enqueue(_record(sample_items))
    up.start()
    try:
        assert _wait_until(lambda: server.sent_ids() == [a] and boom['left'] == 0)
        assert _wait_until(lambda: up.last_error is not None and 'locked' in up.last_error)
        assert up._thread.is_alive()
        b = up.enqueue(_record(sample_items))              # 新入队仍能唤醒并发出
        assert _wait_until(lambda: server.sent_ids() == [a, b])
        assert _wait_until(lambda: real_count() == 0)
        assert up._thread.is_alive() and up.status()['running'] is True
    finally:
        up.stop()
        up._thread.join(timeout=5)


def test_worker_survives_logging_failure(up, server, monkeypatch, sample_items):
    """写日志本身出错（异常处理里再抛）也不能让线程退出。"""
    monkeypatch.setattr(cu, 'START_DELAY_SEC', 0)
    monkeypatch.setattr(cu, 'FAIL_WAIT_SEC', 3600)

    def broken_log(*args, **kwargs):
        raise OSError('log sink broken')

    monkeypatch.setattr(logs, 'log', broken_log)
    a = up.enqueue(_record(sample_items))
    up.start()
    try:
        assert _wait_until(lambda: server.sent_ids() == [a])
        assert _wait_until(lambda: up.last_error is not None)
        assert up._thread.is_alive()
        b = up.enqueue(_record(sample_items))
        assert _wait_until(lambda: server.sent_ids() == [a, b])
        assert up._thread.is_alive()
    finally:
        up.stop()
        up._thread.join(timeout=5)


def test_trigger_restarts_dead_worker(up, server, monkeypatch, sample_items):
    """兜底：线程意外退出后，手动重试 / 新入队会把它重新拉起；从没启动过、或已 stop 的不拉起。"""
    import threading
    monkeypatch.setattr(cu, 'START_DELAY_SEC', 0)
    up.trigger()
    assert up._thread is None                               # 没启动过（如单元测试里）不自己起线程
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    up._thread = dead                                       # 模拟线程意外退出
    a = up.enqueue(_record(sample_items))
    try:
        assert up._thread is not dead and up._thread.is_alive()
        assert _wait_until(lambda: server.sent_ids() == [a])
    finally:
        up.stop()
        up._thread.join(timeout=5)
    stopped = up._thread
    up.trigger()
    assert up._thread is stopped and not stopped.is_alive()  # stop 之后不复活


@pytest.mark.parametrize('fragment', [
    b'"product_code": "P", "items": {"x": 1e400}',          # 解析成 inf
    b'"product_code": "P", "items": {"x": -1e999}',
    b'"product_code": "\\ud800", "items": {"x": 1}',        # 孤立代理项，编不成 UTF-8
])
def test_unserializable_line_quarantined_not_blocking(up, server, sample_items, fragment):
    a = up.enqueue(_record(sample_items))
    with open(up.pending_file, 'ab') as f:
        f.write(b'{"upload_id": "' + b'b' * 32 + b'", ' + fragment + b'}\n')
    b = up.enqueue(_record(sample_items))
    st = up.run_once()
    assert st == {'sent': 2, 'accepted': 2, 'rejected': 0, 'quarantined': 1, 'kept': 0, 'error': None}
    assert server.sent_ids() == [a, b]
    assert _pending_lines(up) == []
    [entry] = _rejected_entries(up)
    assert entry['error'] == '本地队列行损坏'
    for c in server.calls:
        assert b'Infinity' not in c['raw'] and b'NaN' not in c['raw']


def test_rejected_not_duplicated_when_rewrite_fails(up, server, monkeypatch, sample_items):
    """重写待传文件失败（被占用）时每轮会再退回同一批，退回文件里不能越记越多。"""
    a = up.enqueue(_record(sample_items))
    with open(up.pending_file, 'ab') as f:
        f.write(b'garbage\n')
    server.handler = lambda body: FakeResponse(200, {
        'ok': True, 'accepted': [], 'rejected': [{'upload_id': a, 'error': 'bad'}]})
    real_replace = os.replace

    def locked(*args, **kwargs):
        raise PermissionError(13, 'locked by another process')

    monkeypatch.setattr(os, 'replace', locked)
    for _ in range(3):
        st = up.run_once()
        assert st['error'] and 'locked' in st['error']
        assert len(_pending_lines(up)) == 2                 # 什么都没丢
    monkeypatch.setattr(os, 'replace', real_replace)
    st = up.run_once()
    assert st['error'] is None
    assert _pending_lines(up) == []
    entries = _rejected_entries(up)
    assert len(entries) == 2
    assert [e.get('raw') for e in entries if 'raw' in e] == ['garbage']
    assert [e['record']['upload_id'] for e in entries if 'record' in e] == [a]
    assert up.status()['rejected'] == 2


def _lock_file(monkeypatch, *paths):
    """让对指定文件的追加写报「被占用」，其他文件照常。返回的集合清空即解除占用。"""
    real = cu.CloudUploader._append_lines
    blocked = {str(p) for p in paths}

    def guarded(path, lines):
        if str(path) in blocked:
            raise PermissionError(13, f'locked: {path}')
        return real(path, lines)

    monkeypatch.setattr(cu.CloudUploader, '_append_lines', staticmethod(guarded))
    return blocked


def test_enqueue_falls_back_when_pending_file_locked(up, server, monkeypatch, sample_items):
    """待传文件被占用（如被 WPS/Excel 打开）：写到备用文件，照样 fsync 落盘；解除占用后并回并发出。"""
    fsynced = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (real_fsync(fd), fsynced.append(fd)))
    blocked = _lock_file(monkeypatch, up.pending_file)
    uid = up.enqueue(_record(sample_items))
    assert fsynced
    assert not up.pending_file.exists()
    [line] = [ln for ln in up.fallback_file.read_bytes().split(b'\n') if ln.strip()]
    assert json.loads(line)['upload_id'] == uid
    assert up.status()['pending'] == 1
    # 仍被占用：本轮并不回去，记录留在备用文件，线程按失败处理（等 60 秒）
    st = up.run_once()
    assert st['error'] and server.calls == []
    assert up.fallback_file.exists() and up.status()['pending'] == 1
    blocked.clear()
    st = up.run_once()
    assert st['error'] is None and st['accepted'] == 1
    assert server.sent_ids() == [uid]
    assert not up.fallback_file.exists() and _pending_lines(up) == []
    assert up.status()['pending'] == 0


def test_fallback_merge_does_not_duplicate(up, server, sample_items):
    """并回备用文件后、删备用文件前断电：下次再并回时不重复。"""
    a = up.enqueue(_record(sample_items))
    line = up.pending_file.read_bytes()
    up.fallback_file.write_bytes(line)                       # 同一条既在待传又在备用文件
    server.handler = _fail_conn
    up.run_once()
    assert len(_pending_lines(up)) == 1 and not up.fallback_file.exists()
    server.handler = FakeServer.accept_all
    up.run_once()
    assert server.sent_ids() == [a, a]                       # 两轮各发一次，每轮不重复
    assert _pending_lines(up) == []


def test_enqueue_keeps_record_in_memory_when_disk_unwritable(up, server, monkeypatch, sample_items):
    """两个队列文件都写不进（磁盘满 / 目录无权限）：抛 NotPersistedError 让调用方大声报错，
    记录暂存内存，发送线程每轮重试写盘，磁盘恢复后补写并发出。"""
    blocked = _lock_file(monkeypatch, up.pending_file, up.fallback_file)
    with pytest.raises(cu.NotPersistedError):
        up.enqueue(_record(sample_items))
    assert not up.pending_file.exists() and not up.fallback_file.exists()
    s = up.status()
    assert s['pending'] == 1 and s['last_error'] and '内存' in s['last_error']
    st = up.run_once()                                       # 磁盘仍不可写：保留，按失败处理
    assert st['error'] and server.calls == [] and up.status()['pending'] == 1
    blocked.clear()
    st = up.run_once()
    assert st['error'] is None and st['accepted'] == 1
    [uid] = server.sent_ids()
    assert re.fullmatch(r'[0-9a-f]{32}', uid)
    assert up.status()['pending'] == 0 and not up._unsaved
