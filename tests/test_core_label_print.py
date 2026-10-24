# -*- coding: utf-8 -*-
"""磁芯测试数据标签：读 CSV、选记录、排版尺寸、TSPL 作业。不连打印机、不发任何数据。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import core_label_print as cl                              # noqa: E402
import label_print as lp                                   # noqa: E402

HEAD = ['类型', '序列码', '序号', '磁芯编号', '产品', 'Turn_2-3', 'Lx_2-3(uH)', 'Lk_6-5(uH)',
        'Q_2-3', 'Dcr_6-5(mOhm)', '等效n', '产品结果']


def _csv(tmp_path, rows):
    """工位软件的测试 CSV：表头 + 上限行 + 下限行 + 记录"""
    p = tmp_path / 'ZZ-H2500011-磁芯检_test.csv'
    lines = [HEAD, ['上限'] + [''] * (len(HEAD) - 1), ['下限'] + [''] * (len(HEAD) - 1)] + rows
    p.write_text('﻿' + '\n'.join(','.join(r) for r in lines) + '\n', encoding='utf-8')
    return p


def _row(t, core, result, lx='66.70307'):
    return [t, '', '', core, 'ZZ-H2500011-磁芯检', '1.000000', lx, '5.587099', '', '11.498040', '1.185682', result]


@pytest.fixture
def csv_file(tmp_path):
    return _csv(tmp_path, [
        _row('2026-08-14 01:43:12', '9999', 'PASS'),
        _row('2026-08-14 02:00:16', '8888', 'PASS'),
        _row('2026-08-14 02:10:00', '8888', 'FAIL', lx='70.1'),
        _row('2026-08-14 02:20:00', '7777', 'FAIL'),
    ])


def test_default_picks_last_pass_record(csv_file):
    rec, items = cl.read_record(csv_file)
    assert rec['磁芯编号'] == '8888' and rec['产品结果'] == 'PASS'
    # 空值（Q_2-3）不印；短名去掉下划线和单位；等效n 印成 n
    assert items == [('Turn2-3', '1'), ('Lx2-3', '66.7'), ('Lk6-5', '5.587'), ('Dcr6-5', '11.5'), ('n', '1.186')]


def test_core_picks_that_cores_last_record_even_if_fail(csv_file):
    rec, items = cl.read_record(csv_file, '8888')
    assert rec['产品结果'] == 'FAIL' and ('Lx2-3', '70.1') in items
    with pytest.raises(ValueError, match='没有磁芯号 1234'):
        cl.read_record(csv_file, '1234')


def test_no_pass_falls_back_to_last_record(tmp_path):
    rec, _ = cl.read_record(_csv(tmp_path, [_row('2026-08-14 02:20:00', '7777', 'FAIL')]))
    assert rec['磁芯编号'] == '7777'


def test_station_text_from_override_or_config(tmp_path):
    assert cl.station_text(override='汉润/智子专线/磁芯检') == '汉润/智子专线/磁芯检'
    cfg = tmp_path / 'config.json'
    cfg.write_text('{"company": "智子", "line": "测试", "station": "试验"}', encoding='utf-8')
    assert cl.station_text(cfg) == '智子/测试/试验'
    assert cl.station_text(tmp_path / 'none.json') == ''


@pytest.mark.parametrize('size', [(45, 30), (40, 26), (35, 22)])
def test_label_size_fits_printer_width(csv_file, size):
    rec, items = cl.read_record(csv_file)
    img = cl.core_label(rec, items, '智子/测试/试验', *size)
    assert img.width % 8 == 0 and img.width <= int(size[0] * lp.MM)          # 不超过标签宽，见 lp.bitmap_bytes
    assert img.height == int(size[1] * lp.MM)
    assert img.getextrema() == (0, 255)                                        # 有黑有白


def test_label_renders_without_items_or_station(csv_file):
    rec, _ = cl.read_record(csv_file)
    assert cl.core_label(rec, [], '').size == cl.core_label(rec, [], '智子').size


def test_45x30_qr_has_at_least_3_dots_per_module():
    # 45×30 上二维码每格 ≥3 点才好扫；静区留 4 格时只剩 2 点，所以磁芯标签用 2 格静区
    W, H = int(45 * lp.MM) // 8 * 8, int(30 * lp.MM)
    qs = min(int(H * 0.40), int(W * 0.30))
    qr = lp.qr_image(cl.QR_PREFIX + '8888', qs, quiet=cl.QR_QUIET)
    from reportlab.graphics.barcode.qr import QrCodeWidget
    w = QrCodeWidget(cl.QR_PREFIX + '8888')
    w.qr.make()
    assert qr.width // (w.qr.getModuleCount() + 2 * cl.QR_QUIET) >= 3


def test_on_paper_keeps_label_when_paper_matches(csv_file):
    rec, items = cl.read_record(csv_file)
    img = cl.core_label(rec, items, '')
    assert cl.on_paper(img, (45, 30), (45, 30)) is img
    sheet = cl.on_paper(img, (45, 30), (70, 130))
    assert sheet.size == (int(70 * lp.MM) // 8 * 8, int(130 * lp.MM))


def test_preview_only_never_sends_to_printer(csv_file, tmp_path, monkeypatch):
    monkeypatch.setattr(lp, 'send_raw', lambda *a, **k: pytest.fail('不加 --print 不能发打印机'))
    cl.main([str(csv_file), '--station', '智子/测试/试验', '--out', str(tmp_path / 'out')])
    cl.main([str(csv_file), '--samples', '--out', str(tmp_path / 'out')])
    assert sorted(p.name for p in (tmp_path / 'out').iterdir()) == ['8888_45x30.png', '8888_samples.png']


def test_print_sends_exactly_one_label_job(csv_file, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(lp, 'send_raw', lambda data, title, printer=lp.PRINTER: sent.append((data, title, printer)))
    cl.main([str(csv_file), '--paper', '45x30', '--out', str(tmp_path / 'out'), '--print'])
    [(job, title, printer)] = sent
    assert title == 'core-label-8888' and printer == 'EZSCAN E75'
    assert job.startswith(b'SIZE 45 mm,30 mm\r\n') and job.endswith(b'\r\nPRINT 1,1\r\n')   # 只打一张
    assert job.count(b'PRINT') == 1
