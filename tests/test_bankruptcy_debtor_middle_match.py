"""Bankruptcy debtor-name match accuracy fix (2026-10-02).

A live population-scale check found 234 board rows with comparable owner-
name-vs-debtor-case-name data: only 56% strong real matches, 38.5% weak/
likely-wrong-person, 5.6% a confirmed different real person. Re-deriving
concrete (defendant, case_name) pairs straight off the live board (see
enrichment_bankruptcy.py's module docstring, "MATCH-ACCURACY FIX") confirmed
the OLD matcher's "strict subset" check was a position-blind bag-of-tokens
comparison that also pooled a joint filing's two debtors into one token set.
These tests reproduce the exact false positives found live, and confirm a
real corroborating match -- a genuine positional first/last candidate,
checked ONE debtor at a time via the new name_normalize.debtor_positional_match
-- is still accepted. Same "common-name-only rejected; a real corroborating
match accepted" pattern as tests/test_jail_bookings_cross_county.py and
tests/test_marriage_license_rod.py from the same day, with one deliberate
difference from the SC-divorce fix: bankruptcy does NOT require a positive
middle-initial AGREEMENT (`debtor_middle_verdict(...) == "agrees"`), only
that it isn't a PROVEN conflict. See debtor_positional_match's own docstring
and the "positional match with no middle corroboration is still accepted"
test below for exactly why that asymmetry is deliberate, not an oversight.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper import enrichment_bankruptcy as eb
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.name_normalize import debtor_middle_verdict, debtor_positional_match


# ---- name_normalize.debtor_positional_match, direct ---------------------------------

def test_positional_match_requires_the_SAME_debtor_segment_for_first_and_last():
    # No single debtor in this joint filing is named "Robert ... Jones".
    assert debtor_positional_match(
        "Jones, Robert", ["Robert Curtis Best and Shannon Marie Jones"]) is False


def test_positional_match_true_even_with_no_middle_on_either_side():
    assert debtor_positional_match("Tallant, Bryan", ["Bryan Tallant"]) is True


def test_positional_match_finds_the_correct_half_of_a_joint_filing():
    assert debtor_positional_match(
        "Turner, Susan E", ["Charles Michael Turner and Susan Eudy Turner"]) is True


# ---- name_normalize.debtor_middle_verdict, direct ----------------------------------

def test_debtor_middle_verdict_rejects_the_joint_filer_composite_phantom():
    assert debtor_middle_verdict("Jones, Robert",
                                  ["Robert Curtis Best and Shannon Marie Jones"]) == "unverified"


def test_debtor_middle_verdict_rejects_a_position_blind_match():
    assert debtor_middle_verdict("Davis, David", ["Bryan David Davis"]) == "unverified"


def test_debtor_middle_verdict_flags_a_proven_conflict():
    # ALL CAPS, no comma -> GIS surname-first convention (surname MOORE,
    # given JAMES, middle initial A) -- same convention _fc()'s mixed-case
    # "Moore James A" would NOT trigger (see owner_last_first_middle).
    assert debtor_middle_verdict("MOORE JAMES A", ["James Dewayne Moore"]) == "conflict"


def test_debtor_middle_verdict_agrees_on_a_real_single_filer():
    assert debtor_middle_verdict("Tallant, Bryan C", ["Bryan Christopher Tallant"]) == "agrees"


def test_debtor_middle_verdict_agrees_on_the_correct_half_of_a_joint_filing():
    assert debtor_middle_verdict(
        "Turner, Susan E", ["Charles Michael Turner and Susan Eudy Turner"]) == "agrees"


def test_debtor_middle_verdict_unverified_with_no_middle_on_either_side():
    assert debtor_middle_verdict("Foster, Johnny", ["Johnny Foster"]) == "unverified"


def _fc(defendant, state="NC"):
    return Listing(source="counties_generic.some_tax_source", source_url="u",
                   listing_type=ListingType.TAX_LIEN, defendant=defendant, state=state, raw={})


def _hit(case_name, court="ncwb", docket="26-10701", date_filed="2026-06-01"):
    return {"case_name": case_name, "docket_number": docket, "date_filed": date_filed,
            "date_terminated": None, "absolute_url": f"/docket/1/{docket}/"}


def _run(listing, hits_by_court: dict):
    async def _rec(c, court, tok):
        return hits_by_court.get(court, [])

    async def _go():
        with patch.object(eb, "_load_token", return_value="faketoken"), \
             patch.object(eb, "_fetch_recent_bankruptcies", new=AsyncMock(side_effect=_rec)), \
             patch.object(eb, "_fetch_chapter", new=AsyncMock(return_value="13")), \
             patch.object(eb, "_fetch_long_open_bankruptcies", new=AsyncMock(return_value=[])):
            await eb.enrich_with_bankruptcy([listing])

    asyncio.run(_go())
    return listing.raw.get("bankruptcy")


# ---- the live false positives, reproduced -----------------------------------------

def test_joint_filer_composite_phantom_is_rejected():
    """'JONES, ROBERT' is neither debtor in this joint filing -- it is debtor
    #1's first name ('Robert' Curtis Best) glued to debtor #2's last name
    (Shannon Marie 'Jones'). The OLD bag-of-tokens matcher pooled both
    debtors into one set and matched this; the new positional, per-debtor
    check must not."""
    li = _fc("Jones, Robert")
    bk = _run(li, {"ncwb": [_hit("Robert Curtis Best and Shannon Marie Jones")]})
    assert bk is None


def test_middle_name_mistaken_for_first_name_is_rejected():
    """'David' is Bryan Davis's MIDDLE name, not his first name -- a bag-of-
    tokens check cannot tell the difference; a positional check can."""
    li = _fc("Davis, David")
    bk = _run(li, {"ncwb": [_hit("Bryan David Davis")]})
    assert bk is None


def test_first_name_mistaken_for_surname_is_rejected():
    """'Lewis' is the real debtor's FIRST name, not his surname -- the owner
    (ALL CAPS, no comma -> GIS surname-first convention) claims surname=
    LEWIS, given=WILLIAM; the real debtor is Lewis William Hedgepeth
    (surname Hedgepeth). A middle initial on the owner's side makes sure
    this is rejected on the POSITION mismatch, not merely for lacking one."""
    li = _fc("LEWIS WILLIAM G")
    bk = _run(li, {"ncwb": [_hit("Lewis William Hedgepeth")]})
    assert bk is None


def test_conflicting_middle_name_same_first_and_last_is_rejected():
    """Same first+last ('James Moore'), a DIFFERENT real middle name on the
    debtor -- a different person with a common name."""
    li = _fc("Moore James A")
    bk = _run(li, {"ncwb": [_hit("James Dewayne Moore")]})
    assert bk is None


def test_joint_filer_middle_name_mistaken_for_a_third_debtor_is_rejected():
    """'TURNER, MICHAEL' is not either real debtor: 'Michael' sits in debtor
    #1's MIDDLE slot (Charles Michael Turner), not a first-name slot, and
    debtor #2 (Susan Eudy Turner) shares the surname but nothing else. The
    old bag-of-tokens matcher accepted this live; the positional per-debtor
    check must not."""
    li = _fc("Turner, Michael C", state="NC")
    bk = _run(li, {"ncwb": [_hit("Charles Michael Turner and Susan Eudy Turner")]})
    assert bk is None


def test_cross_state_filing_is_rejected_even_with_a_perfect_name_match():
    """The jurisdiction check: an otherwise-perfect positional+middle match
    must still be rejected when the filing's own court is in the OTHER
    state from the candidate listing -- the old code never checked this at
    all (one global NC+SC index, no state gate)."""
    li = _fc("Tallant, Bryan Christopher", state="SC")
    bk = _run(li, {"ncwb": [_hit("Bryan Christopher Tallant")]})   # ncwb = NC, listing = SC
    assert bk is None


# ---- the real corroborating match is still accepted --------------------------------

def test_positional_match_with_agreeing_middle_initial_is_accepted():
    li = _fc("Tallant, Bryan C")
    bk = _run(li, {"ncwb": [_hit("Bryan Christopher Tallant")]})
    assert bk is not None
    assert bk["case_name"] == "Bryan Christopher Tallant"
    assert bk["match_strategy"] == "positional_match"
    assert bk["signal"] == "recent_filing"


def test_joint_filer_real_debtor_match_is_accepted():
    """The genuine counterpart to the rejected case above: the owner really
    IS one of the two real debtors in this joint filing (Susan Eudy Turner
    herself), not a phantom assembled from the other debtor's middle name."""
    li = _fc("Turner, Susan E", state="NC")
    bk = _run(li, {"ncwb": [_hit("Charles Michael Turner and Susan Eudy Turner")]})
    assert bk is not None
    assert bk["match_strategy"] == "positional_match"


def test_single_filer_exact_name_match_in_the_right_state_is_accepted():
    li = _fc("Homeowner, Jane Q", state="SC")
    bk = _run(li, {"scb": [_hit("Jane Q Homeowner", court="scb")]})
    assert bk is not None
    assert bk["match_strategy"] == "positional_match"


def test_positional_match_with_no_middle_corroboration_is_still_accepted():
    """The deliberate asymmetry with the SC-divorce fix: 'FOSTER, JOHNNY' has
    no middle name at all, and neither does the real debtor 'Johnny Foster'
    -- this is 'unverified', not 'agrees'. SC-divorce would reject that
    outright (0% real at population scale justified the stricter bar
    there); bankruptcy's defendant field routinely lacks a middle name even
    on a correct match (56% of a comparable live sample were already strong,
    correct matches), so a real positional candidate with no PROVEN conflict
    is accepted here instead of discarded."""
    li = _fc("Foster, Johnny", state="NC")
    bk = _run(li, {"ncwb": [_hit("Johnny Foster")]})
    assert bk is not None
    assert bk["match_verdict"] == "unverified"
    assert bk["match_strategy"] == "positional_match"
