"""qPublic/Schneider card parser, pinned to a REAL captured Oconee SC card.

Fixture oconee_card.html is the live-rendered card for parcel 520-77-01-021
(412 Pepper Ct, Seneca), captured 2026-06-24. Guards the BeautifulSoup parsing
(two-column building facts + the header-mapped sales grid) against silent breakage
when Schneider tweaks the markup — the network render path can't be exercised in CI.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.assessor_cards.qpublic_render import _parse_card

_FIXTURE = Path(__file__).parent / "fixtures" / "assessor_cards" / "oconee_card.html"


def test_parse_oconee_card_fills_heated_sqft_and_arms_length_price():
    r = _parse_card(_FIXTURE.read_text(), "Oconee")
    assert r is not None
    # heated sqft (the bulk-missing field), flagged as real heated area
    assert r.living_sqft == 3076.0 and r.living_sqft_is_heated is True
    # most-recent ARMS-LENGTH sale; the $5 "9: Other Not Valid" row is skipped
    assert r.best_sale_price() == 632275.0
    assert r.market_value == 286992.0
    assert len(r.sales) >= 2


def test_parse_spartanburg_card_prefers_finished_over_gross_sqft():
    """Spartanburg's card lists BOTH 'Gross Sq Ft' (2,705) and 'Finished Sq Ft'
    (2,371); the parser must return the FINISHED/heated value, not gross. (Regression
    for the abbreviated-label bug found by live-reading 1101 Partridge Rd.)"""
    html = (Path(__file__).parent / "fixtures" / "assessor_cards" / "spartanburg_card.html").read_text()
    r = _parse_card(html, "Spartanburg")
    assert r is not None
    assert r.living_sqft == 2371.0 and r.living_sqft_is_heated is True   # finished, not gross 2705
    assert r.market_value == 384600.0
    # all 6 recent transfers are $1 nominal trust/family deeds -> no arms-length price
    assert r.best_sale_price() is None
    assert len(r.sales) == 7


def test_parse_card_on_garbage_returns_none():
    assert _parse_card("<html><body>not a card</body></html>", "Oconee") is None
