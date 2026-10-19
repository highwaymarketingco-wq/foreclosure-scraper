"""Deferred-value / rollback-tax exposure enrichment.

Offline tests run against fixtures captured from the live sources on
2026-08-03 (tests/fixtures/buncombe_deferred_bills.json and
tests/fixtures/anderson_rollback_2025_p1_2.pdf, a 2-page slice of the real
AZR012 book). The network fetchers are monkeypatched, so nothing here needs
a connection. A live smoke test is gated behind RUN_LIVE=1.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
from datetime import datetime

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_rollback_deferral as mod

FIX = pathlib.Path(__file__).parent / "fixtures"
BILLS = json.loads((FIX / "buncombe_deferred_bills.json").read_text())
BOOK_PDF = (FIX / "anderson_rollback_2025_p1_2.pdf").read_bytes()


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(
        source="test",
        source_url="https://example.test",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=now,
        last_seen=now,
    )
    base.update(kw)
    return Listing(**base)


def _run(listings):
    return asyncio.run(mod.enrich_with_rollback_exposure(listings))


def _patch(monkeypatch, buncombe=None, anderson=None, mecklenburg=None, meck_topup=None):
    async def fake_bun(c):
        return buncombe or {}

    async def fake_and(c):
        return anderson or {}

    async def fake_meck_rows(c):
        return mecklenburg or []

    async def fake_meck_topup(c, pid):
        return (meck_topup or {}).get(pid)

    monkeypatch.setattr(mod, "_fetch_buncombe", fake_bun)
    monkeypatch.setattr(mod, "_fetch_anderson", fake_and)
    monkeypatch.setattr(mod, "_fetch_mecklenburg_candidates", fake_meck_rows)
    monkeypatch.setattr(mod, "_mecklenburg_live_topup", fake_meck_topup)


# --------------------------------------------------------------------------
# Buncombe record math
# --------------------------------------------------------------------------

def _bills_for(pin):
    return [a for a in BILLS if a["pin"] == pin]


def test_buncombe_record_derives_rate_from_the_bill_not_a_hardcoded_millage():
    a = dict(BILLS[0])
    a["bill"] = "0000742141-2025-2025-0070-00"      # a current-year levy row
    rate = mod._pick_rate([a])
    rec = mod._buncombe_record([a], rate, "parcel_bill")
    expected = float(a["original_bill_amount"]) / float(a["total_value"])
    # effective_tax_rate is stored rounded to 6dp for the artifact.
    assert rec["effective_tax_rate"] == pytest.approx(expected, abs=5e-7)
    assert rec["annual_deferred_tax"] == pytest.approx(
        float(a["deferred_value"]) * expected, rel=1e-3)
    # NC: current fiscal year + 3 preceding (G.S. 105-277.4(c)).
    assert rec["rollback_years"] == 4
    assert rec["estimated_rollback"] == pytest.approx(rec["annual_deferred_tax"] * 4, rel=1e-4)
    assert rec["estimate_is_floor"] is True
    assert rec["tax_year"] == 2025


def test_pick_rate_prefers_the_full_current_year_levy_over_a_district_slice():
    """The regression this guards: taking whichever bill row came back first
    picked a fire-district-only slice (0.10 per $100) instead of the combined
    county+municipal levy (0.70), understating every rollback ~7x."""
    slice_row = {"bill": "0000000001-2025-2025-0070-00", "total_value": "100000",
                 "original_bill_amount": "100", "deferred_value": "200000"}
    full_row = {"bill": "0000000001-2025-2025-0010-00", "total_value": "100000",
                "original_bill_amount": "700", "deferred_value": "200000"}
    assert mod._pick_rate([slice_row, full_row]) == pytest.approx(0.007)
    assert mod._pick_rate([full_row, slice_row]) == pytest.approx(0.007)


def test_prior_tax_year_rows_are_reported_as_already_billed_rollback():
    """A 2025 levy carrying 2021-2024 tax-year rows is a rollback the county
    has ALREADY issued — a fact that must not be presented as an estimate."""
    rows = _bills_for("9702-79-6329-00000")
    assert rows, "fixture lost its multi-year parcel"
    rec = mod._buncombe_record(rows, 0.007, "county_median")
    assert rec["rollback_already_billed"] > 0
    assert rec["rollback_billed_years"] == [2021, 2022, 2023, 2024]


def test_bill_year_segments_are_decoded():
    assert mod._bill_years("0000742141-2025-2021-0070-00") == (2025, 2021)
    assert mod._bill_years("garbage") == (None, None)


def test_implausible_rate_falls_back_to_the_county_median_not_a_guess():
    rec = mod._buncombe_record(
        [{"pin": "9999999999", "bill": "1-2025-2025-0010-00",
          "deferred_value": "100000", "total_value": "0",
          "original_bill_amount": "", "levy_year": "2025"}],
        0.0070, "county_median")
    assert rec["deferred_value"] == 100000.0
    assert rec["tax_rate_source"] == "county_median"
    assert rec["estimated_rollback"] == pytest.approx(100000 * 0.0070 * 4)


def test_no_rate_at_all_still_reports_the_exposure_base():
    rec = mod._buncombe_record(
        [{"pin": "9999999999", "bill": "1-2025-2025-0010-00",
          "deferred_value": "100000", "total_value": "0",
          "original_bill_amount": "", "levy_year": "2025"}],
        None, "county_median")
    assert rec["deferred_value"] == 100000.0
    # No rate available -> no invented estimate, but the exposure base stands.
    assert rec["effective_tax_rate"] is None
    assert rec["estimated_rollback"] is None


# --------------------------------------------------------------------------
# Anderson book parsing (text layer, no OCR)
# --------------------------------------------------------------------------

def test_anderson_book_parses_from_the_pdf_text_layer():
    rows = mod.parse_anderson_book(BOOK_PDF, 2025)
    assert len(rows) >= 50
    r = rows[0]
    assert r["tms"] == "002-00-01-002"
    assert r["county"] == "Anderson" and r["state"] == "SC"
    assert r["tax_year"] == 2025
    # SC rollback runs the 3 years preceding the change in use.
    assert r["rollback_years"] == 3
    assert r["estimated_rollback"] == pytest.approx(r["annual_deferred_tax"] * 3, rel=1e-6)


def test_anderson_annual_tax_reproduces_the_statutory_formula():
    """annual rollback == (market - use) x 0.06 assessment ratio x millage.

    The book prints a per-acre figure; multiplying it back out must reproduce
    the county's own arithmetic, which proves the columns are mapped correctly
    (and would catch a column shifted by one)."""
    rows = mod.parse_anderson_book(BOOK_PDF, 2025)
    checked = 0
    for r in rows:
        if not all(r.get(k) for k in ("market_value", "use_value", "millage", "acres")):
            continue
        expected = (r["market_value"] - r["use_value"]) * 0.06 * r["millage"]
        # 5% band: the book prints acreage rounded to 2dp and computes the
        # per-acre figure off the unrounded ag-classified acreage, so the two
        # routes agree closely but not exactly. A mis-mapped column would be
        # off by orders of magnitude, not percent.
        assert r["annual_deferred_tax"] == pytest.approx(expected, rel=0.05), r["tms"]
        checked += 1
    assert checked >= 30


def test_anderson_sub_acre_rows_are_not_dropped():
    """Rows under one acre print acreage as '.85' with no leading zero — an
    earlier regex missed every one of them."""
    line = "007-02-01-017 SANDERS DENNIS E + PAMELA J 004 .85 1,312 130 .33232 28.53"
    m = mod.ANDERSON_ROW_RE.match(line)
    assert m and m.group("acres") == ".85"


def test_anderson_malformed_report_rows_are_skipped_not_guessed():
    # Real defect in the source: per-acre overflowed the print column.
    bad = "035-03-01-001 OBERMILLER ROBERT L 031 41,627 .33873 *********"
    assert mod.ANDERSON_ROW_RE.match(bad) is None


def test_anderson_key_pads_the_board_form_of_a_tax_map():
    # Board carries '930802014'; the book prints '093-08-02-014'.
    assert mod._anderson_key("093-08-02-014") == "0930802014"
    assert mod._lead_keys(_lead(parcel_id="930802014")) == ["930802014", "0930802014"]


# --------------------------------------------------------------------------
# Matching / stamping
# --------------------------------------------------------------------------

def _rec(pin, deferred, total, bill_amt, bill="1-2025-2025-0010-00"):
    row = {"pin": pin, "bill": bill, "deferred_value": str(deferred),
           "total_value": str(total), "original_bill_amount": str(bill_amt),
           "levy_year": "2025"}
    return mod._buncombe_record([row], mod._pick_rate([row]), "parcel_bill")


def test_stamps_exposure_on_a_matching_buncombe_lead(monkeypatch):
    idx = {"9679090515": _rec("9679-09-0515-00000", 285500, 139500, 994)}
    _patch(monkeypatch, buncombe=idx)
    hit = _lead(state="NC", county="Buncombe", parcel_id="967909051500000",
                street_address="2111 RICEVILLE RD")
    miss = _lead(state="NC", county="Buncombe", parcel_id="1111111111")
    stats = _run([hit, miss])
    assert stats["matched"] == 1 and stats["matched_buncombe"] == 1
    assert stats["with_estimate"] == 1
    exp = hit.raw["rollback_exposure"]
    assert exp["deferred_value"] == 285500.0
    assert exp["match_method"] == "parcel"
    assert exp["basis"] == "present_use_deferral"
    assert exp["estimated_rollback"] > 0
    assert "rollback_exposure" not in (miss.raw or {})


def test_padded_and_bare_pins_join_to_the_same_parcel(monkeypatch):
    _patch(monkeypatch, buncombe={"9679090515": _rec("9679090515", 1000, 1000, 7)})
    padded = _lead(state="NC", county="Buncombe", parcel_id="967909051500000")
    bare = _lead(state="NC", county="Buncombe", parcel_id="9679-09-0515")
    _run([padded, bare])
    assert padded.raw["rollback_exposure"]["deferred_value"] == 1000.0
    assert bare.raw["rollback_exposure"]["deferred_value"] == 1000.0


def test_wrong_county_or_state_never_matches(monkeypatch):
    _patch(monkeypatch, buncombe={"9679090515": _rec("9679090515", 1000, 1000, 7)})
    # Same PIN digits, different county — must not cross-contaminate.
    other = _lead(state="NC", county="Henderson", parcel_id="9679090515")
    sc = _lead(state="SC", county="Buncombe", parcel_id="9679090515")
    stats = _run([other, sc])
    assert stats["matched"] == 0


def test_anderson_leads_match_the_book(monkeypatch):
    rows = mod.parse_anderson_book(BOOK_PDF, 2025)
    idx = {mod._anderson_key(r["tms"]): r for r in rows}
    monkeypatch.setattr(mod, "_ANDERSON_ON", True)
    _patch(monkeypatch, anderson=idx)
    tms = rows[0]["tms"]
    li = _lead(state="SC", county="Anderson",
               parcel_id=tms.replace("-", "").lstrip("0"))
    stats = _run([li])
    assert stats["matched_anderson"] == 1
    assert li.raw["rollback_exposure"]["state"] == "SC"
    assert li.raw["rollback_exposure"]["rollback_years"] == 3


def test_anderson_is_off_by_default(monkeypatch):
    """The 200-page pdfplumber parse must not fire unless asked for."""
    called = {"n": 0}

    async def fake_and(c):
        called["n"] += 1
        return {}

    async def fake_bun(c):
        return {}

    monkeypatch.setattr(mod, "_ANDERSON_ON", False)
    monkeypatch.setattr(mod, "_fetch_anderson", fake_and)
    monkeypatch.setattr(mod, "_fetch_buncombe", fake_bun)
    _run([_lead(state="SC", county="Anderson", parcel_id="0020001002")])
    assert called["n"] == 0


def test_kill_switch_short_circuits(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "1")
    stats = _run([_lead(state="NC", county="Buncombe", parcel_id="9679090515")])
    assert stats == {"targets": 0, "matched": 0, "matched_buncombe": 0,
                     "matched_anderson": 0, "matched_mecklenburg": 0, "matched_wake": 0,
                     "mecklenburg_live_confirmed": 0, "wake_live_confirmed": 0,
                     "with_estimate": 0}


def test_no_relevant_counties_skips_every_fetch(monkeypatch):
    calls = {"n": 0}

    async def boom(c):
        calls["n"] += 1
        return {}

    async def boom_rows(c):
        calls["n"] += 1
        return []

    monkeypatch.setattr(mod, "_fetch_buncombe", boom)
    monkeypatch.setattr(mod, "_fetch_anderson", boom)
    monkeypatch.setattr(mod, "_fetch_mecklenburg_candidates", boom_rows)
    _run([_lead(state="SC", county="Spartanburg", parcel_id="7091501300")])
    assert calls["n"] == 0


# --------------------------------------------------------------------------
# Mecklenburg NC: bulk GIS deferred-value + live rate top-up
# --------------------------------------------------------------------------

def _meck_row(pid, real, use, desc="AGRICULTURAL - COMMERCIAL PRODUCTION"):
    return {"pid": pid, "txt_propertyuse_desc": desc, "amt_landvalue": real,
            "amt_totalvalue": use, "situsaddress1": "1 TEST RD UNINC NC"}


# A minimal, hand-built stand-in for the live BillDetails.aspx markup (same element
# ids and table shape as the real page, fabricated owner-free values -- this repo's
# fixtures never carry a real person's data; see test_saved_bill_fixture_carries_no_
# personal_columns above for the same rule on the Buncombe fixture).
_MECK_DETAIL_HTML = """
<span id="lblParcel">00099999</span>
<span id="lblRealOriginal">$100,000</span>
<span id="lblDeferredOriginal">$90,000</span>
<span id="lblUseOriginal">$10,000</span>
<span id="lblTotalValue">$10,000</span>
<span id="dgShowResultRate_lblRate_0">.4927</span>
<span id="dgShowResultRate_taxDistricts_0">MECKLENBURG</span>
<span id="dgShowResultRate_description_0">Tax</span>
<span id="dgShowResultRate_amtBilled_0">$49.27</span>
<span id="dgShowResultRate_lblRate_1"> </span>
<span id="dgShowResultRate_taxDistricts_1">MECKLENBURG</span>
<span id="dgShowResultRate_description_1">Single Family Solid Waste Fee</span>
<span id="dgShowResultRate_amtBilled_1">$61.50</span>
<span id="dgShowResultRate_lblRate_2">.2930</span>
<span id="dgShowResultRate_taxDistricts_2">CHARLOTTE</span>
<span id="dgShowResultRate_description_2">Tax</span>
<span id="dgShowResultRate_amtBilled_2">$29.30</span>
"""


def test_mecklenburg_index_computes_deferred_as_real_minus_use():
    idx = mod._mecklenburg_index([_meck_row("00716203", 2012599, 616275)])
    rec = idx["00716203"]
    assert rec["deferred_value"] == pytest.approx(1396324.0)
    assert rec["basis"] == "present_use_deferral"
    assert rec["county"] == "Mecklenburg" and rec["state"] == "NC"


def test_mecklenburg_index_skips_a_parcel_with_no_real_deferral():
    """real == use (no present-use discount at all) must not be reported as a
    $0 'deferral' -- that is simply not a deferred parcel."""
    idx = mod._mecklenburg_index([_meck_row("1", 50000, 50000), _meck_row("2", 50000, 60000)])
    assert idx == {}


def test_parse_mecklenburg_bill_detail_sums_only_the_tax_rate_rows():
    rec = mod.parse_mecklenburg_bill_detail(_MECK_DETAIL_HTML)
    assert rec["parcel"] == "00099999"
    assert rec["real_value"] == 100000.0
    assert rec["deferred_value"] == 90000.0
    assert rec["use_value"] == 10000.0
    # .4927 + .2930, NOT the blank-rated fee row -> 0.7857/100 as a fraction.
    assert rec["combined_rate"] == pytest.approx(0.007857)
    assert rec["tax_rows"] == 2


def test_parse_mecklenburg_bill_detail_returns_none_without_a_value_table():
    assert mod.parse_mecklenburg_bill_detail("<html>no bill here</html>") is None


def test_stamps_exposure_on_a_matching_mecklenburg_lead_with_live_rate(monkeypatch):
    rows = [_meck_row("19705113", 810636, 7794, desc="FOREST - COMMERCIAL PRODUCTION")]
    topup = {"19705113": {"parcel": "19705113", "real_value": 810636.0,
                          "deferred_value": 802842.0, "use_value": 7794.0,
                          "combined_rate": 0.007177, "tax_rows": 1}}
    _patch(monkeypatch, mecklenburg=rows, meck_topup=topup)
    hit = _lead(state="NC", county="Mecklenburg", parcel_id="19705113")
    miss = _lead(state="NC", county="Mecklenburg", parcel_id="02951502")
    stats = _run([hit, miss])
    assert stats["matched_mecklenburg"] == 1
    assert stats["mecklenburg_live_confirmed"] == 1
    assert stats["with_estimate"] == 1
    exp = hit.raw["rollback_exposure"]
    assert exp["deferred_value"] == 802842.0
    assert exp["live_confirmed"] is True
    assert exp["rollback_years"] == 4
    assert exp["estimated_rollback"] == pytest.approx(802842.0 * 0.007177 * 4, rel=1e-4)
    assert "rollback_exposure" not in (miss.raw or {})


def test_mecklenburg_live_topup_failure_keeps_the_bulk_only_record(monkeypatch):
    """The live site being down must not erase the free bulk-GIS finding --
    it just means no dollar estimate is invented on top of it."""
    rows = [_meck_row("19705113", 810636, 7794)]
    _patch(monkeypatch, mecklenburg=rows, meck_topup={})   # topup returns None
    hit = _lead(state="NC", county="Mecklenburg", parcel_id="19705113")
    stats = _run([hit])
    assert stats["matched_mecklenburg"] == 1
    assert stats["mecklenburg_live_confirmed"] == 0
    exp = hit.raw["rollback_exposure"]
    assert exp["deferred_value"] == pytest.approx(802842.0)
    assert "estimated_rollback" not in exp
    assert "live_confirmed" not in exp


def test_mecklenburg_live_lookups_are_capped(monkeypatch):
    monkeypatch.setattr(mod, "_MECK_LIVE_CAP", 1)
    rows = [_meck_row("1", 100000, 1000), _meck_row("2", 100000, 1000)]
    calls = {"n": 0}

    async def counting_topup(c, pid):
        calls["n"] += 1
        return None

    _patch(monkeypatch, mecklenburg=rows)
    monkeypatch.setattr(mod, "_mecklenburg_live_topup", counting_topup)
    leads = [_lead(state="NC", county="Mecklenburg", parcel_id="1"),
             _lead(state="NC", county="Mecklenburg", parcel_id="2")]
    stats = _run(leads)
    assert stats["matched_mecklenburg"] == 2    # both get the free bulk finding
    assert calls["n"] == 1                       # only the capped live top-up fires once


# --------------------------------------------------------------------------
# Privacy / compliance guards
# --------------------------------------------------------------------------

def test_bills_request_never_uses_a_wildcard_field_list():
    """The bills layer carries owner names, mailing address, mortgage company
    and loan_num. outFields must stay enumerated."""
    assert "*" not in mod.BUNCOMBE_BILLS_FIELDS
    for banned in ("owner1", "owner2", "loan_num", "mortgage_co",
                   "address_line1", "postal_code"):
        assert banned not in mod.BUNCOMBE_BILLS_FIELDS


def test_saved_bill_fixture_carries_no_personal_columns():
    for row in BILLS:
        assert set(row) <= {"pin", "bill", "deferred_value", "total_value",
                            "original_bill_amount", "levy_due", "levy_year"}


# --------------------------------------------------------------------------
# Live smoke (opt-in)
# --------------------------------------------------------------------------

@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live smoke")
def test_live_buncombe_bills_layer_still_has_the_fields():
    import httpx
    r = httpx.get(mod.BUNCOMBE_BILLS_URL, params={
        "where": mod.BUNCOMBE_BILLS_WHERE, "outFields": mod.BUNCOMBE_BILLS_FIELDS,
        "returnGeometry": "false", "resultRecordCount": 5, "f": "json"}, timeout=60.0)
    data = r.json()
    assert "error" not in data
    assert data["features"], "deferred_value rows disappeared from the bills layer"
    a = data["features"][0]["attributes"]
    assert "deferred_value" in a and "original_bill_amount" in a
