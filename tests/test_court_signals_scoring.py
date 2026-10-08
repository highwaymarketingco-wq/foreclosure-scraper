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
                   raw={"nc_ecourts": {"cause_of_action": "CV - Lis Pendens",
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


# ---- claims of lien are not lis pendens (court_signals 2026-10-09, coordinator decision) ----------

def _lien(cause: str, lt=ListingType.LIS_PENDENS, source="counties_nc.nc_ecourts_lis_pendens", signal=None):
    b = {"cause": cause, "civilJudgmentStatus": "Active"}
    if signal:
        b["signal"] = signal
    return Listing(source=source, source_url="https://example.test/ec", listing_type=lt,
                   property_kind=PropertyKind.UNKNOWN, state="NC", county="Gaston",
                   case_number="26M000002-350", parcel_id="1234567890", raw={"nc_ecourts": b})


def _ev(li):
    from foreclosure_scraper.distress_score import _signals_ev
    return {n: (w, e) for n, _c, w, e in _signals_ev(li)}


def test_a_carried_claim_of_lien_scores_as_a_lien_claim_not_a_lis_pendens():
    for li in (_lien("CV - Claim of Lien"), _lien("CV - Lien"),
               _lien("CV - Claim of Lien", lt=ListingType.LIEN_CLAIM, signal="lien_claim")):
        ev = _ev(li)
        assert "lis_pendens" not in ev
        assert ev["lien_claim"] == (10, "name_only")     # lower weight; never a HOT record


def test_a_transcript_of_judgment_scores_as_a_judgment_lien():
    for li in (_lien("CV - Transcript of Judgment"),
               _lien("CV - Transcript of Judgment", lt=ListingType.DISTRESSED, signal="judgment_lien")):
        ev = _ev(li)
        assert "lis_pendens" not in ev and ev["judgment_lien"][0] == 12


def test_a_real_lis_pendens_stays_a_lis_pendens():
    ev = _ev(_lien("CV - Lis Pendens"))
    assert ev["lis_pendens"][0] == 28 and "lien_claim" not in ev


def test_a_claim_of_lien_never_completes_a_hot_stack():
    from foreclosure_scraper.distress_score import score_board
    li = _lien("CV - Claim of Lien", lt=ListingType.LIEN_CLAIM, signal="lien_claim")
    li.raw["tax_owed"] = {"balance": 2500.0, "year": 2024}
    score_board([li])
    ds = li.raw["distress_stack"]
    assert "lien_claim" in ds["signals"] and ds["tier"] != "HOT"
