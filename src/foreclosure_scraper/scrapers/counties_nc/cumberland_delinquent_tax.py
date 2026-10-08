"""Cumberland County NC advertisement of unpaid real-estate taxes (NCGS 105-369), the county's
own PDF.

SOURCE
    cumberlandcountync.gov/departments/tax-group/tax/tax-bill-options/delinquent-taxes links the
    newspaper advertisement as a PDF (docs/default-source/tax-documents/delinquent-taxes/
    delinquent_taxes__<year>.pdf). The 2025 file, read 2026-10-07: 14 pages, "Advertisement of
    Unpaid Real Estate Taxes for 2025", printed for the Fayetteville Observer of Sunday
    June 21, 2026. The county's web grid of the same list (3,755 rows, a Telerik ASP.NET grid that
    pages by postback) shrinks as bills are paid; the PDF is the June snapshot, so a row may have
    been paid since. Every row is real estate (the county advertises personal property apart).

ROW LAYOUT (pypdf text)
    "<PIN 9999-99-9999> <owner ...> <house number> <street ...> <CITY> NC [ZIP] $<amount>",
    wrapped over two or three lines. A record starts at a PIN and ends at the "$amount". The PIN
    is the NC OneMap / parcel-cache key; the owner and situs are split at the last house number
    followed by a street word, best effort, and the parcel cache supplies both by PIN anyway.

THE NOT-YET-LATE RULE: the advertised levy year (2025) is late since 2026-01-06, so the rows
count; raw['tax_owed'] via _tax_kit counts only late years.

DATELESS: slug counties_nc.cumberland_delinquent_tax goes in main.DATELESS_OK_SOURCES.
Gate: FORECLOSURE_CUMBERLAND_TAX=0. Year: FORECLOSURE_CUMBERLAND_TAX_YEAR (default: last levy
year that is late today).
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...tax_calendar import latest_delinquent_levy_year
from ..counties_generic._tax_kit import tax_owed_block

log = structlog.get_logger()

SLUG = "counties_nc.cumberland_delinquent_tax"
ENV_OFF = "FORECLOSURE_CUMBERLAND_TAX"
PAGE = ("https://www.cumberlandcountync.gov/departments/tax-group/tax/tax-bill-options/"
        "delinquent-taxes")
PDF = ("https://www.cumberlandcountync.gov/docs/default-source/tax-documents/delinquent-taxes/"
       "delinquent_taxes__{year}.pdf")

_PIN = re.compile(r"^(\d{4}-\d{2}-\d{4})\b\s*(.*)$")
#: pypdf sometimes splits an amount with a space ("$17 6.08" is $176.08): spaces inside the
#: digits after the "$" are dropped.
_AMT = re.compile(r"\$\s?(\d[\d, ]*\.\s?\d{2})\s*$")
_TAIL = re.compile(r"\s*(?:\b(?:FAYETTEVILLE|HOPE MILLS|SPRING LAKE|STEDMAN|EASTOVER|GODWIN|WADE|"
                   r"FALCON|LINDEN|FORT LIBERTY|FORT BRAGG|PARKTON|ROSEBORO|DUNN|ERWIN|SALEMBURG)\b)?"
                   r"(?:\s+NC)?(?:\s+\d{5}(?:-\d{4})?)?\s*$", re.I)
_STREET = re.compile(r"\b(\d{1,6}[A-Z]?)\s+((?:[NSEW]\s+)?[A-Z0-9][A-Z0-9'.\- ]*?\b(?:RD|ST|DR|AVE|LN|CT|CIR|"
                     r"PL|WAY|BLVD|HWY|PKWY|TRL|TER|LOOP|RUN|PATH|XING|SQ|PT|ROW|ALY|EXT|CV|TRCE|"
                     r"HOLW|BND|GRV|LNDG|PIKE|PASS|WALK|RDG|VW|CRK|CRES)\b(?:\s+[NSEW])?)", re.I)


def parse_text(text: str) -> list[dict]:
    """Records from the advertisement's text: {'pin', 'owner', 'situs', 'amount'}."""
    out: list[dict] = []
    cur: Optional[dict] = None
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = _PIN.match(ln)
        if m:
            cur = {"pin": m.group(1), "text": m.group(2)}
        elif cur is not None:
            cur["text"] = (cur["text"] + " " + ln).strip()
        else:
            continue
        a = _AMT.search(cur["text"])
        if a:
            body = cur["text"][: a.start()].strip()
            amount = float(re.sub(r"[,\s]", "", a.group(1)))
            owner, situs = split_owner_situs(body)
            out.append({"pin": cur["pin"], "owner": owner, "situs": situs, "amount": amount})
            cur = None
    return out


#: The ad prints a parcel with no situs as "0 ? DR UNINCORPORATED" or "0 N/A DR": the placeholder
#: is not an address and must not stay in the owner (5 of 30 sampled rows on 10/8; audit
#: 2026-10-09 additions_verify).
_PLACEHOLDER_SITUS = re.compile(r"\s+0+\s+(?:\?+|N\s*/\s*A|UNKNOWN)(?:\s+[A-Z]{2,5})?(?:\s+UNINCORPORATED)?"
                                r"(?:\s+NC)?(?:\s+\d{5}(?:-\d{4})?)?\s*$", re.I)


def split_owner_situs(body: str) -> tuple[Optional[str], Optional[str]]:
    body = re.sub(r"\s+", " ", body or "").strip()
    core = _TAIL.sub("", body).strip()
    ph = _PLACEHOLDER_SITUS.search(core)
    if ph:
        return (core[: ph.start()].strip(" ,") or None), None
    hits = list(_STREET.finditer(core))
    if not hits:
        return (core or None), None
    m = hits[-1]
    owner = core[: m.start()].strip(" ,") or None
    num = m.group(1).lstrip("0")
    situs = f"{num} {m.group(2).strip()}" if num else None
    return owner, situs


def to_listing(rec: dict, year: int, url: str, *, now: Optional[datetime] = None) -> Optional[Listing]:
    to = tax_owed_block([(year, rec["amount"])], state="NC", county="Cumberland", source=SLUG,
                        basis="advertised_list")
    if not to:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    raw: dict[str, Any] = {
        "cumberland_delinquent_tax": {"tax_year": year, "amount": rec["amount"], "pin": rec["pin"],
                                      "years_unpaid": [year], "list_url": url},
        "tax_owed": to,
    }
    return Listing(
        source=SLUG, source_url=url,
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Cumberland",
        street_address=rec.get("situs"), parcel_id=rec["pin"],
        owner_name=rec.get("owner"), defendant=rec.get("owner"),
        foreclosure_process="tax",
        description=f"Cumberland NC unpaid {year} real-estate tax ${rec['amount']:,.0f} — {rec['pin']}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class CumberlandDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Cumberland County NC unpaid real-estate tax advertisement (county PDF)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        from pypdf import PdfReader
        year = int(os.environ.get("FORECLOSURE_CUMBERLAND_TAX_YEAR") or latest_delinquent_levy_year("NC"))
        url = PDF.format(year=year)
        async with client(timeout=120.0) as c:
            r = await c.get(url)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            raise RuntimeError(f"cumberland {year} PDF: HTTP {r.status_code}")
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)
        recs = parse_text(text)
        out = [li for li in (to_listing(rec, year, url) for rec in recs) if li]
        log.info("cumberland_tax.done", year=year, records=len(recs), leads=len(out))
        return out
