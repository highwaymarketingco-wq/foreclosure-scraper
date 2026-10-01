"""raw['probate'] bare-presence false positive (audit 2026-10-01).

Several scrapers write raw['probate'] as an ALWAYS-PRESENT "we checked this notice" wrapper,
the same bug class already fixed for Greenville's fabricated `raw['distressed']=True` stamp
(commits d1fe4056/2190aa5a/8081e57b) and for the SC `divorce` case_count:0 wrapper (which
`distress_score._divorce_signal` already guards on `case_count` for exactly this reason):

  - sc_public_notices.py writes {"decedent": defendant or None, "es_case_number": ... or
    None, ...} for EVERY "probate" notice kind, whether or not a decedent name or case number
    was actually captured.
  - column_legal_notices.py's SC probate path writes a dict with only `date_of_death` /
    `personal_representative`, never a decedent name or case number at all.

Measured board-wide (2026-10-01, docs/listings_part_*.json.gz, 219,143 rows): 555 rows carry
a raw['probate'] dict, 135 of which have none of decedent / case_number / es_case_number /
nc_estate_file_no -- an empty "notice seen, nothing matched" wrapper -- and 14 of those 135
were riding a bare `if raw.get('probate')` check to a WARM tier on a notice that names no one.

Every current reader of raw['probate'] did the same bare-presence check: distress_score (the
live HOT/WARM/COLD scorer), enrichment_strategy_fit (LAND_WHOLESALE tagging), enrichment_
property_category (the dashboard category chip), enrichment_lead_signals (the "signals"
chip + intent_score), and fullmer_rank (the Fullmer buy-box ranking's probate_heirs bonus).
All five are fixed here to use the same `signal_freshness.has_real_probate` gate.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.signal_freshness import has_real_probate
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

TODAY = date(2026, 10, 1)

#: An always-written wrapper with no real identifier -- exactly the sc_public_notices.py /
#: column_legal_notices.py shape that should NOT count as a probate hit.
EMPTY_WRAPPER = {"date_of_death": "2026-01-15", "personal_representative": "Jane Doe",
                 "match_confidence": 0.5}
#: A real hit: any ONE identifier is enough.
REAL_DECEDENT = {"decedent": "John Smith", "date_of_death": "2026-01-15"}
REAL_CASE_NUMBER = {"case_number": "22E001234", "court": "Gaston County Probate Court"}
REAL_ES_CASE = {"decedent": None, "es_case_number": "24-ES-001234"}
REAL_NC_FILE_NO = {"nc_estate_file_no": "24-E-123", "personal_representative": "Jane Doe"}


# ---------------------------------------------------------------------------
# has_real_probate itself
# ---------------------------------------------------------------------------
def test_empty_wrapper_is_not_real():
    assert has_real_probate(EMPTY_WRAPPER) is False


def test_each_identifier_field_alone_is_real():
    assert has_real_probate(REAL_DECEDENT) is True
    assert has_real_probate(REAL_CASE_NUMBER) is True
    assert has_real_probate(REAL_ES_CASE) is True
    assert has_real_probate(REAL_NC_FILE_NO) is True


def test_blank_and_whitespace_identifiers_are_not_real():
    assert has_real_probate({"decedent": "", "es_case_number": "   "}) is False
    assert has_real_probate({"decedent": None, "case_number": None}) is False


def test_non_dict_and_missing_are_not_real():
    assert has_real_probate(None) is False
    assert has_real_probate({}) is False
    assert has_real_probate("probate") is False
    assert has_real_probate([1, 2]) is False


# ---------------------------------------------------------------------------
# distress_score: the live HOT/WARM/COLD scorer
# ---------------------------------------------------------------------------
from foreclosure_scraper.distress_score import _signals_for, score_board  # noqa: E402

from pathlib import Path  # noqa: E402

NOPE = Path("/nonexistent/listings.json")


def _li(raw, lt=ListingType.TAX_LIEN, **kw) -> Listing:
    base = dict(source="counties_sc.sc_public_notices", source_url="u", listing_type=lt,
                state="SC", county="Spartanburg", parcel_id="123-45-67-890", raw=raw)
    base.update(kw)
    return Listing(**base)


def test_empty_probate_wrapper_scores_no_life_event_signal():
    li = _li({"probate": dict(EMPTY_WRAPPER)})
    sigs = _signals_for(li, today=TODAY)
    assert "probate" not in {n for n, _c, _w in sigs}


def test_real_probate_identifier_scores_the_life_event_signal():
    for real in (REAL_DECEDENT, REAL_CASE_NUMBER, REAL_ES_CASE, REAL_NC_FILE_NO):
        li = _li({"probate": dict(real)})
        sigs = _signals_for(li, today=TODAY)
        assert ("probate", "LIFE_EVENT", 20) in sigs, real


def test_score_board_does_not_fake_a_stack_of_two_from_an_empty_probate_wrapper():
    """BEFORE this fix: a tax_lien (FINANCIAL) + an empty probate wrapper (counted as a
    second, LIFE_EVENT category) faked a stack of 2, which alone reaches WARM regardless of
    equity or mailability (`_tier`: `stack >= 2` -> WARM). AFTER: only the one real FINANCIAL
    category exists, stack is 1, score 20 < 28, not absentee -- COLD. This reproduces 14 of
    the 135 board rows found riding the empty wrapper to WARM."""
    li = _li({"probate": dict(EMPTY_WRAPPER)}, lt=ListingType.TAX_LIEN,
             parcel_id="999-88-77-000")
    score_board([li], previous_path=NOPE, today=TODAY)
    ds = li.raw["distress_stack"]
    assert "LIFE_EVENT" not in ds["categories"]
    assert ds["stack"] == 1
    assert ds["tier"] != "WARM"


def test_score_board_still_reaches_the_stack_with_a_real_probate_case():
    li = _li({"probate": dict(REAL_DECEDENT)}, lt=ListingType.TAX_LIEN,
             parcel_id="999-88-77-111")
    score_board([li], previous_path=NOPE, today=TODAY)
    ds = li.raw["distress_stack"]
    assert "LIFE_EVENT" in ds["categories"]
    assert ds["stack"] == 2
    assert ds["tier"] == "WARM"


# ---------------------------------------------------------------------------
# enrichment_strategy_fit: LAND_WHOLESALE tagging
# ---------------------------------------------------------------------------
from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit  # noqa: E402


def _land_li(raw) -> Listing:
    return Listing(source="counties_sc.sc_public_notices", source_url="u",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.LAND,
                   state="SC", county="Spartanburg", raw=raw)


def test_strategy_fit_ignores_an_empty_probate_wrapper():
    li = _land_li({"probate": dict(EMPTY_WRAPPER)})
    enrich_strategy_fit([li])
    tags = li.raw.get("strategy_fit", {}).get("tags", [])
    assert "LAND_WHOLESALE" not in tags


def test_strategy_fit_tags_land_wholesale_on_a_real_probate_case():
    li = _land_li({"probate": dict(REAL_DECEDENT)})
    enrich_strategy_fit([li])
    tags = li.raw["strategy_fit"]["tags"]
    assert "LAND_WHOLESALE" in tags


# ---------------------------------------------------------------------------
# enrichment_property_category: the dashboard category chip
# ---------------------------------------------------------------------------
from foreclosure_scraper.enrichment_property_category import _categorize  # noqa: E402


def _notice_li(raw) -> Listing:
    # probate_notice is not one of the section-1/2/3 short-circuit types in _categorize, and
    # the source carries no probate/estate/obituary/heir substring, so this lands cleanly on
    # the distressed_signals probate check in section 4.
    return Listing(source="counties_sc.sc_public_notices", source_url="u",
                   listing_type=ListingType.PROBATE_NOTICE, state="SC", county="Spartanburg",
                   raw=raw)


def test_property_category_does_not_add_probate_signal_for_an_empty_wrapper():
    li = _notice_li({"probate": dict(EMPTY_WRAPPER)})
    cat = _categorize(li)
    assert "probate" not in (cat or {}).get("signals", [])


def test_property_category_adds_probate_signal_for_a_real_case():
    li = _notice_li({"probate": dict(REAL_DECEDENT)})
    cat = _categorize(li)
    assert "probate" in (cat or {}).get("signals", [])


# ---------------------------------------------------------------------------
# enrichment_lead_signals: the dashboard "signals" chip + intent_score
# ---------------------------------------------------------------------------
from foreclosure_scraper.enrichment_lead_signals import _facet_signals  # noqa: E402


def test_facet_signals_ignores_an_empty_probate_wrapper():
    li = _li({"probate": dict(EMPTY_WRAPPER)})
    assert "probate" not in _facet_signals(li, today=TODAY)


def test_facet_signals_includes_probate_for_a_real_case():
    li = _li({"probate": dict(REAL_DECEDENT)})
    assert "probate" in _facet_signals(li, today=TODAY)


# ---------------------------------------------------------------------------
# fullmer_rank: the Fullmer buy-box probate_heirs bonus
# ---------------------------------------------------------------------------
from foreclosure_scraper.fullmer_rank import score as fullmer_score  # noqa: E402


def _fullmer_li(raw) -> Listing:
    return Listing(source="counties_sc.sc_public_notices", source_url="u",
                   listing_type=ListingType.TAX_LIEN, state="SC", county="Spartanburg",
                   owner_name="JOHN NORMAL OWNER", raw=raw)


def test_fullmer_rank_does_not_award_probate_heirs_for_an_empty_wrapper():
    li = _fullmer_li({"probate": dict(EMPTY_WRAPPER)})
    result = fullmer_score(li)
    assert "probate_heirs" not in result["why"]


def test_fullmer_rank_awards_probate_heirs_for_a_real_case():
    li = _fullmer_li({"probate": dict(REAL_DECEDENT)})
    result = fullmer_score(li)
    assert result["why"].get("probate_heirs") == 16
