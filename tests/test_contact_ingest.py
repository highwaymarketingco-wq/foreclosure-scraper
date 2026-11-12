"""Skip-trace/Propwire export ingest: fuzzy headers, parcel+address match, DNC tag."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.contact_ingest import map_row, ingest_contacts


def _li(parcel=None, addr=None):
    now = datetime.utcnow()
    return Listing(
        source="national.courtlistener_bankruptcy", source_url="https://x/1",
        listing_type=ListingType.BANKRUPTCY, property_kind=PropertyKind.SINGLE_FAMILY,
        state="NC", county="Buncombe", parcel_id=parcel, street_address=addr,
        first_seen=now, last_seen=now, raw={})


def test_map_row_fuzzy_headers_and_multiple_phones():
    row = {"Owner Name": "Jane Doe", "Parcel ID": "9678-12-3456",
           "Property Address": "104 Yates Ave", "Phone 1": "(828) 555-1212",
           "Phone 2": "1-828-555-9999", "Email": "JANE@EXAMPLE.COM",
           "Mailing Address": "PO Box 5"}
    m = map_row(row)
    assert m["name"] == "Jane Doe"
    assert m["parcel"] == "9678-12-3456"
    assert m["phones"] == ["8285551212", "8285559999"]
    assert m["emails"] == ["jane@example.com"]
    assert m["mailing"] == "PO Box 5"


def test_match_by_parcel_normalized():
    li = _li(parcel="9678123456")
    rows = [{"APN": "9678-12-3456", "Mobile": "828.555.1212"}]
    stats = ingest_contacts([li], rows, ingested_at="2026-06-30")
    assert stats["matched"] == 1
    assert li.raw["contact"]["phones"] == ["8285551212"]
    assert li.raw["contact"]["needs_dnc_scrub"] is True
    assert li.raw["contact"]["ingested_at"] == "2026-06-30"


def test_match_by_address_when_no_parcel():
    li = _li(addr="104 Yates Ave")
    rows = [{"Property Address": "104 YATES AVE", "Cell": "8285551212"}]
    stats = ingest_contacts([li], rows)
    assert stats["matched"] == 1
    assert "8285551212" in li.raw["contact"]["phones"]


def test_unmatched_row_counted_not_attached():
    li = _li(parcel="111")
    rows = [{"APN": "999", "Phone": "8285551212"}]
    stats = ingest_contacts([li], rows)
    assert stats["matched"] == 0 and stats["unmatched"] == 1
    assert "contact" not in li.raw


def test_reingest_merges_phones_idempotently():
    li = _li(parcel="111")
    ingest_contacts([li], [{"APN": "111", "Phone": "8285551212"}])
    ingest_contacts([li], [{"APN": "111", "Phone": "8285559999"}])
    assert li.raw["contact"]["phones"] == ["8285551212", "8285559999"]


def test_bad_phone_rejected():
    m = map_row({"Phone": "555-12"})  # too short
    assert m["phones"] == []
