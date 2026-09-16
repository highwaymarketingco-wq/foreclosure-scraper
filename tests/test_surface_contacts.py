"""Regression test for the 2026-09-16 surface_contacts persistence bug.

enrich_surface_contacts() built `raw = li.raw if isinstance(li.raw, dict)
else {}` and mutated that local `raw` for the rest of the loop body, but
never assigned it back to `li.raw` when a fresh dict was created. Every
mutation for a row whose raw wasn't already a dict vanished at the end of
that loop iteration. Live-reproduced running the first-ever board-wide
call: stats correctly counted emails_found=119248 across
new_email_listings=47790, but the board gained exactly 18 new owner_email
entries -- the function computed the right answer and then discarded it
for effectively every row.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_surface_contacts import enrich_surface_contacts
from foreclosure_scraper.models import Listing, ListingType


def _mk_listing(raw=None) -> Listing:
    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe")
    li.raw = raw
    return li


def test_raw_becomes_a_real_dict_when_it_starts_as_none():
    li = _mk_listing(raw=None)
    assert li.raw is None
    stats = enrich_surface_contacts([li])
    assert stats["total"] == 1
    # No contact-bearing data was present, so nothing should be found --
    # but critically, raw must now be a real dict on the OBJECT, not still
    # None and not an orphaned local copy.
    assert isinstance(li.raw, dict)


def test_email_found_in_notice_contact_actually_persists_onto_the_listing():
    li = _mk_listing(raw={"notice_contact": {"email": "attorney@examplefirm.com"}})
    stats = enrich_surface_contacts([li])
    assert stats["listings_with_new_emails"] == 1
    assert li.raw["owner_email"]["best_email"] == "attorney@examplefirm.com"


def test_phone_and_email_persist_when_raw_is_none_and_gets_populated_by_the_function():
    """The exact regression: raw is None going in. Even though there is no
    data to surface in that case (nothing was ever attached), the function
    must not crash and must leave raw as a real dict for later enrichers."""
    li = _mk_listing(raw=None)
    stats = enrich_surface_contacts([li])
    assert isinstance(li.raw, dict)
    assert stats["total"] == 1
    assert stats["listings_with_new_phones"] == 0
    assert stats["listings_with_new_emails"] == 0


def test_non_dict_raw_still_surfaces_and_persists_when_data_was_attached_first():
    """Covers the real production shape: a scraper attaches a dict payload
    (this IS a dict, just built fresh), and the enricher must write onto
    that same object -- not an orphaned copy."""
    li = _mk_listing(raw={"distressed": {"agent_email": "Agent@Broker.com",
                                          "agent_phones": [{"number": "704-555-0100", "type": "MOBILE"}]}})
    stats = enrich_surface_contacts([li])
    assert stats["listings_with_new_emails"] == 1
    assert stats["listings_with_new_phones"] == 1
    assert li.raw["owner_email"]["best_email"] == "agent@broker.com"
    assert li.raw["owner_phone"]["phone"]


def test_does_not_overwrite_an_existing_owner_email():
    li = _mk_listing(raw={
        "owner_email": {"emails": [{"email": "already@set.com"}], "best_email": "already@set.com"},
        "notice_contact": {"email": "new@shouldnotwin.com"},
    })
    enrich_surface_contacts([li])
    assert li.raw["owner_email"]["best_email"] == "already@set.com"
