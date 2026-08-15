"""
main.py — FastAPI 后端
所有对 agent 的调用都经过这里，agent 不直接暴露给前端
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional
import json
import sys
import threading

from . import state
from . import logs
from .csv_writer import save
from .inspection_csv_writer import save as save_inspection
from .feishu_uploader import get_uploader

APP_VERSION = '1.5.1'  # 软件版本号（每次发布更新，同步更新 CHANGELOG.md）

app = FastAPI(title='变压器测试系统', version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
def _startup_feishu_uploader():
    """后端一启动就拉起飞书上传器 + 续传线程，不必等第一次测试。
    这样开机后即使工人还没测试，积压的 pending 也会自动续传。"""
    try:
        up = get_uploader(Path.cwd())
        if up:
            pend = up.queue_file
            n = 0
            if pend.exists():
                try:
                    n = sum(1 for ln in pend.read_text(encoding='utf-8').splitlines() if ln.strip())
                except Exception:
                    n = -1
            if n > 0:
                logs.log(f'飞书上传器已就绪，发现 {n} 条待续传，后台线程开始补推', sticky=True)
            else:
                logs.log('飞书上传器已就绪，无待续传', sticky=True)
        else:
            logs.log('飞书未配置（缺 feishu_config.json），云端推送已禁用', 'WARN', sticky=True)
    except Exception as e:
        logs.log(f'飞书上传器启动失败: {e}', 'ERROR', sticky=True)
    # 启动参数自动同步线程（已注册工位则每5分钟自动拉ERP下发的参数）
    try:
        _start_auto_sync()
        logs.log(f'软件 v{APP_VERSION} · 参数自动同步已开启（每5分钟）', sticky=True)
    except Exception as e:
        logs.log(f'自动同步启动失败: {e}', 'WARN', sticky=True)
    # 启动软件更新检查线程（每小时查飞书 _软件版本 表）
    try:
        threading.Thread(target=_auto_update_check_loop, daemon=True, name='update-check').start()
    except Exception as e:
        logs.log(f'更新检查启动失败: {e}', 'WARN', sticky=True)


@app.get('/api/version')
def get_app_version():
    """软件版本号 + 当前工位。"""
    return {'version': APP_VERSION, **state.get_deployment()}


# ── 请求/响应模型 ────────────────────────────────────────────────

class InitRequest(BaseModel):
    product_code: str
    port: Optional[str] = None   # auto scan if omitted


class InspectionInitRequest(BaseModel):
    product_code: str
    port: str


class RunTestRequest(BaseModel):
    serial_code: str = ''
    record_number: str = ''
    core_number: str = ''


class TestResult(BaseModel):
    ok: bool
    timestamp: str
    product_code: str
    serial_code: str
    overall: str
    passed: int
    failed: int
    items: list[dict]
    csv_file: str


class InspectionStepResult(BaseModel):
    ok: bool
    step_index: int
    pins: str
    step_result: str
    items: list[dict]
    finished: bool
    next_prompt: str
    overall: str = ""


@app.get('/api/products')
def list_products():
    """列出所有可用产品配置"""
    products_dir = state.get_products_dir()
    result = []
    for f in sorted(products_dir.glob('*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            result.append({
                'product_code': data['product_code'],
                'product_name': data['product_name'],
                'instrument_config_id': data.get('instrument_config_id', 0),
                'instrument_driver': data.get('instrument_driver', 'uce'),
                'workflow_type': data.get('workflow_type', 'fixture_test'),
                'test_items_count': len(data.get('test_items', [])),
                'inspection_steps_count': len(data.get('inspection_steps', [])),
                'description': data.get('description', '')
            })
        except Exception:
            pass
    return result


@app.get('/api/products/{product_code}')
def get_product(product_code: str):
    """Get full product configuration."""
    p = state.get_products_dir() / f'{product_code}.json'
    if not p.exists():
        raise HTTPException(404, f'product {product_code} not found')
    data = json.loads(p.read_text(encoding='utf-8'))
    data.setdefault('instrument_driver', 'uce')
    data.setdefault('workflow_type', 'fixture_test')
    data.setdefault('inspection_steps', [])
    return data


class ProductBody(BaseModel):
    product_code: str
    product_name: str
    instrument_config_id: int = 0
    instrument_driver: str = 'uce'
    workflow_type: str = 'fixture_test'
    description: str = ''
    test_items: list[dict] = []
    inspection_steps: list[dict] = []
    enable_eq_n: bool = False
    eq_n_vars: dict = Field(default_factory=lambda: {'l_raw': 'A', 'lk_raw': 'B', 'l_aux': 'C'})
    require_record_number: bool = True
    require_core_number: bool = False


@app.post('/api/products', status_code=201)
def create_product(body: ProductBody):
    """新建产品配置"""
    p = state.get_products_dir() / f'{body.product_code}.json'
    if p.exists():
        raise HTTPException(400, f'产品已存在: {body.product_code}')
    p.write_text(json.dumps(body.model_dump(), indent=2, ensure_ascii=False), encoding='utf-8')
    return {'ok': True, 'product_code': body.product_code}


@app.put('/api/products/{product_code}')
def update_product(product_code: str, body: ProductBody):
    """更新产品配置"""
    p = state.get_products_dir() / f'{product_code}.json'
    if not p.exists():
        raise HTTPException(404, f'产品不存在: {product_code}')
    p.write_text(json.dumps(body.model_dump(), indent=2, ensure_ascii=False), encoding='utf-8')
    return {'ok': True, 'product_code': product_code}


@app.delete('/api/products/{product_code}')
def delete_product(product_code: str):
    """删除产品配置"""
    p = state.get_products_dir() / f'{product_code}.json'
    if not p.exists():
        raise HTTPException(404, f'产品不存在: {product_code}')
    p.unlink()
    return {'ok': True}


@app.post('/api/config/upload')
def upload_config():
    """把本地 products/*.json 上传到飞书云端"""
    uploader = get_uploader(Path.cwd())
    if not uploader:
        raise HTTPException(400, '飞书未配置（缺少凭证）')
    try:
        result = uploader.upload_products(state.get_products_dir())
        return {'ok': True, **result}
    except Exception as e:
        raise HTTPException(500, f'上传失败: {e}')


@app.post('/api/config/download')
def download_config():
    """从飞书云端拉取产品配置写入本地"""
    uploader = get_uploader(Path.cwd())
    if not uploader:
        raise HTTPException(400, '飞书未配置（缺少凭证）')
    try:
        result = uploader.download_products(state.get_products_dir())
        return {'ok': True, **result}
    except Exception as e:
        raise HTTPException(500, f'下载失败: {e}')


# ── 仪器控制 ─────────────────────────────────────────────────────

@app.post('/api/initialize')
def initialize(req: InitRequest):
    """
    7步初始化：扫描端口 → 连接 → 加载配置 → 比对 → 初始化TRG → 就绪
    成功后 runner 保持连接，可以反复调用 /api/test/run
    """
    from agent.test_runner import TestRunner

    # 找产品JSON
    product_path = state.get_products_dir() / f'{req.product_code}.json'
    if not product_path.exists():
        raise HTTPException(404, f'产品配置不存在: {req.product_code}')

    logs.start_session(req.product_code, 'initialize')
    logs.log(f'初始化请求：product={req.product_code} port={req.port or "auto"}')

    # 关闭旧连接
    if state.runner:
        logs.log('关闭旧连接')
        state.runner.close()
        state.runner = None

    # 初始化
    runner = TestRunner(str(product_path), logger=logs.log)
    port = req.port or state.get_port()
    status = runner.initialize(port=port, baudrate=state.get_baudrate())

    if status['ok']:
        state.runner = runner
        state.current_product = req.product_code
        # 记住成功的端口
        if status.get('port'):
            state.save_port(status['port'])
        logs.log('初始化成功')
    else:
        logs.log('初始化失败')
        runner.close()

    return status


@app.get('/api/status')
def get_status():
    """获取当前系统状态"""
    return {
        'ready': state.runner is not None and state.runner._ready,
        'product_code': state.current_product,
        'port': state.get_port(),
    }


@app.post('/api/test/run')
def run_test(req: RunTestRequest = RunTestRequest()):
    """
    执行一次测试，返回结果并保存CSV
    必须先 POST /api/initialize 成功
    """
    if not state.runner or not state.runner._ready:
        raise HTTPException(400, '仪器未初始化，请先调用 /api/initialize')

    logs.log(f'开始测试' + (f'，序列码={req.serial_code}' if req.serial_code else ''))
    record = state.runner.run()
    if record is None:
        logs.log('测试失败：仪器无响应')
        raise HTTPException(500, '测试失败：仪器无响应')

    # 绑定扫码序列码 / 人工输入字段
    record.serial_code = req.serial_code
    record.record_number = req.record_number
    record.core_number = req.core_number

    # 保存CSV
    csv_file = save(record, state.get_results_dir())
    logs.log(f'测试完成：{record.overall}，结果保存 {csv_file}')

    # 飞书异步推送（无凭证时静默跳过；失败入队后台重试）
    dep = state.get_deployment()
    uploader = get_uploader(Path.cwd())
    if uploader:
        uploader.push_async({
            'timestamp': record.timestamp,
            'product_code': record.product_code,
            'serial_code': record.serial_code,
            'record_number': record.record_number,
            'core_number': record.core_number,
            'overall': record.overall,
            'passed': record.passed,
            'failed': record.failed,
            'items': record.items,
            'company': dep.get('company', ''),
            'line': dep.get('line', ''),
            'station': dep.get('station', ''),
            'deployment_id': dep.get('deployment_id', ''),
        })

    return TestResult(
        ok=True,
        timestamp=record.timestamp,
        product_code=record.product_code,
        serial_code=record.serial_code,
        overall=record.overall,
        passed=record.passed,
        failed=record.failed,
        items=record.items,
        csv_file=csv_file
    )


# ── 工位注册 + 参数同步（第2步：ERP集中管控）────────────
class RegisterDeploymentRequest(BaseModel):
    company: str
    line: str
    station: str


@app.get('/api/deployment')
def get_deployment_info():
    """当前工位信息；前端据此判断是否已注册。"""
    return state.get_deployment()


@app.post('/api/deployment/register')
def register_deployment(req: RegisterDeploymentRequest):
    """首次注册工位：生成 deployment_id，写飞书 _工位 + 本地 config。"""
    company = (req.company or '').strip()
    line = (req.line or '').strip()
    station = (req.station or '').strip()
    if not (company and line and station):
        raise HTTPException(400, '公司/产线/工段都要填')
    uploader = get_uploader(Path.cwd())
    if not uploader:
        raise HTTPException(400, '飞书未配置，无法注册工位')
    try:
        dep_id = uploader.register_station(company, line, station)
    except Exception as e:
        raise HTTPException(500, f'注册失败: {e}')
    state.save_deployment(dep_id, company, line, station)
    logs.log(f'工位注册成功: {dep_id}')
    return {'ok': True, 'deployment_id': dep_id, 'company': company, 'line': line, 'station': station}


def _do_sync_params() -> dict:
    """同步参数核心逻辑（端点 + 后台自动同步线程共用）。
    从飞书 _产品参数 拉本工位下发的产品，版本更新的覆盖本地，未下发的归档。"""
    dep = state.get_deployment()
    if not dep.get('deployment_id'):
        return {'ok': False, 'error': '尚未注册工位'}
    uploader = get_uploader(Path.cwd())
    if not uploader:
        return {'ok': False, 'error': '飞书未配置'}
    remote = uploader.fetch_deployed_params(dep['deployment_id'])

    products_dir = state.get_products_dir()
    products_dir.mkdir(parents=True, exist_ok=True)
    updated = []
    remote_codes = set()
    for item in remote:
        code = item['product_code']
        remote_codes.add(code)
        ver = item['version']
        upd = item.get('updated_at', 0)
        cfg = item['config']
        local_path = products_dir / f'{code}.json'
        local_ver, local_upd = 0, 0
        if local_path.exists():
            try:
                local_data = json.loads(local_path.read_text(encoding='utf-8'))
                local_ver = int(local_data.get('_version', 0))
                local_upd = int(local_data.get('_updated_at', 0))
            except Exception:
                local_ver, local_upd = 0, 0
        # 远端为准：版本或更新时间任一变化就覆盖（兼容撤回后重新下发版本回到 v1 的情况）
        if ver != local_ver or upd != local_upd:
            cfg['_version'] = ver
            cfg['_updated_at'] = upd
            local_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            updated.append({'product_code': code, 'version': ver})

    # 收权：本地未下发的产品移到 _archived（不删，可恢复）
    archived = []
    archive_dir = products_dir / '_archived'
    for p in products_dir.glob('*.json'):
        stem = p.stem
        if stem not in remote_codes:
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                p.rename(archive_dir / p.name)
                archived.append(stem)
            except Exception:
                pass

    if updated:
        parts = [f"{u['product_code']}(v{u['version']})" for u in updated]
        logs.log('参数已更新: ' + ', '.join(parts), sticky=True)
    return {'ok': True, 'updated': updated, 'archived': archived, 'total_remote': len(remote)}


# ── 软件自动更新（飞书 _软件版本 表为更新通道）────────────────────

_UPDATE_BAT = r'''@echo off
cd /d %~dp0
timeout /t 3 /nobreak >nul
taskkill /f /im smarton-backend.exe >nul 2>&1
timeout /t 2 /nobreak >nul
copy /y "__NEWREL__\smarton-backend.exe" "smarton-backend.exe" >nul
if errorlevel 1 copy /y "backup\smarton-backend.exe" "smarton-backend.exe" >nul
if exist "__NEWREL__\smarton.exe" copy /y "__NEWREL__\smarton.exe" "smarton.exe" >nul 2>&1
if exist "__NEWREL__\frontend\dist" (
  rd /s /q "frontend\dist" >nul 2>&1
  xcopy /y /e /i "__NEWREL__\frontend\dist" "frontend\dist" >nul
)
if exist "__NEWREL__\更新日志.md" copy /y "__NEWREL__\更新日志.md" "更新日志.md" >nul 2>&1
start "" "smarton.exe"
timeout /t 2 /nobreak >nul
rd /s /q "update_tmp" >nul 2>&1
del "%~f0"
'''


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip('vV').split('.'))
    except Exception:
        return (0,)


def _check_update() -> dict:
    """查飞书 _软件版本 表，比较版本。返回给前端的 dict（内部字段 _rel 供 apply 用）。"""
    uploader = get_uploader(Path.cwd())
    if not uploader:
        return {'ok': False, 'error': '飞书未配置'}
    try:
        rel = uploader.fetch_latest_release()
    except Exception as e:
        return {'ok': False, 'error': f'检查更新失败: {e}'}
    if not rel or not rel.get('file_token'):
        return {'ok': True, 'current': APP_VERSION, 'available': False}
    available = _version_tuple(rel['version']) > _version_tuple(APP_VERSION)
    return {
        'ok': True, 'current': APP_VERSION, 'latest': rel['version'],
        'notes': rel.get('notes', ''), 'file_size': rel.get('file_size', 0),
        'available': available, '_rel': rel,
    }


def _download_and_stage(rel: dict) -> Path:
    """下载 zip → 校验 → 解压到 update_tmp/new → 备份当前 exe → 写 update.bat。"""
    import zipfile
    import shutil
    uploader = get_uploader(Path.cwd())
    work = Path.cwd()
    tmp = work / 'update_tmp'
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    zip_path = tmp / 'release.zip'
    logs.log(f"下载新版本 v{rel['version']}（{rel.get('file_size', 0) // 1024 // 1024}MB）...", sticky=True)
    n = uploader.download_release_file(rel['file_token'], zip_path)
    if rel.get('file_size') and n != rel['file_size']:
        raise RuntimeError(f'下载不完整：{n} != {rel["file_size"]} 字节')
    new_dir = tmp / 'new'
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(new_dir)
    # zip 可能带一层顶级目录
    if not (new_dir / 'smarton-backend.exe').exists():
        subs = [d for d in new_dir.iterdir() if d.is_dir()]
        if len(subs) == 1 and (subs[0] / 'smarton-backend.exe').exists():
            new_dir = subs[0]
    if not (new_dir / 'smarton-backend.exe').exists():
        raise RuntimeError('安装包无效：缺 smarton-backend.exe')
    if not (new_dir / 'frontend' / 'dist').exists():
        raise RuntimeError('安装包无效：缺 frontend/dist')
    # 备份当前 exe（bat 替换失败时自动回滚）
    bak = work / 'backup'
    bak.mkdir(exist_ok=True)
    shutil.copy2(work / 'smarton-backend.exe', bak / 'smarton-backend.exe')
    new_rel = str(new_dir.relative_to(work))
    (work / 'update.bat').write_text(_UPDATE_BAT.replace('__NEWREL__', new_rel), encoding='gbk')
    return new_dir


def _launch_updater_and_exit():
    """启动 update.bat（独立进程）后退出自身，由 bat 完成替换并重启。"""
    import subprocess
    import os
    import time as _t
    _t.sleep(1.0)  # 让 HTTP 响应先送达前端
    logs.log('开始应用更新，软件即将自动重启...', 'WARN', sticky=True)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(['cmd', '/c', str(Path.cwd() / 'update.bat')],
                     cwd=str(Path.cwd()), creationflags=flags)
    _t.sleep(0.5)
    os._exit(0)


# ── 气隙研磨计算（转发 ERP 云端算法，产线 FAIL 磁芯自动算研磨建议）──

class GapCalcRequest(BaseModel):
    NNv: list
    params_target: list
    current_Locsc_uH: list
    hg_pri_mm: float
    hg_sec_mm: float
    hg_film_mm: float
    perf_core_pctg_target: Optional[list] = None
    perf_trans_pctg_target: Optional[list] = None


@app.post('/api/gap-calc')
def gap_calc(req: GapCalcRequest):
    """转发到 soaipower.com 的气隙计算服务（算法依赖 scipy/sympy，不适合打进本地 exe）。"""
    import requests as _rq
    payload = req.dict()
    if payload.get('perf_core_pctg_target') is None:
        payload['perf_core_pctg_target'] = [2.5, 2.5, 2.5, 2.5, 0.6, 2.5]
    if payload.get('perf_trans_pctg_target') is None:
        payload['perf_trans_pctg_target'] = [5, 5, 5, 5, 1, 5]
    try:
        r = _rq.post('https://www.soaipower.com/api/hg-calc', json=payload, timeout=(10, 90))
        data = r.json()
    except Exception as e:
        raise HTTPException(502, f'气隙计算服务不可达: {e}')
    if r.status_code != 200:
        raise HTTPException(502, data.get('error') or '气隙计算失败')
    return data


@app.get('/api/update/check')
def update_check():
    r = _check_update()
    r.pop('_rel', None)
    return r


@app.post('/api/update/apply')
def update_apply():
    r = _check_update()
    if not r.get('ok'):
        raise HTTPException(500, r.get('error', '检查更新失败'))
    if not r.get('available'):
        raise HTTPException(400, '已是最新版本，无需更新')
    try:
        _download_and_stage(r['_rel'])
    except Exception as e:
        logs.log(f'更新下载/校验失败: {e}', 'ERROR', sticky=True)
        raise HTTPException(500, f'下载/校验失败: {e}')
    threading.Thread(target=_launch_updater_and_exit, daemon=True).start()
    return {'ok': True, 'message': f"开始更新到 v{r['latest']}，约 30 秒后自动恢复"}


def _auto_update_check_loop():
    """每小时查一次新版本：发现即在日志区提示；config 里 auto_update=true 且仪器空闲时自动更新。"""
    import time as _t
    _t.sleep(60)
    while True:
        try:
            r = _check_update()
            if r.get('available'):
                logs.log(f"发现新版本 v{r['latest']}（当前 v{APP_VERSION}），请在页面顶部点击「立即更新」",
                         'WARN', sticky=True)
                auto = False
                try:
                    auto = bool(json.loads((Path.cwd() / 'config.json').read_text(encoding='utf-8')).get('auto_update'))
                except Exception:
                    auto = False
                if auto and not (state.runner is not None and state.runner._ready):
                    _download_and_stage(r['_rel'])
                    _launch_updater_and_exit()
        except Exception:
            pass
        _t.sleep(3600)


@app.post('/api/deployment/sync-params')
def sync_deployment_params():
    """手动同步参数（前端按钮）。"""
    r = _do_sync_params()
    if not r.get('ok'):
        raise HTTPException(400, r.get('error', '同步失败'))
    return r


# ── 参数自动同步后台线程（每5分钟拉一次，ERP改了自动生效）────
def _auto_param_sync_loop():
    import time as _t
    _t.sleep(25)  # 启动后等一会再开始
    while True:
        try:
            dep = state.get_deployment()
            if dep.get('deployment_id'):
                r = _do_sync_params()
                if r.get('ok') and r.get('updated'):
                    n = len(r['updated'])
                    logs.log(f'自动同步：{n} 个产品参数已更新', sticky=True)
        except Exception:
            pass
        _t.sleep(300)  # 每5分钟


def _start_auto_sync():
    t = threading.Thread(target=_auto_param_sync_loop, daemon=True, name='param-auto-sync')
    t.start()


@app.post('/api/disconnect')
def disconnect():
    """Disconnect active instrument sessions."""
    if state.runner:
        logs.log('??????')
        state.runner.close()
        state.runner = None
        state.current_product = None
    if state.inspection_runner:
        logs.log('????????')
        state.inspection_runner.close()
        state.inspection_runner = None
        state.current_inspection_product = None
    return {'ok': True, 'message': '???'}


@app.post('/api/inspection/initialize')
def initialize_inspection(req: InspectionInitRequest):
    from agent.inspection_runner import InspectionRunner

    product_path = state.get_products_dir() / f'{req.product_code}.json'
    if not product_path.exists():
        raise HTTPException(404, f'product config not found: {req.product_code}')

    logs.start_session(req.product_code, 'inspection_initialize')
    logs.log(f'inspection initialize request: product={req.product_code} port={req.port}')

    if state.inspection_runner:
        state.inspection_runner.close()
        state.inspection_runner = None
        state.current_inspection_product = None
    if state.runner:
        state.runner.close()
        state.runner = None
        state.current_product = None

    runner = InspectionRunner(str(product_path), logger=logs.log)
    status = runner.initialize(port=req.port, baudrate=state.get_baudrate())
    if status['ok']:
        state.inspection_runner = runner
        state.current_inspection_product = req.product_code
        state.save_port(req.port)
    else:
        runner.close()
    return status


@app.get('/api/inspection/status')
def get_inspection_status():
    if not state.inspection_runner:
        return {
            'ready': False,
            'product_code': state.current_inspection_product,
            'port': state.get_port(),
            'workflow_type': 'incoming_inspection',
            'current_step_index': 0,
            'total_steps': 0,
            'next_prompt': '',
            'completed_steps': 0,
        }
    status = state.inspection_runner.status()
    status['port'] = state.get_port()
    return status


@app.post('/api/inspection/run-step')
def run_inspection_step():
    if not state.inspection_runner:
        raise HTTPException(400, 'inspection runner is not initialized')
    try:
        result = state.inspection_runner.run_current_step()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc

    payload = dict(result)
    if payload.get('finished'):
        record = state.inspection_runner.build_record()
        csv_file = save_inspection(record, state.get_results_dir())
        payload['csv_file'] = csv_file
        logs.log(f'inspection completed: {record.overall}, saved to {csv_file}')
    return payload


class PatchRecordNumberRequest(BaseModel):
    csv_file: str
    record_number: str


@app.post('/api/test/patch-record-number')
def patch_record_number(req: PatchRecordNumberRequest):
    """异步补写飞书序号到CSV最后一行（飞书表里只推 serial_code，序号在飞书侧自行通过关联字段拉取）"""
    import csv as csvmod
    p = Path(req.csv_file)
    if not p.exists():
        raise HTTPException(404, f'CSV文件不存在: {req.csv_file}')
    try:
        with open(p, 'r', newline='', encoding='utf-8-sig') as f:
            rows = list(csvmod.reader(f))
        if len(rows) > 3:
            # 序号在第3列（index 2）
            rows[-1][2] = req.record_number
            with open(p, 'w', newline='', encoding='utf-8-sig') as f:
                csvmod.writer(f).writerows(rows)
        return {'ok': True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/feishu/record-number')
def get_feishu_record_number(url: str):
    """从飞书记录二维码链接获取序号"""
    import requests as req
    import re
    try:
        r = req.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        match = re.search(
            r'window\.SERVER_DATA\.shareRecord\s*=\s*Object\((\{.*?\})\);',
            r.text, re.DOTALL
        )
        if not match:
            return {'ok': False, 'record_number': None, 'message': '未找到记录数据'}
        data = json.loads(match.group(1))
        record_share = json.loads(data.get('RecordShare', '{}'))
        record_data = record_share.get('recordData', {})
        primary_key = record_share.get('primaryKey')
        value = record_data.get(primary_key, {}).get('value')
        # value 是列表如 [{"number": "2602N0118", "sequence": "118"}]
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
            record_number = value[0].get('number', value[0].get('sequence', str(value[0])))
        else:
            record_number = str(value) if value is not None else None
        return {'ok': True, 'record_number': record_number}
    except Exception as e:
        return {'ok': False, 'record_number': None, 'message': str(e)}


@app.get('/api/logs')
def get_logs(since: int = 0):
    """获取运行日志（增量）"""
    return logs.get_since(since)


# ── 历史结果 ─────────────────────────────────────────────────────

@app.get('/api/results')
def list_results():
    """列出所有结果CSV文件"""
    results_dir = state.get_results_dir()
    files = []
    for f in sorted(results_dir.glob('*.csv'), reverse=True):
        files.append({
            'filename': f.name,
            'size': f.stat().st_size,
            'modified': f.stat().st_mtime
        })
    return files


# Frontend static files (for packaged/offline run)
def _find_frontend_dist() -> Path | None:
    candidates = []

    # Source mode
    candidates.append(Path(__file__).resolve().parent.parent / 'frontend' / 'dist')
    # Run from release folder
    candidates.append(Path.cwd() / 'frontend' / 'dist')

    # PyInstaller onefile mode: prefer exe folder
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / 'frontend' / 'dist')

    for p in candidates:
        if p.exists() and (p / 'index.html').exists():
            return p
    return None


frontend_dist = _find_frontend_dist()
if frontend_dist:
    app.mount('/', StaticFiles(directory=str(frontend_dist), html=True), name='frontend')


# ── 启动入口 ─────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
