"""SC Department of Revenue Tax Lien Registry — the REAL statewide state-tax-lien
source (not sc_dew_lien_registry.py, which is a different agency's UNEMPLOYMENT
tax lien registry; this is the state's general income/sales/withholding tax
lien registry, DOR itself).

NEW SOURCE discovered 2026-11-25 by Hermes independent verification, confirmed
live by Claude the same day: https://mydorway.dor.sc.gov/?link=LienRegistry --
genuinely free, no CAPTCHA, no login, covering SC state tax liens filed
statewide since Nov 1, 2019 (per the page's own copy).

IMPLEMENTED 2026-11-26 (this file was previously an honest stub: it extracted
an ASP.NET __VIEWSTATE token and explicitly returned empty, "needs browser
automation" -- that __VIEWSTATE path was a dead end, see below). Live
investigation (Claude, in-browser DOM + network inspection, not guessed):

THE SITE IS NOT ASP.NET WEBFORMS. The "__VIEWSTATE" hidden input the old stub
looked for does not exist -- this is a proprietary stateful low-code framework
(internal element ids/field names like "Dc-r", "Dc-t", request params like
"FAST_CLIENT_AJAX_ID__", "FAST_VERLAST__") that drives the whole UI through two
endpoints, `Recalc` (fired on every field edit) and `EventOccurred` (fired on a
button click), each POST carrying a sequential per-session version token tied
to the PRECEDING response plus a full browser fingerprint. Replaying this raw
protocol with httpx would mean re-deriving that version-token chaining AND
fingerprint generation for every request -- fragile and not worth it when a
real browser just handles the whole thing for free. No Cloudflare/CAPTCHA at
all on this host (confirmed), so a PLAIN Playwright session is enough; no
StealthyFetcher-style Cloudflare bypass needed (unlike nc_ccs_name_search.py's
Caldwell/Franklin/Hertford paths).

CONFIRMED LIVE, stable (re-checked across two separate fresh page loads, same
ids both times -- these are framework-generated but NOT session-random):
  Individual-mode radio: #Dc-a_1
  First Name input:      #Dc-r   (REQUIRED -- confirmed via the red asterisk +
                                   a submit with it empty silently no-ops,
                                   client-side validation, not a rate limit)
  Last Name input:       #Dc-t   (REQUIRED, same as above)
  Search button:         #Dc-b1
  Results table:         #Dc-x1 (rows tr#Dc-x1-N, N resets to 1 on each new
                                  page of results, NOT a global row index)
  Result cell ids (row N): #Dc-n1-N Lien ID | #Dc-o1-N primary debtor name |
    #Dc-p1-N second name (co-debtor OR a business DBA alias -- can't always
    tell which from the cell alone) | #Dc-q1-N address | #Dc-r1-N county (or
    the literal "Statewide" when DOR has no county on file) | #Dc-s1-N balance
    due | #Dc-u1-N date filed | #Dc-v1-N date satisfied (blank if unsatisfied)
  Next-page link: #Dc-x1_pgnext (100 rows/page; absent/unclickable on the last
    page -- confirmed live: "John"+"Smith" returned 110 rows over 2 pages)

NAME-PAIR SEARCH, NOT A BARE SURNAME SWEEP: unlike nc_ccs_name_search.py's
per-county CCS sites (surname alone is a full, valid search there), THIS site
requires BOTH first and last name -- there is no single-field broad Individual
search. (A LAST-NAME-ONLY submit looked at first like it silently failed or
hit a "locked out" wall; re-tested clean on a fresh page load and it's neither
-- the submit is just client-side blocked because First Name is empty. The
"locked out" text that showed up in an earlier textContent search is static
template copy ALWAYS present in the DOM, even on a page that was never
searched at all -- not a live state.) _NAME_PAIRS below is therefore a bounded
grid of common (first, last) combinations, not a single-dimension surname
list -- real coverage of the full registry would need a much larger grid or a
different search angle (Business-name sweep: confirmed live that a single
required Business Name field DOES support broad substring matching -- a
"LLC" search returned real paginated results -- but it took 15+ seconds for
that one broad term, vs the Individual path's near-instant response for a
specific name pair; left for a future expansion rather than built blind here).

Each registry row becomes a standalone ListingType.TAX_LIEN lead AND populates
raw["sc_state_tax_lien"] = {owner, balance} in the exact shape
enrichment_lien_stack.py already reads (see that file's own docstring: "We
already pull the SCDOR Top-Delinquent-Taxpayer list each run" -- a DIFFERENT,
narrower existing SC DOR source; this registry is the same agency's much
larger general lien database, feeding the SAME downstream cross-reference
pipeline sc_dew_lien_registry.py already wires into, not a second disconnected
copy of it). The lien-stack joiner itself requires a 3+ token owner name
(first + middle/initial + last) to avoid false-matching a common 2-token name
-- most Individual-search rows here will be bare "LAST, FIRST" (2 tokens) and
won't satisfy that join, which is fine: the row is still a real, valuable
standalone TAX_LIEN lead regardless of whether the cross-reference happens to
fire for it.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import structlog

from ...base_scraper import BaseScraper
from ...config import in_scope_distressed
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_SEARCH_URL = "https://mydorway.dor.sc.gov/?link=LienRegistry"
_SOURCE_URL = _SEARCH_URL

# The radio input itself (#Dc-a_1) is visually hidden (jQuery UI's
# "ui-helper-hidden-accessible" pattern); its sibling <label> is the real,
# visible click target the framework expects a real interaction on. A
# force=True click directly on the hidden input DOES register at the DOM
# level but does not reliably trigger this framework's own state transition
# (confirmed live: the dependent First/Last Name fields never became
# interactable afterward) -- click the label instead, same as a real user.
_SEL_INDIVIDUAL_TAB = 'label[for="Dc-a_1"]'
_SEL_FIRST_NAME = "#Dc-r"
_SEL_LAST_NAME = "#Dc-t"
_SEL_SEARCH_BTN = "#Dc-b1"
_SEL_RESULTS_TABLE = "#Dc-x1"
_SEL_NEXT_PAGE = "#Dc-x1_pgnext"

_MAX_PAGES_PER_SEARCH = 15  # 1,500 rows/search ceiling -- generous, bounded
_PAGE_LOAD_TIMEOUT_MS = 20_000
_SEARCH_BETWEEN_DELAY_S = 1.5  # courtesy pacing between name-pair searches

# Bounded (first, last) grid -- common U.S. first names x common U.S.
# surnames. Real exhaustive coverage of the registry would need a much larger
# grid (or the Business-name substring-sweep angle noted in the module
# docstring); this is a reasonable, genuinely-working first corpus, not
# claimed as complete.
_FIRST_NAMES = (
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "William", "Elizabeth",
)
_LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor",
    "Thomas", "Moore",
)

# Anchors on the reliable tail only (state + zip, optional trailing "USA") --
# the street/city boundary before it is NOT reliably regex-separable across
# both observed formats (see _split_address), so that part is split in code.
_ADDR_TAIL = re.compile(
    r"^(?P<rest>.*?)[,\s]+(?P<state>[A-Z]{2})[,\s]+(?P<zip>\d{5}-?\d{0,4})"
    r"\s*(?:USA)?\s*$"
)
_MONEY_RE = re.compile(r"[\d,.]+")


def _money(text: str | None) -> float | None:
    if not text:
        return None
    m = _MONEY_RE.search(text)
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return v if v else None


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    head = text.strip().split()[0] if text.strip() else ""
    for fmt in ("%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(head, fmt)
        except ValueError:
            continue
    return None


def _split_address(addr: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """Best-effort (street, city, state, zip) split. DOR's own address text
    mixes two formats live-observed on the same result page -- comma-joined
    ("130 COUNTRY CLUB RD, DARLINGTON, SC, 295324228", zip+4 run together with
    no hyphen) and bare space-joined with a trailing "USA" ("311 POWELL MILL
    RD APT E SPARTANBURG SC 29301-1537 USA"). Only the state+zip tail is
    regex-anchored (reliable from the END of the string either way); the
    street/city split before it is NOT reliably regex-separable without
    commas (a street can itself be multiple words), so it's a plain
    comma-or-heuristic split in code, not claimed to be exact for every
    multi-word city."""
    if not addr:
        return None, None, None, None
    s = " ".join(addr.split())
    m = _ADDR_TAIL.match(s)
    if not m:
        return s, None, None, None
    rest = (m.group("rest") or "").strip(", ")
    state = (m.group("state") or "").strip().upper() or None
    zipc = (m.group("zip") or "").replace("-", "")[:5] or None
    if not rest:
        return None, None, state, zipc
    if "," in rest:
        street, _, city = rest.rpartition(",")
        street = street.strip(", ") or None
        city = city.strip().title() or None
    else:
        # No comma to anchor on -- heuristically take the last word as the
        # city. Under-splits a genuinely multi-word city ("North Myrtle
        # Beach" -> city="Beach"), which is an accepted, documented
        # imprecision here: county (the field that actually gates scope) is
        # sourced from DOR's own explicit county column in the common case,
        # not derived from this split.
        parts = rest.rsplit(None, 1)
        if len(parts) == 2:
            street, city = parts[0].title(), parts[1].title()
        else:
            street, city = rest.title(), None
    return street, city, state, zipc


def _row_to_listing(row: dict[str, Any], slug: str) -> Listing | None:
    name1 = (row.get("name1") or "").strip()
    name2 = (row.get("name2") or "").strip()
    name = name1 or name2
    if not name:
        return None
    balance = _money(row.get("balance"))
    filed = _parse_date(row.get("date_filed"))
    satisfied = row.get("date_satisfied")

    street, city, addr_state, zipc = _split_address(row.get("address"))
    state = (addr_state or "SC").upper()

    county_raw = (row.get("county") or "").strip()
    county = None if county_raw.lower() in ("", "statewide") else county_raw.title()
    if not county:
        # DOR's own "county" column is frequently the literal "Statewide"
        # (no county on file) -- fall back to the address city/state the same
        # way sc_dew_lien_registry.py does, rather than dropping the row.
        try:
            from ..._upstate_city_to_county import upstate_county_for
            from ..._coastal_city_to_county import coastal_county_for
            county = upstate_county_for(city, state) or coastal_county_for(city, state)
        except ImportError:
            county = None

    # Only emit a board row for a real, named NC/SC county (a tax lien is a
    # distress signal, in scope anywhere in NC/SC per the owner's standing
    # rule -- same gate sc_dew_lien_registry.py applies, see that file's own
    # comment for the 2026-09-29 rationale); a genuinely countyless row (no
    # county on file AND an unresolvable/out-of-state address) is dropped.
    if not (state == "SC" and county and in_scope_distressed(county, "SC")):
        return None

    lien_id = row.get("lien_id") or None
    desc = "SC DOR state tax lien"
    if lien_id:
        desc += f" #{lien_id}"
    if satisfied:
        desc += " (satisfied)"
    elif balance:
        desc += f" — balance ${balance:,.0f}"

    return Listing(
        source=slug,
        source_url=_SOURCE_URL,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county,
        city=city,
        zip_code=zipc,
        street_address=street,
        defendant=name,
        owner_name=name,
        judgment_amount=balance,
        foreclosure_process="lien",
        first_seen=filed or datetime.utcnow(),
        last_seen=datetime.utcnow(),
        description=desc,
        raw={
            "sc_state_tax_lien": {
                "owner": name,
                "balance": balance,
                "source": "sc_dor_tax_lien",
            },
            "sc_dor_tax_lien": {
                "lien_id": lien_id,
                "name2": name2 if name2 and name2 != name1 else None,
                "balance": balance,
                "date_filed": filed.isoformat() if filed else None,
                "date_satisfied": satisfied or None,
                "county_as_listed": county_raw or None,
                "raw_address": row.get("address") or None,
            },
        },
    )


async def _scrape_one_pair(page, first: str, last: str) -> list[dict[str, Any]]:
    """Fill First/Last Name, submit, and collect every result row across all
    pages for this one (first, last) pair. Returns raw row dicts (not yet
    Listings) keyed by the confirmed-live cell ids."""
    rows: list[dict[str, Any]] = []
    try:
        await page.fill(_SEL_FIRST_NAME, first)
        await page.fill(_SEL_LAST_NAME, last)
        await page.click(_SEL_SEARCH_BTN, force=True)
        # The results table's element id (#Dc-x1) is REUSED in place across
        # searches (confirmed live), so a plain wait_for_selector(visible)
        # resolves instantly off a PRIOR search's still-present table rather
        # than this search's real response -- networkidle is what actually
        # distinguishes "this search's AJAX traffic has settled" here.
        await page.wait_for_load_state("networkidle", timeout=_PAGE_LOAD_TIMEOUT_MS)
        # A no-match search shows no results table at all -- don't hang
        # waiting for one that will never appear.
        try:
            await page.wait_for_selector(_SEL_RESULTS_TABLE, timeout=3_000)
        except Exception:  # noqa: BLE001 - genuinely zero results for this pair
            return rows

        for _page_num in range(_MAX_PAGES_PER_SEARCH):
            row_els = await page.query_selector_all(f"{_SEL_RESULTS_TABLE} tbody tr")
            for i in range(1, len(row_els) + 1):
                suffix = f"-{i}"

                async def cell(prefix: str) -> str | None:
                    el = await page.query_selector(f"#{prefix}{suffix}")
                    if not el:
                        return None
                    txt = await el.inner_text()
                    return txt.strip() or None

                lien_id = await cell("Dc-n1")
                if not lien_id:
                    continue  # a stray/empty row template, not real data
                rows.append({
                    "lien_id": lien_id,
                    "name1": await cell("Dc-o1"),
                    "name2": await cell("Dc-p1"),
                    "address": await cell("Dc-q1"),
                    "county": await cell("Dc-r1"),
                    "balance": await cell("Dc-s1"),
                    "date_filed": await cell("Dc-u1"),
                    "date_satisfied": await cell("Dc-v1"),
                })

            next_el = await page.query_selector(_SEL_NEXT_PAGE)
            if not next_el:
                break
            disabled = await next_el.get_attribute("aria-disabled")
            cls = (await next_el.get_attribute("class")) or ""
            if disabled == "true" or "disabled" in cls.lower():
                break
            try:
                await next_el.click(force=True)
            except Exception:  # noqa: BLE001 - treat as "no more pages", not a
                break          # pair-level failure (e.g. a stale/detached
                                # element reference from an in-place DOM update)
            await page.wait_for_load_state("networkidle", timeout=_PAGE_LOAD_TIMEOUT_MS)

    except Exception as exc:  # noqa: BLE001 - one bad pair must not kill the run
        log.warning("sc_dor_lien.pair_failed", first=first, last=last, error=str(exc)[:200])
    return rows


class ScDorTaxLienScraper(BaseScraper):
    """SC DOR Tax Lien Registry — free statewide name-search, bounded
    (first, last) name-pair sweep (see module docstring for scope/limits)."""

    slug = "counties_sc.sc_dor_tax_lien"
    name = "SC DOR Tax Lien Registry"
    category = "tax_lien"
    timeout_s = 1200.0  # 150 pairs x a few seconds each, generous ceiling

    async def fetch(self) -> list[Listing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.warning("sc_dor_lien.no_playwright")
            return []

        all_rows: list[dict[str, Any]] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(_SEARCH_URL, timeout=30_000, wait_until="domcontentloaded")
                await page.click(_SEL_INDIVIDUAL_TAB)
                # The radio click fires an async "Recalc" round-trip (confirmed
                # live via network capture) that swaps in the First/Last Name
                # fields -- they don't exist in an interactable state until
                # that completes. A fixed short sleep here is exactly the
                # flaky-timing bug a real wait avoids: wait for the field
                # itself to become visible instead of guessing a delay.
                await page.wait_for_selector(_SEL_FIRST_NAME, state="visible", timeout=10_000)

                for last in _LAST_NAMES:
                    for first in _FIRST_NAMES:
                        pair_rows = await _scrape_one_pair(page, first, last)
                        if pair_rows:
                            log.info("sc_dor_lien.pair_done", first=first, last=last,
                                     rows=len(pair_rows))
                        all_rows.extend(pair_rows)
                        await page.wait_for_timeout(int(_SEARCH_BETWEEN_DELAY_S * 1000))
            except Exception as exc:  # noqa: BLE001
                log.warning("sc_dor_lien.fetch_failed", error=str(exc)[:200])
            finally:
                await browser.close()

        seen_ids: set[str] = set()
        results: list[Listing] = []
        for row in all_rows:
            lien_id = row.get("lien_id")
            if lien_id and lien_id in seen_ids:
                continue
            if lien_id:
                seen_ids.add(lien_id)
            li = _row_to_listing(row, self.slug)
            if li:
                results.append(li)

        log.info("sc_dor_lien.done", raw_rows=len(all_rows),
                  unique_liens=len(seen_ids), in_footprint=len(results))
        return results
