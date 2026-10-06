"""verifiers/comps_buncombe.py: the board's sold comps against Buncombe's own parcel layer.

Fixture tests/fixtures/verification/comps_buncombe.json.gz: REAL responses of
property_bc_dis/MapServer/1 captured live on 2026-10-06 (situs + sale columns only, as the
verifier requests them) and six real 10/5 board rows (comps from the lazy-detail sidecar, owner and
other personal fields dropped) whose comps include the validation's hard cases: 140 Old Leicester Rd
(the confirmed MLS miskey), 117 Lookout Rd (a deed over 3 parcels), 4 Heather Way (really 4B),
205 Linden St (deed not on the layer yet), 44 Haw Creek Cir (no such street at that number),
78 and 80 Taylor St (two parcels), 12 Killian Ln (a new address; its sale is on record as 3
"99999 TATOOINE LN" lots); plus the layer's real (empty) answers for a street it does not have
("9 Nowhere Ln") and for a sale nobody recorded. No network."""
from __future__ import annotations

import asyncio
import copy
import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper import board_stream
from foreclosure_scraper import enrichment_comps
from foreclosure_scraper import enrichment_gis_sale_crosscheck as xc
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import from_module
from foreclosure_scraper.verification.verifiers import comps_buncombe as cb

FIX = json.loads(gzip.decompress(
    (Path(__file__).parent / "fixtures" / "verification" / "comps_buncombe.json.gz").read_bytes()))
RESP = FIX["responses"]
ROWS = FIX["rows"]
TODAY = date(2026, 10, 6)


def _row(name):
    return copy.deepcopy(ROWS[name])


def _run(row, fetcher=None, today=TODAY):
    return asyncio.run(cb.verify(row, fetcher if fetcher is not None else ReplayFetcher(RESP),
                                 today=today))


def _comp(res, address):
    return next(c for c in res.evidence["comps"] if c["address"].startswith(address))


# ---------------------------------------------------------------------------
# the contract
# ---------------------------------------------------------------------------

def test_module_meets_the_registry_contract():
    v = from_module(cb)
    assert (v.signal, v.version, v.identity) == ("comps", "v2", "property")
    assert v.governs == ()                       # informational: see the module docstring
    assert v.detail_keys == ("comps",)
    assert cb.ROW_SUMMARY_EXCLUDE == ("owner_name",)


def test_window_and_tolerances_are_the_pipelines_own():
    assert cb.FRESHNESS_WINDOW_DAYS == round(enrichment_comps.SOLD_WINDOW_MONTHS * 30)
    assert cb.PRICE_TOLERANCE == xc.PRICE_DISAGREEMENT_TOLERANCE
    assert cb.DATE_TOLERANCE_DAYS == xc.DATE_TOLERANCE_DAYS
    assert cb.LAYER_QUERY == xc.BUNCOMBE_PARCELS


def test_no_personal_column_is_ever_requested():
    cols = set(xc._BUNCOMBE_FIELDS.split(","))
    for personal in ("owner", "CareOf", "Address", "CityName", "Zipcode", "State"):
        assert personal not in cols
    for url in RESP:
        assert "owner" not in url.lower() and "CityName" not in url


# ---------------------------------------------------------------------------
# applies
# ---------------------------------------------------------------------------

def test_applies_to_buncombe_rows_with_comps_only():
    r = _row("140 old leicester")
    assert cb.applies(r)
    assert cb.applies({**r, "county": "Buncombe County"})
    assert not cb.applies({**r, "county": "Henderson"})
    assert not cb.applies({**r, "state": "SC"})
    slim = {**r, "raw": {"distress_stack": {"tier": "WARM"}}}   # board_stream row: no sidecar
    assert not cb.applies(slim)
    assert not cb.applies({**r, "raw": {"comps": []}})
    assert not cb.applies({**r, "raw": {"comps": [{"address": ""}]}})


# ---------------------------------------------------------------------------
# the live answers, replayed
# ---------------------------------------------------------------------------

LIVE = {  # what the 2026-10-06 live run answered for each row (same order, one client)
    "140 old leicester": ("refuted", "price_mismatch"),
    "44 haw creek": ("confirmed", None),
    "4 heather way": ("confirmed", None),
    "117 lookout": ("refuted", "price_mismatch"),
    "205 linden": ("confirmed", None),
    "78 and 80 taylor": ("confirmed", None),
    "739 patton cove": ("unconfirmed", "no_comp_resolvable"),
    "s turkey creek": ("refuted", "price_mismatch"),
}


def test_the_live_verdicts_reproduce_with_one_query_per_distinct_address():
    f = ReplayFetcher(RESP)
    got = {}
    for name in LIVE:
        res = _run(_row(name), f)
        got[name] = (res.verdict, res.evidence.get("reason"))
    assert got == LIVE
    assert len(f.asked) == len(set(f.asked)) == 20     # the per-run cache: never asked twice


def test_refuted_the_140_old_leicester_miskey():
    res = _run(_row("140 old leicester"))
    assert res.verdict == "refuted" and res.evidence["reason"] == "price_mismatch"
    c = _comp(res, "140 Old Leicester Rd")
    assert c["status"] == "mismatch" and c["reason"] == "price_differs_uncorrected"
    assert (c["board_price"], c["county_price"], c["delta"], c["delta_pct"]) == \
        (140000.0, 160000.0, 20000.0, 12.5)
    assert (c["claimed_sold_date"], c["deed_date"], c["date_gap_days"]) == \
        ("2026-04-06", "2026-04-06", 0)
    assert (c["county_stamps"], c["stamps_price"]) == (320.0, 160000)
    assert c["deed"] == "6581/0333" and c["deed_parcels"] == 1
    assert c["county_pin"] == "972073757600000"           # the RD parcel, not the HWY one
    assert c["match_basis"] == "street+date+price+stamps"
    assert res.evidence["comps_mismatched"] == 1 and res.evidence["comps_matched"] == 2


def test_a_deed_over_several_parcels_never_refutes():
    res = _run(_row("117 lookout"))
    c = _comp(res, "117 Lookout Rd")
    assert c["status"] == "unresolvable" and c["reason"] == "deed_covers_several_parcels"
    assert c["deed_parcels"] == 3 and c["county_price"] == 205000.0
    # the row is refuted by its OTHER comp, 140 Old Leicester Rd
    assert res.verdict == "refuted"
    assert _comp(res, "140 Old Leicester Rd")["status"] == "mismatch"


def test_a_unit_letter_the_comp_dropped_is_pinned_by_deed_date():
    res = _run(_row("4 heather way"))
    c = _comp(res, "4 Heather Way")
    assert c["status"] == "match" and c["candidates"] == 2
    assert c["match_basis"] == "street+date_pin+date+price+stamps"
    assert res.verdict == "confirmed" and res.evidence["comps_matched"] == 3


def test_unresolvable_comps_do_not_decide():
    res = _run(_row("205 linden"))
    assert _comp(res, "205 Linden St")["reason"] == "claimed_sale_not_recorded"
    assert res.verdict == "confirmed" and res.evidence["comps_unresolvable"] == 1
    res = _run(_row("78 and 80 taylor"))
    assert _comp(res, "78 and 80 Taylor St")["reason"] == "multi_parcel_address"
    res = _run(_row("44 haw creek"))
    c = _comp(res, "44 Haw Creek Cir")
    assert c["status"] == "unresolvable" and c["reason"] == "no_exact_street_match"


# ---------------------------------------------------------------------------
# the other rules, on the same real responses
# ---------------------------------------------------------------------------

def test_a_county_corrected_comp_matches():
    r = _row("140 old leicester")
    c = next(c for c in r["raw"]["comps"] if c["address"].startswith("140 Old Leicester"))
    c["sold_price_homeharvest"], c["sold_price"] = c["sold_price"], 160000.0
    res = _run(r)
    v = _comp(res, "140 Old Leicester Rd")
    assert v["status"] == "match" and v["county_correction_applied"] is True
    assert v["homeharvest_price"] == 140000.0 and v["match_basis"].endswith("+county_corrected")
    assert res.verdict == "confirmed"


def test_stale_once_every_comp_is_outside_the_freshness_window():
    r = _row("4 heather way")
    newest = date.fromisoformat(_run(r).evidence["newest_comp_sold"])
    res = _run(r, today=date.fromordinal(newest.toordinal() + cb.FRESHNESS_WINDOW_DAYS + 1))
    assert res.verdict == "stale" and res.evidence["reason"] == "comps_outside_freshness_window"
    assert res.evidence["comps_outside_window"] == 3
    res = _run(r, today=date.fromordinal(newest.toordinal() + cb.FRESHNESS_WINDOW_DAYS - 1))
    assert res.verdict == "confirmed"


def test_refuted_wins_over_stale():
    r = _row("140 old leicester")
    res = _run(r, today=date(2027, 6, 1))
    assert res.verdict == "refuted"


def test_a_missing_address_whose_sale_is_on_record_elsewhere_never_refutes():
    """739 Patton Cove Rd's comps (live): '12 Killian Ln' ($95,000, 2026-04-23) has no parcel,
    but a county-wide search finds the sale (3 '99999 TATOOINE LN' lots, deed 6586/1409); the
    two '99999' comps are the placeholder number of unaddressed lots."""
    res = _run(_row("739 patton cove"))
    k = _comp(res, "12 Killian Ln")
    assert k["status"] == "unresolvable" and k["reason"] == "sale_on_record_at_another_address"
    assert k["county_sales_matching"] == 3
    assert [c["reason"] for c in res.evidence["comps"] if c["address"].startswith("99999")] == \
        ["placeholder_house_number"] * 2
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_comp_resolvable"


def _single(address, zip_code, sold="2026-05-01 00:00:00", price=7654321.0):
    return {"state": "NC", "county": "Buncombe", "parcel_id": "9999999999", "street_address": "1 Test St",
            "raw": {"comps": [{"address": address, "zip": zip_code, "sold_price": price,
                               "sold_date": sold}]}}


def test_not_found_refutes_only_with_no_such_sale_anywhere_in_the_county():
    # real answers: the layer has no "9 Nowhere Ln", and no deed near $7,654,321 near 2026-05-01
    res = _run(_single("9 Nowhere Ln", "28806"))
    assert res.verdict == "refuted" and res.evidence["reason"] == "comp_not_on_county_record"
    c = res.evidence["comps"][0]
    assert c["status"] == "not_found" and c["reason"] == "no_parcel_and_no_such_sale"
    assert c["county_sales_matching"] == 0


def test_not_found_in_a_border_zip_or_recent_decides_nothing():
    for border in ("28732", "28704", "28787"):
        res = _run(_single("9 Nowhere Ln", border))
        assert res.verdict == "unconfirmed"
        assert res.evidence["comps"][0]["reason"] == "not_found_border_zip"
    f = ReplayFetcher(RESP)
    res = _run(_single("9 Nowhere Ln", "28806", sold="2026-08-01 00:00:00"), f)
    assert res.evidence["comps"][0]["reason"] == "not_found_recent_sale"
    assert res.verdict == "unconfirmed" and len(f.asked) == 1      # no county-wide search


def test_a_two_word_street_is_retried_broadly_before_not_found():
    f = ReplayFetcher(RESP)
    res = _run(_single("9 Nowhere Valley Ln", "28806"), f)
    assert len(f.asked) == 3 and res.verdict == "refuted"     # street, broad, sale search


def test_lookup_failures_are_unconfirmed_never_refuted():
    res = _run(_single("140 Old Leicester Rd", "28804"), ReplayFetcher({}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "lookup_failed"
    assert res.evidence["comps"][0]["status"] == "lookup_failed"
    parts = xc.parse_address("140 Old Leicester Rd")
    err = {cb.query_url(xc.street_where(parts)): json.dumps({"error": {"code": 500}})}
    res = _run(_single("140 Old Leicester Rd", "28804"), ReplayFetcher(err))
    assert res.verdict == "unconfirmed"


def test_a_failed_deed_count_never_refutes():
    parts = xc.parse_address("140 Old Leicester Rd")
    only_rows = {cb.query_url(xc.street_where(parts)): RESP[cb.query_url(xc.street_where(parts))]}
    res = _run(_single("140 Old Leicester Rd", "28804", sold="2026-04-06 00:00:00",
                       price=140000.0), ReplayFetcher(only_rows))
    assert res.verdict == "unconfirmed"
    assert res.evidence["comps"][0]["reason"] == "deed_count_error"


def test_a_parcel_picked_by_deed_date_alone_can_match_but_never_refute():
    parts = xc.parse_address("4 Heather Way")
    body = RESP[cb.query_url(xc.street_where(parts))]
    f = ReplayFetcher({cb.query_url(xc.street_where(parts)): body})
    res = _run(_single("4 Heather Way", "28715", sold="2026-08-27 00:00:00", price=300000.0), f)
    c = res.evidence["comps"][0]
    assert c["status"] == "unresolvable" and c["reason"] == "price_differs_identity_by_date_only"
    assert res.verdict == "unconfirmed"


def test_ambiguous_without_a_sold_date():
    parts = xc.parse_address("4 Heather Way")
    f = ReplayFetcher({cb.query_url(xc.street_where(parts)): RESP[cb.query_url(xc.street_where(parts))]})
    res = _run(_single("4 Heather Way", "28715", sold=None), f)
    assert res.evidence["comps"][0]["reason"] == "ambiguous_parcel"
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_comp_resolvable"


def test_no_comps_is_unconfirmed():
    res = _run({"state": "NC", "county": "Buncombe", "raw": {}}, ReplayFetcher({}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_comps"


# ---------------------------------------------------------------------------
# privacy and scoring
# ---------------------------------------------------------------------------

def test_evidence_is_the_whitelist_and_names_nobody():
    for name in LIVE:
        res = _run(_row(name))
        assert set(res.evidence) <= set(cb._TOP_FIELDS) | {"comps"}
        for c in res.evidence["comps"]:
            assert set(c) <= set(cb._COMP_FIELDS)
        blob = json.dumps(res.to_dict()).lower()
        assert "owner" not in blob and "url" not in json.dumps(res.evidence["comps"])


def test_a_refuted_comp_set_removes_no_scorer_signal():
    res = _run(_row("140 old leicester"))
    rec = {**res.to_dict(), "governs": list(cb.GOVERNS),
           "expires_at": core.expires_at(res.checked_at, cb.TTL_DAYS)}
    raw = {"verification": [rec]}
    assert core.suppressed_scorer_signals(raw, TODAY) == set()
    assert core.verdict_badges(raw, core.parse_ts(res.checked_at)) == {"comps": "refuted"}


# ---------------------------------------------------------------------------
# the lazy-detail sidecar, streamed beside the board (board_stream + the sweep)
# ---------------------------------------------------------------------------

def _gz(path, rows):
    path.write_bytes(gzip.compress(json.dumps(rows).encode()))


@pytest.fixture
def board(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    slim = []
    detail = []
    for name in ("140 old leicester", "4 heather way"):
        r = _row(name)
        comps = r["raw"].pop("comps")
        slim.append(r)
        detail.append({"comps": comps, "vision": {"big": "x" * 50}})
    slim.append({"state": "NC", "county": "Henderson", "parcel_id": "1", "raw": {}})
    detail.append({})
    _gz(docs / "listings.json.gz", slim)
    _gz(docs / "listings_detail.json.gz", detail)
    return docs


def test_iter_board_rows_with_detail_merges_only_the_named_keys(board):
    rows = list(board_stream.iter_board_rows_with_detail(board / "listings.json.gz", ("comps",)))
    assert [len(r["raw"].get("comps") or []) for r in rows] == [3, 3, 0]
    assert all("vision" not in r["raw"] for r in rows)
    assert list(board_stream.iter_board_rows_with_detail(board / "listings.json.gz", ())) == \
        list(board_stream.iter_board_rows(board / "listings.json.gz"))


def test_a_misaligned_sidecar_is_refused(board):
    _gz(board / "listings_detail.json.gz", [{}])
    with pytest.raises(Exception, match="not index-aligned"):
        list(board_stream.iter_board_rows_with_detail(board / "listings.json.gz", ("comps",)))


def test_a_sidecar_that_disagrees_with_the_manifest_is_refused(board):
    (board / "board.manifest.json").write_text(json.dumps({
        "schema": "board-manifest-v1", "count": 3, "detail_count": 3,
        "files": {"listings_detail.json.gz": {"bytes": 1, "sha256": "0" * 64}}}))
    with pytest.raises(Exception, match="manifest"):
        board_stream.detail_source(board)


def _load_sweep():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verification_sweep", Path(__file__).resolve().parent.parent / "scripts" / "verification_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_sweep_selects_comps_rows_from_the_sidecar(board):
    from datetime import datetime, timezone
    from foreclosure_scraper.verification import ledger as L
    sw = _load_sweep()
    v = from_module(cb)
    plan, why = sw.select(board / "listings.json.gz", [v], {"comps": L.Ledger("comps")},
                          county=None, cap=10, now=datetime(2026, 10, 6, tzinfo=timezone.utc))
    assert why["comps"]["applies"] == 2 and len(plan["comps"]) == 2
    (board / "listings_detail.json.gz").unlink()      # no sidecar: nothing applies, no crash
    plan, why = sw.select(board / "listings.json.gz", [v], {"comps": L.Ledger("comps")},
                          county=None, cap=10, now=datetime(2026, 10, 6, tzinfo=timezone.utc))
    assert plan["comps"] == [] and why["comps"]["applies"] == 0
