"""NC public legal notices via ncnotices.com (NC Press Association aggregator).

The site is ASP.NET WebForms with session-based URLs (the path includes a
session token like /(S(...))/default.aspx). Direct HTTP fails because of
__VIEWSTATE / session handshake. Scrapling stealth-renders + drives the
search form to extract notices in three categories:

  - Foreclosure-related (sale, trustee, upset bid, tax foreclosure)
  - Divorce-related (service-by-publication summons, contested divorces)
  - Probate-related (Notice to Creditors / Estate filings)

Free, no auth required. Each query category produces its own ListingType:
  - FORECLOSURE_SALE / TAX_SALE / SHERIFF_SALE (existing)
  - DIVORCE_NOTICE (new)
  - PROBATE_NOTICE (new)

Probate + divorce notices often LACK a street address (they reference
the deceased's name + county only). The address-required filter is
relaxed for those categories — county + named-defendant is enough to
emit a useful lead. Address can be backfilled later via owner-name
cross-reference against tax records.
"""
from __future__ import annotations

import os
import pathlib
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.ncnotices.com/"

# Debug HTML dumps land here. Picked up by the patch-run-scrapers
# workflow as a build artifact (`debug-html-{run_id}`) so we can
# inspect the actual rendered HTML when the parser returns 0 listings.
# Set NCNOTICES_DEBUG_DUMP=0 to disable.
DEBUG_DUMP_DIR = pathlib.Path(
    os.environ.get("NCNOTICES_DEBUG_DUMP_DIR", "debug")
)
DEBUG_DUMP_ENABLED = os.environ.get("NCNOTICES_DEBUG_DUMP", "1") == "1"


def _dump_html_for_debug(html: str, query: str, category: str, url: str) -> None:
    """Save the raw HTML response to debug/ when the parser returns 0
    listings with substantial body. Triggered only on the failure-but-
    not-empty path so we collect signal, not noise."""
    if not DEBUG_DUMP_ENABLED or not html or len(html) < 1000:
        return
    try:
        DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        safe_query = re.sub(r"[^A-Za-z0-9_-]", "_", query)[:50]
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        out = DEBUG_DUMP_DIR / f"ncnotices_{category}_{safe_query}_{ts}.html"
        # Prepend a comment so we know which URL this came from.
        out.write_text(
            f"<!-- query={query!r} category={category!r} url={url!r} -->\n{html}",
            encoding="utf-8",
        )
        log.info(
            "ncnotices.html_dumped",
            path=str(out), query=query, category=category, size=len(html),
        )
    except Exception as exc:
        log.warning("ncnotices.html_dump_fail", error=str(exc)[:200])

# Each tuple = (query_string, category). Category drives classifier
# + relevance filter strictness.
QUERIES: tuple[tuple[str, str], ...] = (
    # Foreclosure / tax-sale (existing — most-relevant-first)
    ("foreclosure sale", "foreclosure"),
    ("substitute trustee", "foreclosure"),
    ("upset bid", "foreclosure"),
    ("tax foreclosure", "foreclosure"),
    # Divorce: service-by-publication summons + contested-divorce notices.
    # NCGS §1A-1 Rule 4(j1) requires publication when the spouse can't
    # be found — those are the most-distressed subset (often involves
    # property abandonment).
    ("summons divorce", "divorce"),
    ("notice of service divorce", "divorce"),
    ("absolute divorce service publication", "divorce"),
    # Probate: Notice to Creditors is legally required (NCGS §28A-14-1)
    # when an estate is opened. Published in newspaper of record.
    ("notice to creditors", "probate"),
    ("executor estate", "probate"),
    ("administrator estate", "probate"),
    ("estate of", "probate"),
)

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
COUNTY_RE = re.compile(
    r"\b(Mecklenburg|Buncombe|Henderson|Gaston|Cleveland|Rutherford|Polk|"
    r"Burke|McDowell|Lincoln|Madison|Yancey|Mitchell|Transylvania)\s+County\b",
    re.I,
)
# Named-defendant / decedent extractor for divorce + probate notices.
# Patterns: "Estate of JOHN SMITH", "JOHN SMITH, deceased", "JANE DOE,
# Plaintiff vs. JOHN DOE, Defendant".
NAMED_PARTY_RE = re.compile(
    r"(?:estate of|in the matter of|deceased[:\s]*|defendant[:\s]*)\s*"
    r"([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})",
    re.I,
)


# Classifier categories → ListingType + foreclosure-relevance keywords.
# Probate + divorce categories use looser keyword sets since their
# notice text rarely contains the word "foreclosure".
_CATEGORY_RULES = {
    "foreclosure": {
        "type": ListingType.FORECLOSURE_SALE,
        "keywords": ("foreclosure", "trustee sale", "tax foreclosure",
                     "tax sale", "upset bid", "substitute trustee"),
        "require_address": True,
    },
    "divorce": {
        "type": ListingType.DIVORCE_NOTICE,
        "keywords": ("divorce", "summons", "service of process",
                     "absolute divorce", "dissolution"),
        "require_address": False,
    },
    "probate": {
        "type": ListingType.PROBATE_NOTICE,
        "keywords": ("notice to creditors", "executor", "administrator",
                     "estate of", "deceased", "letters testamentary",
                     "personal representative"),
        "require_address": False,
    },
}


def _classify(text: str, category: str) -> ListingType:
    """Refine ListingType based on text content. Defaults to the
    category's primary type, but downgrades to TAX_SALE / SHERIFF_SALE
    when the text matches more-specific foreclosure subtypes."""
    t = text.lower()
    if category == "foreclosure":
        if "tax foreclosure" in t or "tax sale" in t:
            return ListingType.TAX_SALE
        if "sheriff" in t:
            return ListingType.SHERIFF_SALE
        return ListingType.FORECLOSURE_SALE
    if category == "divorce":
        return ListingType.DIVORCE_NOTICE
    if category == "probate":
        return ListingType.PROBATE_NOTICE
    return ListingType.UNKNOWN


def _matches_category(text: str, category: str) -> bool:
    """Quick relevance filter — does the snippet contain the category's
    expected keywords?"""
    rules = _CATEGORY_RULES.get(category, {})
    keywords = rules.get("keywords", ())
    lower = text.lower()
    return any(k in lower for k in keywords)


async def _search_one(query: str, category: str) -> list[Listing]:
    """Drive ncnotices.com's ASP.NET search form via Scrapling.

    Site behavior (verified 2026-05-08): Default.aspx is a SPA that shows
    'Please Wait...' loading until JS finishes. Results land in
    #searchResults div. Strategy:

      1. Land at Default.aspx + the search query as URL param
         (the form auto-submits when keyword= is set)
      2. Wait up to 45s for #searchResults to populate (or for the
         'Please Wait' indicator to disappear)
      3. Fall back to form-fill + submit-button click if URL approach
         doesn't return results
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("ncnotices.scrapling_missing")
        return []

    async def page_action(page):
        # ncnotices.com production HTML inspection (2026-05-08 dump):
        #   keyword input id = ctl00_ContentPlaceHolder1_as1_txtSearch
        #   search button   = ctl00_ContentPlaceHolder1_as1_btnGo (NOT btnSearch)
        #   reset button    = ctl00_ContentPlaceHolder1_as1_btnReset
        #   results panel   = ctl00_ContentPlaceHolder1_WSExtendedGridNP1_updateWSGrid
        #   empty-state msg = "Please use the Advanced Search Menu to find public notices."
        # URL ?keyword= param does NOT auto-trigger search; the form has to
        # be submitted via __doPostBack on btnGo. The keyword input has an
        # onkeypress that calls WebForm_FireDefaultButton on btnGo, so
        # pressing Enter on the input triggers the postback.
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        # Fill keyword input — exact ID from production dump
        filled = False
        keyword_selectors = (
            "input#ctl00_ContentPlaceHolder1_as1_txtSearch",
            "input[id$='_txtSearch']",
            "input[name$='$txtSearch']",
            "input[id*='txtSearch' i]",
        )
        for sel in keyword_selectors:
            try:
                await page.fill(sel, query, timeout=8000)
                filled = True
                break
            except Exception:
                continue
        if not filled:
            return

        # Submit via Enter on the input (triggers WebForm_FireDefaultButton
        # → __doPostBack on btnGo). Fall back to clicking btnGo directly.
        submitted = False
        try:
            await page.press(
                "input#ctl00_ContentPlaceHolder1_as1_txtSearch", "Enter"
            )
            submitted = True
        except Exception:
            pass
        if not submitted:
            for sel in (
                "#ctl00_ContentPlaceHolder1_as1_btnGo",
                "input[id$='_btnGo']",
                "input[name$='$btnGo']",
            ):
                try:
                    await page.click(sel, timeout=4000)
                    submitted = True
                    break
                except Exception:
                    continue
        if not submitted:
            try:
                await page.evaluate(
                    "() => __doPostBack('ctl00$ContentPlaceHolder1$as1$btnGo','')"
                )
            except Exception:
                pass

        # Wait for the actual result panel content to change away from
        # the empty-state placeholder. We watch the lblEmptyDataText span
        # (which IS the empty-state) — when it's gone or the panel grows
        # past the empty-state size (~200 chars), results have rendered.
        empty_msg = "Please use the Advanced Search Menu"
        try:
            await page.wait_for_function(
                f"""() => {{
                    const p = document.getElementById('ctl00_ContentPlaceHolder1_WSExtendedGridNP1_updateWSGrid');
                    if (!p) return false;
                    const html = p.innerHTML || '';
                    return html.length > 1000 && !html.includes({empty_msg!r});
                }}""",
                timeout=30000,
            )
        except Exception:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    # Try multiple landing URL shapes — different ncnotices.com
    # deployments respond to different param names + paths.
    candidate_urls = [
        f"{BASE}Search.aspx?keyword={query.replace(' ', '+')}",
        f"{BASE}Default.aspx?keyword={query.replace(' ', '+')}",
        BASE,  # form-fill fallback
    ]

    last_html_size = 0
    for url in candidate_urls:
        try:
            result = await StealthyFetcher.async_fetch(
                url, headless=True, network_idle=True, timeout=90000,
                page_action=page_action,
            )
        except Exception as exc:
            log.warning("ncnotices.fetch_fail", query=query, url=url, error=str(exc)[:200])
            continue

        body = getattr(result, "body", b"")
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
        listings = _parse_results_html(html, query, category) if html else []
        last_html_size = max(last_html_size, len(html or ""))
        log.info(
            "ncnotices.attempt_done",
            query=query, category=category,
            url=url, html_size=len(html), listings=len(listings),
        )
        # Short-circuit on success
        if listings:
            return listings
        # Short-circuit on substantial HTML — means the URL loaded a real
        # page, just no results for this query. Trying alternate URLs won't
        # help and would 3x the runtime budget. (Empty page < 5KB suggests
        # WAF block / 503; keep trying alternates.)
        if len(html or "") > 5000:
            # Save HTML so we can inspect what the parser missed
            _dump_html_for_debug(html, query, category, url)
            return []

    return []


def _parse_results_html(html: str, query: str, category: str) -> list[Listing]:
    """Parse ncnotices.com search results HTML into Listing objects.
    Pure function — no network — so this is unit-testable."""
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    rules = _CATEGORY_RULES.get(category, {})
    require_address = rules.get("require_address", True)

    # Production ncnotices.com renders results inside the
    # WSExtendedGridNP1_updateWSGrid panel. Result-card classes seen
    # there include `searchResultRow`/`pnlResult`/etc. Empty-state
    # has class `pnlInfo` with the "Please use Advanced Search" text.
    grid_panel = tree.css_first("#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_updateWSGrid")
    cards = []
    if grid_panel is not None:
        # Within the result panel: <tr> rows are the most likely result
        # containers (ASP.NET GridView default). Also try the variants
        # other templates use.
        cards = grid_panel.css(
            "tr.searchResultRow, tr[class*='Row'], "
            "div.searchResultRow, div.publicNoticeResult, "
            "div.NoticeContainer, div[class*='notice'], "
            "li.searchResultRow"
        )
    if not cards:
        cards = tree.css(
            "div.search-result, div.result, article.notice, "
            "tr.searchResultRow, div[class*='notice'], div.NoticeContainer, "
            "div.publicNoticeResult"
        )
    if not cards:
        # Fallback: paragraphs/divs containing category-relevant content
        addr_re = re.compile(
            r"\d+\s+[A-Z][\w .'-]+(?:Road|Rd|Street|St|Drive|Dr|Avenue|Ave|"
            r"Lane|Ln|Court|Ct|Way|Place|Pl|Boulevard|Blvd)",
            re.I,
        )
        candidates = tree.css("p, li, div, td")
        cards = []
        for c in candidates:
            t = c.text().lower()
            # For foreclosure: require addr. For probate/divorce:
            # require keyword + county or named party.
            if require_address:
                if _matches_category(t, category) and addr_re.search(c.text()):
                    cards.append(c)
            else:
                if _matches_category(t, category) and (
                    COUNTY_RE.search(c.text()) or NAMED_PARTY_RE.search(c.text())
                ):
                    cards.append(c)
        cards = cards[:200]

    for card in cards:
        text = card.text(strip=True)
        if not text or len(text) < 60:
            continue
        lower = text.lower()
        if any(s in lower for s in (
            "login", "subscribe", "navigation menu", "search results",
            "12 months are available", "use the search", "sort by",
            "filter by", "select a category", "page of",
        )):
            continue
        if not _matches_category(text, category):
            continue

        addr_m = ADDR_RE.search(text)
        if require_address and not addr_m:
            continue
        if not require_address and not (
            COUNTY_RE.search(text) or NAMED_PARTY_RE.search(text)
        ):
            continue

        a = card.css_first("a[href]")
        href = (a.attributes.get("href", "") if a else "") or BASE
        if href.startswith("/"):
            href = f"https://www.ncnotices.com{href}"

        county_m = COUNTY_RE.search(text)
        county = county_m.group(1).title() if county_m else None
        named_m = NAMED_PARTY_RE.search(text)
        named_party = named_m.group(1).strip().title() if named_m else None

        # Dedup by best-available signature
        sig = (addr_m.group(1) if addr_m else (
            f"{named_party}|{county}" if named_party else text[:80]
        )).strip().lower()
        if sig in seen:
            continue
        seen.add(sig)

        raw_blob = {
            "ncnotices": {
                "query": query,
                "category": category,
                "snippet": text[:800],
            }
        }
        if named_party:
            raw_blob["ncnotices"]["named_party"] = named_party

        out.append(
            Listing(
                source="public_notices.ncnotices",
                source_url=href,
                listing_type=_classify(text, category),
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr_m.group(1) if addr_m else None,
                state="NC",
                county=county,
                description=text[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw=raw_blob,
            )
        )

    return out


class PublicNoticeNC(BaseScraper):
    slug = "public_notices.ncnotices"
    name = "NC Notices (NC Press Association)"
    category = "public_notice"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 900.0  # 11 queries × ~80s each

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_overall: set[str] = set()
        for q, cat in QUERIES:
            try:
                listings = await _search_one(q, cat)
                for li in listings:
                    sig = (li.street_address or
                           ((li.raw or {}).get("ncnotices", {}).get("named_party") or "")
                           or li.description[:80]).lower()
                    if sig in seen_overall:
                        continue
                    seen_overall.add(sig)
                    out.append(li)
                log.info(
                    "ncnotices.query_done",
                    query=q, category=cat, count=len(listings),
                )
            except Exception as exc:
                log.warning("ncnotices.query_failed", query=q, error=str(exc)[:200])
        return out
