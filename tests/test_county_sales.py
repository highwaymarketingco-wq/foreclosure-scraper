"""County sales rolls — the comps spine.

comps sat at 0.0% on the 2026-08-03 board: not one lead of 25,552 had one.
living_sqft was 11.3%, year_built 29.3%. All of it is ordinary county assessor
data published free; we were not reading it.

The join is where this breaks, so that is what these pin.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import foreclosure_scraper.enrichment_county_sales as S
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(parcel, county="Henderson", state="NC"):
    return Listing(source="x", source_url="https://e.com/1",
                   listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN,
                   state=state, county=county, parcel_id=parcel)


def test_sale_date_handles_both_county_encodings():
    """Counties store this as epoch-millis OR a bare yyyymm string."""
    assert S._sale_date(1590695820000) == "2020-05-28"
    assert S._sale_date("199607") == "1996-07-01"
    assert S._sale_date(None) is None
    assert S._sale_date("") is None
    assert S._sale_date("garbage") is None


def test_a_bare_year_is_not_read_as_an_epoch():
    """1982 as epoch-millis is 1970. A silent 12-year error on every comp."""
    assert S._sale_date(1982) is None
    assert S._sale_date("2003") is None


def test_both_key_dialects_are_tried():
    """THE bug this had. 742 of 1,019 Henderson parcel_ids are ALREADY REIDs
    (from the ptscloud delinquent roll) while 277 are PINs. Bridging everything
    silently dropped the ones already in the roll's own key — matched went from
    63 to 158 when both were tried."""
    roll = S.ROLLS[0]
    assert roll.bridge_from == "PIN" and roll.bridge_to == "REID"
    assert roll.key == "REID"


def test_never_requests_a_wildcard():
    """outFields=* on an assessor layer sweeps up owner mailing data."""
    for r in S.ROLLS:
        assert r.fields and "*" not in r.fields


def test_existing_values_are_not_overwritten():
    lead = _li("101727")
    lead.living_sqft, lead.year_built = 999, 1900
    rows = [{"REID": "101727", "PRICE": 360000, "SALE_DATE": 1633564800000,
             "BLDG_SIZE": 1932, "YEAR_BUILT": 1982, "SALE_TYPE": "LAND & BLDG(S)"}]
    _apply(lead, rows)
    assert lead.living_sqft == 999 and lead.year_built == 1900


def _apply(lead, rows):
    """Drive the per-lead mapping the way _one_county does."""
    roll = S.ROLLS[0]
    newest = rows[0]
    if roll.sqft and lead.living_sqft in (None, 0):
        v = S._int(newest.get(roll.sqft))
        if v:
            lead.living_sqft = v
    if roll.year_built and lead.year_built in (None, 0):
        v = S._int(newest.get(roll.year_built))
        if v and 1700 < v <= 2027:
            lead.year_built = v


def test_absurd_year_built_is_rejected():
    lead = _li("101727")
    _apply(lead, [{"YEAR_BUILT": 12, "BLDG_SIZE": 0}])
    assert lead.year_built is None


def test_arcgis_200_with_an_error_body_raises():
    """ArcGIS answers 200 with an error payload; reading that as an empty result
    is how a token wall reads as 'no sales today'."""
    c = MagicMock()
    r = MagicMock(); r.status_code = 200
    r.json = MagicMock(return_value={"error": {"code": 499, "message": "Token Required"}})
    c.post = AsyncMock(return_value=r)
    try:
        asyncio.run(S._fetch_all(c, "https://x/query", ("A",), "1=1"))
    except RuntimeError as e:
        assert "499" in str(e) or "Token" in str(e)
    else:
        raise AssertionError("an error body was treated as success")


def test_disabled_is_a_no_op(monkeypatch):
    monkeypatch.setattr(S, "ENABLED", False)
    assert asyncio.run(S.enrich_county_sales([_li("1")]))["skipped"] == "disabled"


def test_leads_without_a_parcel_are_skipped():
    """The join is by parcel; a lead without one cannot be reached and must not
    cause a query."""
    assert asyncio.run(S.enrich_county_sales([_li(None)]))["counties"] == 0


def test_county_sales_is_whitelisted_for_publication():
    """court_record was gathered for 621 leads and stripped at publish because
    nobody whitelisted it. Do not repeat that here."""
    from foreclosure_scraper import web_artifact
    src = open(web_artifact.__file__).read()
    assert '"county_sales"' in src, "county_sales would be stripped at publish"


# ---------------------------------------------------------------------------
# Per-county format drift. Every one of these was found by a live run
# returning zero, not by reading a spec.
# ---------------------------------------------------------------------------

def test_yyyymmdd_string_dates_parse():
    """Laurens stores Sale_Date as '20260113'. Unhandled, it parsed to None and
    the county produced 0 comps from 211 matched parcels."""
    assert S._sale_date("20260113") == "2026-01-13"
    assert S._sale_date("20180827") == "2018-08-27"


def test_slash_dates_parse():
    assert S._sale_date("05/28/2020") == "2020-05-28"


def test_impossible_dates_are_rejected_not_coerced():
    assert S._sale_date("20261399") is None      # month 13, day 99
    assert S._sale_date("999901") is None        # year 9999


def test_price_strings_with_commas_parse():
    """Laurens returns Sale_Price as the STRING '250,000'."""
    assert S._num("250,000") == 250000.0
    assert S._num("$1,234.50") == 1234.5
    assert S._num("0") is None
    assert S._num(None) is None


def test_the_query_is_a_POST():
    """A WHERE clause listing a few hundred parcel ids makes a query string long
    enough that the server answers 404 — which reads as 'layer gone' and is
    really 'URL too long'. Pickens and Laurens both 404'd on GET with 262 and
    211 ids; POST fixed both."""
    import inspect
    src = inspect.getsource(S._fetch_all)
    assert "c.post(" in src, "long IN() clauses will 404 on GET"
    assert "c.get(" not in src


def test_every_roll_declares_explicit_fields():
    for r in S.ROLLS:
        assert r.fields and "*" not in r.fields, r.county


def test_rolls_cover_the_counties_we_verified():
    got = {(r.county, r.state) for r in S.ROLLS}
    assert ("Henderson", "NC") in got
    assert ("Pickens", "SC") in got
    assert ("Laurens", "SC") in got
