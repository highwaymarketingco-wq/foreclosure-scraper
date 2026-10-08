"""Anderson County SC Master in Equity — corrected URL + WordPress uploads PDF discovery.

FIXED 2026-10-03 (HERMES sec 8 per-source audit, batch 7). The live page
publishes a THIRD PDF family this module never fetched at all: a plain
"<Month>-<Day>-<Year>-Deficiency-Sale.pdf" / "...-Deficiency-Sale-1.pdf" link
(no "-List" and no "-Results" in the filename). It is neither of the two
types already handled -- `PDF_HREF_RE` requires "-Sale-List" and
`RESULTS_HREF_RE` requires the "-Results" suffix -- so this family was
silently invisible to both. Live-verified 2026-10-03: when a Master-in-Equity
sale's winning bid was the PLAINTIFF's own (no third party outbid them), SC
law reopens bidding for 30 more days, and Anderson publishes that reopened
roster here with the SAME columns as a Sale-List (case#/attorney/caption/
legal-desc/address) plus a "Plaintiff bid $X" floor the next bidder must
beat. The September 3, 2026 edition alone carries 4 real, un-withdrawn rows
(e.g. case 26-690, NewRez LLC v. Patrick Lahmann, 101 Clarendon Drive
Anderson, floor $301,500) -- real pending auctions with a real address,
never captured. GOTCHA caught live: the reopen date/time is printed in the
PDF's own BODY text ("...BIDDING WILL REOPEN ON THURSDAY, OCTOBER 1, 2026 @
11:00 AM") and does NOT always match the filename's nominal date -- the
May-7-2026-Deficiency-Sale-1.pdf's own body names its reopen date as APRIL
2, 2026, a full month off the filename. Sale-List safely trusts its filename
date because that convention was never seen to drift; this one does drift,
so `sale_date` here is parsed from the body's "REOPEN ON ... @ ..." line,
never assumed from the filename.

SOURCE-COMPLETENESS AUDIT, 2026-10-08 (the 10/7 extraction audit's open item "results/
deficiency PDFs, real sale time"), live page read the same day:
  * The August 4, 2026 results were posted as "August-4-2026-Sale-List-Results.pdf". Neither the
    results selector (href containing "Sale-Results") nor RESULTS_HREF_RE admitted the
    "Sale-List-Results" spelling, so its 9 priced rows never reached the sold-comps pool.
  * Results PDFs were capped at the newest 6 although the 180-day window held 9 on the page;
    the cap is now 12 (one sale list and one deficiency sale a month over the window), so the
    date window is what bounds it. Cost: up to 6 more PDF GETs per run.
  * Every Sale-List and results PDF states the sale hour in its header ("SALES ARE HELD AT
    THE ANDERSON COUNTY COURTHOUSE ... 11:00 AM"); sale_date used to be midnight of the
    filename date. The header's time is now applied (the filename date is unchanged).
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

PAGE_URL = "https://www.andersoncountysc.org/departments-a-z/master-in-equity/"

PDF_HREF_RE = re.compile(
    r"/wp-content/uploads/(\d{4})/(\d{2})/([A-Za-z]+)-(\d+)-(\d{4})-Sale-List(?:-\d+)?\.pdf",
    re.I,
)
# Anderson also publishes Sale-Results and Deficiency-Sale-Results PDFs
# with hammer prices — these feed the foreclosure_sold_comps pool.
RESULTS_HREF_RE = re.compile(
    r"/wp-content/uploads/(\d{4})/(\d{2})/"
    r"([A-Za-z]+)-(\d+)-(\d{4})-(?:Deficiency-Sale-Results|Sale-List-Results|Sale-Results)(?:-\d+)?\.pdf",
    re.I,
)
# Newest results PDFs read per run. The 180-day lookback holds about one sale list and one
# deficiency sale a month (~12); the old cap of 6 dropped the older half of that window.
RESULTS_PDF_CAP = 12
# Header line on every Sale-List / results PDF: "SALES ARE HELD AT THE ANDERSON COUNTY
# COURTHOUSE, THIRD FLOOR, COURTROOM #2, 11:00 AM."
_SALE_TIME_RE = re.compile(
    r"SALES\s+ARE\s+HELD\b[^.]{0,200}?\b(\d{1,2}):(\d{2})\s*([AP])\.?\s?M\b",
    re.I,
)


def _sale_clock(text: str) -> str | None:
    """The header's sale hour as Listing.sale_time ("HH:MM", 24-hour), or None."""
    at = _at_sale_time(datetime(2000, 1, 1), text)
    return f"{at.hour:02d}:{at.minute:02d}" if at and (at.hour or at.minute) else None


def _at_sale_time(sale_date: datetime | None, text: str) -> datetime | None:
    """`sale_date` at the hour the PDF's own header states; unchanged when none is stated."""
    if sale_date is None:
        return None
    m = _SALE_TIME_RE.search(text or "")
    if not m:
        return sale_date
    hour, minute = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3).upper() == "P":
        hour += 12
    if minute > 59:
        return sale_date
    return sale_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
# Sold-price patterns observed in Anderson results PDFs.
# Examples:
#   "To Third Party $228,500.00"
#   "To Plaintiff $164,000.00"
#   "Plaintiff bid $78,000.00"
ANDERSON_SOLD_RE = re.compile(
    r"(?:to\s+third\s+party|to\s+plaintiff|plaintiff\s+bid)\s*\$\s*"
    r"([\d,]+(?:\.\d{2})?)",
    re.I,
)
ANDERSON_NON_SALE_RE = re.compile(r"\b(WD|WD/BR|BR\b|withdrawn)", re.I)

# Upcoming Deficiency Sale (reopened bidding) -- distinct from both
# "-Sale-List" (first sale) and "-Deficiency-Sale-Results" (completed).
# The trailing "$" anchors against the "-Results" variant, which never
# matches here since "Results" sits between "Deficiency-Sale" and ".pdf".
DEFICIENCY_UPCOMING_HREF_RE = re.compile(
    r"/wp-content/uploads/(\d{4})/(\d{2})/([A-Za-z]+)-(\d+)-(\d{4})-Deficiency-Sale(?:-\d+)?\.pdf$",
    re.I,
)
# "...BIDDING WILL REOPEN ON THURSDAY, OCTOBER 1, 2026 @ 11:00 AM" -- the
# authoritative sale date for this PDF family; see module docstring for why
# the filename's own date cannot be trusted here the way Sale-List's can.
_REOPEN_DATE_RE = re.compile(
    r"REOPEN\s+ON\s+\w+,?\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})\s*@\s*(\d{1,2}):(\d{2})\s*([AP]M)",
    re.I,
)
CASE_RE = re.compile(r"\b\d{2,4}-\d{3,5}\b")
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+?\b(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\b\.?)",
    re.I,
)
# Deed-book / plat-book reference, e.g. "PB98@684", "PS2873@4", "PB1038@1&2".
_PLAT_REF = re.compile(r"\b([A-Z]{1,3}\d{1,5}@[\dA-Za-z&\-]+)\b")
_MH_RE = re.compile(r"\bMH\b|mobile\s+home", re.I)
# The caption line ("Plaintiff v. Defendant, et al."); everything between its
# end and the street address is the DESCRIPTION column (lot/acreage + plat ref).
_CAPTION_RE = re.compile(r"([A-Z][\w &.,'\-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'\-]{3,80})", re.I)
ATTORNEY_LEGEND = {
    "B&S": "Brock & Scott",
    "BCP": "Bell Carrington Price & Gregg",
    "BR": "Bankruptcy",
    "WD": "Withdrawn",
    "HSB": "Haynsworth Sinkler Boyd",
    "RPL": "Riley Pope & Laney",
    "RT": "Rogers Townsend",
    "S&C": "Scott & Corley",
}

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
          "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}


_ET_AL_RE = re.compile(r"\bet\s+al\.?,?", re.I)


def _legal_description(chunk: str,
                        addr_m: "re.Match[str] | None") -> tuple[str | None, PropertyKind]:
    """The DESCRIPTION column (lot/acreage + plat-book@page) sits between the
    '...et al.' end of the caption and the street address on both the
    Sale-List and Sale-Results PDFs. Neither was captured before — it is the
    strongest free-text legal description these rows carry, and a 'MH' /
    'Mobile Home' token in it is the only mobile-home signal on the page.
    The caption's defendant can wrap onto multiple PDF-extracted lines
    ("...Berry-\\nBurns, et al."), so anchor on the literal 'et al.' marker
    rather than the (necessarily single-line) plaintiff/defendant regex."""
    etal_m = _ET_AL_RE.search(chunk)
    cap_m = _CAPTION_RE.search(chunk) if not etal_m else None
    start = etal_m.end() if etal_m else (cap_m.end() if cap_m else 0)
    end = addr_m.start() if addr_m else len(chunk)
    if end <= start:
        return None, PropertyKind.UNKNOWN
    desc = re.sub(r"\s+", " ", chunk[start:end]).strip(" ,.-")
    kind = PropertyKind.MOBILE if (desc and _MH_RE.search(desc)) else PropertyKind.UNKNOWN
    return (desc or None), kind


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _parse_results_pdf(text: str, source_url: str, slug: str,
                       sale_date: datetime) -> list[Listing]:
    """Anderson Sale-Results / Deficiency-Sale-Results PDFs report past
    sales with hammer prices. Each row's price appears as 'To Third
    Party $X' / 'To Plaintiff $X' / 'Plaintiff bid $X'. Rows tagged
    WD or WD/BR didn't actually sell — skip those."""
    out: list[Listing] = []
    # Split on numbered-row markers ("1. 25-733", "2. 24-1352", etc.) —
    # the upcoming-sale-list parser splits on "<case#> <atty-code>" but
    # results PDFs sometimes have full attorney names ("Hutchens" 8 chars,
    # outside the original regex's [A-Z]{1,4} window). Splitting on the
    # numbered-row-with-case-number marker is more robust.
    chunks = re.split(r"(?=\b\d+\.\s+\d{2}-\d{3,5}\b)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        case_m = CASE_RE.search(chunk)
        if not case_m:
            continue
        if ANDERSON_NON_SALE_RE.search(chunk):
            continue  # withdrawn / bankruptcy — no sale happened
        sold_m = ANDERSON_SOLD_RE.search(chunk)
        if not sold_m:
            continue  # no price extractable — skip (would just be noise)
        try:
            price = float(sold_m.group(1).replace(",", ""))
        except ValueError:
            continue
        if not (100 <= price <= 10_000_000):
            continue

        addr_m = ADDR_RE.search(chunk)
        atty = None
        for code, full in ATTORNEY_LEGEND.items():
            if re.search(rf"\b{re.escape(code)}\b", chunk):
                atty = full
                break

        plaintiff = defendant = None
        m = re.search(r"([A-Z][\w &.,'-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'-]{3,80})", chunk)
        if m:
            plaintiff, defendant = m.group(1).strip(), m.group(2).strip().split("\n")[0]
        legal_desc, mh_kind = _legal_description(chunk, addr_m)

        out.append(Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=mh_kind,
            street_address=addr_m.group(1) if addr_m else None,
            state="SC",
            county="Anderson",
            case_number=case_m.group(0),
            plaintiff=plaintiff,
            defendant=defendant,
            trustee=atty,
            sale_date=sale_date,
            opening_bid=price,
            legal_description=legal_desc,
            description=chunk[:500],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={
                # Top-level so enrichment_foreclosure_sold_comps reads it
                # as confirmed hammer price (not opening-bid floor).
                "actual_sold_price": price,
                "anderson_mie_results": {
                    "source_pdf": source_url,
                    "raw_chunk_excerpt": chunk[:400],
                },
            },
        ))
    return out


def _parse_deficiency_upcoming_pdf(text: str, source_url: str, slug: str) -> list[Listing]:
    """Anderson's upcoming "Deficiency Sale" PDFs (never "-Results") reopen
    bidding for 30 days on a prior Master-in-Equity sale the PLAINTIFF's own
    bid won outright (no third party outbid them). Each row names that
    floor bid ("Plaintiff bid $X") the next bidder must beat -- a real
    pending auction with a real address, not a completed comp, so it is
    kept separate from `_parse_results_pdf`'s `actual_sold_price` convention."""
    out: list[Listing] = []
    sale_date = None
    m = _REOPEN_DATE_RE.search(text)
    if m:
        month_num = MONTHS.get(m.group(1).lower())
        if month_num:
            try:
                sale_date = datetime(int(m.group(3)), month_num, int(m.group(2)))
            except ValueError:
                sale_date = None

    chunks = re.split(r"(?=\b\d+\.\s+\d{2}-\d{3,5}\b)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        case_m = CASE_RE.search(chunk)
        if not case_m:
            continue
        if ANDERSON_NON_SALE_RE.search(chunk):
            continue  # withdrawn / bankruptcy -- no longer up for bid

        bid_m = ANDERSON_SOLD_RE.search(chunk)
        floor_bid = None
        if bid_m:
            try:
                floor_bid = float(bid_m.group(1).replace(",", ""))
            except ValueError:
                floor_bid = None

        addr_m = ADDR_RE.search(chunk)
        atty = None
        for code, full in ATTORNEY_LEGEND.items():
            if re.search(rf"\b{re.escape(code)}\b", chunk):
                atty = full
                break
        plaintiff = defendant = None
        pm = re.search(r"([A-Z][\w &.,'-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'-]{3,80})", chunk)
        if pm:
            plaintiff, defendant = pm.group(1).strip(), pm.group(2).strip().split("\n")[0]
        legal_desc, mh_kind = _legal_description(chunk, addr_m)

        out.append(Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=mh_kind,
            street_address=addr_m.group(1) if addr_m else None,
            state="SC",
            county="Anderson",
            case_number=case_m.group(0),
            plaintiff=plaintiff,
            defendant=defendant,
            trustee=atty,
            sale_date=sale_date,
            opening_bid=floor_bid,
            auction_status="deficiency_reopening",
            legal_description=legal_desc,
            description=chunk[:500],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={
                "anderson_mie_deficiency": {
                    "source_pdf": source_url,
                    "raw_chunk_excerpt": chunk[:400],
                    "note": "floor_bid is the PLAINTIFF's own bid (the floor "
                            "a new bidder must beat), not a completed sale "
                            "price -- do not feed to foreclosure_sold_comps.",
                },
            },
        ))
    return out


def _parse_pdf(text: str, source_url: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    today = datetime.utcnow()
    horizon = today + timedelta(days=120)
    cutoff = today - timedelta(days=2)

    # Each row: case# | atty | "Plaintiff v. Defendant" | description (lot, plat, address) | notes
    #
    # BUG FIXED: this used to split on "<case#> <atty-code>" requiring the
    # attorney column to be a short ALL-CAPS code (B&S, BCP, RPL...). Real
    # Sale-List PDFs also carry full-name attorneys (Cox, Driscoll, Hutchens,
    # Nourie, Shook) that don't match that shape, so the split silently
    # failed between those rows and swallowed every following row — up to
    # 16 of 17 parcels on one live PDF — into the PRECEDING chunk's text,
    # never emitted as their own Listing. _parse_results_pdf's own docstring
    # already names the fix ("splitting on the numbered-row-with-case-number
    # marker is more robust") but it was never ported back here. Live-verified
    # 2026-10-01 against the live October 6 2026 Sale List (17 real rows): the
    # old split produced only 2 usable chunks (one case number recovered per
    # merged blob); this split produces 16 (the 17th is a short page-footer
    # fragment with no case number, correctly dropped).
    chunks = re.split(r"(?=\b\d+\.\s+\d{2}-\d{3,5}\b)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        case_m = CASE_RE.search(chunk)
        if not case_m:
            continue
        addr_m = ADDR_RE.search(chunk)

        # Try to identify attorney by short code
        atty = None
        for code, full in ATTORNEY_LEGEND.items():
            if re.search(rf"\b{re.escape(code)}\b", chunk):
                atty = full
                break

        # Plaintiff v. Defendant
        plaintiff = defendant = None
        m = re.search(r"([A-Z][\w &.,'-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'-]{3,80})", chunk)
        if m:
            plaintiff, defendant = m.group(1).strip(), m.group(2).strip().split("\n")[0]
        legal_desc, mh_kind = _legal_description(chunk, addr_m)
        # Trailing special-condition notes ("SUBJECT TO FIRST MORTGAGE",
        # "BIDDING TO REOPEN IN 30 DAYS") sit after the address, before the
        # next numbered row — real signal, previously dropped entirely.
        notes = None
        if addr_m:
            tail = re.sub(r"\s+", " ", chunk[addr_m.end():]).strip(" ,.-")
            notes = tail or None

        out.append(
            Listing(
                source=slug,
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=mh_kind,
                street_address=addr_m.group(1) if addr_m else None,
                state="SC",
                county="Anderson",
                case_number=case_m.group(0),
                plaintiff=plaintiff,
                defendant=defendant,
                trustee=atty,
                legal_description=legal_desc,
                description=chunk[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "anderson_mie": {
                        "source_pdf": source_url,
                        "raw_chunk_excerpt": chunk[:400],
                        "legal_description": legal_desc,
                        "sale_notes": notes,
                    },
                },
            )
        )
    return out


class AndersonMasterInEquity(BaseScraper):
    slug = "counties_sc.anderson_master_in_equity"
    name = "Anderson County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 120.0
    expected_min_count = 5

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        today = datetime.utcnow()
        async with client(timeout=45.0) as c:
            try:
                r = await c.get(PAGE_URL)
                if r.status_code != 200:
                    return []
            except Exception:
                return []

            tree = HTMLParser(r.text)

            # ---- Sale-List PDFs (upcoming sales — the original behavior) ----
            best_pdf_url = None
            best_sale_date = None
            for a in tree.css("a[href*='Sale-List']"):
                href = a.attributes.get("href", "")
                m = PDF_HREF_RE.search(href)
                if not m:
                    continue
                month_name, day, year = m.group(3).lower(), int(m.group(4)), int(m.group(5))
                month_num = MONTHS.get(month_name)
                if not month_num:
                    continue
                try:
                    sale_date = datetime(year, month_num, day)
                except ValueError:
                    continue
                if sale_date < today - timedelta(days=30):
                    continue
                if best_sale_date is None or sale_date > best_sale_date:
                    best_sale_date = sale_date
                    best_pdf_url = (
                        href if href.startswith("http")
                        else f"https://www.andersoncountysc.org{href}"
                    )

            if best_pdf_url:
                try:
                    r2 = await c.get(best_pdf_url)
                    if r2.status_code == 200:
                        upcoming_text = _extract_pdf_text(r2.content)
                        listings = _parse_pdf(upcoming_text, best_pdf_url, self.slug)
                        sale_at = _at_sale_time(best_sale_date, upcoming_text)
                        clock = _sale_clock(upcoming_text)
                        for li in listings:
                            li.sale_date = sale_at
                            li.sale_time = li.sale_time or clock
                        out.extend(listings)
                except Exception:
                    pass

            # ---- Sale-Results / Deficiency-Sale-Results PDFs (past sales
            # with hammer prices — feed the foreclosure_sold_comps pool) ----
            results_pdfs: list[tuple[str, datetime]] = []
            # "-Results" admits every spelling seen: Sale-Results, Deficiency-Sale-Results and
            # Sale-List-Results (August 2026); RESULTS_HREF_RE decides.
            for a in tree.css("a[href*='-Results']"):
                href = a.attributes.get("href", "")
                m = RESULTS_HREF_RE.search(href)
                if not m:
                    continue
                month_name, day, year = m.group(3).lower(), int(m.group(4)), int(m.group(5))
                month_num = MONTHS.get(month_name)
                if not month_num:
                    continue
                try:
                    sale_date = datetime(year, month_num, day)
                except ValueError:
                    continue
                # Only include results within the foreclosure-sold-comps
                # lookback (180d) — older than that adds little signal.
                if sale_date < today - timedelta(days=180):
                    continue
                full_url = (
                    href if href.startswith("http")
                    else f"https://www.andersoncountysc.org{href}"
                )
                results_pdfs.append((full_url, sale_date))

            # Newest first; the 180-day window above is the real bound, RESULTS_PDF_CAP only
            # guards against a page that suddenly lists far more. A PDF linked twice is read once.
            results_pdfs = sorted(dict(results_pdfs).items(), key=lambda x: x[1], reverse=True)
            for url, sale_date in results_pdfs[:RESULTS_PDF_CAP]:
                try:
                    r3 = await c.get(url)
                    if r3.status_code != 200:
                        continue
                    text = _extract_pdf_text(r3.content)
                    if not text:
                        continue
                    clock = _sale_clock(text)
                    for li in _parse_results_pdf(text, url, self.slug,
                                                 _at_sale_time(sale_date, text)):
                        li.sale_time = li.sale_time or clock
                        out.append(li)
                except Exception:
                    continue

            # ---- Deficiency Sale PDFs (UPCOMING reopened bidding -- the
            # third PDF family, see module docstring) ----
            deficiency_pdfs: list[tuple[str, tuple[int, int]]] = []
            for a in tree.css("a[href*='Deficiency-Sale']"):
                href = a.attributes.get("href", "")
                m = DEFICIENCY_UPCOMING_HREF_RE.search(href)
                if not m:
                    continue  # the "-Results" variant never matches (see regex comment)
                full_url = (
                    href if href.startswith("http")
                    else f"https://www.andersoncountysc.org{href}"
                )
                deficiency_pdfs.append((full_url, (int(m.group(1)), int(m.group(2)))))

            # Sort by the upload path's own (year, month) -- a cheap proxy for
            # recency ahead of fetching (the real reopen date only comes from
            # the PDF body; see module docstring on the filename/body drift).
            deficiency_pdfs.sort(key=lambda x: x[1], reverse=True)
            cutoff = today - timedelta(days=45)
            for url, _ym in deficiency_pdfs[:4]:
                try:
                    r4 = await c.get(url)
                    if r4.status_code != 200:
                        continue
                    text = _extract_pdf_text(r4.content)
                    if not text:
                        continue
                    listings = _parse_deficiency_upcoming_pdf(text, url, self.slug)
                    # Drop editions whose OWN body resolves to a stale date --
                    # a resolved date is trustworthy evidence of staleness;
                    # an unresolved one (parse miss) is kept rather than
                    # silently dropped.
                    listings = [
                        li for li in listings
                        if li.sale_date is None or li.sale_date >= cutoff
                    ]
                    out.extend(listings)
                except Exception:
                    continue

        return out
