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
