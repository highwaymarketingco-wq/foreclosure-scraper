"""sc_public_index._to_listings must set a real county per case, or
dedupe_key() collapses nearly the whole batch into one survivor.

MEASURED live 2026-09-27, via scripts/run_scoped_scrapers.py --slugs
national.sc_public_index --limit 15000: 1,632 real CP cases scraped, only 1
survived in-batch dedupe (1,631 "merged into another row in this batch").

Root cause: fetch() collects each county's results via `_salvage(county,
county_results)`, but the flattened list handed to `_to_listings()` at the
end had no per-case county association -- _to_listings()'s own old comment
said so plainly: "We don't track which county each case came from
separately." So every Listing got `county=None`. Combined with every
Listing also sharing one hardcoded `source_url` ("https://
publicindex.sccourts.org/"), `Listing.dedupe_key()` fell all the way through
its parcel branch (no parcel_id here), its address branch (no
street_address here), and its case_number+county branch (skipped: requires
`self.county` to be truthy) down to the final `url:{source_url}` fallback --
identical for every row, so the whole batch collapsed to one survivor.

Fix: `_salvage()` stamps `case["_county"] = county` on each case dict BEFORE
it joins the flattened list (and before the self.partial salvage path, which
reads the same per-county dict). `_to_listings()` reads `case["_county"]`
and title-cases it (SC_COUNTIES entries are lowercase) to match how county
names are stored everywhere else on the board.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.sc_public_index import SCPublicIndexScraper


def _case(case_number: str, county: str) -> dict:
    return {
        "case_number": case_number,
        "_county": county,
        "name": "Doe, Jane",
        "role": "Defendant",
        "date_filed": "01/15/2024",
        "status": "Active",
    }


def test_to_listings_sets_a_real_county_from_the_per_case_tag():
    scraper = SCPublicIndexScraper()
    listings = scraper._to_listings([_case("2024CP1000772", "charleston")])
    assert len(listings) == 1
    assert listings[0].county == "Charleston"


def test_distinct_cases_in_different_counties_get_distinct_dedupe_keys():
    """The actual regression: before the fix, ALL of these collapsed to the
    same url: fallback key regardless of county or case number."""
    scraper = SCPublicIndexScraper()
    cases = [
        _case("2024CP1000772", "charleston"),
        _case("2024CP1000773", "charleston"),
        _case("2024CP1000772", "spartanburg"),  # same case number, different county
    ]
    listings = scraper._to_listings(cases)
    keys = {li.dedupe_key() for li in listings}
    assert len(keys) == 3, f"expected 3 distinct dedupe keys, got {keys}"
    assert all(key.startswith("case:SC:") for key in keys)


def test_same_case_number_and_county_still_collapses_correctly():
    """Not every collapse is wrong -- a genuine duplicate (same case, same
    county, seen twice in one batch) SHOULD still dedupe to one row."""
    scraper = SCPublicIndexScraper()
    cases = [_case("2024CP1000772", "charleston"), _case("2024CP1000772", "charleston")]
    listings = scraper._to_listings(cases)
    keys = {li.dedupe_key() for li in listings}
    assert len(keys) == 1


def test_missing_county_tag_falls_back_to_none_not_a_crash():
    """A case dict that somehow lacks the _county tag (e.g. a call site that
    doesn't go through _salvage) must not crash -- it degrades to the old
    behavior for THAT row only, not silently mislabel it."""
    scraper = SCPublicIndexScraper()
    untagged = {"case_number": "2024CP1000999", "name": "X", "role": "Defendant",
                "date_filed": "", "status": ""}
    listings = scraper._to_listings([untagged])
    assert len(listings) == 1
    assert listings[0].county is None
