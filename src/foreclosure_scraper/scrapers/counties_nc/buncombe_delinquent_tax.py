"""Buncombe County NC advertisement of tax liens (NCGS 105-369 annual PDF).

Buncombe County (Asheville, NC — Western NC core) publishes its statutory
Advertisement of Tax Liens on Real Property as a free, public, no-login .gov PDF:

    https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf

(linked from buncombenc.gov/604/Tax-Collections). Per NCGS 105-369 the county
must advertise unpaid current-year real-property tax liens; each advertised
parcel is a delinquent-tax distress signal — the lien attaches and the county
may pursue tax foreclosure if it stays unpaid.

PDF layout: the advertisement is laid out in newspaper-style columns. pypdf's
extract_text() walks the page in reading order and emits each parcel as a small
block of lines delimited by a literal '--' separator. Within a block the field
order is stable:

    <record owner name line(s)>   (1-2 owners, each possibly wrapped to 2 lines)
    <15-char PIN>                 (e.g. 961895417300000, may contain letters)
    <principal tax due>           (e.g.  $775.59  / $-  for $0)
    <situs address line(s)>       (e.g. 107 PISGAH VIEW RD, may wrap to 2 lines)

We split the full text on the '--' separators and, within each block, locate the
15-char PIN token. Owner-name lines precede the PIN; the situs lines follow the
$-amount line. Multi-line owner names and situs addresses are rejoined. This
column-aware, separator-anchored parse avoids the cross-column interleave that a
naive line-by-line read would produce.

Buncombe PIN: 15 alphanumeric chars (county GIS pads a 10-digit base PIN out to
15 with trailing zeros; some carry interior letters e.g. 9648451100C005I).

Free public .gov PDF; plain HTTP + pypdf. No login, no CAPTCHA, no paywall.
Live-verified 2026-06-30: PDF fetches (12 pages, ~643 KB), 1,192 parcel blocks
parse to owner + situs + PIN + principal-tax-due.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PDF_URL = (
    "https://media.buncombenc.gov/common/tax/"
    "buncombe-county-tax-department-advertisement-of-tax-liens.pdf"
)

# Buncombe PIN: 15 alphanumeric chars (10-digit base padded to 15; may carry
# interior letters). Anchored to a whole line so it's not confused with the
# leading page-number line or the $-amount.
_PIN_RE = re.compile(r"^[0-9A-Z]{15}$")
# Principal tax due: " $775.59 " or " $-   " ($0). Matches a $-led money token.
_MONEY_RE = re.compile(r"^\$\s*[\d,]*\.?\d*\s*$|^\$-\s*$")
# Block separator emitted by pypdf between advertised parcels.
_SEP = "--"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_money(s: str) -> float | None:
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_block(block_lines: list[str], url: str) -> Listing | None:
    """Parse one '--'-delimited advertisement block into a Listing.

    Field order in the block: owner-name line(s), 15-char PIN, $tax-due,
    situs line(s)."""
    lines = [ln.rstrip() for ln in block_lines if ln.strip()]
    if not lines:
        return None

    pin_idx = next((i for i, ln in enumerate(lines) if _PIN_RE.match(ln.strip())), None)
    if pin_idx is None:
        return None
    pin = lines[pin_idx].strip()

    # Owner name = every line before the PIN (joined; drop a leading page-number
    # line that pypdf prepends at the top of each column).
    name_lines = [ln for ln in lines[:pin_idx] if not re.fullmatch(r"\d{1,4}", ln.strip())]
    owner = _clean(" ".join(name_lines)) or None

    # After the PIN: an optional $-amount line, then the situs address line(s).
    rest = lines[pin_idx + 1:]
    tax_due = None
    situs_lines: list[str] = []
    for ln in rest:
        if tax_due is None and _MONEY_RE.match(ln.strip()):
            tax_due = _parse_money(ln)
            continue
        # Stop if a stray PIN or another money token leaks in (block boundary safety).
        if _PIN_RE.match(ln.strip()):
            break
        situs_lines.append(ln)
    situs = _clean(" ".join(situs_lines)) or None

    if not (owner or situs):
        return None

    return Listing(
        source="counties_nc.buncombe_delinquent_tax",
        source_url=url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        street_address=situs,
        owner_name=owner,
        defendant=owner,
        parcel_id=pin,
        # NOTE: tax_due is the back-tax balance OWED, NOT the assessed/taxable
        # value — do NOT put it in tax_value (calc.py would read it as the
        # property value and ARV=tax_value*1.25 would collapse to ~$1k). The
        # owed amount lives in raw.principal_tax_due and is normalized to
        # raw['tax_owed'] by enrichment_tax_owed; assessed value comes from GIS.
        foreclosure_process="tax",
        description=_clean(f"{owner or ''} {situs or ''} PIN {pin}")[:300],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "buncombe_delinquent_tax": {
                "pin": pin,
                "principal_tax_due": tax_due,
                "owner": owner,
                "situs": situs,
            }
        },
    )


def _pdf_text(data: bytes) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:  # noqa: BLE001
        log.warning("buncombe_delinquent.pdf_parse_fail", error=str(exc)[:160])
        return ""


def parse_advertisement(text: str, url: str) -> list[Listing]:
    """Split the advertisement text on '--' separators and parse each block."""
    out: list[Listing] = []
    seen: set[str] = set()
    block: list[str] = []
    for raw_line in (text or "").splitlines():
        if raw_line.strip() == _SEP:
            lst = parse_block(block, url)
            block = []
            if lst is not None and lst.parcel_id not in seen:
                seen.add(lst.parcel_id)
                out.append(lst)
            continue
        block.append(raw_line)
    # Trailing block with no closing separator.
    if block:
        lst = parse_block(block, url)
        if lst is not None and lst.parcel_id not in seen:
            seen.add(lst.parcel_id)
            out.append(lst)
    return out


class BuncombeDelinquentTax(BaseScraper):
    slug = "counties_nc.buncombe_delinquent_tax"
    name = "Buncombe County (NC) Advertisement of Tax Liens (NCGS 105-369 PDF)"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 1

    async def fetch(self) -> Iterable[Listing]:
        try:
            data = await get_bytes(PDF_URL, timeout=90.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("buncombe_delinquent.fetch_fail", error=str(exc)[:160])
            return []
        if not (data and data[:4] == b"%PDF"):
            log.info("buncombe_delinquent.not_pdf")
            return []
        rows = parse_advertisement(_pdf_text(data), PDF_URL)
        log.info("buncombe_delinquent.done", count=len(rows))
        return rows
