"""McMichael Taylor Gray — PowerBI iframe (NC + SC).

mtglaw.com/foreclosure-sales/ embeds a public PowerBI dashboard at
  https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1IiwidCI6IjEzZDFlNzhjLTgyNDgtNGVlYS04OWY3LWQzNGIzZWJkOGM3OSIsImMiOjN9

We scrape that URL directly (skipping the host page). The dashboard has a
state slicer (AL/FL/GA/MD/NC/NY/SC/TN/VA) and a virtualized data table.
Strategy: click NC, mouse-wheel-scroll the table until stagnant, collect
unique [role=row] tuples. Repeat for SC. Parse the row layout into
Listings.

Row layout (verified 2026-05-14):
  cells[0] "Select Row" (button text)
  cells[1] state code (NC, SC, ...)
  cells[2] county
  cells[3] sale_date (m/d/yyyy) or blank
  cells[4] MTG internal file#
  cells[5] NC SP case# (e.g. "25 SP000484-000") or blank for non-NC
  cells[6] full address ("STREET, CITY, STATE, ZIP")
  cells[7] bid ("$X") or blank

If the iframe layout changes (new column order, slicer aria-labels), the
NC click or row-cell index will silently miss — return 0 and log a warning.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

POWERBI_URL = (
    "https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1Ii"
    "widCI6IjEzZDFlNzhjLTgyNDgtNGVlYS04OWY3LWQzNGIzZWJkOGM3OSIsImMiOjN9"
)

ADDR_TAIL_RE = re.compile(
    r"^(.*?),\s*([A-Za-z .'-]+?),?\s+([A-Z]{2}),?\s+(\d{5})(?:-\d{4})?\s*$"
)
BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _parse_row(cells: list[str], slug: str) -> Listing | None:
    """Convert one [role=row] tuple into a Listing. Drop rows where the
    address doesn't parse as US-format STREET, CITY, ST, ZIP."""
    if len(cells) < 7:
        return None
    state = (cells[1] or "").strip().upper()
    if state not in ("NC", "SC"):
        return None
    county = (cells[2] or "").strip().replace(" County", "") or None
    if county:
        # PowerBI emits "Guilford-Forsyth" composites — split, keep the first
        county = county.split("-")[0].strip().title()
    raw_date = (cells[3] or "").strip()
    file_no = (cells[4] or "").strip() or None
    sp_no = (cells[5] or "").strip() or None
    addr_raw = (cells[6] or "").strip()
    bid_raw = (cells[7] if len(cells) > 7 else "").strip()

    if not addr_raw:
        return None
    m = ADDR_TAIL_RE.match(addr_raw)
    street = city = zip_code = None
    if m:
        street, city, _state_addr, zip_code = m.group(1), m.group(2), m.group(3), m.group(4)
    else:
        street = addr_raw  # let downstream parser try

    sale_date = None
    if raw_date:
        try:
            sale_date = dateparser.parse(raw_date)
        except (ValueError, TypeError):
            sale_date = None

    bid = None
    if bid_raw:
        bm = BID_RE.search(bid_raw)
        if bm:
            try:
                v = float(bm.group(1).replace(",", ""))
                if 100 <= v <= 5_000_000:
                    bid = v
            except ValueError:
                pass

    # NC SP case# is the legally-identifying number; prefer it for case_number,
    # fall back to MTG's internal file#.
    case_number = sp_no or file_no
    return Listing(
        source=slug,
        source_url=POWERBI_URL,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county,
        street_address=street,
        city=city,
        zip_code=zip_code,
        sale_date=sale_date,
        case_number=case_number,
        opening_bid=bid,
        description=f"MTG Law trustee sale: {state} {county or ''} {file_no or ''}".strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"mtg_file": file_no, "sp_case": sp_no} if (file_no or sp_no) else None,
    )


async def _fetch_filtered_state(state: str) -> list[list[str]]:
    """Drive PowerBI: load, click state slicer, mouse-wheel-scroll the
    virtualized table to load all rows. Returns the raw cell tuples.
    Empty list on any failure (parser handles []).
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    captured: dict[str, list[list[str]]] = {"rows": []}

    async def page_action(page):
        try:
            await page.wait_for_selector('div[role="row"]', timeout=60000)
        except Exception:
            return
        # PowerBI mounts the visuals progressively — give the table a beat
        # after first-row to finish laying out the slicer.
        await page.wait_for_timeout(15000)

        # Click the state-code option in the State slicer
        ok = await page.evaluate(
            """(state) => {
                const els = [...document.querySelectorAll('div[role="option"]')];
                for (const e of els) {
                    if (e.getAttribute('aria-label') === state) {
                        e.scrollIntoView({block: 'center'});
                        e.click();
                        return true;
                    }
                }
                return false;
            }""",
            state,
        )
        if not ok:
            return
        await page.wait_for_timeout(4000)

        bbox = await page.evaluate(
            """() => {
                const vcs = [...document.querySelectorAll('.visualContainer, .modernVisualOverlay')];
                for (const v of vcs) {
                    if ((v.innerText || '').includes('Select Row')) {
                        const r = v.getBoundingClientRect();
                        return {x: r.x, y: r.y, w: r.width, h: r.height};
                    }
                }
                return null;
            }"""
        )
        if not bbox:
            return
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2

        seen: set[tuple[str, ...]] = set()
        stagnant = 0
        for _ in range(80):  # cap loops; each is ~450ms = ~36s max
            rows = await page.evaluate(
                """() => {
                    return [...document.querySelectorAll('div[role="row"]')]
                        .map(r => [...r.querySelectorAll('[role=rowheader],[role=gridcell]')]
                            .map(c => c.innerText.trim()))
                        .filter(c => c.length > 1);
                }"""
            )
            before = len(seen)
            for r in rows:
                seen.add(tuple(r))
            if len(seen) == before:
                stagnant += 1
            else:
                stagnant = 0
            if stagnant >= 4:
                break
            await page.mouse.move(cx, cy)
            await page.mouse.wheel(0, 600)
            await page.wait_for_timeout(450)

        captured["rows"] = [list(r) for r in seen]

    try:
        await StealthyFetcher.async_fetch(
            POWERBI_URL,
            headless=True,
            network_idle=False,
            timeout=300000,
            page_action=page_action,
            solve_cloudflare=False,
        )
    except Exception:
        return []
    return captured["rows"]


class McMichaelTaylorGray(BaseScraper):
    slug = "law_firms.mcmichael_taylor_gray"
    name = "McMichael Taylor Gray (PowerBI iframe, stealth)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 720.0  # NC + SC = 2x ~5-min PowerBI loads

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("NC", "SC"):
            rows = await _fetch_filtered_state(state)
            for cells in rows:
                li = _parse_row(cells, self.slug)
                if li is not None:
                    out.append(li)
        return out
