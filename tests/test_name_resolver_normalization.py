"""Normalizer + targeting-gate tests for the name->property resolver.

Covers the three defects that made counties_sc.sc_public_index resolve at 0%:
  1. name normalization (double spaces, ', Llc', LAST/FIRST ordering),
  2. the targeting gate / cap starving the cohort by board position,
  3. loose matching committing the wrong person's parcel.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_resolve_name_to_property import (
    SC_NO_FREE_OWNER_SEARCH,
    SC_OWNER_LAYERS,
    _endpoint_cfg,
    _fair_order,
    _is_target,
    _safe_attrs,
)
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.name_normalize import (
    core_tokens,
    distinctive_tokens,
    is_entity,
    like_patterns,
    match_owner,
    middle_conflict,
    normalize_name,
    person_orderings,
    primary_party,
)


# ---------------------------------------------------------------------------
# normalize_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Chante  Fleming", "CHANTE FLEMING"),                 # double space
    ("  Sandra   L   Byrd ", "SANDRA L BYRD"),             # leading/trailing/multi
    ("Allied Of Spartanburg, Llc", "ALLIED OF SPARTANBURG LLC"),
    # apostrophe collapses (assessors store ONEAL, never "O NEAL"); hyphen still
    # goes to a space so "SMITH-LEE" and "SMITH LEE" converge on both sides
    ("O'Neal, Patrick-James", "ONEAL PATRICK JAMES"),
    ("Sean O'Brien", "SEAN OBRIEN"),                       # matches GIS "OBRIEN SEAN P"
    ("Smith-Lee, Dana", "SMITH LEE DANA"),                 # hyphen -> space, unchanged
    ("KIRBY JAMES A<br>(LIFE ESTATE)", "KIRBY JAMES A LIFE ESTATE"),
    (None, ""),
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_core_tokens_drops_suffixes_titles_and_initials():
    assert core_tokens("Robert Lewis Grant Jr") == ["ROBERT", "LEWIS", "GRANT"]
    assert core_tokens("Mr. John Smith III") == ["JOHN", "SMITH"]
    assert core_tokens("BYRD SANDRA D") == ["BYRD", "SANDRA"]      # 'D' initial dropped
    assert core_tokens("FLEMING LOUISE V, TRUSTEE") == ["FLEMING", "LOUISE"]


def test_entity_suffixes_stripped():
    assert is_entity("Allied Of Spartanburg, Llc")
    assert is_entity("SAR 6 LLC")
    assert is_entity("Palmetto Holdings Inc")
    assert not is_entity("Sandra L Byrd")
    # 'OF' and 'LLC' both gone; the identity tokens survive.
    assert core_tokens("Allied Of Spartanburg, Llc") == ["ALLIED", "SPARTANBURG"]
    assert core_tokens("ALLIED OF SPARTANBURG LLC") == ["ALLIED", "SPARTANBURG"]


def test_entity_comma_llc_matches_gis_spelling():
    # The exact pairing that must resolve: court feed vs GIS spelling.
    assert match_owner("Allied Of Spartanburg, Llc", "ALLIED OF SPARTANBURG LLC") == "exact"


def test_distinctive_tokens_prefers_the_rare_word_not_the_longest():
    # The old rule sorted by len() and queried '%SPARTANBURG%', which returns
    # 'CITY OF SPARTANBURG' and friends and matches none of them.
    assert distinctive_tokens("Allied Of Spartanburg, Llc")[0] == "ALLIED"


# ---------------------------------------------------------------------------
# LAST/FIRST ordering
# ---------------------------------------------------------------------------

def test_person_orderings_tries_both_directions():
    orders = person_orderings("Angela Dawn Alexander")
    assert orders[0].surname == "ALEXANDER" and orders[0].given[0] == "ANGELA"
    assert orders[1].surname == "ANGELA" and orders[1].given[0] == "DAWN"


def test_person_orderings_comma_is_authoritative():
    orders = person_orderings("Byrd, Sandra L")
    assert len(orders) == 1
    assert orders[0].surname == "BYRD"
    assert orders[0].given == ("SANDRA",)


def test_both_orderings_resolve_to_the_same_gis_owner():
    for spelling in ("Sandra L Byrd", "Byrd, Sandra L", "BYRD SANDRA L"):
        assert match_owner(spelling, "BYRD SANDRA D") in ("exact", "strong"), spelling


def test_like_patterns_emit_both_orderings_and_no_surname_only_sweep():
    pats = like_patterns("Sandra L Byrd")
    assert pats == ["%BYRD%SANDRA%", "%SANDRA%BYRD%"]
    # A bare '%BYRD%' sweep is capped at 25 arbitrary rows and never resolves.
    assert "%BYRD%" not in pats


def test_primary_party_takes_the_first_of_a_joint_owner():
    assert primary_party("SMITH JOHN C & MELINDA P") == "SMITH JOHN C"
    assert primary_party("JONES MARY AND ROBERT") == "JONES MARY"


# ---------------------------------------------------------------------------
# Match safety
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lead,gis", [
    ("Michael Duane Crowe", "CROWE KEVIN MICHAEL"),        # brother, not him
    ("Mario Roberto Cruz Montes", "MONTES HEMRY CRUZ"),
    ("Robert Lewis Grant Jr", "STEPP ROBERT GRANT"),       # GRANT is a middle name
    ("John Smith", "SMITH ANGELA D"),
    ("Sandra L Byrd", "GIST MARY BYRD"),                   # surname out of position
])
def test_rejects_wrong_person(lead, gis):
    assert match_owner(lead, gis) is None


@pytest.mark.parametrize("lead,gis", [
    ("Sandra L Byrd", "BYRD SANDRA D"),
    ("Angela Dawn Alexander", "ALEXANDER ANGELA FAYE"),
    ("John Mathis Anthony", "ANTHONY JOHN MATHIS"),
    ("Mamie E Young", "YOUNG MAMIE ELORIA"),
    ("James  Allen", "ALLEN JAMES HUNTER JR"),
])
def test_accepts_real_person(lead, gis):
    assert match_owner(lead, gis) in ("exact", "strong")


def test_entities_never_match_positionally():
    # Two different companies sharing a leading token must not match.
    assert match_owner("Allied Of Spartanburg, Llc", "ALLIED CAPITAL LLC") is None


def test_middle_conflict_flag():
    # Both middles spelled out and different -> flagged.
    assert middle_conflict("James Quentin Kirby", "KIRBY JAMES HUNTER")
    # GIS middle is only an initial -> nothing to contradict.
    assert not middle_conflict("James Quentin Kirby", "KIRBY JAMES A")
    assert not middle_conflict("John Mathis Anthony", "ANTHONY JOHN MATHIS")


def test_blank_names_never_match():
    assert match_owner("", "BYRD SANDRA D") is None
    assert match_owner("Sandra L Byrd", None) is None


# ---------------------------------------------------------------------------
# Targeting gate
# ---------------------------------------------------------------------------

def _lead(**kw) -> Listing:
    base = dict(
        source="counties_sc.sc_public_index",
        source_url="https://publicindex.sccourts.org/spartanburg/",
        state="SC", county="Spartanburg",
        owner_name="Sandra L Byrd", listing_type=ListingType.UNKNOWN,
    )
    base.update(kw)
    return Listing(**base)


def test_sc_public_index_unknown_type_is_targeted():
    """listing_type 'unknown' (1,766 of the cohort) must still be attempted."""
    li = _lead()
    assert li.listing_type == ListingType.UNKNOWN
    assert _is_target(li) is True


def test_targets_the_five_wired_sc_counties():
    for county in SC_OWNER_LAYERS:
        assert _is_target(_lead(county=county)) is True, county


def test_skips_counties_with_no_free_owner_search():
    """Anderson + Cherokee have no free owner-name endpoint at all — do not
    burn budget on a guaranteed miss."""
    for county in SC_NO_FREE_OWNER_SEARCH:
        assert _endpoint_cfg(_lead(county=county)) is None
        assert _is_target(_lead(county=county)) is False


def test_gate_still_rejects_junk():
    assert _is_target(_lead(street_address="123 Main St")) is False
    assert _is_target(_lead(parcel_id="712490588793")) is False
    assert _is_target(_lead(owner_name=None, defendant=None)) is False
    assert _is_target(_lead(state="GA", county="Fulton")) is False
    assert _is_target(_lead(owner_name="County Of Spartanburg")) is False


def test_gate_idempotency_only_skips_real_queries():
    queried = _lead(raw={"resolved_from_name": {"queried": True, "confidence": "no_match"}})
    assert _is_target(queried) is False
    # Environmental bails record queried=False and MUST retry next run.
    bailed = _lead(raw={"resolved_from_name": {"queried": False, "confidence": "budget_bail"}})
    assert _is_target(bailed) is True


def test_pinned_endpoint_beats_the_token_walled_scdot():
    cfg = _endpoint_cfg(_lead(county="Spartanburg"))
    assert cfg["pinned"] is True
    assert "scdot.org" not in cfg["base"]
    assert cfg["owner_field"] == "OwnerName"
    assert cfg["situs_field"] == "PropertyLo"     # property, NOT StreetAddr (mailing)


def test_counties_without_a_situs_column_get_none_not_a_guess():
    for county in ("Oconee", "Union"):
        assert _endpoint_cfg(_lead(county=county))["situs_field"] is None


# ---------------------------------------------------------------------------
# Cap fairness
# ---------------------------------------------------------------------------

def test_fair_order_gives_a_starved_source_slots_within_the_cap():
    """ROOT CAUSE regression: a stable priority sort left sc_public_index (board
    index ~17k-21k) with ZERO of the 400 cap slots on every run."""
    targets = [
        _lead(source="counties_sc.sc_probate_net", listing_type=ListingType.PROBATE_NOTICE)
        for _ in range(300)
    ] + [_lead(source="counties_sc.sc_public_index") for _ in range(300)]

    naive = sorted(targets, key=lambda li: 0, reverse=True)[:100]
    assert sum(1 for li in naive if li.source == "counties_sc.sc_public_index") == 0

    fair = _fair_order(targets)[:100]
    assert sum(1 for li in fair if li.source == "counties_sc.sc_public_index") > 0
    assert sum(1 for li in fair if li.source == "counties_sc.sc_probate_net") > 0


def test_fair_order_preserves_every_target():
    targets = ([_lead(source="a") for _ in range(3)]
               + [_lead(source="b") for _ in range(7)])
    assert len(_fair_order(targets)) == 10


# ---------------------------------------------------------------------------
# Mailing-address leak guard
# ---------------------------------------------------------------------------

def test_safe_attrs_strips_owner_mailing_and_pins_the_situs():
    """Spartanburg's StreetAddr/City/State/Zip are the OWNER'S MAILING address.
    FIELD_ALIASES would happily write them as the property address."""
    cfg = _endpoint_cfg(_lead(county="Spartanburg"))
    row = {
        "OwnerName": "BYRD SANDRA D",
        "PropertyLo": "1206 MELVIN ST SPARTANBURG",
        "TAXPIN": "712490588793",
        "StreetAddr": "PO BOX 91 ATLANTA",
        "City": "ATLANTA", "State": "GA", "Zip": "30301",
    }
    attrs = _safe_attrs(row, cfg)
    assert "StreetAddr" not in attrs and "City" not in attrs and "Zip" not in attrs
    assert attrs["SITUS_ADDR"] == "1206 MELVIN ST SPARTANBURG"
    assert attrs["PARID"] == "712490588793"


def test_safe_attrs_invents_nothing_when_the_layer_has_no_situs():
    cfg = _endpoint_cfg(_lead(county="Union"))
    attrs = _safe_attrs({"Name": "BYRD SANDRA", "ParcelID": "0123456789",
                         "Address_1": "PO BOX 5"}, cfg)
    assert "SITUS_ADDR" not in attrs
    assert "Address_1" not in attrs       # mailing, and an alias for site_address
    assert attrs["PARID"] == "0123456789"


def test_speculative_last_first_reading_requires_full_containment():
    """'Casey William Gillespie' is FIRST MIDDLE LAST. Read speculatively as
    surname CASEY it lines up positionally with an unrelated 'CASEY WILLIAM
    MICHAEL' — containment on GILLESPIE is what rejects it."""
    assert match_owner("Casey William Gillespie", "CASEY WILLIAM MICHAEL") is None
    # A genuinely surname-first source name still resolves.
    assert match_owner("Byrd Sandra", "BYRD SANDRA D") in ("exact", "strong")
