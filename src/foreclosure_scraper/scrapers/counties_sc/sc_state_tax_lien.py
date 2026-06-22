"""SC state tax-lien distressed owners — SCDOR Top Delinquent Taxpayers list.

SCDOR publishes (quarterly) the top delinquent individuals + businesses; EVERYONE
listed has a filed state tax lien (state liens centralized at SCDOR since Nov
2019). The list lives on MyDORWAY (a GenTax SPA), but it's a SINGLE rendered
page (not a per-owner search), so we stealth-render it ONCE per run and extract
the table:  Name | Street | City | State | Zip | County | Amount.

SC rows become distressed-owner leads (a large unpaid state tax debt + a filed
lien = motivated seller); the orchestrator's scope filter then keeps the
in-scope counties (and drops out-of-state debtors). Free, no per-owner queries,
no CAPTCHA/bot-detection bypass.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

# Only the individuals list: it's the residential-owner signal we want, and the
# ?link=delinquentbus deep-link is ignored by the SPA (it re-serves individuals),
# so including it would only create duplicates.
URLS = (
    ("https://mydorway.dor.sc.gov/?link=delinquentind", "individual"),
)
SOURCE_URL = "https://dor.sc.gov/delinquent-taxpayers"
_MONEY = re.compile(r"[\d,]+(?:\.\d{2})?")

# JS to pull the largest table's data rows out of the rendered MyDORWAY page.
_EXTRACT_JS = """() => {
    const tables=[...document.querySelectorAll('table')]; let best=null,n=0;
    for(const t of tables){const r=t.querySelectorAll('tr').length; if(r>n){n=r;best=t;}}
    if(!best) return [];
    const out=[];
    for(const tr of [...best.querySelectorAll('tr')].slice(1)){
        const c=[...tr.querySelectorAll('td')].map(td=>td.innerText.trim());
        if(c.length>=7) out.push(c);
    }
    return out;
}"""


async def _render_rows(url: str) -> list[list[str]]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []
    holder: dict = {}

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(4000)  # GenTax fills the grid via AJAX
        try:
            holder["rows"] = await page.evaluate(_EXTRACT_JS)
        except Exception:
            holder["rows"] = []

    try:
        await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=90000,
            page_action=page_action, solve_cloudflare=False)
    except Exception:
        return []
    return holder.get("rows") or []


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
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url, kind in URLS:
            for cells in await _render_rows(url):
                li = _to_listing(cells, kind, self.slug)
                if li:
                    out.append(li)
        return out
