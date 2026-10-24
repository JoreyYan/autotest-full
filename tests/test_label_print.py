# -*- coding: utf-8 -*-
"""成品码标签：号码、位图打包、TSPL 作业。不连打印机、不发任何数据。"""
import sys
from pathlib import Path

import pytest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import label_print as lp                                   # noqa: E402


def test_code_matches_scheme_and_check_digit():
    assert lp.make_code('26', 'AA', 1) == '26AA00019'       # 实机打过的第一张
    assert lp.make_code('26', 'HK', 442) == '26HK04426'     # 规范文档里的样例
    assert len(lp.make_code('26', 'AA', 9999)) == 9


def test_bitmap_never_wider_than_the_label_and_black_is_zero_bit():
    # 关键不变量：每行宽度向下取 8 的倍数。多出 1 个点打印机就会折到下一行，
    # 整张图逐行错位，二维码打成横条纹（实测 70mm 标签发 560 点宽就是这样）。
    img = Image.new('1', (9, 2), 1)                         # 9 像素宽 → 只发 1 字节，不补成 2
    img.putpixel((0, 0), 0)                                 # 左上角一个黑点
    w_bytes, rows, data = lp.bitmap_bytes(img)
    assert (w_bytes, rows, len(data)) == (1, 2, 2)
    assert data[0] == 0b01111111                            # 黑点那一位是 0
    assert data[1] == 0xFF


@pytest.mark.parametrize('w_mm', [45.0, 50.0, 70.0, 72.0, 100.0])
def test_bitmap_width_fits_the_label_at_every_size(w_mm):
    img = lp.label('26AA00019', w_mm, 30.0)
    w_bytes, _, _ = lp.bitmap_bytes(img)
    assert w_bytes * 8 <= int(w_mm * lp.MM)                 # 绝不超过标签宽度
    assert int(w_mm * lp.MM) - w_bytes * 8 < 8              # 也不白白浪费一整字节


def test_tspl_job_prints_exactly_one_label():
    img = lp.label('26AA00019', 72.0, 130.0)
    job = lp.tspl_job(img, 72.0, 130.0)
    head = job[:120].decode('ascii', 'ignore')
    assert 'SIZE 72 mm,130 mm' in head and 'GAP 2 mm,0 mm' in head and 'CLS' in head
    assert job.endswith(b'\r\nPRINT 1,1\r\n')               # 只打一张，不会连续走纸
    assert b'BITMAP 0,0,71,' in job                         # 71 字节 = 568 点 ≤ 72mm@203dpi(575 点)


def test_label_size_matches_millimetres_at_printer_dpi():
    img = lp.label('26AA00019', 45.0, 30.0)
    assert img.width % 8 == 0 and img.width <= int(45 * lp.MM)
    assert img.height == int(30 * lp.MM)
    assert abs(img.width / lp.DPI * 25.4 - 45) < 1.0


def test_qr_encodes_full_url_with_quiet_zone():
    qr = lp.qr_image(lp.URL_PREFIX + '26AA00019', 400)
    assert qr.width == qr.height and qr.width <= 400
    assert qr.getpixel((0, 0)) == 1                         # 静区留白
    assert qr.convert('L').getextrema()[0] == 0             # 有黑模块
