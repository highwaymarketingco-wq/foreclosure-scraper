"""merge_prior_board: a shared URL key alone does not fold two records of different counties or
owners (W2), and a prior VALID parcel beats a fresh short id or a resolver-attached parcel while
data fields stay fresh (W3). Audit 2026-10-09 regressions section 7. Every row here is made up."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from foreclosure_scraper import tax_binding as tb
from foreclosure_scraper.board_persist import keep_prior_valid_parcel, merge_prior_board
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

NOW = datetime(2026, 10, 9)


def _li(source="counties_nc.sample_roll", parcel=None, street=None, zip_code=None, owner="ALPHA ANN",
        county="Sample", url="https://x.invalid/roll.pdf", raw=None):
    return Listing(source=source, source_url=url, listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state="NC", county=county, parcel_id=parcel,
                   street_address=street, zip_code=zip_code, owner_name=owner,
                   first_seen=NOW, last_seen=NOW, raw=raw or {})


def _board(tmp: Path, rows: list[Listing]) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp


# ------------------------------------------------------------------ W2

def test_url_key_alone_does_not_fold_another_owner(tmp_path):
    prior = _li(owner="BETA BOB", raw={"vision": {"score": 2}})
    fresh = _li(owner="ALPHA ANN")
    out, stats = merge_prior_board([fresh], docs_dir=_board(tmp_path, [prior]), now=NOW)
    assert stats["matched"] == 0 and stats["refused_url_key_conflict"] == 1
    assert len(out) == 2                                   # the prior row ages beside the fresh one
    assert "vision" not in next(r for r in out if r.owner_name == "ALPHA ANN").raw


def test_url_key_folds_the_same_record(tmp_path):
    prior = _li(owner="ALPHA ANN", raw={"vision": {"score": 2}})
    out, stats = merge_prior_board([_li(owner="ALPHA ANN")], docs_dir=_board(tmp_path, [prior]), now=NOW)
    assert stats["matched"] == 1 and len(out) == 1 and out[0].raw["vision"] == {"score": 2}
    assert not stats.get("refused_url_key_conflict")


# ------------------------------------------------------------------ W3

def test_prior_valid_parcel_beats_a_fresh_short_id_and_keeps_it_as_alias(tmp_path):
    prior = _li(source="counties_nc.sample_vacant", parcel="3541-27-6809", street="11 Test Rd",
                zip_code="28000", raw={"owner_phone": {"phone": "(555) 010-0000", "match": "parcel_id"}})
    fresh = _li(source="counties_nc.sample_roll", parcel="54321", street="11 Test Rd", zip_code="28000",
                raw={"sample_roll": {"balance": 12.0}})
    out, stats = merge_prior_board([fresh], docs_dir=_board(tmp_path, [prior]), now=NOW)
    assert stats["matched"] == 1 and stats["prior_parcel_kept_short"] == 1
    row = out[0]
    assert row.parcel_id == "3541-27-6809"
    assert row.raw["parcel_id_alias"] == {"short": "54321", "long": "3541-27-6809"}
    assert "54321" in tb.row_ids(row)                     # the short id is still the row's own
    assert row.raw["sample_roll"] == {"balance": 12.0}     # data stays fresh
    assert row.raw["owner_phone"]["phone"] == "(555) 010-0000"


def test_prior_valid_parcel_beats_a_resolver_parcel():
    prior = _li(parcel="3541-27-6809", street="11 Test Rd", zip_code="28000")
    fresh = _li(parcel="3541-27-6899", street="11 Test Rd", zip_code="28000",
                raw={"parcel_from_address": {"source": "parcel_cache_situs_address"}})
    merged = fresh.merge(prior)
    assert keep_prior_valid_parcel(fresh, prior, merged) == "resolver"
    assert merged.parcel_id == "3541-27-6809"
    assert merged.raw["parcel_id_superseded"]["value"] == "3541-27-6899"
    assert "3541-27-6899" not in tb.row_ids(merged)


def test_a_fresh_valid_own_parcel_and_a_fallback_prior_parcel_stay_fresh():
    prior = _li(parcel="3541-27-6809")
    own = _li(parcel="3541-27-6899")                       # the scraper's own valid id: fresh wins
    m = own.merge(prior)
    assert keep_prior_valid_parcel(own, prior, m) is None and m.parcel_id == "3541-27-6899"
    fb = _li(parcel="3541-27-6809", raw={"geo_imprecise": "centroid_snap",
                                         "parcel_from_geo": {"lat": 35.1, "lng": -81.1}})
    short = _li(parcel="54321")
    m2 = short.merge(fb)
    assert keep_prior_valid_parcel(short, fb, m2) is None and m2.parcel_id == "54321"
