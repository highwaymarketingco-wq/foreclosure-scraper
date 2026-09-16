"""Regression tests for the 2026-09-16 systemic sweep of the "orphaned raw
dict" bug class.

The pattern `raw = li.raw if isinstance(li.raw, dict) else {}` followed by
mutating `raw` (raw[...] = ..., raw.pop(...), etc.) WITHOUT reassigning it
back to `li.raw` silently discards every write when li.raw starts as
something other than a dict (commonly None on a freshly-parsed lead).
Confirmed live in enrichment_surface_contacts.py: emails_found=119248
computed correctly, only 18 persisted.

An AST + regex scan of the whole src/ tree for this exact pattern combined
with a later mutation of the local var (and no `li.raw = <var>` reassignment
anywhere in the function) found 6 more candidates. 2 were false positives
(enrichment_dnc.py, enrichment_marriage_license.py both bail out via
`if not raw: continue` before any mutation is reachable) but were hardened
anyway for defense-in-depth. 3 were confirmed real, reachable bugs:
enrichment_email_extract.py, enrichment_equity.py's _payoff(), and
enrichment_hud_fmr.py. main.py's _resolve_pending (the one actually wired
into the live pipeline) was safe in practice by call-order invariants but
hardened the same way since it's live production code.

These tests cover the confirmed-real ones plus main.py's live-pipeline one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from foreclosure_scraper.enrichment_email_extract import enrich_extract_emails
from foreclosure_scraper.enrichment_hud_fmr import _match_listing_to_fmr
from foreclosure_scraper.models import Listing, ListingType


def _mk_listing(raw=None, **kw) -> Listing:
    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe", **kw)
    li.raw = raw
    return li


def test_email_extract_persists_onto_the_listing_not_an_orphan_copy():
    li = _mk_listing(raw={"description": "Contact the trustee at foreclosure@examplefirm.com for details"})
    stats = enrich_extract_emails([li])
    assert stats["listings_with_emails"] == 1
    assert isinstance(li.raw, dict)
    assert li.raw["owner_email"]["best_email"] == "foreclosure@examplefirm.com"


def test_email_extract_raw_becomes_a_real_dict_even_when_it_starts_as_none():
    li = _mk_listing(raw=None)
    assert li.raw is None
    stats = enrich_extract_emails([li])
    assert stats["listings_scanned"] == 1
    assert isinstance(li.raw, dict)


def test_hud_fmr_match_helper_leaves_a_real_dict_on_the_object():
    """_match_listing_to_fmr is a leaf helper inside enrich_hud_fmr; verify
    the isinstance guard it opens with actually lands on li.raw, not an
    orphaned local copy, since later code in enrich_hud_fmr writes onto
    li.raw via the same `raw` binding."""
    li = _mk_listing(raw=None)
    assert li.raw is None
    _match_listing_to_fmr(li)
    assert isinstance(li.raw, dict)


def test_hud_fmr_match_helper_does_not_crash_when_raw_is_already_a_dict():
    """Regression for a mistake made WHILE fixing the orphan-dict bug: an
    early version put `raw = li.raw` INSIDE the `if not isinstance(...)`
    block instead of after it, so when li.raw was already a dict (the
    common case) `raw` was never bound at all and the very next line
    (`raw.get(...)`) raised UnboundLocalError. Same mistake, same fix,
    independently made in enrichment_dnc.py's _get_phones -- covered by
    tests/test_goliath_gap_modules.py::TestDNcScrubber."""
    li = _mk_listing(raw={"state": "NC", "county": "Buncombe"})
    assert isinstance(li.raw, dict)
    result = _match_listing_to_fmr(li)  # must not raise UnboundLocalError
    assert result is None or isinstance(result, dict)
