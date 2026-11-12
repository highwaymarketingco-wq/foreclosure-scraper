"""Unit tests for the absentee-owner determination (GIS owner-mailing).

absentee = the owner mails from somewhere other than the property. It feeds the
distress score (+8) and gates HOT leads on contactability. The prop_addr falls
back to the listing's own street address when the county GIS layer exposes no
situs field, so parcel-match-only counties still flag absentee owners.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_owner_mailing import _is_absentee


def test_absentee_when_mailing_is_a_different_address():
    assert _is_absentee("123 Main St", "456 Oak Ave, Charlotte NC 28202") is True


def test_not_absentee_when_mailing_contains_the_property_address():
    # Owner-occupant: mailing carries the situs plus city/state/zip.
    assert _is_absentee("123 Main St", "123 Main St, Shelby NC 28150") is False


def test_not_absentee_when_no_mailing():
    assert _is_absentee("123 Main St", None) is False
    assert _is_absentee("123 Main St", "") is False


def test_not_absentee_when_no_property_address():
    # No situs and no listing street address -> can't decide -> not flagged
    # (avoids false positives for parcel-only records).
    assert _is_absentee(None, "456 Oak Ave, Charlotte NC 28202") is False


def test_case_and_punctuation_insensitive():
    assert _is_absentee("123 MAIN ST.", "123 Main St, Shelby, NC") is False
    assert _is_absentee("123 main st", "999 ELSEWHERE BLVD, Asheville NC") is True
