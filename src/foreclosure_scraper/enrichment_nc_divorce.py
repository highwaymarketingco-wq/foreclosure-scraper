"""NC absolute-divorce (case-type CVD) distress enricher — NC eCourts Tyler Odyssey portal.

WHAT THIS IS FOR
----------------
A core-county NC lead whose owner_name turns up an open/recent ABSOLUTE DIVORCE
(district-court case-type **CVD**) is a high-motivation seller: a contested
divorce routinely forces the marital home to be sold to divide assets. This
overlays the foreclosure/tax distress with a 'divorce' situation the board
otherwise can't see, in the SAME enricher shape as the ROD enrichers
(idempotent, env-gated, HOT/stale-first, capped, fetched_at refresh).

It searches each NC core-county lead's owner_name by PARTY NAME in the NC
eCourts Tyler Odyssey portal (https://portal-nc.tylertech.cloud/Portal), the
same portal + Smart Search the repo already drives for SP foreclosure cases in
enrichment_courts.py, and reuses that file's `fetch_rendered` stealth-render
path (NOT the AWS-WAF Smart Search JSON API, which is WAF-walled). It writes
raw['divorce'] = {state, county, case_count, cases:[...], source:'nc_ecourts'}
and adds 'divorce' to raw['distress_stack'].categories.

CASE-TYPE FILTERING (CVD only, 50B excluded)
--------------------------------------------
NC district-civil case-type codes: **CVD = civil district (absolute divorce,
equitable distribution, alimony)**. We keep rows whose case-type/number is CVD
and DROP **50B (domestic-violence protective orders)** entirely — a 50B is a
safety matter, not a sale signal, and must never surface as a lead. `_is_cvd()`
encodes both rules; `_DV50B_RE` is the hard exclusion.

LIVE-VERIFICATION STATUS — BLOCKED BY AWS-WAF CAPTCHA (compliant dead-end)
-------------------------------------------------------------------------
Reproduced live 2026-06-30 against portal-nc.tylertech.cloud via the repo's
`fetch_rendered` (scrapling StealthyFetcher / camoufox), the exact path
enrichment_courts.py uses:

  * GET /Portal/  and  /Portal/Home/WorkspaceMode  -> HTTP 200 but only the
    "JavaScript must be enabled in order for you to use this application" BOOT
    SHELL (rendered text len 3070). The Odyssey Angular SPA never hydrates its
    Smart Search form under the headless stealth browser; driving it with a
    page_action + 6s network-idle wait yields exactly ONE <input> on the page —
    the "I'm still here" session-timeout button — never the search box.
  * GET /Portal/Home/Dashboard/29 (the search/results route) -> HTTP **405**
    with an explicit AWS-WAF interstitial: *"verify that you're not a robot by
    solving a CAPTCHA puzzle. The CAPTCHA puzzle requires JavaScript."*

So the only compliant way past Smart Search today is solving the AWS-WAF
CAPTCHA, which this project forbids. (This is the same wall that made
enrichment_courts.py abandon its per-case WorkspaceMode render — see its
docstring: it "filled 0 fields while costing hours" — and pivot to the public
NCJudgmentSearchService JSON API. That judgment service indexes lien/judgment
hits, NOT raw CVD divorce filings, so it can't substitute here.)

Therefore this enricher is shipped **GATED OFF by default** (env
FORECLOSURE_NC_DIVORCE, default "0"). The parse/match/classify logic is complete
and idempotent so the moment a compliant render path exists — e.g. Tyler drops
the WAF on the public Smart Search, an operator supplies a cleared/rendered
session, or `fetch_rendered` gains a compliant hydrate path — flipping the flag
to "1" activates it with no code change. It will never run, and never emit a
network call, while the flag is off.

COMPLIANCE: public + free court records, read-only, party-name index lookups.
No CAPTCHA/login/paywall is defeated. 50B DV cases are excluded. Name-only
matching means namesakes are possible, so flags are advisory.
"""
from __future__ import annotations

import asyncio
import os
import re
import urllib.parse
from datetime import datetime, timezone

import structlog

from .render import fetch_rendered

log = structlog.get_logger()


# ---------- Config -----------------------------------------------------------------

# Western-NC / core counties only (matches the repo's core-county focus).
_CORE_COUNTIES = {
    "Buncombe", "Henderson", "Cleveland", "Gaston", "Rutherford", "Polk",
    "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke", "Madison",
}

# Tyler Odyssey portal Smart Search. We render the public search route; the
# `{q}` party-name query is URL-encoded. NOTE: this route is AWS-WAF gated today
# (see module docstring) — kept here so activation is a one-flag change once a
# compliant render path exists. Dashboard/29 is the NC portal's search node.
PORTAL_SEARCH = (
    "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29"
    "?q={q}&searchType=PartyName"
)

# Per-run cap + refresh windows (render is slow → bound it, like Spartanburg ROD).
_DEFAULT_CAP = int(os.environ.get("FORECLOSURE_NC_DIVORCE_MAX", "20"))
_REFRESH_DAYS = float(os.environ.get("FORECLOSURE_NC_DIVORCE_REFRESH_DAYS", "30"))
_REFRESH_HOT_DAYS = float(os.environ.get("FORECLOSURE_NC_DIVORCE_REFRESH_HOT_DAYS", "7"))
_CALL_TIMEOUT_S = float(os.environ.get("FORECLOSURE_NC_DIVORCE_CALL_TIMEOUT_S", "90"))


# ---------- Case-type filtering: CVD in, 50B out -----------------------------------

# Absolute-divorce / civil-district case numbers look like  24 CVD 1234  /
# 24-CVD-001234. Keep these.
_CVD_RE = re.compile(r"\b\d{2,4}\s?-?\s?CVD\s?-?\s?\d{1,6}\b", re.I)
# Domestic-violence 50B protective-order case numbers:  24 CVD 50B ... is filed
# under the CVD bucket in some counties, but the DV/50B marker is the hard
# exclusion. Drop ANY row carrying a 50B / domestic-violence marker.
_DV50B_RE = re.compile(r"\b50\s?-?\s?B\b|domestic\s+violence|\bDVPO\b|protective\s+order", re.I)
# A bare CVD case number anchor. We find each occurrence, then scan the
# surrounding rendered-text WINDOW for the style/parties and a filed date
# separately — the Odyssey results grid's text layout varies by county skin, so
# requiring case+parties+date in one contiguous match is too brittle.
_CVD_ANCHOR_RE = re.compile(r"\b\d{2,4}\s?-?\s?CVD\s?-?\s?\d{1,6}\b", re.I)
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _is_cvd(blob: str) -> bool:
    """True only if the row is an absolute-divorce CVD case AND not a 50B DV case."""
    if not blob:
        return False
    if _DV50B_RE.search(blob):
        return False
    return bool(_CVD_RE.search(blob))


# ---------- Owner-name handling ----------------------------------------------------

def _name_parts(owner: str) -> tuple[str, str]:
    """('SMITH, JOHN') -> ('SMITH','JOHN'); entity / 'LAST FIRST' fall back sensibly.

    Mirrors the ROD enrichers so behavior is consistent across the board. The
    board stores owners as 'LAST FIRST' (no comma) or 'A;B' for couples — we use
    the FIRST owner of a multi-owner string for the party query.
    """
    o = (owner or "").split(";")[0]
    o = re.sub(r"[^A-Za-z, ]", " ", o).upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def _party_query(last: str, first: str) -> str:
    """Build the 'Last, First' party-name query string for Smart Search."""
    return f"{last}, {first}".strip().strip(",").strip()


def _owner_in_case(blob: str, last: str, first: str) -> bool:
    """Namesake trim: require the owner's last name (and first, if known) to
    appear in the case style text."""
    up = (blob or "").upper()
    return bool(last) and last in up and (not first or first in up)


# ---------- Parse rendered Smart Search results ------------------------------------

def _parse_divorce_cases(text: str, last: str, first: str) -> list[dict]:
    """Pull CVD divorce case rows out of rendered Smart Search results text.

    Excludes 50B DV rows. Returns [{case_number, parties, filed_date}], capped.
    Tolerant text-scan because the Odyssey results grid renders to varying text
    layouts per county skin; we anchor on the CVD case number and grab the
    surrounding style + first date.
    """
    cases: list[dict] = []
    seen: set[str] = set()
    if not text:
        return cases
    matches = list(_CVD_ANCHOR_RE.finditer(text))
    for i, m in enumerate(matches):
        case_no = re.sub(r"\s+", " ", m.group(0)).strip().upper()
        # Row text = from this case number up to the NEXT case number, a newline,
        # or 200 chars — whichever comes first. Bounding to the row prevents the
        # next row's 50B/parties text from bleeding into this one.
        hard_end = min(m.end() + 200,
                       matches[i + 1].start() if i + 1 < len(matches) else len(text))
        rest_full = text[m.end(): hard_end]
        nl = rest_full.find("\n")
        rest = rest_full[:nl] if nl != -1 else rest_full
        window = m.group(0) + rest
        # Hard drop: 50B / domestic-violence rows never become leads.
        if _DV50B_RE.search(window):
            continue
        if not _owner_in_case(window, last, first):
            continue
        key = re.sub(r"[^A-Z0-9]", "", case_no)
        if key in seen:
            continue
        seen.add(key)
        # Parties = style text immediately after the case number (up to the date),
        # collapsed.
        dm = _DATE_RE.search(rest)
        parties = re.sub(r"\s+", " ", rest[: dm.start()] if dm else rest).strip()[:200]
        filed = dm.group(0) if dm else None
        cases.append({
            "case_number": case_no,
            "parties": parties or None,
            "filed_date": filed,
            "case_type": "CVD",
        })
        if len(cases) >= 25:
            break
    return cases


# ---------- HOT/stale ordering -----------------------------------------------------

def _divorce_age_days(li, now: datetime) -> float | None:
    """Days since this lead's divorce check was last fetched (None if never)."""
    dv = (li.raw or {}).get("divorce") if isinstance(li.raw, dict) else None
    fa = (dv or {}).get("fetched_at")
    if not fa:
        return None
    try:
        dt = datetime.fromisoformat(fa)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 86400.0
    except Exception:  # noqa: BLE001
        return None


def _imminent(li, now: datetime) -> bool:
    """HOT tier, or an auction within 30 days → refresh on the hot (shorter) window."""
    tier = ((li.raw or {}).get("distress_stack") or {}).get("tier") if isinstance(li.raw, dict) else None
    if tier == "HOT":
        return True
    sd = getattr(li, "sale_date", None)
    if sd:
        try:
            d = datetime.fromisoformat(str(sd)[:10]).replace(tzinfo=timezone.utc)
            return 0 <= (d - now).days <= 30
        except Exception:  # noqa: BLE001
            return False
    return False


def _stale(li, now: datetime) -> bool:
    age = _divorce_age_days(li, now)
    window = _REFRESH_HOT_DAYS if _imminent(li, now) else _REFRESH_DAYS
    return age is None or age >= window


# ---------- Apply to a single lead -------------------------------------------------

def _apply(li, cases: list[dict], now: datetime) -> None:
    """Write raw['divorce'] + add 'divorce' to distress_stack.categories."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["divorce"] = {
        "state": li.state,
        "county": (li.county or "").strip(),
        "case_count": len(cases),
        "cases": cases,
        "source": "nc_ecourts",
        "fetched_at": now.isoformat(),
    }
    if cases:
        ds = li.raw.get("distress_stack")
        if isinstance(ds, dict):
            cats = ds.setdefault("categories", [])
            if isinstance(cats, list) and "divorce" not in cats:
                cats.append("divorce")


# ---------- Main entry -------------------------------------------------------------

async def enrich_nc_divorce(listings, max_lookups: int | None = None) -> dict:
    """For NC core-county leads with an owner_name, find absolute-divorce (CVD)
    cases by party name and attach raw['divorce'] + the 'divorce' distress
    category.

    GATED OFF by default (FORECLOSURE_NC_DIVORCE, default "0") because the NC
    eCourts Smart Search is AWS-WAF/CAPTCHA-walled to automated renders today
    (see module docstring for live evidence). Set FORECLOSURE_NC_DIVORCE=1 only
    once a compliant render path exists. While off, this makes ZERO network
    calls.

    Render is slow, so this is HOT/stale-first ordered, per-run capped
    (FORECLOSURE_NC_DIVORCE_MAX, default 20), and idempotent (fetched_at refresh
    window), exactly like the Spartanburg ROD enricher.
    """
    if os.environ.get("FORECLOSURE_NC_DIVORCE", "0") != "1":
        return {"skipped": "disabled (FORECLOSURE_NC_DIVORCE=1 to enable; "
                           "blocked by NC eCourts AWS-WAF CAPTCHA — see module docstring)"}

    now = datetime.now(timezone.utc)
    cap = max_lookups if max_lookups is not None else _DEFAULT_CAP

    targets = [li for li in listings
               if li.state == "NC"
               and (li.county or "").strip().replace(" County", "") in _CORE_COUNTIES
               and li.owner_name
               and _stale(li, now)]
    # Never-fetched first, then stalest first — a cap-trimmed run still progresses.
    targets.sort(key=lambda li: (_divorce_age_days(li, now) is not None,
                                 -(_divorce_age_days(li, now) or 1e9)))
    total_pending = len(targets)
    targets = targets[:cap]

    stats = {"pending": total_pending, "targets": len(targets), "searched": 0,
             "with_divorce": 0, "cases_found": 0, "render_failures": 0}

    for li in targets:
        last, first = _name_parts(li.owner_name)
        if not last:
            continue
        q = urllib.parse.quote(_party_query(last, first))
        url = PORTAL_SEARCH.format(q=q)
        try:
            text = await asyncio.wait_for(
                fetch_rendered(url, raise_on_http_failure=True),
                timeout=_CALL_TIMEOUT_S,
            )
        except (Exception, asyncio.TimeoutError):
            stats["render_failures"] += 1
            continue  # render/WAF failure → leave unstamped, retry next run
        stats["searched"] += 1
        if not text:
            continue
        cases = _parse_divorce_cases(text, last, first)
        _apply(li, cases, now)
        if cases:
            stats["with_divorce"] += 1
            stats["cases_found"] += len(cases)
        await asyncio.sleep(0.3)

    log.info("nc_divorce.enrich.done", **stats)
    return stats
