"""tax_lien_york v1: York County SC's own Tax Sale Properties ArcGIS layer. Presence in the
loaded layer snapshot confirms the claim; absence from a COMPLETE snapshot makes it stale (the
county drops a resolved parcel from the view rather than flipping a field in place -- live-
checked 2026-10-18, SOLD='N' on all 853 current features, zero 'Y'). Hand-written layer answers
in the ArcGIS REST shape with made-up parcels and owners. No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover, from_module
from foreclosure_scraper.verification.verifiers import _arcgis_layer as ag
from foreclosure_scraper.verification.verifiers import tax_lien_york as p

TODAY = date(2026, 10, 18)
EDIT = datetime(2026, 9, 29, 11, 53, 33, tzinfo=timezone.utc)

PARCEL_A = "6320902008"      # on the live layer
PARCEL_B = "5550000151"      # on the live layer, matched via TAXMAPID instead of ParcelID
PARCEL_GONE = "9999999999"   # not on the live layer -- resolved since the roll was scraped

ROWS = [
    {"ParcelID": PARCEL_A, "TAXMAPID": "", "NAME": "TESTOWNER JADE CAPITAL LLC", "SOLD": "N"},
    {"ParcelID": "", "TAXMAPID": PARCEL_B, "ownernames": "TESTOWNER BECKFORD", "SOLD": "N"},
]


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def serve(rows=None, *, drop_count=False, drop_page=False, count_override=None) -> ReplayFetcher:
    rows = ROWS if rows is None else rows
    resp: dict = {
        ag.meta_url(p.LAYER): json.dumps({"editingInfo": {"dataLastEditDate": _ms(EDIT)}}),
    }
    if not drop_count:
        resp[ag.count_url(p.LAYER)] = json.dumps(
            {"count": len(rows) if count_override is None else count_override})
    if not drop_page:
        resp[ag.page_url(p.LAYER, out_fields=p.OUT_FIELDS, order_by="OBJECTID", offset=0,
                         page=2000)] = json.dumps(
            {"features": [{"attributes": a} for a in rows]})
    return ReplayFetcher(resp)


def row(parcel=PARCEL_A, *, owner="TESTOWNER JADE CAPITAL LLC", **kw):
    r = {"state": "SC", "county": "York", "listing_type": "tax_sale",
         "source": p.SOURCE_SLUG, "parcel_id": parcel, "owner_name": owner,
         "raw": {"york_delinquent_tax": {"parcel_id": parcel}}}
    r.update(kw)
    return r


def run(r, f, today=TODAY):
    return asyncio.run(p.verify(r, f, today=today))


def test_applies_only_to_york_tax_sale_rows():
    assert p.applies(row())
    assert not p.applies(row(county="Lancaster"))
    assert not p.applies(row(state="NC"))
    assert not p.applies(row(source="counties_sc.other_source"))
    assert not p.applies({"state": "SC", "county": "York", "listing_type": "foreclosure",
                          "source": p.SOURCE_SLUG, "parcel_id": "1", "raw": {}})


def test_registered_once_as_tax_lien():
    v = from_module(p)
    assert v.signal == "tax_lien" and v.name == "tax_lien_york"
    assert v.governs == tuple(p.GOVERNS)
    others = [v for v in discover() if v.signal == "tax_lien" and v.name != "tax_lien_york"]
    assert not any(o.source == p.SOURCE for o in others)


def test_a_parcel_still_on_the_list_is_confirmed_matched_by_parcelid():
    r = run(row(PARCEL_A), serve())
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["still_listed"] is True and r.evidence["owner_match"] == "same"


def test_a_parcel_matched_only_by_taxmapid_is_also_confirmed():
    r = run(row(PARCEL_B, owner="TESTOWNER BECKFORD"), serve())
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["owner_match"] == "same"


def test_an_owner_mismatch_is_reported_but_still_confirmed():
    """Exact parcel match binds confirmed whatever name the county's own record carries --
    owner_match is informational evidence, not a gate, same rule the sibling verifiers use for
    an exact parcel number."""
    r = run(row(PARCEL_A, owner="SOMEONE ELSE ENTIRELY"), serve())
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "differs"


def test_a_parcel_no_longer_on_the_list_is_stale():
    r = run(row(PARCEL_GONE), serve())
    assert r.verdict == "stale", r.evidence
    assert r.evidence["still_listed"] is False


def test_a_row_with_no_parcel_id_is_unconfirmed_without_a_request():
    f = serve()
    r = run(row(parcel_id=None), f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_parcel"
    assert f.asked == []


def test_an_incomplete_snapshot_never_decides_stale():
    """The jail-verifier rule applies here too: a count/page mismatch must not read as 'the
    parcel left the list' -- only a COMPLETE snapshot can say that."""
    r = run(row(PARCEL_GONE), serve(count_override=5))      # count says 5, only 2 rows served
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"


def test_a_failed_layer_load_is_unconfirmed_not_stale():
    r = run(row(PARCEL_GONE), serve(drop_count=True))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"


def test_the_layer_loads_once_and_is_shared_across_rows():
    f = serve()
    r1 = run(row(PARCEL_A), f)
    r2 = run(row(PARCEL_B, owner="TESTOWNER BECKFORD"), f)
    assert r1.verdict == "confirmed" and r2.verdict == "confirmed"
    # meta + count + one page = 3 requests total, however many rows asked
    assert len(f.asked) == 3
