"""Authenticated NC eCourts Tyler portal scraper.

The WAF-blocked /Portal/Home/Dashboard/29 endpoint becomes accessible
when we present session cookies from a verified-account login. The auth
flow is WS-Federation:

  1. GET /Portal/Account/Login → 302 to odysseyidentityprovider.tylerhost.net
  2. POST credentials to IdP signin form
  3. IdP returns WS-Fed token + redirects back to /Portal/
  4. Portal sets session cookies (".ASPXAUTH" et al)
  5. Subsequent /Home/Dashboard/29 requests carry these cookies and
     pass the WAF's verified-human check

We drive the entire flow in a single Playwright session via Scrapling's
StealthyFetcher (one login → many case lookups). Falls back to the
heuristic path silently when login fails so the run still produces a
result.

Credentials are read from env (NEVER hardcode):
  NC_ECOURTS_USERNAME, NC_ECOURTS_PASSWORD

Output dict shape mirrors the heuristic enrichment so downstream code
(comp matcher, dashboard popouts) is path-agnostic. Adds:
  - method = "tyler_authenticated"
  - last_event_date / last_event_text from the docket
  - sold_price (when Order Confirming Sale carries the hammer price)
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


PORTAL_BASE = "https://portal-nc.tylertech.cloud/Portal"
LOGIN_URL = f"{PORTAL_BASE}/Account/Login"
SEARCH_URL = f"{PORTAL_BASE}/Home/Dashboard/29"

# Concurrency = 1 (single browser session, sequential case lookups) since
# we share one auth context. Cap defaults to 50 cases per run to stay
# polite + avoid Tyler rate limits.
DEFAULT_CAP = int(os.environ.get("NC_ECOURTS_AUTH_CAP", "50"))

# Sold-price patterns mirrored from the legacy regex-based extractor.
# Order matters: most-specific first so judgment amounts don't outrank
# the actual hammer price.
SOLD_PRICE_PATTERNS = [
    re.compile(r"high\s+bid(?:\s+of)?\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    re.compile(r"sold\s+(?:to\s+[^$\n]{1,80}?\s+)?for\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    re.compile(r"purchas(?:e\s+price|ed\s+for)\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    re.compile(r"(?:confirm[a-z]*|report\s+of\s+sale)[^\n$]{0,80}\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    re.compile(r"(?:successful|winning)\s+bid\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    re.compile(r"sale\s+price\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
]

STATUS_PATTERNS = [
    (r"\bdismissed\b|\bdismiss\b", "dismissed"),
    (r"\bconfirmed\b|\border confirming sale\b", "confirmed"),
    (r"\bupset bid\b", "upset_bid"),
    (r"\bsold\b|\breport of sale\b", "sold"),
    (r"\bpending\b|\bscheduled\b", "scheduled"),
]


def _extract_sold_price(text: str) -> Optional[float]:
    if not text:
        return None
    for pat in SOLD_PRICE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if 100 <= v <= 10_000_000:
            return v
    return None


def _normalize_status(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, t):
            return status
    return None


def _within_n_days(date_str: str, n: int) -> bool:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            d = datetime.strptime(date_str, fmt)
            return (datetime.utcnow() - d).days < n
        except ValueError:
            continue
    return False


async def _drive_login_and_search(
    page,
    username: str,
    password: str,
    case_numbers: list[str],
) -> dict[str, dict]:
    """Single browser session: login once, query each case sequentially.

    Returns dict mapping case_number → parsed info (status / sold_price /
    last_event). Cases that error out are simply absent from the result.
    """
    out: dict[str, dict] = {}

    # Step 1: Land at portal — Tyler's WS-Fed wrapper redirects to IdP login
    try:
        await page.goto(LOGIN_URL, wait_until="networkidle", timeout=45000)
    except Exception as exc:
        log.warning("nc_ecourts.auth.land_fail", error=str(exc)[:200])
        return out

    # Step 2: Fill credentials on the IdP signin page. Tyler IdP uses
    # standard ASP.NET Identity field names — Username / Password / Sign In
    # button — but selectors vary across IdP versions. Try several.
    user_filled = False
    for sel in (
        'input[name="Username"]',
        'input[name="UserName"]',
        'input[id*="Username"]',
        'input[type="email"]',
        'input[name*="user" i]',
    ):
        try:
            await page.wait_for_selector(sel, timeout=8000)
            await page.fill(sel, username)
            user_filled = True
            break
        except Exception:
            continue
    if not user_filled:
        log.warning("nc_ecourts.auth.no_username_field")
        return out

    pwd_filled = False
    for sel in (
        'input[name="Password"]',
        'input[id*="Password"]',
        'input[type="password"]',
    ):
        try:
            await page.fill(sel, password)
            pwd_filled = True
            break
        except Exception:
            continue
    if not pwd_filled:
        log.warning("nc_ecourts.auth.no_password_field")
        return out

    # Step 3: Submit the form. Try Enter key first (works on most IdP
    # forms); fall back to clicking submit buttons.
    try:
        await page.press('input[type="password"]', "Enter")
    except Exception:
        for btn in (
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Sign In")',
            'button:has-text("Login")',
        ):
            try:
                await page.click(btn, timeout=4000)
                break
            except Exception:
                continue

    # Step 4: Wait for redirect chain back to portal (WS-Fed bounces
    # through several URLs). Check we land on a portal-NC URL.
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    cur = page.url
    if "portal-nc.tylertech.cloud" not in cur:
        log.warning("nc_ecourts.auth.redirect_fail", landed_at=cur[:200])
        return out

    log.info("nc_ecourts.auth.success", landed_at=cur[:120])

    # Step 5: Loop through cases. Tyler's Smart Search Dashboard accepts
    # case-number searches via a single input. Re-navigate to the search
    # page for each case (cheaper than maintaining stateful filters).
    for case_number in case_numbers:
        try:
            info = await _query_one_case(page, case_number)
            if info:
                out[case_number] = info
        except Exception as exc:
            log.debug("nc_ecourts.case_fail", case=case_number, error=str(exc)[:120])
            continue

    return out


async def _query_one_case(page, case_number: str) -> Optional[dict]:
    """Search Tyler for one case# and parse its detail page."""
    try:
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
    except Exception:
        return None

    # Optional: click a "Case Search" sub-tab if Tyler split it out
    for sel in (
        'a:has-text("Case Search")',
        'button:has-text("Case Search")',
        '[data-search-type="caseNumber"]',
    ):
        try:
            await page.click(sel, timeout=3000)
            await page.wait_for_load_state("networkidle", timeout=8000)
            break
        except Exception:
            continue

    # Fill case# input — selector varies across Tyler tenants
    filled = False
    for sel in (
        'input[name="caseNumber"]',
        'input[id*="Case"]',
        '#caseNumber',
        'input[placeholder*="ase" i]',
    ):
        try:
            await page.wait_for_selector(sel, timeout=6000)
            await page.fill(sel, case_number)
            filled = True
            break
        except Exception:
            continue
    if not filled:
        return None

    # Submit
    try:
        await page.press('input[name="caseNumber"]', "Enter")
    except Exception:
        for btn in ('button[type="submit"]', 'input[type="submit"]'):
            try:
                await page.click(btn, timeout=3000)
                break
            except Exception:
                continue
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    # Click into the result row to load case-detail (where docket lives)
    for sel in (
        f'a:has-text("{case_number}")',
        "table.search-results tr:first-of-type a",
        "table tr td:first-of-type a",
    ):
        try:
            await page.click(sel, timeout=4000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            break
        except Exception:
            continue

    # Extract page content
    try:
        html = await page.content()
    except Exception:
        return None
    if not html or len(html) < 1000:
        return None

    return _parse_case_detail_html(html)


def _parse_case_detail_html(html: str) -> Optional[dict]:
    """Extract status + last event + sold_price from a Tyler case-detail page."""
    events = re.findall(
        r"(\d{1,2}/\d{1,2}/\d{2,4})\s*[\-:]?\s*([A-Z][\w \-,/.()&'\"]{8,200})",
        html,
    )
    last_event = events[0] if events else None

    status = _normalize_status(html)
    if not status:
        return None

    info: dict = {
        "status": status,
        "method": "tyler_authenticated",
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
    if last_event:
        info["last_event_date"] = last_event[0]
        info["last_event_text"] = last_event[1].strip()[:200]

    in_window = status == "upset_bid" or (
        status == "sold" and last_event and _within_n_days(last_event[0], 14)
    )
    info["in_upset_bid_window"] = in_window
    if last_event and in_window:
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                d = datetime.strptime(last_event[0], fmt)
                info["upset_bid_deadline"] = (d + timedelta(days=14)).date().isoformat()
                break
            except ValueError:
                continue

    if status in ("sold", "confirmed", "upset_bid"):
        sp = _extract_sold_price(html)
        if sp is not None:
            info["sold_price"] = sp
    return info


# Module-level last-run status — surfaced in run_health.json by the
# orchestrator so we can see auth success/failure per run.
LAST_RUN_STATUS: dict = {
    "outcome": "not_attempted",
    "reason": None,
    "tagged": 0,
    "targets": 0,
    "checked_at": None,
}


def get_last_run_status() -> dict:
    """Return a copy of the most recent auth-path run status. Used by
    orchestrator + patch_run to fold into run_health.json."""
    return dict(LAST_RUN_STATUS)


async def enrich_with_nc_case_status_authenticated(
    listings: list[Listing], max_cases: Optional[int] = None
) -> int:
    """Authenticated Tyler path. Returns number of listings tagged.
    Returns 0 (and logs) when creds are missing or login fails.
    Caller is responsible for falling back to the heuristic path.

    Side effect: updates LAST_RUN_STATUS so the orchestrator can surface
    the outcome in run_health.json (visible in workflow summary).
    """
    LAST_RUN_STATUS.update({
        "outcome": "not_attempted",
        "reason": None,
        "tagged": 0,
        "targets": 0,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    })

    username = os.environ.get("NC_ECOURTS_USERNAME")
    password = os.environ.get("NC_ECOURTS_PASSWORD")
    if not username or not password:
        log.info("nc_ecourts.auth.no_creds")
        LAST_RUN_STATUS.update({
            "outcome": "skipped",
            "reason": "no_credentials_in_env",
        })
        return 0

    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("nc_ecourts.auth.scrapling_missing")
        LAST_RUN_STATUS.update({
            "outcome": "skipped",
            "reason": "scrapling_not_installed",
        })
        return 0

    targets = [
        li
        for li in listings
        if li.state == "NC"
        and li.case_number
        and li.source not in ("national.courtlistener_bankruptcy",)
    ]

    # Prioritize: recent past sales (upset-bid window) first, then
    # scheduled-soon, then everything else.
    def _priority(li: Listing) -> tuple:
        if li.sale_date:
            d = li.sale_date.replace(tzinfo=None) if li.sale_date.tzinfo else li.sale_date
            days = (datetime.utcnow() - d).days
            if 0 <= days <= 14:
                return (0, days)
            if -14 <= days < 0:
                return (1, abs(days))
            if 14 < days <= 60:
                return (2, days)
        return (3, 0)

    targets.sort(key=_priority)
    cap = max_cases if max_cases is not None else DEFAULT_CAP
    targets = targets[:cap]

    LAST_RUN_STATUS["targets"] = len(targets)
    if not targets:
        log.info("nc_ecourts.auth.no_targets")
        LAST_RUN_STATUS.update({"outcome": "no_targets"})
        return 0

    log.info("nc_ecourts.auth.start", target_count=len(targets))
    case_numbers = [li.case_number for li in targets if li.case_number]
    case_to_listing = {li.case_number: li for li in targets}

    # Closure dict captured by page_action
    captured: dict[str, dict] = {}

    async def page_action(page):
        result = await _drive_login_and_search(page, username, password, case_numbers)
        captured.update(result)

    try:
        await StealthyFetcher.async_fetch(
            LOGIN_URL,
            headless=True,
            network_idle=True,
            timeout=180000,  # 3 min: login + ~50 case lookups
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("nc_ecourts.auth.fetch_fail", error=str(exc)[:200])
        LAST_RUN_STATUS.update({
            "outcome": "fetch_exception",
            "reason": str(exc)[:200],
        })
        return 0

    tagged = 0
    for case_num, info in captured.items():
        li = case_to_listing.get(case_num)
        if not li:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["nc_case_status"] = info
        tagged += 1
        # Hammer-price promotion: tag actual_sold_price so the
        # promote-to-sold-pool pass routes this listing into
        # foreclosure_sold_comps. Mirrors the legacy Tyler scraper's
        # promotion semantics.
        sp = info.get("sold_price")
        if sp and info.get("status") in ("sold", "confirmed", "upset_bid"):
            li.raw["actual_sold_price"] = sp
            li.raw.setdefault("nc_case_status", {})["promoted_to_sold_comp"] = True
            last_date = info.get("last_event_date")
            if last_date:
                for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                    try:
                        li.sale_date = datetime.strptime(last_date, fmt)
                        break
                    except ValueError:
                        continue

    log.info("nc_ecourts.auth.done", tagged=tagged, of=len(targets))
    LAST_RUN_STATUS.update({
        "outcome": "ok" if tagged > 0 else "login_or_search_failed",
        "tagged": tagged,
        "reason": (
            "no_cases_returned_from_tyler" if tagged == 0
            else None
        ),
    })
    return tagged
