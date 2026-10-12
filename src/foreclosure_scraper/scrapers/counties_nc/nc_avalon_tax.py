"""NC Catalis Avalon tax sites — delinquent tax records via CloudFront API.

lincolncountytax.com is a Catalis Avalon (Wildfire) SPA.
The SPA loads data from a CloudFront API at:
    POST https://d1ebsyxxbc7tep.cloudfront.net/data/{guid}/Wildfire/Records
    Body: {"value":"a","skip":0,"direct":false}

Each record has an `isDelinquent` boolean — we filter for delinquent records.

Counties: Lincoln (only county with a working domain on this platform).
Other Catalis domains (rutherfordcountytax.com, etc.) are DNS-dead.
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


class NcAvalonTaxScraper(BaseScraper):
    """NC Catalis Avalon tax search via CloudFront Wildfire API."""

    slug = "counties_nc.nc_avalon_tax"
    name = "NC Avalon Tax (Catalis)"
    category = "tax"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for county, cfg in _COUNTY_SITES.items():
                try:
                    base_url = cfg["url"]
                    search_url = f"{base_url}/List/Delinquent"

                    log.info("nc_avalon.fetching", county=county)

                    page = await browser.new_page()
                    try:
                        await page.goto(search_url, timeout=45000)
                        await page.wait_for_load_state("networkidle", timeout=20000)

                        # Accept disclaimer
                        accept_btn = page.locator("button:has-text('Accept')")
                        if await accept_btn.count() > 0:
                            await accept_btn.first.click()
                            await asyncio.sleep(2)

                        # Close tips modal
                        close_btn = page.locator("button:has-text('Close')")
                        if await close_btn.count() > 0:
                            await close_btn.first.click()
                            await asyncio.sleep(1)
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(1)

                        # Discover guid from page if not known
                        guid = cfg.get("guid")
                        if not guid:
                            html = await page.content()
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
                        # Try different search terms to find delinquent records
                        # The API returns all records, we filter by isDelinquent
                        county_results = await self._fetch_via_api(page, base_url, guid, county, cfg["state"])
                        results.extend(county_results)

                        log.info("nc_avalon.county_done", county=county, found=len(county_results))

                    finally:
                        await page.close()

                except Exception as exc:
                    log.warning("nc_avalon.county_error", county=county, error=str(exc)[:200])

            await browser.close()

        return results

    async def _fetch_via_api(
        self, page, base_url: str, guid: str, county: str, state: str
    ) -> list[Listing]:
        """Query the Wildfire Records API and filter for delinquent records."""
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
                    response = await page.evaluate(
                        """async (params) => {
                            const resp = await fetch(params.url, {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                                body: JSON.stringify({
                                    value: params.term,
                                    skip: params.skip,
                                    direct: false
                                })
                            });
                            return await resp.text();
                        }""",
                        {"url": api_url, "term": term, "skip": skip},
                    )

                    if not response:
                        break

                    try:
                        data = json.loads(response)
                    except json.JSONDecodeError:
                        # CloudFront/WAF returns an HTML error page (403, 503,
                        # etc.) instead of JSON when the request is blocked.
                        # That is NOT the same as "API returned {}" — surface
                        # it as a block, not a clean zero.
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

                        if not rec.get("isDelinquent", False):
                            # Also check AmountDue > 0 — taxes owed but not yet delinquent
                            values = rec.get("Values", {})
                            amount_due = values.get("AmountDue", 0)
                            if not amount_due or amount_due <= 0:
                                continue

                        total_delinquent += 1

                        # Extract fields
                        owner = rec.get("OwnerName1", "")
                        owner2 = rec.get("OwnerName2", "")
                        if owner2:
                            owner = f"{owner} / {owner2}"

                        addr_obj = rec.get("SitusAddress", {})
                        addr = addr_obj.get("Line1", "")
                        city = addr_obj.get("City", "") or ""
                        zip_code = addr_obj.get("Zip", "") or ""

                        values = rec.get("Values", {})
                        amount_due = values.get("AmountDue", 0)

                        payment = rec.get("Payment", {})
                        payment_status = payment.get("Status", "")

                        parcel = rec.get("ParcelNumber", "")
                        bill_num = ""
                        ids = rec.get("IDs", {})
                        if ids.get("ID1"):
                            bill_num = ids["ID1"].get("Value", "")

                        results.append(Listing(
                            source=self.slug,
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
                            raw={
                                "county": county,
                                "amount_due": amount_due,
                                "bill_number": bill_num,
                                "payment_status": payment_status,
                                "year": rec.get("Year"),
                                "owner_id": rec.get("OwnerID"),
                            },
                        ))

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
