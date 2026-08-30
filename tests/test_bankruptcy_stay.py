"""Unit tests for the bankruptcy-stay derivation (Ch13/Ch7 status + resume-risk)."""
from foreclosure_scraper.models import Listing, PropertyKind, ListingType
from foreclosure_scraper.enrichment_bankruptcy_stay import enrich_bankruptcy_stay


def _li(ltype, bk):
    li = Listing(source="t", source_url="https://x", state="NC",
                 listing_type=ltype, property_kind=PropertyKind.UNKNOWN)
    li.raw = {"bankruptcy": bk} if bk else {}
    return li


def test_ch13_foreclosure_is_stayed_moderate_when_recent():
    li = _li(ListingType.FORECLOSURE_SALE, {"chapter": "13", "date_filed": "2026-08-01",
                                            "case_name": "Jane Doe"})
    s = enrich_bankruptcy_stay([li])
    assert s["stayed"] == 1 and s["ch13"] == 1
    st = li.raw["bankruptcy_stay"]
    assert st["status"] == "stayed" and st["chapter"] == "13"
    assert st["resume_risk"] == "moderate"   # <9 months old


def test_ch13_old_case_is_elevated_resume_risk():
    li = _li(ListingType.LIS_PENDENS, {"chapter": "13", "date_filed": "2024-01-01",
                                       "case_name": "Old Case"})
    enrich_bankruptcy_stay([li])
    assert li.raw["bankruptcy_stay"]["resume_risk"] == "elevated"   # >9 months


def test_ch7_is_high_resume_risk():
    li = _li(ListingType.FORECLOSURE_SALE, {"chapter": "7", "date_filed": "2026-08-01"})
    s = enrich_bankruptcy_stay([li])
    assert s["ch7"] == 1 and s["elevated_resume_risk"] == 1
    assert li.raw["bankruptcy_stay"]["resume_risk"] == "high"


def test_non_foreclosure_type_not_stayed():
    # a standalone BK lead or an REO match is not a "stayed foreclosure"
    li = _li(ListingType.REO, {"chapter": "13", "date_filed": "2026-08-01"})
    s = enrich_bankruptcy_stay([li])
    assert s["stayed"] == 0
    assert "bankruptcy_stay" not in li.raw


def test_no_bankruptcy_tag_is_noop():
    li = _li(ListingType.FORECLOSURE_SALE, None)
    s = enrich_bankruptcy_stay([li])
    assert s["stayed"] == 0
