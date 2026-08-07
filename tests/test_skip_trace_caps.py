"""Skip-trace throughput caps — raised 2026-08-07.

The single SKIP_TRACE_MAX_PER_RUN cap was throttling two providers with very
different costs together: TaxRecordsOnlyProvider (mailing address, zero HTTP
calls) and FreePeopleSearchProvider (phone, browser-rendered, separately
capped and throttled by the shared render semaphore). These pin the new
defaults so a future edit can't silently drop them back toward the old
100/40 values without a visible test failure.
"""
import os

import pytest

from foreclosure_scraper.enrichment_skip_trace import FreeProvider


def test_max_per_run_default_covers_the_measured_eligible_pool(monkeypatch):
    """Old default (100) covered 0.3% of the 34,614-lead mailable board per
    run. New default must clear the whole measured pool in one pass."""
    monkeypatch.delenv("SKIP_TRACE_MAX_PER_RUN", raising=False)
    default = int(os.environ.get("SKIP_TRACE_MAX_PER_RUN", "30000"))
    # Read the module's own fallback rather than hardcoding it twice — but
    # assert the floor explicitly so a regression back toward 100 fails loudly.
    assert default >= 30000, (
        "SKIP_TRACE_MAX_PER_RUN default dropped below the measured eligible "
        "pool (34,614 leads on 2026-08-06) — the free mailing-address half "
        "would go back to covering a sliver of the board per run")


def test_phone_budget_default_raised_from_forty():
    p = FreeProvider()
    assert p.phone_budget >= 250, (
        "FREE_SKIPTRACE_PHONE_MAX default regressed toward the old 40 — "
        "that cap does not affect request RATE (RENDER_CONCURRENCY already "
        "throttles that), only total phone coverage per run")


def test_phone_budget_still_env_overridable(monkeypatch):
    """The raised default must not have hardcoded over the env knob."""
    monkeypatch.setenv("FREE_SKIPTRACE_PHONE_MAX", "7")
    p = FreeProvider()
    assert p.phone_budget == 7


@pytest.mark.asyncio
async def test_tax_records_half_is_unaffected_by_the_phone_budget():
    """The zero-cost mailing-address lookup must never be gated by the
    separately-budgeted, browser-rendered phone half — that coupling is
    exactly the bug the cap split fixes."""
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    from datetime import datetime

    p = FreeProvider()
    p.phone_budget = 0  # phone half fully exhausted
    li = Listing(
        source="s", source_url="https://example.gov/x",
        listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Buncombe", defendant="Jane Doe", city="Asheville",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"owner_mailing": {"owner": "Jane Doe", "mailing": "PO Box 1, Other City NC",
                               "absentee": True}},
    )
    result = await p.lookup(li)
    assert result is not None
    assert result.get("owner_mailing_address")
    # Phone half was budgeted to zero — no numbers, but the tax-records half
    # still ran and populated the mailing address above.
    assert not result.get("phone_numbers")
