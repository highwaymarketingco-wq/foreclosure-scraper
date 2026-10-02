"""NC eCourts divorce/estates coverage-widening pass, 2026-09-27.

Context: asked to widen the county footprint of nc_ecourts_divorce.py and
nc_ecourts_estates.py, on the premise (docs/coverage_gap_build_plan_2026-09-23
.md sec 2.2/2.4) that both loop `for county in counties:` doing one AWS-WAF
CAPTCHA solve per county per run, capped at 22 counties. Reading the ACTUAL
current source of both files shows that premise is stale for one of the two
and gives an incomplete cost model for the other:

DIVORCE — the premise is stale, not current. `NCECourtsDivorce.fetch()` has
not driven the WAF/browser path (`_drive_divorce_search` /
module-level `TARGET_COUNTIES`) since 2026-07-01 (commit 8719158, "Revive NC
eCourts divorce"). It hits the same free, unauthenticated, no-CAPTCHA
NCJudgmentSearchService JSON endpoint nc_ecourts_lis_pendens.py already uses,
reading `nc_ecourts_lis_pendens.TARGET_COUNTIES` live -- so when THAT list
widened from 22 to all 100 NC counties on 2026-09-23 (commit 97afaed), this
scraper's footprint widened too, automatically, with zero code change. What
was still genuinely broken, and what this pass fixes: the query itself is
unfiltered server-side (same 100-county shape as nc_ecourts_lis_pendens's own
query, just a wider 120-day window) and only gets cause-filtered to "FAM -
Divorce"/"FAM - Equitable Distribution" client-side per hit -- so
JUDGMENT_MAX_PAGES caps the RAW corpus scanned before any divorce-filtering
happens, not the divorce-cause count. MEASURED live 2026-09-27 against the
real endpoint (https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/
search):
  - 100-county, 120-day totalHits = 104,687. Page-1 density sample: 35/200
    "FAM - Divorce" hits -- divorce causes are common in this corpus, not
    rare; they were simply never reached past page 25.
  - At PAGE_SIZE=200, covering totalHits=104,687 needs 524 pages. The old
    JUDGMENT_MAX_PAGES=25 (5,000 raw hits) covered ~4.8% of it.
  - A live end-to-end run at the OLD cap (JUDGMENT_MAX_PAGES=25, timeout_s=
    600) returned 362 divorce/equitable-distribution listings across 62/100
    counties in 27.8s (26 HTTP requests, ~1.07s/request).
  - The SAME live run at the NEW cap (JUDGMENT_MAX_PAGES=600, timeout_s=1200)
    returned 5,294 listings across 91/100 counties in 606.8s -- a 14.6x
    increase in rows and +29 counties, comfortably inside the new timeout.
No browser, no CAPTCHA, no WAF involved anywhere in this path.

ESTATES — the premise is directionally right (this scraper genuinely IS
WAF-gated) but incomplete on WHERE the WAF cost lands. Reading
`_drive_estate_search`, the WAF image-grid is solved EXACTLY ONCE per run,
before the `for county in counties:` loop even starts -- not once per county.
A cleared session then sweeps every configured county for a few cheap
in-page search+scrape round trips each, with no further CAPTCHA. So widening
TARGET_COUNTIES would not multiply WAF cost the way the build-plan doc's
model assumed; the real question is only whether the one-time solve ever
clears. Live-tested 2026-09-27 against 5 never-before-tried Western NC
counties (Madison/Haywood/Watauga/Jackson/Cherokee), with this week's WAF
fixes in place (MAX_PUZZLES 8->20, WAF_SOLVE_MAX_SECONDS=90 self-deadline,
2026-09-25 browser-leak fix): 3 runs, 1 success (11 real probate/estate rows,
solved on the very first puzzle) and 2 failures (16 and 17 puzzles each
solved CORRECTLY per Gemini -- zero waf.gemini.failed events -- but AWS WAF
kept escalating past the point of release until the 90s self-deadline cut
each off cleanly; `ps aux | grep -E "uc_|patchright"` showed no leaked browser
process after any of the 3 runs). 1/3 live success is not reliable enough to
justify re-enabling as a scheduled/default source -- this reconfirms rather
than overturns the scraper's own 2026-06-27 disabled_reason, so it stays
`disabled = True` with TARGET_COUNTIES left at its current 22 (widening the
list would not change the underlying per-run solve-or-not economics either
way). See NCECourtsEstates.disabled_reason / its surrounding comment for the
full writeup.

These are recorded as fixture-shaped/source-inspection unit tests (no live
network call in the test itself) so CI stays deterministic; the MEASURED
findings above are the audit trail for why the numbers below are what they
are.
"""
from __future__ import annotations

import inspect

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_divorce as div
from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_estates as est
from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_lis_pendens as lp


# ---- import / registry sanity ----------------------------------------------

def test_both_modules_import_cleanly():
    assert div.NCECourtsDivorce.slug == "counties_nc.nc_ecourts_divorce"
    assert est.NCECourtsEstates.slug == "counties_nc.nc_ecourts_estates"


def test_both_scrapers_discovered_by_the_registry():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_nc.nc_ecourts_divorce" in slugs
    assert "counties_nc.nc_ecourts_estates" in slugs


# ---- divorce: fetch() is on the free batched endpoint, not the WAF path ----

def test_divorce_fetch_reads_lis_pendens_target_counties_live():
    """The active path inherits nc_ecourts_lis_pendens.TARGET_COUNTIES by
    reference, not by copying it at import time -- so a future widening (or
    narrowing) of that list changes divorce's footprint automatically. Assert
    the source actually reads the live module attribute (`_lp.TARGET_COUNTIES`)
    rather than a snapshot, so a refactor can't silently break this coupling."""
    src = inspect.getsource(div.NCECourtsDivorce.fetch)
    assert "_lp.TARGET_COUNTIES" in src
    # And confirm today's live value really is the full 100-county set,
    # not the dormant module-level 22-county TARGET_COUNTIES above it.
    assert len(lp.TARGET_COUNTIES) == 100
    assert div.TARGET_COUNTIES != lp.TARGET_COUNTIES
    assert len(div.TARGET_COUNTIES) == 22  # the dormant, WAF-path-only list


def test_divorce_module_level_target_counties_is_dead_code():
    """Only _drive_divorce_search (retained, unused) reads the module-level
    TARGET_COUNTIES. fetch() must not."""
    fetch_src = inspect.getsource(div.NCECourtsDivorce.fetch)
    assert "TARGET_COUNTIES" not in fetch_src.replace("_lp.TARGET_COUNTIES", "")
    driver_src = inspect.getsource(div._drive_divorce_search)
    assert "TARGET_COUNTIES" in driver_src or "counties" in driver_src


def test_pagination_cap_covers_the_measured_120day_corpus():
    """MEASURED 2026-09-27: 100-county/120-day totalHits=104,687 -> 524 pages
    at PAGE_SIZE=200. MAX_PAGES must cover that with margin, and timeout_s
    must leave headroom for the larger pull (measured ~1.07s/page live)."""
    assert div.NCECourtsDivorce.JUDGMENT_PAGE_SIZE == 200
    assert div.NCECourtsDivorce.JUDGMENT_MAX_PAGES >= 524, (
        "JUDGMENT_MAX_PAGES must cover the measured 524-page, 104,687-hit "
        "120-day/100-county corpus, or divorce-cause hits past that page "
        "are silently never reached"
    )
    assert div.NCECourtsDivorce.timeout_s >= 900, (
        "timeout_s must leave real headroom for a MAX_PAGES-sized pull at "
        "the measured ~1.07s/page live rate"
    )


def test_divorce_causes_include_equitable_distribution():
    """This is the one piece nc_ecourts_lis_pendens.py's own FAM-Divorce
    extraction does NOT cover (its DIVORCE_CAUSES is {"FAM - Divorce"} only)
    -- confirms divorce.py isn't purely redundant with it."""
    assert "FAM - Equitable Distribution" in div.NCECourtsDivorce.DIVORCE_CAUSES
    assert "FAM - Divorce" in div.NCECourtsDivorce.DIVORCE_CAUSES


def _fam_hit(**overrides) -> dict:
    hit = {
        "causeOfActionDesc": "FAM - Divorce",
        "caseNumber": "26CV001234-320",
        "location": "Cherokee District Court",
        "civilJudgmentStatus": "Active",
        "orderedDate": "2026-08-01T00:00:00-04:00",
        "debtors": [{"name": "DOE, JOHN"}],
        "creditors": [{"name": "DOE, JANE"}],
    }
    hit.update(overrides)
    return hit


def test_judgment_hit_to_listing_shape():
    scraper = div.NCECourtsDivorce()
    li = scraper._judgment_hit_to_listing(_fam_hit())
    assert li is not None
    assert li.listing_type == ListingType.DIVORCE_NOTICE
    assert li.county == "Cherokee"
    assert li.state == "NC"
    assert li.sale_date is None
    assert li.raw["relationship_signal"]["kind"] == "divorce"


def test_judgment_hit_equitable_distribution_admitted():
    scraper = div.NCECourtsDivorce()
    li = scraper._judgment_hit_to_listing(
        _fam_hit(causeOfActionDesc="FAM - Equitable Distribution")
    )
    assert li is not None
    assert li.listing_type == ListingType.DIVORCE_NOTICE


def test_judgment_hit_dismissed_dropped():
    scraper = div.NCECourtsDivorce()
    li = scraper._judgment_hit_to_listing(
        _fam_hit(civilJudgmentStatus="Dismissed")
    )
    assert li is None


def test_judgment_hit_other_fam_cause_not_admitted():
    scraper = div.NCECourtsDivorce()
    li = scraper._judgment_hit_to_listing(_fam_hit(causeOfActionDesc="FAM - Child Support"))
    assert li is None


# ---- estates: WAF solved once per run, not once per county ----------------

def test_estates_waf_solve_happens_once_before_the_county_loop():
    """Source-level guard against re-introducing a per-county WAF-solve cost
    model: _solve_waf must be called exactly once, and that call must appear
    BEFORE the `for county in counties:` loop in the same function."""
    src = inspect.getsource(est._drive_estate_search)
    solve_idx = src.index("_solve_waf(page)")
    loop_idx = src.index("for county in counties:")
    assert solve_idx < loop_idx, (
        "_solve_waf must run once, before the per-county loop -- if this "
        "moves inside the loop, the per-county WAF-solve cost model becomes "
        "real and the widening tradeoff in disabled_reason needs re-deriving"
    )
    assert src.count("_solve_waf(page)") == 1


def test_solve_waf_never_attempts_a_captcha_solve():
    """COMPLIANCE regression (HERMES sec 8 audit, 2026-10-01): _solve_waf used
    to call enrichment_waf_oss.solve_waf_via_browser (an AI vision model
    clicking the AWS-WAF "Human Verification" image-grid tiles) and, on
    failure, enrichment_capsolver.solve_aws_waf (a PAID third-party
    CAPTCHA-solving service) -- both are a CAPTCHA defeat, which HERMES.md
    sec 2 rule 2 and CLAUDE.md's compliance line forbid outright regardless
    of whether the solver is free or paid. safe_run() never reaches this
    scraper's fetch() today because `disabled = True`, but a direct fetch()
    call (this audit's own live-verification step, or a future re-enable)
    must not have a live path to either solver. _solve_waf must now return
    False unconditionally without importing or calling either module. (Checks
    the function's CODE, not its docstring, which names both modules in
    prose when explaining what was removed and why.)"""
    full_src = inspect.getsource(est._solve_waf)
    open_idx = full_src.index('"""')
    close_idx = full_src.index('"""', open_idx + 3)
    body_src = full_src[close_idx + 3:]  # strip the docstring
    assert "solve_waf_via_browser" not in body_src
    assert "solve_aws_waf" not in body_src
    assert "enrichment_waf_oss" not in body_src
    assert "enrichment_capsolver" not in body_src


def test_estates_still_disabled_and_county_list_unwidened():
    """MEASURED 2026-09-27 (see module docstring): 1/3 live WAF-solve success
    against 5 fresh counties is not reliable enough to justify re-enabling
    as a scheduled source, and since the solve is once-per-run (not
    per-county, see test above) widening the list wouldn't change that
    economics anyway. Left disabled, left at 22 counties."""
    assert est.NCECourtsEstates.disabled is True
    assert len(est.TARGET_COUNTIES) == 22
    assert est.NCECourtsEstates.expected_min_count == 0
    assert est.NCECourtsEstates.optional is True


def _estate_row(**overrides) -> dict:
    row = {
        "case_number": "26E001234-320",
        "case_type": "Estate",
        "location": "Madison District Court",
        "status": "Active",
        "filed_date": "08/01/2026",
        "parties": [
            {"name": "Smith, John", "role": "Decedent"},
            {"name": "Smith, Jane", "role": "Executor"},
        ],
    }
    row.update(overrides)
    return row


def test_row_to_listing_shape_still_works():
    """Not touched by this pass, but exercised here so a future edit to
    _row_to_listing that breaks the decedent/executor mapping fails a test
    even while the scraper itself stays disabled."""
    li = est._row_to_listing(_estate_row(), "counties_nc.nc_ecourts_estates")
    assert li is not None
    assert li.listing_type == ListingType.PROBATE_NOTICE
    assert li.county == "Madison"
    assert li.owner_name == "Smith, John"
    assert li.defendant == "Smith, John"
    assert li.plaintiff == "Smith, Jane"
    assert li.sale_date is None
