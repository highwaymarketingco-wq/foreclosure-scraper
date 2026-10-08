"""NC county delinquent-tax advertisements published as free .gov PDFs — the
full NCGS 105-369 roll for counties that self-host the list (FREE, no login).

Sibling of buncombe_delinquent_tax.py (also a PDF) and nc_ptscloud_delinquent_tax.py
(the API counties). Each county here posts its annual "Advertisement of Tax Liens
on Real Property" as a plain .gov PDF; this parses them with pypdf. One config
dict per county with a layout tag, because the three current counties render
three different line formats:

  * name_id_amt   -> "<OWNER NAME>   <ID>   <AMOUNT>"  (one row per line)
        Lincoln (ID = 4-6-digit GIS PIN), Catawba (ID = tax ACCOUNT #, not a PIN)
  * parcel_amt_owner -> a "<PARCEL>  $<AMOUNT>" line, then the owner/description
        on the NEXT line.  McDowell.

Amount is back-tax OWED -> raw (normalized to raw['tax_owed'] by
enrichment_tax_owed), NOT tax_value. Situs isn't in these lists; parcel_id
backfills the address via NC OneMap/GIS. Gate off with FORECLOSURE_NC_PDF_TAX=0.
URLs carry a tax year; when a county rolls to a new year, update the URL here.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...layer_guard import LayerHarvest
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

COUNTIES: dict[str, dict] = {
    "Lincoln": {
        "url": "https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice",
        "layout": "name_id_amt", "id_digits": (4, 6), "id_is_parcel": True,
        "tax_year": 2025,
    },
    "Catawba": {
        "url": "https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf",
        "layout": "name_id_amt", "id_digits": (1, 7), "id_is_parcel": False,  # ID = account #, not GIS PIN
        "tax_year": 2025,
    },
    "McDowell": {
        "url": "https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement/ADVERTISEMENT-LIST-FINAL-2025.pdf",
        "layout": "parcel_amt_owner", "id_is_parcel": True,
        "tax_year": 2025,
    },
}

_PARCEL_AMT_RE = re.compile(r"^([0-9A-Z]{9,15})\s+\$([\d,]+\.\d{2})$")


def _money(s: str) -> float | None:
    try:
        f = float(s.replace(",", "").replace("$", "").strip() or 0)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _clean_owner(s: str | None) -> str | None:
    s = re.sub(r"\s+", " ", (s or "")).strip().strip(";,").strip()
    return s or None


def _parse_name_id_amt(text: str, id_digits: tuple[int, int]) -> list[tuple]:
    """Rows of "<owner> <id> <amount>". Returns [(owner, id, amount)]."""
    lo, hi = id_digits
    rx = re.compile(rf"^(.+?)\s+(\d{{{lo},{hi}}})\s+([\d,]*\.?\d{{1,2}})$")
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or "Column" in s:
            continue
        m = rx.match(s)
        if not m:
            continue
        amt = _money(m.group(3))
        owner = _clean_owner(m.group(1))
        if amt and owner:
            out.append((owner, m.group(2), amt))
    return out


#: A parcel the PDF text breaks with a space ("0000 000000  $1.00"); 18 McDowell rows.
_PARCEL_AMT_SPACED_RE = re.compile(r"^([0-9A-Z][0-9A-Z ]{7,18}[0-9A-Z])\s{2,}\$([\d,]+\.\d{2})$")
#: The list's own column-header lines, never an owner.
_HEADER_RE = re.compile(r"^(OWNER[- ]NAME|PARCEL\s+TOTAL DUE)\b", re.I)


def _parcel_amt(ln: str):
    m = _PARCEL_AMT_RE.match(ln) or _PARCEL_AMT_SPACED_RE.match(ln)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1)), m.group(2)


def _parse_parcel_amt_owner(text: str) -> list[tuple]:
    """"<parcel> $<amount>" lines, each paired with its owner line.

    FIXED 2026-10-07 (extraction audit): the McDowell list prints the OWNER on the line
    BEFORE its "<parcel> $<amount>" line (header "OWNER-NAME" / "PARCEL ... TOTAL DUE",
    then owner, parcel, owner, parcel ...). Reading the NEXT line gave every row the
    following parcel's owner: right only where two neighbours share an owner (544 of
    2,260 live rows). The orientation is read from the document itself: when the first
    parcel line follows the header directly, the owner comes after (the older layout this
    parser was written for); otherwise the owner is the text between the previous parcel
    line and this one (a wrapped name is joined)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    hits = [(i, _parcel_amt(ln)) for i, ln in enumerate(lines)]
    hits = [(i, h) for i, h in hits if h]
    if not hits:
        return []
    first = hits[0][0]
    owner_after = first == 0 or bool(_HEADER_RE.match(lines[first - 1]))
    out = []
    prev = -1
    for n, (i, (parcel, amt_s)) in enumerate(hits):
        amt = _money(amt_s)
        if owner_after:
            nxt = hits[n + 1][0] if n + 1 < len(hits) else len(lines)
            block = lines[i + 1:nxt]
        else:
            block = lines[prev + 1:i]
        prev = i
        owner = _clean_owner(" ".join(b for b in block if not _HEADER_RE.match(b)))
        if amt:
            out.append((owner, parcel, amt))
    return out


def _to_listing(owner, ident, amt, county, cfg) -> Listing:
    now = datetime.utcnow()
    return Listing(
        source="counties_nc.nc_county_pdf_delinquent_tax",
        source_url=cfg["url"],
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        owner_name=owner,
        defendant=owner,
        # Always set parcel_id — it's the county's unique identifier and the
        # dedup key. For Catawba it's a tax ACCOUNT # (not a GIS PIN), flagged
        # id_is_parcel=False in raw so GIS-by-parcel knows to skip it; without a
        # parcel_id every Catawba row would collapse to the shared source_url.
        parcel_id=ident,
        foreclosure_process="tax",
        description=(f"{owner or ''} — {county} NC delinquent tax "
                     f"${amt:,.0f} owed ({ident})")[:300],
        first_seen=now,
        last_seen=now,
        raw={
            "nc_county_pdf_delinquent_tax": {
                "county": county,
                "county_id": ident,      # PIN (Lincoln/McDowell) or account # (Catawba)
                "id_is_parcel": cfg.get("id_is_parcel", False),
                "principal_tax_due": round(amt, 2),  # OWED, not value
                "tax_year": cfg.get("tax_year"),
                "owner": owner,
            }
        },
    )


class NCCountyPdfDelinquentTax(BaseScraper):
    slug = "counties_nc.nc_county_pdf_delinquent_tax"
    name = "NC County Delinquent-Tax PDF Advertisements (Lincoln/Catawba/McDowell)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_NC_PDF_TAX") == "0":
            return []
        out: list[Listing] = []
        # Each county is a four-figure block of leads behind ONE annual PDF, so a
        # county that 404s or quietly stops parsing leaves a hole big enough to
        # pass for normal week-to-week shrinkage. Declare the set and fail loud:
        # a moved document becomes a reported error, not a smaller number.
        # LayerHarvest is a SYNC context manager; putting it in the `async with`
        # header raises TypeError at runtime, which is exactly the kind of break
        # a test that only exercises the helpers will not catch.
        guard = LayerHarvest(self.slug, list(COUNTIES))
        async with client(timeout=40.0) as c:
            with guard:
                for county, cfg in COUNTIES.items():
                    out.extend(await guard.harvest(
                        county, self._county_fetcher(c, county, cfg)))
        return out

    @staticmethod
    def _county_fetcher(c, county: str, cfg: dict):
        """Zero-arg callable for one county, so LayerHarvest can retry it."""
        async def _one() -> list[Listing]:
            r = await c.get(cfg["url"], headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                raise RuntimeError(f"{county}: HTTP {r.status_code}")
            if r.content[:4] != b"%PDF":
                raise RuntimeError(
                    f"{county}: response is not a PDF (starts {r.content[:16]!r}) "
                    "— the county most likely moved the document")
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "")
                             for p in PdfReader(io.BytesIO(r.content)).pages)
            if cfg["layout"] == "name_id_amt":
                rows = _parse_name_id_amt(text, cfg["id_digits"])
            else:
                rows = _parse_parcel_amt_owner(text)
            leads = _aggregate(rows, county, cfg)
            log.info("nc_pdf_tax.county_done", county=county, leads=len(leads),
                     lines=len(rows))
            return leads

        return _one


def _aggregate(rows: list[tuple], county: str, cfg: dict) -> list[Listing]:
    """One lead per id, with EVERY advertised line under it summed.

    FIXED 2026-10-08 (source-completeness audit; extraction audit 2026-10-07 section 3): this
    used to keep the FIRST line of an id and drop the rest. Catawba's id is the taxpayer's
    ACCOUNT number, and an account that owns several parcels is advertised once per parcel
    (account 12391 had three liens: $56.94, $504.82, $56.45), so 42 advertised liens on 28
    accounts never reached principal_tax_due (live list 2026-10-08: 5,298 lines, 5,256
    accounts). McDowell repeats 4 parcels the same way. Each line is its own lien in a
    105-369 advertisement, so the lines are summed and kept in raw['...']['lines']."""
    groups: dict[str, list[tuple]] = {}
    for owner, ident, amt in rows:
        groups.setdefault(ident, []).append((owner, ident, amt))
    out: list[Listing] = []
    for ident, grp in groups.items():
        owner = next((o for o, _, _ in grp if o), None)
        total = round(sum(a for _, _, a in grp), 2)
        li = _to_listing(owner, ident, total, county, cfg)
        if len(grp) > 1:
            blk = li.raw["nc_county_pdf_delinquent_tax"]
            blk["lines"] = [{"owner": o, "amount": round(a, 2)} for o, _, a in grp]
            blk["line_count"] = len(grp)
        out.append(li)
    return out
