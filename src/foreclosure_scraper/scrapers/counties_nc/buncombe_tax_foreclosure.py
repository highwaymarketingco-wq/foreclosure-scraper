"""Buncombe County NC tax-foreclosure / upset-bid sales — official fcl.pdf.

Buncombe publishes its tax-foreclosure list as a single PDF at
``media.buncombenc.gov/common/tax/foreclosure-listings/fcl.pdf`` (may 301 via
buncombenc.gov). Each property block carries the owner name, superior-court
case number, parcel PIN, township, situs address, property type, acreage, an
OPENING/CURRENT bid, and an "UPSET BIDDING ENDS" date (or "REDEEMED"). This
replaces the earlier Trumba ICS feed, which returned zero events.

Block shape (one record)::

    JOSEPHINE SMITH
    CASE 21 CVD 3313 BARNARDSVILLE
    PIN: 9775-47-4188 BARNARDSVILLE HWY
    LAND & STRUCTURES
    12.24 ACRES, MORE OR LESS CURRENT BID: $25,000
    UPSET BIDDING ENDS: MARCH 4, 2022
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PDF_URL = "https://media.buncombenc.gov/common/tax/foreclosure-listings/fcl.pdf"
PAGE_URL = "https://taxforeclosures.buncombenc.gov/"

_HEADER = "Name, Case #, PIN, Location & Bid Information"
_CASE_RE = re.compile(r"^CASE\s+(.+)$", re.I)
_CASENUM_RE = re.compile(r"^(\d{1,4}\s+[A-Z]{1,4}\s+\d+)\s*(.*)$")
_PIN_RE = re.compile(r"^PIN:\s*([0-9][0-9-]*[0-9])\s*(.*)$", re.I)
_BID_RE = re.compile(r"(CURRENT|OPENING)\s+BID:\s*\$?([\d,]+(?:\.\d+)?)", re.I)
_UPSET_RE = re.compile(r"UPSET\s+BIDD[A-Z]*\s+ENDS?:\s*(.+)", re.I | re.M)
_EXPIRE_RE = re.compile(r"BID\s+EXPIRES?:?\s*(.+)", re.I | re.M)
_ACRE_RE = re.compile(r"([\d.]+)\s+ACRES", re.I)
_PROP_TYPES = ("LAND & STRUCTURES", "LAND AND STRUCTURES", "LAND ONLY", "STRUCTURES ONLY", "STRUCTURES")


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", s.replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _parse_date(s: str | None) -> datetime | None:
    s = (s or "").strip().rstrip(".")
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
            except ValueError:
                continue
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%m/%d/%Y")
        except ValueError:
            return None
    return None


def _parse_pdf(data: bytes) -> list[dict]:
    """Segment the PDF text into per-property records."""
    import pdfplumber

    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for ln in (page.extract_text() or "").splitlines():
                lines.append(ln.strip())

    case_idxs = [i for i, ln in enumerate(lines) if ln.upper().startswith("CASE ")]
    out: list[dict] = []
    for n, ci in enumerate(case_idxs):
        # Owner = nearest prior non-empty line that isn't the header/separator.
        owner = None
        j = ci - 1
        while j >= 0:
            lj = lines[j]
            if lj and not lj.startswith(_HEADER) and "___" not in lj and set(lj) != {"_"}:
                owner = lj
                break
            j -= 1
        end = case_idxs[n + 1] if n + 1 < len(case_idxs) else len(lines)
        block = lines[ci:end]
        text = "\n".join(block)
        rec: dict = {"owner": owner, "block": text}

        cm = _CASE_RE.match(block[0])
        if cm:
            num = _CASENUM_RE.match(cm.group(1))
            if num:
                rec["case"] = "CASE " + num.group(1).strip()
                rec["township"] = num.group(2).strip() or None
            else:
                rec["case"] = "CASE " + cm.group(1).strip()

        for ln in block[1:]:
            pm = _PIN_RE.match(ln)
            if pm and "pin" not in rec:
                rec["pin"] = pm.group(1)
                rec["address"] = pm.group(2).strip() or None

        bm = _BID_RE.search(text)
        if bm:
            rec["bid"] = _to_float(bm.group(2))
            rec["bid_kind"] = bm.group(1).upper()
        um = _UPSET_RE.search(text)
        if um:
            rec["upset"] = _parse_date(um.group(1))
        em = _EXPIRE_RE.search(text)
        if em:
            rec["expire"] = _parse_date(em.group(1))
        am = _ACRE_RE.search(text)
        if am:
            try:
                rec["acres"] = float(am.group(1))
            except ValueError:
                pass
        up = text.upper()
        rec["redeemed"] = "REDEEMED" in up
        for pt in _PROP_TYPES:
            if pt in up:
                rec["ptype"] = pt
                break
        out.append(rec)
    return out


class BuncombeTaxForeclosure(BaseScraper):
    slug = "counties_nc.buncombe_tax_foreclosure"
    name = "Buncombe County NC Tax Foreclosure (fcl.pdf)"
    category = "foreclosure"
    expected_min_count = 0  # seasonal / episodic
    requires_render = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        if os.getenv("FORECLOSURE_BUNCOMBE_FCL", "1") == "0":
            log.info("buncombe_tax_fcl.disabled")
            return []
        try:
            async with client(timeout=60) as c:
                r = await c.get(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                data = r.content
        except Exception as exc:  # never raise
            log.warning("buncombe_tax_fcl.fetch_failed", error=str(exc)[:180])
            return []

        try:
            records = _parse_pdf(data)
        except Exception as exc:
            log.warning("buncombe_tax_fcl.parse_failed", error=str(exc)[:180])
            return []

        now = datetime.utcnow()
        out: list[Listing] = []
        for rec in records:
            owner = rec.get("owner")
            addr = rec.get("address")
            pin = rec.get("pin")
            if not (addr or pin):
                continue

            upset = rec.get("upset")
            expire = rec.get("expire")
            deadline = upset or expire
            redeemed = rec.get("redeemed", False)

            raw: dict = {
                "buncombe_tax_fcl": {
                    "township": rec.get("township"),
                    "property_type": rec.get("ptype"),
                    "acreage": rec.get("acres"),
                    "bid_kind": rec.get("bid_kind"),
                    "redeemed": redeemed,
                    "block": rec.get("block", "")[:500],
                }
            }
            if redeemed:
                raw["sold_confirmed"] = True
                raw["tax_sale_status"] = "redeemed"

            desc_bits = [b for b in (rec.get("ptype"), rec.get("township")) if b]
            if rec.get("bid_kind") and rec.get("bid"):
                desc_bits.append(f"{rec['bid_kind'].title()} bid ${rec['bid']:,.0f}")
            if redeemed:
                desc_bits.append("REDEEMED")

            out.append(
                Listing(
                    source=self.slug,
                    source_url=PAGE_URL,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Buncombe",
                    street_address=addr or None,
                    city=(rec.get("township") or "").title() or None,
                    parcel_id=pin,
                    owner_name=owner or None,
                    defendant=owner or None,  # foreclosure defendant = property owner
                    case_number=rec.get("case"),
                    foreclosure_process="tax",
                    opening_bid=rec.get("bid"),
                    acreage=rec.get("acres"),
                    sale_date=deadline,
                    upset_bid_deadline=deadline,
                    auction_status="redeemed" if redeemed else None,
                    description=" | ".join(desc_bits)[:300] or None,
                    first_seen=now,
                    last_seen=now,
                    raw=raw,
                )
            )

        log.info("buncombe_tax_fcl.done", count=len(out))
        return out
