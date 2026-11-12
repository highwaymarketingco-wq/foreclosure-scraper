"""THE BUGS THIS PINS (found 2026-09-13 reading run logs, not code).

1. DEPTH CEILING SILENTLY LOST ROWS. sweep_county walks name prefixes and deepens
   any prefix that fills its pages. The loop is
       while frontier and depth <= MAX_PREFIX_DEPTH
   so when the frontier is STILL non-empty at the ceiling, those prefixes are
   assigned to `frontier` and then dropped by the condition — never walked. Every
   row under them past the parent's first pages is absent from the roll, and the
   old log line ("still filling pages at max depth") read like a tuning note, so
   it was ignored. Unwalked prefixes per county at depth 4: Orangeburg 141,
   Spartanburg 120, Oconee 44, Marlboro 33, Cherokee 17, Darlington 16.

   The paired runs prove the rows are real: Spartanburg 10,094 rows at trunc=0 vs
   12,256 at trunc=120; Orangeburg 11,450 vs 14,169. Depth is the wrong brake —
   REQUEST_BUDGET_PER_COUNTY bounds the crawl by requests AND reports exhaustion.

2. "McCormick".title() == "Mccormick" — the FOURTH occurrence of this mistake in
   this codebase (after the BT appraisal-card lookup, the board's county values,
   and _NC_COUNTY_NAMES). QPAYBILL_SUBS keyed the county "Mccormick", so every row
   it produced carried a misspelled county that validation.py then had to repair.
"""
from foreclosure_scraper.county_name import canonical_county
from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (
    MAX_PREFIX_DEPTH,
    QPAYBILL_SUBS,
    REQUEST_BUDGET_PER_COUNTY,
)


def test_depth_default_stays_at_the_measured_value():
    # This was briefly raised to 6 on the theory that the dropped frontier was
    # costing thousands of rows. Measured at the SAME budget, depth 6 vs depth 4 was
    # Orangeburg -9 parcels and Spartanburg +24, for 2.5x the runtime. The deeper
    # prefixes re-find parcels already read under their parents. Budget is the lever.
    assert MAX_PREFIX_DEPTH == 4


def test_request_budget_is_the_real_brake():
    # The budget is what must stop a runaway crawl, because unlike a depth ceiling
    # it warns when it stops early.
    assert REQUEST_BUDGET_PER_COUNTY > 0


def test_mccormick_is_spelled_correctly():
    assert "McCormick" in QPAYBILL_SUBS
    assert "Mccormick" not in QPAYBILL_SUBS


def test_every_qpaybill_county_key_is_canonical():
    # canonical_county() already knows every Mc/Mac rule. Any key it would rewrite
    # is a key that will produce wrong county values on the board.
    wrong = {c: canonical_county(c) for c in QPAYBILL_SUBS if canonical_county(c) != c}
    assert not wrong, f"non-canonical county keys: {wrong}"


def test_county_roster_does_not_shrink():
    # Was 19. On 2026-09-13 probing every SC county against the vendor's subdomain
    # patterns found EIGHT more live portals (Horry, Lexington, Kershaw, Sumter,
    # Marion, Bamberg, Saluda, Colleton), so the source covers 27 counties. This is
    # a floor, not an equality, so finding more never fails the suite — but silently
    # losing one does.
    assert len(QPAYBILL_SUBS) >= 26


def test_marion_stays_out():
    # marioncounty.qpaybill.com is a working portal with NO DATA: 0 rows for every
    # prefix, every paid status and all four search types (verified 2026-09-13
    # through _walk_prefix). A listed county that can never produce a row reads as a
    # scraper bug forever.
    assert "Marion" not in QPAYBILL_SUBS


def test_hampton_stays_out():
    # hamptontreasurer.qpaybill.com answers 200 with an "Object moved / Error" stub
    # and no search form. Listing it would manufacture a county that reports zero
    # rows forever and reads like a scraper bug.
    assert "Hampton" not in QPAYBILL_SUBS
