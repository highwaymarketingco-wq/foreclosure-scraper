"""SCDOR Top Delinquent Taxpayers -> SC state-tax-lien leads (parser only)."""
from __future__ import annotations

from foreclosure_scraper.models import ListingType
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
