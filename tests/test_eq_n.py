"""等效 n:凑不齐 A/B/C 时记不合格并写明原因,不再静默跳过(2026-10-22 汉润磁芯检规格符号全空,一下午没有 N)。"""
import math

from agent.test_runner import TestRunner as Runner


class FakeInstr:
    def __init__(self, csv):
        self.csv = csv

    def run_test(self):
        return True, self.csv


# 汉润磁芯检 1767 号的实测值(SI 单位,仪器原样):Lx_2-3 / Lk_2-3 / Lx_6-5 / Dcr_2-3
CSV = ";".join([
    "1,Lx,'2-3,6.4645e-05,0,1,PASS",
    "2,Lk,'2-3,9.024e-06,0,1,PASS",
    "3,Lx,'6-5,3.9668e-05,0,1,PASS",
    "4,Dcr,'2-3,0.017722,0,1,PASS",
])


def _item(t, pins, unit, symbol=...):
    it = {"test_type": t, "pins": pins, "unit": unit, "lower_limit": None, "upper_limit": None}
    if symbol is not ...:
        it["symbol"] = symbol
    return it


def _runner(items, csv=CSV, enable=True):
    r = Runner.__new__(Runner)
    r.product = {"product_code": "ZZ-H2500011-磁芯检", "test_items": items, "enable_eq_n": enable,
                 "eq_n_vars": {"l_raw": "A", "lk_raw": "B", "l_aux": "C", "n_lower": 1.17552, "n_upper": 1.19448}}
    r._instr = FakeInstr(csv)
    r._ready = True
    r.logs = []
    r._log = r.logs.append
    return r


def _eqn(rec):
    found = [i for i in rec.items if i["type"] == "EqN"]
    assert len(found) == 1
    return found[0]


def test_symbols_present_computes_n():
    rec = _runner([_item("Lx", "2-3", "uH", "A"), _item("Lk", "2-3", "uH", "B"),
                   _item("Lx", "6-5", "uH", "C"), _item("Dcr", "2-3", "mOhm", "")]).run()
    n = _eqn(rec)
    assert n["result"] == "Pass" and abs(n["value_display"] - 1.1841) < 1e-3
    assert rec.overall == "PASS"


def test_blank_symbols_fail_with_reason():
    # v5 的样子:每项都有 symbol 键但是空串 → 以前静默跳过,现在记不合格
    r = _runner([_item("Lx", "2-3", "uH", ""), _item("Lk", "2-3", "uH", ""),
                 _item("Lx", "6-5", "uH", ""), _item("Dcr", "2-3", "mOhm", "")])
    rec = r.run()
    n = _eqn(rec)
    assert n["result"] == "Fail" and math.isnan(n["value"]) and math.isnan(n["value_display"])
    assert "规格里没有符号A" in n["error"] and "B" in n["error"] and "C" in n["error"]
    assert rec.overall == "FAIL"
    assert any("等效n 算不出来" in m for m in r.logs)


def test_symbol_configured_but_not_measured():
    csv = ";".join(CSV.split(";")[:2])   # 仪器只测了 Lx_2-3、Lk_2-3,没测 Lx_6-5
    rec = _runner([_item("Lx", "2-3", "uH", "A"), _item("Lk", "2-3", "uH", "B"),
                   _item("Lx", "6-5", "uH", "C")], csv=csv).run()
    n = _eqn(rec)
    assert n["result"] == "Fail" and "C(Lx_6-5)没测到" in n["error"]


def test_missing_configured_item_is_fail_placeholder():
    # 规格配了 Dcr_6-5,仪器没返回 → 补一条不合格的占位项,整台不合格;其余项照常
    r = _runner([_item("Lx", "2-3", "uH", "A"), _item("Lk", "2-3", "uH", "B"), _item("Lx", "6-5", "uH", "C"),
                 _item("Dcr", "2-3", "mOhm", ""), _item("Dcr", "6-5", "mOhm", "")])
    rec = r.run()
    miss = [i for i in rec.items if i.get("error") == "缺项(仪器没测到)"]
    assert [(i["type"], i["pins"], i["unit"], i["result"]) for i in miss] == [("Dcr", "6-5", "mOhm", "Fail")]
    assert math.isnan(miss[0]["value"]) and math.isnan(miss[0]["value_display"])
    assert _eqn(rec)["result"] == "Pass"
    assert rec.overall == "FAIL"
    assert any("缺项:Dcr_6-5" in m for m in r.logs)


def test_all_configured_items_measured_no_placeholder():
    rec = _runner([_item("Lx", "2-3", "uH", "A"), _item("Lk", "2-3", "uH", "B"),
                   _item("Lx", "6-5", "uH", "C"), _item("Dcr", "2-3", "mOhm", "")]).run()
    assert not [i for i in rec.items if i.get("error")]
    assert rec.overall == "PASS"


def test_null_symbol_is_not_NONE():
    rec = _runner([_item("Lx", "2-3", "uH", "A"), _item("Lk", "2-3", "uH", "B"),
                   _item("Lx", "6-5", "uH", "C"), _item("Dcr", "2-3", "mOhm", None)]).run()
    dcr = [i for i in rec.items if i["type"] == "Dcr"][0]
    assert dcr["symbol"] is None
    assert _eqn(rec)["result"] == "Pass"


def test_eq_n_off_adds_nothing():
    rec = _runner([_item("Lx", "2-3", "uH", "")], enable=False).run()
    assert not [i for i in rec.items if i["type"] == "EqN"]


def test_missing_symbol_key_uses_position():
    # 测试项没有 symbol 这个键时按位置补 A、B、C(老配置的写法),照常能算
    rec = _runner([_item("Lx", "2-3", "uH"), _item("Lk", "2-3", "uH"), _item("Lx", "6-5", "uH")]).run()
    assert _eqn(rec)["result"] == "Pass"
