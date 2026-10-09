"""lawyer_lane: the attorney's list sourced and dated, raw['deed_latest'] bound to the parcel, the county
deed reference, and the lawyer_lane invariants. Fixtures are made up."""
from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

from foreclosure_scraper import call_ready as CR
from foreclosure_scraper import lawyer_lane as LL
from foreclosure_scraper.county_deed_ref import parse_feature
from foreclosure_scraper.enrichment_rod_chain import bind_chain

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
TODAY = date(2026, 10, 9)


def chain(recorded="2001-05-09", book="2210", page="301", status="ok", **kw):
    c = {"state": "NC", "county": "Polk", "platform": "nc_cott_v4", "status": status,
         "fetched_at": "2026-10-09T12:00:00+00:00", "source_url": "https://rod.example/search",
         "last_deed": {"recorded": recorded, "book": book, "page": page, "type": "DEED",
                       "grantors": ["SELLER A"], "grantees": ["DOE JOHN"], "description": "LOT 7 TEST SUBD"},
         "prior_instruments": [{"recorded": "1987-03-02", "book": "1450", "page": "22"}]}
    c.update(kw)
    return c


def lead(**raw):
    r = {"state": "NC", "county": "Polk", "parcel_id": "P-1234-5678", "owner_name": "DOE JOHN HEIRS",
         "first_seen": "2026-09-01T00:00:00", "last_seen": "2026-10-08T00:00:00",
         "raw": {"entity_type": "estate", "gis": {"owner": "DOE JOHN HEIRS"}}}
    r["raw"].update(raw)
    return r


# ------------------------------------------------------------------ county deed reference (NC OneMap)

def test_parse_feature_reads_the_assessors_deed_reference_and_skips_placeholders():
    f = lambda ref, d1="", d2="": parse_feature("1", [{"parno": "1", "sourceref": ref, "sourcedatx": d1, "saledatetx": d2}])
    assert f("Deed Book/Page 003911/0033", "2019") == {"parno": "1", "book": "3911", "page": "33", "date": "2019"}
    assert f("26972/906")["book"] == "26972" and f("2021E/127")["book"] == "2021E"
    assert f("Sale Book/Page 009911/002525")["page"] == "2525"
    assert f("Deed Book/Page /", "", "0")["book"] is None
    assert f("Deed Book/Page 010134/00526", "", "12/30/1899 12:00:00 AM")["date"] is None   # a placeholder
    assert f("Deed Book/Page 01514/0638", "", "2025-9-22")["date"] == "2025-09-22"
    assert f("Plat Book/Page 12/34")["book"] is None
    assert parse_feature("9", [{"parno": "1", "sourceref": "Deed Book/Page 1/2"}]) is None


# ------------------------------------------------------------------ binding by book / page

def test_book_page_from_the_county_record_binds_and_a_same_day_other_deed_does_not():
    r = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-09", "book": "02210", "page": "0301"}})
    assert bind_chain(r, chain(), NOW)["status"] == "book_page"
    r2 = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-09", "book": "2210", "page": "999"}})
    b = bind_chain(r2, chain(), NOW)
    assert b["status"] == "name_only" and b["reason"] == "book_page_differs"


def test_county_deed_ref_completes_a_row_without_a_sale_on_the_roll():
    r = lead(county_deed_ref={"source": "nc_onemap", "book": "2210", "page": "301", "date": "2001-05",
                              "fetched_at": "2026-10-09T12:00:00+00:00"})
    assert LL.county_deed_ref(r)["book"] == "2210"
    assert bind_chain(r, chain(), NOW)["status"] == "book_page"


# ------------------------------------------------------------------ raw['deed_latest']

def test_stamp_rebinds_a_legacy_chain_and_writes_the_latest_deed():
    r = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-20"}}, rod_chain=chain())
    st = LL.stamp_deed_latest([r], NOW)
    assert st["rebound"] == 1 and st["deed_latest"] == 1
    dl = r["raw"]["deed_latest"]
    assert dl["bound"] == "sale_date" and dl["doc_id"] == "2210/301" and dl["parcel_id"] == "P-1234-5678"
    assert dl["legal_description"] == "LOT 7 TEST SUBD" and dl["legal_description_source"] == "register_index"


def test_stamp_turns_a_contradicted_legacy_chain_unbound_and_writes_nothing():
    r = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2015-02-02"}}, rod_chain=chain())
    LL.stamp_deed_latest([r], NOW)
    assert r["raw"]["rod_chain"]["status"] == "unbound" and "deed_latest" not in r["raw"]


def test_a_name_only_chain_never_gives_a_latest_deed():
    r = lead(rod_chain=chain())                      # no county sale, no deed reference
    LL.stamp_deed_latest([r], NOW)
    assert r["raw"]["rod_chain"]["binding"]["status"] == "name_only" and "deed_latest" not in r["raw"]


def test_a_copied_or_stale_latest_deed_is_removed():
    r = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-09"}}, rod_chain=chain())
    LL.stamp_deed_latest([r], NOW)
    r["parcel_id"] = "OTHER-9999-0000"
    r["raw"]["rod_chain"] = None
    LL.stamp_deed_latest([r], NOW)
    assert "deed_latest" not in r["raw"]


# ------------------------------------------------------------------ items

def test_items_are_dated_and_walls_are_named():
    r = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-09", "book": "2210", "page": "301"}},
             rod_chain=chain())
    LL.stamp_deed_latest([r], NOW)
    its = LL.items(r, TODAY)
    assert (its["parcel"]["status"], its["parcel"]["on"]) == ("sourced", "2026-10-08")
    assert its["legal_description"]["status"] == "sourced" and its["legal_description"]["on"] == "2026-10-09"
    assert its["deed_chain"]["status"] == "sourced"
    assert its["rod_checked"]["on"] == "2026-10-09"
    assert its["probate_checked"]["status"] == "walled"            # NC estates: eCourts CAPTCHA
    assert its["heirs"]["status"] == "missing" and its["obituaries_checked"]["status"] == "missing"
    assert not LL.complete(its)
    pub = LL.published(its)
    assert pub["probate_checked"] == "walled" and pub["parcel"] == "2026-10-08"


def test_lawyer_unmet_names_walled_items_apart():
    assert CR.lawyer_unmet({"parcel": "2026-10-08", "probate_checked": "walled", "heirs": "missing",
                            "obituaries_checked": "n/a"}) == ["lawyer_probate_checked_walled", "lawyer_heirs"]


def test_candidate_classes():
    assert LL.candidate_classes(lead()) == ["heir_estate"]
    old = {"state": "NC", "county": "Polk", "owner_name": "ROE ANN", "raw": {
        "entity_type": "individual", "tenure": {"years_held": 31}, "life_events": ["life_estate"]}}
    assert "elderly_long" in LL.candidate_classes(old)
    tax = {"state": "NC", "county": "Polk", "owner_name": "ROE ANN", "raw": {
        "entity_type": "individual", "fullmer": {"years_delinquent": 3}, "title_risk": {"kind": "x"}}}
    assert LL.candidate_classes(tax) == ["tax2_unclear"]


def test_register_adapter_and_county_access():
    assert LL.register_adapter("McDowell", "NC") == "nc_lookup"
    assert LL.register_adapter("Polk", "NC") == "nc_cott_v4"           # not the lien-only cott module
    assert LL.register_adapter("Oconee", "SC") == "publicsearch"
    assert LL.county_access("Polk", "NC")["probate"] == "person"


# ------------------------------------------------------------------ invariants

def _checks():
    p = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "lawyer_lane.py"
    spec = importlib.util.spec_from_file_location("ac_lawyer_lane", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {c.name: c for c in m.make_checks()}


def test_invariants_catch_an_unbound_chain_a_copied_deed_and_an_undated_ready_lead():
    cs = _checks()
    legacy = lead(rod_chain=chain())                                    # status ok, no binding
    good = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-09"}}, rod_chain=chain())
    LL.stamp_deed_latest([good], NOW)
    copied = lead(deed_latest=dict(good["raw"]["deed_latest"], parcel_id="X-1"))
    wrong_bp = lead(gis={"owner": "DOE JOHN HEIRS", "last_sale": {"date": "2001-05-09", "book": "1", "page": "2"}},
                    rod_chain=dict(chain(), binding={"status": "sale_date"}))
    ready = lead(call_ready={"lane": "C", "tier": "C", "lawyer": {k: "ok" for k in LL.ITEMS}})
    old_shape = lead(call_ready={"lane": "C", "tier": "D", "lawyer": {k: "ok" for k in LL.ITEMS}})
    for r in (legacy, good, copied, wrong_bp, ready, old_shape):
        for c in cs.values():
            c.feed(r)
    res = {n: c.finish() for n, c in cs.items()}
    assert res["lawyer-rod-chain-bound"]["violations"] == 1
    assert res["lawyer-deed-latest-bound"]["violations"] == 1 and "another_parcel" in res["lawyer-deed-latest-bound"]["detail"]
    assert res["lawyer-chain-book-page"]["violations"] == 1
    assert res["lawyer-lane-c-ready-sourced"]["violations"] == 1
    assert res["lawyer-list-shape"]["violations"] == 2
    assert all(set(v) >= {"name", "checked", "violations", "max_violations", "ok", "detail"} for v in res.values())


def test_parse_sc_reads_each_county_layers_deed_fields():
    from foreclosure_scraper.county_deed_ref import parse_sc
    assert parse_sc("Greenwood", {"Deed": "1612-2907", "PurchaseDate": 1566777600000}) == \
        {"book": "1612", "page": "2907", "date": "2019-08-26"}
    assert parse_sc("Greenville", {"CUBOOK": "02345", "CUPAGE": "0012", "DEEDDATE": "20040312"}) == \
        {"book": "2345", "page": "12", "date": "2004-03-12"}
    assert parse_sc("Pickens", {"SALEDT": 1566777600000}) == {"book": None, "page": None, "date": "2019-08-26"}
    assert parse_sc("Oconee", {"deed_book": "", "deed_page": ""}) is None


def test_intake_reads_open_cott_registers_and_pads_buncombe_pins():
    from foreclosure_scraper.quiet_title.adapters import CottOneMapAdapter, adapter_class
    from foreclosure_scraper.quiet_title.adapters.buncombe import BuncombeAdapter
    a = adapter_class("Jackson")
    assert issubclass(a, CottOneMapAdapter) and a.rod_base.endswith("/protected/v4/") and a.register_fetched
    assert not issubclass(adapter_class("Rutherford"), CottOneMapAdapter)     # behind the guest button
    seen = []

    class Fake(BuncombeAdapter):
        def __init__(self):
            pass

        def _gis(self, where, label, slug):
            seen.append(where)
            return [], [], type("E", (), {"key": "E1"})()
    Fake().parcel("9629575926")
    assert seen == ["pinnum='962957592600000'"]


def test_intake_takes_the_only_deed_at_a_dateless_cited_book_page():
    from foreclosure_scraper.quiet_title.intake import vesting_candidates
    from foreclosure_scraper.quiet_title.model import Instrument
    deed = Instrument(date="02/17/2011", date_iso="2011-02-17", index_code="CRP", kind="QUIT CLAIM", book="1", page="2")
    dot = Instrument(date="02/17/2011", date_iso="2011-02-17", index_code="CRP", kind="DEED OF TRUST", book="1", page="2")
    assert vesting_candidates([deed, dot], None) == ([deed], "NODATE")
    assert vesting_candidates([deed, deed], None) == ([], "")


def test_package_merge_takes_intake_and_owner_items(tmp_path):
    import importlib.util as iu
    p = Path(__file__).resolve().parents[1] / "scripts" / "lawyer_packages.py"
    spec = iu.spec_from_file_location("lawyer_packages", p)
    LP = iu.module_from_spec(spec)
    spec.loader.exec_module(LP)
    facts = {"county": "Polk", "state": "NC", "started": "2026-10-09T10:00:00-04:00",
             "parcel": {"found": True, "owner": "DOE JOHN"},
             "vesting": {"book": "413", "page": "362", "date_iso": "2015-06-03", "description": "LOT 7 TEST"},
             "chain": [{"book": "359", "page": "2280"}], "register_fetched": True, "tax": {"bills": []}}
    it = LP.intake_items(facts)
    assert {k for k, v in it.items() if v["status"] == "sourced"} == \
        {"parcel", "taxpayer", "legal_description", "deed_chain", "rod_checked"}
    d = tmp_path / "P13077"
    d.mkdir()
    (d / "items.json").write_text('{"probate_checked": {"on": "2026-10-10", "source": "eCourts, none"}, '
                                  '"heirs": {"on": "bad"}}')
    own = LP.owner_items(tmp_path, "P130-77")
    assert own["probate_checked"]["on"] == "2026-10-10" and "heirs" not in own
    board = {"probate_checked": LL._src("walled"), "heirs": LL._src("missing")}
    m = LP.merge(board, it, own)
    assert m["probate_checked"]["status"] == "sourced" and m["heirs"]["status"] == "missing"
