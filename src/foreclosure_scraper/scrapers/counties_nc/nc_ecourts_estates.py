"""NC eCourts (Tyler Odyssey) ESTATES track — probate / decedent-estate leads.

Source
------
NC AOC's public **Smart Search** portal at
  https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29

Unlike the Judgment Search OData service that nc_ecourts_lis_pendens.py hits
(which only indexes *entered civil judgments* — liens, lis pendens), the
estate / decedent record lives in Tyler's full **Smart Search** index. That
index is behind AWS WAF (the "Human Verification" image-grid CAPTCHA) but is
otherwise *anonymous* — no Tyler IdP login needed. We drive it exactly the way
enrichment_nc_case_status_tyler._drive_anonymous_search already does:

  1. Pre-warm an aws-waf-token via the curl_cffi invisible-challenge solver
     (tyler_waf_token.fetch_waf_token) and inject it into the browser context.
  2. Land on the Smart Search dashboard with Scrapling StealthyFetcher
     (solve_cloudflare + google_search + real-browser fingerprint).
  3. If the WAF image-grid is served, solve it with the free OSS Gemini-vision
     solver (enrichment_waf_oss.solve_waf_via_browser).
  4. Switch the search to the **Estate** case category, run a blank
     party/date-window search per footprint county, page the result hitlist.
  5. Parse each result row's party block: the decedent (the estate "owner") and
     the executor / administrator / personal representative (the actionable
     contact / likely heir-seller).

Why estates are a lead
----------------------
When an estate opens, the heirs typically want to liquidate the decedent's
real property fast (avoid carrying costs, split the inheritance). The decedent
is the record owner of the property; matching that name against the county GIS
owner index fills the address downstream. So we emit **address-less** Listings
carrying owner_name=<decedent>; enrichment_gis_attrs resolves owner -> parcel ->
street_address. These rows are DATELESS (no sale date — an estate filing has no
auction) and are routed through DATELESS_OK_SOURCES.

Footprint
---------
NC footprint counties only (mirrors nc_ecourts_lis_pendens.TARGET_COUNTIES):
the 11 WNC/foothills counties plus the 5 coastal counties. Inland-coastal rows
are re-filtered by main._in_scope's oceanfront gate once geocoded.

WAF note
--------
If the WAF image-grid solve fails (e.g. GEMINI_API_KEY_* unset — the local-dev
case), the run returns 0 and records the block reason via the shared block
signal; the parser is still exercised on whatever HTML was fetched. See
enrichment_nc_case_status_tyler for the canonical WAF handling this mirrors.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PORTAL_BASE = "https://portal-nc.tylertech.cloud/Portal"
# Anonymous Smart Search dashboard — same entry point the case-status
# enrichment uses. No login required; WAF image-grid every ~5 min.
SEARCH_URL = f"{PORTAL_BASE}/Home/Dashboard/29"
ROOT = "https://portal-nc.tylertech.cloud"

# NC footprint counties for the eCourts SmartSearch estates track. Mirrors
# nc_ecourts_lis_pendens.TARGET_COUNTIES exactly so the two eCourts tracks
# stay in lockstep: 11 WNC/foothills + 5 coastal. Tyler indexes each as
# "<County> District Court" / "<County> Superior Court"; estates are filed
# on the Special Proceedings / Estates side of District Court.
TARGET_COUNTIES = [
    "Rutherford", "Cleveland", "Henderson", "Polk", "Gaston",
    "Buncombe", "Transylvania", "McDowell", "Lincoln",
    "Mitchell", "Burke",
    # COASTAL NC track (re-admitted via the oceanfront gate once geocoded).
    "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
    # 2026-08-19 — sync with lis_pendens TARGET_COUNTIES (remaining coastal NC).
    "Currituck", "Hyde", "New Hanover",
    "Beaufort", "Craven", "Pamlico",
]

# Case-category labels Tyler exposes in the Smart Search "Case Category"
# dropdown for the estate/decedent record. Tyler tenants vary the exact
# wording, so we match any of these (case-insensitive) when selecting the
# category option, and again when filtering result rows by their caseType.
ESTATE_CATEGORY_LABELS = (
    "Estate",
    "Estates",
    "Special Proceedings",  # NC files decedent estates as SP-E / estate SPs
    "Probate",
    "Decedent",
)

# caseType strings on Tyler estate result rows we accept. Broad on purpose —
# the category filter already scopes the search; this is a second-pass guard
# so a stray non-estate row (Tyler occasionally bleeds adjacent SP types)
# doesn't slip through.
ESTATE_CASE_TYPE_RE = re.compile(
    r"estate|decedent|administrat|testate|probate|year'?s\s+allowance|"
    r"small\s+estate|collection\s+by\s+affidavit",
    re.I,
)

# Party-role labels for the actionable contact on an estate. The decedent is
# the property owner; the executor/administrator/PR is the person who can sell.
_EXECUTOR_ROLE_RE = re.compile(
    r"executor|executrix|administrat|personal\s+representative|"
    r"collector|petitioner|applicant|fiduciary",
    re.I,
)
_DECEDENT_ROLE_RE = re.compile(r"decedent|deceased|estate\s+of|respondent", re.I)


def _strip_court_suffix(loc: str) -> str:
    """'Henderson District Court' -> 'Henderson'."""
    if not loc:
        return ""
    return re.sub(r"\s+(District|Superior)\s+Court\b.*$", "", loc).strip()


def _clean_name(name: str) -> str:
    """Normalize a party name pulled from Tyler markup."""
    n = re.sub(r"\s+", " ", (name or "")).strip(" ,;")
    # Drop a leading 'Estate of ' wrapper so the bare decedent name geocodes.
    n = re.sub(r"^(?:the\s+)?estate\s+of\s+", "", n, flags=re.I).strip()
    # Drop trailing ', Deceased' / ', Decedent'
    n = re.sub(r",?\s*(deceased|decedent)\s*$", "", n, flags=re.I).strip(" ,;")
    # Trim trailing court/county/date crumbs that bleed in when a name is
    # pulled from a flattened result-row text blob (the DOM-party path never
    # hits this — its names are already isolated in their own elements).
    n = re.sub(
        r"\s+(?:district\s+court|superior\s+court|county|"
        r"\d{1,2}/\d{1,2}/\d{2,4}).*$",
        "", n, flags=re.I,
    ).strip(" ,;")
    return n


def _looks_like_org(name: str) -> bool:
    """True if the name is clearly a company/agency, not a person."""
    return bool(re.search(
        r"\b(llc|inc|corp|company|co\.|bank|trust|county|state|department|"
        r"services|associat|n\.?a\.?|trustee|fund|capital|mortgage)\b",
        name, re.I,
    ))


def _row_to_listing(row: dict, slug: str) -> Optional[Listing]:
    """Convert one parsed Smart Search estate result row to a Listing.

    `row` shape (produced by the in-browser parser below):
      {
        case_number, case_type, location, status, filed_date,
        parties: [{name, role}, ...], detail_url
      }
    """
    case_type = row.get("case_type") or ""
    # Second-pass guard: skip rows whose caseType isn't estate-shaped.
    if case_type and not ESTATE_CASE_TYPE_RE.search(case_type):
        return None

    location = row.get("location") or ""
    county = _strip_court_suffix(location)
    if not county:
        return None

    parties = row.get("parties") or []
    decedent = None
    executor = None
    for p in parties:
        name = _clean_name(p.get("name", ""))
        role = p.get("role", "") or ""
        if not name:
            continue
        if decedent is None and _DECEDENT_ROLE_RE.search(role):
            decedent = name
        elif executor is None and _EXECUTOR_ROLE_RE.search(role):
            executor = name

    # Fallbacks when Tyler doesn't label roles: the case title is usually
    # "In re: Estate of <Decedent>" or "<Decedent>, Deceased". The first
    # person-looking party is the decedent; the next is the PR.
    if decedent is None:
        for p in parties:
            cand = _clean_name(p.get("name", ""))
            if cand and not _looks_like_org(cand):
                decedent = cand
                break
    if executor is None:
        for p in parties:
            cand = _clean_name(p.get("name", ""))
            if cand and cand != decedent and not _looks_like_org(cand):
                executor = cand
                break

    # The decedent is the record owner whose name GIS will resolve to an
    # address. Without it there's nothing to enrich, so skip.
    if not decedent:
        return None

    case_number = (row.get("case_number") or "").strip()
    detail_url = row.get("detail_url") or f"{SEARCH_URL}#/search?caseNumber={case_number}"

    filed_iso = None
    fd = row.get("filed_date")
    if fd:
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                filed_iso = datetime.strptime(fd, fmt).date().isoformat()
                break
            except ValueError:
                continue

    return Listing(
        source=slug,
        source_url=detail_url,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        case_number=case_number or None,
        # owner_name = the decedent → GIS resolves to the property/address.
        owner_name=decedent,
        # defendant carries the decedent too (party-of-interest), plaintiff
        # carries the executor/PR (the actionable contact) for parity with
        # the rest of the pipeline's party model.
        defendant=decedent,
        plaintiff=executor,
        sale_date=None,  # dateless — an estate opening has no auction
        description=(
            f"NC estate filing in {location}: {case_type or 'Estate'} "
            f"{case_number}".strip()
        ),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "nc_ecourts_estates": {
                "case_type": case_type,
                "location": location,
                "status": row.get("status"),
                "filed_date": fd,
                "filed_date_iso": filed_iso,
                "decedent": decedent,
                "executor": executor,
                "parties": parties,
            }
        },
    )


# --- in-browser Smart Search driver -----------------------------------------
# Mirrors enrichment_nc_case_status_tyler._drive_anonymous_search: pre-warm
# token, land, solve WAF, then run the category search and scrape the hitlist.

async def _drive_estate_search(page, counties: list[str], lookback_days: int) -> list[dict]:
    rows: list[dict] = []

    # Step 0: pre-warm aws-waf-token (no-op unless TYLER_USE_WAF_SOLVER=1 and
    # the invisible challenge is served; image-grid falls through to OSS solver).
    try:
        from ...tyler_waf_token import fetch_waf_token
        pre = await fetch_waf_token(SEARCH_URL, "portal-nc.tylertech.cloud")
        if pre:
            await page.context.add_cookies([{
                "name": "aws-waf-token", "value": pre,
                "domain": ".tylertech.cloud", "path": "/",
            }])
            log.info("nc_ecourts_estates.pretoken_injected")
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_estates.pretoken_fail", error=str(exc)[:160])

    # Step 1: land on Smart Search.
    try:
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=45000)
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_estates.land_fail", error=str(exc)[:200])
        return rows

    # Step 1b: detect + solve WAF if present.
    if await _waf_present(page):
        log.info("nc_ecourts_estates.waf_detected", url=page.url[:160])
        if not await _solve_waf(page):
            log.warning("nc_ecourts_estates.waf_solve_failed")
            _dump("estates_waf_fail", await _safe_content(page))
            # Record a block so safe_run classifies this run as BLOCKED (a WAF
            # CAPTCHA we couldn't solve) instead of a silent ZERO_RESULT. The
            # transport's auto-record only fires for httpx; StealthyFetcher
            # never touches it, so we append the same (code, reason) shape.
            _signal_waf_block()
            return rows

    # Step 2: wait for the Smart Search form.
    if not await _wait_search_form(page):
        log.warning("nc_ecourts_estates.no_form", url=page.url[:160])
        _dump("estates_no_form", await _safe_content(page))
        return rows

    # Step 3: select the Estate case category once.
    selected = await _select_case_category(page, ESTATE_CATEGORY_LABELS)
    log.info("nc_ecourts_estates.category_selected", ok=selected)

    # Step 4: per-county blank search, page the hitlist.
    for county in counties:
        try:
            county_rows = await _search_county(page, county, lookback_days)
        except Exception as exc:  # noqa: BLE001
            log.debug("nc_ecourts_estates.county_fail", county=county, error=str(exc)[:160])
            continue
        rows.extend(county_rows)
        log.info("nc_ecourts_estates.county_done", county=county, rows=len(county_rows))

    return rows


# ---- shared Tyler Smart Search browser helpers (kept module-local so we
#      don't edit the shared enrichment file) ---------------------------------

def _signal_waf_block() -> None:
    """Mark the shared per-run block holder so base_scraper.safe_run promotes
    this run's empty result to BLOCKED. Read-only use of the http_client
    ContextVar (we only .get() the list and .append() to it — no .set(), no
    edit to the shared module)."""
    try:
        from ...http_client import _block_holder  # type: ignore
        holder = _block_holder.get()
        if holder is not None:
            holder.append((403, "AWS WAF image-grid CAPTCHA unsolved "
                                "(set GEMINI_API_KEY_* / CAPSOLVER_API_KEY)"))
    except Exception:  # noqa: BLE001
        pass


async def _safe_content(page) -> str:
    try:
        return await page.content()
    except Exception:  # noqa: BLE001
        return ""


async def _waf_present(page) -> bool:
    try:
        body = (await page.content()).lower()
        if "let's confirm you are human" in body or "awswaf" in body or \
                "human verification" in body:
            return True
        try:
            await page.wait_for_selector('#caseCriteria_SearchCriteria', timeout=2000)
            return False
        except Exception:
            return True
    except Exception:  # noqa: BLE001
        return False


async def _solve_waf(page) -> bool:
    try:
        from ...enrichment_waf_oss import solve_waf_via_browser
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_estates.waf_import_fail", error=str(exc)[:160])
        return False
    solved = await solve_waf_via_browser(page)
    if not solved and os.environ.get("CAPSOLVER_API_KEY"):
        try:
            from ...enrichment_capsolver import solve_aws_waf
            token = await solve_aws_waf(page.url)
            if token:
                await page.context.add_cookies([{
                    "name": "aws-waf-token", "value": token,
                    "domain": ".tylerhost.net", "path": "/",
                    "httpOnly": False, "secure": True, "sameSite": "None",
                }])
                await page.reload(wait_until="networkidle", timeout=45000)
                solved = True
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_ecourts_estates.capsolver_fail", error=str(exc)[:160])
    return bool(solved)


async def _wait_search_form(page) -> bool:
    try:
        await page.wait_for_selector('#caseCriteria_SearchCriteria', timeout=15000)
        return True
    except Exception:
        return False


async def _select_case_category(page, labels: tuple[str, ...]) -> bool:
    """Pick the case category in the Smart Search advanced filter.

    Tyler renders the category as a <select> (often #cboHSSearchCategories or
    a 'Case Category' select). We match an <option> whose text contains any of
    `labels` and select it, firing change so the SPA updates the filter.
    """
    labels_lc = [l.lower() for l in labels]
    try:
        return bool(await page.evaluate(
            """(labels) => {
                const sels = [...document.querySelectorAll('select')];
                for (const s of sels) {
                    for (const o of s.options) {
                        const t = (o.text || '').toLowerCase();
                        if (labels.some(l => t.includes(l))) {
                            s.value = o.value;
                            s.dispatchEvent(new Event('change', {bubbles:true}));
                            return true;
                        }
                    }
                }
                return false;
            }""",
            labels_lc,
        ))
    except Exception as exc:  # noqa: BLE001
        log.debug("nc_ecourts_estates.category_select_fail", error=str(exc)[:160])
        return False


async def _search_county(page, county: str, lookback_days: int) -> list[dict]:
    """Run one county search and parse the result hitlist."""
    # Fill the Smart Search criteria input with the county (Advanced Search
    # also exposes a Location filter; the free-text field accepts the county
    # and Tyler scopes the hitlist). Fire input/change so the SPA picks it up.
    try:
        await page.evaluate(
            """(v) => {
                const e = document.querySelector('#caseCriteria_SearchCriteria');
                if (!e) return;
                e.value = v;
                e.dispatchEvent(new Event('input', {bubbles:true}));
                e.dispatchEvent(new Event('change', {bubbles:true}));
            }""",
            county,
        )
    except Exception:
        return []

    # Submit.
    submitted = False
    for sel in (
        'button:has-text("Submit")',
        'input[type="submit"][value="Submit"]',
        'button[type="submit"]',
    ):
        try:
            await page.click(sel, timeout=4000)
            submitted = True
            break
        except Exception:
            continue
    if not submitted:
        try:
            await page.press('#caseCriteria_SearchCriteria', "Enter")
            submitted = True
        except Exception:
            return []

    # Wait for the hitlist (or the empty-state message).
    try:
        await page.wait_for_selector(
            'table, .case-list, :text("No cases match your search")',
            timeout=30000,
        )
    except Exception:
        return []

    body = (await page.content()).lower()
    if "no cases match your search" in body:
        return []

    # Parse the hitlist rows in-browser. Tyler renders each result as a
    # row with a caseLink (data-url -> RegisterOfActions), a caseType, a
    # location, a filed date, and a party block.
    try:
        rows = await page.evaluate(
            """() => {
                const out = [];
                const links = [...document.querySelectorAll('a.caseLink, a[data-url]')];
                for (const a of links) {
                    const tr = a.closest('tr') || a.closest('.row, .caseInfo, li');
                    const txt = tr ? tr.innerText : a.innerText;
                    // case number: the link title or its text
                    const caseNumber = (a.getAttribute('title') || a.innerText || '').trim();
                    const dataUrl = a.getAttribute('data-url') || '';
                    // Pull a caseType / location / filed cell heuristically
                    let caseType = '', location = '', filed = '', status = '';
                    if (tr) {
                        const cells = [...tr.querySelectorAll('td, .col, span, div')]
                            .map(c => c.innerText.trim()).filter(Boolean);
                        for (const c of cells) {
                            if (/district court|superior court/i.test(c) && !location) location = c;
                            if (/estate|decedent|administrat|probate|special proceed/i.test(c) && !caseType) caseType = c;
                            if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}$/.test(c) && !filed) filed = c;
                            if (/disposed|active|pending|open|closed/i.test(c) && !status) status = c;
                        }
                    }
                    // Party block: prefer explicit party rows with roles.
                    const parties = [];
                    if (tr) {
                        const pnodes = [...tr.querySelectorAll('.party, .partyName, [class*=party]')];
                        for (const pn of pnodes) {
                            const name = (pn.querySelector('.name, .partyName') || pn).innerText.trim();
                            const role = (pn.querySelector('.role, .partyType') || {}).innerText || '';
                            if (name) parties.push({name, role: role.trim()});
                        }
                    }
                    out.push({caseNumber, dataUrl, caseType, location, filed, status, rawText: (txt||'').slice(0,600), parties});
                }
                return out;
            }"""
        )
    except Exception:
        return []

    parsed: list[dict] = []
    for r in rows or []:
        parsed.append(_normalize_hit(r, county))
    return parsed


def _normalize_hit(r: dict, fallback_county: str) -> dict:
    """Turn a raw in-browser hit dict into the row shape _row_to_listing wants,
    backfilling parties from the rawText title when the DOM had no party nodes."""
    data_url = r.get("dataUrl") or ""
    if data_url.startswith("/"):
        data_url = ROOT + data_url
    parties = r.get("parties") or []
    if not parties:
        parties = _parties_from_text(r.get("rawText") or "")
    location = r.get("location") or f"{fallback_county} District Court"
    return {
        "case_number": r.get("caseNumber") or "",
        "case_type": r.get("caseType") or "",
        "location": location,
        "status": r.get("status") or "",
        "filed_date": r.get("filed") or "",
        "detail_url": data_url,
        "parties": parties,
    }


# Title patterns Tyler uses for estate case titles, in priority order.
# Each captures ONLY the decedent name — a person name is letters / spaces /
# initials / hyphens / apostrophes, so we stop the capture at the first comma,
# 'Deceased', double-space, or role keyword (which begin the next field on a
# flattened result row). Without the bounded class the greedy capture swallowed
# the rest of the row ('... Administrator: Lisa Jones  Henderson District ...').
_NAME = r"[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4}"
_TITLE_PATTERNS = (
    # "In re: Estate of John Q Decedent" / "In the Matter of the Estate of ..."
    re.compile(rf"(?:in\s+re|in\s+the\s+matter\s+of)[:\s]+(?:the\s+)?estate\s+of\s+({_NAME})", re.I),
    re.compile(rf"estate\s+of\s+({_NAME})", re.I),
    # "Smith, John, Deceased"
    re.compile(rf"({_NAME}(?:,\s*{_NAME})?)\s*,?\s+(?:deceased|decedent)\b", re.I),
)


def _parties_from_text(text: str) -> list[dict]:
    """Best-effort party extraction from a result row's flat text.

    Estate titles rarely use the 'VS' separator; they read 'Estate of <name>'.
    Pull the decedent from the title, and any 'Executor/Administrator: <name>'
    style fragment as the PR.
    """
    if not text:
        return []
    out: list[dict] = []
    for pat in _TITLE_PATTERNS:
        m = pat.search(text)
        if m:
            out.append({"name": m.group(1).strip()[:120], "role": "Decedent"})
            break
    pr = re.search(
        r"(?:executor|executrix|administrator|administratrix|personal\s+representative|collector)"
        rf"\s*[:\-]?\s*({_NAME})",
        text, re.I,
    )
    if pr:
        out.append({"name": pr.group(1).strip()[:120], "role": "Executor"})
    return out


def _dump(label: str, content: str) -> None:
    """Save a debug snapshot under debug/ (artifact-uploaded, not nuked)."""
    if not content:
        return
    try:
        import pathlib
        p = pathlib.Path("debug") / f"nc_ecourts_estates_{label}.html"
        p.parent.mkdir(exist_ok=True)
        p.write_text(content)
        log.info("nc_ecourts_estates.debug_dump", label=label, bytes=len(content))
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_estates.dump_fail", label=label, error=str(exc)[:120])


class NCECourtsEstates(BaseScraper):
    slug = "counties_nc.nc_ecourts_estates"
    name = "NC eCourts Estates (Tyler Odyssey Smart Search)"
    # 2026-06-27: disabled — NC eCourts Smart Search sits behind an AWS-WAF escalating
    # image-CAPTCHA that does NOT clear even with the Gemini solver; it burns vision
    # quota and logs errors for 0 results every run. NC estate/decedent notices are
    # covered compliantly via counties.column_legal_notices. Re-enable if the WAF drops.
    disabled = True
    disabled_reason = "NC eCourts AWS-WAF CAPTCHA unsolvable; NC estate covered via Column"
    category = "county_court"
    # Estate filings are common; but the WAF gate means a run can legitimately
    # come back empty when the image-grid solve fails. Keep min 0 so a blocked
    # run is classified by safe_run's block-signal logic, not as a regression.
    expected_min_count = 0
    timeout_s = 600.0
    requires_apify = False
    optional = True

    # How far back to scope the estate search per county.
    LOOKBACK_DAYS = 120

    async def fetch(self) -> Iterable[Listing]:
        try:
            from scrapling.fetchers import StealthyFetcher
        except ImportError:
            log.warning("nc_ecourts_estates.scrapling_missing")
            return []

        if os.environ.get("NC_ECOURTS_SKIP") == "1":
            log.info("nc_ecourts_estates.skip_via_env")
            return []

        captured: list[dict] = []

        async def page_action(page):
            result = await _drive_estate_search(page, TARGET_COUNTIES, self.LOOKBACK_DAYS)
            captured.extend(result)

        try:
            await StealthyFetcher.async_fetch(
                SEARCH_URL,
                headless=True,
                network_idle=True,
                timeout=240000,
                page_action=page_action,
                solve_cloudflare=True,
                google_search=True,
                wait=5000,
                retries=2,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_ecourts_estates.fetch_fail", error=str(exc)[:200])
            return []

        listings: list[Listing] = []
        seen: set[str] = set()
        for row in captured:
            li = _row_to_listing(row, self.slug)
            if li is None:
                continue
            key = (li.case_number or "", li.county or "", (li.owner_name or "").lower())
            if key in seen:
                continue
            seen.add(key)
            listings.append(li)

        log.info("nc_ecourts_estates.parsed", listings=len(listings),
                 raw_rows=len(captured))
        return listings


# Quick local iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates
if __name__ == "__main__":
    async def _main() -> None:
        scraper = NCECourtsEstates()
        results = await scraper.safe_run()
        print(f"outcome={scraper.last_outcome} reason={scraper.last_reason}")
        print(f"parsed: {len(results)}")
        for x in results[:8]:
            print(f"  {x.county}: case={x.case_number} owner={x.owner_name} pr={x.plaintiff}")

    asyncio.run(_main())
