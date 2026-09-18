"""
tests/conftest.py — 所有用例离线、隔离运行

- 每个用例切到独立临时目录：仓库根有真实 feishu_config.json / config.json，
  在根目录跑后端会把测试记录写进线上飞书
- 全局拦截真实网络：requests / httpx 发请求、socket 连接外部地址、DNS 解析外部主机一律报错，
  并在用例结束时检查「有没有代码试图联网」（被吞掉的异常也算失败）
  本机回环地址放行：Windows 上 asyncio 事件循环用 socket.socketpair 自连接，TestClient 需要
- 清掉 FEISHU_* 环境变量，重置飞书 / 直推上传器单例并停掉直推线程
"""
from __future__ import annotations

import ipaddress
import math
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class NetworkBlockedError(RuntimeError):
    """测试里禁止真实联网。"""


BLOCKED_ATTEMPTS: list[str] = []


def _blocked(what: str):
    BLOCKED_ATTEMPTS.append(what)
    raise NetworkBlockedError(f'测试禁止真实联网: {what}')


def _is_local_host(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode('ascii', 'replace')
    host = str(host).strip('[]')
    if host.lower() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host.split('%')[0]).is_loopback
    except ValueError:
        return False


def _install_network_block():
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else None
        if isinstance(address, tuple) and _is_local_host(host):
            return orig_connect(self, address)
        _blocked(f'socket.connect {address!r}')

    def guarded_connect_ex(self, address):
        host = address[0] if isinstance(address, tuple) else None
        if isinstance(address, tuple) and _is_local_host(host):
            return orig_connect_ex(self, address)
        _blocked(f'socket.connect_ex {address!r}')

    def guarded_getaddrinfo(host, *args, **kwargs):
        if _is_local_host(host):
            return orig_getaddrinfo(host, *args, **kwargs)
        _blocked(f'getaddrinfo {host!r}')

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo

    import requests.adapters

    def blocked_requests_send(self, request, *args, **kwargs):
        _blocked(f'requests {request.method} {request.url}')

    requests.adapters.HTTPAdapter.send = blocked_requests_send

    try:
        import httpx

        def blocked_httpx(self, request, *args, **kwargs):
            _blocked(f'httpx {request.method} {request.url}')

        async def blocked_httpx_async(self, request, *args, **kwargs):
            _blocked(f'httpx {request.method} {request.url}')

        httpx.HTTPTransport.handle_request = blocked_httpx
        httpx.AsyncHTTPTransport.handle_async_request = blocked_httpx_async
    except ImportError:
        pass


def pytest_configure(config):
    _install_network_block()


@pytest.fixture(autouse=True)
def _offline_sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ('FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'FEISHU_APP_TOKEN'):
        monkeypatch.delenv(k, raising=False)

    import backend.feishu_uploader as fu
    import backend.cloud_uploader as cu
    monkeypatch.setattr(fu, '_uploader', None)
    monkeypatch.setattr(cu, '_uploader', None)

    BLOCKED_ATTEMPTS.clear()
    yield tmp_path

    if cu._uploader is not None:
        cu._uploader.stop()
    attempts = list(BLOCKED_ATTEMPTS)
    BLOCKED_ATTEMPTS.clear()
    assert not attempts, f'用例试图真实联网: {attempts}'


@pytest.fixture
def sample_items():
    """有代表性的一组测试项：有单位 / 无单位 / NA 项 / EqN 计算失败(NaN) / 值是字符串 /
    value_display 与 value 都不是有限数（应跳过）/ 同名测项重复（后者覆盖前者）。"""
    return [
        {'type': 'Lx', 'pins': '1-2', 'value': 0.000123, 'lo': 0.0001, 'hi': 0.00015, 'result': 'Pass',
         'unit': 'uH', 'value_display': 123.0, 'lo_display': 100.0, 'hi_display': 150.0, 'symbol': 'A'},
        {'type': 'Lk', 'pins': '1-2', 'value': 1.2e-06, 'lo': 0.0, 'hi': 0.0, 'result': 'Pass',
         'unit': 'uH', 'value_display': 1.2, 'lo_display': None, 'hi_display': 2.0, 'symbol': 'B'},
        {'type': 'Q', 'pins': '3-4', 'value': 45.6, 'lo': 0.0, 'hi': 0.0, 'result': 'NA',
         'unit': '', 'value_display': 45.6, 'lo_display': None, 'hi_display': None, 'symbol': None},
        {'type': 'Turn', 'pins': '5-6', 'value': 12, 'lo': 0.0, 'hi': 0.0, 'result': 'Pass',
         'value_display': 12, 'symbol': 'C'},
        {'type': 'Dcr', 'pins': '7-8', 'value': 0.0123, 'lo': 0.0, 'hi': 0.0, 'result': 'Pass',
         'unit': 'mΩ', 'value_display': '12.3', 'symbol': None},
        {'type': 'Cx', 'pins': '1-5', 'value': math.nan, 'lo': 0.0, 'hi': 0.0, 'result': 'NA',
         'unit': 'pF', 'value_display': math.inf, 'symbol': None},
        {'type': 'Zx', 'pins': '2-6', 'value': 'bad', 'lo': 0.0, 'hi': 0.0, 'result': 'NA',
         'unit': 'Ω', 'value_display': None, 'symbol': None},
        {'type': 'Lx', 'pins': '1-2', 'value': 99.5, 'lo': 0.0, 'hi': 0.0, 'result': 'Pass',
         'unit': 'uH', 'value_display': -math.inf, 'symbol': None},
        {'type': 'EqN', 'pins': '-', 'value': 0.0, 'lo': 0.0, 'hi': 0.0, 'result': 'Fail',
         'unit': '', 'value_display': math.nan, 'lo_display': None, 'hi_display': None,
         'error': 'C=0', 'symbol': 'N'},
    ]
