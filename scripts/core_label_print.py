# -*- coding: utf-8 -*-
"""磁芯测试数据标签（原型，还没接入工位软件）—— 热敏标签机 TSPL 直通打印。

一张小标签上印：公司/产线/工位、磁芯号（大字）+ 合格判定、产品、测试时间、二维码，
以及这颗磁芯的全部测试值（Turn / Lx / Lk / Q / Cx / Dcr / 等效n）。目标是贴在磁芯上。

来历：2026-09-11 业主在本机试做，比较过 45×30、40×26、35×22 三种尺寸，最后想用 45×30。
原型只存在于会话临时目录、后来被清掉；2026-10-24 从会话记录原样还原后整理成这个脚本。
交接说明（现状、待定事项、下一步）见 doc/磁芯标签.md；打印机为什么不能走驱动见 doc/标签打印机.md。

驱动打印机的部分（二维码位图、位图打包、TSPL 作业、RAW 发送）直接用 label_print.py 里
已经实测过的函数，这里只管排版。

依赖：Pillow、reportlab、pywin32（只在真打印时用）。系统 Python 3.11 和 miniforge 的
autotest 环境都有。

用法（数据取工位软件 results/ 目录下的测试 CSV）::

    python scripts/core_label_print.py <测试CSV>                     # 取最后一条合格记录，出 45×30 预览图，不打印
    python scripts/core_label_print.py <测试CSV> --core 8888         # 指定磁芯号（取它最后一条记录）
    python scripts/core_label_print.py <测试CSV> --samples           # 三种尺寸对比样张，画在 70×130 纸上
    python scripts/core_label_print.py <测试CSV> --print             # 真打印：标签画在当前 70×130 卷纸上，带裁切框
    python scripts/core_label_print.py <测试CSV> --size 45x30 --paper 45x30 --print   # 换成 45×30 卷纸后直接打
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import label_print as lp                                   # noqa: E402  驱动打印机的部分复用这里

SAMPLE_SIZES = [(45, 30), (40, 26), (35, 22)]               # 2026-09-11 比过的三种尺寸
DEFAULT_SIZE = (45, 30)                                     # 业主最后想用的尺寸
DEFAULT_PAPER = (70, 130)                                   # 本机现在装的卷纸（见 doc/标签打印机.md）
QR_PREFIX = 'soaipower.com/t/'                             # 原型的二维码内容 = 前缀 + 磁芯号（待定，见交接说明）
QR_QUIET = 2                                                # 二维码静区格数，理由见 core_label()
BOLD = r'C:\Windows\Fonts\msyhbd.ttc'                      # 微软雅黑：中文工位名、产品名要能显示
REG = r'C:\Windows\Fonts\msyh.ttc'
_META = ('类型', '序列码', '序号', '磁芯编号', '产品', '产品结果')


def mm(v: float) -> int:
    return int(v * lp.MM)


def font(path: str, size: float) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, max(7, int(size)))
    except OSError:                                         # 没有微软雅黑时退回 label_print 的字体
        return lp._font(max(7, int(size)))


def fmt(v: str, digits: int = 4) -> str:
    try:
        return f'{float(v):.{digits}g}'
    except (TypeError, ValueError):
        return v or '-'


def short_key(k: str) -> str:
    """CSV 列名 → 标签上的短名：Lk_6-5(uH) → Lk6-5，等效n → n"""
    return 'n' if k == '等效n' else k.split('(')[0].replace('_', '')


# ── 数据 ────────────────────────────────────────────────────────────

def read_record(csv_path: str | Path, core: str | None = None) -> tuple[dict, list[tuple[str, str]]]:
    """读工位测试 CSV（第 1 行表头，第 2、3 行上下限，第 4 行起是记录）。
    指定 core 时取该磁芯号的最后一条；否则取最后一条合格（PASS）记录，没有合格的就取最后一条。
    返回 (记录, [(短名, 数值文本), ...])，测试项按 CSV 列顺序。"""
    with open(csv_path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if len(rows) < 4:
        raise ValueError(f'{csv_path} 里没有测试记录')
    head = rows[0]
    recs = [dict(zip(head, r)) for r in rows[3:] if any(c.strip() for c in r)]
    if core is not None:
        hit = [r for r in recs if (r.get('磁芯编号') or '').strip() == str(core).strip()]
        if not hit:
            raise ValueError(f'{csv_path} 里没有磁芯号 {core} 的记录')
        rec = hit[-1]
    else:
        passed = [r for r in recs if (r.get('产品结果') or '').upper() == 'PASS']
        rec = (passed or recs)[-1]
    items = [(short_key(k), fmt(rec[k])) for k in head
             if k not in _META and ('_' in k or k == '等效n') and (rec.get(k) or '').strip()]
    return rec, items


def station_text(config: str | Path | None = None, override: str | None = None) -> str:
    """标签顶部的 公司/产线/工位：命令行给了就用；否则读工位软件的 config.json。"""
    if override:
        return override
    p = Path(config) if config else Path('config.json')
    if p.exists():
        cfg = json.loads(p.read_text(encoding='utf-8'))
        parts = [cfg.get(k) or '' for k in ('company', 'line', 'station')]
        if any(parts):
            return '/'.join(parts)
    return ''


# ── 排版（2026-09-11 原型最终版的布局） ─────────────────────────────

def core_label(rec: dict, items: list[tuple[str, str]], station: str,
               w_mm: float = DEFAULT_SIZE[0], h_mm: float = DEFAULT_SIZE[1],
               qr_prefix: str = QR_PREFIX) -> Image.Image:
    """一张磁芯标签（灰度图，白底黑字）。宽度取 8 的整数倍且不超过标签宽，理由见 lp.bitmap_bytes。"""
    W, H = mm(w_mm) // 8 * 8, mm(h_mm)
    img = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(img)
    core = (rec.get('磁芯编号') or '').strip() or '-'
    result = (rec.get('产品结果') or '').strip().upper()
    pad = max(2, int(W * 0.018))
    g = max(1, int(H * 0.006))                              # 极小间距：小标签上不留死白

    # ① 工位条：满宽黑底白字，紧贴顶部
    bar = max(mm(2.3), int(H * 0.11))
    d.rectangle([0, 0, W, bar], fill=0)
    if station:
        fb = font(BOLD, bar * 0.84)
        while d.textlength(station, font=fb) > W - 2 * pad and fb.size > 8:
            fb = font(BOLD, fb.size - 1)
        d.text((pad, -bar * 0.06), station, font=fb, fill=255)
    y0 = bar + g

    # ② 二维码在右上；左边是磁芯号 + 判定、产品、测试时间
    qs = min(int(H * 0.40), int(W * 0.30))
    # 按模块整数倍作图、不缩放，扫码不糊。静区只留 2 格：45×30 上留 4 格每格只剩 2 个点，太小难扫；
    # 二维码四周本来就有留白（上方隔着 g 和静区才是黑色工位条）
    qr = lp.qr_image(qr_prefix + core, qs, quiet=QR_QUIET).convert('L')
    img.paste(qr, (W - pad - qs + (qs - qr.width) // 2, y0 + (qs - qr.height) // 2))

    lw = W - qs - 2 * pad - g                               # 左侧可用宽
    cs = int(qs * 0.46)
    fc = font(BOLD, cs)
    while d.textlength(core, font=fc) > lw * 0.60 and cs > 9:
        cs -= 1
        fc = font(BOLD, cs)
    d.text((pad, y0 - cs * 0.10), core, font=fc, fill=0)
    if result:
        rs = int(cs * 0.62)
        fr = font(BOLD, rs)
        rx = pad + d.textlength(core, font=fc) + g * 2
        ry = y0 + int(cs * 0.22)
        ok = result == 'PASS'
        d.rectangle([rx, ry, min(rx + d.textlength(result, font=fr) + 5, pad + lw), ry + rs * 1.3],
                    fill=0 if ok else 255, outline=0, width=2)    # 合格黑底白字，不合格白底黑框
        d.text((rx + 2, ry - rs * 0.14), result, font=fr, fill=255 if ok else 0)
    ss = int(qs * 0.21)
    fs = font(REG, ss)
    prod = rec.get('产品') or ''
    while d.textlength(prod, font=fs) > lw and ss > 6:
        ss -= 1
        fs = font(REG, ss)
    y2 = y0 + int(cs * 1.08)
    d.text((pad, y2), prod, font=fs, fill=0)
    d.text((pad, y2 + ss * 1.25), (rec.get('类型') or '')[:16], font=font(REG, ss * 0.92), fill=0)  # 「类型」列存的是测试时间

    y = y0 + qs + g
    d.line([pad, y, W - pad, y], fill=0, width=1)
    y += g

    # ③ 测试值 3 列：列宽按各列实际内容取，字号自适应撑满剩余高度
    if items:
        cols = 3
        rows_n = (len(items) + cols - 1) // cols
        row_h = (H - y - pad) / rows_n
        avail_w = W - 2 * pad
        vs = row_h * 0.95
        while True:
            fk, fv = font(REG, vs * 0.82), font(BOLD, vs)
            colw = [max((d.textlength(k, font=fk) + vs * 0.26 + d.textlength(v, font=fv)
                         for i, (k, v) in enumerate(items) if i % cols == c), default=0)
                    for c in range(cols)]
            gap = vs * 0.55
            if sum(colw) + gap * (cols - 1) <= avail_w or vs <= 7:
                break
            vs -= 1
        gap += max(0, avail_w - (sum(colw) + gap * (cols - 1))) / (cols - 1)   # 余下宽度均摊到列间隙
        xs, cur = [], pad
        for c in range(cols):
            xs.append(cur)
            cur += colw[c] + gap
        for i, (k, v) in enumerate(items):
            cx, cy = xs[i % cols], y + (i // cols) * row_h
            d.text((cx, cy + vs * 0.30), k, font=fk, fill=0)
            d.text((cx + d.textlength(k, font=fk) + vs * 0.26, cy), v, font=fv, fill=0)
    return img


def on_paper(label: Image.Image, label_mm: tuple[float, float], paper_mm: tuple[float, float],
             note: str = '') -> Image.Image:
    """把一张小标签画在当前卷纸上（左上角，带裁切框和说明），方便在大纸上看真实大小。
    卷纸和标签一样大时原样返回。"""
    if tuple(paper_mm) == tuple(label_mm):
        return label
    W, H = mm(paper_mm[0]) // 8 * 8, mm(paper_mm[1])
    sheet = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(sheet)
    M = mm(4)
    d.text((M, mm(3)), f'{label_mm[0]:g} × {label_mm[1]:g} mm 实样', font=font(BOLD, mm(5)), fill=0)
    if note:
        d.text((M, mm(9)), note, font=font(REG, mm(2.6)), fill=0)
    y = mm(14)
    sheet.paste(label, (M, y))
    d.rectangle([M - 2, y - 2, M + label.width + 1, y + label.height + 1], outline=0, width=2)
    d.text((M, y + label.height + mm(2)), f'↑ 框内即 {label_mm[0]:g}×{label_mm[1]:g}mm 实际大小，可沿框剪下比对磁芯',
           font=font(REG, mm(2.8)), fill=0)
    return sheet


def sample_sheet(rec: dict, items: list[tuple[str, str]], station: str,
                 sizes=SAMPLE_SIZES, paper_mm=DEFAULT_PAPER, qr_prefix: str = QR_PREFIX) -> Image.Image:
    """几种尺寸的对比样张，按实物比例排在一张卷纸上（2026-09-11 原型的样张页）。"""
    W, H = mm(paper_mm[0]) // 8 * 8, mm(paper_mm[1])
    sheet = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(sheet)
    M = mm(2.5)
    d.text((M, mm(1.0)), '磁芯标签尺寸样张 · 实物比例', font=font(BOLD, mm(3.8)), fill=0)
    y = mm(6.5)
    for (w, h) in sizes:
        img = core_label(rec, items, station, w, h, qr_prefix)
        d.text((M, y), f'{w}×{h}mm', font=font(BOLD, mm(3.0)), fill=0)
        y += mm(4.0)
        sheet.paste(img, (M, y))
        d.rectangle([M - 1, y - 1, M + img.width, y + img.height], outline=0, width=2)
        y += img.height + mm(4)
    d.text((M, y), f'二维码内容 = {qr_prefix}<磁芯号>', font=font(REG, mm(2.3)), fill=0)
    return sheet


# ── 命令行 ──────────────────────────────────────────────────────────

def _size(s: str) -> tuple[float, float]:
    w, h = s.lower().replace('×', 'x').split('x')
    return float(w), float(h)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description='磁芯测试数据标签（TSPL 直通，原型）')
    ap.add_argument('csv', help='工位软件 results/ 下的测试 CSV')
    ap.add_argument('--core', help='磁芯号；不给就取最后一条合格记录')
    ap.add_argument('--size', type=_size, default=DEFAULT_SIZE, help='标签尺寸 mm，默认 45x30')
    ap.add_argument('--paper', type=_size, default=DEFAULT_PAPER, help='打印机里装的卷纸 mm，默认 70x130')
    ap.add_argument('--station', help='顶部的 公司/产线/工位；不给就读 --config')
    ap.add_argument('--config', help='工位软件的 config.json，默认当前目录下的')
    ap.add_argument('--qr-prefix', default=QR_PREFIX, help='二维码内容前缀，默认 soaipower.com/t/')
    ap.add_argument('--samples', action='store_true', help='出几种尺寸的对比样张，而不是单张')
    ap.add_argument('--out', default='core_label_preview', help='预览图目录（默认 ./core_label_preview）')
    ap.add_argument('--printer', default=lp.PRINTER)
    ap.add_argument('--print', dest='do', action='store_true', help='真的打印；不给这个参数只出预览图')
    a = ap.parse_args(argv)

    rec, items = read_record(a.csv, a.core)
    station = station_text(a.config, a.station)
    core = (rec.get('磁芯编号') or '-').strip()
    if a.samples:
        page, name = sample_sheet(rec, items, station, paper_mm=a.paper, qr_prefix=a.qr_prefix), f'{core}_samples'
    else:
        img = core_label(rec, items, station, *a.size, qr_prefix=a.qr_prefix)
        page, name = on_paper(img, a.size, a.paper), f'{core}_{a.size[0]:g}x{a.size[1]:g}'
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f'{name}.png'
    page.save(png, dpi=(lp.DPI, lp.DPI))
    job = lp.tspl_job(page.convert('1'), *a.paper)
    print(f'磁芯 {core} {rec.get("产品结果", "")} | {len(items)} 项 | 工位 {station or "(空)"} | 预览 {png}'
          + ('' if a.do else ' | 未打印'))
    if a.do:
        lp.send_raw(job, f'core-label-{core}', a.printer)
        print(f'  已 RAW 发送到 {a.printer}（{len(job)} 字节）')


if __name__ == '__main__':
    main()
