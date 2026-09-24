"""NC eCourts Judgment Search: statewide TARGET_COUNTIES widening + FAM-Divorce.

MEASURED 2026-09-23 live against the real endpoint
(https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search), per
docs/coverage_gap_build_plan_2026-09-23.md items 1 + 2. These are the exact
findings that justified widening `TARGET_COUNTIES` from 22 to all 100 NC
counties and adding `DIVORCE_CAUSES = {"FAM - Divorce"}`:

1. Facet mechanism works statewide, not just in the 22-county footprint.
   Queried 10 non-footprint counties individually (Wake, Mecklenburg,
   Forsyth, Guilford, Durham, Cumberland, New Hanover, Alamance, Chatham,
   Person) over a 90-day window: every one returned real, non-zero
   `totalHits` (230-11,949) under both "<County> District Court" and
   "<County> Superior Court" facet names.

2. No shared-Clerk-of-Court naming collisions found. The build plan's own
   caveat ("a handful of NC counties share a Clerk of Court office with a
   neighbor for some case types") was checked against 20 small/rural
   counties most likely to hit that case (Tyrrell, Camden, Gates, Hyde,
   Jones, Bertie, Warren, Hertford, Alleghany, Avery, Graham, Clay,
   Pamlico, Washington, Perquimans, Chowan, Swain, Yancey, Madison,
   Mecklenburg) over a 180-day window: every one returned real, non-zero
   `totalHits` (46-11,949) under its own county name. No county returned
   zero or an HTTP error.

3. A full 100-county, single-batched-query request (exactly how production
   runs it) returned `totalHits=78,663` for a 90-day window. The response's
   `facets` display list only echoed 74/100 counties with a nonzero count —
   this is a facet-aggregation SIZE CAP on Tyler's side (a display artifact),
   not evidence that the other 26 counties have zero real judgments: querying
   those exact 26 counties ALONE returned `totalHits=2,814`, and paging the
   full-100 query's actual `hits[]` (not the facets list) turned up real rows
   from 22 of those 26 counties within the first 3,000 hits sampled. The
   scraper reads `hits[]`/`location` per row, never the `facets` list, so
   this display artifact does not affect what actually gets scraped.

4. `causeOfActionDesc == "FAM - Divorce"` / `caseCategoryKey == "FAM"` is a
   live, current cause code, not a stale finding from docs/gap_ledger.md
   (line ~119). A 5-county, 90-day sample (Buncombe/Henderson/Rutherford/
   Wake/Mecklenburg, 3,000 hits) found 281 "FAM - Divorce" hits (5th most
   common cause overall, matching the gap ledger's "5th most common cause"
   note), each with both spouses structured as debtors[]/creditors[] the
   same way lien debtors/creditors already are, `civilJudgmentStatus` values
   including "Active" and "Voluntary Dismissal without Prejudice" (the
   latter already excluded by the existing terminal-disposition filter).

5. No domestic-violence/50B-named cause code was found anywhere in this
   taxonomy. A broader 100-county, 90-day, 4,000-row sample's FAM-prefixed
   causes were: FAM - Arrears, FAM - Child Support, FAM - Divorce,
   FAM - Equitable Distribution, FAM - Other Filing, FAM - Qualified
   Domestic Relations Order, FAM - Registration of a Foreign Order. None
   resembles a 50B/DVPO filing. `_DV50B_RE` (mirroring
   enrichment_nc_divorce.py's existing pattern) is kept as defense-in-depth
   only, per the coverage-gap plan's explicit ask to mirror that safety
   pattern -- not because live data showed a leak.

These are recorded as fixture-shaped unit tests (no live network call in the
test itself) so CI stays deterministic; the live findings above are what
justified the code change and are preserved here for the audit trail.
"""
from __future__ import annotations

from foreclosure_scraper.config import in_scope_distressed
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.validation import NC_COUNTIES as ALL_NC_COUNTIES
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    TARGET_COUNTIES,
    DIVORCE_CAUSES,
    FORECLOSURE_CAUSES,
    _hit_to_listing,
)


def _fam_divorce_hit(**overrides) -> dict:
    """Shaped from a real hit captured live 2026-09-23 (Mecklenburg District
    Court, case 25CV017989-590) -- field names/shape unchanged from the API
    response, party names swapped for clarity."""
    hit = {
        "causeOfActionDesc": "FAM - Divorce",
        "caseNumber": "25CV017989-590",
        "location": "Mecklenburg District Court",
        "civilJudgmentStatus": "Active",
        "caseCategoryKey": "FAM",
        "judgmentType": "Civil Judgment",
        "orderedDate": "2026-07-19T23:00:00-05:00",
        "debtors": [{"name": "POLO, JOEL, Sr.", "partyType": "D"}],
        "creditors": [{"name": "CARDENAS, NORIS", "partyType": "C"}],
    }
    hit.update(overrides)
    return hit


# ---- Item 1: statewide TARGET_COUNTIES widening ----------------------------

def test_target_counties_is_all_100_nc_counties():
    assert set(TARGET_COUNTIES) == set(ALL_NC_COUNTIES)
    assert len(TARGET_COUNTIES) == 100


def test_formerly_pruned_counties_now_included():
    """These were explicitly pruned from TARGET_COUNTIES pre-2026-09-23 as a
    footprint artifact -- live-verified 2026-09-23 (see module docstring)
    that Tyler indexes all of them with real, non-zero judgment volume."""
    for c in ("Wake", "Mecklenburg", "Forsyth", "Guilford", "Durham",
              "Cumberland", "Madison", "Yancey"):
        assert c in TARGET_COUNTIES


def test_small_rural_counties_included_no_naming_exceptions():
    """The build plan's shared-Clerk-of-Court caveat was checked live against
    these 20 small/rural counties (see module docstring finding #2) and none
    showed a naming collision -- all included at face value."""
    for c in ("Tyrrell", "Camden", "Gates", "Hyde", "Jones", "Bertie",
              "Warren", "Hertford", "Alleghany", "Avery", "Graham", "Clay",
              "Pamlico", "Washington", "Perquimans", "Chowan", "Swain",
              "Yancey", "Madison"):
        assert c in TARGET_COUNTIES


def test_every_target_county_passes_the_real_scope_gate():
    """LIS_PENDENS/TAX_LIEN/DIVORCE_NOTICE are not flip listing types, so
    they must pass config.in_scope_distressed(), not the narrow flip
    footprint -- confirmed by reading main._county_in_scope."""
    for c in TARGET_COUNTIES:
        assert in_scope_distressed(c, "NC"), (
            f"{c} is in TARGET_COUNTIES but fails in_scope_distressed -- "
            f"its rows would be silently dropped at the scope gate"
        )


def test_target_counties_sourced_from_validation_not_a_new_list():
    """Widening should reuse the canonical county set (validation.NC_COUNTIES,
    already used by the scope gate) rather than hand-maintaining a fourth
    parallel county list that can drift out of sync."""
    import inspect
    from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_lis_pendens
    src = inspect.getsource(nc_ecourts_lis_pendens)
    assert "_ALL_NC_COUNTIES" in src
    assert "from ...validation import NC_COUNTIES" in src


# ---- Item 2: FAM - Divorce -------------------------------------------------

def test_fam_divorce_cause_is_tracked():
    assert "FAM - Divorce" in DIVORCE_CAUSES
    # Kept as a separate set from FORECLOSURE_CAUSES -- divorce is a distinct
    # lead type (DIVORCE_NOTICE), not a foreclosure/lien precursor.
    assert "FAM - Divorce" not in FORECLOSURE_CAUSES


def test_fam_divorce_hit_becomes_divorce_notice_listing():
    li = _hit_to_listing(_fam_divorce_hit(), "counties_nc.nc_ecourts_lis_pendens")
    assert li is not None
    assert li.listing_type == ListingType.DIVORCE_NOTICE
    assert li.county == "Mecklenburg"
    assert li.state == "NC"
    # Both spouses captured, same debtors[]->defendant / creditors[]->plaintiff
    # mapping the scraper already uses for lien parties.
    assert li.defendant == "POLO, JOEL, Sr."
    assert li.plaintiff == "CARDENAS, NORIS"


def test_fam_divorce_owner_name_is_filing_spouse():
    """Matches nc_ecourts_divorce.py's convention: owner_name is the filing
    (plaintiff/petitioner) spouse, so GIS name-to-property resolution can
    find the marital home."""
    li = _hit_to_listing(_fam_divorce_hit(), "counties_nc.nc_ecourts_lis_pendens")
    assert li.owner_name == "CARDENAS, NORIS"
    assert li.owner_name == li.plaintiff


def test_fam_divorce_has_no_sale_date_or_upset_bid():
    """A divorce judgment is not a foreclosure sale -- sale_date must stay
    None (dateless, same as every other eCourts row) and the upset-bid
    machinery (an NC foreclosure-specific statute concept) must not fire."""
    li = _hit_to_listing(_fam_divorce_hit(), "counties_nc.nc_ecourts_lis_pendens")
    assert li.sale_date is None
    assert li.upset_bid_deadline is None
    assert "upset_bid" not in li.raw


def test_fam_divorce_dismissed_case_dropped():
    """Already covered by the existing terminal-disposition filter -- a
    'Voluntary Dismissal without Prejudice' divorce is not an actionable
    lead. Live-verified this status string appears on real FAM - Divorce
    rows (see module docstring finding #4)."""
    hit = _fam_divorce_hit(civilJudgmentStatus="Voluntary Dismissal without Prejudice")
    assert _hit_to_listing(hit, "test") is None


def test_dv50b_defense_in_depth_drops_poisoned_hit():
    """Live data shows no DV/50B-named cause exists in this taxonomy (module
    docstring finding #5), but the exclusion is kept as a second layer per
    the coverage-gap plan's explicit ask to mirror enrichment_nc_divorce.py's
    _DV50B_RE pattern -- verify it actually fires if free text ever carries
    DV-adjacent language."""
    for poison_field, poison_value in (
        ("judgmentType", "Domestic Violence Protective Order"),
        ("debtors", [{"name": "DOE, JOHN (50B Protective Order)"}]),
    ):
        hit = _fam_divorce_hit(**{poison_field: poison_value})
        assert _hit_to_listing(hit, "test") is None, (
            f"DV/50B-poisoned {poison_field} should be dropped, wasn't"
        )


def test_other_fam_causes_not_admitted():
    """Only FAM - Divorce is tracked -- other FAM causes seen live (Arrears,
    Child Support, Equitable Distribution, Other Filing, Qualified Domestic
    Relations Order, Registration of a Foreign Order) are deliberately left
    out; they are not the granted-divorce signal this item targets."""
    for other_cause in (
        "FAM - Arrears", "FAM - Child Support", "FAM - Equitable Distribution",
        "FAM - Other Filing", "FAM - Qualified Domestic Relations Order",
        "FAM - Registration of a Foreign Order",
    ):
        hit = _fam_divorce_hit(causeOfActionDesc=other_cause)
        assert _hit_to_listing(hit, "test") is None, (
            f"{other_cause} should not be admitted, only FAM - Divorce is"
        )


# ---- MAX_PAGES / timeout_s (needed for the widened corpus to be reachable) --

def test_max_pages_and_timeout_raised_for_wider_corpus():
    """MEASURED 2026-09-23: the full 100-county, 90-day query has
    totalHits=78,663; at PAGE_SIZE=200 that is ~394 pages. The pre-widening
    MAX_PAGES=25 would have silently capped this source at ~6% of the
    now-reachable corpus, defeating the point of widening TARGET_COUNTIES.
    MEASURED page latency was ~1.15s/page (5-page live sample), so 450 pages
    is a ~450-520s pull -- kept under the also-raised 900s timeout_s."""
    from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
        NCECourtsLisPendens,
    )
    assert NCECourtsLisPendens.MAX_PAGES >= 394, (
        "MAX_PAGES must cover the measured 394-page full-100-county corpus"
    )
    assert NCECourtsLisPendens.timeout_s >= 600, (
        "timeout_s must leave headroom for the larger MAX_PAGES pull"
    )
