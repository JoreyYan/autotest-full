"""
config_checker.py — 配置比对层
规则：JSON 里要求的测试项，仪器必须全有；仪器多测的无所谓。
输入：初始化 *TRG 返回的 CSV 文本 + 产品 JSON 配置
输出：比对报告
"""
from dataclasses import dataclass


@dataclass
class CheckResult:
    ok: bool
    missing: list[str]   # JSON要求但仪器没有的
    extra: list[str]     # 仪器多测了但JSON没要求的（不影响结果）
    message: str


def parse_csv(csv_text: str) -> set[str]:
    """
    从 CSV 文本提取 {类型_引脚} 集合。
    例如 '1,Turn,'3-1,...' → 'Turn_3-1'
    """
    items = set()
    for seg in csv_text.split(';'):
        seg = seg.strip().lstrip('!')
        parts = seg.split(',')
        if len(parts) >= 3:
            test_type = parts[1].strip()
            pins      = parts[2].strip().lstrip("'")
            if test_type and pins:
                items.add(f'{test_type}_{pins}')
    return items


def check(csv_text: str, product_config: dict) -> CheckResult:
    """
    比对仪器实测项 vs JSON 期望项。
    product_config 格式与 ZZ-T250005A.json 一致。
    """
    # 从 CSV 提取仪器实际测了什么
    instr_items = parse_csv(csv_text)

    # 从 JSON 提取期望的测试项
    json_items = set()
    for item in product_config.get('test_items', []):
        t = item.get('test_type', '').strip()
        p = item.get('pins', '').strip()
        if t and p:
            json_items.add(f'{t}_{p}')

    # 比对
    missing = sorted(json_items - instr_items)   # JSON有，仪器没有 → 不行
    extra   = sorted(instr_items - json_items)   # 仪器多测了 → 没关系

    ok = len(missing) == 0

    if ok:
        msg = f'配置验证通过：仪器覆盖全部 {len(json_items)} 个测试项'
        if extra:
            msg += f'（另有 {len(extra)} 项仪器多测，不影响）'
    else:
        msg = f'配置验证失败：以下 {len(missing)} 项 JSON 要求但仪器未返回：{missing}'

    return CheckResult(ok=ok, missing=missing, extra=extra, message=msg)
