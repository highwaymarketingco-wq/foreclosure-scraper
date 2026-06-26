"""NC eCourts (Tyler Odyssey) DIVORCE track — absolute-divorce / equitable-
distribution leads.

Source
------
NC AOC's public **Smart Search** portal at
  https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29

Same anonymous Smart Search index + AWS-WAF flow as nc_ecourts_estates.py — we
just switch the case category to **Family / Civil Action (absolute divorce)**
and parse the two **spouse** party rows instead of decedent/executor. This
reuses the exact WAF/token handling from
enrichment_nc_case_status_tyler._drive_anonymous_search:

  1. Pre-warm an aws-waf-token via tyler_waf_token.fetch_waf_token.
  2. Land on Smart Search with Scrapling StealthyFetcher.
  3. Solve the WAF image-grid with the free OSS Gemini-vision solver.
  4. Select the Family / Divorce case category, search per footprint county.
  5. Parse the plaintiff/defendant spouse rows from each result.

Why divorce is a lead
---------------------
A contested absolute divorce frequently forces a sale of the marital home to
divide assets (equitable distribution under NCGS §50-20). Either spouse is a
candidate owner / motivated seller. NC divorce captions read
"<Plaintiff Spouse> VS <Defendant Spouse>". We emit **address-less** Listings
carrying owner_name = the plaintiff spouse (the filing party — usually the one
still in or controlling the home), with both spouses preserved in raw; the
owner -> GIS pass resolves the marital-home address downstream. DATELESS — a
divorce filing has no sale date, so these route through DATELESS_OK_SOURCES.

Footprint
---------
NC footprint counties only (mirrors nc_ecourts_lis_pendens.TARGET_COUNTIES):
the 11 WNC/foothills counties plus the 5 coastal counties.

WAF note
--------
If the WAF image-grid solve fails (e.g. GEMINI_API_KEY_* unset — the local-dev
case), the run returns 0 and the block reason is recorded via the shared block
signal; the parser is still exercised on whatever HTML was fetched.
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
SEARCH_URL = f"{PORTAL_BASE}/Home/Dashboard/29"
ROOT = "https://portal-nc.tylertech.cloud"

# NC footprint counties — mirrors nc_ecourts_lis_pendens.TARGET_COUNTIES.
TARGET_COUNTIES = [
    "Rutherford", "Cleveland", "Henderson", "Polk", "Gaston",
    "Buncombe", "Transylvania", "McDowell", "Lincoln",
    "Mitchell", "Burke",
    "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
]

# Case-category labels Tyler exposes for divorce / family. NC files absolute
# divorce as a Civil Action (CVD) in District Court; some tenants surface a
# 'Family' category, others only 'Civil'. Match any (case-insensitive).
DIVORCE_CATEGORY_LABELS = (
    "Family",
    "Domestic",
    "Civil Action",
    "Civil",  # NC CVD absolute-divorce lives under the Civil category
)

# caseType strings on divorce result rows we accept. NC absolute-divorce =
# "CVD" / "Civil District" with a divorce cause; equitable distribution and
# divorce-from-bed-and-board also qualify (both can force a home sale).
DIVORCE_CASE_TYPE_RE = re.compile(
    r"divorce|equitable\s+distribution|bed\s+and\s+board|domestic|"
    r"\bcvd\b|absolute\s+divorce|marital",
    re.I,
)

# Cause-of-action guard: when a row exposes its cause text, require a divorce
# signal so we don't pull child-support/custody-only CVD rows (no home to sell).
DIVORCE_CAUSE_RE = re.compile(
    r"divorce|equitable\s+distribution|bed\s+and\s+board|marital|alimony",
    re.I,
)


def _strip_court_suffix(loc: str) -> str:
    """'Buncombe District Court' -> 'Buncombe'."""
    if not loc:
        return ""
    return re.sub(r"\s+(District|Superior)\s+Court\b.*$", "", loc).strip()


def _clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "")).strip(" ,;")
    # Drop role wrappers Tyler sometimes prefixes onto the caption name.
    n = re.sub(r"^(plaintiff|defendant|petitioner|respondent)\s*[:\-]?\s*", "",
               n, flags=re.I).strip()
    return n


def _looks_like_org(name: str) -> bool:
    return bool(re.search(
        r"\b(llc|inc|corp|company|co\.|bank|trust|county|state|department|"
        r"services|associat|n\.?a\.?|child\s+support|enforcement)\b",
        name, re.I,
    ))


def _split_caption(title: str) -> tuple[Optional[str], Optional[str]]:
    """Split 'Jane A Doe VS John B Doe' -> ('Jane A Doe', 'John B Doe')."""
    if not title:
        return None, None
    m = re.split(r"\s+(?:vs?\.?|v\.|versus|and)\s+", title, maxsplit=1, flags=re.I)
    if len(m) == 2:
        return _clean_name(m[0]), _clean_name(m[1])
    return _clean_name(title), None


def _row_to_listing(row: dict, slug: str) -> Optional[Listing]:
    """Convert one parsed Smart Search divorce result row to a Listing."""
    case_type = row.get("case_type") or ""
    cause = row.get("cause") or ""
    # Guard: require a divorce signal in caseType OR cause. If neither field
    # is populated (Tyler hid them on the hitlist), fall through on the
    # category filter alone — the search was already scoped to Family/Civil.
    if case_type and cause:
        if not (DIVORCE_CASE_TYPE_RE.search(case_type) or DIVORCE_CAUSE_RE.search(cause)):
            return None
    elif case_type and not DIVORCE_CASE_TYPE_RE.search(case_type):
        # Only caseType present and it's clearly non-divorce -> skip.
        if not DIVORCE_CASE_TYPE_RE.search(case_type):
            return None

    location = row.get("location") or ""
    county = _strip_court_suffix(location)
    if not county:
        return None

    # Spouses: prefer explicit plaintiff/defendant party roles; else split caption.
    plaintiff = None
    defendant = None
    for p in row.get("parties") or []:
        name = _clean_name(p.get("name", ""))
        role = (p.get("role") or "").lower()
        if not name or _looks_like_org(name):
            continue
        if "plaintiff" in role or "petitioner" in role:
            plaintiff = plaintiff or name
        elif "defendant" in role or "respondent" in role:
            defendant = defendant or name

    if not plaintiff or not defendant:
        p2, d2 = _split_caption(row.get("title") or "")
        plaintiff = plaintiff or p2
        defendant = defendant or d2

    # Drop child-support enforcement style captions (a "County / NCCSE VS
    # parent" row is not a marital-home divorce).
    if plaintiff and _looks_like_org(plaintiff):
        return None

    # The plaintiff spouse is the filing party — owner_name for GIS resolution.
    if not plaintiff:
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
        listing_type=ListingType.DIVORCE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        case_number=case_number or None,
        owner_name=plaintiff,   # filing spouse → GIS resolves marital home
        plaintiff=plaintiff,
        defendant=defendant,
        sale_date=None,         # dateless — divorce filing has no auction
        description=(
            f"NC absolute-divorce filing in {location}: "
            f"{case_type or 'Civil Action'} {case_number}".strip()
        ),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "nc_ecourts_divorce": {
                "case_type": case_type,
                "cause": cause,
                "location": location,
                "status": row.get("status"),
                "filed_date": fd,
                "filed_date_iso": filed_iso,
                "spouse_plaintiff": plaintiff,
                "spouse_defendant": defendant,
                "parties": row.get("parties") or [],
            }
        },
    )


# --- in-browser Smart Search driver (mirrors nc_ecourts_estates) -------------

async def _drive_divorce_search(page, counties: list[str], lookback_days: int) -> list[dict]:
    rows: list[dict] = []

    try:
        from ...tyler_waf_token import fetch_waf_token
        pre = await fetch_waf_token(SEARCH_URL, "portal-nc.tylertech.cloud")
        if pre:
            await page.context.add_cookies([{
                "name": "aws-waf-token", "value": pre,
                "domain": ".tylertech.cloud", "path": "/",
            }])
            log.info("nc_ecourts_divorce.pretoken_injected")
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_divorce.pretoken_fail", error=str(exc)[:160])

    try:
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=45000)
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_divorce.land_fail", error=str(exc)[:200])
        return rows

    if await _waf_present(page):
        log.info("nc_ecourts_divorce.waf_detected", url=page.url[:160])
        if not await _solve_waf(page):
            log.warning("nc_ecourts_divorce.waf_solve_failed")
            _dump("divorce_waf_fail", await _safe_content(page))
            # Record a block so safe_run reports BLOCKED, not a silent ZERO.
            # (StealthyFetcher never trips the transport's httpx auto-record.)
            _signal_waf_block()
            return rows

    if not await _wait_search_form(page):
        log.warning("nc_ecourts_divorce.no_form", url=page.url[:160])
        _dump("divorce_no_form", await _safe_content(page))
        return rows

    selected = await _select_case_category(page, DIVORCE_CATEGORY_LABELS)
    log.info("nc_ecourts_divorce.category_selected", ok=selected)

    for county in counties:
        try:
            county_rows = await _search_county(page, county, lookback_days)
        except Exception as exc:  # noqa: BLE001
            log.debug("nc_ecourts_divorce.county_fail", county=county, error=str(exc)[:160])
            continue
        rows.extend(county_rows)
        log.info("nc_ecourts_divorce.county_done", county=county, rows=len(county_rows))

    return rows


# ---- shared Tyler Smart Search browser helpers (module-local) ---------------

def _signal_waf_block() -> None:
    """Mark the shared per-run block holder so base_scraper.safe_run promotes
    this run's empty result to BLOCKED. Read-only use of the http_client
    ContextVar (only .get()/.append() — no .set(), no shared-file edit)."""
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
        log.warning("nc_ecourts_divorce.waf_import_fail", error=str(exc)[:160])
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
            log.warning("nc_ecourts_divorce.capsolver_fail", error=str(exc)[:160])
    return bool(solved)


async def _wait_search_form(page) -> bool:
    try:
        await page.wait_for_selector('#caseCriteria_SearchCriteria', timeout=15000)
        return True
    except Exception:
        return False


async def _select_case_category(page, labels: tuple[str, ...]) -> bool:
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
        log.debug("nc_ecourts_divorce.category_select_fail", error=str(exc)[:160])
        return False


async def _search_county(page, county: str, lookback_days: int) -> list[dict]:
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

    try:
        rows = await page.evaluate(
            """() => {
                const out = [];
                const links = [...document.querySelectorAll('a.caseLink, a[data-url]')];
                for (const a of links) {
                    const tr = a.closest('tr') || a.closest('.row, .caseInfo, li');
                    const txt = tr ? tr.innerText : a.innerText;
                    const caseNumber = (a.getAttribute('title') || a.innerText || '').trim();
                    const dataUrl = a.getAttribute('data-url') || '';
                    let caseType = '', location = '', filed = '', status = '', cause = '', title = '';
                    if (tr) {
                        const cells = [...tr.querySelectorAll('td, .col, span, div')]
                            .map(c => c.innerText.trim()).filter(Boolean);
                        for (const c of cells) {
                            if (/district court|superior court/i.test(c) && !location) location = c;
                            if (/divorce|equitable|cvd|domestic|civil/i.test(c) && !caseType) caseType = c;
                            if (/divorce|equitable distribution|bed and board|marital|alimony/i.test(c) && !cause) cause = c;
                            if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}$/.test(c) && !filed) filed = c;
                            if (/disposed|active|pending|open|closed/i.test(c) && !status) status = c;
                            if (/\\bvs?\\.?\\b|\\bversus\\b/i.test(c) && !title) title = c;
                        }
                    }
                    const parties = [];
                    if (tr) {
                        const pnodes = [...tr.querySelectorAll('.party, .partyName, [class*=party]')];
                        for (const pn of pnodes) {
                            const name = (pn.querySelector('.name, .partyName') || pn).innerText.trim();
                            const role = (pn.querySelector('.role, .partyType') || {}).innerText || '';
                            if (name) parties.push({name, role: role.trim()});
                        }
                    }
                    out.push({caseNumber, dataUrl, caseType, location, filed, status, cause, title, rawText: (txt||'').slice(0,600), parties});
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
    data_url = r.get("dataUrl") or ""
    if data_url.startswith("/"):
        data_url = ROOT + data_url
    title = r.get("title") or _title_from_text(r.get("rawText") or "")
    location = r.get("location") or f"{fallback_county} District Court"
    return {
        "case_number": r.get("caseNumber") or "",
        "case_type": r.get("caseType") or "",
        "cause": r.get("cause") or "",
        "location": location,
        "status": r.get("status") or "",
        "filed_date": r.get("filed") or "",
        "title": title,
        "detail_url": data_url,
        "parties": r.get("parties") or [],
    }


def _title_from_text(text: str) -> str:
    """Pull the 'A VS B' caption out of a flat result-row text blob."""
    if not text:
        return ""
    m = re.search(r"([A-Z][^\n]{2,80}?\s+(?:vs?\.?|versus)\s+[A-Z][^\n]{2,80})", text, re.I)
    return m.group(1).strip() if m else ""


def _dump(label: str, content: str) -> None:
    if not content:
        return
    try:
        import pathlib
        p = pathlib.Path("debug") / f"nc_ecourts_divorce_{label}.html"
        p.parent.mkdir(exist_ok=True)
        p.write_text(content)
        log.info("nc_ecourts_divorce.debug_dump", label=label, bytes=len(content))
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_ecourts_divorce.dump_fail", label=label, error=str(exc)[:120])


class NCECourtsDivorce(BaseScraper):
    slug = "counties_nc.nc_ecourts_divorce"
    name = "NC eCourts Divorce (Tyler Odyssey Smart Search)"
    category = "county_court"
    expected_min_count = 0
    timeout_s = 600.0
    requires_apify = False
    optional = True

    LOOKBACK_DAYS = 120

    async def fetch(self) -> Iterable[Listing]:
        try:
            from scrapling.fetchers import StealthyFetcher
        except ImportError:
            log.warning("nc_ecourts_divorce.scrapling_missing")
            return []

        if os.environ.get("NC_ECOURTS_SKIP") == "1":
            log.info("nc_ecourts_divorce.skip_via_env")
            return []

        captured: list[dict] = []

        async def page_action(page):
            result = await _drive_divorce_search(page, TARGET_COUNTIES, self.LOOKBACK_DAYS)
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
            log.warning("nc_ecourts_divorce.fetch_fail", error=str(exc)[:200])
            return []

        listings: list[Listing] = []
        seen: set[str] = set()
        for row in captured:
            li = _row_to_listing(row, self.slug)
            if li is None:
                continue
            key = (li.case_number or "", li.county or "",
                   (li.plaintiff or "").lower(), (li.defendant or "").lower())
            if key in seen:
                continue
            seen.add(key)
            listings.append(li)

        log.info("nc_ecourts_divorce.parsed", listings=len(listings),
                 raw_rows=len(captured))
        return listings


# Quick local iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.nc_ecourts_divorce
if __name__ == "__main__":
    async def _main() -> None:
        scraper = NCECourtsDivorce()
        results = await scraper.safe_run()
        print(f"outcome={scraper.last_outcome} reason={scraper.last_reason}")
        print(f"parsed: {len(results)}")
        for x in results[:8]:
            print(f"  {x.county}: case={x.case_number} {x.plaintiff} vs {x.defendant}")

    asyncio.run(_main())
