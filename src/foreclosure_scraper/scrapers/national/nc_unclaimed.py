"""NC Unclaimed Property — nccash.gov Cloudflare Turnstile.

unclaimed.nccash.gov hosts NC's unclaimed property database behind a
Cloudflare Turnstile challenge. The Angular SPA calls POST /SWS/properties
with a Turnstile token.

Strategy: Playwright renders the SPA. Turnstile in managed mode auto-solves
without user interaction — we just wait for the page to settle. The Angular
app makes XHR calls to /SWS/properties — we intercept those responses.

FOUND 2026-10-13 (source-completeness audit, triggered by the owner finding
cherokee_rod.py silently missing real data): this scraper never searched a
real board name. `_SEARCH_NAMES` was a hardcoded list of 10 generic American
surnames ("Smith", "Johnson", ...), searched the same way on every run
regardless of which owners/defendants are actually on the board -- the exact
stub-data bug already found and fixed in the sibling national.people_search
on 2026-10-12 ("REAL NAMES, NOT A STUB"), never applied here. The API
searches by `lastName` only (confirmed by the POST body below, unchanged),
so the fix pulls real SURNAMES off the board's own owner/defendant names
(via the same bounded `board_stream.iter_board_rows()` people_search.py
uses, so this never materializes the whole board) instead of a fixed list.
A small ledger (`docs/handoff/nc_unclaimed_searched.json`) tracks which
surnames a run has already searched, so repeat runs cover new board names
instead of re-sampling the same ones -- the Turnstile solve is the
expensive part of a run (one per run, not per surname), so this doesn't
change the cost model, just what gets searched with it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://unclaimed.nccash.gov/app/claim-search"
_API = "https://unclaimed.nccash.gov/SWS/properties"

# Bail out of surname selection once we have this many -- a per-run sample,
# not a full-board sweep (same bound/reasoning as people_search.py).
_MAX_SURNAMES = 15

_ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|CO\b|COMPANY|"
    r"LP\b|LLP\b|TRUST|ESTATE OF|BANK|TAX COLLECTOR|COUNTY|CITY OF|"
    r"HOMEOWNERS|ASSOCIATION|HOA\b|CHURCH|MINISTR|TEMPLE|CHAPEL|"
    r"CONGREGATION|SCHOOL|ACADEMY|UNIVERSITY|FOUNDATION|MINISTRIES)",
    re.I,
)
_SEARCHED_LEDGER_PATH = Path("docs/handoff/nc_unclaimed_searched.json")


def _surname_of(name: str | None) -> str | None:
    """A cleaned surname for the `lastName` search param, or None (entity,
    blank, or too short to be worth a search). Handles both "Last, First"
    (this codebase's county-record convention) and "First Last" (the more
    common plain-English order) -- a comma means the first segment already
    IS the surname; otherwise the last whitespace-separated token is."""
    if not name:
        return None
    name = name.strip()
    if not name or _ENTITY_RE.search(name):
        return None
    if "," in name:
        surname = name.split(",", 1)[0].strip()
    else:
        parts = name.split()
        surname = parts[-1].strip() if parts else ""
    surname = re.sub(r"[^A-Za-z'\-]", "", surname)
    return surname if len(surname) >= 2 else None


def _load_searched_ledger() -> dict:
    if _SEARCHED_LEDGER_PATH.exists():
        try:
            return json.loads(_SEARCHED_LEDGER_PATH.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"schema": 1, "kind": "nc_unclaimed_searched", "surnames": {}}


def _save_searched_ledger(ledger: dict) -> None:
    ledger["generated_at"] = datetime.now(timezone.utc).isoformat()
    _SEARCHED_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SEARCHED_LEDGER_PATH.write_text(json.dumps(ledger, indent=2, sort_keys=True))


def _candidate_surnames(limit: int = _MAX_SURNAMES) -> list[str]:
    """Up to `limit` real, not-yet-searched surnames off the board's own
    owner/defendant names, via a bounded stream (never loads the whole
    board). Falls back to a handful of common NC surnames only if the board
    stream yields nothing at all (e.g. a fresh checkout with no board yet),
    so this scraper is never a hard zero."""
    from ...board_stream import iter_board_rows

    ledger = _load_searched_ledger()
    seen: set[str] = set()
    out: list[str] = []
    try:
        for row in iter_board_rows():
            if len(out) >= limit:
                break
            for field in ("owner_name", "defendant"):
                surname = _surname_of(row.get(field) if isinstance(row, dict) else None)
                if not surname:
                    continue
                key = surname.lower()
                if key in seen or key in ledger.get("surnames", {}):
                    continue
                seen.add(key)
                out.append(surname)
                if len(out) >= limit:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_unclaimed.candidate_scan_error", error=str(exc)[:200])
    if not out:
        # Board stream genuinely empty (fresh checkout) -- fall back so a
        # first run still exercises the real search path end to end.
        out = ["Smith", "Johnson", "Williams", "Brown", "Jones"][:limit]
    return out


class NcUnclaimedScraper(BaseScraper):
    """NC Unclaimed Property — Turnstile auto-solve via Playwright."""

    slug = "national.nc_unclaimed"
    name = "NC Unclaimed Property"
    category = "unclaimed"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            results = await self._fetch_with_playwright()
        except BaseException as exc:
            log.warning("nc_unclaimed.playwright_failed", error=str(exc)[:160])

        return results

    async def _fetch_with_playwright(self) -> list[Listing]:
        """Use Playwright to render the SPA, capture Turnstile token, call API directly."""
        results: list[Listing] = []
        try:
            try:
                from patchright.async_api import async_playwright
                _USE_PATCHRIGHT = True
            except ImportError:
                from playwright.async_api import async_playwright
                _USE_PATCHRIGHT = False
        except ImportError:
            log.error("nc_unclaimed.no_playwright")
            return results

        import asyncio
        import httpx

        import os
        # Use non-headless if Xvfb is available (Turnstile requires interaction)
        xvfb = os.environ.get("DISPLAY", "")
        headless = not bool(xvfb)

        if _USE_PATCHRIGHT:
            log.info("nc_unclaimed.using_patchright")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            # Capture console messages for debugging
            page.on("console", lambda msg: log.debug("nc_unclaimed.console",
                                                     level=msg.type, text=msg.text[:200]))

            await page.goto(_URL, timeout=60000)

            # Wait for Angular to bootstrap and Turnstile to load
            await asyncio.sleep(8)

            # Wait for turnstile object to be available
            try:
                await page.wait_for_function(
                    "() => typeof turnstile !== 'undefined'",
                    timeout=15000,
                )
            except Exception:
                log.warning("nc_unclaimed.no_turnstile_obj")
                await browser.close()
                return results

            # Execute Turnstile and get token
            token = None
            for attempt in range(3):
                try:
                    # First, try clicking the Turnstile checkbox directly
                    # The widget renders in an iframe — we need to click inside it
                    for frame in page.frames:
                        if "challenges.cloudflare" in (frame.url or ""):
                            try:
                                checkbox = await frame.query_selector("input[type='checkbox'], .cb-i, .mark")
                                if checkbox:
                                    box = await checkbox.bounding_box()
                                    if box:
                                        await page.mouse.click(box["x"] + box["width"]/2,
                                                                box["y"] + box["height"]/2)
                                        log.info("nc_unclaimed.turnstile_click",
                                                 attempt=attempt + 1,
                                                 x=box["x"], y=box["y"])
                                        await asyncio.sleep(5)
                                        break
                            except Exception:
                                pass

                    token = await page.evaluate("""() => {
                        try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                        const el = document.querySelector('[name="cf-turnstile-response"]');
                        if (el && el.value && el.value.length > 10) return el.value;
                        return null;
                    }""")
                    if token and len(token) > 10:
                        break

                    # Also try clicking the SEARCH button to trigger Turnstile callback
                    await page.evaluate("""() => {
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) {
                            if (b.innerText && b.innerText.toUpperCase().includes('SEARCH')) {
                                try { b.click(); } catch(e) {}
                                break;
                            }
                        }
                    }""")

                    # Wait for callback to fire after clicking SEARCH
                    await asyncio.sleep(8)
                    token = await page.evaluate("""() => {
                        try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                        const el = document.querySelector('[name="cf-turnstile-response"]');
                        if (el && el.value && el.value.length > 10) return el.value;
                        return null;
                    }""")
                    if token and len(token) > 10:
                        break
                except Exception as exc:
                    log.warning("nc_unclaimed.turnstile_exec_failed",
                                attempt=attempt + 1, error=str(exc)[:160])
                    await asyncio.sleep(3)

            if not token or len(token) < 10:
                log.warning("nc_unclaimed.no_token")
                await browser.close()
                return results

            log.info("nc_unclaimed.token_captured", token_len=len(token))

            # Now make direct API calls with the token
            surnames = _candidate_surnames()
            searched_ledger = _load_searched_ledger()
            async with httpx.AsyncClient() as client:
                for surname in surnames:
                    try:
                        resp = await client.post(
                            _API,
                            json={
                                "lastName": surname,
                                "firstName": "",
                                "city": "",
                                "searchZipCode": "",
                                "propertyID": "",
                                "cf-turnstile-response": token,
                            },
                            headers={
                                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                                "Origin": "https://unclaimed.nccash.gov",
                                "Referer": "https://unclaimed.nccash.gov/app/claim-search",
                                "Content-Type": "application/json",
                            },
                            timeout=30,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            found = self._parse_api_response(data, surname)
                            results.extend(found)
                            log.info("nc_unclaimed.surname_done",
                                     surname=surname, found=len(found),
                                     status=resp.status_code)
                            searched_ledger["surnames"][surname.lower()] = {
                                "checked_at": datetime.now(timezone.utc).date().isoformat(),
                                "found": len(found),
                            }
                        else:
                            log.warning("nc_unclaimed.api_error",
                                        surname=surname,
                                        status=resp.status_code,
                                        body=resp.text[:200])
                            searched_ledger["surnames"][surname.lower()] = {
                                "checked_at": datetime.now(timezone.utc).date().isoformat(),
                                "status": resp.status_code,
                            }
                    except Exception as exc:
                        log.warning("nc_unclaimed.surname_error",
                                    surname=surname, error=str(exc)[:160])
                        searched_ledger["surnames"][surname.lower()] = {
                            "checked_at": datetime.now(timezone.utc).date().isoformat(),
                            "error": str(exc)[:160],
                        }

            await browser.close()
            _save_searched_ledger(searched_ledger)

        return results

    def _search_via_browser(self, html: str) -> list[Listing]:
        """Parse search results from rendered HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select(
            "table tr, .results tr, .grid tr, "
            ".search-result, .property-item"
        )

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            name = cells[0].get_text(strip=True)
            addr = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            amount = cells[2].get_text(strip=True) if len(cells) > 2 else ""

            amount_val = None
            if amount:
                m = re.search(r"[\$]([\d,.]+)", amount)
                if m:
                    amount_val = float(m.group(1).replace(",", ""))

            results.append(Listing(
                source=self.slug,
                source_url=_URL,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                state="NC",
                owner_name=name,
                tax_value=amount_val,
                raw={"amount": amount},
            ))

        return results

    def _parse_api_response(self, data: dict, surname: str) -> list[Listing]:
        """Parse JSON API response from /SWS/properties."""
        results: list[Listing] = []
        items = data.get("items") or data.get("properties") or data.get("results") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("ownerName") or item.get("name") or ""
                addr = item.get("address") or item.get("address1") or ""
                amount = item.get("amount") or item.get("amountText") or ""
                amount_val = None
                if isinstance(amount, (int, float)):
                    amount_val = float(amount)
                elif amount:
                    m = re.search(r"[\$]?([\d,.]+)", str(amount))
                    if m:
                        amount_val = float(m.group(1).replace(",", ""))

                results.append(Listing(
                    source=self.slug,
                    source_url=_URL,
                    listing_type=ListingType.UNKNOWN,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr,
                    state="NC",
                    owner_name=name,
                    tax_value=amount_val,
                    raw={"surname_searched": surname, "amount": str(amount)},
                ))
        return results
