"""court_signals audit 2026-10-09: two scorer guards (made-up rows).

1. A bankruptcy filing row is scored only when it is about a property: a parcel, or a street
   address with a house number. 751 rows of the 2026-10-08 checkpoint carried '<debtor name> —
   <case>' in street_address and passed the old truthiness test (F11).
2. A row built from an NC Judgment Search hit is not scored once its own block says the judgment
   ended (Canceled, Satisfied, ...): 762 rows (43 WARM) did on the same checkpoint, almost all
   from the legacy nc_ecourts_judgments lane, which kept every status.
"""
from __future__ import annotations

from foreclosure_scraper.distress_score import _signals_for, court_record_ended, has_property_address
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _names(li: Listing) -> set[str]:
    return {n for n, _c, _w in _signals_for(li)}


def _bk(addr, parcel=None) -> Listing:
    return Listing(source="courtlistener.recap", source_url="https://example.test/docket/1/",
                   listing_type=ListingType.BANKRUPTCY, property_kind=PropertyKind.UNKNOWN,
                   state="NC", county="Gaston", case_number="26-00001", street_address=addr,
                   parcel_id=parcel, raw={})


def test_bankruptcy_needs_a_house_numbered_address_or_a_parcel():
    assert "bankruptcy" in _names(_bk("12 Example Rd"))
    assert "bankruptcy" in _names(_bk(None, parcel="1234567890"))
    assert "bankruptcy" not in _names(_bk("Sample Person — 26-00001"))
    assert "bankruptcy" not in _names(_bk("EXAMPLE RD"))
    assert "bankruptcy" not in _names(_bk("0 Example Rd"))
    assert not has_property_address(_bk("Sample Person — 26-00001"))


def _ec(status: str, source="nc_ecourts_judgments", lt=ListingType.LIS_PENDENS) -> Listing:
    return Listing(source=source, source_url="https://example.test/ec", listing_type=lt,
                   property_kind=PropertyKind.UNKNOWN, state="NC", county="Cleveland",
                   case_number="25M000001-220", street_address="12 Example Rd",
                   raw={"nc_ecourts": {"cause_of_action": "CV - Claim of Lien",
                                       "civil_judgment_status": status}})


def test_an_ended_judgment_no_longer_scores():
    assert "lis_pendens" in _names(_ec("Active"))
    for s in ("Canceled", "Satisfied", "Dismissed", "Vacated", "Child Support Terminated"):
        assert "lis_pendens" not in _names(_ec(s)), s
    assert court_record_ended({"nc_ecourts": {"civilJudgmentStatus": "Canceled"}})
    assert not court_record_ended({"nc_ecourts": {"civilJudgmentStatus": "Active"}})


def test_the_guard_reads_only_ecourts_rows():
    li = _ec("Canceled", source="law_firms.example")
    assert "lis_pendens" in _names(li)
