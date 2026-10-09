"""Top-80 Logan Systems / Harris Recorder group: the county-wide AcclaimWeb lien sweep (Horry,
Pickens), its stamp, the enricher, the cube reading and the county verdicts. Fixtures are made up."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_register_lien_sweep as E
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.rod import lien_sweep as L
from foreclosure_scraper.rod import sc_polite

REPO = Path(__file__).resolve().parents[1]

FORM = """
<form action="/AcclaimWeb/search/SearchTypeDocType"><input name="DocTypeInfoCheckBox" title="CONDO LIEN (064)" type="checkbox" value="1">
<input aria-label="x" name="DocTypeInfoCheckBox" title="CONDO LIEN SATISFACTION (036)" type="checkbox" value="2">
<input name="DocTypeInfoCheckBox" title="MECHANICS LIEN (015)" type="checkbox" value="3">
<input name="DocTypeInfoCheckBox" title="LIS PENDENS DEED (135)" type="checkbox" value="4">
<input name="DocTypeInfoCheckBox" title="DEED (001)" type="checkbox" value="5">
<input name="DocTypeInfoCheckBox" title="TAX LIENS - STATE (084)" type="checkbox" value="6">
<input name="DocTypeInfoCheckBox" title="TAX SATISFACTION (092)" type="checkbox" value="7">
<input name="DocTypeInfoCheckBox" title="MECHANICS &amp; CONDO LIEN SATISFACTION (035)" type="checkbox" value="8">
<input name="DocTypeInfoCheckBox" title="UCC3: TERMINATION LIEN BK (210)" type="checkbox" value="9">
<input name="DocTypeInfoCheckBox" title="AFFIDAVIT - LIEN BOOK (109)" type="checkbox" value="10"></form>"""

DISCLAIMER = '<form action="/AcclaimWeb/Search/Disclaimer?st=x"><input name="disclaimer" value="true"></form>'


def _row(name_from, name_to, typ, ms, bp="10/20", inst="2026-1"):
    return {"DirectName": name_from, "IndirectName": name_to, "DocTypeDescription": typ,
            "RecordDate": f"/Date({ms})/", "BookPage": bp, "InstrumentNumber": inst, "ParcelNumber": ""}


MS_2026_08 = 1787000000000          # a day in August 2026


class FakeHttp:
    """A scripted PoliteSession: disclaimer, the type search, the grid pages."""

    def __init__(self, rows_by_month=None, wall=False):
        self.rows_by_month = rows_by_month or {}
        self.wall = wall
        self.posts = []
        self.month = None
        self.t = 0                       # a fake clock: every search costs 100 s

    def _r(self, text, status=200, url="https://reg.test/AcclaimWeb/x"):
        return sc_polite.Resp(status, url, text)

    def get(self, url, **kw):
        if self.wall:
            raise sc_polite.RodWalled(url, "CAPTCHA")
        return self._r(DISCLAIMER, url="https://reg.test/AcclaimWeb/Search/Disclaimer?st=x")

    def post(self, url, data=None, **kw):
        self.posts.append((url, dict(data or {})))
        if url.endswith("Disclaimer?st=x") or "Disclaimer" in url:
            return self._r(FORM)
        if "SearchTypeDocType" in url:
            self.month = data["RecordDateFrom"]
            self.t += 100
            return self._r("<html>ok</html>")
        if "GridResults" in url:
            rows = self.rows_by_month.get(self.month, [])
            page = int(data["page"])
            chunk = rows[(page - 1) * 2: page * 2]                  # a tiny page size
            return self._r(json.dumps({"Data": chunk, "Total": len(rows)}))
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "CACHE_DIR", tmp_path / "sweep")
    monkeypatch.setattr(L, "PAGE_SIZE", 2)
    sc_polite.reset_walled()
    yield


def test_adverse_options_keep_the_liens_and_drop_the_plumbing():
    opts = L.parse_doc_type_options(FORM)
    assert len(opts) == 10
    got = {t for t, _ in L.adverse_options(opts)}
    assert got == {"CONDO LIEN (064)", "MECHANICS LIEN (015)", "LIS PENDENS DEED (135)", "TAX LIENS - STATE (084)"}


def test_month_windows_newest_first_and_clipped():
    w = L.month_windows(date(2026, 10, 9), date(2026, 8, 1))
    assert w == [(date(2026, 10, 1), date(2026, 10, 9)), (date(2026, 9, 1), date(2026, 9, 30)),
                 (date(2026, 8, 1), date(2026, 8, 31))]
    assert L.month_windows(date(2027, 1, 5), date(2026, 12, 20))[1] == (date(2026, 12, 1), date(2026, 12, 31))


def _index():
    ix = L.LienIndex()
    for s in (
        {"t": "CONDO LIEN", "d": "2026-08-01", "b": "1", "p": "2", "i": "A1", "f": "OCEAN CONDO ASSOCIATION", "g": "SMITH JOHN A", "n": "123456"},
        {"t": "TAX LIENS - STATE", "d": "2026-07-01", "b": "1", "p": "3", "i": "A2", "f": "STATE OF SOUTH CAROLINA DEPT OF REVENUE", "g": "DOE JANE", "n": None},
        {"t": "MECHANICS LIEN", "d": "2026-06-01", "b": "1", "p": "4", "i": "A3", "f": "ABC ROOFING LLC", "g": "NORTHSIDE HOLDINGS LLC", "n": None},
    ):
        ix.add(s)
    return ix


def test_match_levels_exact_name_parcel_and_none():
    ix = _index()
    exact = ix.match("SMITH JOHN A")
    assert [h["fit"] for h in exact] == ["exact"]
    by_parcel = ix.match("SMITH JOHN A", parcel="12-3456")
    assert by_parcel[0]["fit"] == "parcel"
    only_name = ix.match("SMITH JOHN")                       # no middle initial on the owner: name only
    assert [h["fit"] for h in only_name] == ["name"]
    assert ix.match("SMITH JANE") == []                      # another first name
    assert ix.match("DOE JANE")[0]["t"] == "TAX LIENS - STATE"
    assert ix.match("Northside Holdings, LLC")[0]["fit"] == "exact"   # entity words equal
    assert ix.match("") is None                              # unusable name is not 'none found'


def test_sweep_reads_months_pages_and_reuses_the_cache():
    rows = [_row("OCEAN CONDO ASSOCIATION", "SMITH JOHN A", "CONDO LIEN", MS_2026_08, inst=f"I{i}") for i in range(5)]
    http = FakeHttp({"8/1/2026": rows})
    ix, res = L.sweep_county("Horry", since=date(2026, 8, 1), today=date(2026, 8, 31), session=http)
    assert res.error is None and res.walled is None
    assert res.months_read == 1 and res.instruments_new == 5 and ix.size == 5
    assert res.window_from == "2026-08-01" and res.window_to == "2026-08-31" and res.types == 4
    sent = [d for u, d in http.posts if "SearchTypeDocType" in u][0]
    assert sent["DocTypes"] == "1,3,4,6"                     # only the adverse ids
    # the finished month comes from the cache the second time; no search is posted
    http2 = FakeHttp()
    ix2, res2 = L.sweep_county("Horry", since=date(2026, 8, 1), today=date(2026, 8, 31), session=http2)
    assert res2.months_cached == 1 and res2.months_read == 0 and ix2.size == 5
    assert http2.posts == []


def test_running_month_is_read_again_every_run():
    http = FakeHttp({"8/1/2026": []})
    L.sweep_county("Horry", since=date(2026, 8, 1), today=date(2026, 8, 20), session=http)
    http2 = FakeHttp({"8/1/2026": []})
    _, res = L.sweep_county("Horry", since=date(2026, 8, 1), today=date(2026, 8, 20), session=http2)
    assert res.months_read == 1 and res.months_cached == 0


def test_budget_ends_the_sweep_newest_first_and_window_is_contiguous():
    http = FakeHttp({})
    _, res = L.sweep_county("Horry", since=date(2026, 6, 1), today=date(2026, 8, 31), session=http,
                            budget_s=50, clock=lambda: http.t)
    assert res.budget_exhausted and res.months_read == 1
    assert res.window_from == "2026-08-01"                   # only the month actually read is claimed


def test_wall_stamps_nothing():
    ix, res = L.sweep_county("Horry", since=date(2026, 8, 1), today=date(2026, 8, 31), session=FakeHttp(wall=True))
    assert res.walled == "CAPTCHA" and res.window_from is None
    assert L.stamp_for([], res) is None


def test_stamp_statuses_and_window():
    res = L.SweepResult(county="Horry", window_from="2026-01-01", window_to="2026-08-31", types=4)
    none = L.stamp_for([], res, "2026-10-09")
    assert none["status"] == "none_found" and none["window_from"] == "2026-01-01" and none["checked_at"] == "2026-10-09"
    poss = L.stamp_for([{"fit": "name", "t": "X"}], res)
    assert poss["status"] == "possible" and poss["adverse_count"] == 0 and poss["possible_count"] == 1
    found = L.stamp_for([{"fit": "exact", "t": "X"}, {"fit": "name", "t": "Y"}], res)
    assert found["status"] == "found" and found["adverse_count"] == 1
    assert L.stamp_for(None, res) is None


def _lead(owner, county="Horry", state="SC", parcel="P1"):
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE, state=state,
                   county=county, owner_name=owner, parcel_id=parcel, raw={})


def test_enricher_stamps_swept_counties_only(monkeypatch):
    ix = _index()
    res = L.SweepResult(county="Horry", window_from="2026-01-01", window_to="2026-09-30", types=4, months_read=9)
    monkeypatch.setattr(L, "sweep_county", lambda county, **kw: (ix, res))
    a, b, c, d = _lead("SMITH JOHN A"), _lead("NOBODY HERE"), _lead("X", county="Greenville"), _lead("", parcel="P9")
    stats = asyncio.run(E.enrich_register_lien_sweep([a, b, c, d]))
    assert a.raw["rod_lien_sweep"]["status"] == "found"
    assert b.raw["rod_lien_sweep"]["status"] == "none_found"
    assert "rod_lien_sweep" not in c.raw and "rod_lien_sweep" not in d.raw
    assert stats["targets"] == 2 and stats["stamped"] == 2 and stats["found"] == 1 and stats["none_found"] == 1


def test_enricher_off_and_no_county(monkeypatch):
    monkeypatch.setenv(L.ENV_FLAG, "0")
    assert "skipped" in asyncio.run(E.enrich_register_lien_sweep([_lead("A B")]))
    monkeypatch.setenv(L.ENV_FLAG, "1")
    assert "skipped" in asyncio.run(E.enrich_register_lien_sweep([_lead("A B", county="Greenville")]))


def test_enricher_walled_county_stamps_nothing(monkeypatch):
    res = L.SweepResult(county="Horry", walled="CAPTCHA")
    monkeypatch.setattr(L, "sweep_county", lambda county, **kw: (L.LienIndex(), res))
    a = _lead("SMITH JOHN A")
    stats = asyncio.run(E.enrich_register_lien_sweep([a]))
    assert "rod_lien_sweep" not in a.raw and stats["not_stamped"] == 1 and stats["stamped"] == 0


def test_cube_counts_the_sweep_stamp_as_a_liens_check():
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import gap_matrix as gm
    stamp = {"status": "none_found", "checked_at": "2026-10-09"}
    assert gm.rod_checked({"rod_lien_sweep": stamp})
    assert not gm.rod_checked({"rod_lien_sweep": {"status": "none_found"}})          # undated: not a check
    rec = {"raw": {"rod_lien_sweep": stamp}}
    assert "liens" in gm.checked_columns(rec, set(), {})


def test_county_verdicts_and_flags_are_recorded():
    m = json.loads((REPO / "docs/county_records/county_records_matrix.json").read_text())
    by = {(c["state"], c["county"].lower()): c for c in m["counties"]}
    for k in [("NC", "cabarrus"), ("NC", "catawba"), ("NC", "chatham"), ("NC", "cumberland"), ("NC", "transylvania"),
              ("SC", "spartanburg"), ("SC", "horry"), ("SC", "pickens")]:
        assert by[k]["rod"]["column_access"]["marriage_license"] == "none", k
    prof = json.loads((REPO / "deploy/oracle/run_profile.json").read_text())
    assert prof["flags"]["FORECLOSURE_SC_LIEN_SWEEP"] == "1"
    assert prof["flags"]["FORECLOSURE_NC_LOGAN_BLAZOR_ROD"] == "0"                  # browser-only: measured, OFF
    vm = (REPO / "deploy/oracle/vm_lib.sh").read_text()
    assert 'FORECLOSURE_SC_LIEN_SWEEP="${FORECLOSURE_SC_LIEN_SWEEP:-1}"' in vm


# --- the invariants -------------------------------------------------------------------------------
def _checks():
    import importlib.util
    spec = importlib.util.spec_from_file_location("t80lh", REPO / "scripts/audit_checks/top80_logan_harris.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {c.name: c for c in m.make_checks()}


def _brow(stamp=None, county="Horry", state="SC", owner="SMITH JOHN A", parcel="P1"):
    raw = {} if stamp is None else {"rod_lien_sweep": stamp}
    return {"state": state, "county": county, "owner_name": owner, "parcel_id": parcel, "raw": raw}


def _stamp(status="none_found", insts=(), **kw):
    s = {"status": status, "checked_at": "2026-10-09", "window_from": "2026-01-01", "window_to": "2026-10-09",
         "county": "Horry", "platform": "harris_acclaimweb_lien_sweep", "adverse_count": 0, "possible_count": 0, "instruments": list(insts)}
    s.update(kw)
    return s


def test_invariants_pass_on_good_rows_and_catch_each_defect():
    ck = _checks()
    good = [_brow(_stamp()),
            _brow(_stamp("found", [{"fit": "exact", "f": "OCEAN CONDO ASSOCIATION", "g": "SMITH JOHN A"}], adverse_count=1)),
            _brow(_stamp("possible", [{"fit": "name", "f": "X ASSOCIATION", "g": "SMITH JOHN"}], possible_count=1))]
    bad = [
        _brow(_stamp(window_from="2026-12-01")),                                   # window after window_to
        _brow(_stamp(window_from=None)),                                           # no window
        _brow(_stamp(adverse_count=2)),                                            # none_found beside a count
        _brow(_stamp("found", [], adverse_count=0)),                               # found with nothing
        _brow(_stamp("maybe")),                                                    # unknown status
        _brow(_stamp(county="Horry"), county="Greenville"),                        # stamp outside the county
        _brow(_stamp("found", [{"fit": "exact", "f": "A CO", "g": "JONES MARY"}], adverse_count=1)),   # names another person
    ]
    for r in good + bad:
        for c in ck.values():
            c.feed(r)
    out = {n: c.finish() for n, c in ck.items()}
    assert out["top80-lien-sweep-shape"]["violations"] == 5
    assert out["top80-lien-sweep-county-only"]["violations"] == 1
    assert out["top80-lien-sweep-name-fit"]["violations"] == 2     # no instrument at all, and another person
    assert out["top80-lien-sweep-name-fit"]["checked"] == 3
    cov = out["top80-lien-sweep-coverage"]
    assert cov["checked"] == 9 and cov["violations"] == 0 and cov["ok"]
    assert out["top80-logan-harris-config"]["ok"], out["top80-logan-harris-config"]["detail"]


def test_coverage_ratchet_counts_unstamped_owner_rows():
    c = _checks()["top80-lien-sweep-coverage"]
    for r in (_brow(), _brow(parcel="P2"), _brow(_stamp(), parcel="P3"), _brow(owner="", parcel="P4"),
              _brow(county="Greenville", parcel="P5")):
        c.feed(r)
    out = c.finish()
    assert out["checked"] == 3 and out["violations"] == 2 and out["ok"]


def test_invariants_ignore_stamps_of_other_registers():
    ck = _checks()
    other = _brow(_stamp("found", [], adverse_count=0, platform="ccs_classic_lien_sweep"), county="Orange", state="NC")
    for c in ck.values():
        c.feed(other)
    assert ck["top80-lien-sweep-shape"].finish()["checked"] == 0
    assert ck["top80-lien-sweep-county-only"].finish()["checked"] == 0
