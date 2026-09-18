"""
cloud_uploader.py — 新码记录直推 SOAI 云端（v1.7.5）

- 只处理「新码记录」（序号是铝壳成品码，见 finished_code.py）；旧码记录仍走 feishu_uploader，互不影响
- 先落盘再发送：enqueue 追加一行到 cloud_pending.jsonl 并 fsync 后才返回，断网/断电不丢
- 后台线程（不依赖飞书凭证）每批最多 50 条 POST 到 SOAI 接收端：
    accepted → 从待传里删掉；rejected（服务端明确退回）→ 移到 cloud_rejected.jsonl，不再重试；
    网络错误 / 非 JSON / 非 200 → 整批保留，60 秒后再试（服务端按 upload_id 幂等，重发不重复）
- 发 HTTP 时不持锁；收到结果后持锁重写待传文件，只删本批有结论的 id，期间新入队的行保留
- 队列里损坏的行移入 cloud_rejected.jsonl（原因「本地队列行损坏」），不阻塞其他行
- 待传文件写不进（被 WPS/Excel 等占用）→ 改写备用文件 cloud_pending_fallback.jsonl（同样 fsync），
  发送线程每轮先并回待传；两个文件都写不进（磁盘满 / 无权限）→ 暂存内存并抛 NotPersistedError
  让调用方记 ERROR，发送线程每轮重试写盘

文件都在进程工作目录下（与 feishu_pending.jsonl 同目录）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from . import logs
from . import state
from .feishu_uploader import item_values, record_time_ms


DEFAULT_INGEST_URL = 'https://www.soaipower.com/api/erp/production/ingest'
PENDING_FILE_NAME = 'cloud_pending.jsonl'
REJECTED_FILE_NAME = 'cloud_rejected.jsonl'
FALLBACK_FILE_NAME = 'cloud_pending_fallback.jsonl'   # 待传文件被占用时的备用落盘处

BATCH_SIZE = 50            # 每批最多条数（接收端上限 200）
HTTP_TIMEOUT = (5, 30)     # (连接, 读取) 秒
START_DELAY_SEC = 5        # 线程启动后等 5 秒再开始
FAIL_WAIT_SEC = 60         # 失败后等 60 秒（可被 enqueue / 手动重试提前唤醒）

CORRUPT_LINE_ERROR = '本地队列行损坏'

_UPLOAD_ID_RE = re.compile(r'[0-9a-f]{32}')


class NotPersistedError(RuntimeError):
    """待传文件和备用文件都写不进：记录只暂存在内存里（发送线程每轮重试写盘），软件关掉前没写进去就会丢。"""


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _str_or_none(v) -> Optional[str]:
    """空串 / None → None，其余转字符串。"""
    if v is None:
        return None
    s = str(v)
    return s if s else None


def _reject_constant(name):
    # json.loads 默认接受 NaN / Infinity，队列行里出现就当损坏行
    raise ValueError(f'非法数值 {name}')


def _parse_line(raw: bytes) -> Optional[dict]:
    """解析一行待传记录；不是合法记录（解码失败 / 非 JSON / 含 NaN / 缺 upload_id /
    发送时序列化不出来）返回 None。"""
    try:
        rec = json.loads(raw.decode('utf-8'), parse_constant=_reject_constant)
        # 1e400 这类越界数会被解析成 inf、\ud800 这类孤立代理项编不成 UTF-8：
        # 发送时整批序列化失败会把整个队列堵死，这里就按损坏行处理
        json.dumps(rec, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except Exception:
        return None
    if not isinstance(rec, dict):
        return None
    uid = rec.get('upload_id')
    if not isinstance(uid, str) or not _UPLOAD_ID_RE.fullmatch(uid):
        return None
    return rec


def build_record(record_dict: dict) -> dict:
    """run_test 的记录字典 → 直推载荷里的单条记录（upload_id 在这里生成一次，之后重试不变）。
    record_dict 与飞书 push_async 的字典同形：timestamp/product_code/serial_code/record_number/
    core_number/overall/items/company/line/station/deployment_id/calibration_id。"""
    ts_str = record_dict.get('timestamp', '')
    ts_ms = record_time_ms(ts_str)
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
        logs.log(f'直推记录测试时间解析失败（{ts_str!r}），改用当前时间', 'WARN')
    overall = str(record_dict.get('overall') or '').strip().upper()
    return {
        'upload_id': uuid.uuid4().hex,
        'product_code': str(record_dict.get('product_code') or ''),
        'test_time_ms': ts_ms,
        'company': str(record_dict.get('company') or ''),
        'line': str(record_dict.get('line') or ''),
        'station': str(record_dict.get('station') or ''),
        'deployment_id': str(record_dict.get('deployment_id') or ''),
        'serial_code': _str_or_none(record_dict.get('serial_code')),
        'record_number': _str_or_none(record_dict.get('record_number')),
        'core_number': _str_or_none(record_dict.get('core_number')),
        'overall': 'PASS' if overall == 'PASS' else 'FAIL',
        'items': item_values(record_dict.get('items')),
        'calibration_id': _str_or_none(record_dict.get('calibration_id')),
    }


class CloudUploader:
    def __init__(self, work_dir: Path, app_version: str = ''):
        self.work_dir = Path(work_dir)
        self.pending_file = self.work_dir / PENDING_FILE_NAME
        self.rejected_file = self.work_dir / REJECTED_FILE_NAME
        self.fallback_file = self.work_dir / FALLBACK_FILE_NAME
        self.app_version = app_version
        self._unsaved: list[bytes] = []      # 两个文件都写不进时暂存在内存的行（持 self._lock 访问）
        self._lock = threading.Lock()        # 保护队列文件与 _unsaved 的读写
        self._run_lock = threading.Lock()    # 同一时刻只跑一轮发送
        self._start_lock = threading.Lock()  # 防止并发 start / trigger 拉起两个线程
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_ok_at: Optional[str] = None
        self.last_error: Optional[str] = None

    # ── 地址 ──────────────────────────────────────────────
    def ingest_url(self) -> str:
        """默认 SOAI 线上地址；config.json 里 cloud_ingest_url 可覆盖（测试用）。"""
        try:
            url = state._load_config().get('cloud_ingest_url')
            if isinstance(url, str) and url.strip():
                return url.strip()
        except Exception:
            pass
        return DEFAULT_INGEST_URL

    # ── 文件操作（调用方持 self._lock）──────────────────────
    @staticmethod
    def _read_lines(path: Path) -> list[bytes]:
        if not path.exists():
            return []
        data = path.read_bytes()
        return [ln.rstrip(b'\r') for ln in data.split(b'\n') if ln.strip()]

    @staticmethod
    def _append_lines(path: Path, lines: list[bytes]):
        """追加若干行并 fsync。文件末尾缺换行（上次写一半断电）时先补换行，免得粘到坏行上。"""
        with open(path, 'ab') as f:
            size = os.path.getsize(path)
            if size > 0:
                with open(path, 'rb') as rf:
                    rf.seek(size - 1)
                    if rf.read(1) != b'\n':
                        f.write(b'\n')
            for ln in lines:
                f.write(ln + b'\n')
            f.flush()
            os.fsync(f.fileno())

    def _rejected_keys(self) -> tuple[set, set]:
        """退回文件里已有的 (upload_id 集合, 损坏行原文集合)。"""
        ids: set = set()
        raws: set = set()
        for ln in self._read_lines(self.rejected_file):
            try:
                e = json.loads(ln.decode('utf-8'))
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            rec = e.get('record')
            if isinstance(rec, dict) and isinstance(rec.get('upload_id'), str):
                ids.add(rec['upload_id'])
            if isinstance(e.get('raw'), str):
                raws.add(e['raw'])
        return ids, raws

    def _append_rejected(self, entries: list[dict]):
        """追加到退回文件。已记过的（同一 upload_id / 同一损坏行原文）不再追加：
        重写待传文件失败时下一轮会再退回同一批，不能越记越多。"""
        ids, raws = self._rejected_keys()
        lines = []
        for e in entries:
            rec = e.get('record')
            uid = rec.get('upload_id') if isinstance(rec, dict) else None
            raw = e.get('raw')
            if (uid is not None and uid in ids) or (isinstance(raw, str) and raw in raws):
                continue
            if uid is not None:
                ids.add(uid)
            if isinstance(raw, str):
                raws.add(raw)
            lines.append(json.dumps(e, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if lines:
            self._append_lines(self.rejected_file, lines)

    def _rewrite_pending(self, remove_ids: set = frozenset(), remove_raw: set = frozenset()):
        """重读当前待传文件，删掉指定 id / 指定原始行，其余（含期间新入队的）原样保留。
        临时文件 + fsync + os.replace，写一半断电也不会丢原文件。"""
        keep: list[bytes] = []
        for raw in self._read_lines(self.pending_file):
            if raw in remove_raw:
                continue
            if remove_ids:
                rec = _parse_line(raw)
                if rec is not None and rec['upload_id'] in remove_ids:
                    continue
            keep.append(raw)
        tmp = self.pending_file.with_name(self.pending_file.name + '.tmp')
        with open(tmp, 'wb') as f:
            for raw in keep:
                f.write(raw + b'\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(self.pending_file))

    def _merge_side_queues(self):
        """把暂存内存 / 备用文件里的记录并回待传文件（调用方持 self._lock）。
        写不进就抛异常，记录原样留在原处；待传里已有的 upload_id / 原文不重复追加
        （并回后、删备用文件前断电，下次再并回时不会多出来）。"""
        if self._unsaved:
            try:
                self._append_lines(self.pending_file, self._unsaved)
            except OSError:
                self._append_lines(self.fallback_file, self._unsaved)
            self._unsaved = []
        if not self.fallback_file.exists():
            return
        extra = self._read_lines(self.fallback_file)
        if extra:
            have_raw = set(self._read_lines(self.pending_file))
            have_ids = {rec['upload_id'] for rec in map(_parse_line, have_raw) if rec is not None}
            new: list[bytes] = []
            for raw in extra:
                rec = _parse_line(raw)
                if raw in have_raw or (rec is not None and rec['upload_id'] in have_ids):
                    continue
                have_raw.add(raw)
                if rec is not None:
                    have_ids.add(rec['upload_id'])
                new.append(raw)
            if new:
                self._append_lines(self.pending_file, new)
        os.remove(str(self.fallback_file))

    # ── 入队 ──────────────────────────────────────────────
    def enqueue(self, record_dict: dict) -> str:
        """落盘一条新码记录（fsync 后才返回），返回 upload_id，然后唤醒发送线程。
        待传文件写不进 → 写备用文件（同样 fsync）；两个都写不进 → 暂存内存并抛 NotPersistedError。"""
        rec = build_record(record_dict)
        uid = rec['upload_id']
        line = json.dumps(rec, ensure_ascii=False, allow_nan=False).encode('utf-8')
        fallback_err = None
        not_persisted = None
        with self._lock:
            try:
                self._append_lines(self.pending_file, [line])
            except OSError as e1:
                fallback_err = e1
                try:
                    self._append_lines(self.fallback_file, [line])
                except OSError as e2:
                    self._unsaved.append(line)
                    self.last_error = (f'直推队列写盘失败，{len(self._unsaved)} 条暂存内存，'
                                       f'磁盘恢复后自动补写（补写前关闭软件会丢）: {e2}')
                    not_persisted = NotPersistedError(self.last_error)
        if not_persisted is None and fallback_err is not None:
            logs.log(f'直推待传文件写不进（{fallback_err}），记录已写入备用文件 {FALLBACK_FILE_NAME}，'
                     f'发送线程稍后并回', 'WARN', sticky=True)
        self.trigger()
        if not_persisted is not None:
            raise not_persisted
        return uid

    # ── 发送 ──────────────────────────────────────────────
    def _send_batch(self, url: str, batch: list[dict]):
        """发一批。返回 (ok, accepted_ids, {rejected_id: 原因}, 错误描述)。
        只认本批里的 id；ok=False 表示整批保留待重试。"""
        body = {'source': 'autotest', 'app_version': self.app_version, 'records': batch}
        try:
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except ValueError as e:
            return False, set(), {}, f'载荷序列化失败: {e}'
        try:
            r = requests.post(url, data=data,
                              headers={'Content-Type': 'application/json; charset=utf-8'},
                              timeout=HTTP_TIMEOUT)
        except Exception as e:
            return False, set(), {}, f'网络错误: {e}'
        status = getattr(r, 'status_code', None)
        try:
            resp = r.json()
        except Exception:
            text = str(getattr(r, 'text', '') or '')[:200]
            return False, set(), {}, f'非 JSON 响应 HTTP {status}: {text}'
        if status != 200 or not isinstance(resp, dict) or resp.get('ok') is not True:
            err = resp.get('error') if isinstance(resp, dict) else None
            return False, set(), {}, f'服务端未接收 HTTP {status}: {err or resp}'
        accepted = resp.get('accepted')
        rejected = resp.get('rejected')
        if not isinstance(accepted, list) or not isinstance(rejected, list):
            return False, set(), {}, f'响应格式不对 HTTP {status}'
        batch_ids = {rec['upload_id'] for rec in batch}
        acc = {x for x in accepted if isinstance(x, str) and x in batch_ids}
        rej: dict = {}
        for x in rejected:
            if not isinstance(x, dict):
                continue
            uid = x.get('upload_id')
            if isinstance(uid, str) and uid in batch_ids and uid not in acc:
                rej[uid] = str(x.get('error') or '服务端退回')
        return True, acc, rej, None

    def run_once(self) -> dict:
        """跑一轮：读待传快照 → 损坏行隔离 → 分批发送 → 按结果重写待传文件。
        返回统计 {sent, accepted, rejected, quarantined, kept, error}；
        kept > 0 或 error 非空表示有记录留待下轮重试。"""
        stats = {'sent': 0, 'accepted': 0, 'rejected': 0, 'quarantined': 0, 'kept': 0, 'error': None}
        with self._run_lock:
            merge_error = None
            with self._lock:
                try:
                    self._merge_side_queues()
                except Exception as e:
                    # 并不回去的记录原样留在备用文件 / 内存里；本轮照常发待传文件里已有的
                    merge_error = f'暂存记录并回待传文件失败: {e}'
                raws = self._read_lines(self.pending_file)
            if merge_error:
                stats['error'] = merge_error        # 按失败处理：线程等 60 秒再试
                if merge_error != self.last_error:
                    logs.log(f'直推{merge_error}', 'WARN', sticky=True)
                self.last_error = merge_error
            if not raws:
                return stats

            good: list[dict] = []
            corrupt: list[bytes] = []
            seen: set = set()
            for raw in raws:
                rec = _parse_line(raw)
                if rec is None:
                    corrupt.append(raw)
                    continue
                if rec['upload_id'] in seen:   # 同一条重复落盘只发一次
                    continue
                seen.add(rec['upload_id'])
                good.append(rec)

            if corrupt:
                try:
                    now = _now_str()
                    with self._lock:
                        self._append_rejected([
                            {'rejected_at': now, 'error': CORRUPT_LINE_ERROR,
                             'raw': raw.decode('utf-8', 'replace')} for raw in corrupt])
                        self._rewrite_pending(remove_raw=set(corrupt))
                    stats['quarantined'] = len(corrupt)
                    logs.log(f'直推队列发现 {len(corrupt)} 行损坏，已移入 {REJECTED_FILE_NAME}', 'WARN', sticky=True)
                except Exception as e:
                    stats['error'] = f'隔离损坏行失败: {e}'
                    self.last_error = stats['error']
                    logs.log(f'直推队列{stats["error"]}', 'ERROR', sticky=True)

            url = self.ingest_url()
            for i in range(0, len(good), BATCH_SIZE):
                batch = good[i:i + BATCH_SIZE]
                ok, acc, rej, err = self._send_batch(url, batch)
                stats['sent'] += len(batch)
                if not ok:
                    left = len(good) - i
                    stats['kept'] += left
                    stats['error'] = err
                    if err != self.last_error:   # 同样的错误每 60 秒一次，只在变化时记日志，免得刷屏
                        logs.log(f'新码直推云端失败，{left} 条留待重试: {err}', 'WARN')
                    self.last_error = err
                    break   # 网络/服务端不通，本轮剩下的批次不再硬发
                self.last_ok_at = _now_str()
                self.last_error = None
                try:
                    if acc or rej:
                        by_id = {rec['upload_id']: rec for rec in batch}
                        with self._lock:
                            if rej:
                                now = _now_str()
                                self._append_rejected([
                                    {'rejected_at': now, 'error': rej[uid], 'record': by_id[uid]}
                                    for uid in rej])
                            self._rewrite_pending(remove_ids=set(acc) | set(rej))
                except Exception as e:
                    # 已被服务端接收但本地没删掉：下轮会重发，服务端按 upload_id 幂等
                    stats['error'] = f'更新本地队列失败: {e}'
                    self.last_error = stats['error']
                    logs.log(f'直推{stats["error"]}', 'ERROR', sticky=True)
                unknown = len(batch) - len(acc) - len(rej)
                stats['accepted'] += len(acc)
                stats['rejected'] += len(rej)
                stats['kept'] += unknown
                if rej:
                    logs.log(f'新码直推：服务端退回 {len(rej)} 条，已移入 {REJECTED_FILE_NAME}', 'WARN', sticky=True)
                if unknown:
                    logs.log(f'新码直推：{unknown} 条服务端未给结论，留待重试', 'WARN')
            if merge_error and self.last_error is None:
                self.last_error = merge_error       # 本轮发送成功，但还有记录没并回，状态里仍要看得到
            if stats['accepted']:
                logs.log(f'新码直推云端成功 {stats["accepted"]} 条')
        return stats

    # ── 后台线程 ──────────────────────────────────────────
    def _loop(self):
        self._stop.wait(START_DELAY_SEC)
        while not self._stop.is_set():
            self._wake.clear()
            # 一轮里任何异常（含查待传条数时读文件出错、写日志出错）都按失败处理，线程绝不能退出
            try:
                st = self.run_once()
                failed = bool(st['error']) or st['kept'] > 0
                more = not failed and self.pending_count() > 0   # 期间又有新记录入队：立刻下一批
            except Exception as e:
                failed, more = True, False
                self.last_error = f'直推循环异常: {e}'
                try:
                    logs.log(self.last_error, 'ERROR')
                except Exception:
                    pass
            if self._stop.is_set():
                break
            if failed:
                self._wake.wait(FAIL_WAIT_SEC)
            elif not more:
                self._wake.wait()

    def start(self):
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name='cloud-upload')
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def trigger(self):
        """唤醒发送线程（新入队 / 手动重试）。兜底：线程启动过、没被 stop 却已退出，就重新拉起。"""
        t = self._thread
        if t is not None and not t.is_alive() and not self._stop.is_set():
            try:
                logs.log('直推发送线程意外退出，已重新拉起', 'WARN', sticky=True)
            except Exception:
                pass
            self.start()
        self._wake.set()

    # ── 状态 ──────────────────────────────────────────────
    def pending_count(self) -> int:
        """待传条数，含备用文件与暂存内存里还没并回的。"""
        with self._lock:
            n = len(self._read_lines(self.pending_file)) + len(self._unsaved)
            if self.fallback_file.exists():
                n += len(self._read_lines(self.fallback_file))
            return n

    def rejected_count(self) -> int:
        with self._lock:
            return len(self._read_lines(self.rejected_file))

    def status(self) -> dict:
        return {
            'url': self.ingest_url(),
            'pending': self.pending_count(),
            'rejected': self.rejected_count(),
            'last_ok_at': self.last_ok_at,
            'last_error': self.last_error,
            'running': bool(self._thread and self._thread.is_alive()),
        }


# ── 全局单例 ──────────────────────────────────────────────
_uploader: Optional[CloudUploader] = None
_init_lock = threading.Lock()


def get_cloud_uploader(work_dir: Optional[Path] = None) -> CloudUploader:
    """返回单例（工作目录取首次调用时的 cwd，与飞书上传器一致）。不需要任何凭证。"""
    global _uploader
    if _uploader is not None:
        return _uploader
    with _init_lock:
        if _uploader is None:
            _uploader = CloudUploader(work_dir or Path.cwd())
        return _uploader


def start(app_version: str = '') -> CloudUploader:
    up = get_cloud_uploader()
    if app_version:
        up.app_version = app_version
    up.start()
    return up


def enqueue(record_dict: dict) -> str:
    return get_cloud_uploader().enqueue(record_dict)


def trigger():
    get_cloud_uploader().trigger()


def status() -> dict:
    return get_cloud_uploader().status()
