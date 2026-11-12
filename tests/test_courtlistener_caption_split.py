"""Regression tests for the CourtListener case_name caption split.

extraction_gaps.md flagged 51 board rows where a servicer/GSE name
(SERVICEMAC/FNMA/...) ended up in a name-resolution field because a
"<Plaintiff> v. <Defendant>" case_name was dumped whole into `defendant` --
the field nearly every owner/skip-trace enricher reads as "the person to
search" (enrichment_free_phones, enrichment_probate_search, enrichment_nc_doj,
enrichment_resolve_name_to_property, ...). Live-verified 2026-10-01 against
all three CourtListener scrapers (bankruptcy's /search/ results mix in true
adversary captions like "United States v. Bingham"; courtlistener_civil's
real-property feed is dominated by servicer-vs-borrower foreclosure captions).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (
    _is_institution,
    _split_caption,
)
from foreclosure_scraper.scrapers.national.courtlistener_civil import (
    CourtListenerCivil,
)


def test_plain_bankruptcy_caption_unaffected():
    # the common case: "In re <Debtor>" has no "v." at all
    assert _split_caption("John Doe") == (None, "John Doe")
    assert _split_caption("In re John Doe") == (None, "John Doe")
    assert _split_caption("In re: Smith, Jane") == (None, "Smith, Jane")


def test_two_party_caption_is_split_not_concatenated():
    assert _split_caption("Taylor v. Honeycutt") == ("Taylor", "Honeycutt")
    assert _split_caption("Batt vs. Cole") == ("Batt", "Cole")


def test_institution_plaintiff_never_becomes_the_defendant_field():
    # the exact failure class the gap note names: a servicer/GSE caption
    plaintiff, defendant = _split_caption(
        "Federal National Mortgage Association v. John Smith")
    assert plaintiff is None  # institution blocked from a name-resolution field
    assert defendant == "John Smith"

    plaintiff, defendant = _split_caption("ServiceMac LLC v. Jane Doe et al")
    assert plaintiff is None
    assert defendant == "Jane Doe"


def test_institution_defendant_is_withheld_not_misreported():
    # a borrower-initiated suit naming the bank as defendant: the bank's name
    # must never occupy `defendant` either, even though it is textually there
    plaintiff, defendant = _split_caption("John Smith v. Wells Fargo Bank, N.A.")
    assert plaintiff == "John Smith"
    assert defendant is None


def test_united_states_as_party_is_an_institution():
    plaintiff, defendant = _split_caption("United States v. Bingham")
    assert plaintiff is None
    assert defendant == "Bingham"


def test_is_institution_direct():
    assert _is_institution("ServiceMac LLC")
    assert _is_institution("Federal National Mortgage Association")
    assert _is_institution("FNMA")
    assert _is_institution("Wells Fargo Bank, N.A.")
    assert _is_institution("United States of America")
    assert not _is_institution("John Smith")
    assert not _is_institution("Honeycutt")
    assert not _is_institution(None)
    assert not _is_institution("")


def test_named_servicer_brands_with_no_generic_keyword():
    """Live-verified 2026-10-01 against a real federal real-property caption:
    "Washington v. NewRez, LLC" -- NewRez carries no generic keyword
    (mortgage/bank/servicing) of its own, so the keyword-only gate alone would
    have let it through as if it were a person's name."""
    for brand in ("NewRez, LLC", "Mr. Cooper", "Shellpoint Mortgage Servicing",
                  "Nationstar Mortgage LLC", "PennyMac Loan Services"):
        assert _is_institution(brand), brand

    plaintiff, defendant = _split_caption("Washington v. NewRez, LLC")
    assert plaintiff == "Washington"
    assert defendant is None


def test_empty_case_name():
    assert _split_caption("") == (None, None)
    assert _split_caption(None) == (None, None)


# ---------------------------------------------------------------------------
# Integration: CourtListenerCivil.fetch() wires the split through to the
# Listing, with the raw case_name kept verbatim for provenance.
# ---------------------------------------------------------------------------

def _hit(case_name, docket_no="1:26-cv-00001", **kw):
    return {
        "caseName": case_name,
        "docketNumber": docket_no,
        "dateFiled": "2026-09-01",
        "nature_of_suit": "220",
        "docket_absolute_url": f"/docket/{docket_no}/",
        **kw,
    }


def test_civil_fetch_splits_servicer_caption_live_shape(monkeypatch):
    import foreclosure_scraper.scrapers.national.courtlistener_civil as M

    async def fake_fetch_court_civil(c, court, token, deadline=None):
        if court == "scd":
            return [M._normalize_search_hit(
                _hit("Federal National Mortgage Association v. Mary Jones"),
                "scd")]
        return []

    monkeypatch.setattr(M, "_fetch_court_civil", fake_fetch_court_civil)
    monkeypatch.setattr(M, "_load_token", lambda: "fake-token")

    result = list(asyncio.run(CourtListenerCivil().fetch()))
    assert len(result) == 1
    li = result[0]
    assert li.plaintiff is None, "the GSE must not occupy a name-resolution field"
    assert li.defendant == "Mary Jones"
    # provenance: the full original caption is still kept in raw
    assert li.raw["courtlistener_civil"]["case_name"] == (
        "Federal National Mortgage Association v. Mary Jones")
