"""Regression coverage for enrichment_florence_tax_inquiry.py's pure parsers and apply_block().

Found 2026-11-16 chasing gap_matrix's Florence tax_aging_surfaced "sourced-not-built" entry
(paired with two_year_delinquent, same root cause -- see
scripts/backfill_florence_tax_inquiry.py's own docstring): apply_block() wrote raw['tax_owed']
with a plural "years" list only. enrichment_tax_aging.py's own first gate reads a SINGULAR
"year" key (`to.get("year")`) before it ever calls tax_year_status() -- every other producer
of raw['tax_owed'] (enrichment_tax_owed.enrich_tax_owed() itself, line ~666) always writes
that singular key alongside any per-year detail. Without it, raw['tax_owed'] and
raw['two_year_delinquent'] would land correctly but raw['tax_aging_surfaced'] never would
have, flag or no flag -- these tests pin the fix so it cannot silently regress.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from foreclosure_scraper.enrichment_florence_tax_inquiry import (
    aggregate, apply_block, build_block, mbp,
)
from foreclosure_scraper.enrichment_florence_two_year_delinquent import (
    enrich_florence_two_year_delinquent,
)
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging


def test_mbp_zero_pads_and_rejects_blank():
    assert mbp("30000-44-787") == ("30000", "44", "787")
    assert mbp("3400-47-51") == ("03400", "47", "051")
    assert mbp("0-0-0") is None
    assert mbp(None) is None
    assert mbp("not a tms") is None


def test_build_block_shapes_is_two_year_plus_from_late_years():
    agg = {"balance": 487.49, "years": [2024, 2026], "sold": False}
    today = date(2026, 11, 15)
    block = build_block(("41000", "52", "676"), agg, "2026-11-16T00:00:00+00:00", today)
    assert block["tms"] == "41000-52-676"
    assert block["balance"] == 487.49
    assert block["years"] == [2024, 2026]
    # 2024 is late by late 2026, 2026 itself is not -- exactly one late year, not two_year_plus
    assert block["years_delinquent"] == 1
    assert block["is_two_year_plus"] is False
    assert block["source"] == "web.florenceco.org"


def test_apply_block_writes_a_singular_year_on_tax_owed():
    """THE regression pin: tax_owed must carry a singular "year", not only the plural "years"
    list -- enrichment_tax_aging.py's first gate reads exactly that key."""
    li = SimpleNamespace(raw={})
    block = build_block(("34000", "47", "051"), {"balance": 439.09, "years": [2026], "sold": False},
                        "2026-11-16T00:00:00+00:00", date(2026, 11, 15))
    filled = apply_block(li, block)
    assert filled is True
    assert li.raw["tax_owed"]["year"] == 2026
    assert li.raw["tax_owed"]["years"] == [2026]
    assert li.raw["florence_tax_inquiry"] == block


def test_apply_block_year_is_the_newest_of_several():
    li = SimpleNamespace(raw={})
    block = build_block(("41000", "52", "676"), {"balance": 487.49, "years": [2024, 2026], "sold": False},
                        "2026-11-16T00:00:00+00:00", date(2026, 11, 15))
    apply_block(li, block)
    assert li.raw["tax_owed"]["year"] == 2026
    assert li.raw["tax_owed"]["years"] == [2024, 2026]


def test_apply_block_never_overwrites_an_existing_real_balance():
    li = SimpleNamespace(raw={"tax_owed": {"balance": 999.0, "source": "other_source"}})
    block = build_block(("34000", "47", "051"), {"balance": 439.09, "years": [2026], "sold": False},
                        "2026-11-16T00:00:00+00:00", date(2026, 11, 15))
    filled = apply_block(li, block)
    assert filled is False
    assert li.raw["tax_owed"]["balance"] == 999.0
    # the module's own block still lands unconditionally
    assert li.raw["florence_tax_inquiry"] == block


def test_full_chain_surfaces_tax_aging_for_a_not_yet_late_single_year():
    """End-to-end pin (no network): apply_block -> two_year_delinquent restate ->
    enrich_tax_aging all land on the SAME row from the SAME fetched block -- the two
    gap_matrix columns this module exists for, both real, in one pass."""
    li = SimpleNamespace(state="SC", county="Florence", source="counties_sc.florence_delinquent_tax",
                        raw={})
    today = date(2026, 11, 15)
    block = build_block(("34000", "47", "051"), {"balance": 439.09, "years": [2026], "sold": False},
                        "2026-11-16T00:00:00+00:00", today)
    apply_block(li, block)
    enrich_florence_two_year_delinquent([li])
    enrich_tax_aging([li], today=today)

    assert li.raw["two_year_delinquent"] == {
        "is_two_year_plus": False, "years": 0, "oldest_year": 2026, "source": "florence_tax_inquiry",
    }
    tas = li.raw["tax_aging_surfaced"]
    assert tas["source"] == "tax_owed"
    assert tas["status"] == "not_yet_late"
    assert tas["years_delinquent"] == 0


def test_full_chain_surfaces_tax_aging_for_a_genuinely_late_year():
    li = SimpleNamespace(state="SC", county="Florence", source="counties_sc.florence_delinquent_tax",
                        raw={})
    today = date(2026, 11, 15)
    block = build_block(("41000", "52", "676"), {"balance": 487.49, "years": [2024, 2026], "sold": False},
                        "2026-11-16T00:00:00+00:00", today)
    apply_block(li, block)
    enrich_florence_two_year_delinquent([li])
    enrich_tax_aging([li], today=today)

    assert li.raw["two_year_delinquent"]["years"] == 1
    tas = li.raw["tax_aging_surfaced"]
    assert tas["status"] == "delinquent"
    assert tas["years_delinquent"] == 1


def test_aggregate_dedupes_by_year_keeping_the_larger_owed():
    rows = [
        {"year": 2024, "real": True, "owed": 0.0, "paid": None, "delinquent": False, "sold": False},
        {"year": 2024, "real": True, "owed": 268.01, "paid": None, "delinquent": True, "sold": False},
        {"year": 2026, "real": True, "owed": 164.47, "paid": None, "delinquent": False, "sold": False},
        {"year": 2026, "real": False, "owed": 999.0, "paid": None, "delinquent": False, "sold": False},
    ]
    agg = aggregate(rows)
    assert agg["years"] == [2024, 2026]
    assert agg["balance"] == 432.48
    assert agg["sold"] is False
