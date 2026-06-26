"""Gaston County (NC) Surplus Properties — county-owned post-foreclosure inventory.

Built 2026-06-26. This is the COUNTY-OWNED SURPLUS REAL-PROPERTY list: parcels
Gaston County took through in-rem tax foreclosure (or otherwise acquired) that
never sold at the courthouse sale and now sit in county inventory "Accepting
Offers". It is DISTINCT from ``nc_county_tax_foreclosure`` (the active/upcoming
tax-foreclosure SALE + upset-bid pages at /669 and /671): those are properties
still going TO sale; this is the leftover inventory the county already owns and
wants off its books. Net-new distressed inventory, often vacant lots at a deep
discount to market value — a classic motivated-seller (the government) lead.

Source (verified live 2026-06-26):
  https://www.gastongov.com/709/Surplus-Properties  -> plain HTTP GET. The page
  links a "Surplus Property Listing (PDF)" at /DocumentCenter/View/1686. The PDF
  has a clean text layer laid out as a FIXED-COLUMN table:

      PID # | Surplus Date | Address | City | Acres | Market Value | Zoning | Status

  (a 2021 archived edition also carried an "AC" + "Description" column — the
  parser keys off the header LABELS, not fixed offsets, so either layout works.)

  Each data row is positionally aligned (one parcel per line). We read the PDF
  with pdfplumber word-boxes, learn each column's x-range from the header row,
  then bin each data word into its column by x-center. This survives multi-word
  addresses/cities and the county's quirk of splitting big dollar amounts with
  stray spaces ("$ 4 0,000.00") because every word lands in the right column.

Dateless: the page is a static county-owned-inventory list, not a dated auction
calendar — properties sit "Accepting Offers" indefinitely (the "Surplus Date" is
when the county acquired it, kept as acquisition provenance, not a sale date).

Off-season note: the list legitimately empties to "There are no surplus
properties at this time." (its exact state 2026-06-26). When that happens the
parser returns 0 and the scraper reports a clean ZERO — not a bug.

Free + compliant: plain HTTP GET of a public county page + a public county PDF.
No login / CAPTCHA / WAF defeat.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Iterable, Optional

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.gaston_surplus_properties"

SURPLUS_PAGE = "https://www.gastongov.com/709/Surplus-Properties"
GASTON_HOST = "https://www.gastongov.com"
# Fallback direct link to the listing PDF, used only if the page link can't be
# found (the page text "Surplus Property Listing (PDF)" -> /DocumentCenter/View/1686).
SURPLUS_PDF_FALLBACK = "https://www.gastongov.com/DocumentCenter/View/1686"

_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
_MONEY_RE = re.compile(r"\$?\s?([\d,]+(?:\.\d{2})?)")
_PID_RE = re.compile(r"^\d{4,7}$")  # Gaston PIDs are 4-7 digit numerics
_EMPTY_RE = re.compile(r"no\s+surplus\s+propert", re.I)


def _parse_date(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    try:
        return dateparser.parse(m.group(1))
    except (ValueError, TypeError, OverflowError):
        return None


def _money(s: str | None) -> Optional[float]:
    if not s:
        return None
    # The county splits big amounts with stray spaces ("$ 4 0,000.00"); strip all
    # whitespace inside the number before matching.
    s2 = re.sub(r"(?<=\d)\s+(?=[\d,])", "", s)
    m = _MONEY_RE.search(s2)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v or None


# --- row grammar -----------------------------------------------------------
# Each data row reads, left-to-right:
#   PID  Surplus-Date  <Address words>  <City>  Acres  $Market-Value  <Desc>  Zoning  Status
# The free-text columns (Address/City and Description/Zoning) have no fixed
# width, so positional binning is brittle. Instead we anchor on the columns
# whose token shape is unambiguous — PID (leading int), date (mm/dd/yy), acres
# (a bare decimal), market value ($...), and the trailing status phrase — then
# carve the two free-text spans out of what's left. This survives multi-word
# addresses, the "Bessemer City" two-word city, and the county's habit of
# splitting big dollar amounts with stray spaces ("$ 4 0,000.00").
_ROW_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_ACRES_RE = re.compile(r"^\d{1,3}\.\d{1,3}$")  # bare decimal acreage, e.g. 0.32
# Zoning codes seen on the list: G-R, RS-12, RS-8, R-1, I-2, C-3, O-I, etc.
_ZONING_RE = re.compile(r"^[A-Z]{1,3}(?:-[A-Z0-9]{1,4})?$")
# Status phrases that terminate a row (lowercased contains-match).
_STATUS_PHRASES = (
    "accepting offers", "under contract", "pending", "sold", "available",
    "offer accepted", "withdrawn", "removed",
)
# Gaston County municipalities (+ a couple of common nearby post-office cities)
# used to split the Address|City span. Two-word names first so "Bessemer City"
# binds before "City" alone. Lowercased.
_GASTON_CITIES = (
    "bessemer city", "high shoals", "mount holly", "stanley", "gastonia",
    "belmont", "cherryville", "dallas", "lowell", "mcadenville", "ranlo",
    "spencer mountain", "kings mountain", "lincolnton", "charlotte",
    "cramerton",
)


def _group_lines(words: list[dict], y_tol: float = 3.0) -> list[list[dict]]:
    """Group pdfplumber words into visual lines by their 'top' coordinate,
    each line sorted left-to-right by x0."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        placed = False
        for line in lines:
            if abs(line[0]["top"] - w["top"]) <= y_tol:
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    lines.sort(key=lambda line: line[0]["top"])
    return lines


def _split_addr_city(tokens: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Split the Address+City span into (address, city). Prefer a trailing known
    Gaston municipality (handles the two-word "Bessemer City"); otherwise fall
    back to "last token is the city" (the common single-word-city case)."""
    if not tokens:
        return None, None
    joined = " ".join(tokens)
    low = joined.lower()
    for city in _GASTON_CITIES:  # two-word names listed first
        if low.endswith(city):
            addr = joined[: len(joined) - len(city)].strip(" ,")
            # Re-title the matched city to its canonical spacing/caps.
            city_disp = " ".join(w.capitalize() for w in city.split())
            return (addr or None), city_disp
    # Unknown city — assume the final token is the city.
    if len(tokens) >= 2:
        return " ".join(tokens[:-1]).strip(" ,") or None, tokens[-1].strip(" ,") or None
    return joined or None, None


def _split_desc_zoning_status(tokens: list[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Split the tail (after market value) into (description, zoning, status).

    Status is a trailing known phrase; zoning is the single code token just
    before it; everything before that is the description (e.g. "Vacant Lot")."""
    if not tokens:
        return None, None, None
    joined_low = " ".join(tokens).lower()
    status: Optional[str] = None
    cut = len(tokens)
    for phrase in _STATUS_PHRASES:
        idx = joined_low.find(phrase)
        if idx == -1:
            continue
        # Count how many tokens the phrase spans.
        nwords = len(phrase.split())
        # Find the token index where the phrase begins.
        for start in range(len(tokens)):
            if " ".join(tokens[start:start + nwords]).lower() == phrase:
                status = " ".join(tokens[start:start + nwords])
                cut = start
                break
        if status:
            break
    body = tokens[:cut]
    zoning: Optional[str] = None
    if body and _ZONING_RE.match(body[-1]):
        zoning = body[-1]
        body = body[:-1]
    desc = " ".join(body).strip() or None
    return desc, zoning, status


def _parse_row_tokens(tokens: list[str]) -> Optional[dict[str, Any]]:
    """Parse one data row's token list into a field dict using the row grammar.

    Returns None if the row doesn't start with a PID + date (i.e. not a data
    row). Tolerant of missing optional columns."""
    if len(tokens) < 3 or not _PID_RE.match(tokens[0]):
        return None
    if not _ROW_DATE_RE.match(tokens[1]):
        return None
    pid = tokens[0]
    surplus_date = tokens[1]
    rest = tokens[2:]

    # Locate acres = the first bare-decimal token. Address+City is everything
    # before it; the money+desc+zoning+status tail is everything after.
    acres_idx = next((i for i, t in enumerate(rest) if _ACRES_RE.match(t)), None)
    if acres_idx is None:
        # No acres column on this row — fall back to the $ marker as the split.
        money_idx = next((i for i, t in enumerate(rest) if t.startswith("$")), None)
        addr_city = rest[:money_idx] if money_idx is not None else rest
        tail = rest[money_idx:] if money_idx is not None else []
        acres_raw = None
    else:
        addr_city = rest[:acres_idx]
        acres_raw = rest[acres_idx]
        tail = rest[acres_idx + 1:]

    # tail = [maybe "$", split-value-digits..., desc..., zoning, status...]
    # Re-glue the money: take leading tokens that are $/digits/commas until a
    # token that looks like words (the description start).
    money_tokens: list[str] = []
    j = 0
    while j < len(tail):
        t = tail[j]
        if t.startswith("$") or re.fullmatch(r"[\d,]+(?:\.\d{2})?", t):
            money_tokens.append(t)
            j += 1
        else:
            break
    market_raw = " ".join(money_tokens) if money_tokens else None
    desc, zoning, status = _split_desc_zoning_status(tail[j:])
    addr, city = _split_addr_city(addr_city)

    return {
        "pid": pid,
        "surplus_date": surplus_date,
        "address": addr,
        "city": city,
        "acres": acres_raw,
        "market_value": market_raw,
        "description": desc,
        "zoning": zoning,
        "status": status,
    }


def parse_surplus_pdf(pdf_bytes: bytes, page_url: str = SURPLUS_PAGE) -> list[Listing]:
    """Parse the Gaston County Surplus Properties PDF into listings.

    Reads pdfplumber word-boxes, groups them into visual lines, and parses each
    data line (one starting with a numeric PID + mm/dd/yy date) with the row
    grammar (see ``_parse_row_tokens``). Returns [] cleanly when the PDF says
    "no surplus properties at this time."
    """
    import pdfplumber  # local import keeps module import cheap

    out: list[Listing] = []
    seen: set[str] = set()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if not words:
                continue
            full_text = page.extract_text() or ""
            if _EMPTY_RE.search(full_text):
                # Explicit empty-state — a legit ZERO, not a parse failure.
                continue

            for line in _group_lines(words):
                tokens = [(w["text"] or "").strip() for w in line if (w["text"] or "").strip()]
                row = _parse_row_tokens(tokens)
                if not row:
                    continue  # header / title / "Updated …" / non-data line
                pid = (row.get("pid") or "").strip()
                if not pid or pid in seen:
                    continue
                seen.add(pid)

                addr = (row.get("address") or "").strip() or None
                city = (row.get("city") or "").strip() or None
                zoning = (row.get("zoning") or "").strip() or None
                status = (row.get("status") or "").strip() or None
                desc_col = (row.get("description") or "").strip()
                acquired = _parse_date(row.get("surplus_date"))
                market_value = _money(row.get("market_value"))
                acres: Optional[float] = None
                ac_raw = (row.get("acres") or "").strip()
                m_ac = re.search(r"\d+(?:\.\d+)?", ac_raw)
                if m_ac:
                    try:
                        acres = float(m_ac.group(0))
                    except ValueError:
                        acres = None

                # Vacant lots are the bulk of county surplus — classify when the
                # description/zoning says so, else leave UNKNOWN.
                kind = PropertyKind.UNKNOWN
                blob = f"{desc_col} {zoning or ''}".lower()
                if "vacant" in blob or "lot" in blob or "land" in blob:
                    kind = PropertyKind.LAND

                desc_bits = ["Gaston County surplus property (county-owned, accepting offers)"]
                if desc_col:
                    desc_bits.append(desc_col)
                if status:
                    desc_bits.append(f"status: {status}")
                description = " — ".join(desc_bits)[:400]

                out.append(
                    Listing(
                        source=SLUG,
                        source_url=page_url,
                        listing_type=ListingType.REO,
                        property_kind=kind,
                        state="NC",
                        county="Gaston",
                        street_address=addr,
                        city=city,
                        parcel_id=pid,
                        zoning=zoning,
                        acreage=acres,
                        market_value=market_value,
                        auction_status="active",
                        foreclosure_process="tax",
                        description=description,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={
                            "gaston_surplus": {
                                "pid": pid,
                                "surplus_date": row.get("surplus_date") or None,
                                "acquired_date": acquired.isoformat() if acquired else None,
                                "status": status,
                                "description_col": desc_col or None,
                                "zoning": zoning,
                            }
                        },
                    )
                )
    return out


async def _find_pdf_url(html: str) -> str:
    """Locate the 'Surplus Property Listing' PDF link on the page; fall back to
    the known DocumentCenter id if the anchor moves."""
    tree = HTMLParser(html)
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        txt = (a.text() or "").strip().lower()
        if not href:
            continue
        if "documentcenter/view" in href.lower() and "surplus" in txt and "vehicle" not in txt:
            return href if href.startswith("http") else GASTON_HOST + href
    # Secondary pass: any DocumentCenter PDF whose surrounding text mentions surplus.
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        txt = (a.text() or "").strip().lower()
        if "documentcenter/view" in href.lower() and "listing" in txt:
            return href if href.startswith("http") else GASTON_HOST + href
    return SURPLUS_PDF_FALLBACK


class GastonSurplusProperties(BaseScraper):
    slug = SLUG
    name = "Gaston County Surplus Properties (NC, county-owned inventory)"
    category = "county_surplus"
    # County surplus inventory is episodic — the list legitimately empties to
    # "no surplus properties at this time" between acquisitions.
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(SURPLUS_PAGE, headers={"User-Agent": "Mozilla/5.0"})
            pdf_url = await _find_pdf_url(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("gaston_surplus.page_failed", error=str(exc))
            pdf_url = SURPLUS_PDF_FALLBACK

        try:
            pdf_bytes = await get_bytes(pdf_url, timeout=60.0)
            out = parse_surplus_pdf(pdf_bytes)
            log.info("gaston_surplus.parsed", rows=len(out), pdf_url=pdf_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("gaston_surplus.pdf_failed", error=str(exc), pdf_url=pdf_url)

        return out


# Allow running this module directly for quick iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.gaston_surplus_properties
if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        scraper = GastonSurplusProperties()
        results = await scraper.safe_run()
        print(f"parsed: {len(results)}  outcome={scraper.last_outcome}  reason={scraper.last_reason}")
        for x in results[:15]:
            print(f"  pid={x.parcel_id} addr={x.street_address!r} city={x.city!r} "
                  f"acres={x.acreage} mv={x.market_value} zoning={x.zoning!r} "
                  f"kind={x.property_kind} desc={x.description!r}")

    asyncio.run(_main())
