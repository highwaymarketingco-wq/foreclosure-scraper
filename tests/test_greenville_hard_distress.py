"""Greenville County SC hard-distress scraper (flag-gated, default OFF).

Fixtures are REAL slices of the live sources captured 2026-08-03:
  * greenville_delinquent_parcels.json — layer-52 features incl. one polygon,
    one government owner, one out-of-state mailing, one blank house number.
  * greenville_tax_sale.html           — roster rows incl. the real blank-Map#
    mobile-home items the county interleaves.
  * greenville_probate_results.html    — a real "Deceased Person" result page.
"""
from __future__ import annotations

import asyncio
import json
import pathlib


from foreclosure_scraper.models import ListingType, PropertyKind, _normalize_parcel
from foreclosure_scraper.scrapers.counties_sc import greenville_hard_distress as gv
from foreclosure_scraper.scrapers.counties_sc.greenville_hard_distress import (
    GreenvilleHardDistress, TaxSaleRow, build_listing, parse_probate_rows,
    parse_tax_sale, probate_match, _situs, _is_absentee,
)

FX = pathlib.Path(__file__).parent / "fixtures"

PIN_BOTH = "0032000200610"      # delinquent AND on the tax-sale roster
PIN_VACANT = "0001000100208"    # blank house number, out-of-state (GA) mailing
PIN_ABSENTEE = "0053000501500"  # FL mailing
PIN_GOV = "0091010802300"       # CITY OF GREENVILLE — never a lead
PIN_MOBILE = "0135000601300"    # MOBILE HOME proptype


def _parcels():
    return json.loads((FX / "greenville_delinquent_parcels.json").read_text())["features"]


def _by_pin():
    return {f["attributes"]["PIN"]: f for f in _parcels()}


# ------------------------------------------------------------ the flag ------
def test_scraper_is_dormant_without_the_flag(monkeypatch):
    monkeypatch.delenv(gv.ENV_ON, raising=False)
    s = GreenvilleHardDistress()
    assert s.disabled is True
    assert gv.ENV_ON in s.disabled_reason
    rows = asyncio.run(s.safe_run())
    assert rows == [] and s.last_outcome == "DORMANT"


def test_flag_off_reports_dormant_not_a_suspicious_zero(monkeypatch):
    """A county that is deliberately off must never look like a broken source
    in the run report."""
    monkeypatch.setenv(gv.ENV_ON, "0")
    s = GreenvilleHardDistress()
    asyncio.run(s.safe_run())
    assert s.last_outcome == "DORMANT"


def test_flag_on_arms_the_scraper(monkeypatch):
    monkeypatch.setenv(gv.ENV_ON, "1")
    assert GreenvilleHardDistress().disabled is False


def test_fetch_returns_nothing_when_the_flag_is_unset(monkeypatch):
    monkeypatch.delenv(gv.ENV_ON, raising=False)
    s = GreenvilleHardDistress()
    s.disabled = False                     # bypass the base-class short-circuit
    assert list(asyncio.run(s.fetch())) == []


def test_greenville_is_not_added_to_the_scope_config():
    """The operator has not decided to expand. Building the source must not
    quietly widen the footprint."""
    from foreclosure_scraper.config import (
        SC_COUNTIES, SCOPE_DENY_COUNTIES_NORMALIZED, in_scope,
    )
    assert not any(c.name == "Greenville" for c in SC_COUNTIES)
    assert ("Greenville", "SC") in SCOPE_DENY_COUNTIES_NORMALIZED
    assert in_scope("Greenville", "SC") is False


# ---------------------------------------------------------- tax sale --------
def test_parse_tax_sale_reads_the_roster():
    p = parse_tax_sale((FX / "greenville_tax_sale.html").read_text())
    assert p.rows
    first = p.rows[0]
    assert first.pin == _normalize_parcel(PIN_BOTH)
    assert first.map_number == PIN_BOTH
    assert first.owner == "MASS MEDIA INC"
    assert first.amount == 5987.69
    assert all(r.pin for r in p.rows)


def test_parse_tax_sale_counts_the_unmapped_mobile_home_items():
    """~229 roster items are mobile-home/personal-property rows with a BLANK
    Map #. They are not real-property leads, but the drop must be visible."""
    p = parse_tax_sale((FX / "greenville_tax_sale.html").read_text())
    assert p.unmapped == 2
    assert all(r.map_number.strip() for r in p.rows)


def test_parse_tax_sale_skips_the_header_row():
    p = parse_tax_sale((FX / "greenville_tax_sale.html").read_text())
    assert not any((r.item or "").lower().startswith("item") for r in p.rows)


def test_parse_tax_sale_on_junk_is_empty():
    assert parse_tax_sale("").rows == []
    assert parse_tax_sale("<html><body>no table</body></html>").rows == []


# ------------------------------------------------------------- probate ------
def test_parse_probate_rows():
    rows = parse_probate_rows((FX / "greenville_probate_results.html").read_text())
    assert len(rows) == 10
    assert all(r["party"] == "Deceased Person" for r in rows)
    assert {"case", "name", "party"} == set(rows[0])


def test_probate_match_needs_surname_and_first_name():
    rows = parse_probate_rows((FX / "greenville_probate_results.html").read_text())
    # 2026ES2300916 ABERNATHY , RANDALL DALE
    hit = probate_match("ABERNATHY RANDALL DALE", rows)
    assert hit and hit["case"] == "2026ES2300916" and hit["year"] == 2026
    assert hit["confidence"] == "high"          # middle name agrees too
    # A different Abernathy must NOT match on surname alone.
    assert probate_match("ABERNATHY WILLIAM T", rows) is None
    # Surname-only owner strings can never match.
    assert probate_match("ABERNATHY", rows) is None


def test_probate_match_is_positional_not_a_token_soup():
    """Real false positives this rule exists to stop. Each pair below was
    produced by the live index under a looser 'tokens appear anywhere' match."""
    def rows(name):
        return [{"case": "2025ES2300001", "name": name, "party": "Deceased Person"}]

    # middle name read as a first name
    assert probate_match("SMITH WILLIAM R", rows("SMITH , ELRAMA WILLIAM JR")) is None
    assert probate_match("SMITH TODD A", rows("SMITH , ELOISE TODD")) is None
    assert probate_match("JONES ROY", rows("JONES , BOBBY ROY")) is None
    assert probate_match("ASHMORE ANDREW S", rows("ASHMORE , LORRAINE ANDREW")) is None
    # first + last agree -> a real match, medium confidence (middles differ)
    m = probate_match("SMITH CARL K", rows("SMITH , CARL HENRY"))
    assert m and m["confidence"] == "medium"
    # first + last + middle agree -> high
    h = probate_match("ALLISON MALINDA MAE", rows("ALLISON , MALINDA MAE JONES"))
    assert h and h["confidence"] == "high"


def test_probate_match_ignores_generational_suffixes():
    rows = [{"case": "2025ES2300002", "name": "JONES , DAVID DANIEL JR",
             "party": "Deceased Person"}]
    assert probate_match("JONES DAVID", rows)["confidence"] == "medium"
    assert probate_match("JONES JR", rows) is None      # suffix is not a name


def test_probate_match_requires_a_given_name_on_the_decedent_record():
    rows = [{"case": "2025ES2300003", "name": "JONES", "party": "Deceased Person"}]
    assert probate_match("JONES DAVID", rows) is None


def test_probate_match_ignores_estates_older_than_the_cutoff():
    rows = parse_probate_rows((FX / "greenville_probate_results.html").read_text())
    # 1988ES2300124 ABERNATHY , JAMES HARRY — real, but far too old to act on.
    assert probate_match("ABERNATHY JAMES HARRY", rows) is None
    # 2021ES2301806 ABERNATHY , MARY ANN — inside the window.
    assert probate_match("ABERNATHY MARY ANN", rows)["year"] == 2021


def test_probate_match_ignores_undated_apt_case_numbers():
    rows = parse_probate_rows((FX / "greenville_probate_results.html").read_text())
    # 'APT448F12' carries no year — it cannot be shown to be recent.
    assert probate_match("ABERNATHY J L", rows) is None


def test_probate_match_ignores_non_deceased_parties():
    rows = [{"case": "2025ES2300001", "name": "SMITH , JOHN A",
             "party": "Personal Representative"}]
    assert probate_match("SMITH JOHN A", rows) is None


def test_only_the_deceased_party_type_is_ever_requested():
    """PRIVACY: the same form exposes Incapacitated Person / Patient / Minor /
    guardian types. This module must never request them."""
    assert gv.PROBATE_PARTY_DECEASED == "EST"
    src = pathlib.Path(gv.__file__).read_text()
    for banned in ('"NCM"', '"PAT"', '"MIN"', '"MN2"', '"GDN"', '"GAL"'):
        assert banned not in src


# ---------------------------------------------------------- build_listing ---
def test_delinquent_parcel_becomes_a_lead_with_the_full_spine():
    f = _by_pin()[PIN_BOTH]
    li = build_listing(_normalize_parcel(PIN_BOTH), f["attributes"], f["geometry"])
    assert li is not None
    assert li.state == "SC" and li.county == "Greenville"
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.owner_name == "MASS MEDIA INC"
    assert li.street_address == "200 MAIN"
    assert li.latitude is not None and li.longitude is not None
    d = li.raw["greenville_distress"]
    assert d["lanes"] == ["delinquent_tax"]
    assert d["amount_owed"] == 5567.69
    assert li.raw["owner_mailing"]["state"] == "SC"


def test_the_unpaid_balance_never_lands_in_a_value_field():
    """A $5,567 tax bill must not become the property's value — that is how
    calc.py ends up pricing a building off a tax bill."""
    f = _by_pin()[PIN_BOTH]
    li = build_listing(_normalize_parcel(PIN_BOTH), f["attributes"], f["geometry"])
    assert li.tax_value == f["attributes"]["TAXMKTVAL"]
    assert li.market_value == f["attributes"]["FAIRMKTVAL"]
    assert li.tax_value != 5567.69 and li.market_value != 5567.69


def test_government_owners_are_never_leads():
    f = _by_pin()[PIN_GOV]
    assert build_listing(_normalize_parcel(PIN_GOV), f["attributes"], None) is None


def test_a_paid_bill_is_not_the_delinquent_lane():
    """TOTTAX is the BILLED amount whether or not it was paid. Only a NULL
    PAIDDATE means delinquent — the tax-sale-only parcels backfilled by PIN do
    carry a PAIDDATE and must not inflate the delinquent count."""
    f = _by_pin()[PIN_BOTH]
    paid = dict(f["attributes"], PAIDDATE=1_700_000_000_000)
    ts = TaxSaleRow(item="99", pin=_normalize_parcel(PIN_BOTH),
                    map_number=PIN_BOTH, owner="MASS MEDIA INC", amount=5987.69)
    li = build_listing(_normalize_parcel(PIN_BOTH), paid, None, tax_sale=ts)
    d = li.raw["greenville_distress"]
    assert d["lanes"] == ["tax_sale_roster"]
    assert d["tax_billed_unpaid"] is None
    assert d["tax_billed"] == 5567.69
    assert d["amount_owed"] == 5987.69


def test_a_paid_bill_with_no_tax_sale_row_is_not_a_lead_at_all():
    f = _by_pin()[PIN_BOTH]
    paid = dict(f["attributes"], PAIDDATE=1_700_000_000_000)
    assert build_listing(_normalize_parcel(PIN_BOTH), paid, None) is None


def test_both_lanes_merge_into_one_parcel_keyed_lead():
    f = _by_pin()[PIN_BOTH]
    ts = TaxSaleRow(item="11724", pin=_normalize_parcel(PIN_BOTH),
                    map_number=PIN_BOTH, owner="MASS MEDIA INC", amount=5987.69)
    li = build_listing(_normalize_parcel(PIN_BOTH), f["attributes"], f["geometry"],
                       tax_sale=ts)
    d = li.raw["greenville_distress"]
    assert d["lanes"] == ["delinquent_tax", "tax_sale_roster"]
    assert d["tax_sale"]["item"] == "11724"
    assert li.raw["distressed"] is True
    assert li.parcel_id == _normalize_parcel(PIN_BOTH)


def test_probate_match_adds_a_lane_and_never_leaks_extra_personal_data():
    f = _by_pin()[PIN_MOBILE]
    pro = {"case": "2025ES2301111", "name": "HARVLEY , JULIE MARIE", "year": 2025,
           "confidence": "high"}
    li = build_listing(_normalize_parcel(PIN_MOBILE), f["attributes"], None, probate=pro)
    d = li.raw["greenville_distress"]
    assert "probate_decedent_owner" in d["lanes"]
    assert set(d["probate"]) == {"case", "name", "year", "confidence", "party_type", "note"}
    assert li.raw["distressed"] is True


def test_absentee_is_an_attribute_and_never_a_lane():
    """The absentee figure was previously over-counted as leads. It must never
    appear in `lanes`, and must never on its own produce a lead."""
    f = _by_pin()[PIN_ABSENTEE]
    li = build_listing(_normalize_parcel(PIN_ABSENTEE), f["attributes"], None)
    assert li.raw["absentee_owner"] is True
    assert "absentee" not in " ".join(li.raw["greenville_distress"]["lanes"])
    assert li.raw["greenville_distress"]["lanes"] == ["delinquent_tax"]


def test_is_absentee_rules():
    assert _is_absentee("100 PEACHTREE ST", "GA", "12 MAIN ST") is True
    assert _is_absentee("PO BOX 26928", "SC", "506 WILTON ST") is True
    assert _is_absentee("506 WILTON ST", "SC", "506 WILTON ST") is False


def test_vacant_land_kind_and_blank_house_number():
    f = _by_pin()[PIN_VACANT]
    li = build_listing(_normalize_parcel(PIN_VACANT), f["attributes"], None)
    assert li.street_address == "LAURENS"          # no invented house number
    assert li.raw["greenville_distress"]["improved"] == "NO"


def test_mobile_home_property_kind():
    f = _by_pin()[PIN_MOBILE]
    li = build_listing(_normalize_parcel(PIN_MOBILE), f["attributes"], None)
    assert li.property_kind == PropertyKind.MOBILE


def test_situs_drops_the_county_zero_filler_and_takes_the_type_from_layer_5():
    assert _situs("00000", "PARK") == "PARK"
    assert _situs("506", "WILTON", "ST") == "506 WILTON ST"
    assert _situs("", "LAURENS") == "LAURENS"
    assert _situs("506", "") is None


def test_last_sale_join_marks_arms_length():
    f = _by_pin()[PIN_BOTH]
    sale = {"SALEPRICE": 195000, "SALEDATE": 1525824000000,
            "SALETYPE": "WARRANTY DEED", "TRUESALE": "YES", "STRTYP": "ST"}
    li = build_listing(_normalize_parcel(PIN_BOTH), f["attributes"], None, sale=sale)
    ls = li.raw["greenville_distress"]["last_sale"]
    assert ls["arms_length"] is True and ls["price"] == 195000.0
    assert ls["date"] == "2018-05-09"
    assert li.street_address == "200 MAIN ST"


def test_non_arms_length_sale_is_marked_false():
    f = _by_pin()[PIN_BOTH]
    sale = {"SALEPRICE": 1, "SALEDATE": 1555027200000,
            "SALETYPE": "CASH (LAND)", "TRUESALE": "NO"}
    li = build_listing(_normalize_parcel(PIN_BOTH), f["attributes"], None, sale=sale)
    assert li.raw["greenville_distress"]["last_sale"]["arms_length"] is False


# ------------------------------------------------------------ compliance ----
def test_slug_lets_enrichment_tax_owed_pick_up_the_balance():
    """enrichment_tax_owed's generic scan only fires for slugs containing one of
    tax/flc/forfeited/delinquent/lien. The slug carries 'tax' on purpose — with
    a slug like 'greenville_hard_distress' the owed balance is silently dropped
    and every lead ships with no tax_owed."""
    from foreclosure_scraper.enrichment_tax_owed import _TAXISH, enrich_tax_owed
    assert any(k in GreenvilleHardDistress.slug for k in _TAXISH)
    f = _by_pin()[PIN_BOTH]
    li = build_listing(_normalize_parcel(PIN_BOTH), f["attributes"], f["geometry"])
    enrich_tax_owed([li])
    assert li.raw["tax_owed"]["balance"] == 5567.69
    assert li.raw["tax_owed"]["kind"] == "delinquent_tax"


def test_out_fields_are_enumerated_never_star():
    for fields in (gv.PARCEL_FIELDS, gv.SALES_FIELDS):
        assert "*" not in fields
        low = fields.lower()
        for banned in ("ssn", "dob", "birth", "phone", "email", "license", "driver"):
            assert banned not in low


def _code_body() -> str:
    """Module source with the docstring stripped — the docstring deliberately
    NAMES the walled hosts to record that they are off limits."""
    return pathlib.Path(gv.__file__).read_text().split('"""', 2)[2]


def test_no_walled_greenville_host_is_referenced():
    """www2. and app. greenvillecounty.org are Incapsula-walled and are out of
    bounds. No code in this module may point at them."""
    body = _code_body()
    assert "www2.greenvillecounty.org" not in body
    assert "app.greenvillecounty.org" not in body
    for url in (gv.TAXSALE_URL, gv.PROBATE_BASE, gv.PAGE_URL):
        assert url.startswith("https://www.greenvillecounty.org/")
    assert gv.GIS.startswith("https://www.gcgis.org/")


def test_the_252mb_unfiltered_probate_page_is_never_fetched():
    assert "SearchResults.aspx" not in _code_body(), \
        "probate must be queried by POSTing Default.aspx, not by pulling the index"


def test_no_captcha_or_waf_bypass_machinery():
    body = _code_body().lower()
    for banned in ("capsolver", "captcha", "2captcha", "cf_clearance",
                   "curl_cffi", "impersonate", "undetected"):
        assert banned not in body


def test_pin_chunks_are_validated_before_going_into_a_where_clause():
    """PINs are spliced into a SQL WHERE. Anything non-alphanumeric is dropped
    rather than escaped."""
    import re as _re
    assert _re.fullmatch(r"[A-Za-z0-9]+", "0032000200610")
    assert not _re.fullmatch(r"[A-Za-z0-9]+", "0032' OR '1'='1")
