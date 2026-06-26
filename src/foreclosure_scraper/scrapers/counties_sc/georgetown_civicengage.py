"""Georgetown County (SC, coastal) — three county-hosted CivicEngage PDFs.

Built 2026-06-26 for the COASTAL track. Georgetown's Master-in-Equity HEARING
docket is already reached via publicindex (``sc_coastal_rosters.py``), but the
county ALSO publishes three foreclosure/tax-distress PDFs on its own CivicEngage
site DocumentCenter — none of which are on publicindex. This scraper pulls all
three into one source, each free + compliant (plain HTTP PDF, pdfplumber, no
login/CAPTCHA/WAF defeat):

(a) FORFEITED-LAND-COMMISSION list  — /415/Forfeited-Land-Commission
    The "2026 FLC LIST" PDF: parcels the county already took at tax sale and now
    offers over-the-counter. Section-banded ("MOBILE HOMES" then "LAND"), each row:
        Group Name TMS# Description TaxSaleDate OpeningBid
        5028 Baker Louise (H) 01-0442-029-03-00.001 1973 12x45 Panoramic 11/1/2021 $901.77
    The TaxSaleDate is the HISTORICAL sale the parcel was forfeited at (not an
    upcoming auction), so FLC rows are emitted DATELESS (no sale_date) per spec —
    they're standing OTC inventory, a strong owner-in-distress / vacant-land signal.

(b) TAX-SALE list  — /408/Tax-Sale
    The "2025 Tax Sale List (PDF)" — delinquent parcels headed to the annual tax
    sale. The PDF has a main REAL-ESTATE block and a trailing MOBILE-HOME block:
        Main: TaxPayerName TaxMapNumber CountyItemNumber
              ANDREWS LARRY A 05-0017-114-00-00 2024-1010302-0
        MH:   TaxPayerName TaxMapNumber(+item)
              BELLAMY TASHIA HOLMES 03-0463-0060301
    The same PDF re-lists PropertyDesc / PropAddress1 in SEPARATE, positionally
    unaligned column blocks that extract_text() can't join back to a parcel row,
    so we DON'T fabricate an address from them — name + TMS is the reliable,
    load-bearing pair. Dateless per spec (annual sale date isn't on the list).

(c) MASTER-IN-EQUITY foreclosure-sale rosters  — /223/Foreclosure-Sales
    Monthly "MASTER'S AUCTION LIST" PDFs (one per sale month, labelled "May 2026"
    etc.). These HAVE sale dates — the auction month is the document's own month
    label, so sale_date is set to the 1st of that month (month-level; the precise
    sale day is the county's monthly Master sale). Each row, TMS-anchored:
        2025-746 Loan Funder, LLC 42 Lakeshore Dr. 04-0133-037-00-00 462 Lakeshore Dr., PI ...
    i.e. CaseNumber Plaintiff Defendant TMS Address <compliance/rate/deficiency>.
    Some monthly docs are uploaded as .xls (OLE) rather than PDF; those are
    skipped (magic-byte guarded) — pdfplumber only sees real PDFs.

DocumentCenter link discovery: each landing page is scraped for /DocumentCenter/
links, then routed by label/url. FLC keeps the "FLC LIST" doc and drops the
"FLC-Procedures" doc; Tax keeps the "Tax Sale List" doc and drops Policy /
Statutes / "sold at the ... Tax Sale" RESULTS docs; MIE keeps every monthly
roster (most-recent few) and parses each. Robust to the View-id changing each
year because we match on label text, not a hard-coded id.

All rows are TMS-anchored (the Georgetown TMS is the one bare dashed parcel token
per line), so variable owner/party wording and run-together columns don't break
the parse. parcel_id is set on every row; the downstream SCDOT enrichment chain
geocodes it so the oceanfront scope gate (Georgetown is out-of-footprint, admitted
only near-beach) can place each lead.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.gtcountysc.gov"
FLC_PAGE = f"{BASE}/415/Forfeited-Land-Commission"
TAX_PAGE = f"{BASE}/408/Tax-Sale"
MIE_PAGE = f"{BASE}/223/Foreclosure-Sales"

# A Georgetown TMS is the load-bearing anchor on every parcel row. Forms seen
# live 2026-06-26 across the three PDFs:
#   02-0414-012-04-00.006        (FLC / tax-sale real-estate, dotted suffix)
#   05-0017-114-00-00            (tax-sale real-estate, no suffix)
#   04-0187B-027-01-00           (MIE, alpha block segment)
#   04-0100-01-01-01             (MIE, short 2-digit segments)
#   03-9980-002-37-82            (FLC W/S parcels)
# Block-2 may carry a trailing letter; segment widths vary, so we allow 2-4
# digits per dashed segment after the first two and an optional .NNN suffix.
_TMS_RE = re.compile(
    r"\b\d{2}-\d{4}[A-Z]?-\d{2,3}-\d{2,3}-\d{2,3}(?:\.\d{1,3})?\b"
)
# Tax-sale county item number, e.g. 2024-1010302-0 / 2024-993016-0.
_ITEM_RE = re.compile(r"\b(20\d{2}-\d{3,7}-\d)\b")
# Mobile-home tax block: TMS has the item digits concatenated, e.g.
# 03-0463-0060301 (dashed prefix then a long digit run, no second dash group).
_MH_TMS_RE = re.compile(r"\b(\d{2}-\d{4}[A-Z]?-\d{7,})\b")
# MIE case number, e.g. 2025-746 / 2024-954 (4-digit year, 1-5 digit sequence).
_CASE_RE = re.compile(r"\b(20\d{2}-\d{1,5})\b")
# Money / opening bid.
_MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# A historical tax-sale date on FLC rows: M/D/YYYY.
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

# Month-name -> number, for deriving the MIE sale month from the doc label.
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_LABEL_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)[\s\-_]*?(20\d{2})",
    re.I,
)

# Lines on the PDFs that are headers / banners / instructions, never parcel rows.
_SKIP_MARKERS = (
    "georgetown county", "forfeited land commission", "master's auction list",
    "group name", "taxpayername", "taxmapnumber", "countyitemnumber",
    "propertytype", "propertydesc", "propaddress", "how to look up",
    "go to www", "click on", "in the blue field", "proceed to site",
    "accept the statement", "this is the page", "case number", "included with",
    "mobile homes", "real estate st",  # 'REAL ESTATE' desc-column lines start here
)


def _is_skip(line: str) -> bool:
    low = (line or "").strip().lower()
    if len(low) < 6:
        return True
    return any(m in low for m in _SKIP_MARKERS)


def _pdf_text(data: bytes) -> str:
    """Extract all-page text via pdfplumber. Returns '' on any parse error."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:  # noqa: BLE001
        log.warning("georgetown.pdf_parse_fail", error=str(exc)[:160])
        return ""


def _clean_name(s: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", (s or "")).strip(" .,-")
    return s or None


def parse_flc(text: str, url: str) -> list[Listing]:
    """Parse the Forfeited-Land-Commission list. Each parcel row is
    `Group Name TMS Description TaxSaleDate OpeningBid` (section banners and the
    'how to look up' instructions are non-TMS and skipped). Emitted DATELESS —
    the date on the row is the historical forfeiture sale, not an upcoming one."""
    out: list[Listing] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if _is_skip(line):
            continue
        tm = _TMS_RE.search(line)
        if not tm:
            continue
        tms = tm.group(0)
        if tms in seen:
            continue
        seen.add(tms)
        before = line[: tm.start()].strip()
        after = line[tm.end():].strip()
        # Drop a leading group/item number from the name half.
        name = _clean_name(re.sub(r"^\s*\d{3,5}\s+", "", before))
        # Opening bid = last $ on the row; description = after-TMS minus the
        # trailing date + bid.
        bid = None
        bm = list(_MONEY_RE.finditer(after))
        if bm:
            try:
                bid = float(bm[-1].group(1).replace(",", ""))
            except ValueError:
                pass
        desc = after
        dm = _DATE_RE.search(after)
        if dm:
            desc = after[: dm.start()].strip()
        elif bm:
            desc = after[: bm[-1].start()].strip()
        desc = _clean_name(desc)
        out.append(Listing(
            source="counties_sc.georgetown_civicengage",
            source_url=url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Georgetown",
            parcel_id=tms,
            defendant=name,                    # forfeited owner
            opening_bid=bid,
            legal_description=desc,
            description=re.sub(r"\s+", " ", line)[:300],
            foreclosure_process="tax",
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw={"georgetown_civicengage": {"doc": "flc", "line": line[:200]}},
        ))
    return out


def parse_tax(text: str, url: str) -> list[Listing]:
    """Parse the annual Tax-Sale list. Two blocks:
      * real-estate: `TaxPayerName TMS CountyItemNumber`
      * mobile-home: `TaxPayerName TMS(+item)` (item concatenated onto the TMS)
    Name + TMS is the reliable pair; the PDF's separate desc/address columns are
    not positionally joinable, so we don't fabricate an address. Dateless."""
    out: list[Listing] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if _is_skip(line):
            continue
        # Mobile-home block first (TMS with item run concatenated, no item col).
        mh = _MH_TMS_RE.search(line)
        item = _ITEM_RE.search(line)
        tm = _TMS_RE.search(line)
        tms = None
        item_no = None
        before = line
        if tm and item:
            tms = tm.group(0)
            item_no = item.group(1)
            before = line[: tm.start()].strip()
        elif mh:
            tms = mh.group(1)
            before = line[: mh.start()].strip()
        else:
            continue
        if tms in seen:
            continue
        seen.add(tms)
        name = _clean_name(before)
        if not name:
            continue
        out.append(Listing(
            source="counties_sc.georgetown_civicengage",
            source_url=url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Georgetown",
            parcel_id=tms,
            defendant=name,                    # delinquent taxpayer
            description=("Georgetown tax sale"
                         + (f" item {item_no}" if item_no else "")
                         + f" — {name}")[:300],
            foreclosure_process="tax",
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw={"georgetown_civicengage": {"doc": "tax", "item": item_no,
                                            "line": line[:200]}},
        ))
    return out


def _sale_date_from_label(label: str, url: str) -> Optional[datetime]:
    """Derive the MIE sale month from the doc's link label (or url slug),
    e.g. 'May 2026' -> 2026-05-01. Month-level — the precise day is the
    county's monthly Master's sale."""
    for hay in (label or "", url or ""):
        m = _MONTH_LABEL_RE.search(hay.replace("%20", " "))
        if m:
            mo = _MONTHS.get(m.group(1).lower())
            try:
                return datetime(int(m.group(2)), mo, 1) if mo else None
            except (ValueError, TypeError):
                return None
    return None


def parse_mie(text: str, url: str, label: str = "") -> list[Listing]:
    """Parse one monthly MASTER'S AUCTION LIST roster. TMS-anchored: case# +
    plaintiff/defendant sit before the TMS, the street address after it (up to
    the 'NN days in Note' compliance column). sale_date comes from the doc's
    month label (these rosters HAVE sale dates, per spec)."""
    out: list[Listing] = []
    seen: set[str] = set()
    sale_date = _sale_date_from_label(label, url)
    for raw in (text or "").splitlines():
        line = raw.strip()
        if _is_skip(line):
            continue
        tm = _TMS_RE.search(line)
        if not tm:
            continue
        tms = tm.group(0)
        if tms in seen:
            continue
        seen.add(tms)
        before = line[: tm.start()].strip()
        after = line[tm.end():].strip()

        case_number = None
        cm = _CASE_RE.search(before)
        if cm:
            case_number = cm.group(1)
        # Party blob = text after the case# and before the TMS. We can't reliably
        # split undelimited plaintiff/defendant, so keep the blob in description
        # and surface a best-effort plaintiff (text right after the case#).
        party_blob = before
        plaintiff = None
        if case_number:
            party_blob = before[before.find(case_number) + len(case_number):].strip()
        if party_blob:
            plaintiff = _clean_name(party_blob[:120])

        # Address = run after the TMS up to the compliance / rate / deficiency
        # column ("NN days in Note", "Yes"/"No"). Cut at the first such marker.
        address = after
        cut = re.search(r"\b\d+\s*days?\s+in\b|\bin\s+Note\b", address, re.I)
        if cut:
            address = address[: cut.start()].strip()
        address = _clean_name(address)
        # Reject a non-address blob (must start with a digit or 'Lot'/known kind).
        if address and not re.match(r"^\d|^lot\b|^unit\b|^pt\b|^tract\b", address, re.I):
            # Keep it in description but don't claim it as a street address.
            address = None

        out.append(Listing(
            source="counties_sc.georgetown_civicengage",
            source_url=url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Georgetown",
            parcel_id=tms,
            street_address=address,
            sale_date=sale_date,
            plaintiff=plaintiff,
            case_number=case_number,
            foreclosure_process="judicial",
            auction_status="active",
            description=re.sub(r"\s+", " ", line)[:400],
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw={"georgetown_civicengage": {"doc": "mie", "label": label[:60],
                                            "line": line[:200]}},
        ))
    return out


def _discover_docs(html: str, base: str) -> list[tuple[str, str]]:
    """Return [(absolute_url, label_text)] for every DocumentCenter link on a
    landing page, in page order."""
    out: list[tuple[str, str]] = []
    tree = HTMLParser(html)
    for a in tree.css("a[href*='DocumentCenter']"):
        href = a.attributes.get("href", "")
        if not href:
            continue
        out.append((urljoin(base, href), a.text(strip=True) or ""))
    return out


# Most-recent monthly MIE rosters to parse (covers the live + upcoming sales).
MAX_MIE_ROSTERS = 4


class GeorgetownCivicEngage(BaseScraper):
    slug = "counties_sc.georgetown_civicengage"
    name = "Georgetown County (SC) FLC + Tax Sale + Master-in-Equity PDFs"
    category = "county_tax"
    timeout_s = 120.0
    requires_render = False
    # FLC + tax lists are large and standing; the floor flags a regression
    # (all three docs gone / parser broken) without false-alarming on a quiet
    # MIE month.
    expected_min_count = 5

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=60.0) as c:
            # --- (a) FLC list ---------------------------------------------
            try:
                r = await c.get(FLC_PAGE)
                if r.status_code == 200:
                    for url, label in _discover_docs(r.text, FLC_PAGE):
                        low = (label + " " + url).lower()
                        if "procedure" in low or "bid-app" in low or "bid app" in low:
                            continue
                        if "flc" not in low and "forfeit" not in low:
                            continue
                        data = await self._get_pdf(c, url)
                        if data:
                            rows = parse_flc(_pdf_text(data), url)
                            out.extend(rows)
                            log.info("georgetown.flc_ok", url=url, count=len(rows))
                            break  # one FLC list doc
            except Exception as exc:  # noqa: BLE001
                log.warning("georgetown.flc_fail", error=str(exc)[:160])

            # --- (b) Tax-Sale list ----------------------------------------
            try:
                r = await c.get(TAX_PAGE)
                if r.status_code == 200:
                    for url, label in _discover_docs(r.text, TAX_PAGE):
                        low = (label + " " + url).lower()
                        if any(k in low for k in
                               ("policy", "procedure", "statute", "sold at",
                                "results", "result")):
                            continue
                        if "tax sale list" not in low and "tax-sale-list" not in low:
                            continue
                        data = await self._get_pdf(c, url)
                        if data:
                            rows = parse_tax(_pdf_text(data), url)
                            out.extend(rows)
                            log.info("georgetown.tax_ok", url=url, count=len(rows))
                            break  # one tax-sale list doc
            except Exception as exc:  # noqa: BLE001
                log.warning("georgetown.tax_fail", error=str(exc)[:160])

            # --- (c) Master-in-Equity monthly rosters ---------------------
            try:
                r = await c.get(MIE_PAGE)
                if r.status_code == 200:
                    docs = _discover_docs(r.text, MIE_PAGE)
                    # Rank by the month/year in the label (newest first) so we
                    # parse the most relevant sale months and cap run time.
                    def _key(d: tuple[str, str]):
                        sd = _sale_date_from_label(d[1], d[0])
                        return sd or datetime.min
                    docs.sort(key=_key, reverse=True)
                    parsed = 0
                    for url, label in docs:
                        if "procedure" in (label + url).lower():
                            continue
                        data = await self._get_pdf(c, url)
                        if not data:
                            continue
                        rows = parse_mie(_pdf_text(data), url, label)
                        out.extend(rows)
                        log.info("georgetown.mie_ok", url=url, label=label,
                                 count=len(rows))
                        parsed += 1
                        if parsed >= MAX_MIE_ROSTERS:
                            break
            except Exception as exc:  # noqa: BLE001
                log.warning("georgetown.mie_fail", error=str(exc)[:160])

        # De-dupe across all three docs by parcel (a parcel headed to tax sale
        # can also sit on the FLC list); keep the first (richer) sighting.
        deduped: dict[str, Listing] = {}
        for li in out:
            k = li.dedupe_key()
            if k in deduped:
                deduped[k] = deduped[k].merge(li)
            else:
                deduped[k] = li
        result = list(deduped.values())
        log.info("georgetown.done", count=len(result), raw=len(out))
        return result

    async def _get_pdf(self, c, url: str) -> Optional[bytes]:
        """GET a DocumentCenter doc and return its bytes only if it's a real
        PDF (some monthly MIE docs are uploaded as .xls — magic-byte guarded)."""
        try:
            r = await c.get(url)
        except Exception:
            return None
        if r.status_code != 200:
            return None
        data = r.content
        if data[:4] != b"%PDF":
            log.info("georgetown.skip_non_pdf", url=url, magic=str(data[:4]))
            return None
        return data
