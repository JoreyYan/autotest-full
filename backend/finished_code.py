"""
finished_code.py — 成品码（铝壳镭射二维码）识别

号码规则与 SOAI「明码编号规范」逐位一致：
  9 位 = 年 2 位数字 + 代次 2 个字母 + 流水 4 位数字 + Damm 校验 1 位数字，例如 26HK04426
  二维码内容：https://www.soaipower.com/t/<9位码>

字母表和 Damm 表必须与 SOAI 的 serialCode.ts / ww_order_api.py 相同，要改几边一起改。
前端 src/lib/finishedCode.ts 的 parseFinishedCode 与这里的 parse_finished_code 行为相同。
"""
from __future__ import annotations

import re
from typing import Optional

# 代次可用字母，按此顺序映射为 0-9 参与校验
LETTERS = 'ACFHKLRTWY'

# Damm 算法准乘表
DAMM = [
    [0, 3, 1, 7, 5, 9, 8, 6, 4, 2],
    [7, 0, 9, 2, 1, 5, 4, 8, 6, 3],
    [4, 2, 0, 6, 8, 7, 1, 3, 5, 9],
    [1, 7, 5, 0, 9, 8, 3, 4, 2, 6],
    [6, 1, 2, 3, 0, 4, 5, 9, 7, 8],
    [3, 6, 7, 4, 2, 0, 9, 5, 8, 1],
    [5, 8, 6, 9, 7, 2, 0, 1, 3, 4],
    [8, 9, 4, 5, 3, 6, 2, 0, 1, 7],
    [9, 4, 3, 8, 6, 1, 7, 2, 0, 5],
    [2, 5, 8, 1, 4, 3, 6, 7, 9, 0],
]

# 二维码链接（主机不区分大小写；re.ASCII 防止 Unicode 大小写折叠把非 ASCII 字符当字母）
_URL_RE = re.compile(r'https?://(www\.)?soaipower\.com/t/([0-9A-Za-z]{9})/?',
                     re.IGNORECASE | re.ASCII)
_ALNUM9_RE = re.compile(r'[0-9A-Za-z]{9}', re.ASCII)
_CODE_RE = re.compile(r'[0-9]{2}[ACFHKLRTWY]{2}[0-9]{5}', re.ASCII)
_BODY_RE = re.compile(r'[0-9]{2}[ACFHKLRTWY]{2}[0-9]{4}', re.ASCII)

# 首尾去掉的空白：与前端 String.prototype.trim() 去掉的字符完全相同（ECMAScript WhiteSpace + LineTerminator）。
# 不用 str.strip()：它还会去 \x1c-\x1f、\x85，却不去 \ufeff，同一段扫码文字前后端会判得不一样
_TRIM_CHARS = ('\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008'
               '\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')


def check_digit(body: str) -> int:
    """前 8 位算校验位；第 3、4 位是代次字母，按 LETTERS 位序换成 0-9。
    body 格式不对时抛 ValueError。"""
    if not isinstance(body, str) or not _BODY_RE.fullmatch(body):
        raise ValueError(f'成品码前 8 位格式不对: {body!r}')
    i = 0
    for pos, ch in enumerate(body):
        d = LETTERS.index(ch) if pos in (2, 3) else int(ch)
        i = DAMM[i][d]
    return i


def is_valid(code: str) -> bool:
    """9 位大写成品码：格式对且校验位正确。"""
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        return False
    return check_digit(code[:8]) == int(code[8])


def parse_finished_code(text) -> Optional[str]:
    """从扫码/手填文字里识别成品码，是则返回 9 位大写码，否则 None。
    接受：成品码二维码链接（http/https、带不带 www、结尾斜杠可有可无）或裸 9 位码（大小写均可）。
    旧码（260YN0062 / 2602N0186 这类序号、飞书 token、飞书 /record/ 链接）一律 None。"""
    if not isinstance(text, str):
        return None
    s = text.strip(_TRIM_CHARS)
    if not s:
        return None
    m = _URL_RE.fullmatch(s)
    if m:
        cand = m.group(2)
    elif _ALNUM9_RE.fullmatch(s):
        cand = s
    else:
        return None
    cand = cand.upper()
    return cand if is_valid(cand) else None
