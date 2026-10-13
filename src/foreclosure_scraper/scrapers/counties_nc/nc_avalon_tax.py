"""NC Catalis Avalon tax sites — delinquent tax records via CloudFront API.

lincolncountytax.com is a Catalis Avalon (Wildfire) SPA.
The SPA loads data from a CloudFront API at:
    POST https://d1ebsyxxbc7tep.cloudfront.net/data/{guid}/Wildfire/Records
    Body: {"value":"a","skip":0,"direct":false}

Each record has an `isDelinquent` boolean — we filter for delinquent records.

Counties: Lincoln (only county with a working domain on this platform).
Other Catalis domains (rutherfordcountytax.com, etc.) are DNS-dead.

FOUND 2026-10-13 (source-completeness audit, same Catalis/Avalon Wildfire
platform as the sibling counties_nc.rutherford_wildfire_tax -- confirmed real
schema from tests/fixtures/rutherford_wildfire_records_page1.json, a genuine
captured payload): this file had two real gaps.

1. No real-estate filter at all. The request body sends no `facets` to
   restrict to Property-type bills, and nothing checked `AbstractType` client
   side either -- so a personal-property (vehicle) or business-property tax
   bill (AbstractType IND/BUS) could reach the board as a fake real-estate
   lead. The sibling file both sends a Type facet AND still filters
   AbstractType == "REI" client side; this file did neither. Fixed with a
   client-side AbstractType check only (_is_real_estate) -- CloudFront is
   currently blocking live calls to this endpoint (confirmed from both the Mac
   and the Oracle VM), so an unverified change to the request body's facets
   shape was not worth the risk; a client-side filter can only remove false
   positives, never cause a new miss.
2. `Values`/`Payment`/`IDs`/`OwnerAddress`/`Flags`/`LineItems`/`Description` on
   every record were read for one key each (or not read at all) and the rest
   silently dropped: mailing address, legal description, assessed value,
   DELINQUENT/OUTSIDE LAW FIRM/ADVERTISED flags, the levy/fee breakdown, and
   payment-history / original-amount-due signals. Fixed by extracting the
   per-record parse into _record_to_listing() (also makes it unit-testable
   without a live nodriver page) and capturing all of them, matching the
   field names and shapes already proven correct in rutherford_wildfire_tax.py.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


def _signal_block(detail: str) -> None:
    """Mark the shared per-run block holder so base_scraper.safe_run promotes
    this run's empty result to BLOCKED instead of ZERO_RESULT. This scraper's
    API calls run inside Playwright's page.evaluate(fetch(...)), which never
    goes through the shared httpx client — so the normal block-signal path
    (http_client.py's transport appending on 401/403/406/429) never fires for
    it. Without this, a CloudFront/WAF 403 on every search term was silently
    swallowed by the `except Exception: break` below and reported as a clean
    zero (confirmed live 2026-10-12: direct curl to the same CloudFront
    endpoint returns a 403 "Request blocked" page, yet the scraper's run
    logged OUTCOME_ZERO / "ran clean but returned 0 rows"). Same fix pattern
    already used by nc_ecourts_divorce.py / nc_ecourts_estates.py."""
    try:
        from ...http_client import _block_holder  # type: ignore
        holder = _block_holder.get()
        if holder is not None:
            holder.append((403, detail))
    except Exception:  # noqa: BLE001
        pass


# Only Lincoln County — other Catalis domains are DNS-dead
_COUNTY_SITES = {
    "lincoln": {
        "url": "https://www.lincolncountytax.com",
        "state": "NC",
        "guid": "a45b9ca6-46be-4396-9468-56194741a38e",
    },
}

_CLOUDFRONT_BASE = "https://d1ebsyxxbc7tep.cloudfront.net"


def _clean(v: Any) -> str | None:
    s = (str(v) if v is not None else "").replace("\x00", "").strip()
    return s or None


def _money(v: Any) -> float | None:
    try:
        f = round(float(v), 2)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _is_real_estate(rec: dict) -> bool:
    """REI = real estate; IND/BUS = personal/business property tax bills ride
    the same API with no server-side type facet in this request shape (unlike
    rutherford_wildfire_tax.py, which both sends a Type facet AND still checks
    this client side). Mirrors that file's AbstractType check exactly."""
    return (rec.get("AbstractType") or "").strip().upper() == "REI"


def _flag_labels(rec: dict) -> list[str]:
    """Human flag labels, from Flags[].Description with FlagsString as backup."""
    out: list[str] = []
    for f in rec.get("Flags") or []:
        if isinstance(f, dict):
            d = _clean(f.get("Description"))
            if d:
                out.append(d.upper())
    if not out:
        out = [t.strip().upper() for t in (rec.get("FlagsString") or "").split(",")
               if t.strip()]
    return out


def _mailing(rec: dict) -> dict[str, str | None] | None:
    a = rec.get("OwnerAddress") or {}
    if not isinstance(a, dict):
        return None
    out = {
        "addr": _clean(a.get("Line1")),
        "city": _clean(a.get("City")),
        "state": _clean(a.get("State")),
        "zip": _clean(a.get("Zip")),
    }
    return out if out["addr"] or out["city"] else None


def _slim_line_items(rec: dict) -> list[dict]:
    """Same Wildfire/Catalis platform as rutherford_wildfire_tax.py -- same
    raw LineItems shape, same 5-key subset."""
    items = rec.get("LineItems")
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append({
            "levy_type": item.get("LevyType"),
            "levy_type_description": item.get("LevyTypeDescription"),
            "taxing_unit": item.get("TaxingUnit"),
            "amount": item.get("LevyAmount"),
            "amount_due": item.get("LevyAmountDue"),
        })
    return out


def _record_to_listing(
    rec: dict, county: str, state: str, base_url: str, slug: str
) -> Listing | None:
    """Pure record -> Listing mapping, split out of _fetch_via_api so the
    parse is unit-testable without a live nodriver page. Returns None for a
    non-real-estate bill or a bill that's neither delinquent nor owing."""
    if not _is_real_estate(rec):
        return None

    values = rec.get("Values") or {}
    amount_due = values.get("AmountDue", 0)
    if not rec.get("isDelinquent", False) and not (amount_due and amount_due > 0):
        return None

    owner = rec.get("OwnerName1", "") or ""
    owner2 = rec.get("OwnerName2", "")
    if owner2:
        owner = f"{owner} / {owner2}"

    situs = rec.get("SitusAddress") or {}
    addr = situs.get("Line1", "") or ""
    city = situs.get("City", "") or ""
    zip_code = situs.get("Zip", "") or ""

    payment = rec.get("Payment") or {}
    payment_status = payment.get("Status", "")
    has_payment_history = bool(rec.get("FilePaymentHistory") or payment.get("PaymentLog"))

    parcel = rec.get("ParcelNumber", "") or ""
    bill_num = ""
    ids = rec.get("IDs") or {}
    if ids.get("ID1"):
        bill_num = ids["ID1"].get("Value", "")

    return Listing(
        source=slug,
        source_url=base_url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        street_address=addr,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county.title(),
        parcel_id=parcel,
        owner_name=owner,
        tax_value=amount_due if amount_due else None,
        market_value=_money(values.get("RealValue")),
        legal_description=_clean(rec.get("Description")),
        raw={
            "county": county,
            "amount_due": amount_due,
            "original_amount_due": _money(values.get("OriginalAmountDue")),
            "bill_number": bill_num,
            "id_hash": _clean(rec.get("IDHash")),
            "payment_status": payment_status,
            "has_payment_history": has_payment_history,
            "year": rec.get("Year"),
            "owner_id": rec.get("OwnerID"),
            "owner_mailing": _mailing(rec),
            "flags": _flag_labels(rec),
            "line_items": _slim_line_items(rec),
        },
    )


class NcAvalonTaxScraper(BaseScraper):
    """NC Catalis Avalon tax search via CloudFront Wildfire API."""

    slug = "counties_nc.nc_avalon_tax"
    name = "NC Avalon Tax (Catalis)"
    category = "tax"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        from ...browser_utils import start_browser

        browser = await start_browser(headless=True)

        for county, cfg in _COUNTY_SITES.items():
            try:
                base_url = cfg["url"]

                log.info("nc_avalon.fetching", county=county)

                page = await browser.get(base_url)
                await asyncio.sleep(8)  # Wait for SPA to load

                # Discover guid from page if not known
                guid = cfg.get("guid")
                if not guid:
                    html = await page.get_content()
                    m = re.search(
                        r"cloudfront\.net/(?:views|css|data)/([a-f0-9-]{36})",
                        html,
                    )
                    if m:
                        guid = m.group(1)
                        log.info("nc_avalon.guid_found", county=county, guid=guid)
                    else:
                        log.warning("nc_avalon.no_guid", county=county)
                        continue

                # Query the Wildfire API for delinquent records
                # nodriver bypasses CloudFront WAF (Playwright gets 403)
                county_results = await self._fetch_via_api(page, base_url, guid, county, cfg["state"])
                results.extend(county_results)

                log.info("nc_avalon.county_done", county=county, found=len(county_results))

            except Exception as exc:
                log.warning("nc_avalon.county_error", county=county, error=str(exc)[:200])

        browser.stop()
        return results

    async def _fetch_via_api(
        self, page, base_url: str, guid: str, county: str, state: str
    ) -> list[Listing]:
        """Query the Wildfire Records API and filter for delinquent records.

        Uses nodriver's page.evaluate with an async IIFE pattern (nodriver
        wraps the code in an async function body, so top-level await works
        inside an IIFE but not at the bare top level).
        """
        results: list[Listing] = []
        api_url = f"{_CLOUDFRONT_BASE}/data/{guid}/Wildfire/Records"

        # Search with broad terms to get as many delinquent records as possible
        # The API paginates with skip
        search_terms = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
                        "k", "l", "m", "n", "o", "p", "q", "r", "s", "t",
                        "u", "v", "w", "x", "y", "z"]

        seen_ids: set[str] = set()
        total_delinquent = 0

        for term in search_terms:
            skip = 0
            page_size = 20  # API default

            while True:
                try:
                    # nodriver evaluate: use async IIFE, inline params (no arg passing)
                    js = (
                        "(async () => {\n"
                        f"  const resp = await fetch({json.dumps(api_url)}, {{\n"
                        "    method: 'POST',\n"
                        "    headers: {'Content-Type': 'application/json'},\n"
                        f"    body: JSON.stringify({{value: {json.dumps(term)}, skip: {skip}, direct: false}})\n"
                        "  });\n"
                        "  const text = await resp.text();\n"
                        "  return text;\n"
                        "})()"
                    )

                    response = await page.evaluate(js, await_promise=True)

                    if not response or not isinstance(response, str):
                        break

                    try:
                        data = json.loads(response)
                    except json.JSONDecodeError:
                        # CloudFront/WAF returns an HTML error page (403, 503,
                        # etc.) instead of JSON when the request is blocked.
                        snippet = response[:200].replace("\n", " ")
                        log.warning("nc_avalon.blocked", county=county, term=term,
                                    skip=skip, body=snippet)
                        _signal_block(f"CloudFront/WAF non-JSON response: {snippet}")
                        break
                    records = data.get("Records", [])
                    total_records = data.get("TotalRecords", 0)

                    if not records:
                        break

                    for rec in records:
                        billing_id = rec.get("BillingID", "")
                        if billing_id in seen_ids:
                            continue
                        seen_ids.add(billing_id)

                        listing = _record_to_listing(rec, county, state, base_url, self.slug)
                        if listing is None:
                            continue
                        total_delinquent += 1
                        results.append(listing)

                    skip += len(records)

                    # Stop if we've gone through all records for this term
                    if skip >= total_records or len(records) < page_size:
                        break

                    # Rate limit
                    await asyncio.sleep(0.5)

                except Exception as exc:
                    log.warning("nc_avalon.api_error", county=county, term=term, skip=skip, error=str(exc)[:160])
                    break

            log.info("nc_avalon.term_done", county=county, term=term, delinquent=total_delinquent)

        return results
