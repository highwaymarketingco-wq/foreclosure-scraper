"""SCDOR Top Delinquent Taxpayers -> SC state-tax-lien leads."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc import sc_state_tax_lien as m
from foreclosure_scraper.scrapers.counties_sc.sc_state_tax_lien import _to_listing

SLUG = "counties_sc.sc_state_tax_lien"
ROW = ["COPELAND, QUINTESSA", "100 MAIN ST", "WELLFORD", "SC", "29385",
       "SPARTANBURG", "$2,201,776.42"]


def test_parses_sc_row():
    li = _to_listing(ROW, "individual", SLUG)
    assert li is not None
    assert li.state == "SC"
    assert li.county == "Spartanburg"
    assert li.city == "Wellford"
    assert li.zip_code == "29385"
    assert li.street_address == "100 MAIN ST"
    assert li.defendant == "COPELAND, QUINTESSA"
    assert li.listing_type is ListingType.TAX_LIEN
    assert li.judgment_amount == 2201776.42
    assert "tax lien" in (li.description or "").lower()
    assert li.raw["sc_state_tax_lien"]["balance"] == 2201776.42


def test_drops_out_of_state():
    ky = ["MICHEL, CLARENCE J", "120 SUNSET LODGE RD", "LANCASTER", "KY",
          "40444", "GARRARD", "$3,299,369.17"]
    assert _to_listing(ky, "individual", SLUG) is None


def test_handles_missing_amount():
    row = ["DOE, JANE", "5 OAK AVE", "EASLEY", "SC", "29640", "PICKENS", ""]
    li = _to_listing(row, "individual", SLUG)
    assert li is not None and li.judgment_amount is None


def test_short_row_is_safe():
    assert _to_listing(["NAME", "SC"], "individual", SLUG) is None  # too few cols -> no SC at idx 3


def test_parses_business_row():
    """AUDITED 2026-10-01: the Business tab was never read before; it shares
    the individuals grid's 7-column shape."""
    row = ["PRESTIGE APPLIANCES LLC", "401 PARK AVE SE", "AIKEN", "SC",
           "29801", "AIKEN", "$2,490,802.57"]
    li = _to_listing(row, "business", SLUG)
    assert li is not None
    assert li.defendant == "PRESTIGE APPLIANCES LLC"
    assert li.county == "Aiken"
    assert "business" in (li.description or "").lower()


def test_fetch_combines_individual_and_business_pages(monkeypatch):
    """AUDITED 2026-10-01: fetch() must read BOTH tabs (_render_rows now
    returns all pages of each, pre-combined by the in-page JS driver) and
    keep both kinds, not just individuals."""
    async def fake_render_rows():
        return {
            "individual": [
                ["COPELAND, QUINTESSA", "100 MAIN ST", "WELLFORD", "SC",
                 "29385", "SPARTANBURG", "$2,201,776.42"],
                ["MICHEL, CLARENCE J", "120 SUNSET LODGE RD", "LANCASTER",
                 "KY", "40444", "GARRARD", "$3,299,369.17"],  # out-of-state
            ],
            "business": [
                ["PRESTIGE APPLIANCES LLC", "401 PARK AVE SE", "AIKEN", "SC",
                 "29801", "AIKEN", "$2,490,802.57"],
            ],
        }

    monkeypatch.setattr(m, "_render_rows", fake_render_rows)
    rows = asyncio.run(m.SCStateTaxLien().fetch())
    kinds = {li.raw["sc_state_tax_lien"]["kind"] for li in rows}
    assert kinds == {"individual", "business"}
    assert len(rows) == 2  # the KY row dropped, SC individual + SC business kept


def test_fetch_dedupes_a_row_the_pager_might_repeat(monkeypatch):
    """A slow page-swap could in principle re-read a row before the content
    actually changes; fetch() must not double-count it."""
    row = ["COPELAND, QUINTESSA", "100 MAIN ST", "WELLFORD", "SC", "29385",
           "SPARTANBURG", "$2,201,776.42"]

    async def fake_render_rows():
        return {"individual": [row, list(row)], "business": []}

    monkeypatch.setattr(m, "_render_rows", fake_render_rows)
    rows = asyncio.run(m.SCStateTaxLien().fetch())
    assert len(rows) == 1
