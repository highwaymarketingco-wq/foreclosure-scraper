"""The owner name itself is a distress signal, but the tokens are not equal.

A county assessor does not rewrite the owner of record unprompted -- the name becomes
"ESTATE OF ..." / "HEIRS OF ..." / "... ET AL" because a survivor rang the tax office
about the bill (Dirty Deeds eps 036, 064). So the token implies a death or an
ownership fracture AND an engaged survivor who already contacted a government office.

The grading is the point of these tests. Publishing one flat count would overstate
it: a living TRUST is ordinary estate planning -- a solvent owner with a lawyer, the
opposite of the target profile -- and "C/O" is as often a property manager. Those
must never be scored alongside "HEIRS OF".
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_owner_name_signal import (
    classify,
    enrich_owner_name_signal,
)
from foreclosure_scraper.models import Listing


@pytest.mark.parametrize("name,token", [
    ("ESTATE OF JOHN SMITH", "estate_of"),
    ("EST OF MARY JONES", "estate_of"),
    ("SMITH JOHN DECEASED", "deceased"),
    ("JONES MARY DEC'D", "deceased"),
    ("SMITH JOHN LIFE ESTATE", "life_estate"),
    ("HEIRS OF WILLIAM BROWN", "heirs"),
    ("BROWN WILLIAM HEIR", "heirs"),
])
def test_strong_tokens_imply_a_death(name, token):
    sig = classify(name)
    assert sig is not None
    assert sig["grade"] == "strong"
    assert token in sig["tokens"]


def test_et_al_is_medium_not_strong():
    """Fractured ownership. The multi-owner mess, but not necessarily a death."""
    sig = classify("SMITH JOHN ET AL")
    assert sig["grade"] == "medium"


# ===========================================================================
# ABBREVIATION/CONCATENATION VARIANTS LIVE-FOUND ON THE REAL BOARD, 2026-10-03
#
# name_heirs (52/148) and name_et_al (57/148) were live-verified against
# board_stream.iter_board_rows() and reproduced exactly -- not stale. But the
# live sweep also turned up real owner_name shapes the original regexes could
# not see at all:
#   - "HEIRS1" / "HEIR2" -- a GIS fractional-interest concatenation (Rutherford
#     NC: "HOFFMAN, CARL V HEIRS1") with no word boundary between the token
#     and the appended digit.
#   - "ETALS" / "ET ALS" -- the plural Latin form with no separator, the
#     dominant shape in Dillon SC's own roll (16 of 84 live rows) and present
#     in 9 other counties.
#   - bare "HRS" -- a standalone abbreviation for "heirs" with no HEIR
#     substring at all, live-found in NC Orange (127 rows) and SC Georgetown
#     (24 rows) -- e.g. "SHERIDAN SAMUEL HRS".
# ===========================================================================

@pytest.mark.parametrize("name", [
    "HOFFMAN, CARL V HEIRS1",
    "ONEAL, O W JR HEIRS1",
])
def test_heirs_digit_suffix_concatenation_matches(name):
    """A county GIS system concatenates a fractional-interest number directly
    onto the token with no separator -- the plain word must still be seen."""
    sig = classify(name)
    assert sig is not None
    assert "heirs" in sig["tokens"]
    assert sig["grade"] == "strong"


@pytest.mark.parametrize("name", [
    "HOELLMAN JOHN R JR ETALS",
    "BRUNSON WHITNEY A ETALS",
    "RIGGSBEE, MYRTLE L HRS ET AL",
])
def test_et_al_plural_and_no_separator_variants_match(name):
    sig = classify(name)
    assert sig is not None
    assert "et_al" in sig["tokens"]


@pytest.mark.parametrize("name", [
    "SHERIDAN SAMUEL HRS",
    "GREEN TOM JR HRS",
    "JACOBS, HIAWATHA H HRS",
])
def test_bare_hrs_abbreviation_matches_heirs(name):
    sig = classify(name)
    assert sig is not None
    assert "heirs" in sig["tokens"]
    assert sig["grade"] == "strong"


@pytest.mark.parametrize("name", [
    "HRS Property Group, LLC",
    "HRS Property Group, LLC, a North Carolina Limited Liability Company",
])
def test_bare_hrs_abbreviation_is_suppressed_for_a_real_business_name(name):
    """The real board carries this exact company (NC Yadkin) -- "HRS" is only 3
    letters and collides with a real business name, unlike the full word
    "HEIRS", so the abbreviation must not fire on anything that reads as an
    entity."""
    assert classify(name) is None


# ===========================================================================
# "C/O" MAILING-CONTACT VARIANTS LIVE-FOUND ON THE REAL BOARD, 2026-10-03
#
# name_care_of (42/148) is the same "weak" grade as plain C/O for the same
# reason -- a property manager or caretaker is as common as an heir here, so
# neither must ever outrank a real death/fracture token. The live sweep
# found two more real mailing-contact shapes the original "C/O"-only regex
# could not see:
#   - a bare "%" used as SC tax-roll shorthand for "care of" (202 rows / 10
#     counties, Dillon SC dominant: "ADAMS EARLINE BETHEA ETAL % EARLINE
#     ADAMS"), deliberately distinguished from the DIFFERENT real meaning of
#     "51% INT" / "1% INT" (a fractional ownership share, not a mailing
#     contact -- 3 live rows ruled out) by requiring a space before the `%`
#     with no digit before that space.
#   - "ATTN" (23 rows / 7 counties: "WATTS JACKSON ATTN. PARTIN CHRIS").
# Spelled-out "CARE OF" was tested and deliberately NOT added: all 6 live
# hits are real entity names that happen to contain the phrase ("Home Care
# of the Upstate LLC", "Autumn Care of Drexel"), not an owner routed to a
# contact.
# ===========================================================================

@pytest.mark.parametrize("name", [
    "ALFORD MELVIN C %OCTAVIA ALFORD",
    "BETHEA LESSIE %KENNETH CARMICHAEL",
    "WATTS JACKSON ATTN. PARTIN CHRIS",
    "DEFUSCO VELMA C ATTN: CANDICE SMITH",
])
def test_care_of_mailing_contact_variants_match(name):
    sig = classify(name)
    assert sig is not None
    assert "care_of" in sig["tokens"]
    assert sig["grade"] == "weak"


def test_care_of_percent_variant_coexists_with_a_stronger_token():
    """Real board row: the '%' shorthand and ETAL both fire on the same name --
    care_of must still be recorded (for the richer tokens list) even though
    the overall grade is won by the stronger et_al token, same precedent as
    the existing strong-beats-weak test."""
    sig = classify("ADAMS EARLINE BETHEA ETAL % EARLINE ADAMS")
    assert sig is not None
    assert {"et_al", "care_of"} <= set(sig["tokens"])
    assert sig["grade"] == "medium"


@pytest.mark.parametrize("name", [
    "MCGUGAN LAURA LYNN 1% INT & BELL KAY F 99% INT HEIRS",
    "CHARLES ANTHONY HUFFSTETLER REVOCABLE TRUST 51% INT & BINGHAM PATRICIA L 49% INT",
    "KING ROGER 99% INTEREST &",
])
def test_percent_ownership_interest_is_not_read_as_care_of(name):
    """'N% INT' is a fractional ownership share, a completely different real
    meaning from the tax-roll '%' mailing-contact shorthand -- the board
    never writes this shape with a space before the '%', which is exactly
    what the care_of pattern requires."""
    sig = classify(name)
    assert sig is None or "care_of" not in sig["tokens"]


@pytest.mark.parametrize("name", [
    "AUTUMN CARE OF DREXEL",
    "Xtreme Home Care of the Upstate LLC",
    "HELPING HANDS HOME CARE OF SPARTANBURG I",
    "HOLISTIC CARE OF CHARLESTON LLC",
])
def test_spelled_out_care_of_is_not_matched(name):
    """These are real entity names that happen to contain the phrase 'care
    of' -- not an owner being routed to a mailing contact. Adding a
    spelled-out 'CARE OF' pattern would be 100% false positive on this
    board, so it is deliberately not matched."""
    sig = classify(name)
    assert sig is None or "care_of" not in sig["tokens"]


@pytest.mark.parametrize("name,false_positive", [
    ("Gayle A Heiring", "heirs"),       # surname contains HEIR with no boundary
    ("MYNHEIR KIMBERLY A", "heirs"),
    ("CARVALHEIRA, MICHAEL", "heirs"),
    ("Julia Heironymus", "heirs"),
])
def test_heir_substring_inside_an_unrelated_surname_does_not_match(name, false_positive):
    """Same word-boundary guard as the existing PINHEIRO/HEIR fix -- a surname
    that merely contains the letters must never imply a death."""
    sig = classify(name)
    assert sig is None or false_positive not in sig["tokens"]


@pytest.mark.parametrize("name", [
    "SMITH FAMILY REVOCABLE TRUST",
    "JOHN SMITH TRUSTEE",
    "MARY JONES C/O ACME PROPERTY MGMT",
    "UNKNOWN OWNER",
])
def test_weak_tokens_are_graded_weak(name):
    """A living trust is a solvent owner with a lawyer. Do not rank it as distress."""
    assert classify(name)["grade"] == "weak"


def test_plain_owner_name_yields_nothing():
    assert classify("JOHN SMITH") is None
    assert classify("") is None
    assert classify(None) is None


@pytest.mark.parametrize("name", [
    "COUNTY OF BUNCOMBE TRUSTEE",
    "STATE OF NORTH CAROLINA HEIRS",
    "ACME BANK N.A. TRUSTEE",
])
def test_institutional_owner_WITH_a_token_is_capped_at_weak(name):
    """A government or lender owner is not a motivated seller, even when the string
    happens to contain HEIRS or TRUSTEE. The token is recorded, the grade is capped."""
    sig = classify(name)
    assert sig is not None
    assert sig["institutional_owner"] is True
    assert sig["grade"] == "weak"


@pytest.mark.parametrize("name", [
    "CITY OF SPARTANBURG",
    "FEDERAL NATIONAL MORTGAGE ASSOC",
    "SECRETARY OF HOUSING AND URBAN DEV",
])
def test_institutional_owner_with_NO_token_yields_nothing(name):
    """No death or fracture token at all means no signal -- not a weak signal.
    These names are institutional but there is nothing to grade, so the enricher
    must stay silent rather than tag every government parcel."""
    assert classify(name) is None


def test_strong_beats_weak_when_both_present():
    """'HEIRS OF X TRUST' carries both; the death signal wins."""
    sig = classify("HEIRS OF JOHN SMITH TRUST")
    assert sig["grade"] == "strong"
    assert set(sig["tokens"]) >= {"heirs", "trust"}


def _rows(names):
    return [Listing(source="t.x", source_url="http://x", street_address=f"{i} Main St",
                    county="Spartanburg", state="SC", owner_name=n)
            for i, n in enumerate(names)]


def test_enrich_tags_and_never_drops():
    rows = _rows(["ESTATE OF JOHN SMITH", "SMITH JOHN ET AL",
                  "SMITH FAMILY TRUST", "PLAIN JANE OWNER",
                  "COUNTY OF BUNCOMBE TRUSTEE"])
    n = len(rows)
    stats = enrich_owner_name_signal(rows)
    assert len(rows) == n
    assert stats["tagged"] == 4          # PLAIN JANE OWNER matches nothing
    assert stats["strong"] == 1
    assert stats["medium"] == 1
    assert stats["weak"] == 2            # the trust and the county
    assert stats["institutional"] == 1
    assert rows[3].raw is None or "owner_name_signal" not in (rows[3].raw or {})


def test_signal_survives_the_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "owner_name_signal" in RAW_KEEP


# ===========================================================================
# A STALE STAMP MUST NOT SURVIVE AN OWNER-NAME CHANGE
#
# fullmer_rank.score() reads raw['owner_name_signal']['grade'] DIRECTLY (not a
# fresh classify() call) to award owner_name_death/fracture points. If the
# property sells (or an estate closes) and owner_freshness.py / a later full
# pipeline run refreshes owner_name to a living owner, re-running this
# enricher must erase the old stamp -- not leave "strong"/"deceased" sitting
# behind implying a death signal that no longer holds on today's record.
# ===========================================================================

def test_enrich_clears_a_stale_stamp_when_the_name_no_longer_matches():
    rows = _rows(["ESTATE OF JOHN SMITH"])
    enrich_owner_name_signal(rows)
    assert rows[0].raw["owner_name_signal"]["primary_token"] == "estate_of"

    # The property sold; a refresh (owner_freshness.py, a full pipeline run)
    # overwrote owner_name with the new, living owner -- but the stale stamp
    # from the old name is still sitting in raw until this enricher re-runs.
    rows[0].owner_name = "CHURCH OF JESUS CHRIST OF LDS"
    stats = enrich_owner_name_signal(rows)
    assert "owner_name_signal" not in rows[0].raw
    assert stats["stale_cleared"] == 1
    assert stats["tagged"] == 0


def test_enrich_leaves_a_still_matching_stamp_alone():
    """No name change, no token change -- re-running must not churn the stamp
    or count it as cleared."""
    rows = _rows(["HEIRS OF WILLIAM BROWN"])
    enrich_owner_name_signal(rows)
    stats = enrich_owner_name_signal(rows)
    assert rows[0].raw["owner_name_signal"]["primary_token"] == "heirs"
    assert stats["stale_cleared"] == 0
    assert stats["tagged"] == 1


def test_fullmer_rank_does_not_score_a_stale_owner_name_signal():
    """The real bug this closes: fullmer_rank.py trusts the stored
    raw['owner_name_signal'] field rather than re-deriving it, so a stale
    'strong'/deceased stamp left over from a sold property's old owner name
    kept awarding owner_name_death points after the sale. Simulates exactly
    that -- a raw blob carrying the OLD signal next to a CURRENT owner_name
    that no longer matches any token -- which only this enricher's clearing
    behavior, run again, can fix."""
    rows = _rows(["CHURCH OF JESUS CHRIST OF LDS"])
    rows[0].raw = {"owner_name_signal": {"tokens": ["deceased"], "primary_token": "deceased",
                                          "grade": "strong", "institutional_owner": False,
                                          "source": "owner_name_token"}}
    enrich_owner_name_signal(rows)
    assert "owner_name_signal" not in rows[0].raw

    from foreclosure_scraper.fullmer_rank import score
    r = score(rows[0])
    assert "owner_name_death" not in str(r)


# ===========================================================================
# THE ABSENTEE SIGNAL WAS BEING SCORED FROM TWO EMPTY KEYS
#
# fullmer_rank.score() awards 8 points for an absentee owner -- Fullmer is
# explicit that out-of-state and non-occupying owners are the target. It read
# raw["distress_stack"]["absentee"] and raw["absentee"].
#
# Measured on the live 94,384-row board, 2026-09-10:
#     raw["owner_mailing"]["absentee"] is True on   56,091 rows
#     the two keys the scorer read covered           10,647 rows
#     absentee rows the scorer could NOT see         45,450   (81% of the signal)
#
# enrichment_owner_mailing is the authority: its _is_absentee tolerates a mailing
# carrying extra city/state/zip, accepts a token-subset match so Anderson's
# 'SPRINGSIDE  300 SPRINGSIDE CIR' situs does not flag its own owner-occupant,
# and an authoritative county homestead marker forces absentee back to False.
# ===========================================================================

def _bare_listing(**raw):
    from datetime import datetime
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(source="t", source_url="u", listing_type=ListingType.TAX_SALE,
                   property_kind=PropertyKind.UNKNOWN, state="NC", county="Buncombe",
                   first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw=raw)


def _has_absentee(li) -> bool:
    from foreclosure_scraper.fullmer_rank import score
    r = score(li)
    return any("absentee" in str(f) for f in (r.get("factors") or r.get("reasons") or []))


@pytest.mark.parametrize("raw,expect", [
    ({"owner_mailing": {"absentee": True}}, True),      # the 45,450 that were invisible
    ({"distress_stack": {"absentee": True}}, True),     # the key that already worked
    ({"absentee": True}, True),                         # the other key that already worked
    ({"owner_mailing": {"absentee": False}}, False),    # owner mails to the property
    ({"owner_mailing": {}}, False),                     # no mailing known
    ({}, False),
])
def test_absentee_is_scored_from_the_key_that_is_actually_populated(raw, expect):
    from foreclosure_scraper.fullmer_rank import score
    r = score(_bare_listing(**raw))
    txt = str(r)
    assert ("absentee" in txt) is expect, f"raw={raw} -> {txt[:220]}"


def test_owner_occupied_is_never_read_as_absentee():
    """A False must stay False. enrichment_owner_mailing sets absentee=False when a
    county homestead marker says the owner lives there, and that authoritative
    suppression must survive into the score -- flagging a homeowner absentee puts
    them on an absentee call list."""
    from foreclosure_scraper.fullmer_rank import score
    r = score(_bare_listing(owner_mailing={"absentee": False, "owner_occupied": True}))
    assert "absentee" not in str(r)


def test_a_non_dict_owner_mailing_does_not_crash_the_scorer():
    """Some sources emit owner_mailing as a bare string; distress_score.py already
    guards for exactly this, and the scorer must too."""
    from foreclosure_scraper.fullmer_rank import score
    assert isinstance(score(_bare_listing(owner_mailing="123 MAIN ST")), dict)
    assert isinstance(score(_bare_listing(owner_mailing=None)), dict)
