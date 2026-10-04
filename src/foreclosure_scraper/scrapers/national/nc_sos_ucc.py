"""NC Secretary of State UCC fixture-filing search.

DISABLED 2026-10-01 (per-source extraction-completeness audit) — confirmed
dead AND confirmed never worked as designed. Two separate live findings:

1. The target URL (_UCC_SEARCH_URL) 307-redirects into sosnc.gov's generic
   "Business Registration" search widget. The landing page's HTML contains
   zero occurrences of "UCC", "Uniform Commercial Code", "financing
   statement", "debtor", or "secured party" anywhere -- confirmed by a full
   text search of the live page. The CorpSearchType dropdown on that widget
   only offers four modes (Company By Name / SOSID / Company Officials /
   Registered Agents), none of them UCC. Whatever dedicated UCC-filing
   search sosnc.gov once hosted at this path is gone; the URL now serves an
   unrelated generic entity search.

2. This module's own premise was already broken independent of (1): the
   docstring used to claim "the search supports date-range browsing ('filed
   in last N days')", but the live page has NO date-range input of any
   kind -- only a free-text organization/individual NAME search (Words:
   Starting With / All / Any / Exact Match). There was never a way to
   "discover filings broadly without knowing debtor names in advance" on
   this site; the whole broad-discovery design this scraper was built
   around does not match how sosnc.gov's search actually works. Even before
   finding (1), filling the search box with a wildcard like "a" and
   submitting correctly (the old page_action's button-selector guesses all
   missed the real #SubmitButton, so it silently never submitted at all --
   confirmed the returned HTML was always the untouched blank form, 42,063
   bytes every time) would only ever have searched the wrong record type.

_fetch_ucc_page/_parse_results/_is_fixture are kept below as
_disabled_fetch for reference. A real rebuild would need to find whether
NC SOS exposes a genuine UCC-filing browse/bulk-export anywhere (unverified
either way) rather than retrying this page.

Free, no auth, public record, Scrapling stealth — the approach itself
(running Cloudflare's own JS challenge via a real headless browser) is
compliant and still proven elsewhere (enrichment_sos_dissolution.py,
enrichment_sos_agent.py); it is this page's actual content that is dead.

FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 17), same
bug class as the 2026-10-01 law_firms.korn fix: `fetch()` below was a
hardcoded `return []` with NO `disabled = True` set on the class. `disabled`
defaults to False (base_scraper.py), so every run executed the normal
`safe_run()` path, got an empty list back, and recorded `OUTCOME_ZERO`
("ran clean but returned 0 rows") -- indistinguishable from a genuinely
quiet day on a source whose data is real but sparse. The module's OWN
docstring above already proves this source is permanently, confirmedly
dead (wrong content at the URL, broken search-form premise), not
intermittently empty. Set `disabled = True` with the reason already
documented above, so `safe_run()` now reports the accurate
`OUTCOME_DORMANT` instead.

Also re-verified live 2026-10-04: the target URL is now gated behind an
ADDITIONAL, active Cloudflare JS "Just a moment..." challenge that did not
let even a genuine (non-headless) browser through after ~18s of waiting --
strictly worse than the 2026-10-01 finding (a redirect to unrelated
content), not better. The disable conclusion is reconfirmed, not weakened.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_UCC_SEARCH_URL = "https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code"

# Reliability guards — same pattern as enrichment_sos_dissolution.py.
_CALL_TIMEOUT_S = float(os.environ.get("SOS_UCC_CALL_TIMEOUT_S", "120"))
_MAX_SECONDS = float(os.environ.get("SOS_UCC_MAX_SECONDS", "300"))
_BREAKER_FAILS = int(os.environ.get("SOS_UCC_BREAKER_FAILS", "3"))

# Fixture-filing keywords in the collateral description.
_FIXTURE_KEYWORDS = (
    "fixture", "real property", "real estate", "as-extracted collateral",
    "as extracted collateral", "mortgage", "deed of trust", "deed-of-trust",
    "immovable", "land", "premises", "building",
)

# NC counties in our core footprint.
_FOOTPRINT_COUNTIES = {
    "buncombe", "haywood", "henderson", "madison", "transylvania",
    "polk", "rutherford", "mcdowell", "yancey", "jackson",
    "macon", "swain", "graham", "cherokee", "clay",
    # Upstate SC border counties served from NC SOS
}

_FILING_DATE_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})", re.I
)
_FILING_NUM_RE = re.compile(
    r"(\d{4,}-?\d{4,})", re.I
)


def _is_fixture(collateral: str) -> bool:
    """True if the collateral description mentions real-property fixtures."""
    if not collateral:
        return False
    low = collateral.lower()
    return any(k in low for k in _FIXTURE_KEYWORDS)


def _parse_date(s: str) -> datetime | None:
    """Parse NC SOS date formats (M/D/YYYY)."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def _fetch_ucc_page(days_back: int = 90) -> str:
    """Stealth-render the NC SOS UCC search page and return result HTML.

    Uses the same Scrapling StealthyFetcher pattern as enrichment_sos_dissolution.
    The page_action fills the date-range search and submits.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("nc_sos_ucc.no_scrapling")
        return ""

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%m/%d/%Y")

    async def page_action(page):
        try:
            # Wait for the SearchCriteria input (confirmed field name on the
            # by_title/_uniform_commercial_code page).
            await page.wait_for_selector(
                "input[name='SearchCriteria'], input[name*='search'], input[type='text']",
                timeout=20000,
            )

            # The UCC page has: SearchCriteria (broad text), IndividualsSurname,
            # FirstPersonalName, AdditionalNamesInitials.  Fill SearchCriteria
            # with "a" for a broad wildcard search (the form requires input).
            el = await page.query_selector("input[name='SearchCriteria']")
            if el:
                await el.fill("a")
            else:
                # Fallback: try generic search inputs.
                for sel in (
                    "input[name*='search']", "input[type='search']",
                    "input[name*='debtor']", "input[name*='name']",
                ):
                    try:
                        el = await page.query_selector(sel)
                        if el and not await el.input_value():
                            await el.fill("a")
                            break
                    except Exception:
                        continue

            # Click submit.
            for btn in (
                "button[type='submit']", "input[type='submit']",
                "button:has-text('Search')", "input[value*='Search']",
                "button:has-text('search')",
            ):
                try:
                    await page.click(btn, timeout=5000)
                    break
                except Exception:
                    continue

            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            # If the page_action fails, we still get whatever HTML loaded.
            pass

    try:
        coro = StealthyFetcher.async_fetch(
            _UCC_SEARCH_URL, headless=True, network_idle=True, timeout=90000,
            page_action=page_action, solve_cloudflare=True,
        )
        result = await asyncio.wait_for(coro, timeout=_CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("nc_sos_ucc.render_timeout")
        return ""
    except Exception as exc:
        log.warning("nc_sos_ucc.render_error", error=str(exc)[:200])
        return ""

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    return html


def _parse_results(html: str) -> list[dict]:
    """Parse UCC search results from the rendered HTML.

    NC SOS results pages typically show a table with columns:
    Filing Number | Debtor Name | Secured Party | Filing Date | Collateral

    We defensively try table parsing and fall back to regex extraction.
    """
    results: list[dict] = []
    if not html:
        return results

    # Check for Cloudflare challenge page.
    if "just a moment" in html.lower() or "challenge-platform" in html:
        log.warning("nc_sos_ucc.cloudflare_blocked")
        return results

    # Try table-based parsing.
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        for row in tree.css("table tr"):
            cells = row.css("td")
            if len(cells) < 3:
                continue
            texts = [c.text(strip=True) for c in cells]
            entry: dict = {}
            for i, t in enumerate(texts):
                low = t.lower()
                if "filing" in low and ("num" in low or "filed" in low or _FILING_NUM_RE.search(t)):
                    entry["filing_number"] = t
                elif _parse_date(t):
                    entry["filing_date"] = t
                elif "debtor" in low or "name" in low:
                    if i + 1 < len(texts):
                        entry["debtor"] = texts[i + 1]
                elif "secured" in low:
                    if i + 1 < len(texts):
                        entry["secured_party"] = texts[i + 1]
                elif "collateral" in low:
                    if i + 1 < len(texts):
                        entry["collateral"] = texts[i + 1]

            # If table has no headers, use positional parsing.
            if "debtor" not in entry and len(texts) >= 4:
                entry.setdefault("debtor", texts[0])
                entry.setdefault("secured_party", texts[1])
                entry.setdefault("filing_date", texts[2] if _parse_date(texts[2]) else "")
                entry.setdefault("collateral", texts[3] if len(texts) > 3 else "")

            if entry.get("debtor"):
                results.append(entry)
    except ImportError:
        pass

    # Fallback: regex-based extraction for non-table layouts.
    if not results:
        # Look for filing blocks separated by <hr> or <div class="result">
        blocks = re.split(r'<hr\s*/?>|class=["\']result', html, flags=re.I)
        for block in blocks:
            entry: dict = {}
            # Debtor name
            m = re.search(r"debtor[:\s]*</?\w*[^>]*>([^<]+)", block, re.I)
            if m:
                entry["debtor"] = m.group(1).strip()
            # Secured party
            m = re.search(r"secured\s*party[:\s]*</?\w*[^>]*>([^<]+)", block, re.I)
            if m:
                entry["secured_party"] = m.group(1).strip()
            # Filing date
            m = _FILING_DATE_RE.search(block)
            if m:
                entry["filing_date"] = m.group(1)
            # Filing number
            m = _FILING_NUM_RE.search(block)
            if m:
                entry["filing_number"] = m.group(1)
            # Collateral
            m = re.search(r"collateral[:\s]*</?\w*[^>]*>([^<]+)", block, re.I)
            if m:
                entry["collateral"] = m.group(1).strip()
            if entry.get("debtor"):
                results.append(entry)

    return results


class NcSosUccScraper(BaseScraper):
    """NC SOS UCC fixture-filing search via Scrapling stealth render."""

    slug = "national.nc_sos_ucc"
    name = "NC SOS UCC Fixture Filings"
    category = "national_aggregator"
    expected_min_count = 0
    optional = True
    timeout_s = 300.0
    # FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 17):
    # see module docstring's FOUND note -- fetch() used to hardcode
    # `return []` with no `disabled` flag, so safe_run() recorded the
    # ambiguous OUTCOME_ZERO every run instead of the accurate
    # OUTCOME_DORMANT this confirmed-permanently-dead source deserves.
    disabled = True
    disabled_reason = (
        "sosnc.gov's UCC search URL 307-redirects to an unrelated generic "
        "Business Registration search widget with zero UCC content "
        "(confirmed live 2026-10-01), and the scraper's own broad "
        "date-range-discovery premise never matched how that site's real "
        "name-only search works even before that; re-verified live "
        "2026-10-04 the URL is now ALSO gated behind an active Cloudflare "
        "challenge a genuine browser didn't clear in ~18s -- strictly "
        "worse, not better. See module docstring for full detail."
    )

    async def fetch(self) -> Iterable[Listing]:
        # Confirmed permanently dead -- see module docstring. `disabled =
        # True` above means safe_run never even calls this, but fetch()
        # stays a safe no-op for any direct caller (tests, __main__
        # probes, etc.)
        return []

    async def _disabled_fetch(self) -> Iterable[Listing]:
        html = await _fetch_ucc_page(days_back=90)
        if not html:
            log.warning("nc_sos_ucc.empty_html")
            self.last_outcome = OUTCOME_BLOCKED
            self.last_reason = "Stealth render returned empty (Cloudflare or timeout)"
            return []

        rows = _parse_results(html)
        if not rows:
            log.info("nc_sos_ucc.no_results",
                     hint="Cloudflare may have blocked, or search form changed")
            return []

        out: list[Listing] = []
        fixture_count = 0
        for r in rows:
            collateral = r.get("collateral", "")
            if not _is_fixture(collateral):
                continue
            fixture_count += 1

            filing_date = _parse_date(r.get("filing_date", ""))

            li = Listing(
                source=self.slug,
                source_url=_UCC_SEARCH_URL,
                listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                defendant=r.get("debtor", ""),
                plaintiff=r.get("secured_party", ""),
                case_number=r.get("filing_number"),
                sale_date=filing_date,
                description=f"UCC fixture filing: {collateral[:200]}" if collateral else None,
                raw={
                    "filing_number": r.get("filing_number"),
                    "debtor": r.get("debtor"),
                    "secured_party": r.get("secured_party"),
                    "filing_date": r.get("filing_date"),
                    "collateral": collateral,
                    "source": "nc_sos_ucc",
                },
            )
            out.append(li)

        log.info("nc_sos_ucc.done",
                 total_parsed=len(rows), fixture_filings=fixture_count)
        return out
