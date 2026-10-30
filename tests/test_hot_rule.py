"""热机测试(业主 2026-10-30):NTC(Dcr 7-8,kΩ)1–50 kΩ 判热机,DCR(mΩ)各项改按 ≤70 mΩ 判,其余项照常。"""
import math

from agent.test_runner import TestRunner as Runner, apply_hot_rule, hot_ntc_kohm


class FakeInstr:
    def __init__(self, csv):
        self.csv = csv

    def run_test(self):
        return True, self.csv


def _cfg(t, pins, unit, lo=None, hi=None):
    return {"test_type": t, "pins": pins, "unit": unit, "lower_limit": lo, "upper_limit": hi, "symbol": ""}


ITEMS = [_cfg("Dcr", "2-3", "mOhm", hi=24.5), _cfg("Dcr", "6-5", "mOhm", hi=16.5),
         _cfg("Dcr", "7-8", "kOhm", lo=1.5, hi=135), _cfg("Lx", "2-3", "uH", lo=62.4625, hi=69.0375)]


def _csv(d23=0.0302, d65=0.0134, ntc=5000.0, lx=6.48e-05):
    """仪器原样 SI 单位:Ω、H"""
    return ";".join([f"1,Dcr,'2-3,{d23},0,1,PASS", f"2,Dcr,'6-5,{d65},0,1,PASS",
                     f"3,Dcr,'7-8,{ntc},0,1,PASS", f"4,Lx,'2-3,{lx},0,1,PASS"])


def _run(csv, items=ITEMS):
    r = Runner.__new__(Runner)
    r.product = {"product_code": "ZZ-H2500011-2910", "test_items": items, "enable_eq_n": False}
    r._instr = FakeInstr(csv)
    r._ready = True
    r.logs = []
    r._log = r.logs.append
    return r, r.run()


def _get(rec, t, pins):
    return next(i for i in rec.items if i["type"] == t and i["pins"] == pins)


def test_hot_dcr_over_cold_spec_passes_under_70():
    r, rec = _run(_csv(d23=0.0302))                 # NTC 5 kΩ,DCR 30.2 mΩ(冷机上限 24.5)
    assert rec.hot is True and rec.overall == "PASS"
    d = _get(rec, "Dcr", "2-3")
    assert d["result"] == "Pass" and d["hi_display"] == 70.0 and d["hot_rule"] is True
    assert any("热机测试" in m for m in r.logs)


def test_hot_dcr_over_70_fails():
    _, rec = _run(_csv(d23=0.0752))
    assert rec.hot is True and rec.overall == "FAIL"
    assert _get(rec, "Dcr", "2-3")["result"] == "Fail"


def test_hot_other_item_still_judged_normally():
    _, rec = _run(_csv(d23=0.0302, lx=7.06e-05))    # 电感 70.6 超上限 69.04
    assert rec.hot is True and rec.overall == "FAIL"
    assert _get(rec, "Lx", "2-3")["result"] == "Fail"
    assert "hot_rule" not in _get(rec, "Lx", "2-3")


def test_cold_keeps_normal_dcr_limit():
    _, rec = _run(_csv(d23=0.0302, ntc=100000.0))   # NTC 100 kΩ = 冷机
    assert rec.hot is False and rec.overall == "FAIL"
    d = _get(rec, "Dcr", "2-3")
    assert d["result"] == "Fail" and d["hi_display"] == 24.5 and "hot_rule" not in d


def test_ntc_below_1k_is_fault_not_hot():
    _, rec = _run(_csv(d23=0.0302, ntc=500.0))      # 0.5 kΩ:NTC 短路/接触不良
    assert rec.hot is False and rec.overall == "FAIL"


def test_ntc_at_50k_boundary_is_cold():
    _, rec = _run(_csv(d23=0.0302, ntc=50000.0))
    assert rec.hot is False


def test_station_without_ntc_item_unaffected():
    items = [_cfg("Dcr", "2-3", "mOhm", hi=24.5), _cfg("Lx", "2-3", "uH", lo=62.4625, hi=69.0375)]
    csv = ";".join(["1,Dcr,'2-3,0.0302,0,1,PASS", "2,Lx,'2-3,6.48e-05,0,1,PASS"])
    _, rec = _run(csv, items)
    assert rec.hot is False and rec.overall == "FAIL"


def test_missing_dcr_placeholder_stays_fail_when_hot():
    items = ITEMS + [_cfg("Dcr", "4-5", "mOhm", hi=24.5)]    # 规格多一项,仪器没测
    _, rec = _run(_csv(), items)
    miss = _get(rec, "Dcr", "4-5")
    assert rec.hot is True and miss["result"] == "Fail" and math.isnan(miss["value_display"])
    assert rec.overall == "FAIL"


def test_apply_hot_rule_direct():
    items = [{"type": "Dcr", "pins": "7-8", "unit": "kOhm", "value_display": 12.5, "result": "Pass"},
             {"type": "Dcr", "pins": "2-3", "unit": "mOhm", "value_display": 40.0, "result": "Fail",
              "lo_display": None, "hi_display": 24.5}]
    assert hot_ntc_kohm(items) == 12.5
    assert apply_hot_rule(items) is True
    assert items[1]["result"] == "Pass" and items[1]["hi_display"] == 70.0
