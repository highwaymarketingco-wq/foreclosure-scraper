"""Regression coverage for enrichment_greenville_tax.py's offline tax_owed-year patch.

Found 2026-11-16 chasing gap_matrix's Greenville SC tax_aging_surfaced "sourced-not-built"
entry (5,547 rows). scripts/backfill_greenville_tax.py's 2026-11-12 run fetched 3,268 real
parcels and found bills on 3,247, but logged tax_owed_filled=0 for every one of them: each row
already carried a raw['tax_owed']['balance'] from an older/different producer (the Taxsale
roster's generic promotion via enrichment_tax_owed.py), so enrich_greenville_tax()'s own
"don't clobber an existing balance" guard correctly declined to overwrite it -- discarding the
'year' it had just computed along with the rest of its own, richer block. Without a 'year',
enrichment_tax_aging.py's first gate (a singular raw['tax_owed']['year'], the same contract
just fixed for Florence this session) never reaches tax_year_status(), so raw['tax_aging_
surfaced'] never lands either -- live board sample confirmed 3,346 rows with a real tax_owed
balance, zero with a real tax_aging_surfaced.

patch_cached_tax_owed_year() re-derives build_tax_owed_block() from the SAME bills this module
already fetched and cached on raw['greenville_tax_history']['bills'] (SOURCE_KEY) -- no new
network call -- and patches in ONLY the missing year/years/years_delinquent/status fields,
never touching the existing balance/source/kind/basis. These tests pin that contract so it
cannot silently regress.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from foreclosure_scraper.enrichment_greenville_tax import (
    SOURCE_KEY, patch_cached_tax_owed_year, patch_cached_tax_owed_years,
)

TODAY = date(2026, 11, 16)


def _bill(year: int, owed: float, sold: bool = False) -> dict:
    return {"year": year, "owner": "DOE JOHN", "receipt": f"{year} 000000001 01 001",
            "billed": owed, "owed": owed, "paid_on": None, "late_flag": True,
            "sold_at_tax_sale": sold, "bankruptcy": False}


def _row(*, bills, tax_owed: dict, map_no: str = "0574050100702") -> SimpleNamespace:
    return SimpleNamespace(
        state="SC", county="Greenville",
        raw={
            SOURCE_KEY: {"map_number": map_no, "results_found": len(bills), "bills": bills,
                         "source_url": "https://example.invalid", "fetched_at": "2026-11-12T00:00:00Z"},
            "tax_owed": dict(tax_owed),
        })


def test_patches_missing_year_without_touching_balance():
    """THE regression pin: an existing tax_owed with a real balance but no year gets a year
    (and years/years_delinquent/status) added from the cached bills -- balance/source untouched."""
    li = _row(
        bills=[_bill(2024, 7826.17), _bill(2025, 8082.24)],
        tax_owed={"balance": 8082.24, "kind": "delinquent_tax", "source": "national.distressed",
                  "basis": "own_record", "parcel": "0574050100702"},
    )
    patched = patch_cached_tax_owed_year(li, today=TODAY)
    assert patched is True
    to = li.raw["tax_owed"]
    # untouched -- the pre-existing, possibly-different-source balance is never overwritten
    assert to["balance"] == 8082.24
    assert to["source"] == "national.distressed"
    # newly patched in
    assert to["year"] == 2025
    assert to["years"] == ["2024", "2025"]
    assert to["years_delinquent"] == 2


def test_noop_when_tax_owed_already_has_a_year():
    li = _row(
        bills=[_bill(2025, 500.0)],
        tax_owed={"balance": 500.0, "year": 2025, "source": "greenville_votaxqry:x"},
    )
    before = dict(li.raw["tax_owed"])
    assert patch_cached_tax_owed_year(li, today=TODAY) is False
    assert li.raw["tax_owed"] == before


def test_noop_when_no_existing_balance():
    """Not this function's case -- enrich_greenville_tax()'s own normal write path (the
    to_block guard) already handles a row with no pre-existing tax_owed at all."""
    li = _row(bills=[_bill(2025, 500.0)], tax_owed={})
    li.raw["tax_owed"] = None
    assert patch_cached_tax_owed_year(li, today=TODAY) is False


def test_noop_when_no_cached_bill_history():
    li = SimpleNamespace(state="SC", county="Greenville",
                         raw={"tax_owed": {"balance": 500.0, "source": "x"}})
    assert patch_cached_tax_owed_year(li, today=TODAY) is False


def test_noop_when_recomputed_block_has_nothing_owed():
    """Cached bills exist but every year is fully paid (owed 0) -- build_tax_owed_block()
    returns None, nothing to patch in."""
    li = _row(bills=[_bill(2025, 0.0)],
              tax_owed={"balance": 100.0, "source": "national.distressed"})
    assert patch_cached_tax_owed_year(li, today=TODAY) is False


def test_driver_counts_across_several_rows_and_skips_other_counties():
    greenville_patchable = _row(
        bills=[_bill(2024, 100.0), _bill(2025, 200.0)],
        tax_owed={"balance": 200.0, "source": "national.distressed"},
    )
    greenville_already_done = _row(
        bills=[_bill(2025, 50.0)],
        tax_owed={"balance": 50.0, "year": 2025, "source": "greenville_votaxqry:x"},
        map_no="0000000000001",
    )
    other_county = SimpleNamespace(
        state="SC", county="Pickens",
        raw={SOURCE_KEY: {"map_number": "x", "bills": [_bill(2025, 1.0)]},
             "tax_owed": {"balance": 1.0, "source": "national.distressed"}})

    stats = patch_cached_tax_owed_years(
        [greenville_patchable, greenville_already_done, other_county])
    assert stats["scanned"] == 2  # other_county excluded by _is_greenville_sc
    assert stats["eligible_hist"] == 2
    assert stats["patched"] == 1
    assert greenville_patchable.raw["tax_owed"]["year"] == 2025
    assert other_county.raw["tax_owed"].get("year") is None  # never touched -- wrong county
