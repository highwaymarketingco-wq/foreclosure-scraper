"""scripts/backfill_multiyear_tax_restatement.py: classification/bucketing and patch-building
logic, on synthetic fixtures. No real board, no real network -- board_stream.iter_board_rows()
is monkeypatched to yield board-shaped dicts built the same way test_backfill_deed_ref_bound.py
does (Listing.model_dump(mode="json")), and board_lock()/patch_existing_rows() are never reached
by these tests (they only exercise _collect_candidates()/_build_patches(), the Phase 1 seam --
same reasoning as that file's own tests: the write side is already covered by
backfill_deed_ref_bound.py's watchdog tests, reused verbatim here).
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_multiyear_tax_restatement as bb  # noqa: E402

from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402

TODAY = date(2026, 10, 18)


def _listing(**kw) -> Listing:
    base = dict(source="counties_sc.qpaybill_delinquent_roll", source_url="https://example/1",
                listing_type=ListingType.TAX_SALE, property_kind=PropertyKind.UNKNOWN,
                state="SC", county="Horry", parcel_id="44305030067")
    base.update(kw)
    return Listing(**base)


def _board_dict(li: Listing) -> dict:
    """What iter_board_rows() would actually yield for this row -- a plain dict, same shape
    json.loads(listings.json) produces, not a Listing object."""
    return li.model_dump(mode="json")


def _fake_iter(rows, monkeypatch):
    monkeypatch.setattr(bb, "iter_board_rows", lambda *_a, **_kw: iter(rows))


# ---------------------------------------------------------------------------------------------
# qpaybill (SC) source rows
# ---------------------------------------------------------------------------------------------

def _qr(ident="44305030067", balance=100.0, years_unpaid=None) -> dict:
    years_unpaid = years_unpaid if years_unpaid is not None else ["2023", "2024"]
    return {"identification_no": ident, "is_account_id_not_parcel": False, "county": "Horry",
            "subdomain": "horrycountytreasurer", "balance_owed": balance,
            "years_unpaid": years_unpaid, "all_unpaid_years": years_unpaid,
            "years_delinquent": len(years_unpaid), "is_two_year_plus": len(years_unpaid) >= 2}


def test_qpaybill_row_classified_and_patched():
    li = _listing(parcel_id="44305030067", county="Horry", state="SC",
                  raw={"qpaybill_roll": _qr()})
    rows = [_board_dict(li)]
    buckets, total, conflicts, ambiguity = bb._collect_candidates_from_rows(rows)
    assert total == 1
    assert conflicts == 0
    assert ambiguity["rows_total"] == 0
    assert len(buckets["qpaybill"]) == 1
    assert len(buckets["ptscloud"]) == 0
    assert len(buckets["its_public"]) == 0

    c: Counter = Counter()
    patches = bb._build_patches(buckets, c)
    assert len(patches) == 1
    (key, patch), = patches.items()
    assert "two_year_delinquent" in patch["raw"]
    assert "multi_year_delinquent_tax" in patch["raw"]
    assert patch["raw"]["multi_year_delinquent_tax"]["years"] == [2023, 2024]
    assert c["qpaybill_patched"] == 1


def test_qpaybill_row_single_year_gets_two_year_block_but_not_multiyear():
    """Single-year qpaybill_roll: two_year_delinquent is still written (unconditional per the
    source module), multi_year_delinquent_tax is not (gate: MIN_YEARS=2)."""
    li = _listing(parcel_id="44305030067", county="Horry", state="SC",
                  raw={"qpaybill_roll": _qr(years_unpaid=["2025"])})
    rows = [_board_dict(li)]
    buckets, *_ = bb._collect_candidates_from_rows(rows)
    c: Counter = Counter()
    patches = bb._build_patches(buckets, c)
    assert len(patches) == 1
    (_, patch), = patches.items()
    assert patch["raw"] == {"two_year_delinquent": {
        "is_two_year_plus": False, "years": 1, "oldest_year": 2025,
        "source": "counties_sc.qpaybill_delinquent_roll"}}


# ---------------------------------------------------------------------------------------------
# ptscloud (NC) source rows
# ---------------------------------------------------------------------------------------------

def _bill_ptscloud(year: str, total_due: float) -> dict:
    return {"tax_year": year, "bill_number": f"B-{year}", "total_due": total_due,
            "bill_status": "DELINQUENT", "bill_due_date": f"{year}-01-05"}


def test_ptscloud_row_classified_and_patched():
    by_year = [_bill_ptscloud("2023", 45.0), _bill_ptscloud("2024", 48.0)]
    li = _listing(source="counties_nc.nc_ptscloud_delinquent_tax", parcel_id="6869430725",
                  county="Forsyth", state="NC",
                  raw={"nc_ptscloud_delinquent_tax": {"by_year": by_year, "tenant": "Forsyth"}})
    rows = [_board_dict(li)]
    buckets, total, conflicts, ambiguity = bb._collect_candidates_from_rows(rows)
    assert len(buckets["ptscloud"]) == 1
    assert len(buckets["qpaybill"]) == 0
    assert len(buckets["its_public"]) == 0

    c: Counter = Counter()
    patches = bb._build_patches(buckets, c)
    assert len(patches) == 1
    (_, patch), = patches.items()
    assert patch["raw"]["multi_year_delinquent_tax"]["years"] == [2023, 2024]
    assert patch["raw"]["multi_year_delinquent_tax"]["amount_basis"] == "annual_bill"
    assert c["ptscloud_patched"] == 1


# ---------------------------------------------------------------------------------------------
# its_public (NC) source rows
# ---------------------------------------------------------------------------------------------

def _bill_its_public(year: int, balance: float) -> dict:
    return {"year": year, "bill": f"B-{year}", "balance": balance, "status": None}


def test_its_public_row_classified_and_patched():
    bills = [_bill_its_public(2023, 219.16), _bill_its_public(2024, 203.59)]
    src = {"county": "Duplin", "portal": "https://www.bttaxpayerportal.com/ITSPublicDL",
           "parcel": "DL-1", "years": [2023, 2024], "bills": bills}
    li = _listing(source="counties_nc.nc_its_public_tax", parcel_id="DL-1", county="Duplin",
                  state="NC", raw={"nc_its_public_tax": src})
    rows = [_board_dict(li)]
    buckets, total, conflicts, ambiguity = bb._collect_candidates_from_rows(rows)
    assert len(buckets["its_public"]) == 1
    assert len(buckets["qpaybill"]) == 0
    assert len(buckets["ptscloud"]) == 0

    c: Counter = Counter()
    patches = bb._build_patches(buckets, c)
    assert len(patches) == 1
    (_, patch), = patches.items()
    assert patch["raw"]["multi_year_delinquent_tax"]["years"] == [2023, 2024]
    assert c["its_public_patched"] == 1


# ---------------------------------------------------------------------------------------------
# no-op row: none of the three source keys present
# ---------------------------------------------------------------------------------------------

def test_row_with_none_of_the_three_source_keys_is_not_a_candidate():
    li = _listing(raw={"some_other_block": {"x": 1}})
    rows = [_board_dict(li)]
    buckets, total, conflicts, ambiguity = bb._collect_candidates_from_rows(rows)
    assert total == 1
    assert conflicts == 0
    assert all(len(b) == 0 for b in buckets.values())
    c: Counter = Counter()
    assert bb._build_patches(buckets, c) == {}


def test_row_already_restated_is_a_noop_patch():
    """A row whose qpaybill_roll block already has both canonical keys written (e.g. a prior run
    of this same backfill, or a real pipeline run) is eligible (carries qpaybill_roll) but
    produces no patch -- enrich_qpaybill_multiyear_tax()'s own _already_done() gate is reused
    verbatim via the real production function, not re-implemented here."""
    li = _listing(raw={"qpaybill_roll": _qr(),
                       "two_year_delinquent": {"is_two_year_plus": True, "years": 2,
                                               "oldest_year": 2023, "source": "x"},
                       "multi_year_delinquent_tax": {"years": [2023, 2024]}})
    rows = [_board_dict(li)]
    buckets, *_ = bb._collect_candidates_from_rows(rows)
    assert len(buckets["qpaybill"]) == 1
    c: Counter = Counter()
    patches = bb._build_patches(buckets, c)
    assert patches == {}


# ---------------------------------------------------------------------------------------------
# multi_source_conflict: a row carrying more than one of the three source keys
# ---------------------------------------------------------------------------------------------

def test_row_with_two_source_keys_excluded_as_conflict():
    li = _listing(raw={"qpaybill_roll": _qr(),
                       "nc_ptscloud_delinquent_tax": {"by_year": [_bill_ptscloud("2023", 1.0)]}})
    rows = [_board_dict(li)]
    buckets, total, conflicts, ambiguity = bb._collect_candidates_from_rows(rows)
    assert conflicts == 1
    assert all(len(b) == 0 for b in buckets.values())


# ---------------------------------------------------------------------------------------------
# ambiguous shared-dedupe_key exclusion
# ---------------------------------------------------------------------------------------------

def test_ambiguous_shared_dedupe_key_excluded_from_every_bucket():
    """Two DIFFERENT board rows sharing one dedupe_key (same parcel/county/state identity) --
    one a qpaybill candidate, the other a ptscloud candidate purely to prove the exclusion is
    global across buckets, not per-bucket. Both must be excluded, never guessed at."""
    shared = dict(parcel_id="44305030067", county="Horry", state="SC")
    li1 = _listing(**shared, raw={"qpaybill_roll": _qr()})
    li2 = _listing(**shared, source="counties_nc.nc_ptscloud_delinquent_tax",
                   raw={"nc_ptscloud_delinquent_tax":
                        {"by_year": [_bill_ptscloud("2023", 1.0), _bill_ptscloud("2024", 1.0)]}})
    assert li1.dedupe_key() == li2.dedupe_key()
    rows = [_board_dict(li1), _board_dict(li2)]
    buckets, total, conflicts, ambiguity = bb._collect_candidates_from_rows(rows)
    assert total == 2
    assert ambiguity["distinct_keys"] == 1
    assert ambiguity["rows_total"] == 2
    assert ambiguity["rows_by_bucket"] == {"qpaybill": 1, "ptscloud": 1}
    assert all(len(b) == 0 for b in buckets.values())
    c: Counter = Counter()
    assert bb._build_patches(buckets, c) == {}


# ---------------------------------------------------------------------------------------------
# _watchdog_should_kill() / _parse_proc_status_text() -- reused verbatim from
# backfill_deed_ref_bound.py; re-tested here since this module has its own copy.
# ---------------------------------------------------------------------------------------------

def test_parse_proc_status_text_reads_rss_and_hwm():
    text = "Name:\tpython3\nVmRSS:\t   654321 kB\nVmHWM:\t   789012 kB\n"
    rss, hwm = bb._parse_proc_status_text(text)
    assert rss == pytest.approx(654321 / 1024.0)
    assert hwm == pytest.approx(789012 / 1024.0)


def test_watchdog_should_kill_none_when_under_both_ceilings():
    assert bb._watchdog_should_kill(10.0, 500.0, 600.0, timeout_s=1200.0, mem_ceiling_mb=16000.0) is None


def test_watchdog_should_kill_on_timeout():
    reason = bb._watchdog_should_kill(2000.0, 100.0, 100.0, timeout_s=1800.0, mem_ceiling_mb=16000.0)
    assert reason is not None and "timeout" in reason


def test_watchdog_should_kill_on_mem_ceiling():
    reason = bb._watchdog_should_kill(10.0, 20000.0, 100.0, timeout_s=1800.0, mem_ceiling_mb=16000.0)
    assert reason is not None and "VmRSS" in reason
