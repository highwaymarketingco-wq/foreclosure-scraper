"""gis_fill.py (county parcel-record fill: deed book/page, short legal, value, acreage, account join) and
scripts/audit_checks/top80_fill.py. Every fixture is made up; the transport is a fake post()."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import gis_fill as G
from foreclosure_scraper.models import Listing

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("top80_fill", REPO / "scripts" / "audit_checks" / "top80_fill.py")
T = importlib.util.module_from_spec(_spec)
sys.modules["top80_fill"] = T
_spec.loader.exec_module(T)

_gm_spec = importlib.util.spec_from_file_location("gap_matrix_t80", REPO / "scripts" / "gap_matrix.py")
GM = importlib.util.module_from_spec(_gm_spec)
sys.modules["gap_matrix_t80"] = GM
_gm_spec.loader.exec_module(GM)


def li(state="NC", county="Alamance", pin="1234-56-7890", **kw):
    return Listing(source="t.src", source_url="https://x.test/1", state=state, county=county, parcel_id=pin,
                   raw=kw.pop("raw", {}), **kw)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    G.reset_state()
    monkeypatch.setattr(G, "sleep", lambda s: None)
    monkeypatch.setattr(G, "post_fn", None)
    monkeypatch.delenv("FORECLOSURE_GIS_FILL", raising=False)
    yield
    G.reset_state()
    monkeypatch.setattr(G, "post_fn", None)


class FakeResp:
    def __init__(self, features=None, status=200, error=None):
        self.status_code = status
        self._j = {"error": error} if error else {"features": [{"attributes": a} for a in (features or [])]}

    def json(self):
        return self._j


def fake_post(monkeypatch, handler):
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append((url, dict(data or {})))
        return handler(url, dict(data or {}))
    monkeypatch.setattr(G, "post_fn", post)
    return calls


# ------------------------------------------------------------------------------------ parsers

@pytest.mark.parametrize("ref,want", [
    ("Deed Book/Page 003559/00295", ("3559", "295")),
    (" Deed Book/Page 3470/0039", ("3470", "39")),
    ("Sale Book/Page 7000/12", ("7000", "12")),
    ("26972/906", ("26972", "906")),
    ("Plat Book/Page 0012/0034", None),
    ("Deed Book/Page 007777", None),                 # a book alone (Guilford) is not a deed reference
    ("Deed Book Page:   ,", None),                   # Union writes a blank
    ("", None), (None, None),
])
def test_parse_nc_ref(ref, want):
    assert G.parse_nc_ref(ref) == want


@pytest.mark.parametrize("text,want", [
    ("695-194", ("695", "194")), ("5268/1393", ("5268", "1393")), ("007687-289", ("7687", "289")),
    ("BK 1111 PG 2222 YR 22", ("1111", "2222")), ("NA", None), ("0-0", None), ("plat 12-3", None), ("", None),
])
def test_parse_combined(text, want):
    assert G.parse_combined(text) == want


def test_book_page_rejects_placeholders():
    assert G.book_page("NA", "12") is None and G.book_page("12", "0000") is None
    assert G.book_page("D006", "5174") == ("D006", "5174")
    assert G.book_page(" ", "5") is None


def test_iso_date_forms():
    assert G.iso_date(1759204800000) == "2025-09-30"
    assert G.iso_date("20130501") == "2013-05-01"
    assert G.iso_date("9/23/2021") == "2021-09-23"
    assert G.iso_date("00000000") is None and G.iso_date(0) is None and G.iso_date("12/30/1899") is None
    assert G.iso_date(None) is None


def test_num_and_plausibility():
    assert G.num("4,229,310") == 4229310.0 and G.num("$1,200") == 1200.0
    assert G.num("0") is None and G.num("abc") is None and G.num(None) is None and G.num(True) is None
    assert G.plausible_value(50) is None and G.plausible_value(1e9) is None and G.plausible_value(250000) == 250000
    assert G.plausible_acres(0.0) is None and G.plausible_acres(2.5) == 2.5 and G.plausible_acres(1e6) is None


def test_legal_text_drops_placeholders_and_joins_fields():
    assert G.legal_text("LOT 7 TEST SUBD", "SEC B") == "LOT 7 TEST SUBD SEC B"
    assert G.legal_text("7") is None and G.legal_text("N/A") is None and G.legal_text(None, " ") is None
    assert len(G.legal_text("A" * 400)) == 200


def test_parse_nc_attrs_reads_deed_legal_value_and_caldwell_style():
    a = {"sourceref": "Deed Book/Page 003911/0033", "sourcedatx": "03/04/2019", "legdecfull": "LT 6B TEST ACRES",
         "parval": 180000, "gisacres": 0.5}
    out = G.parse_nc_attrs(a)
    assert out["deed"] == {"book": "3911", "page": "33", "date": "2019-03-04"}
    assert out["legal"] == "LT 6B TEST ACRES" and out["market"] == 180000 and out["acres"] == 0.5
    cald = G.parse_nc_attrs({"sourceref": "", "legdecfull": "BK 1111 PG 2222 YR 22 ST 100.00"})
    assert cald["deed"]["book"] == "1111" and cald["deed"]["page"] == "2222"
    assert cald["legal"] is None               # the deed reference is never shown as a legal description
    assert G.parse_nc_attrs({"sourceref": "Plat Book/Page 1/2"})["deed"] is None


def test_parse_sc_attrs_per_county_shapes():
    sp = G.SC_FILL["Hampton"]
    out = G.parse_sc_attrs(sp, {"Deed_Book": "395", "Deed_Page": "225", "Instrmnt_Dt": "20130501",
                                "Tot_Market_Appr": "2,917,000", "Tot_Assesd_Value": "22,680",
                                "Tot_Number_Acres": "2,641.00"})
    assert out["deed"] == {"book": "395", "page": "225", "date": "2013-05-01"}
    assert out["market"] == 2917000 and out["assessed"] == 22680 and out["acres"] == 2641.0
    ag = G.parse_sc_attrs(G.SC_FILL["Greenwood"], {"Deed": "695-194", "PurchaseDate": 1003190400000,
                                                   "Description": "1 LOT", "MarketValue_Total": 74000})
    assert ag["deed"]["book"] == "695" and ag["legal"] == "1 LOT" and ag["market"] == 74000
    nx = G.parse_sc_attrs(G.SC_FILL["Sumter"], {"deed_book": "NA", "deed_page": None, "legal_description": "TRACTS A,B 1.79AC",
                                                "market_value_total": 1010000, "deedacre": 1.79})
    assert nx["deed"] is None and nx["legal"] and nx["acres"] == 1.79
    lex = G.parse_sc_attrs(G.SC_FILL["Lexington"], {"CAMA_DeedBook": "", "CAMA_DeedPage": "", "TM_DeedBook": "4306",
                                                    "TM_DeedPage": "148", "Legal_1_2": "THE OAKS LOT 59",
                                                    "Legal_3": "SPLIT FROM 00102901001"})
    assert lex["deed"]["book"] == "4306" and lex["legal"] == "THE OAKS LOT 59 SPLIT FROM 00102901001"
    ber = G.parse_sc_attrs(G.SC_FILL["Berkeley"], {"DeedBook": "5077", "DeedPage": "0317", "SaleDate": 1736208000000,
                                                   "TotalTaxValue": 298000.0, "TotalAcres": 0.0})
    assert ber["deed"]["page"] == "317" and ber["market"] == 298000 and ber["acres"] is None


def test_every_registered_sc_layer_names_its_fields():
    for county, sp in G.SC_FILL.items():
        assert sp["url"].endswith("/query") and sp["ids"], county
        assert G.spec_fields(sp), county
        a = G.asks(sp)
        assert any(a.values()), county


def test_not_fillable_reasons_are_stated():
    assert ("SC", "Clarendon") in G.NOT_FILLABLE and "Cloudflare" in G.NOT_FILLABLE[("SC", "Clarendon")]["assessed_value"]
    assert all(v for d in G.NOT_FILLABLE.values() for v in d.values())


def test_pin_aliases_and_literals():
    assert G.pin_aliases("4738-71-6101-00") == ["4738716101" + "00", "4738716101"]
    assert G.pin_aliases("9659816764") == ["9659816764", "965981676400000"]
    assert G.pin_aliases("0-1") == ["01"]
    lit = G.pin_literals("4738-71-6101-00")
    assert "4738-71-6101-00" in lit and "4738-71-6101" in lit and "4738716101" in lit
    assert "'" not in "".join(G.pin_literals("A'B-1"))


# ------------------------------------------------------------------------------------ verdicts

def test_build_block_and_verdict_columns():
    m = {"deed": None, "legal": "LOT 1 TEST", "market": None, "assessed": None, "acres": 0.3}
    b = G.build_block("NC", "Union", "1", m, "nc_onemap", "2026-10-09T00:00:00+00:00", G.asks(None))
    assert b == {"checked_at": "2026-10-09T00:00:00+00:00", "source": "nc_onemap", "found": True, "deed": "none",
                 "legal": "found", "value": "none", "acres": "found"}
    assert G.verdict_columns({"gis_fill": b}) == {"atty_deed_ref", "assessed_value"}
    nf = G.build_block("NC", "Union", "1", None, "nc_onemap", "2026-10-09T00:00:00+00:00", G.asks(None))
    assert nf["found"] is False and nf["deed"] == "unknown"
    assert G.verdict_columns({"gis_fill": nf}) == set()          # a parcel the layer does not hold is no verdict
    sk = G.build_block("SC", "Lancaster", "1", {"deed": None, "legal": None, "market": None, "assessed": None,
                                                "acres": None}, "x_parcel_layer", "2026-10-09T00:00:00+00:00",
                       G.asks(G.SC_FILL["Lancaster"]))
    assert sk["legal"] == "skip" and sk["value"] == "skip" and sk["deed"] == "none"
    assert G.verdict_columns({}) == set() and G.verdict_columns(None) == set()


# ------------------------------------------------------------------------------------ needs / apply

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def test_needs_gates():
    assert G.needs(li(), NOW)
    assert not G.needs(li(pin=""), NOW) and not G.needs(li(pin="12"), NOW)
    assert not G.needs(li(state="SC", county="Clarendon"), NOW)          # no open layer registered
    assert G.needs(li(state="SC", county="Berkeley"), NOW)
    assert not G.needs(li(state="NC", county="Nowhere"), NOW)
    done = li(raw={"county_deed_ref": {"book": "1", "page": "2"}, "county_legal": {"text": "LOT 1"}},
              assessed_value=1000.0, acreage=1.0)
    assert not G.needs(done, NOW)
    fresh = li(raw={"gis_fill": {"checked_at": (NOW - timedelta(days=3)).isoformat()}})
    assert not G.needs(fresh, NOW)
    stale = li(raw={"gis_fill": {"checked_at": (NOW - timedelta(days=90)).isoformat()}})
    assert G.needs(stale, NOW)


def test_apply_one_is_missing_only():
    row = li(raw={"county_deed_ref": {"book": "9", "page": "9", "source": "register"}}, market_value=555000.0)
    m = {"deed": {"book": "1", "page": "2", "date": "2020-01-02"}, "legal": "LOT 1 TEST", "market": 1.0e5,
         "assessed": 6000.0, "acres": 2.0, "parno": "P"}
    c = G.apply_one(row, m, "nc_onemap", "Alamance", "2026-10-09T00:00:00+00:00", G.asks(None))
    assert row.raw["county_deed_ref"]["book"] == "9"             # the register's own is kept
    assert row.raw["county_legal"]["text"] == "LOT 1 TEST"
    assert row.market_value == 555000.0 and row.assessed_value == 6000.0 and row.acreage == 2.0
    assert c == {"deed": 0, "legal": 1, "value": 1, "acres": 1}
    assert row.raw["gis_fill"]["found"] is True


# ------------------------------------------------------------------------------------ the enricher

def nc_feature(parno, ref="Deed Book/Page 001234/00567", legal="LOT 9 TEST ACRES", **kw):
    return {"parno": parno, "altparno": "", "cntyname": "Alamance", "sourceref": ref, "sourcedatx": "2019",
            "saledatetx": "", "legdecfull": legal, "parval": 150000, "gisacres": 1.2, **kw}


def run(listings, **kw):
    return asyncio.run(G.enrich_gis_fill(listings, **kw))


def test_nc_exact_pass_fills_and_stamps(monkeypatch):
    a, b, c = li(pin="1234-56-7890"), li(pin="2234-56-7890"), li(pin="3234-56-7890")

    def handler(url, data):
        assert url == G.NC_URL and "cntyname='Alamance'" in data["where"]
        return FakeResp([nc_feature("1234-56-7890"), nc_feature("2234-56-7890", ref="", legal="")])
    calls = fake_post(monkeypatch, handler)
    st = run([a, b, c], budget_s=60)
    # c is in no layer record: the LIKE pass asks for it and finds nothing, so it is stamped not-found
    assert a.raw["county_deed_ref"]["book"] == "1234" and a.raw["county_deed_ref"]["page"] == "567"
    assert a.raw["county_deed_ref"]["source"] == "nc_onemap" and a.raw["county_legal"]["text"] == "LOT 9 TEST ACRES"
    assert a.market_value == 150000 and a.acreage == 1.2
    assert b.raw["gis_fill"]["deed"] == "none" and b.raw["gis_fill"]["legal"] == "none"
    assert "county_deed_ref" not in b.raw
    assert c.raw["gis_fill"]["found"] is False
    assert st["candidates"] == 3 and st["screened"] == 3 and st["not_in_layer"] == 1 and st["deed"] == 1
    assert st["none_deed"] == 1 and len(calls) == 2           # one exact request, one LIKE request


def test_nc_like_pass_finds_other_separators_and_never_binds_a_neighbour(monkeypatch):
    row = li(pin="166220709679")

    def handler(url, data):
        if "LIKE" in data["where"]:
            return FakeResp([nc_feature("166220-70-9679"), nc_feature("166220-70-9680", ref="Deed Book/Page 9/9")])
        return FakeResp([])
    fake_post(monkeypatch, handler)
    st = run([row], budget_s=60)
    assert row.raw["county_deed_ref"]["parno"] == "166220-70-9679" and row.raw["county_deed_ref"]["book"] == "1234"
    assert st["found_by_like"] == 1


def test_zero_suffix_and_ten_digit_aliases_reach_the_layer(monkeypatch):
    rows = [li(pin="4738-71-6101-00"), li(pin="9659816764")]

    def handler(url, data):
        return FakeResp([nc_feature("4738-71-6101"), nc_feature("965981676400000")])
    fake_post(monkeypatch, handler)
    run(rows, budget_s=60)
    assert all(r.raw["gis_fill"]["found"] for r in rows)


def test_sc_county_layer_and_none_verdict(monkeypatch):
    row = li(state="SC", county="Lancaster", pin="0068I-0L-007.00")
    blank = li(state="SC", county="Lancaster", pin="0068J-0H-012.00")

    def handler(url, data):
        assert url == G.SC_FILL["Lancaster"]["url"]
        return FakeResp([{"PIN": "0068I-0L-007.00", "PIN2": "0068I 0L 007 00", "DEED_BOOK": "D006",
                          "DEED_PAGE": "5174", "ACRES": 0.35},
                         {"PIN": "0068J-0H-012.00", "PIN2": "0068J 0H 012 00", "DEED_BOOK": " ",
                          "DEED_PAGE": "0000", "ACRES": 1.2}])
    fake_post(monkeypatch, handler)
    st = run([row, blank], budget_s=60)
    assert row.raw["county_deed_ref"]["book"] == "D006" and row.raw["county_deed_ref"]["source"] == "lancaster_parcel_layer"
    assert row.acreage == 0.35
    assert blank.raw["gis_fill"]["deed"] == "none" and G.verdict_columns(blank.raw) == {"atty_deed_ref"}
    assert blank.raw["gis_fill"]["legal"] == "skip"
    assert st["deed"] == 1 and st["none_deed"] == 1


def test_a_layer_that_errors_twice_is_closed_and_rows_stay_unscreened(monkeypatch):
    rows = [li(state="SC", county="Horry", pin=f"4190601{i:04d}") for i in range(100)]
    calls = fake_post(monkeypatch, lambda u, d: FakeResp(error={"code": 499, "message": "Token Required"}))
    st = run(rows, budget_s=60)
    assert all("gis_fill" not in r.raw for r in rows)
    assert st["screened"] == 0 and st["closed_layers"]
    assert len(calls) == 2            # two id fields tried, the second error closes the layer: 100 rows, 2 requests


def test_flag_off_and_budget(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_GIS_FILL", "0")
    row = li()
    assert run([row])["skipped"] == "FORECLOSURE_GIS_FILL=0" and "gis_fill" not in row.raw
    monkeypatch.delenv("FORECLOSURE_GIS_FILL")
    clock = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0])
    monkeypatch.setattr(G, "clock", lambda: next(clock, 2000.0))
    fake_post(monkeypatch, lambda u, d: FakeResp([nc_feature("1234-56-7890")]))
    st = run([row], budget_s=10)
    assert st["budget_hit"] is True and "gis_fill" not in row.raw


def test_account_join_sets_parcel_and_acreage_only_on_a_unique_account(monkeypatch):
    mk = lambda acct: li(state="SC", county="Orangeburg", pin="", raw={"qpaybill_roll": {"identification_no": acct}})
    rows = [mk("0970023"), mk("993249"), mk("5550001")]

    def handler(url, data):
        assert "parcel_id IN" in data["where"]
        return FakeResp([{"parcel_id": "0970023   ", "MAPBLOLOT": "0001-00-00-001.000", "CalculatedAcres": 5.3},
                         {"parcel_id": "0993249", "MAPBLOLOT": "0002-00-01-002.000", "CalculatedAcres": 2.0},
                         {"parcel_id": "5550001", "MAPBLOLOT": "0003-00-00-003.000", "CalculatedAcres": 1.0},
                         {"parcel_id": "5550001", "MAPBLOLOT": "0003-00-00-004.000", "CalculatedAcres": 1.0}])
    fake_post(monkeypatch, handler)
    st = run(rows, budget_s=60)
    assert rows[0].parcel_id == "0001-00-00-001.000" and rows[0].acreage == 5.3
    assert rows[1].parcel_id == "0002-00-01-002.000"
    assert rows[2].parcel_id in (None, "")                       # an account on two parcels is not resolved
    assert rows[0].raw["parcel_from_account"]["join"].startswith("qpaybill_roll.identification_no")
    assert st["parcel_from_account"] == 2


# ------------------------------------------------------------------------------------ cube hooks

def test_gap_matrix_reads_the_fill():
    assert GM.deed_ref_present({"county_deed_ref": {"book": "1", "page": "2"}})
    assert not GM.deed_ref_present({"county_deed_ref": {"book": "1"}})
    assert GM.legal_description_present({"raw": {"county_legal": {"text": "LOT 1 TEST"}}})
    assert not GM.legal_description_present({"raw": {"county_legal": {"text": ""}}})
    rec = {"raw": {"gis_fill": {"checked_at": "2026-10-09T00:00:00+00:00", "found": True, "deed": "none",
                               "legal": "found", "value": "skip", "acres": "none"}}}
    chk = GM.checked_columns(rec, set(), {})
    assert {"atty_deed_ref", "lot_size"} <= chk and "atty_legal_description" not in chk
    assert GM.GIS_FILL_VERDICT_COLS == frozenset(G.VERDICT_COLUMNS)
    # the register index's deed bound to the parcel (lawyer_lane deed_latest) counts for both attorney columns
    dl = {"bound": "book_page", "book": "12", "page": "34", "legal_description": "LOT 3 TEST SUBD"}
    assert GM.deed_ref_present({"deed_latest": dl}) and GM.legal_description_present({"raw": {"deed_latest": dl}})
    assert not GM.deed_ref_present({"deed_latest": {**dl, "bound": None}})
    assert not GM.legal_description_present({"raw": {"deed_latest": {**dl, "bound": None}}})


def test_orangeburg_is_read_for_acres_and_its_gaps_are_stated():
    sp = G.sc_spec("Orangeburg")
    assert sp["acres"] == ["CalculatedAcres"] and not G.asks(sp)["deed"] and G.asks(sp)["acres"]
    nf = G.NOT_FILLABLE
    assert "parcel_id" in nf[("SC", "Aiken")] and "parcel_id" in nf[("SC", "Orangeburg")]
    assert "Service not started" in nf[("SC", "Newberry")]["lot_size"] or "not started" in nf[("SC", "Newberry")]["lot_size"]


# ------------------------------------------------------------------------------------ invariants

def feed_all(checks, rows):
    for r in rows:
        for c in checks:
            c.feed(r)
    return {c.name: c.finish() for c in checks}


def good_row():
    return {"state": "NC", "county": "Alamance", "parcel_id": "4738-71-6101-00", "market_value": 150000.0,
            "acreage": 1.2,
            "raw": {"county_deed_ref": {"source": "nc_onemap", "parno": "4738-71-6101", "book": "3559", "page": "295",
                                        "date": "2016", "fetched_at": "2026-10-09T10:00:00+00:00"},
                    "county_legal": {"source": "nc_onemap", "kind": "assessor_short_legal", "text": "LOT 9 TEST",
                                     "parno": "4738-71-6101", "fetched_at": "2026-10-09T10:00:00+00:00"},
                    "gis_fill": {"checked_at": "2026-10-09T10:00:00+00:00", "source": "nc_onemap", "found": True,
                                 "deed": "found", "legal": "found", "value": "found", "acres": "found"}}}


def test_invariants_pass_on_a_clean_row_and_names_are_kebab():
    out = feed_all(T.make_checks(), [good_row()])
    assert all(v["ok"] for v in out.values()), out
    assert all(n == n.lower() and " " not in n and n.startswith("top80-fill-") for n in out)


def bad(mut):
    r = good_row()
    mut(r)
    return r


@pytest.mark.parametrize("name,mut", [
    ("top80-fill-deed-ref-shape", lambda r: r["raw"]["county_deed_ref"].update(book="0007")),
    ("top80-fill-deed-ref-shape", lambda r: r["raw"]["county_deed_ref"].update(page="")),
    ("top80-fill-deed-ref-shape", lambda r: r["raw"]["county_deed_ref"].update(book="NA")),
    ("top80-fill-deed-ref-bound", lambda r: r["raw"]["county_deed_ref"].update(parno="9999-99-9999")),
    ("top80-fill-deed-ref-bound", lambda r: r["raw"]["county_legal"].update(parno="9999-99-9999")),
    ("top80-fill-legal-shape", lambda r: r["raw"]["county_legal"].update(text="BK 1111 PG 2222")),
    ("top80-fill-legal-shape", lambda r: r["raw"]["county_legal"].update(text="7")),
    ("top80-fill-screen-honest", lambda r: r["raw"]["gis_fill"].update(checked_at="")),
    ("top80-fill-screen-honest", lambda r: r["raw"]["gis_fill"].update(found=False)),
    ("top80-fill-screen-honest", lambda r: r["raw"].pop("county_deed_ref")),
    ("top80-fill-screen-honest", lambda r: r["raw"]["gis_fill"].update(deed="maybe")),
    ("top80-fill-values-sane", lambda r: r.update(market_value=5.0)),
    ("top80-fill-values-sane", lambda r: r.update(acreage=1e7)),
])
def test_each_invariant_catches_its_defect(name, mut):
    out = feed_all(T.make_checks(), [bad(mut)])
    assert out[name]["violations"] == 1 and not out[name]["ok"], out[name]


def test_account_join_invariant():
    r = {"state": "SC", "county": "Orangeburg", "parcel_id": "0001-00-00-001.000",
         "raw": {"qpaybill_roll": {"identification_no": "0970023"},
                 "parcel_from_account": {"source": "orangeburg_parcel_layer", "fetched_at": "2026-10-09T00:00:00+00:00"}}}
    assert feed_all(T.make_checks(), [r])["top80-fill-account-join"]["ok"]
    r2 = {**r, "parcel_id": "970023"}
    assert not feed_all(T.make_checks(), [r2])["top80-fill-account-join"]["ok"]
    r3 = {**r, "raw": {"parcel_from_account": r["raw"]["parcel_from_account"]}}
    assert not feed_all(T.make_checks(), [r3])["top80-fill-account-join"]["ok"]


def test_unscreened_is_a_ratchet(monkeypatch):
    assert T.UNSCREENED_MAX_SHARE == 1.0          # report-only until a gated run measures coverage
    monkeypatch.setattr(T, "UNSCREENED_MAX_SHARE", 0.6)
    clean = good_row()
    open_rows = [{"state": "NC", "county": "Alamance", "parcel_id": f"1234-56-{i:04d}", "raw": {}} for i in range(5)]
    out = feed_all(T.make_checks(), [clean] + open_rows)["top80-fill-unscreened"]
    assert out["violations"] == 5 and out["max_violations"] == int(6 * T.UNSCREENED_MAX_SHARE) and not out["ok"]
    out2 = feed_all(T.make_checks(), [clean] * 8 + open_rows[:2])["top80-fill-unscreened"]
    assert out2["ok"]
    sc_unlisted = {"state": "SC", "county": "Clarendon", "parcel_id": "1", "raw": {}}
    assert feed_all(T.make_checks(), [sc_unlisted])["top80-fill-unscreened"]["checked"] == 0
