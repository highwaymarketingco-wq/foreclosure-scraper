"""Rowan County NC deeds — Cott eSearch via Playwright (guest session).

rod.rowancountync.gov/external is a Cott Systems "eSearch" app. Live-verified
2026-10-13: it redirects straight to an account login page
(``/external/User/Login.aspx``) — NOT a WAF/CAPTCHA challenge. The previous
version of this scraper sniffed the page for "challenge"/"turnstile"/
"aws-waf" text (none of which is ever present on a plain login page) and then
tried a handful of generic date-input CSS selectors against whatever page it
was stuck on, so every run silently returned 0 rows forever.

The login page carries a real "Sign in as a Guest" button that grants full,
free, anonymous read access — no credentials, no CAPTCHA (confirmed live) —
to the index, the per-document "Document Details" page (grantors, grantees,
"Returned To" filer address, full property/legal description — the same
richer-detail-page shape the Cherokee SC audit finding was named for), and a
free HTML5 image viewer with no shopping-cart/purchase prompt (confirmed live
on a sampled DEED: "Save Document as PDF"/"Save Document as Image" buttons,
no "confirm your purchase" gate). This is the SAME guest-access pattern
``rod/doc_images.py`` already documents for Cott RecordRoom (SC Union).

Guest session flow (live-verified 2026-10-13):
  1. GET  /external                          -> redirects to Login.aspx
  2. click "Sign in as a Guest"              -> SrchName.aspx (Quick Name Search)
  3. click "Date Range" (the search-type nav)-> SrchDate.aspx
  4. pick Index Type = CONSOLIDATED REAL PROPERTY (land records; excludes
     the births/deaths/marriages this same install also indexes), fill
     From/Thru (Cott enforces a HARD 30-day span cap -- a wider range
     fails client-side JS validation with an alert and never posts) --
     live-confirmed 2026-10-13 this order matters: selecting Index Type
     (or Kind) fires its own ``__doPostBack`` that reloads the panel and
     wipes any From/Thru value already set, so dates must be the LAST
     thing filled before Search. Kind is deliberately left UNSET at the
     search level -- live-confirmed 2026-10-13 that selecting a Kind
     listbox option corrupts the page's own date-range validator (a
     search with valid 28-day dates set AFTER a Kind selection reliably
     fails the page's "valid date range" JS check, even though the exact
     same dates set with no Kind selection succeed) -- so this fetches
     every Index=CRP kind in the window and filters to deed-like kinds
     in Python afterward (``_is_deed_kind``), where it's free and can't
     corrupt any page state.
  5. the real results grid (table id ``...cpgvInstruments``) is a normal
     ASP.NET GridView -- NOT the generic ``table tr`` the old code guessed at
  6. each row's Book/Page cell is a ``__doPostBack`` link to a real
     "Document Details" page (``DocumentDetails.aspx?BaseFileNumb=...
     &ImageID=...``); clicking it is a genuine browser navigation (confirmed
     live: the resulting URL is independently re-fetchable with the same
     session cookie, and the browser Back button reliably returns to the
     exact same results grid), so a budget-capped click/parse/go_back loop
     per row is safe.

The document IMAGE itself (the HTML5Viewer's actual page bitmap) is served
through a LEADTOOLS viewer via a session-scoped
``wscottfilexfer.asmx/Load?requestID=...`` call, architecturally closer to
rod/logan.py's session-scoped ``view_image.php?key=`` (dies outside the
request that rendered it) than to anderson_acpass_deeds.py's durable
``/OPTICAL/*.PDF`` link. Replicating the LEADTOOLS tile-loading protocol
well enough to pull real bytes is a separate, larger project (same scope
boundary ``enrichment_doc_ocr.py`` already draws elsewhere in this
codebase) — out of scope here. What this file now captures instead is every
non-image field the audit's Cherokee finding was about: the Document
Details page's Returned-To filer, full Grantors/Grantees party lists and
Property Information/legal description, plus a reference link to that
Details page (``raw['rowan_detail']['detail_url']``) for a human (or a
future image-fetch pass) to follow directly.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://rod.rowancountync.gov/external"
# Cott's own client-side validator rejects a span over 30 days ("Please enter
# a valid date range. The maximum range allowed is 30 days...", live-caught
# 2026-10-13); 28 keeps margin for any inclusive-endpoint off-by-one.
_LOOKBACK_DAYS = 28
# Document Details is a second full navigation per row (click + parse + back)
# on top of the search itself -- budget-capped so a high-volume window can't
# turn one run into an hours-long crawl (same convention as
# anderson_acpass_deeds.py's _MAX_DETAIL_FETCHES / _MAX_IMAGE_FETCHES).
_MAX_DETAIL_FETCHES = 40
_RESULTS_TABLE_ID_SUFFIX = "cpgvInstruments"

# Kind is left unselected at the search level (see module docstring); this
# filters the resulting Index=CRP grid (every recorded-instrument kind --
# deeds, mortgages, satisfactions, liens, judgments, affidavits, ...) down to
# the deed-conveyance kinds this scraper exists for. Rowan's real Kind code
# list (live-captured 2026-10-13): bare "DEED" plus several slash-suffixed
# conveyance abbreviations that don't contain the substring "DEED" at all.
_DEED_KIND_SUBSTRING = "DEED"
_DEED_KIND_EXACT = {"TRS/D", "ADMR/D", "COMR/D", "EXR/ DEED"}


def _is_deed_kind(kind: str | None) -> bool:
    k = (kind or "").strip().upper()
    return _DEED_KIND_SUBSTRING in k or k in _DEED_KIND_EXACT


def _cell_lines(td) -> list[str]:
    """Text of each nested-table row inside a search-grid party/description
    cell (Cott renders one name/description line per ``<tr><td colspan=2>``)."""
    lines = [t.get_text(strip=True) for t in td.select("table tr td")]
    return [t for t in lines if t]


def _parse_results(html: str) -> list[dict[str, Any]]:
    """Parse the real Cott eSearch Date Range results grid (table id ending
    in ``cpgvInstruments``) into row dicts. Returns [] when the page isn't
    actually the results grid (login page, empty search, etc.)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=lambda i: bool(i) and i.endswith(_RESULTS_TABLE_ID_SUFFIX))
    if not table:
        return []
    out: list[dict[str, Any]] = []
    for tr in table.select("tbody > tr"):
        classes = tr.get("class") or []
        if not any(c.startswith("cottPagedGridViewRowStyle") or c.startswith("cottPagedGridViewAltRowStyle")
                   for c in classes):
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 11:
            continue
        bp_link = tds[8].find("a")
        images_count = None
        if len(tds) > 11:
            m = re.search(r"\d+", tds[11].get_text())
            images_count = int(m.group()) if m else None
        out.append({
            "date_filed": tds[1].get_text(strip=True),
            "index_type": tds[2].get_text(strip=True),
            "kind": tds[3].get_text(strip=True),
            "grantors": _cell_lines(tds[4]),
            "grantees": _cell_lines(tds[5]),
            "description": " ".join(_cell_lines(tds[6])),
            "book_page": bp_link.get_text(strip=True) if bp_link else tds[8].get_text(strip=True),
            "ref": tds[9].get_text(strip=True),
            "amount": tds[10].get_text(strip=True),
            "images_count": images_count,
            "detail_link_id": bp_link.get("id") if bp_link else None,
        })
    return out


def _parse_detail(html: str) -> dict[str, Any]:
    """Parse a Document Details page: Returned To (filer) address, full
    Grantors/Grantees party lists, and Property Information/legal
    description -- the richer per-record detail the search grid truncates."""
    soup = BeautifulSoup(html, "html.parser")
    info: dict[str, Any] = {}

    rt = soup.find(id=lambda i: bool(i) and i.endswith("gvReturnToInformation"))
    if rt:
        cells = rt.select("tr.GridView_Row td")
        labels = ("returned_to", "address", "address2", "city", "state", "zip")
        vals = {lab: cells[i].get_text(strip=True) for i, lab in enumerate(labels) if i < len(cells)}
        if any(vals.values()):
            info["returned_to"] = vals

    g1 = soup.find(id=lambda i: bool(i) and i.endswith("gvParties1"))
    if g1:
        info["grantors"] = [td.get_text(strip=True) for td in g1.select("tr.GridView_Row td")
                            if td.get_text(strip=True)]

    g2 = soup.find(id=lambda i: bool(i) and i.endswith("gvParties2"))
    if g2:
        info["grantees"] = [td.get_text(strip=True) for td in g2.select("tr.GridView_Row td")
                            if td.get_text(strip=True)]

    prop = soup.find(id=lambda i: bool(i) and i.endswith("gvProperty"))
    if prop:
        td = prop.select_one("tr.GridView_Row td")
        if td:
            info["property_info"] = td.get_text(separator=" ", strip=True)

    return info


def _to_listing(slug: str, row: dict[str, Any]) -> Listing:
    book_page = row.get("book_page") or ""
    detail = row.get("detail") or {}
    # Prefer the Document Details page's full party lists -- the search-grid
    # cell truncates to whatever rendered in its nested table; fall back to
    # the grid values when the detail fetch was skipped (budget) or failed.
    grantor_names = detail.get("grantors") or row.get("grantors") or []
    grantee_names = detail.get("grantees") or row.get("grantees") or []

    raw: dict[str, Any] = {
        # Flat keys already RAW_KEEP'd for this file (web_artifact.py's
        # shared "county"/"doc_type"/"grantor"/"grantee"/"book_page" block
        # names nc_rowan_cott explicitly) -- unchanged from before this fix.
        "doc_type": row.get("kind"),
        "filing_date": row.get("date_filed"),
        "grantor": "; ".join(grantor_names) or None,
        "grantee": "; ".join(grantee_names) or None,
        "book_page": book_page or None,
        "amount": row.get("amount") or None,
        # Everything new this fix adds is nested under one block-name key so
        # it needs exactly ONE new RAW_KEEP entry ("rowan_detail": "*") to
        # reach the dashboard, instead of five flat ones -- see this
        # session's final report ("NEW RAW KEYS TO REGISTER").
        "rowan_detail": {
            "index_type": row.get("index_type"),
            "ref": row.get("ref") or None,
            "images_count": row.get("images_count"),
            "returned_to": detail.get("returned_to") if detail else None,
            "detail_url": row.get("detail_url") if detail else None,
        },
    }

    return Listing(
        source=slug,
        source_url=row.get("detail_url") or _URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        county="Rowan",
        state="NC",
        case_number=book_page or None,
        owner_name="; ".join(grantee_names) or None,
        plaintiff="; ".join(grantor_names) or None,
        legal_description=detail.get("property_info"),
        description=row.get("description") or None,
        raw=raw,
    )


class NcRowanCottScraper(BaseScraper):
    """Rowan County NC deeds — Cott eSearch via Playwright (guest session)."""

    slug = "counties_nc.nc_rowan_cott"
    name = "Rowan NC Deeds (Cott)"
    category = "rod"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_rowan_cott.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = None
            try:
                page = await browser.new_page()
                log.info("nc_rowan_cott.fetching")

                await page.goto(_URL, timeout=30000)
                await page.wait_for_load_state("domcontentloaded", timeout=20000)

                guest_btn = page.locator(
                    "button:has-text('Sign in as a Guest'), input[value*='Guest' i]"
                )
                if await guest_btn.count() > 0:
                    await guest_btn.first.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                else:
                    log.warning("nc_rowan_cott.no_guest_button")
                    return results

                date_tab = page.locator(
                    "button:has-text('Date Range'), input[value='Date Range']"
                )
                if await date_tab.count() == 0:
                    log.warning("nc_rowan_cott.no_date_tab")
                    return results
                await date_tab.first.click()
                await page.wait_for_load_state("domcontentloaded", timeout=20000)

                # Index Type is an ASP.NET listbox wired to onchange ->
                # __doPostBack: selecting it reloads the panel and resets any
                # From/Thru value already typed (live-confirmed 2026-10-13 --
                # dates set before this select came back as the fields'
                # placeholder text, "From"/"Thru", after the select postback).
                # Select it FIRST, dates LAST. Kind is deliberately left
                # unselected here -- see module docstring; filtered in Python
                # via _is_deed_kind after the real grid HTML comes back.
                try:
                    await page.select_option(
                        "select[id$='lbIndexTypes']", label="CONSOLIDATED REAL PROPERTY"
                    )
                except Exception as exc:
                    log.warning("nc_rowan_cott.index_type_select_failed", error=str(exc)[:160])

                today = datetime.now()
                frm = today - timedelta(days=_LOOKBACK_DAYS)
                # These two fields carry a jQuery MaskedEdit plugin (the real
                # markup loads javascripts/MaskedEditFix.js). page.fill()
                # sets .value directly but the mask plugin still intercepts
                # the synthetic keystrokes Playwright fires alongside it,
                # live-confirmed 2026-10-13 to leave the mask's own
                # placeholder characters appended to the real value (e.g.
                # "10/13/2026__/__/____"), which fails the page's own
                # "valid date range" JS check and silently blocks the
                # search postback. Setting .value via evaluate() (same as
                # this scraper's manual live verification) bypasses the
                # mask plugin's keystroke handling entirely.
                for field_id_suffix, value in (
                    ("txtFiledFrom", frm.strftime("%m/%d/%Y")),
                    ("txtFiledThru", today.strftime("%m/%d/%Y")),
                ):
                    await page.evaluate(
                        """([suffix, val]) => {
                            const el = document.querySelector(
                                "input[id$='" + suffix + "']");
                            if (el) el.value = val;
                        }""",
                        [field_id_suffix, value],
                    )

                search_btn = page.locator("input[id$='btnSearch']")
                if await search_btn.count() == 0:
                    log.warning("nc_rowan_cott.no_search_button")
                    return results
                await search_btn.first.click()
                await page.wait_for_load_state("networkidle", timeout=20000)

                html = await page.content()
                all_rows = _parse_results(html)
                rows = [r for r in all_rows if _is_deed_kind(r.get("kind"))]
                log.info("nc_rowan_cott.search_done", total=len(all_rows), deeds=len(rows))

                budget = _MAX_DETAIL_FETCHES
                on_results_page = True
                for row in rows:
                    link_id = row.get("detail_link_id")
                    if budget > 0 and link_id and on_results_page:
                        budget -= 1
                        try:
                            # ASP.NET's __doPostBack here is a full-page POST
                            # reload, not an in-place DOM swap. Live-confirmed
                            # 2026-10-13: "domcontentloaded" plus an
                            # immediate go_back() races the Details page's
                            # own still-settling navigation and throws
                            # "net::ERR_ABORTED; maybe frame was detached" --
                            # and because that left the browser on neither
                            # the Details page nor the results grid, every
                            # row after that first failure then burned a
                            # full click timeout trying to find a link_id
                            # that no longer existed anywhere on screen.
                            # "load" (not "domcontentloaded") plus a short
                            # settle wait before go_back() fixed it
                            # (confirmed stable across a 40-row run, 39/40
                            # detail fetches succeeded, the one miss a
                            # transient content-read race the circuit
                            # breaker below recovered from cleanly).
                            await page.click(f"#{link_id}", timeout=12000)
                            await page.wait_for_load_state("load", timeout=15000)
                            await page.wait_for_timeout(500)
                            row["detail_url"] = page.url
                            row["detail"] = _parse_detail(await page.content())
                            await page.go_back(timeout=15000)
                            await page.wait_for_load_state("load", timeout=15000)
                            if not await page.locator(
                                f"table[id$='{_RESULTS_TABLE_ID_SUFFIX}']"
                            ).count():
                                on_results_page = False
                        except Exception as exc:
                            log.warning("nc_rowan_cott.detail_failed", error=str(exc)[:160])
                            # Best-effort single recovery attempt. If this
                            # doesn't land back on the results grid, every
                            # remaining row's link_id is gone too -- stop the
                            # detail loop instead of burning the rest of the
                            # budget on guaranteed click timeouts (live-
                            # confirmed 2026-10-13: ~10 rows x 30s each on one
                            # stuck run).
                            try:
                                await page.go_back(timeout=15000)
                                await page.wait_for_load_state("load", timeout=15000)
                            except Exception:
                                pass
                            if not await page.locator(
                                f"table[id$='{_RESULTS_TABLE_ID_SUFFIX}']"
                            ).count():
                                on_results_page = False
                                log.warning("nc_rowan_cott.detail_loop_aborted",
                                           reason="lost results page after a failed detail fetch")
                    results.append(_to_listing(self.slug, row))

                log.info("nc_rowan_cott.done", found=len(results))

            except Exception as exc:
                log.warning("nc_rowan_cott.error", error=str(exc)[:200])
            finally:
                if page:
                    try:
                        await page.close()
                    except BaseException:
                        pass

            await browser.close()

        return results
