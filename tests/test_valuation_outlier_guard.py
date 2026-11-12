"""An outlier ARV names its evidence or is withheld (audit 2026-10-09, area valuation).

Outlier: over $1M, over 8x the parcel's largest 100%-basis county value, or over 5x the highest
cited comp. Basis: the county value within 2.5x (6x for land), a cited comp sold for at least
half the ARV, or the seller's own asking price. The parcel's recorded sale is not a basis (it is
what raises the ARV when it floors it, and one deed can cover several parcels). Made-up rows.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc
from foreclosure_scraper.valuation import grading


def _li(**kw) -> Listing:
    base = dict(source="counties_nc.test", source_url="http://x",
                listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Buncombe",
                property_kind=PropertyKind.SINGLE_FAMILY)
    base.update(kw)
    return Listing(**base)


def _comps(price: float, sqft: float = 2000, n: int = 3) -> list[dict]:
    p = price / sqft
    return [{"sold_price": price, "sqft": sqft, "price_per_sqft": p, "adjusted_ppsf": p,
             "kind": "sfr", "geo_anchored": True, "sold_date": "2026-08-01"} for _ in range(n)]


def test_ordinary_house_carries_no_basis_check():
    li = _li(living_sqft=1500, market_value=250_000,
             raw={"comps": _comps(300_000, 1600), "comp_median_ppsf": 187.5})
    c = vcalc.compute(li)
    assert c.arv_expected and c.arv_expected < 1_000_000
    assert c.arv_basis_check is None
    assert "arv_basis_check" not in vcalc.to_dict(c)


def test_million_dollar_arv_supported_by_county_value_is_explained():
    li = _li(living_sqft=4000, market_value=1_200_000,
             raw={"comps": _comps(1_300_000, 4000), "comp_median_ppsf": 325.0})
    c = vcalc.compute(li)
    assert c.arv_expected and c.arv_expected > 1_000_000
    chk = c.arv_basis_check
    assert chk["verdict"] == "explained"
    assert any("county value" in b for b in chk["basis"])
    assert any("over $1,000,000" in t for t in chk["triggers"])
    assert vcalc.ARV_FLAG_UNEXPLAINED_OUTLIER not in (c.arv_flags or [])


def test_million_dollar_arv_with_no_basis_is_withheld():
    """Big subject sqft times small-house comps, no county value: nothing supports $1.6M."""
    li = _li(living_sqft=8000, raw={"comps": _comps(400_000, 2000), "comp_median_ppsf": 200.0})
    c = vcalc.compute(li)
    assert c.arv_expected is None
    assert c.arv_withheld and c.arv_withheld > 1_000_000
    assert vcalc.ARV_FLAG_UNEXPLAINED_OUTLIER in c.arv_flags
    assert c.arv_basis_check["verdict"] == "withheld"
    assert c.max_bid_70 is None
    assert grading.arv_trust(c.arv_flags, c.arv_expected, c.arv_withheld) == "withheld"
    assert any(n.startswith("ARV WITHHELD") and "nothing on the record supports it" in n
               for n in c.notes)


def test_floor_from_a_deed_far_above_the_county_value_is_withheld():
    """A $1.4M recorded sale on a lot the county values at $274K raised the ARV (the 10/8
    checkpoint's Greenville rows); with no comp or county value near it, it is withheld."""
    li = _li(state="SC", county="Greenville", living_sqft=2250, market_value=274_000,
             raw={"gis": {"last_sale": {"amount": 1_400_000, "date": "2026-03-01"}}})
    c = vcalc.compute(li)
    assert c.arv_expected is None
    assert c.arv_withheld == 1_400_000
    assert vcalc.ARV_FLAG_UNEXPLAINED_OUTLIER in c.arv_flags


def test_arv_over_five_times_the_highest_comp_needs_a_basis():
    # county-wide (unanchored) comps are cited but do not price; the county market value does
    comps = _comps(60_000, 1800)
    for x in comps:
        x["geo_anchored"] = False
    li = _li(living_sqft=1800, market_value=400_000, raw={"comps": comps})
    c = vcalc.compute(li)
    assert c.arv_expected and c.arv_expected > 5 * 60_000
    chk = c.arv_basis_check
    assert chk and any("highest cited comp" in t for t in chk["triggers"])
    assert chk["verdict"] == "explained"          # the county value supports it


def _land_comps(price: float, acres: float) -> list[dict]:
    return [{"sold_price": price, "lot_sqft": acres * 43560, "kind": "land", "geo_anchored": True,
             "sold_date": "2026-08-01"} for _ in range(3)]


def test_land_arv_over_eight_times_county_value_explained_by_its_land_comps():
    """Present-use land: the county figure is far below market, the land comps are not."""
    li = _li(property_kind=PropertyKind.LAND, acreage=5.0, tax_value=20_000,
             raw={"comps": _land_comps(200_000, 5.0)})
    c = vcalc.compute(li)
    assert c.arv_expected and c.arv_expected > 8 * 20_000
    assert c.arv_basis_check["verdict"] == "explained"
    assert any("cited comp" in b for b in c.arv_basis_check["basis"])


def test_arv_over_five_times_every_cited_comp_with_no_county_value_is_withheld():
    """Recorded $/sqft times 3,000 sqft gives ~$530K; the comps cited on the row sold for
    $90K and there is no county value: the two records describe different properties."""
    li = _li(living_sqft=3000,
             raw={"recorded_comps": {"median_ppsf": 200.0, "count": 12, "confidence": "HIGH",
                                     "radius_mi": 1.0},
                  "comp_median_ppsf_recorded": 200.0,
                  "comps": _comps(90_000, 1000)})
    c = vcalc.compute(li)
    assert c.arv_expected is None
    assert c.arv_withheld and c.arv_withheld > 5 * 90_000
    assert c.arv_basis_check == {"triggers": ["over 5x the highest cited comp"], "basis": [],
                                 "verdict": "withheld"}


def test_outlier_triggers_shared_helper():
    t = vcalc.outlier_triggers(1_200_000, 100_000, 200_000)
    assert len(t) == 3
    assert vcalc.outlier_triggers(300_000, 100_000, 200_000) == []
    assert vcalc.outlier_triggers(300_000, None, None) == []


def test_unexplained_outlier_flag_is_contradicted():
    assert "arv_unexplained_outlier" in grading.ARV_FLAGS_CONTRADICTED
