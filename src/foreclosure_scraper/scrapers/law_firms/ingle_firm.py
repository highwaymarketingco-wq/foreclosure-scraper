"""The Ingle Firm (NC) — successor to Shapiro & Ingle substitute-trustee.

Discovered 2026-06-16. The old logs.com Shapiro & Ingle sales URL 404s;
the firm now publishes its NC foreclosure-sale docket at
theinglefirm.com/Sales.aspx as a clean HTML table:

  County | Original Sale Date/Time | Postponed Until Date/Time |
  Court Case Number | Property Address | Bid Amount

This is a high-value NC source: it carries the real Property Address AND
the Bid Amount in one row. Statewide; we keep only our 14 in-scope NC
counties. Plain HTTP, no bot protection.

FIX 2026-10-04: `fetch()` wrapped its entire request in `except Exception:
return []`, identical to a genuinely-empty docket. Live-verified the site's
own TLS certificate expired 2026-10-03 23:59:59 GMT (`openssl s_client`
against www.theinglefirm.com: `notAfter=Oct 3 23:59:59 2026 GMT`, one day
before this audit) -- every request has been failing with
`SSL: CERTIFICATE_VERIFY_FAILED` since. The old code swallowed that
`httpx.ConnectError` and returned a clean `[]`, which `BaseScraper.safe_run`
records as `OUTCOME_ZERO` ("ran clean but returned 0 rows") -- it never saw
the real error at all. `safe_run` already has the right classification for
this exact failure (`httpx.ConnectError` -> `OUTCOME_BLOCKED`,
`HTTPStatusError` -> `OUTCOME_BLOCKED`/`OUTCOME_ERROR` by status code); the
local try/except in `fetch()` was intercepting it before `safe_run` ever
got the chance. Removed the swallow and added `raise_for_status()` so both
a connection failure (bad cert, DNS, refused) and a bad HTTP status now
surface as the correct outcome instead of looking identical to a week with
no scheduled sales. This is NOT a compliance bypass: we still verify TLS
normally (no `verify=False`); an expired cert is the SITE's own outage to
fix, and the engine's job is to report it accurately, not hide it.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URL = "https://www.theinglefirm.com/Sales.aspx"

# In-scope NC counties (county cell looks like "Rutherford, NC").
# Mecklenburg/Madison/Yancey are in SCOPE_DENY_COUNTIES (pruned per owner
# direction), so they're excluded here to avoid emitting filtered rows.
IN_SCOPE = {
    "rutherford", "cleveland", "henderson", "polk", "gaston",
    "buncombe", "transylvania", "mcdowell", "lincoln",
    "mitchell", "burke",
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _money(s: str) -> float | None:
    m = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", s or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_html(html: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    if not html:
        return out
    tree = HTMLParser(html)
    for table in tree.css("table"):
            rows = table.css("tr")
            if not rows:
                continue
            header = [_clean(c.text()).lower() for c in rows[0].css("td,th")]
            if not any("case" in h for h in header) or not any("address" in h for h in header):
                continue
            # Map columns by header name (layout-drift resilient).
            idx = {}
            for i, h in enumerate(header):
                if "county" in h: idx["county"] = i
                elif "postponed" in h: idx["postponed"] = i
                elif "original sale" in h or ("sale" in h and "date" in h): idx.setdefault("orig", i)
                elif "case" in h: idx["case"] = i
                elif "address" in h: idx["addr"] = i
                elif "bid" in h: idx["bid"] = i

            for tr in rows[1:]:
                cells = [_clean(c.text()) for c in tr.css("td")]
                if len(cells) < max(idx.values(), default=0) + 1:
                    continue

                # This docket is MULTI-STATE (confirmed live 2026-10-01: AL rows
                # mixed in with NC), and the County cell is always "County, ST".
                # Several in-scope NC county NAMES collide with real counties in
                # other states this firm also covers (Rutherford County TN, Polk
                # County GA/TN, Lincoln County GA/TN/MS, Henderson County TN,
                # Burke/Mitchell County GA) — matching on the bare county name
                # alone would silently relabel an out-of-state property as NC.
                # Require the cell's own state suffix to actually be NC first.
                county_raw = cells[idx.get("county", 0)]
                cm = re.match(r"^(.*?),\s*([A-Za-z]{2})\s*$", county_raw)
                if cm:
                    county, row_state = cm.group(1).strip(), cm.group(2).upper()
                else:
                    county, row_state = county_raw.strip(), "NC"  # no suffix: assume NC (legacy shape)
                if row_state != "NC" or county.lower() not in IN_SCOPE:
                    continue

                case = cells[idx["case"]] if "case" in idx else ""
                addr_raw = cells[idx["addr"]] if "addr" in idx else ""
                if not case and not addr_raw:
                    continue

                # Address cell: "747 Hidden Springs Road, West Jefferson, NC 28694"
                street, city, zip_code = addr_raw, None, None
                am = re.match(r"\s*(.+?),\s*([A-Za-z .'-]+?),?\s*NC\s*(\d{5})?", addr_raw)
                if am:
                    street = am.group(1).strip()
                    city = am.group(2).strip()
                    zip_code = am.group(3)

                # Prefer the postponed date (the actual upcoming sale) when set.
                sale_raw = ""
                if "postponed" in idx and cells[idx["postponed"]]:
                    sale_raw = cells[idx["postponed"]]
                elif "orig" in idx:
                    sale_raw = cells[idx["orig"]]
                sale_date = None
                if sale_raw:
                    try:
                        sale_date = dateparser.parse(sale_raw)
                    except (ValueError, TypeError, OverflowError):
                        pass

                opening_bid = _money(cells[idx["bid"]]) if "bid" in idx else None

                out.append(
                    Listing(
                        source=slug,
                        source_url=URL,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county=county,
                        street_address=street or None,
                        city=city,
                        zip_code=zip_code,
                        case_number=case or None,
                        sale_date=sale_date,
                        opening_bid=opening_bid,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"ingle_firm": {"county_raw": county_raw, "bid_raw": cells[idx["bid"]] if "bid" in idx else None}},
                    )
                )
    return out


class IngleFirm(BaseScraper):
    slug = "law_firms.ingle_firm"
    name = "The Ingle Firm (NC trustee)"
    category = "law_firm"
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        # No local try/except here on purpose: BaseScraper.safe_run already
        # classifies a connection failure / bad HTTP status correctly
        # (OUTCOME_BLOCKED / OUTCOME_ERROR, see the module docstring's
        # 2026-10-04 fix). Swallowing it here made a real site-side outage
        # look identical to a genuinely empty docket.
        async with client(timeout=40.0, follow_redirects=True) as c:
            r = await c.get(URL, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return _parse_html(r.text, self.slug)
