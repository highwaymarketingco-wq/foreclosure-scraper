"""Authenticated NC eCourts Tyler portal scraper.

Uses Scrapling StealthyFetcher with full WAF-bypass arsenal:
  - solve_cloudflare=True: auto-solves Cloudflare/AWS-WAF challenges
  - google_search=True: sets Google as referer (mimics organic traffic)
  - real_chrome=True (when chrome installed): authentic browser fingerprint
  - user_data_dir: persistent profile so session cookies survive across
    runs (skip re-login if recent session is still valid)

Auth flow when WAF challenge is solved:
  1. GET /Portal/Account/Login → 302 to IdP signin
  2. WAF challenge auto-solved by solve_cloudflare
  3. Fill username + password, click Sign In
  4. WS-Fed token → portal session cookies
  5. Loop through case-number lookups using same browser context

Earlier attempts (runs #5-7) showed last_step='no_username_field' with
the WAF challenge URL as landed_url — Scrapling without solve_cloudflare
was reaching the challenge page but couldn't see the actual form. With
solve_cloudflare enabled, the challenge is supposed to resolve before
page_action runs.

If it STILL fails (Tyler's WAF is custom-tuned), the code reports
detailed step-by-step status (LAST_RUN_STATUS) so we know exactly which
step died — and the heuristic + ROD path always runs as fallback.

Set NC_ECOURTS_SKIP=1 to skip the entire Tyler attempt without
disabling the heuristic fallback.
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

    Side-effect: updates LAST_RUN_STATUS at each milestone so we can see
    exactly where the flow died (visible in run_health.json next run).
    """
    out: dict[str, dict] = {}

    # Step 1: Land at portal — Tyler's WS-Fed wrapper redirects to IdP login
    LAST_RUN_STATUS["last_step"] = "landing_login_url"
    try:
        await page.goto(LOGIN_URL, wait_until="networkidle", timeout=45000)
    except Exception as exc:
        log.warning("nc_ecourts.auth.land_fail", error=str(exc)[:200])
        LAST_RUN_STATUS.update({
            "last_step": "land_failed",
            "step_error": str(exc)[:200],
            "landed_url": None,
        })
        return out

    LAST_RUN_STATUS["landed_url"] = page.url[:200]

    # Step 1b: Detect AWS WAF challenge. The challenge page lacks our
    # expected username field, so before declaring failure, try to solve
    # the WAF via CapSolver (when CAPSOLVER_API_KEY is set).
    waf_challenge_detected = False
    try:
        # WAF challenge pages are short (< 2KB), have no form inputs,
        # and contain 'awswaf' / 'captcha' markers in the body.
        body_text = await page.content()
        if (len(body_text) < 5000 and
                ("awswaf" in body_text.lower() or "captcha" in body_text.lower())):
            waf_challenge_detected = True
        # Also: if no <input type=password>, the real form didn't render
        try:
            await page.wait_for_selector('input[type="password"]', timeout=2000)
        except Exception:
            waf_challenge_detected = True
    except Exception:
        pass

    if waf_challenge_detected:
        LAST_RUN_STATUS["last_step"] = "waf_challenge_detected"
        log.info("nc_ecourts.auth.waf_challenge_detected", url=page.url[:200])

        # Primary path: free OSS browser-driven solver using Gemini for
        # image recognition (uses the GEMINI_API_KEY_* keys already wired
        # for vision). No paid CAPTCHA service required.
        from .enrichment_waf_oss import solve_waf_via_browser
        solved = await solve_waf_via_browser(page)

        # Fallback path: CapSolver token-injection (only if CAPSOLVER_API_KEY
        # is set in env and the OSS browser solve failed).
        if not solved and os.environ.get("CAPSOLVER_API_KEY"):
            log.info("nc_ecourts.auth.waf_oss_failed_trying_capsolver")
            from .enrichment_capsolver import solve_aws_waf
            token = await solve_aws_waf(page.url)
            if token:
                try:
                    await page.context.add_cookies([{
                        "name": "aws-waf-token",
                        "value": token,
                        "domain": ".tylerhost.net",
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "None",
                    }])
                    await page.reload(wait_until="networkidle", timeout=45000)
                    solved = True
                except Exception as exc:
                    LAST_RUN_STATUS.update({
                        "last_step": "waf_cookie_inject_failed",
                        "step_error": str(exc)[:200],
                    })
                    return out

        if not solved:
            LAST_RUN_STATUS.update({
                "last_step": "waf_solve_failed",
                "step_error": (
                    "Browser-driven OSS solve failed. "
                    "Check GEMINI_API_KEY_* secrets are set + 2.5-flash has quota. "
                    "Set CAPSOLVER_API_KEY as a paid fallback if this keeps failing."
                ),
            })
            return out

        LAST_RUN_STATUS["last_step"] = "waf_solved_reloaded"
        LAST_RUN_STATUS["landed_url"] = page.url[:200]
        log.info("nc_ecourts.auth.waf_solved", url=page.url[:200])

    # Step 2: Fill credentials on the IdP signin page.
    LAST_RUN_STATUS["last_step"] = "filling_username"
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
        log.warning("nc_ecourts.auth.no_username_field", landed_url=page.url[:200])
        LAST_RUN_STATUS.update({
            "last_step": "no_username_field",
            "step_error": "couldn't find username input on IdP signin page",
        })
        return out

    LAST_RUN_STATUS["last_step"] = "filling_password"
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
        LAST_RUN_STATUS.update({
            "last_step": "no_password_field",
            "step_error": "couldn't find password input",
        })
        return out

    # Step 3: Submit the form.
    LAST_RUN_STATUS["last_step"] = "submitting_login"
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
    LAST_RUN_STATUS["last_step"] = "waiting_portal_redirect"
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    cur = page.url
    LAST_RUN_STATUS["post_login_url"] = cur[:200]
    if "portal-nc.tylertech.cloud" not in cur:
        log.warning("nc_ecourts.auth.redirect_fail", landed_at=cur[:200])
        LAST_RUN_STATUS.update({
            "last_step": "redirect_fail",
            "step_error": f"after login, landed at {cur[:120]} not portal-nc",
        })
        return out

    log.info("nc_ecourts.auth.success", landed_at=cur[:120])
    LAST_RUN_STATUS.update({
        "last_step": "login_succeeded",
        "step_error": None,
    })

    # Step 5: Loop through cases.
    LAST_RUN_STATUS["last_step"] = "querying_cases"
    cases_attempted = 0
    cases_with_data = 0
    for case_number in case_numbers:
        cases_attempted += 1
        try:
            info = await _query_one_case(page, case_number)
            if info:
                out[case_number] = info
                cases_with_data += 1
        except Exception as exc:
            log.debug("nc_ecourts.case_fail", case=case_number, error=str(exc)[:120])
            continue

    LAST_RUN_STATUS.update({
        "last_step": "case_loop_done",
        "cases_attempted": cases_attempted,
        "cases_with_data": cases_with_data,
    })
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

    # NC_ECOURTS_SKIP=1 skips entirely without trying.
    if os.environ.get("NC_ECOURTS_SKIP") == "1":
        log.info("nc_ecourts.auth.skip_via_env")
        LAST_RUN_STATUS.update({
            "outcome": "skipped",
            "reason": "NC_ECOURTS_SKIP=1 in env",
        })
        return 0

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
            timeout=240000,  # 4 min: WAF-solve + login + ~50 case lookups
            page_action=page_action,
            # WAF-bypass arsenal:
            solve_cloudflare=True,    # auto-solves Cloudflare/AWS-WAF challenges
            google_search=True,       # Google as referer (mimics organic)
            wait=5000,                # 5s settle so Scrapling 0.4.8's updated
                                       # browser fingerprints have time to
                                       # establish before the page reads them
            retries=2,                # retry once on transient WAF/network blips
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
