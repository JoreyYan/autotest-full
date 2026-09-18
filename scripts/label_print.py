# -*- coding: utf-8 -*-
"""成品码标签打印（二维码 + 序号）—— 必须 TSPL 直通，不能走 Windows 驱动。

机器：Windows 打印队列名 `EZSCAN E75`（端口 USB002，203 dpi），实际机器是 **APRT 芝润**
（USB 设备名 `AY AY-D33`）。队列名和机器对不上：走驱动打印（GDI / PrintDocument / 自定义纸张）
时，驱动吐出来的指令打印机不认，会把指令当文字打出来——乱码而且不停走纸，只能清队列并给打印机
断电才停。2026-09-16、09-17 各踩过一次。

可用的办法只有一个：把整张标签渲染成位图，用 TSPL 指令 RAW 直发。标签尺寸由 `SIZE` 指令决定，
不受驱动预置纸张限制。详见 doc/标签打印机.md。

依赖：pywin32、Pillow、reportlab（二维码用 reportlab 自带的 qrencoder 画，本机没有 qrcode/segno）。
系统 Python 3.11 里都有；miniforge 的 autotest 环境缺 reportlab。

用法::

    python scripts/label_print.py 26 AA 1 1              # 只渲染预览，不打印
    python scripts/label_print.py 26 AA 1 1 --print      # 渲染并打印 1 张
    python scripts/label_print.py 26 AA 1 10 --print     # 连号打 10 张
    python scripts/label_print.py 26 AA 1 1 --print --w 45 --h 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics.barcode.qr import QrCodeWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.finished_code import check_digit          # noqa: E402  校验位与工位、SOAI 同一套

PRINTER = 'EZSCAN E75'          # Windows 队列名；机器实为 APRT 芝润
DPI = 203                       # 热敏头分辨率
MM = DPI / 25.4
URL_PREFIX = 'https://www.soaipower.com/t/'
FONTS = ('arialbd.ttf', 'arial.ttf', 'msyhbd.ttc', 'consolab.ttf')


def make_code(year: str, gen: str, seq: int) -> str:
    """年 2 位 + 代次 2 字母 + 流水 4 位 + Damm 校验 1 位，例如 26AA00019。"""
    body = f'{year}{gen}{seq:04d}'
    return f'{body}{check_digit(body)}'          # check_digit 返回 int


def qr_image(text: str, px: int) -> Image.Image:
    """按模块整数倍作图，避免缩放糊边导致扫不出。返回黑白正方形图。"""
    w = QrCodeWidget(text)
    w.qr.make()
    modules, n = w.qr.modules, w.qr.getModuleCount()
    quiet = 4                                              # 静区，少于 4 格扫码枪易失败
    scale = max(1, px // (n + quiet * 2))
    size = (n + quiet * 2) * scale
    img = Image.new('1', (size, size), 1)
    d = ImageDraw.Draw(img)
    for y in range(n):
        for x in range(n):
            if modules[y][x]:
                x0, y0 = (x + quiet) * scale, (y + quiet) * scale
                d.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=0)
    return img


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def label(code: str, w_mm: float = 72.0, h_mm: float = 130.0, prefix: str = URL_PREFIX) -> Image.Image:
    """竖版标签：二维码在上、序号在下。标签上只印序号，不印网址（业主 2026-09-17 确认）。"""
    W, H = int(w_mm * MM), int(h_mm * MM)
    img = Image.new('1', (W, H), 1)
    d = ImageDraw.Draw(img)
    pad = int(5 * MM)
    f_code = _font(int(12 * MM))
    box = d.textbbox((0, 0), code, font=f_code)
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    qr = qr_image(prefix + code, min(W - 2 * pad, H - 2 * pad - text_h - int(6 * MM)))
    img.paste(qr, ((W - qr.size[0]) // 2, pad))
    d.text(((W - text_w) // 2 - box[0], pad + qr.size[1] + int(4 * MM) - box[1]), code, font=f_code, fill=0)
    return img


def bitmap_bytes(img: Image.Image) -> tuple[int, int, bytes]:
    """TSPL BITMAP 数据：每行按字节对齐（右侧补白），位 0 = 打黑点，位 1 = 不打。"""
    img = img.convert('1')
    w_bytes = (img.width + 7) // 8
    padded = Image.new('1', (w_bytes * 8, img.height), 1)
    padded.paste(img, (0, 0))
    px = padded.load()
    out = bytearray()
    for y in range(padded.height):
        for bx in range(w_bytes):
            b = 0
            for bit in range(8):
                b = (b << 1) | (0 if px[bx * 8 + bit, y] == 0 else 1)
            out.append(b)
    return w_bytes, padded.height, bytes(out)


def tspl_job(img: Image.Image, w_mm: float, h_mm: float) -> bytes:
    """一张标签的完整 TSPL 作业。PRINT 1,1 = 打一张，绝不多走纸。"""
    w_bytes, rows, data = bitmap_bytes(img)
    head = (f'SIZE {w_mm:g} mm,{h_mm:g} mm\r\n'
            'GAP 2 mm,0 mm\r\n'
            'DIRECTION 1\r\n'
            'DENSITY 10\r\n'
            'SPEED 4\r\n'
            'CLS\r\n'
            f'BITMAP 0,0,{w_bytes},{rows},0,').encode('ascii')
    return head + data + b'\r\nPRINT 1,1\r\n'


def send_raw(data: bytes, title: str, printer: str = PRINTER) -> None:
    """RAW 直发：绕开驱动的渲染，打印机直接解释 TSPL 指令。"""
    import win32print                                      # 只在真打印时才需要 pywin32
    h = win32print.OpenPrinter(printer)
    try:
        win32print.StartDocPrinter(h, 1, (title, None, 'RAW'))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


def main() -> None:
    ap = argparse.ArgumentParser(description='成品码标签打印（TSPL 直通）')
    ap.add_argument('year', help='年份 2 位，如 26')
    ap.add_argument('gen', help='代次 2 个字母，如 AA（字母表 ACFHKLRTWY）')
    ap.add_argument('start', type=int, help='起始流水号')
    ap.add_argument('count', type=int, help='张数')
    ap.add_argument('--w', type=float, default=72.0, help='标签宽 mm（默认 72）')
    ap.add_argument('--h', type=float, default=130.0, help='标签高 mm（默认 130）')
    ap.add_argument('--printer', default=PRINTER)
    ap.add_argument('--prefix', default=URL_PREFIX, help='二维码里的网址前缀')
    ap.add_argument('--out', default='', help='预览图输出目录（默认不存盘）')
    ap.add_argument('--print', dest='do', action='store_true', help='真的打印；不给这个参数只渲染')
    a = ap.parse_args()

    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    for i in range(a.count):
        code = make_code(a.year, a.gen, a.start + i)
        img = label(code, a.w, a.h, a.prefix)
        if out:
            img.save(out / f'{code}.png', dpi=(DPI, DPI))
        job = tspl_job(img, a.w, a.h)
        print(f'{code}  {img.width}x{img.height}px = {a.w:g}x{a.h:g}mm  作业 {len(job)} 字节'
              + ('' if a.do else '（未打印）'))
        if a.do:
            send_raw(job, f'label-{code}', a.printer)
            print(f'  已 RAW 发送到 {a.printer}')


if __name__ == '__main__':
    main()
