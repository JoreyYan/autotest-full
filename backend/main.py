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

from . import state
from . import logs
from .csv_writer import save

app = FastAPI(title='变压器测试系统', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


# ── 请求/响应模型 ────────────────────────────────────────────────

class InitRequest(BaseModel):
    product_code: str
    port: Optional[str] = None   # 不填则自动扫描


class TestResult(BaseModel):
    ok: bool
    timestamp: str
    product_code: str
    overall: str
    passed: int
    failed: int
    items: list[dict]
    csv_file: str


# ── 产品管理 ─────────────────────────────────────────────────────

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
                'instrument_config_id': data['instrument_config_id'],
                'test_items_count': len(data.get('test_items', [])),
                'description': data.get('description', '')
            })
        except Exception:
            pass
    return result


@app.get('/api/products/{product_code}')
def get_product(product_code: str):
    """获取指定产品配置详情"""
    p = state.get_products_dir() / f'{product_code}.json'
    if not p.exists():
        raise HTTPException(404, f'产品 {product_code} 不存在')
    return json.loads(p.read_text(encoding='utf-8'))


class ProductBody(BaseModel):
    product_code: str
    product_name: str
    instrument_config_id: int
    description: str = ''
    test_items: list[dict] = []
    enable_eq_n: bool = False
    eq_n_vars: dict = Field(default_factory=lambda: {'l_raw': 'A', 'lk_raw': 'B', 'l_aux': 'C'})


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
def run_test():
    """
    执行一次测试，返回结果并保存CSV
    必须先 POST /api/initialize 成功
    """
    if not state.runner or not state.runner._ready:
        raise HTTPException(400, '仪器未初始化，请先调用 /api/initialize')

    logs.log('开始测试')
    record = state.runner.run()
    if record is None:
        logs.log('测试失败：仪器无响应')
        raise HTTPException(500, '测试失败：仪器无响应')

    # 保存CSV
    csv_file = save(record, state.get_results_dir())
    logs.log(f'测试完成：{record.overall}，结果保存 {csv_file}')

    return TestResult(
        ok=True,
        timestamp=record.timestamp,
        product_code=record.product_code,
        overall=record.overall,
        passed=record.passed,
        failed=record.failed,
        items=record.items,
        csv_file=csv_file
    )


@app.post('/api/disconnect')
def disconnect():
    """断开仪器连接"""
    if state.runner:
        logs.log('断开连接')
        state.runner.close()
        state.runner = None
        state.current_product = None
    return {'ok': True, 'message': '已断开'}


# ── 运行日志 ─────────────────────────────────────────────────

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


# ── 启动入口 ─────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
