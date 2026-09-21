"""The apply_rows contract every 2026-09-21 fix script exposes for the single-process driver:

    apply_rows(rows, *, dry_run=False) -> dict     mutates Listing objects in place, never changes len(rows),
                                                   returns counts, '_backup' carries anything it replaced.

dry_run=True mutates nothing; a real run refuses (RuntimeError) before touching any row when a raw key it
stamps is not in RAW_KEEP.
"""
from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _dq_common as C  # noqa: E402
import backfill_missing_county as B  # noqa: E402
import fill_address_from_parcel as F  # noqa: E402
import map_account_ids_to_parcels as M  # noqa: E402
import promote_ptscloud_block as P  # noqa: E402
import quarantine_flip_leaks as Q  # noqa: E402
import undo_resolver_middle_conflicts as U  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _li(**kw):
    base = dict(source="counties_sc.x", source_url="https://example.invalid/1", listing_type=ListingType.TAX_LIEN,
                state="SC", county="Darlington")
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def registered(monkeypatch):
    """Pretend every raw key is registered in RAW_KEEP."""
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: [])


@pytest.fixture
def unregistered(monkeypatch):
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: list(keys))


def _snapshot(rows):
    return [copy.deepcopy(r.model_dump(mode="json")) for r in rows]


# ---- fill_address_from_parcel --------------------------------------------------------------------------
def _fill_rows():
    return [_li(parcel_id="100-00-02-141.000", street_address=None, raw={}),
            _li(parcel_id="", street_address=None, raw={}),
            _li(parcel_id="1", street_address="12 OAK ST", raw={})]


def _fake_lookup(monkeypatch):
    def fake(county, state, pid):
        return True, {"address": "437 SEMINOLE DR", "owner_mailing": "437 SEMINOLE DR HARTSVILLE SC 29550"}, "zero_suffix", None
    monkeypatch.setattr(F, "_lookup", fake)


def test_fill_dry_run_mutates_nothing_and_a_real_run_fills(monkeypatch, registered):
    _fake_lookup(monkeypatch)
    rows = _fill_rows()
    before = _snapshot(rows)
    res = F.apply_rows(rows, dry_run=True)
    assert _snapshot(rows) == before and res["filled"] == 1 and res["skip_no_parcel"] == 1
    res = F.apply_rows(rows)
    assert len(rows) == 3 and rows[0].street_address == "437 SEMINOLE DR"
    assert rows[0].city == "Hartsville" and rows[0].zip_code == "29550"
    assert rows[0].raw["situs_address_source"] == "parcel_cache:zero_suffix"
    assert rows[2].street_address == "12 OAK ST"                       # already numbered: untouched
    assert "_backup" not in res


def test_fill_upgrade_returns_the_replaced_street_as_backup(monkeypatch, registered):
    _fake_lookup(monkeypatch)
    monkeypatch.setattr(F, "_lookup", lambda c, s, p: (True, {"address": "437 SEMINOLE DR"}, "exact", None))
    rows = [_li(parcel_id="9", street_address="SEMINOLE DR", raw={})]
    res = F.apply_rows(rows)
    assert rows[0].street_address == "437 SEMINOLE DR"
    assert next(iter(res["_backup"].values()))["street_address"] == "SEMINOLE DR"
    assert rows[0].raw["situs_road_only"]["road"] == "SEMINOLE DR"


# ---- backfill_missing_county ---------------------------------------------------------------------------
def _ev():
    ev = B.Evidence()
    ev.cache_zip["NC|28717"] = Counter({"Jackson": 86})
    ev.board_zip["NC|28717"] = Counter({"Jackson": 12})
    return ev


def test_county_backfill_fills_only_blank_counties(registered):
    rows = [_li(state="NC", county=None, zip_code="28717", raw={}),
            _li(state="NC", county="Swain", zip_code="28717", raw={}),
            _li(state="SC", county=None, raw={})]
    before = _snapshot(rows)
    res = B.apply_rows(rows, dry_run=True, evidence=_ev())
    assert _snapshot(rows) == before and res["resolved"] == 1 and res["none"] == 1
    res = B.apply_rows(rows, evidence=_ev())
    assert rows[0].county == "Jackson" and rows[0].raw["county_backfill"]["evidence"] == "zip"
    assert rows[1].county == "Swain"                                    # never overwritten
    assert rows[2].county is None and len(rows) == 3


# ---- quarantine_flip_leaks -----------------------------------------------------------------------------
def test_quarantine_stamps_leaks_clears_stale_stamps_and_moves_nothing(registered):
    rows = [_li(listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Charleston", raw={}),
            _li(listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Spartanburg", raw={"scope": Q.STAMP}),
            _li(listing_type=ListingType.TAX_LIEN, state="SC", county="Charleston", raw={}),
            _li(listing_type=ListingType.REO, state="NC", county=None, raw={})]
    before = _snapshot(rows)
    res = Q.apply_rows(rows, dry_run=True)
    assert _snapshot(rows) == before and res["stamped"] == 1
    res = Q.apply_rows(rows)
    assert rows[0].raw["scope"] == Q.STAMP
    assert "scope" not in rows[1].raw                                   # now in the footprint: stamp cleared
    assert "scope" not in rows[2].raw                                   # a lead, not a flip
    assert "scope" not in rows[3].raw and len(rows) == 4                # no county, not derived: left alone
    assert rows[0].county == "Charleston" and rows[0].street_address is None       # nothing else changed


# ---- promote_ptscloud_block ----------------------------------------------------------------------------
def test_promote_swaps_the_pts_number_and_returns_the_old_id():
    blk = {"parcel": "9941506", "owner": "DALTON, DWIGHT", "assessed_value": 36300.0, "prop_size": "0.94 AC",
           "mailing": {"addr1": "RT 1 BOX 218", "addr2": "HENDERSONVILLE, NC, 28792", "addr3": None}}
    rows = [_li(source=P.SRC_KEY and "counties_nc.nc_ptscloud_delinquent_tax", state="NC", county="Henderson",
                listing_type=ListingType.TAX_LIEN, parcel_id="9941506", owner_name="DALTON, DWIGHT",
                assessed_value=36300.0, acreage=0.94, legal_description="X",
                raw={"nc_ptscloud_delinquent_tax": blk,
                     "owner_mailing": {"mailing": "PO BOX 245 EDNEYVILLE NC 28727", "parcel_id": "0601560094"}})]
    look = lambda pin: {"owner": "THE DWIGHT E. DALTON REVOCABLE LIVING TRUST;DALTON, DWIGHT E."}    # noqa: E731
    before = _snapshot(rows)
    res = P.apply_rows(rows, dry_run=True, cache_lookup=look)
    assert _snapshot(rows) == before and res["parcel_id PTS -> PIN"] == 1
    res = P.apply_rows(rows, cache_lookup=look)
    assert rows[0].parcel_id == "0601560094"
    assert rows[0].raw["parcel_from_geo"]["pts_number"] == "9941506"
    assert next(iter(res["_backup"].values()))["old_parcel_id"] == "9941506"
    assert rows[0].raw["nc_ptscloud_delinquent_tax"]["parcel"] == "9941506"      # the block keeps it too


# ---- map_account_ids_to_parcels ------------------------------------------------------------------------
def test_laurens_account_number_is_replaced_by_the_block_tms():
    rows = [_li(county="Laurens", parcel_id="000789",
                raw={"qpaybill_roll": {"identification_no": "000789", "detail": {"map_number": "094-00-00-036.002"}}})]
    res = M.apply_rows(rows, dry_run=True, cache_lookup=lambda p: None)
    assert rows[0].parcel_id == "000789" and res["Laurens account number -> TMS"] == 1
    res = M.apply_rows(rows, cache_lookup=lambda p: None)
    assert rows[0].parcel_id == "094-00-00-036.002" and rows[0].raw["qpaybill_roll"]["identification_no"] == "000789"
    assert next(iter(res["_backup"].values()))["old_parcel_id"] == "000789"


# ---- undo_resolver_middle_conflicts --------------------------------------------------------------------
def _resolved_row(source="counties_sc.sc_public_index", **kw):
    base = dict(source=source, county="Spartanburg", parcel_id="712207947183", street_address="922 LOGAN ST SPARTANBURG",
                market_value=14600.0, living_sqft=1150.0, owner_name="EVANS DAVID N", defendant="David Lee Evans",
                raw={"resolved_from_name": {"queried": True, "confidence": "strong", "matched_owner": "EVANS DAVID N",
                                            "query_name": "David Lee Evans"},
                     "gis": {"owner": "EVANS DAVID N"}, "owner_mailing": {"mailing": "1 X ST"}})
    base.update(kw)
    return _li(**base)


def test_undo_blanks_a_resolver_owned_lead_and_keeps_what_it_removed(registered):
    # sc_public_index rows are name-only, so give the rates something to read from
    filler = [_li(source="counties_sc.sc_public_index", parcel_id=None, street_address=None, raw={}) for _ in range(9)]
    rows = filler + [_resolved_row()]
    before = _snapshot(rows)
    res = U.apply_rows(rows, dry_run=True)
    assert _snapshot(rows) == before and res["proven conflicts"] == 1
    res = U.apply_rows(rows)
    li = rows[-1]
    assert li.parcel_id is None and li.street_address is None and li.market_value is None and li.owner_name is None
    assert li.defendant == "David Lee Evans"                            # the lead's own name is kept
    assert "gis" not in li.raw and "owner_mailing" not in li.raw
    u = li.raw["resolver_conflict_undone"]
    assert u["action"] == "blanked" and u["removed"]["parcel_id"] == "712207947183"
    assert u["removed"]["raw"]["gis"] == {"owner": "EVANS DAVID N"}
    assert li.raw["resolved_from_name"]["confidence"] == "middle_conflict_undone"
    assert li.raw["resolved_from_name"]["confidence_before"] == "strong"
    assert len(rows) == 10 and res["_backup"]


def test_undo_only_flags_a_lead_merged_with_a_parcel_native_source(registered):
    filler = [_li(source="counties_sc.spartanburg_vacant", parcel_id="1", street_address="1 A ST", raw={}) for _ in range(9)]
    rows = filler + [_resolved_row(source="counties_sc.spartanburg_vacant")]
    U.apply_rows(rows)
    li = rows[-1]
    assert li.parcel_id == "712207947183" and li.street_address == "922 LOGAN ST SPARTANBURG"
    assert li.raw["resolver_conflict_undone"]["action"] == "flag_only"


def test_undo_leaves_agreeing_and_unverifiable_resolutions_alone(registered):
    ok = _resolved_row(defendant="David N Evans")
    ok.raw["resolved_from_name"]["query_name"] = "David N Evans"
    rows = [ok]
    U.apply_rows(rows)
    assert rows[0].parcel_id == "712207947183" and "resolver_conflict_undone" not in rows[0].raw


# ---- the RAW_KEEP refusal ------------------------------------------------------------------------------
@pytest.mark.parametrize("mod", [F, B, Q, P, M, U])
def test_a_real_run_refuses_before_touching_a_row_when_a_raw_key_is_unregistered(mod, unregistered):
    rows = [_li(raw={})]
    before = _snapshot(rows)
    with pytest.raises(RuntimeError, match="RAW_KEEP"):
        if mod is B:
            mod.apply_rows(rows, evidence=_ev())
        else:
            mod.apply_rows(rows)
    assert _snapshot(rows) == before


@pytest.mark.parametrize("mod", [F, B, Q, P, M, U])
def test_every_script_declares_its_required_raw_keys(mod):
    assert isinstance(mod.REQUIRED_RAW_KEYS, list) and mod.REQUIRED_RAW_KEYS
