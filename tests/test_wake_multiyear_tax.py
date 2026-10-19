"""enrichment_wake_multiyear_tax: Wake County NC multi-year delinquent-tax history, read per
parcel from services.wake.gov (tax_lien_wake.py's own bridge + bill-history fetch, reused
verbatim). No network -- a FakeSite stands in for the live PIN->REID bridge + bill page the same
way test_gaston_multiyear_tax.py's own FakeSite does.

Real markup reused from test_verification_tax_lien_wake.py (captured live 2026-10-18); every
dollar figure and year below is read straight off that live page, not invented.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.verifiers import tax_lien_wake as _wake
from foreclosure_scraper import enrichment_wake_multiyear_tax as mod
from foreclosure_scraper.enrichment_wake_multiyear_tax import (
    build_block, enrich_with_wake_multiyear_tax, _resolve_and_fetch,
)
from tests.test_verification_tax_lien_wake import (
    REAL_BILLS_0047895, REAL_BILLS_0210739, REAL_BILLS_0167151, PIN, REID,
)

TODAY = date(2026, 10, 18)


def _bridge_json(reid=REID) -> str:
    return json.dumps({"features": [{"attributes": {"altparno": reid}}]})


class FakeSite:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.asked: list[str] = []

    async def get_text(self, url, **_):
        self.asked.append(url)
        if url not in self.pages:
            raise RuntimeError(f"unexpected url {url}")
        return self.pages[url]


def _site_for(pin: str, reid: str, bills_html: str) -> FakeSite:
    return FakeSite({
        _wake._bridge_url(pin): _bridge_json(reid=reid),
        _wake.BILLS_URL.format(reid=reid): bills_html,
    })


def _li(parcel, county="Wake", state="NC", raw=None) -> Listing:
    return Listing(source="counties_generic.nc_onemap", source_url="https://x/1",
                  listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


def _real_bills() -> list[dict]:
    return _wake.parse_bills(REAL_BILLS_0047895)


# ---------------------------------------------------------------------------
# build_block: pure, real numbers off the live-captured page
# ---------------------------------------------------------------------------

def test_real_multi_year_parcel_qualifies_with_the_live_dollar_figures():
    block = build_block(PIN, REID, _real_bills(), today=TODAY)
    assert block is not None
    assert block["years"] == [2022, 2023, 2024, 2025, 2026]
    assert block["matured_years"] == [2022, 2023, 2024, 2025]
    assert block["total_due"] == block["total_owed"] == 10178.84
    assert block["matured_owed"] == 8544.53
    assert block["current_levy_year"] == 2026 and block["in_current_levy"] is True
    assert block["consecutive_years"] == 5
    assert block["reid"] == REID
    assert block["parcel_key"] == "1713252770"
    assert "owner" not in block and "mailing" not in block   # privacy


def test_the_rollback_tracking_row_is_never_counted_as_a_second_bill():
    bills = _wake.parse_bills(REAL_BILLS_0167151)
    block = build_block("1797953869", "0167151", bills, today=TODAY)
    # 2025/2026 ordinary bills are $0.00/$197.79 -- only one year ever owes, below MIN_YEARS.
    assert block is None


def test_below_min_years_does_not_qualify():
    bills = _wake.parse_bills(REAL_BILLS_0210739)
    assert build_block("0765045120", "0210739", bills, today=TODAY) is None


def test_two_consecutive_unpaid_years_is_the_minimum_qualifying_shape():
    bills = [{"year": 2025, "suffix": "000000", "flag": "Delinquent", "amount_due": 100.0},
            {"year": 2026, "suffix": "000000", "flag": "", "amount_due": 50.0}]
    block = build_block("900001", "0900001", bills, today=TODAY)
    assert block["years"] == [2025, 2026] and block["matured_years"] == [2025]
    assert block["total_due"] == 150.0 and block["matured_owed"] == 100.0


# ---------------------------------------------------------------------------
# _resolve_and_fetch
# ---------------------------------------------------------------------------

def test_resolve_and_fetch_ok_path_reuses_tax_lien_wake_verbatim():
    site = _site_for(PIN, REID, REAL_BILLS_0047895)
    reid, bills, status = run(_resolve_and_fetch(site, PIN, TODAY))
    assert (reid, status) == (REID, "ok")
    assert bills[0]["year"] == 2026


def test_resolve_and_fetch_bridge_no_match():
    site = FakeSite({_wake._bridge_url(PIN): json.dumps({"features": []})})
    reid, bills, status = run(_resolve_and_fetch(site, PIN, TODAY))
    assert (reid, bills, status) == (None, None, "bridge_no_match")


# ---------------------------------------------------------------------------
# enrich_with_wake_multiyear_tax: end to end, eligibility + idempotency + privacy
# ---------------------------------------------------------------------------

def test_only_wake_nc_rows_with_a_parcel_are_eligible():
    rows = [
        _li(PIN),                                            # eligible
        _li(PIN, county="Durham"),                            # wrong county
        _li(PIN, state="SC"),                                  # wrong state
        _li(None),                                            # no parcel
        _li(PIN, raw={"multi_year_delinquent_tax": {"already": True}}),  # already done
        _li(PIN, raw={"_wake_mydt_checked": "insufficient_history"}),    # already checked
    ]
    stats = run(enrich_with_wake_multiyear_tax(rows, client=_site_for(PIN, REID, REAL_BILLS_0047895)))
    assert stats["eligible"] == 1 and stats["attempted"] == 1 and stats["qualified"] == 1


def test_a_qualifying_row_is_stamped_with_the_shared_signal_key():
    li = _li(PIN)
    stats = run(enrich_with_wake_multiyear_tax([li], client=_site_for(PIN, REID, REAL_BILLS_0047895)))
    assert stats["qualified"] == 1
    block = li.raw["multi_year_delinquent_tax"]
    assert block["total_due"] == 10178.84 and block["parcel_key"] == "1713252770"
    assert block["reid"] == REID
    assert "_wake_mydt_checked" not in li.raw


def test_a_resolved_but_non_qualifying_row_gets_the_checked_sentinel_not_the_real_key():
    li = _li("0765045120")
    stats = run(enrich_with_wake_multiyear_tax(
        [li], client=_site_for("0765045120", "0210739", REAL_BILLS_0210739)))
    assert stats["qualified"] == 0 and stats["insufficient_history"] == 1
    assert li.raw.get("_wake_mydt_checked") == "insufficient_history"
    assert "multi_year_delinquent_tax" not in li.raw


def test_a_bridge_failure_gets_the_checked_sentinel_with_its_real_reason():
    li = _li(PIN)
    site = FakeSite({_wake._bridge_url(PIN): json.dumps({"features": []})})
    stats = run(enrich_with_wake_multiyear_tax([li], client=site))
    assert stats["no_bridge_match"] == 1
    assert li.raw.get("_wake_mydt_checked") == "bridge_no_match"


def test_the_checked_sentinel_makes_the_next_run_a_no_op():
    li = _li(PIN, raw={"_wake_mydt_checked": "bridge_no_match"})
    site = _site_for(PIN, REID, REAL_BILLS_0047895)
    stats = run(enrich_with_wake_multiyear_tax([li], client=site))
    assert stats["eligible"] == 0 and stats["attempted"] == 0
    assert site.asked == []


def test_the_kill_switch_short_circuits_with_no_network_at_all(monkeypatch):
    monkeypatch.setattr(mod, "ENABLED", False)
    li = _li(PIN)
    site = _site_for(PIN, REID, REAL_BILLS_0047895)
    stats = run(enrich_with_wake_multiyear_tax([li], client=site))
    assert stats["eligible"] == 0
    assert site.asked == []


def test_the_per_run_cap_is_respected(monkeypatch):
    monkeypatch.setattr(mod, "MAX_ROWS", 2)
    rows = [_li(PIN) for _ in range(5)]
    stats = run(enrich_with_wake_multiyear_tax(rows, client=_site_for(PIN, REID, REAL_BILLS_0047895)))
    assert stats["eligible"] == 5 and stats["attempted"] == 2 and stats["skipped_cap"] == 3
