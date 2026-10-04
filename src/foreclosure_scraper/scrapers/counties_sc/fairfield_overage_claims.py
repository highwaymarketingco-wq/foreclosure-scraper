"""Fairfield County SC — Tax Sale Overage Claim List.

Fairfield County publishes a live-maintained, multi-year PDF of unclaimed
tax-sale surplus funds: when a delinquent parcel sells at auction for MORE
than the taxes owed, the excess ("overage") is owed back to the FORMER
owner. Same mechanism as counties_sc.york_overage_claims /
counties_sc.orangeburg_overage_claims / counties_sc.laurens_overage_claims.

  https://www.fairfieldsc.com/departments/tax-collector
  -> "Tax Sale Overage List & Public Records Notice"
     https://www.fairfieldsc.com/uploads/uploads/Tax_Sale_Overage_List___Public_Records_Notice.pdf

Verified live 2026-10-04 (real fetch + pypdf extraction, not assumed): a
TEXT-layer PDF, 4 pages. Page 1 is a disclaimer/public-records notice (no
data). Pages 2-4 carry four tax-sale years' rosters (11-1-2021, 11-7-2022,
11-13-2023, 11-18-2024), ~60 real claimant rows total, grouped under
"Tax Sale MM-DD-YYYY" headers with a repeated
"Owners Name on record at time of Tax Sale  MAP#  OVERAGE AMT" column
header and "TAX SALE OVERAGE CLAIM LISTING" / "According To State Law..."
boilerplate block between groups.

UNLIKE York's three-LINE-per-record shape (NAME, then MAP#, then $AMOUNT on
separate lines), Fairfield prints all three on ONE line:
    "ADAMS, JAMES  170-00-00-058-000 $17.51"
Map numbers are a fixed 5-segment TMS (3-2-2-3-3, e.g. "170-00-00-058-000"),
distinct from Laurens/Orangeburg/Calhoun's 4-segment TMS. A handful of 2023+
rows carry a space after "$" ("$ 3737.01") -- handled by the amount regex's
`\\s*` after the dollar sign.

NOT a property-acquisition lead (same caveat as York's docstring) -- the
claimant already lost the property at the tax sale; it is owned by whoever
bought it at auction. The parcel/claimant pair is still a real, actionable
lead for the overage fund itself.

No situs lookup: Fairfield's county GIS (qPublic) sits behind a Cloudflare
challenge and is not one of the counties cached in parcel_cache.py (see that
module's own comment on "Fairfield (qPublic behind a Cloudflare
challenge)"), so street_address is left unset.

Free, public, no login, no CAPTCHA, no disclaimer click-through required to
reach this document (the page 1 "disclaimer" is informational only, part of
the same PDF -- there is no gate before downloading it, unlike Aiken's
blank-form-only page, see york_overage_claims.py's sibling investigation
note in docs/HERMES.md's 2026-10-04 history).

Slug: counties_sc.fairfield_overage_claims
Category: county_tax
ListingType: TAX_SALE_OVERAGE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

HUB_URL = "https://www.fairfieldsc.com/departments/tax-collector"
#: Direct fallback, live-verified 2026-10-04, used only if hub-page discovery
#: (which reads the real <a> off the live page) fails outright.
FALLBACK_DOC_URL = (
    "https://www.fairfieldsc.com/uploads/uploads/"
    "Tax_Sale_Overage_List___Public_Records_Notice.pdf"
)

TMS_RE = re.compile(r"\b\d{3}-\d{2}-\d{2}-\d{3}-\d{3}\b")
AMOUNT_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")
SALE_DATE_RE = re.compile(r"Tax\s+Sale\s+(\d{1,2}-\d{1,2}-\d{4})", re.I)


def parse_overage_text(text: str) -> list[dict]:
    """Parse NAME / MAP# / $AMOUNT one-line-per-record rows out of the
    extracted PDF text, tracking the current "Tax Sale MM-DD-YYYY" header.

    A line is only treated as a data row when it contains BOTH a TMS-shaped
    token and a dollar amount after it -- the repeated column-header and
    boilerplate disclaimer lines between tax-sale groups contain neither, so
    they drop out with no explicit skip list needed."""
    records: list[dict] = []
    current_sale_date: str | None = None
    for raw_line in (text or "").splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        sm = SALE_DATE_RE.search(line)
        if sm:
            current_sale_date = sm.group(1)
            continue
        tm = TMS_RE.search(line)
        if not tm:
            continue
        am = AMOUNT_RE.search(line, tm.end())
        if not am:
            continue
        name = line[:tm.start()].strip()
        if not name:
            continue
        try:
            amount = float(am.group(1).replace(",", ""))
        except ValueError:
            continue
        records.append({
            "name": name,
            "map_number": tm.group(0),
            "amount": amount,
            "tax_sale_date": current_sale_date,
        })
    return records


async def _discover_doc_url(c: httpx.AsyncClient) -> str:
    """Read the real 'Overage List' href off the live Tax Collector page,
    deliberately skipping the sibling 'Overage Claim Form' link (a blank
    form, not a roster). Falls back to FALLBACK_DOC_URL if the page is
    unreachable or no longer carries a matching link."""
    try:
        resp = await c.get(HUB_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("fairfield_overage.hub_fetch_fail", error=str(exc)[:160])
        return FALLBACK_DOC_URL
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(resp.text)
    except Exception:  # noqa: BLE001
        return FALLBACK_DOC_URL
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "") or ""
        label = (a.attributes.get("aria-label", "") or a.text(strip=True) or "")
        if not href or not re.search(r"overage\s*list", label, re.I):
            continue
        if re.search(r"claim\s*form", label, re.I):
            continue  # the blank claim form, not the roster
        return urljoin(str(resp.url), href)
    return FALLBACK_DOC_URL


class FairfieldOverageClaims(BaseScraper):
    slug = "counties_sc.fairfield_overage_claims"
    name = "Fairfield County SC Overage Claim List"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 30
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as c:
            doc_url = await _discover_doc_url(c)
            try:
                resp = await c.get(doc_url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                data = resp.content
            except Exception as exc:  # noqa: BLE001
                log.warning("fairfield_overage.doc_fetch_fail", url=doc_url, error=str(exc)[:160])
                return out

        if data[:4] != b"%PDF":
            log.warning("fairfield_overage.not_pdf", url=doc_url, head=data[:8])
            return out

        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as exc:  # noqa: BLE001
            log.warning("fairfield_overage.pdf_parse_fail", error=str(exc)[:160])
            return out

        records = parse_overage_text(text)
        now = datetime.utcnow()
        seen: set[str] = set()
        for rec in records:
            if rec["amount"] <= 0:
                continue
            key = f"{rec['map_number']}|{rec['tax_sale_date']}"
            if key in seen:
                continue
            seen.add(key)

            # sale_date intentionally left unset -- it would be the PAST
            # parcel auction date (2021-2024), and _active_only() in main.py
            # would drop every row as a stale upcoming sale. The claim
            # itself has no expiry the source publishes (a standing
            # condition, not a scheduled event), same reasoning as every
            # sibling overage scraper. Original tax-sale date preserved in
            # raw instead. See this slug's entry in
            # main.py.DATELESS_OK_SOURCES.
            out.append(Listing(
                source=self.slug,
                source_url=doc_url,
                listing_type=ListingType.TAX_SALE_OVERAGE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Fairfield",
                parcel_id=rec["map_number"],
                owner_name=rec["name"],
                description=(f"Tax-sale overage of ${rec['amount']:,.2f} owed to former "
                             f"owner {rec['name']} (parcel {rec['map_number']}, sold at the "
                             f"{rec['tax_sale_date'] or 'unknown-date'} tax sale)."),
                first_seen=now,
                last_seen=now,
                raw={"tax_sale_overage": {
                    "amount": rec["amount"],
                    "tax_sale_date": rec["tax_sale_date"],
                    "map_number": rec["map_number"],
                }},
            ))

        log.info("fairfield_overage.done", parsed=len(records), usable=len(out))
        return out


if __name__ == "__main__":
    # Manual smoke: uv run python -m foreclosure_scraper.scrapers.counties_sc.fairfield_overage_claims
    import asyncio

    async def _main() -> None:
        s = FairfieldOverageClaims()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:20]:
            print(" -", r.parcel_id, "|", r.owner_name, "| $",
                  r.raw.get("tax_sale_overage", {}).get("amount"), "|",
                  r.raw.get("tax_sale_overage", {}).get("tax_sale_date"))

    asyncio.run(_main())
