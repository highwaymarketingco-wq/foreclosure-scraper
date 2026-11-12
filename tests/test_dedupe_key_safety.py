"""Pin dedupe-key safety against whitespace-only fields.

Bug: `if self.parcel_id:` accepts whitespace-only strings as truthy,
but `.strip().upper()` reduces them to "". The resulting key
'parcel:NC:' collides every listing with a whitespace parcel_id into
one bucket — and Listing.merge() then mashes unrelated properties
together. Dedupe runs BEFORE validation in the orchestrator, so
validation can't catch it post-hoc.

This test ensures the truthy-check accounts for stripping.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing
from foreclosure_scraper.dedupe import dedupe


def _mk(**over) -> Listing:
    base = dict(
        source="counties_nc.wake_tax",
        source_url="https://example.com/x",
        state="NC",
        county="Wake",
    )
    base.update(over)
    return Listing(**base)


def test_whitespace_parcel_id_falls_through_to_url():
    """A parcel_id of '   ' (whitespace) should not produce a degenerate
    dedupe key — it should fall through to the URL-based key."""
    a = _mk(parcel_id="   ", source_url="https://example.com/a")
    b = _mk(parcel_id="\t\n", source_url="https://example.com/b")
    assert a.dedupe_key() != b.dedupe_key()
    assert a.dedupe_key().startswith("url:")
    assert b.dedupe_key().startswith("url:")


def test_whitespace_case_number_falls_through_to_url():
    """Whitespace case_number must not collide separate listings."""
    a = _mk(case_number=" ", source_url="https://example.com/a")
    b = _mk(case_number="  ", source_url="https://example.com/b")
    assert a.dedupe_key() != b.dedupe_key()


def test_whitespace_address_falls_through():
    """Address with only whitespace + valid zip shouldn't bucket-merge
    every such listing into one."""
    a = _mk(street_address=" ", zip_code="27601", source_url="https://example.com/a")
    b = _mk(street_address="\t", zip_code="27601", source_url="https://example.com/b")
    assert a.dedupe_key() != b.dedupe_key()


def test_dedupe_does_not_merge_whitespace_parcel_records():
    """End-to-end: 5 listings with whitespace parcel_ids should NOT
    dedupe down to 1 — they're different properties from different
    sources, just missing parcel data."""
    listings = [
        _mk(parcel_id="   ", source_url=f"https://example.com/{i}",
            street_address=f"{i*100} Main St", zip_code="27601")
        for i in range(5)
    ]
    out = dedupe(listings)
    # Each has a distinct address+zip, so the address-key path catches them
    assert len(out) == 5


def test_real_parcel_id_still_dedupes():
    """Make sure the fix didn't break legitimate parcel-based dedupe."""
    a = _mk(parcel_id="0123456789", source_url="https://a.example/1")
    b = _mk(parcel_id="0123456789", source_url="https://b.example/2")
    assert a.dedupe_key() == b.dedupe_key()
    out = dedupe([a, b])
    assert len(out) == 1
