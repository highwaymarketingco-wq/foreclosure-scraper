"""Tax-owed normalizer: per-source amounts -> raw['tax_owed'] + parcel cross-ref."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed


def _li(source, parcel=None, county="Buncombe", state="NC", raw=None, **kw):
    now = datetime.utcnow()
    return Listing(
        source=source, source_url="https://x/1",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        county=county, state=state, parcel_id=parcel,
        first_seen=now, last_seen=now, raw=raw or {}, **kw)


def test_buncombe_principal_tax_due_normalized():
    li = _li("counties_nc.buncombe_delinquent_tax", parcel="9678-12-3456",
             raw={"buncombe_delinquent_tax": {"principal_tax_due": "$775.59"}})
    stats = enrich_tax_owed([li])
    assert stats["stamped"] == 1
    assert li.raw["tax_owed"]["balance"] == 775.59
    assert li.raw["tax_owed"]["kind"] == "delinquent_tax"
    assert li.raw["tax_owed"]["basis"] == "own_record"


def test_sc_state_lien_balance_normalized():
    li = _li("counties_sc.sc_state_tax_lien", county="Spartanburg", state="SC",
             raw={"sc_state_tax_lien": {"balance": 12500.0}})
    enrich_tax_owed([li])
    assert li.raw["tax_owed"]["balance"] == 12500.0
    assert li.raw["tax_owed"]["kind"] == "state_tax_lien"


def test_cross_reference_onto_matching_parcel():
    # A delinquent-tax lead carries the balance; a court lead resolved to the SAME
    # parcel (different source, no own amount) should inherit it.
    tax = _li("counties_nc.buncombe_delinquent_tax", parcel="9678-12-3456",
              raw={"buncombe_delinquent_tax": {"principal_tax_due": 920.0}})
    court = _li("national.courtlistener_bankruptcy", parcel="9678123456",
                raw={"resolved_from_name": {"confidence": "unique_match"}})
    stats = enrich_tax_owed([tax, court])
    assert stats["cross_referenced"] == 1
    assert court.raw["tax_owed"]["balance"] == 920.0
    assert court.raw["tax_owed"]["basis"] == "parcel_cross_ref"


def test_no_cross_ref_across_counties():
    a = _li("counties_nc.buncombe_delinquent_tax", parcel="123", county="Buncombe",
            raw={"buncombe_delinquent_tax": {"principal_tax_due": 500.0}})
    b = _li("national.courtlistener_bankruptcy", parcel="123", county="Burke",
            raw={})
    enrich_tax_owed([a, b])
    assert "tax_owed" not in b.raw  # same parcel string, different county -> no match


def test_zero_amount_not_stamped():
    li = _li("counties_nc.buncombe_delinquent_tax", parcel="1",
             raw={"buncombe_delinquent_tax": {"principal_tax_due": "$-"}})
    stats = enrich_tax_owed([li])
    assert stats["stamped"] == 0
    assert "tax_owed" not in li.raw
