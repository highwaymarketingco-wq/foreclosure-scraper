"""SC state tax-lien distressed owners — SCDOR Top Delinquent Taxpayers list.

SCDOR publishes (quarterly) the top delinquent individuals + businesses; EVERYONE
listed has a filed state tax lien (state liens centralized at SCDOR since Nov
2019). The list lives on MyDORWAY (a "Fast" GenTax-style SPA, not Salesforce),
and we stealth-render it to extract the table: Name | Street | City | State |
Zip | County | Amount.

AUDITED 2026-10-01 -- TWO confirmed gaps closed, both real completeness
misses, not cosmetic:

1. PAGINATION. The grid shows "Page 1 of 3" (confirmed live: 95-ish rows on
   page 1 alone) and the old code read page 1 only, via one
   ``page.evaluate()`` with no interaction. Measured live the same day: all
   three pages together return 227 individual rows (vs. the ~80 SC rows the
   single-page read produced) -- roughly 3x. The grid paginates behind a
   FAST-framework ``a.TablePageLinkNext`` link (title "Go to the next page")
   rather than a plain URL; the in-browser driver below clicks it and waits
   for the table's own content to change (not just a fixed sleep) before
   reading the next page, so a slow AJAX response can't be read as "no
   change" and cut the sweep short.

2. THE BUSINESS TAB WAS NEVER READ. The old docstring claimed "the
   ?link=delinquentbus deep-link is ignored by the SPA (it re-serves
   individuals)" and concluded business debtors were unreachable. That is
   true of the URL deep-link, but the SAME page exposes a
   "Top Delinquent Businesses" IN-PAGE tab (a
   ``label.FastComboButtonItem_BUS`` control) that swaps the active grid
   in place -- no navigation, no new fetch, same session. Confirmed live:
   clicking it surfaces a second 3-page, 224-row grid with the identical
   7-column shape. Businesses are real leads here on the same footing
   qpaybill/catalis already treat LLC owners (e.g. "2ND CHANCE LLC") as
   valid delinquent-roll entities -- this module now captures them as
   ``kind="business"``.

Both grids coexist in the DOM at once (only one is visually active), so the
in-page JS filters every DOM query to VISIBLE elements (``el.offsetParent``)
before picking "the" table / "the" pagination controls / "the" Next link --
otherwise a stale, hidden copy of the other tab's grid or pager can be read
by mistake (confirmed live: ``document.querySelectorAll('table')`` alone
returns both tables at once, and the inactive one sometimes has MORE rows
left over from a prior page than the freshly-switched-to tab's page 1).

SC rows become distressed-owner leads (a large unpaid state tax debt + a filed
lien = motivated seller); the orchestrator's scope filter then keeps the
in-scope counties (and drops out-of-state debtors). Free, no per-owner
queries, no CAPTCHA/bot-detection bypass -- same compliant stealth-render
pattern this codebase already uses elsewhere (e.g. counties_sc.sc_county_rosters).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SOURCE_URL = "https://dor.sc.gov/delinquent-taxpayers"
#: The individuals tab is what the page loads by default at this URL. The
#: businesses tab is reached in-page (see _DRIVER_JS), not via a second URL --
#: ``?link=delinquentbus`` re-serves individuals (confirmed live, unchanged).
START_URL = "https://mydorway.dor.sc.gov/?link=delinquentind"
_MONEY = re.compile(r"[\d,]+(?:\.\d{2})?")

#: Hard ceiling on pages per tab. The live list has 3; this leaves headroom
#: for the quarterly list to grow without needing a code change, while still
#: bounding a pathological pager that never reports "last page".
MAX_PAGES_PER_TAB = 12

# In-page driver: reads every page of the Individuals grid, switches to the
# Business tab, reads every page of that grid too. Runs entirely inside the
# browser (one page.evaluate call) so there is no Python<->page round trip
# between a click and the next read, which is where a fixed-sleep approach
# would either race ahead of a slow AJAX response or waste time on a fast one.
_DRIVER_JS = """async () => {
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    const visible = (el) => !!(el && el.offsetParent);

    function activeTable() {
        const tables = [...document.querySelectorAll('table')].filter(visible);
        let best = null, n = 0;
        for (const t of tables) {
            const r = t.querySelectorAll('tr').length;
            if (r > n) { n = r; best = t; }
        }
        return best;
    }
    function extractRows() {
        const t = activeTable();
        if (!t) return [];
        const out = [];
        for (const tr of [...t.querySelectorAll('tr')].slice(1)) {
            const c = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
            if (c.length >= 7) out.push(c);
        }
        return out;
    }
    function pageInfo() {
        const el = [...document.querySelectorAll('.TablePageCurrent')].find(visible);
        if (!el) return null;
        const m = (el.innerText || '').match(/Page (\\d+) of (\\d+)/);
        return m ? [parseInt(m[1]), parseInt(m[2])] : null;
    }
    async function collectAllPages(maxPages) {
        let all = [];
        for (let i = 0; i < maxPages; i++) {
            await sleep(300);
            const rows = extractRows();
            all = all.concat(rows);
            const info = pageInfo();
            const next = [...document.querySelectorAll('.TablePageLinkNext')].find(visible);
            if (!next) break;
            if (info && info[0] >= info[1]) break;
            const before = rows.map(r => r.join('|')).join(';');
            next.click();
            // Wait for the table's own content to change rather than a fixed
            // sleep: a slow AJAX page-load must not be read as "no next page".
            let changed = false;
            for (let w = 0; w < 20; w++) {
                await sleep(250);
                const now = extractRows().map(r => r.join('|')).join(';');
                if (now && now !== before) { changed = true; break; }
            }
            if (!changed) break;  // pager stalled -- stop rather than loop on stale data
        }
        return all;
    }
    function clickTab(name) {
        const labels = [...document.querySelectorAll('label.FastComboButtonItem')];
        const target = labels.find(l => (l.innerText || '').trim() === name);
        if (target) target.click();
        return !!target;
    }

    const individual = await collectAllPages(%(max_pages)d);
    let business = [];
    if (clickTab('Top Delinquent Businesses')) {
        await sleep(1800);
        business = await collectAllPages(%(max_pages)d);
    }
    return {individual, business};
}""" % {"max_pages": MAX_PAGES_PER_TAB}


async def _render_rows() -> dict[str, list[list[str]]]:
    """Returns {"individual": [...], "business": [...]}, each a list of
    [name, street, city, state, zip, county, amount] rows across ALL pages."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return {"individual": [], "business": []}
    holder: dict = {}

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(4000)  # GenTax fills the grid via AJAX
        try:
            holder["result"] = await page.evaluate(_DRIVER_JS)
        except Exception:
            holder["result"] = {}

    try:
        await StealthyFetcher.async_fetch(
            START_URL, headless=True, network_idle=True, timeout=150000,
            page_action=page_action, solve_cloudflare=False)
    except Exception:
        return {"individual": [], "business": []}
    result = holder.get("result") or {}
    return {
        "individual": result.get("individual") or [],
        "business": result.get("business") or [],
    }


def _to_listing(cells: list[str], kind: str, slug: str) -> Listing | None:
    # Name | Street | City | State | Zip | County | Amount
    name, street, city, state, zipc, county, amount = (list(cells) + [""] * 7)[:7]
    if (state or "").strip().upper() != "SC":
        return None  # drop out-of-state debtors
    amt = None
    m = _MONEY.search(amount or "")
    if m:
        try:
            amt = float(m.group(0).replace(",", ""))
        except ValueError:
            pass
    desc = f"SC state tax lien — top delinquent {kind}"
    if amt:
        desc += f" (balance ${amt:,.0f})"
    return Listing(
        source=slug, source_url=SOURCE_URL,
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county=(county or "").strip().title() or None,
        city=(city or "").strip().title() or None,
        zip_code=(zipc or "").strip() or None,
        street_address=(street or "").strip() or None,
        defendant=(name or "").strip() or None,
        judgment_amount=amt,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"sc_state_tax_lien": {"kind": kind, "balance": amt, "owner": name}},
    )


class SCStateTaxLien(BaseScraper):
    slug = "counties_sc.sc_state_tax_lien"
    name = "SC State Tax Lien (SCDOR Top Delinquent)"
    category = "state_lien"
    expected_min_count = 0   # quarterly list; in-scope-county overlap varies
    requires_render = True
    # Raised from 240s: reading both tabs across up to MAX_PAGES_PER_TAB pages
    # each (3 pages/tab measured live) needs more wall clock than a single
    # one-page read did.
    timeout_s = 420.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple] = set()
        result = await _render_rows()
        for kind, rows in (("individual", result["individual"]),
                           ("business", result["business"])):
            for cells in rows:
                li = _to_listing(cells, kind, self.slug)
                if li is None:
                    continue
                # The grid's pager is read-and-advance, not offset-paged, so a
                # slow page swap could in principle re-read a row; de-dupe on
                # the identity the data itself provides rather than trust the
                # pager never repeats.
                key = (kind, li.defendant, li.street_address, li.judgment_amount)
                if key in seen:
                    continue
                seen.add(key)
                out.append(li)
        log.info("sc_state_tax_lien.done",
                 individual_raw=len(result["individual"]),
                 business_raw=len(result["business"]),
                 sc_leads=len(out))
        return out
