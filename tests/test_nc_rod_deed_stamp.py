"""Pin NC deed-tax-stamp -> sold-price conversion.

NC charges $1 per $500 of consideration on deed transfer. So a deed
recording with EXCISE TAX $50.00 implies a $25,000 sale price. This
is the path Trustee's Deed Upon Sale recordings (post-foreclosure
auction) use to encode the hammer price publicly.

These tests pin the conversion + the explicit-consideration shortcut
so the foreclosure_sold_comps pool gets accurate hammer prices once
the per-vendor Permitium search-form flow is wired.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.nc_rod_substitute_trustee import (
    _sold_price_from_stamp,
)


def test_explicit_consideration_preferred():
    text = "Trustee's Deed Upon Sale CONSIDERATION: $48,500.00 EXCISE TAX: $97.00"
    # $48,500 explicit beats $97 * 500 = $48,500. They match here, but
    # the explicit path runs first so we get exact value with cents.
    assert _sold_price_from_stamp(text) == 48500.0


def test_excise_tax_converts_at_500x():
    """No explicit CONSIDERATION line — fall back to stamp × 500."""
    text = "Trustee's Deed Upon Sale Excise Tax: $50.00"
    assert _sold_price_from_stamp(text) == 25000.0


def test_stamp_alternate_label():
    """Some counties use 'Stamped Tax' / 'Consideration Stamp' wording."""
    text = "STAMPED TAX $90.00"
    assert _sold_price_from_stamp(text) == 45000.0


def test_no_stamp_returns_none():
    """Recording with no consideration field at all."""
    assert _sold_price_from_stamp("Substitute Trustee Deed - no price field") is None


def test_implausibly_low_rejected():
    """A $5 stamp would imply a $2,500 'sale' — almost certainly a
    transfer between related parties, not a real foreclosure auction."""
    text = "Excise Tax: $0.10"
    assert _sold_price_from_stamp(text) is None


def test_implausibly_high_rejected():
    """$5,000 stamp = $2.5M sale; possible but probably parser misfire
    on a Buncombe foreclosure (median Buncombe foreclosure is well
    under that). Cap at $10M to allow real luxury cases through."""
    text = "Excise Tax: $50,000.00"  # $25M
    assert _sold_price_from_stamp(text) is None


def test_consideration_with_cents():
    text = "CONSIDERATION: $123,456.78"
    assert _sold_price_from_stamp(text) == 123456.78
