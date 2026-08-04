"""Free comp spine: county sales-roll parsing, arms-length gating, land banding,
deed-stamp price recovery, and the ratio tier in the ARV calculator.

Fixtures in tests/fixtures/recorded_sales_rows.json are REAL rows captured live
from each county layer (Buncombe saledata + parcel ring, Cleveland improved +
vacant lot sales).
"""
from __future__ import annotations

import json
from pathlib import Path

from foreclosure_scraper import enrichment_recorded_sales as rs
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc

FIXTURES = json.loads((Path(__file__).parent / "fixtures" /
                       "recorded_sales_rows.json").read_text())


def _li(**kw) -> Listing:
    base = dict(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE)
    base.update(kw)
    return Listing(**base)


# --- field / format plumbing ------------------------------------------------
def test_buncombe_pin_dashing_matches_saledata_format():
    # parcel layer pinnum (15 digits) -> saledata PINN (dashed 4-2-4-5)
    assert rs._buncombe_pinn("962845105300000") == "9628-45-1053-00000"
    assert rs._buncombe_pinn("0606317317") is None          # wrong width -> no join


def test_deed_stamps_back_out_price_at_one_dollar_per_five_hundred():
    # Live Cleveland row: 230 stamps == $115,000 stated Sales_Amount.
    row = FIXTURES["cleveland_improved"]["features"][0]["attributes"]
    assert rs._stamp_price(row["Deed_Stamp_Amount"]) == row["Sales_Amount"]


def test_date_parsers():
    assert rs._yyyymmdd_iso(20230303) == "2023-03-03"
    assert rs._yyyymmdd_iso("20220810") == "2022-08-10"
    assert rs._yyyymmdd_iso("garbage") is None
    assert rs._epoch_iso(1752883200000) == "2025-07-19"


# --- arms-length gating -----------------------------------------------------
def _buncombe_sales_from_fixture() -> list[dict]:
    out = []
    for f in FIXTURES["buncombe_saledata"]["features"]:
        a = f["attributes"]
        q = (a.get("QualifiedSale") or "").strip().upper()
        out.append(rs._sale(
            a["PINN"], float(a["SellingPrice"]), rs._epoch_iso(a["SellDate"]),
            book=a.get("DeedBook"), page=a.get("DeedPage"),
            grantor=a.get("Grantor1"), grantee=a.get("Grantee1"),
            arms_length={"Y": True, "N": False}.get(q), qualified_code=q or None,
            vacant=(str(a.get("VacantLot")).strip().lower() == "true"),
            acres=rs._num(a.get("Acres")), assessed=200000.0))
    return out


def test_non_arms_length_is_excluded_from_the_basket():
    sales = _buncombe_sales_from_fixture()
    assert any(s["qualified_code"] == "N" for s in sales)      # fixture has some
    kept = rs._arms_length_only(sales)
    assert all(s["qualified_code"] != "N" for s in kept)


def test_priced_pool_uses_only_county_qualified_when_flag_published():
    sales = _buncombe_sales_from_fixture()
    priced, basis = rs._priced_pool(rs._arms_length_only(sales))
    assert basis == "county_qualified_arms_length_only"
    assert priced and all(s["qualified_code"] == "Y" for s in priced)


def test_priced_pool_falls_back_when_county_publishes_no_flag():
    # Anderson / Cleveland publish no arms-length flag at all.
    sales = [rs._sale("1", 150000.0, "2024-01-01"), rs._sale("2", 200000.0, "2024-02-01")]
    priced, basis = rs._priced_pool(sales)
    assert basis == "all_price_bearing_deeds"
    assert len(priced) == 2


# --- comp math --------------------------------------------------------------
def test_ppa_list_drops_garbage_and_improved_lots():
    sales = [
        rs._sale("a", 100000.0, "2024-01-01", acres=2.0, vacant=True),    # 50,000/ac
        rs._sale("b", 100000.0, "2024-01-01", acres=0.001, vacant=True),  # sub-min acreage
        rs._sale("c", 900000.0, "2024-01-01", acres=0.0201, vacant=True),  # > ppa ceiling
        rs._sale("d", 300000.0, "2024-01-01", acres=3.0, vacant=False),   # improved -> skip
    ]
    assert rs._ppa_list(sales, vacant_only=True) == [50000.0]


def test_acre_band_keeps_size_comparable_land_comps():
    sales = [rs._sale(str(i), 50000.0, "2024-01-01", acres=a)
             for i, a in enumerate((0.20, 0.25, 0.30, 13.5, 40.0))]
    band, label = rs._acre_band(sales, 0.25)
    assert label == "±50% lot size"
    assert sorted(s["acres"] for s in band) == [0.20, 0.25, 0.30]


def test_acre_band_widens_rather_than_returning_nothing():
    sales = [rs._sale("a", 50000.0, "2024-01-01", acres=10.0),
             rs._sale("b", 60000.0, "2024-01-01", acres=12.0)]
    band, label = rs._acre_band(sales, 5.0)
    assert len(band) == 2 and label == "±200% lot size"


def test_ratio_list_bands_out_nonsense():
    sales = [
        rs._sale("a", 150000.0, "2024-01-01", assessed=100000.0),   # 1.50 keep
        rs._sale("b", 100000.0, "2024-01-01", assessed=1000.0),     # 100x  drop
        rs._sale("c", 10000.0, "2024-01-01", assessed=500000.0),    # 0.02  drop
        rs._sale("d", 130000.0, "2024-01-01", assessed=100000.0),   # 1.30 keep
    ]
    assert rs._ratio_list(sales, want_vacant=None) == [1.3, 1.5]


def test_ratio_respects_vacant_class_split():
    sales = [rs._sale("a", 150000.0, "2024-01-01", assessed=100000.0, vacant=False),
             rs._sale("b", 300000.0, "2024-01-01", assessed=100000.0, vacant=True)]
    assert rs._ratio_list(sales, want_vacant=False) == [1.5]
    assert rs._ratio_list(sales, want_vacant=True) == [3.0]


# --- centroid guard ---------------------------------------------------------
def test_county_centroid_cluster_is_detected():
    leads = [_li(state="SC", county="Anderson", latitude=34.504, longitude=-82.65)
             for _ in range(rs.CENTROID_MIN_SHARE)]
    leads.append(_li(state="SC", county="Anderson", latitude=34.8341, longitude=-82.4182))
    bad = rs._degenerate_coords(leads)
    assert (34.504, -82.65) in bad
    assert (34.834, -82.418) not in bad


def test_known_centroids_fire_on_a_small_batch_too():
    # A one-lead incremental batch can never reach the dynamic threshold, so the
    # measured centroid list has to carry it.
    one = [_li(state="NC", county="Cleveland", latitude=35.2924, longitude=-81.5354)]
    assert (35.292, -81.535) in rs._degenerate_coords(one)


# --- writing onto the lead --------------------------------------------------
def _ring_sales(n=12, price=300000.0, assessed=200000.0, vacant=False, acres=0.3):
    return [rs._sale(str(i), price, f"2025-0{i % 9 + 1}-01", assessed=assessed,
                     vacant=vacant, acres=acres, arms_length=True, qualified_code="Y",
                     grantor="A SELLER", grantee="A BUYER", book="6600", page="0100")
            for i in range(n)]


def test_apply_writes_ratio_comps_for_improved():
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.SINGLE_FAMILY,
             latitude=35.5, longitude=-82.5)
    got = rs._apply(li, _ring_sales(), subject_assessed=150000.0,
                    basis_source="county_layer", source="src", note="note")
    rc = li.raw["recorded_ratio_comps"]
    assert got["ratio"] == 1
    assert rc["median_ratio"] == 1.5 and rc["assessed_basis"] == 150000.0
    assert rc["confidence"] == "MEDIUM"        # 12 comps, zero spread
    assert li.raw["recorded_sales"]["parties_published"] is True


def test_apply_writes_land_comps_and_never_clobbers_existing_comps():
    sales = _ring_sales(n=6, price=60000.0, vacant=True, acres=1.0)
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.LAND,
             acreage=1.0, latitude=35.5, longitude=-82.5)
    rs._apply(li, sales, subject_assessed=50000.0, basis_source="county_layer",
              source="src", note="note")
    assert li.raw["comp_median_ppa_recorded"] == 60000.0
    assert li.raw["comps"][0]["lot_sqft"] == 43560
    # land comps landed -> no competing ratio signal on the same lead
    assert "recorded_ratio_comps" not in li.raw

    pre = _li(state="NC", county="Buncombe", property_kind=PropertyKind.LAND,
              acreage=1.0, latitude=35.5, longitude=-82.5,
              raw={"comps": [{"sold_price": 1, "lot_sqft": 1}]})
    rs._apply(pre, sales, subject_assessed=50000.0, basis_source="county_layer",
              source="src", note="note")
    assert pre.raw["comps"] == [{"sold_price": 1, "lot_sqft": 1}]


def test_apply_skips_ratio_without_a_matching_assessed_basis():
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.SINGLE_FAMILY,
             latitude=35.5, longitude=-82.5, tax_value=400000.0)
    rs._apply(li, _ring_sales(), subject_assessed=None, basis_source="none",
              source="src", note="note")
    # li.tax_value is NOT interchangeable with the county basis -> no ratio.
    assert "recorded_ratio_comps" not in li.raw
    assert li.raw["recorded_sales"]["count"] == 12


def test_subject_assessed_prefers_county_layer_over_board_tax_value():
    li = _li(state="NC", county="Buncombe", parcel_id="9628334112",
             tax_value=42300.0, assessed_value=99999.0)
    parcels = [f["attributes"] for f in FIXTURES["buncombe_parcels"]["features"]]
    assert rs._subject_assessed(li, ("NC", "Buncombe"), [], parcels) == (57000.0, "county_layer")
    # No parcel match -> the lead-carried assessed_value, LABELLED as such.
    orphan = _li(state="NC", county="Buncombe", parcel_id="0000000000",
                 tax_value=42300.0, assessed_value=99999.0)
    assert rs._subject_assessed(orphan, ("NC", "Buncombe"), [], parcels) == \
        (99999.0, "lead_assessed_value")


def test_unverified_assessed_basis_can_never_be_medium():
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.SINGLE_FAMILY,
             latitude=35.5, longitude=-82.5)
    rs._apply(li, _ring_sales(n=20), subject_assessed=150000.0,
              basis_source="lead_assessed_value", source="src", note="note")
    assert li.raw["recorded_ratio_comps"]["confidence"] == "LOW"


def test_ratio_arv_over_the_plausibility_ceiling_is_withheld():
    # A $3.26M "assessed value" on a distressed residential lead is a judgment /
    # portfolio figure — the ratio must not launder it into a confident ARV.
    li = _li(state="NC", county="Cleveland", property_kind=PropertyKind.MULTI_FAMILY,
             raw={"recorded_ratio_comps": {"median_ratio": 1.03, "p25_ratio": 0.9,
                                           "p75_ratio": 1.2, "count": 221,
                                           "assessed_basis": 3256402.0,
                                           "confidence": "MEDIUM", "radius_mi": 1.0}})
    expected, _, _, _, notes = calc._arv_signals(li)
    assert expected is None
    assert any("plausibility ceiling" in n for n in notes)


# --- source-outage circuit breaker ------------------------------------------
class _FakeResp:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {}


class _FakeHttp:
    """Counts POSTs and always answers 503 (Anderson's live failure mode)."""

    def __init__(self):
        self.calls = 0

    async def post(self, url, data=None, timeout=None):
        self.calls += 1
        return _FakeResp(503)


class _VariablePageHttp:
    """Mimics the Buncombe parcel layer: honours a BYTE budget, so successive
    pages return different row counts (1673, 1685, 2 observed live)."""

    def __init__(self, sizes):
        self.sizes = list(sizes)
        self.offsets = []

    async def post(self, url, data=None, timeout=None):
        self.offsets.append(int(data["resultOffset"]))
        n = self.sizes.pop(0) if self.sizes else 0
        more = bool(self.sizes)

        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"features": [{"attributes": {"i": i}} for i in range(n)],
                        "exceededTransferLimit": more}
        return R


def test_paging_cursor_advances_by_rows_returned_not_by_page_size():
    import asyncio

    http = _VariablePageHttp([1673, 1685, 42])
    feats = asyncio.run(rs._paged(http, "https://x/services/P/MapServer/1/query", {},
                                  page_size=2000, page_cap=6))
    # A fixed page*page_size stride would have asked for 0, 2000, 4000 and both
    # skipped and duplicated rows.
    assert http.offsets == [0, 1673, 3358]
    assert len(feats) == 1673 + 1685 + 42


def test_five_hundred_raises_source_down_instead_of_looping():
    import asyncio

    http = _FakeHttp()
    try:
        asyncio.run(rs._paged(http, "https://x/services/Foo/MapServer/0/query", {},
                              page_size=1000, page_cap=10))
    except rs._SourceDown:
        pass
    else:                                            # pragma: no cover
        raise AssertionError("5xx must raise _SourceDown")
    assert http.calls == 1                           # no re-paging against a dead box


# --- calculator tier --------------------------------------------------------
def test_ratio_tier_prices_improved_lead_and_is_capped_medium():
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.SINGLE_FAMILY,
             tax_value=100000.0,
             raw={"recorded_ratio_comps": {"median_ratio": 1.45, "p25_ratio": 1.30,
                                           "p75_ratio": 1.62, "count": 40,
                                           "assessed_basis": 200000.0,
                                           "confidence": "MEDIUM", "radius_mi": 1.0}})
    expected, low, high, conf, notes = calc._arv_signals(li)
    assert expected == 290000                # 1.45 x the COUNTY basis, not li.tax_value
    assert (low, high) == (260000, 324000)
    assert conf == "MEDIUM"                  # ratio proxy is never HIGH
    # and it survives to the calculator (Buncombe's ×0.89 county calibration applies)
    c = calc.compute(li)
    assert any("sale-to-assessed" in n for n in c.notes)
    assert c.arv_confidence == "MEDIUM"


def test_sqft_recorded_comps_still_outrank_the_ratio_tier():
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1500,
             raw={"comp_median_ppsf_recorded": 180.0,
                  "recorded_comps": {"median_ppsf": 180.0, "count": 12, "p25_ppsf": 150.0,
                                     "p75_ppsf": 210.0, "radius_mi": 1.0,
                                     "confidence": "HIGH"},
                  "recorded_ratio_comps": {"median_ratio": 9.0, "count": 40,
                                           "assessed_basis": 200000.0,
                                           "confidence": "MEDIUM"}})
    c = calc.compute(li)
    assert c.arv_expected == 270000 and c.arv_confidence == "HIGH"


def test_thin_ratio_basket_is_low_confidence():
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.SINGLE_FAMILY,
             raw={"recorded_ratio_comps": {"median_ratio": 1.40, "p25_ratio": 1.0,
                                           "p75_ratio": 2.4, "count": 4,
                                           "assessed_basis": 100000.0,
                                           "confidence": "LOW", "radius_mi": 1.0}})
    c = calc.compute(li)
    assert c.arv_confidence == "LOW"


def test_land_ratio_tier_beats_flat_tax_times_1_10():
    li = _li(state="NC", county="Buncombe", property_kind=PropertyKind.LAND,
             acreage=1.0, tax_value=100000.0,
             raw={"recorded_ratio_comps": {"median_ratio": 1.60, "p25_ratio": 1.4,
                                           "p75_ratio": 1.8, "count": 12,
                                           "assessed_basis": 100000.0,
                                           "confidence": "MEDIUM", "radius_mi": 1.0}})
    expected, _, _, conf, notes = calc._arv_signals(li)
    assert expected == 160000                # not tax_value x 1.10 == 110,000
    assert conf == "MEDIUM"
    assert any("sale-to-assessed" in n for n in notes)
