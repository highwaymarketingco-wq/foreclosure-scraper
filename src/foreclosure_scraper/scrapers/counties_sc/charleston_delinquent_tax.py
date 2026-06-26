"""Charleston County (SC, coastal) Delinquent-Tax tax-sale + FLC sealed-bid lists.

Charleston's Delinquent Tax Office publishes the annual tax-sale inventory as two
weekly-updated PDFs on https://charlestoncounty.gov/departments/delinquent-tax/ :

  * RP-Tax-Sale-Listing.pdf  — Real Property parcels (10-digit PIN). Columns:
      pin classcd Tag owner1 owner2 City SitusAddr Appraisal TotalAssessed Acerage Totaldue
  * MH-Tax-Sale-Listing.pdf  — Mobile Home parcels (PIN = "MH########"). Columns:
      pin Tag owner1 owner2 description SitusAddr City Appraisal Totaldue

Each PDF is a clean pdfplumber table (the header row repeats on every page, so we
map columns by NAME and tolerate the RP/MH column-order difference). The county
prints owner names and dollar amounts with spurious intra-token spaces (a PDF
text-layer artifact — "A C E V EDO" / "$ 6 81.63"); `_despace_name` /
`_clean_money` repair these.

The FLC sealed-bid sale draws from this same unsold inventory — the county's
"FLC Sealed Bid" PDF is a blank submittal FORM (no parcels), so we discover/record
its URL + the sealed-bid deadline but parse parcels from the RP/MH listings, which
ARE the FLC/tax-sale parcel list.

Distress: every row is a property whose owner owes back taxes and is headed to the
Dec tax sale (then a ~12mo SC redemption per §12-51-90, then FLC sealed-bid if
unsold) — strong, early, free pre-foreclosure signal.

Dateless at the ROW level (line items carry no per-parcel sale date). We DO parse
the single sale date printed in the PDF header when present and set sale_date from
it; raw["charleston_delinquent_tax"]["dateless"] records whether a date was found.

SEASONAL: Charleston posts the list ~Oct, sale ~Dec, FLC sealed-bid window into
Feb — gated to Oct-Feb so off-season runs skip cleanly and auto-resume.

Free, plain HTTP PDF (pdfplumber), no anti-bot, ToS-OK (county treasurer page).
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

LANDING = "https://charlestoncounty.gov/departments/delinquent-tax/"

# Known current filenames (stable across years on this CMS) used as a fallback
# when link-discovery on the landing page comes up empty. Discovery runs first so
# a filename change is picked up automatically.
FALLBACK_LIST_PDFS = (
    "https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf",
    "https://www.charlestoncounty.gov/departments/delinquent-tax/files/MH-Tax-Sale-Listing.pdf",
)

# RESID-SFR / VAC-RES-LOT etc. classcd -> PropertyKind (RP only; MH is always MOBILE).
_KIND_BY_CLASS = (
    ("sfr", PropertyKind.SINGLE_FAMILY),
    ("dup", PropertyKind.MULTI_FAMILY),
    ("tri", PropertyKind.MULTI_FAMILY),
    ("apt", PropertyKind.MULTI_FAMILY),
    ("condo", PropertyKind.CONDO),
    ("comm", PropertyKind.COMMERCIAL),
    ("vac", PropertyKind.LAND),
    ("lot", PropertyKind.LAND),
    ("undevelop", PropertyKind.LAND),
    ("mh", PropertyKind.MOBILE),
)

# Header tokens we map columns from. Lowercased substring match so minor header
# wording drift still binds the right column.
_HDR_PIN = ("pin",)
_HDR_OWNER1 = ("owner1", "owner")
_HDR_OWNER2 = ("owner2",)
_HDR_SITUS = ("situsaddr", "situs", "address")
_HDR_CITY = ("city",)
_HDR_CLASS = ("classcd", "class")
_HDR_APPR = ("appraisal", "appraised")
_HDR_ASSESS = ("totalassessed", "assessed")
_HDR_ACRE = ("acerage", "acreage")
_HDR_DUE = ("totaldue", "due", "amount")
_HDR_DESC = ("description", "descript")

_RP_PIN_RE = re.compile(r"^\d{8,12}$")
_MH_PIN_RE = re.compile(r"^MH\d{4,}$", re.I)
_SALE_DATE_RE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?,?\s*"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(20\d{2})",
    re.I,
)
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def _despace_name(s: str | None) -> str | None:
    """Repair Charleston's spaced-out leading letters in owner/desc text.

    The county's PDF prints the alphabetical sort prefix one letter at a time
    ("A C E V EDO IBARRA ADOLFO" -> "ACEVEDO IBARRA ADOLFO"). Single letters
    separated by spaces are re-joined; multi-letter words are left alone. A
    leading run of digits (the situs house-number echoed into owner1, e.g.
    "1 4 0 SPRING HOLDINGS LLC") is stripped.
    """
    if not s:
        return None
    s = s.replace("\n", " ").strip()
    # Drop a leading spaced/un-spaced run of digits (house-number echo).
    s = re.sub(r"^(?:\d\s*)+", "", s).strip()
    if not s:
        return None
    # Re-join a run of consecutive single letters. The county spaces out the
    # leading letters of the FIRST surname only, leaving its tail either fully
    # consumed ("A D A M S FLORENCE" -> "ADAMS" + "FLORENCE") or as a short
    # trailing fragment of the SAME word ("A C E V EDO" -> "ACEVEDO";
    # "A C K E RMAN" -> "ACKERMAN"). Heuristic: absorb the trailing word into
    # the run only if it's short (<=4 chars) — a true separate name like
    # "FLORENCE" (>=5) stays its own token.
    toks = s.split()
    out: list[str] = []
    buf: list[str] = []
    for t in toks:
        if len(t) == 1 and t.isalpha():
            buf.append(t)
        elif buf:
            if len(t) <= 4 and t.isalpha():
                out.append("".join(buf) + t)  # tail fragment of the same word
            else:
                out.append("".join(buf))       # spaced word complete; t is separate
                out.append(t)
            buf = []
        else:
            out.append(t)
    if buf:
        out.append("".join(buf))
    return re.sub(r"\s+", " ", " ".join(out)).strip() or None


def _clean_money(s: str | None) -> float | None:
    """'$ 1 ,970,000.00' / '$ 6 81.63' -> 1970000.00 / 681.63."""
    if not s:
        return None
    digits = re.sub(r"[^\d.]", "", s.replace(" ", ""))
    if not digits or digits == ".":
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _clean_text(s: str | None) -> str | None:
    if not s:
        return None
    out = re.sub(r"\s+", " ", s.replace("\n", " ")).strip()
    return out or None


def _kind_for(classcd: str | None, is_mh: bool) -> PropertyKind:
    if is_mh:
        return PropertyKind.MOBILE
    low = (classcd or "").lower()
    for needle, kind in _KIND_BY_CLASS:
        if needle in low:
            return kind
    return PropertyKind.UNKNOWN


def _col_map(header: list[str]) -> dict[str, int]:
    """Map our logical field -> column index using a header row."""
    low = [str(h or "").strip().lower() for h in header]

    def find(cands: tuple[str, ...]) -> int | None:
        for i, h in enumerate(low):
            if any(c in h for c in cands):
                return i
        return None

    return {
        "pin": find(_HDR_PIN),
        "owner1": find(_HDR_OWNER1),
        "owner2": find(_HDR_OWNER2),
        "situs": find(_HDR_SITUS),
        "city": find(_HDR_CITY),
        "classcd": find(_HDR_CLASS),
        "appr": find(_HDR_APPR),
        "assess": find(_HDR_ASSESS),
        "acre": find(_HDR_ACRE),
        "due": find(_HDR_DUE),
        "desc": find(_HDR_DESC),
    }


def _is_header_row(row: list) -> bool:
    cells = [str(c or "").strip().lower() for c in row]
    return "pin" in cells and any("owner" in c for c in cells)


def _parse_sale_date(text: str) -> datetime | None:
    m = _SALE_DATE_RE.search(text or "")
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(2)))
    except ValueError:
        return None


def _cell(row: list, idx: int | None) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    return str(v).strip() if v is not None and str(v).strip() else None


def parse_listing_pdf(data: bytes, source_url: str) -> list[Listing]:
    """pdfplumber-parse a Charleston RP or MH tax-sale-listing PDF into Listings.

    Header row repeats on every page; we (re)bind the column map whenever a
    header row is seen, so RP/MH column-order differences and continuation pages
    are both handled. Returns one Listing per parcel row, deduped by PIN.
    """
    try:
        import pdfplumber
    except ImportError:
        log.warning("charleston_delinquent.no_pdfplumber")
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    cols: dict[str, int] | None = None
    sale_date: datetime | None = None
    is_mh = "mh-tax" in source_url.lower() or "/mh" in source_url.lower()

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            if sale_date is None:
                sale_date = _parse_sale_date(page.extract_text() or "")
            for tbl in page.extract_tables() or []:
                for row in tbl:
                    if not row or all(not (c and str(c).strip()) for c in row):
                        continue
                    if _is_header_row(row):
                        cols = _col_map(row)
                        continue
                    if cols is None:
                        continue
                    pin_raw = _cell(row, cols["pin"])
                    if not pin_raw:
                        continue
                    pin = re.sub(r"\s+", "", pin_raw)
                    if not (_RP_PIN_RE.match(pin) or _MH_PIN_RE.match(pin)):
                        continue
                    if pin in seen:
                        continue
                    seen.add(pin)

                    row_is_mh = is_mh or bool(_MH_PIN_RE.match(pin))
                    owner1 = _despace_name(_cell(row, cols["owner1"]))
                    owner2 = _despace_name(_cell(row, cols["owner2"]))
                    owner = " ".join(o for o in (owner1, owner2) if o) or None
                    situs = _clean_text(_cell(row, cols["situs"]))
                    city = _clean_text(_cell(row, cols["city"]))
                    classcd = _clean_text(_cell(row, cols["classcd"]))
                    desc = _clean_text(_cell(row, cols["desc"]))
                    appraisal = _clean_money(_cell(row, cols["appr"]))
                    assessed = _clean_money(_cell(row, cols["assess"]))
                    acreage = _clean_money(_cell(row, cols["acre"]))
                    total_due = _clean_money(_cell(row, cols["due"]))

                    desc_bits = [
                        f"Charleston SC delinquent-tax / tax-sale parcel (PIN {pin})",
                    ]
                    if classcd:
                        desc_bits.append(classcd)
                    if desc:
                        desc_bits.append(desc)
                    if total_due is not None:
                        desc_bits.append(f"delinquent ${total_due:,.2f}")

                    out.append(Listing(
                        source="counties_sc.charleston_delinquent_tax",
                        source_url=source_url,
                        listing_type=ListingType.TAX_SALE,
                        property_kind=_kind_for(classcd, row_is_mh),
                        state="SC",
                        county="Charleston",
                        street_address=situs,
                        city=city,
                        parcel_id=pin,
                        defendant=owner,
                        # Totaldue is the delinquent amount = basis for the
                        # opening bid (county notes it excludes current-year
                        # taxes, so it's a floor, not the final start bid).
                        opening_bid=total_due,
                        market_value=appraisal,
                        assessed_value=assessed,
                        acreage=acreage,
                        sale_date=sale_date,  # from PDF header; None if absent
                        foreclosure_process="tax",
                        description=" | ".join(desc_bits)[:300],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"charleston_delinquent_tax": {
                            "pin": pin,
                            "kind": "mobile_home" if row_is_mh else "real_property",
                            "owner": owner,
                            "total_due": total_due,
                            "appraisal": appraisal,
                            "total_assessed": assessed,
                            "acreage": acreage,
                            "classcd": classcd,
                            "mh_description": desc if row_is_mh else None,
                            # Row-level data is dateless; True unless a header
                            # sale date was parsed for the file.
                            "dateless": sale_date is None,
                            "sale_date": sale_date.date().isoformat() if sale_date else None,
                            "list_pdf": source_url,
                        }},
                    ))
    log.info("charleston_delinquent.pdf_parsed", url=source_url, count=len(out),
             sale_date=sale_date.date().isoformat() if sale_date else None)
    return out


def _discover_pdfs(html: str) -> tuple[list[str], str | None]:
    """Return (tax-sale-list PDF urls, FLC-sealed-bid form url) from the landing page."""
    hrefs = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)
    lists: list[str] = []
    flc_form: str | None = None
    for h in hrefs:
        u = urljoin(LANDING, h)
        low = u.lower()
        if "tax-sale-listing" in low or re.search(r"/(rp|mh)[-_]?tax", low):
            if u not in lists:
                lists.append(u)
        elif "sealed-bid" in low and ("form" in low or "submittal" in low):
            flc_form = flc_form or u
    return lists, flc_form


class CharlestonDelinquentTax(BaseScraper):
    slug = "counties_sc.charleston_delinquent_tax"
    name = "Charleston County (SC) Delinquent Tax Sale + FLC Sealed-Bid Lists"
    category = "county_tax"
    expected_min_count = 0  # seasonal — 0 off-season is legitimate
    requires_apify = False
    timeout_s = 180.0
    active_months = (10, 11, 12, 1, 2)  # list posts ~Oct; sale ~Dec; FLC sealed bid into Feb

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        list_urls: list[str] = []
        flc_form: str | None = None

        # Discover the current list-PDF links (robust to filename changes).
        try:
            html = await get_text(LANDING, headers={"User-Agent": "Mozilla/5.0"}, timeout=45.0)
            list_urls, flc_form = _discover_pdfs(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("charleston_delinquent.landing_fail", error=str(exc)[:160])

        # Fall back to the known stable filenames if discovery found nothing.
        for u in FALLBACK_LIST_PDFS:
            if u not in list_urls:
                list_urls.append(u)
        if flc_form:
            log.info("charleston_delinquent.flc_sealed_bid_form", url=flc_form)

        # Dedup the fetch list by path (ignore the ?v=NNN cache-buster query) so a
        # discovered "RP-Tax-Sale-Listing.pdf?v=670" and the bare fallback URL
        # don't fetch + parse the same PDF twice.
        seen_path: set[str] = set()
        seen_pin: set[str] = set()
        for url in list_urls:
            path = url.split("?", 1)[0]
            if path in seen_path:
                continue
            seen_path.add(path)
            try:
                data = await get_bytes(url, timeout=120.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("charleston_delinquent.pdf_fetch_fail", url=url, error=str(exc)[:160])
                continue
            if not (data and data[:4] == b"%PDF"):
                continue
            for r in parse_listing_pdf(data, url):
                if r.parcel_id in seen_pin:
                    continue
                seen_pin.add(r.parcel_id)
                if flc_form:
                    r.raw["charleston_delinquent_tax"]["flc_sealed_bid_form"] = flc_form
                out.append(r)

        log.info("charleston_delinquent.done", count=len(out))
        return out
