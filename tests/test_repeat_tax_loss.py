"""Tests for enrichment_repeat_tax_loss -- Dirty Deeds Tier A #34.

"Match tax-deed grantors back to the current owner index. A proven
non-payer with proven capitulation."
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_repeat_tax_loss import enrich_repeat_tax_loss
from foreclosure_scraper.models import Listing, ListingType


def _mk(owner_name, county="Buncombe", state="NC", parcel_id=None,
        deed_chain=None, source="s", source_url=None):
    return Listing(
        source=source, source_url=source_url or f"https://example.com/{owner_name}-{parcel_id}",
        listing_type=ListingType.TAX_LIEN, state=state, county=county,
        owner_name=owner_name, parcel_id=parcel_id,
        raw={"deed_chain": deed_chain} if deed_chain else {},
    )


def _dc(grantor, doc_type, date="2020-01-01"):
    return {
        "summary": {
            "prior_owner": grantor,
            "distress_transfers": [
                {"date": date, "doc_type": doc_type, "grantor": grantor, "price": None, "source": "rod"},
            ],
        }
    }


def test_owner_who_lost_a_parcel_and_holds_another_is_flagged():
    # SMITH JOHN lost parcel P1 to a tax deed in 2020...
    lost = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED"))
    # ...and currently owns a DIFFERENT parcel P2, same county/state.
    current = _mk("SMITH JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 1
    assert stats["tagged_rows"] == 1
    assert "repeat_tax_loss" not in (lost.raw or {})
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 1
    assert current.raw["repeat_tax_loss"]["most_recent_loss_doc_type"] == "TAX DEED"


def test_redemption_of_the_same_parcel_is_not_flagged():
    # The SAME parcel, same owner, same property key -- a buy-back/
    # redemption, not "still holds another property".
    lost = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED"))
    stats = enrich_repeat_tax_loss([lost])
    assert stats["tagged_rows"] == 0
    assert "repeat_tax_loss" not in (lost.raw or {})


def test_non_loss_doc_type_is_ignored():
    # A quitclaim in distress_transfers is real distress but not a tax/
    # foreclosure-sale LOSS -- must not seed the loser index.
    lost = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "QUITCLAIM"))
    current = _mk("SMITH JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 0
    assert "repeat_tax_loss" not in (current.raw or {})


def test_different_county_does_not_match():
    lost = _mk("SMITH JOHN", county="Buncombe", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED"))
    current = _mk("SMITH JOHN", county="Henderson", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["tagged_rows"] == 0


def test_entity_owner_never_matches():
    lost = _mk("ABC HOLDINGS LLC", parcel_id="P1", deed_chain=_dc("ABC HOLDINGS LLC", "TAX DEED"))
    current = _mk("ABC HOLDINGS LLC", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 0
    assert stats["tagged_rows"] == 0


def test_no_deed_chain_is_a_no_op_not_an_error():
    a = _mk("SMITH JOHN", parcel_id="P1")
    b = _mk("SMITH JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([a, b])
    assert stats["losses_indexed"] == 0
    assert stats["tagged_rows"] == 0


def test_most_recent_loss_picked_when_multiple():
    lost1 = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED", date="2018-01-01"))
    lost2 = _mk("SMITH JOHN", parcel_id="P2", deed_chain=_dc("SMITH JOHN", "SHERIFF'S DEED", date="2022-06-01"))
    current = _mk("SMITH JOHN", parcel_id="P3")
    stats = enrich_repeat_tax_loss([lost1, lost2, current])
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 2
    assert current.raw["repeat_tax_loss"]["most_recent_loss_date"] == "2022-06-01"
    assert current.raw["repeat_tax_loss"]["most_recent_loss_doc_type"] == "SHERIFF'S DEED"
