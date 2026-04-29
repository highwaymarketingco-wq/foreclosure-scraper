"""Greenville SC Master in Equity sales roster.

Pipeline:
  1. GET /SCJD/courtrosters/disclaimer.aspx (collects ASP.NET hidden fields + cookie)
  2. POST same URL with ButtonAccept=Accept (sets cookie that grants access)
  3. GET /SCJD/courtrosters/RosterSelection.aspx (lists MO/DEFI rosters)
  4. For each RosterCode=MO link, GET RosterDetails.aspx
  5. Parse the standardRow / altRow <tr>s; keep only Sub Type = "Foreclosure 420"

The roster gives us: scheduled date, filed date, plaintiff (lender), defendant,
case#, TMS (parcel id), plaintiff/defendant attorneys, sale notes (bids,
upset bids, completed status). Address is filled by the GIS enrichment via TMS.
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

BASE = "https://www.greenvillecounty.org/SCJD/courtrosters"
DISCLAIMER = f"{BASE}/disclaimer.aspx"
SELECTION = f"{BASE}/RosterSelection.aspx"

ROSTER_LINK_RE = re.compile(
    r'href="(RosterDetails\.aspx\?CourtAgency=\d+(?:&|&amp;)RosterID=\d+(?:&|&amp;)RosterCode=MO\s*)"'
)
HIDDEN_RE = lambda name: re.compile(  # noqa: E731
    rf'name="{re.escape(name)}"[^>]*value="([^"]*)"'
)


def _hidden(html: str, name: str) -> str:
    m = HIDDEN_RE(name).search(html)
    return m.group(1) if m else ""


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


class GreenvilleMasterInEquity(BaseScraper):
    slug = "counties_sc.greenville_master_in_equity"
    name = "Greenville SC Master in Equity Sales Roster"
    category = "county_court"
    expected_min_count = 5
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=30.0, follow_redirects=True) as c:
            # 1. GET disclaimer to seed cookies + extract __VIEWSTATE etc.
            r = await c.get(DISCLAIMER, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return []
            vs = _hidden(r.text, "__VIEWSTATE")
            vsg = _hidden(r.text, "__VIEWSTATEGENERATOR")
            ev = _hidden(r.text, "__EVENTVALIDATION")
            if not vs:
                return []

            # 2. POST Accept
            r2 = await c.post(
                DISCLAIMER,
                data={
                    "__VIEWSTATE": vs,
                    "__VIEWSTATEGENERATOR": vsg,
                    "__EVENTVALIDATION": ev,
                    "ctl00$ContentPlaceHolder1$ButtonAccept": "Accept",
                },
                headers={"User-Agent": "Mozilla/5.0", "Referer": DISCLAIMER},
            )
            # 3. GET RosterSelection
            r3 = await c.get(SELECTION, headers={"User-Agent": "Mozilla/5.0", "Referer": DISCLAIMER})
            if r3.status_code != 200:
                return []
            raw_paths = ROSTER_LINK_RE.findall(r3.text)
            # Decode HTML entities + dedupe
            roster_paths = sorted(set(p.replace("&amp;", "&").strip() for p in raw_paths))
            # Limit to most-recent ~6 rosters (one per month) to avoid 30-min runs
            roster_paths = roster_paths[-6:]

            # 4-5. Pull each roster + parse foreclosure rows
            for path in roster_paths:
                roster_url = f"{BASE}/{path}"
                rd = await c.get(
                    roster_url,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": SELECTION},
                )
                if rd.status_code != 200:
                    continue
                out.extend(self._parse_roster(rd.text, roster_url))
        return out

    def _parse_roster(self, html: str, roster_url: str) -> list[Listing]:
        out: list[Listing] = []
        tree = HTMLParser(html)
        for tr in tree.css("tr.standardRow, tr.altRow"):
            cells = tr.css("td")
            if len(cells) < 10:
                continue
            sub_type = _clean(cells[8].html or "")
            if not sub_type.lower().startswith("foreclosure"):
                continue

            scheduled_raw = _clean(cells[1].html or "")
            start_time = _clean(cells[2].html or "")
            description = _clean(cells[4].html or "")
            filing_party = _clean(cells[5].html or "")
            filed_raw = _clean(cells[6].html or "")
            case_cell_html = cells[7].html or ""
            tms = _clean(cells[9].html or "")
            plaintiff_atty = _clean(cells[10].html or "") if len(cells) > 10 else ""
            defendant_atty = _clean(cells[11].html or "") if len(cells) > 11 else ""
            notes = _clean(cells[12].html or "") if len(cells) > 12 else ""

            # case# + caption: "<a href=...>2025CP2303497</a><br />LPP Mortgage Inc vs Shirley M Durham"
            m = re.search(r">(\d{4}CP\d{4,8})</a>", case_cell_html)
            case_number = m.group(1) if m else None
            caption_match = re.search(r"</a>\s*<br\s*/?>\s*(.+)", case_cell_html, re.S)
            caption = _clean(caption_match.group(1)) if caption_match else ""

            # plaintiff = filing party (strip -PLT)
            plaintiff = filing_party.replace("-PLT", "").strip() or None
            # defendant = right side of "vs"
            def_m = re.search(r"\bvs\.?\s+(.+?)(?:,?\s*defendant|,?\s*et al|$)", caption, re.I)
            defendant = def_m.group(1).strip() if def_m else None

            # detail URL on PublicIndex
            detail_m = re.search(r'href="([^"]+CaseDetails[^"]+)"', case_cell_html)
            source_url = detail_m.group(1) if detail_m else roster_url
            if source_url.startswith(".."):
                source_url = "https://www.greenvillecounty.org/SCJD/" + source_url.lstrip("./")
            source_url = source_url.replace("&amp;", "&")

            # Skip "Completed" rows — they've already been sold
            auction_status = "completed" if "Completed-" in notes else "active"

            # Parse scheduled + filed dates
            sale_date = None
            try:
                if scheduled_raw:
                    sale_date = dateparser.parse(scheduled_raw)
            except (ValueError, TypeError):
                pass

            opening_bid = None
            for amt_m in re.finditer(r"\$([\d,]+\.\d{2})", notes):
                try:
                    opening_bid = float(amt_m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass

            out.append(
                Listing(
                    source=self.slug,
                    source_url=source_url,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Greenville",
                    parcel_id=tms.strip().replace("  ", " ") or None,
                    sale_date=sale_date,
                    sale_time=start_time or None,
                    opening_bid=opening_bid,
                    plaintiff=plaintiff[:200] if plaintiff else None,
                    defendant=defendant[:200] if defendant else None,
                    case_number=case_number,
                    auction_status=auction_status,
                    description=(notes or description)[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"greenville_mie": {
                        "filing_party": filing_party,
                        "filed_date": filed_raw,
                        "plaintiff_attorney": plaintiff_atty,
                        "defendant_attorney": defendant_atty,
                        "notes": notes,
                        "tms": tms,
                    }},
                )
            )
        return out
