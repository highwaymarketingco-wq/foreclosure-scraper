"""Florence County SC — Delinquent Tax Sale list.

Florence County's Office of Delinquent Tax publishes the annual tax-sale
lists as PDFs linked off its office page (NOT the county homepage):

    https://www.florenceco.org/offices/delinquent-tax/

2026-09-10 verified live: the page announces the sale date ("scheduled to be
conducted ... on Monday, October 5th, 2026") and links two lists hosted on S3:

    .../DelinquentTax/2026/2026 Tax Sale List Real 9-01-26.pdf        (26 pp)
    .../DelinquentTax/2026/2026 Tax Sale List Mobile Homes 9-1-26.pdf ( 6 pp)

PDF layout (fixed-width columns, verified 2026):
    TAXPAYER                       MAP-BLOCK-PARCEL/LOCATION            LOTS ACRES BLDGS DISTRICT
    A-1 STORAGE LLC              S  1012-01-215  KINGSBURY PARK L 15P&16   1        4    10
    ADJABENG MEISHA A            S 90046-09-013  S CALHOUN DR              1        1    11

A "**CURRENT OWNER:" line precedes the row it belongs to and repeats the TMS —
the taxpayer of record can be a decades-stale name, so the current owner is
captured too.

The LOCATION column is a plat/lot description ("KINGSBURY PARK L 15P&16",
"COIT & DARLINGTON"), not a mailable street address, so street_address is only
set when the text actually starts with a house number. Otherwise the TMS
(parcel_id) is the resolver's handle.

Free, public, no login, no CAPTCHA.
Slug: counties_sc.florence_delinquent_tax
Category: county_tax
ListingType: TAX_SALE

AUDITED 2026-10-03: the PDF's own trailing LOTS/ACRES/BLDGS/DISTRICT columns
(visible in the header dump above) were being stripped off `rest` by
`_TAIL_NUMS_RE` and thrown away -- never written to any field. These are
NOT reliably separable by counting whitespace-delimited numbers from the
right: a 2-number tail is "LOTS DISTRICT" on one row (e.g. "1  10") and
"ACRES DISTRICT" on another (e.g. "9  20") with no text difference between
the two shapes -- only each number's X position on the page (preserved by
pypdf's text flow as inconsistent run-to-run character offsets, confirmed
live NOT usable for fixed-width slicing) tells them apart. Fixed via a
SEPARATE pdfplumber word-coordinate pass (`_extract_tail_columns`): read the
header's own LOTS/ACRES/BLDGS/DISTRICT word x0/x1 once per PDF to get each
column's x-range, then for every other page word that's purely numeric,
bucket it by which column's x-range its x0 falls in, keyed by the TMS token
on the same visual line (words grouped by rounded `top`). Live-verified
2026-10-03 against the real 2026 files: 714/715 "Real" rows and 263/263
"Mobile Homes" rows recovered their tail columns (spot-checked 5 rows
against a manual read of the PDF text/word dump -- exact match, e.g. TMS
395-02-003 -> acres=9, district=20, no lots/bldgs, matching "ANDREWS GAIL
KATHY ... OFF HWY 57     9     20" on the live page). `BLDGS` is NEVER
written as a literal "0" in this export (confirmed: value set is only
{None, "1".."8"}) -- blank means no building, the same sparse-omission
convention Dillon's PAPER.xlsx uses for its own Buildings column. On the
"Real" list only (not "Mobile Homes", which is already force-tagged
MOBILE), a missing `bldgs` now sets `property_kind=LAND` -- live: 357/715
Real rows (50.0%) carry no BLDGS value.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import quote, urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.florenceco.org/offices/delinquent-tax/"

# florenceco.org is a Mobirise-built site: EVERY attribute is single-quoted.
# A double-quote-only href regex (the previous implementation) matched 0 links.
_HREF_RE = re.compile(r"""href\s*=\s*['"]([^'"]+)['"]""", re.I)

# Keep the sale LISTS; skip the registration form / buyer info / process /
# GIS-instruction PDFs that sit on the same page.
_PDF_WANT = ("tax sale",)
_PDF_SKIP = (
    "process", "instruction", "registration", "bidder", "buyer",
    "form", "gis", "faq",
)

# Florence TMS / map-block-parcel: 47-03-060, 151-01-137, 1012-01-215,
# 90073-05-005, 21105-02-005 (2-5 digit map, 2 digit block, 3 digit parcel).
_TMS = r"\d{2,5}-\d{2}-\d{3}(?:\.\d+)?"

_ROW_RE = re.compile(
    r"^\s*(?P<owner>\S.{0,40}?)\s{2,}S\s+"
    r"(?P<tms>" + _TMS + r")\s{2,}"
    r"(?P<rest>\S.*)$"
)
_CURRENT_OWNER_RE = re.compile(
    r"\*\*\s*CURRENT\s+OWNER:\s*(?P<owner>.+?)\s{2,}(?P<tms>" + _TMS + r")",
    re.I,
)
# Trailing fixed-width numeric columns (LOTS / ACRES / BLDGS / DISTRICT).
_TAIL_NUMS_RE = re.compile(r"(?:\s{2,}[\d.,]+)+\s*$")
_HOUSE_NUM_RE = re.compile(r"^\d{1,6}\s+[A-Za-z]")
_YEAR_PREFIX_RE = re.compile(r"^(?:19|20)\d{2}\b")  # mobile-home model year

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_DATE_RE = re.compile(
    r"(" + _MONTHS + r")\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(\d{4})", re.I
)
_MONTH_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _page_text(html: str) -> str:
    txt = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", txt)


def _parse_sale_date(text: str) -> tuple[datetime | None, str | None]:
    """Read the announced sale date out of the office page.

    Anchored on the sentence that states when the sale is held, so the
    pre-registration deadline (a different, earlier date on the same page)
    is never mistaken for the sale.
    """
    for anchor in ("conducted", "will be held", "scheduled", "sale begins"):
        m = re.search(re.escape(anchor) + r"(.{0,240})", text, re.I)
        if not m:
            continue
        d = _DATE_RE.search(m.group(1))
        if not d:
            continue
        mo = _MONTH_NUM.get(d.group(1).lower())
        try:
            when = datetime(int(d.group(3)), mo, int(d.group(2)))
        except (TypeError, ValueError):
            continue
        return when, d.group(0)
    return None, None


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


_COL_NUM_RE = re.compile(r"^[\d.,]+$")


def _extract_tail_columns(pdf_bytes: bytes) -> dict[str, dict[str, str]]:
    """Map each row's TMS -> its {lots, acres, bldgs, district} values, read
    by each number's X position against the header's own column bins (see
    the module docstring's "AUDITED 2026-10-03" note for why position, not
    whitespace-run counting, is the only reliable way to tell these columns
    apart). Works for both the "Real" (LOTS/ACRES/BLDGS/DISTRICT) and
    "Mobile Homes" (BLDGS/DISTRICT only) PDFs -- whichever header words are
    actually present set the bins."""
    import pdfplumber

    out: dict[str, dict[str, str]] = {}
    bins: dict[str, tuple[float, float]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            try:
                words = page.extract_words()
            except Exception:
                continue
            for w in words:
                name = w["text"].rstrip(":").upper()
                if name in ("LOTS", "ACRES", "BLDGS", "DISTRICT"):
                    bins[name.lower()] = (w["x0"] - 3, w["x1"] + 3)
            if not bins:
                continue  # header not seen yet on any page -- nothing to bin against

            lines: dict[int, list[dict]] = {}
            for w in words:
                lines.setdefault(round(w["top"]), []).append(w)
            for ws in lines.values():
                ws.sort(key=lambda w: w["x0"])
                tms = None
                nums: dict[str, str] = {}
                for w in ws:
                    t = w["text"]
                    if tms is None and re.fullmatch(_TMS, t):
                        tms = t
                        continue
                    if _COL_NUM_RE.match(t):
                        for col, (lo, hi) in bins.items():
                            if lo <= w["x0"] <= hi:
                                nums[col] = t
                                break
                if tms and nums:
                    out[tms] = nums
    return out


def _parse_pdf_text(text: str) -> list[dict]:
    """Parse a Florence tax-sale PDF into {taxpayer, tms, location, current_owner}."""
    rows: list[dict] = []
    pending: dict[str, str] = {}   # tms -> current owner (line precedes its row)
    for ln in text.splitlines():
        if not ln.strip():
            continue

        co = _CURRENT_OWNER_RE.search(ln)
        if co:
            pending[co.group("tms")] = re.sub(r"\s+", " ", co.group("owner")).strip()
            continue

        up = ln.upper()
        if "TAXPAYER" in up and "MAP-BLOCK-PARCEL" in up:
            continue

        m = _ROW_RE.match(ln)
        if not m:
            continue
        owner = re.sub(r"\s+", " ", m.group("owner")).strip()
        if len(owner) < 2:
            continue
        loc = _TAIL_NUMS_RE.sub("", m.group("rest"))
        loc = re.sub(r"\s{2,}", " ", loc).strip()
        tms = m.group("tms")
        rows.append({
            "taxpayer": owner,
            "tms": tms,
            "location": loc or None,
            "current_owner": pending.pop(tms, None),
        })
    return rows


class FlorenceDelinquentTax(BaseScraper):
    slug = "counties_sc.florence_delinquent_tax"
    name = "Florence County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 240.0
    expected_min_count = 0
    optional = True
    # The list is PUBLISHED in September for an early-October sale (2026 file is
    # dated 9-01-26 for an Oct 5 sale), so September must be in-season or the
    # entire pre-sale window is skipped.
    active_months = (9, 10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=45.0)
        except Exception as exc:
            log.warning("florence_tax.fetch_fail", error=str(exc)[:160])
            return out
        if not html or len(html) < 200:
            return out

        text = _page_text(html)
        sale_date, sale_date_text = _parse_sale_date(text)
        log.info("florence_tax.page", sale_date=str(sale_date), raw=sale_date_text)

        pdfs: list[str] = []
        for href in _HREF_RE.findall(html):
            if ".pdf" not in href.lower():
                continue
            low = href.lower()
            if not any(w in low for w in _PDF_WANT):
                continue
            if any(s in low for s in _PDF_SKIP):
                continue
            full = urljoin(PAGE_URL, href)
            if full not in pdfs:
                pdfs.append(full)
        log.info("florence_tax.pdfs", count=len(pdfs))

        for pdf_url in pdfs[:6]:
            label = pdf_url.rsplit("/", 1)[-1]
            is_mobile = "mobile" in label.lower()
            try:
                # S3 filenames contain spaces; quote them but keep the URL punctuation.
                data = await get_bytes(quote(pdf_url, safe=":/?&=%"), timeout=120)
                rows = _parse_pdf_text(_extract_pdf_text(data))
            except Exception as exc:
                log.warning("florence_tax.pdf_error", url=label[:60], error=str(exc)[:140])
                continue
            try:
                tail_cols = _extract_tail_columns(data)
            except Exception as exc:
                log.warning("florence_tax.tail_cols_error", url=label[:60], error=str(exc)[:140])
                tail_cols = {}
            log.info("florence_tax.pdf_parsed", url=label[:60], rows=len(rows),
                      tail_cols=len(tail_cols))

            for r in rows[:5000]:
                loc = r.get("location")
                addr = None
                if loc and _HOUSE_NUM_RE.match(loc) and not _YEAR_PREFIX_RE.match(loc):
                    addr = loc
                now = datetime.utcnow()
                tail = tail_cols.get(r["tms"], {})

                def _num(key: str) -> float | None:
                    v = tail.get(key)
                    if not v:
                        return None
                    try:
                        return float(v.replace(",", ""))
                    except ValueError:
                        return None

                # AUDITED 2026-10-03: BLDGS is never written as a literal "0"
                # in this export (blank = no building, same sparse-omission
                # convention as Dillon's own Buildings column) -- a missing
                # bldgs on the REAL list (not the already-MOBILE-tagged list)
                # means vacant land.
                kind = PropertyKind.MOBILE if is_mobile else (
                    PropertyKind.LAND if "bldgs" not in tail else PropertyKind.UNKNOWN
                )

                out.append(Listing(
                    source="counties_sc.florence_delinquent_tax",
                    source_url=pdf_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=kind,
                    state="SC",
                    county="Florence",
                    parcel_id=r["tms"],
                    defendant=r.get("current_owner") or r["taxpayer"],
                    street_address=addr,
                    sale_date=sale_date,
                    description=" | ".join(
                        x for x in (r["taxpayer"], loc, label) if x
                    ),
                    first_seen=now,
                    last_seen=now,
                    raw={"florence_delinquent_tax": {
                        "tms": r["tms"],
                        "taxpayer": r["taxpayer"],
                        "current_owner": r.get("current_owner"),
                        "location": loc,
                        "list": label,
                        "pdf_url": pdf_url,
                        "sale_date_text": sale_date_text,
                        "is_mobile_home": is_mobile,
                        "lots": _num("lots"),
                        "acres": _num("acres"),
                        "buildings": _num("bldgs"),
                        "tax_district": tail.get("district"),
                    }},
                ))

        log.info("florence_tax.done", count=len(out))
        return out
