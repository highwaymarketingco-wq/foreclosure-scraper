"""York County SC — Tax Sale Overage Claim List.

York County publishes a live-maintained PDF of unclaimed tax-sale surplus:
when a delinquent parcel sells at auction for MORE than the taxes owed, the
excess ("overage") is owed back to the FORMER owner. The county does not
proactively track them down; claims sit until someone files for them.

  https://www.yorkcountysc.gov/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST

Verified live 2026-09-14: 3-page text PDF (not scanned), footer stamped
"**UPDATED 8/11/26**", $296-$52,676 per claim across 5 tax-sale years
(2021-2024). Grouped under "Tax Sale <date>" headers; each record is three
lines — NAME, then MAP# (dashed TMS, matches York's parcel-cache key format),
then $OVERAGE AMT. A strict line-shape state machine parses this (validates
the TMS and dollar patterns on every line) rather than assuming position,
since a malformed row would otherwise attribute one claimant's amount to
the next claimant's name.

IMPORTANT — this is NOT a property-acquisition lead. The claimant already
lost the property; someone else owns it now (confirmed live: PDF claimant
ANDREWS MINERVA W ETAL / 070-09-01-017 vs parcel-cache current owner TORRES
JUAN C GARCIA at the same TMS). The situs address is pulled from the parcel
cache for CONTEXT only (identifies which property the claim came from); the
cache's owner/owner_mailing/value/sqft belong to the current owner and are
deliberately NOT copied onto this listing — see the matching guards added
2026-09-14 in join_parcel_cache_to_board.py, enrichment_gis_attrs.py,
enrichment_owner_mailing.py and enrichment_arcgis.py, all of which resolve
person data FROM a parcel/address and would otherwise silently attach the
current owner's mailing address under the claimant's name.

Free, public, no login, no CAPTCHA.
Slug: counties_sc.york_overage_claims
Category: county_tax
ListingType: TAX_SALE_OVERAGE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...parcel_cache import lookup as _parcel_lookup

log = structlog.get_logger()

PDF_URL = "https://www.yorkcountysc.gov/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST"

MAP_RE = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}$")
AMOUNT_RE = re.compile(r"^\$[\d,]+\.\d{2}$")
SALE_DATE_RE = re.compile(r"Tax\s+Sale\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
HEADER_RE = re.compile(r"^(NAME|MAP\s*#?|OVERAGE\s*AMT)$", re.I)
FOOTER_RE = re.compile(r"\*\*\s*UPDATED", re.I)


def _clean_amount(s: str) -> float:
    return float(s.replace("$", "").replace(",", ""))


def parse_overage_pdf(text: str) -> list[dict]:
    """Parse the NAME / MAP# / $AMOUNT triples out of the extracted PDF text.

    Strict state machine: NAME -> MAP# -> AMOUNT -> (repeat). A line that
    fails the expected shape at the MAP# or AMOUNT step drops the pending
    record (never guesses) and resumes scanning for the next NAME, so one
    malformed row can't smear its neighbor's data across two claimants.
    """
    records: list[dict] = []
    current_sale_date: str | None = None
    state = "name"
    pending_name: str | None = None
    pending_map: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = SALE_DATE_RE.search(line)
        if m:
            current_sale_date = m.group(1)
            state = "name"
            pending_name = pending_map = None
            continue
        if HEADER_RE.match(line) or FOOTER_RE.search(line):
            continue

        if state == "name":
            # A stray MAP#/AMOUNT line while expecting a name means the
            # previous record never completed cleanly — drop it and keep
            # scanning rather than misattributing it.
            if MAP_RE.match(line) or AMOUNT_RE.match(line):
                continue
            pending_name = line
            state = "map"
        elif state == "map":
            if not MAP_RE.match(line):
                log.warning("york_overage.bad_map_line", after_name=pending_name, line=line[:60])
                state = "name"
                pending_name = pending_map = None
                # Re-try this line as a fresh NAME in case it's actually the
                # next record's name (a header/footer variant we didn't
                # recognize), rather than losing it entirely.
                if not MAP_RE.match(line) and not AMOUNT_RE.match(line):
                    pending_name = line
                    state = "map"
                continue
            pending_map = line
            state = "amount"
        elif state == "amount":
            if not AMOUNT_RE.match(line):
                log.warning("york_overage.bad_amount_line", name=pending_name,
                            map_number=pending_map, line=line[:60])
                state = "name"
                pending_name = pending_map = None
                continue
            records.append({
                "name": pending_name,
                "map_number": pending_map,
                "amount": _clean_amount(line),
                "tax_sale_date": current_sale_date,
            })
            state = "name"
            pending_name = pending_map = None

    return records


def _situs_for(map_number: str) -> dict | None:
    try:
        return _parcel_lookup("York", map_number, "SC")
    except Exception:  # noqa: BLE001 — situs is a nice-to-have, never fatal
        return None


class YorkOverageClaims(BaseScraper):
    slug = "counties_sc.york_overage_claims"
    name = "York County SC Overage Claim List"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 50
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as c:
                resp = await c.get(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                pdf_bytes = resp.content
        except Exception as exc:
            log.warning("york_overage.fetch_fail", error=str(exc)[:160])
            return out

        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            log.warning("york_overage.pdf_parse_fail", error=str(exc)[:160])
            return out

        records = parse_overage_pdf(text)
        now = datetime.utcnow()
        for rec in records:
            name = (rec["name"] or "").strip()
            if not name or name.upper() == "UNKNOWN":
                continue  # no claimant to search for — not a usable lead
            map_number = rec["map_number"]

            situs = _situs_for(map_number)
            street_address = situs.get("address") if situs else None

            # sale_date intentionally left unset: it would be the date the
            # PARCEL sold at auction (2021-2024, all in the past), and
            # _active_only() in main.py reads sale_date as an upcoming/recent
            # AUCTION to keep alive, not a standing condition — a past date
            # there gets every row dropped as stale. The claim itself has no
            # expiry the source publishes, matching the "standing condition,
            # not a scheduled event" dateless sources already whitelisted in
            # main.py.DATELESS_OK_SOURCES (fairfield/york/saluda delinquent
            # tax). The original tax-sale date is preserved in raw instead.
            out.append(Listing(
                source=self.slug,
                source_url=PDF_URL,
                listing_type=ListingType.TAX_SALE_OVERAGE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="York",
                parcel_id=map_number,
                owner_name=name,
                street_address=street_address,
                description=(f"Tax-sale overage of ${rec['amount']:,.2f} owed to former "
                             f"owner {name} (parcel {map_number}, sold at the "
                             f"{rec.get('tax_sale_date') or 'unknown-date'} tax sale)."),
                first_seen=now,
                last_seen=now,
                raw={"tax_sale_overage": {
                    "amount": rec["amount"],
                    "tax_sale_date": rec.get("tax_sale_date"),
                    "map_number": map_number,
                }},
            ))

        log.info("york_overage.done", parsed=len(records), usable=len(out))
        return out
