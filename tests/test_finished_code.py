"""成品码识别 parse_finished_code（规格 §1）。"""
import string

import pytest

from backend.finished_code import DAMM, LETTERS, check_digit, is_valid, parse_finished_code

GOOD = '26HK04426'
ALPHABET = string.digits + string.ascii_uppercase


def test_tables_match_spec():
    assert LETTERS == 'ACFHKLRTWY'
    assert DAMM == [
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


def _reference_check_digit(body: str) -> int:
    # 按规格文字独立再算一遍：i = DAMM[i][d]，第 3、4 位 d 是字母下标
    i = 0
    for pos, ch in enumerate(body):
        d = LETTERS.index(ch) if pos in (2, 3) else int(ch)
        i = DAMM[i][d]
    return i


def test_known_good_code():
    assert check_digit(GOOD[:8]) == 6 == _reference_check_digit(GOOD[:8])
    assert is_valid(GOOD)
    assert parse_finished_code(GOOD) == GOOD


@pytest.mark.parametrize('body', ['26HK0442', '00AA0000', '99YY9999', '27LT1234', '30CW0001'])
def test_check_digit_matches_reference(body):
    assert check_digit(body) == _reference_check_digit(body)
    code = body + str(check_digit(body))
    assert is_valid(code)
    assert parse_finished_code(code) == code


@pytest.mark.parametrize('bad', ['26HK044', '26BK0442', 'AAHK0442', '26HK044X', '', None])
def test_check_digit_rejects_bad_body(bad):
    with pytest.raises(ValueError):
        check_digit(bad)


def test_every_single_char_substitution_invalid():
    n = 0
    for pos in range(len(GOOD)):
        for ch in ALPHABET:
            if ch == GOOD[pos]:
                continue
            mutated = GOOD[:pos] + ch + GOOD[pos + 1:]
            assert parse_finished_code(mutated) is None, mutated
            assert parse_finished_code('https://www.soaipower.com/t/' + mutated) is None, mutated
            assert not is_valid(mutated)
            n += 1
    assert n == 9 * 35


def test_every_adjacent_transposition_invalid():
    n = 0
    for pos in range(len(GOOD) - 1):
        a, b = GOOD[pos], GOOD[pos + 1]
        if a == b:
            continue
        mutated = GOOD[:pos] + b + a + GOOD[pos + 2:]
        assert parse_finished_code(mutated) is None, mutated
        assert not is_valid(mutated)
        n += 1
    assert n == 7   # 26HK04426 里只有 "44" 相同


@pytest.mark.parametrize('text', [
    '26HK04426',
    '26hk04426',
    '26Hk04426',
    '  26HK04426\r\n',
    '\t26hk04426 ',
    'https://www.soaipower.com/t/26HK04426',
    'https://www.soaipower.com/t/26HK04426/',
    'http://www.soaipower.com/t/26HK04426',
    'http://soaipower.com/t/26HK04426',
    'https://soaipower.com/t/26HK04426/',
    'https://WWW.SOAIPOWER.COM/t/26HK04426',
    'https://www.SoaiPower.com/t/26hk04426/',
    'HTTPS://WWW.SOAIPOWER.COM/T/26HK04426',
    '  https://www.soaipower.com/t/26hk04426  \n',
])
def test_accepted_forms(text):
    assert parse_finished_code(text) == GOOD


@pytest.mark.parametrize('text', [
    # 旧码 / 飞书
    '260YN0062',
    '2602N0186',
    'RqK8bW3xYtZ2mN7pLc4VdF9sHjA',                       # 27 位飞书 token
    'https://smartonep.feishu.cn/record/RqK8bW3xYtZ2mN7pLc4VdF9sHjA',
    'https://smartonep.feishu.cn/record/26HK04426',
    # 校验位错 / 格式错
    '26HK04427',
    '26HK0442',
    '26HK044266',
    '26HB04426',
    '2HHK04426',
    # 链接不对
    'https://www.soaipower.com/t/26HK04427',
    'https://www.soaipower.com/t/26HK04426//',
    'https://www.soaipower.com/t/26HK04426?x=1',
    'https://www.soaipower.com/t/26HK04426#a',
    'https://evil.com/t/26HK04426',
    'https://soaipower.com.evil.com/t/26HK04426',
    'https://www.soaipower.com/x/26HK04426',
    'https://www.soaipower.com/t/',
    'ftp://www.soaipower.com/t/26HK04426',
    'www.soaipower.com/t/26HK04426',
    'https://m.soaipower.com/t/26HK04426',
    'https://www.soaipower.com:443/t/26HK04426',
    '26HK 04426',
    '26HK04426\n26HK04426',
    '２６HK04426',                                        # 全角数字
    '',
    '   ',
])
def test_rejected_forms(text):
    assert parse_finished_code(text) is None


# 前端 finishedCode.ts 用 String.prototype.trim()，去掉的正是这些字符（ECMAScript WhiteSpace + LineTerminator，
# 用 node 对 U+0000–U+FFFF 逐个核对过）。Python 的 str.strip() 还会去 \x1c-\x1f、\x85，却不去 \ufeff，两边会判得不一样
JS_TRIM_CHARS = ('\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008'
                 '\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')


def test_trim_set_is_exactly_js_trim():
    stripped = [chr(c) for c in range(0x10000)
                if parse_finished_code(chr(c) + GOOD + chr(c)) == GOOD]
    assert ''.join(stripped) == JS_TRIM_CHARS


@pytest.mark.parametrize('ch', ['\x1c', '\x1d', '\x1e', '\x1f', '\x85', '\u200b', '\x00'])
def test_non_js_whitespace_not_trimmed(ch):
    assert parse_finished_code(GOOD + ch) is None
    assert parse_finished_code(ch + 'https://www.soaipower.com/t/' + GOOD) is None


@pytest.mark.parametrize('text', ['\ufeff26HK04426', '\ufeffhttps://www.soaipower.com/t/26HK04426\u3000',
                                  '\xa026hk04426\u2028'])
def test_js_whitespace_trimmed(text):
    assert parse_finished_code(text) == GOOD


@pytest.mark.parametrize('value', [None, 26, 26.0, b'26HK04426', ['26HK04426'], True])
def test_non_string_returns_none(value):
    assert parse_finished_code(value) is None
