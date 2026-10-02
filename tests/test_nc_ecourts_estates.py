"""counties_nc.nc_ecourts_estates — row parsing + heir-list promotion.

No dedicated test file existed for this scraper before (checked: `find tests
-iname "*ecourts_estate*"` returned nothing). Added per HERMES sec 8/7 while
investigating the 2026-10-02 heir-list gap (owner: "if its multiple heirs and
who they are ... i want ALL data").

`_row_to_listing` is a pure function (no network), so this is exercised
entirely offline against synthetic Smart Search hitlist-row dicts matching
the real shape `_normalize_hit`/`_parties_from_text` produce.

The live Tyler Odyssey portal is behind an AWS WAF image-grid CAPTCHA (the
module's own docstring); defeating a CAPTCHA is out of scope here, so the
`fetch()`/browser-driving path is NOT live-exercised in this session. Instead
this project's OWN existing test fixture, `tests/fixtures/tyler_roa_25M000272.txt`
— a real, previously-captured Tyler case-summary page (Henderson County tax
judgment vs "Julia Taylor Heirs") — is used as evidence (see
`test_collective_heir_caption_has_no_individual_heirs_to_extract` below) that
NC court captions often name multiple heirs as ONE collective party, not as
individually-enumerated rows. That fixture is read here, not re-fetched.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates import (
    _row_to_listing,
    _HEIR_ROLE_RE,
)

SLUG = "counties_nc.nc_ecourts_estates"


def _row(parties: list[dict], **overrides) -> dict:
    base = {
        "case_number": "26E000100-320",
        "case_type": "Estate",
        "location": "Buncombe District Court",
        "filed_date": "01/15/2026",
        "status": "Open",
        "parties": parties,
    }
    base.update(overrides)
    return base


def test_decedent_and_executor_captured_as_before():
    row = _row([
        {"name": "John Smith", "role": "Decedent"},
        {"name": "Mary Smith", "role": "Executor"},
    ])
    li = _row_to_listing(row, SLUG)
    assert li is not None
    assert li.owner_name == "John Smith"
    assert li.defendant == "John Smith"
    assert li.plaintiff == "Mary Smith"
    assert li.raw["nc_ecourts_estates"]["heirs"] is None


def test_role_labelled_heirs_are_promoted_to_a_real_list():
    row = _row([
        {"name": "John Smith", "role": "Decedent"},
        {"name": "Mary Smith", "role": "Executor"},
        {"name": "Robert Smith", "role": "Heir"},
        {"name": "Jane Smith", "role": "Heir"},
    ])
    li = _row_to_listing(row, SLUG)
    heirs = li.raw["nc_ecourts_estates"]["heirs"]
    assert heirs == ["Robert Smith", "Jane Smith"]


def test_devisee_and_interested_party_roles_also_count_as_heirs():
    row = _row([
        {"name": "John Smith", "role": "Decedent"},
        {"name": "Mary Smith", "role": "Executor"},
        {"name": "Alice Jones", "role": "Devisee"},
        {"name": "Tom Jones", "role": "Interested Party"},
    ])
    li = _row_to_listing(row, SLUG)
    assert li.raw["nc_ecourts_estates"]["heirs"] == ["Alice Jones", "Tom Jones"]


def test_organization_party_is_never_promoted_as_a_heir():
    row = _row([
        {"name": "John Smith", "role": "Decedent"},
        {"name": "Mary Smith", "role": "Executor"},
        {"name": "Bank of America N.A.", "role": "Interested Party"},
    ])
    li = _row_to_listing(row, SLUG)
    assert li.raw["nc_ecourts_estates"]["heirs"] is None


def test_duplicate_heir_rows_are_deduped_case_insensitively():
    row = _row([
        {"name": "John Smith", "role": "Decedent"},
        {"name": "Mary Smith", "role": "Executor"},
        {"name": "Robert Smith", "role": "Heir"},
        {"name": "ROBERT SMITH", "role": "Heir"},
    ])
    li = _row_to_listing(row, SLUG)
    assert li.raw["nc_ecourts_estates"]["heirs"] == ["Robert Smith"]


def test_no_role_labels_at_all_falls_back_to_any_further_distinct_party():
    """When Tyler ships no role text, decedent/executor are guessed by bare
    position (pre-existing behavior) -- a THIRD distinct named party must
    still surface as a heir candidate rather than being silently dropped."""
    row = _row([
        {"name": "John Smith", "role": ""},
        {"name": "Mary Smith", "role": ""},
        {"name": "Robert Smith", "role": ""},
    ])
    li = _row_to_listing(row, SLUG)
    assert li.owner_name == "John Smith"
    assert li.plaintiff == "Mary Smith"
    assert li.raw["nc_ecourts_estates"]["heirs"] == ["Robert Smith"]


def test_role_labelled_heirs_take_priority_over_the_no_label_fallback():
    """If even ONE party carries an explicit heir-shaped role, the role-driven
    branch is authoritative -- the position-fallback branch must not ALSO run
    and inject an unrelated party."""
    row = _row([
        {"name": "John Smith", "role": "Decedent"},
        {"name": "Mary Smith", "role": "Executor"},
        {"name": "Robert Smith", "role": "Heir"},
    ])
    li = _row_to_listing(row, SLUG)
    assert li.raw["nc_ecourts_estates"]["heirs"] == ["Robert Smith"]


def test_collective_heir_caption_has_no_individual_heirs_to_extract():
    """Real evidence, not assumption: a captured Tyler Odyssey case-summary
    page already in this repo (tests/fixtures/tyler_roa_25M000272.txt) shows
    NC courts sometimes caption an entire heir group as ONE party --
    'Defendant Julia Taylor Heirs' -- with no per-heir breakout anywhere on
    the page. Mirror that exact shape: a single collective-named party with
    no heir-role label. `heirs` must stay empty; there is nothing to
    individually extract, and the collective name is already the decedent/
    owner_name (unchanged, existing behavior)."""
    fixture = Path(__file__).parent / "fixtures" / "tyler_roa_25M000272.txt"
    assert "Julia Taylor Heirs" in fixture.read_text()

    row = _row([{"name": "Julia Taylor Heirs", "role": "Respondent"}])
    li = _row_to_listing(row, SLUG)
    assert li is not None
    assert li.owner_name == "Julia Taylor Heirs"
    assert li.raw["nc_ecourts_estates"]["heirs"] is None


def test_heir_role_regex_matches_the_expected_labels_and_not_pr_or_decedent():
    for label in ("Heir", "Heirs", "Devisee", "Interested Party",
                  "Next of Kin", "Beneficiary"):
        assert _HEIR_ROLE_RE.search(label), label
    for label in ("Decedent", "Executor", "Administrator", "Petitioner"):
        assert not _HEIR_ROLE_RE.search(label), label
