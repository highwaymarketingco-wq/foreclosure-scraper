"""SC divorce-distress enricher — Family Court FCCMS PublicAccess portal (FREE, public).

WHAT THIS IS FOR
----------------
An Upstate-SC core-county lead whose owner_name turns up an open/recent DIVORCE
(Family Court "Marital Dissolution" — case-category 110-Divorce / 130-Separate
Support / 199-Marital Dissolution) is a high-motivation seller: a contested
divorce routinely forces the marital home to be sold to divide assets. This
overlays the foreclosure/tax distress with a 'divorce' situation the board
otherwise can't see, in the SAME enricher shape as the ROD + nc_divorce
enrichers (idempotent, env-gated, HOT/stale-first, capped, fetched_at refresh).

It searches each SC core-county lead's owner_name by PARTY NAME in the SC
Family Court FCCMS PublicAccess portal (https://portal.fccms.sccourts.org), a
SEPARATE portal from the publicindex foreclosure portal. This is the
Family-Court (Marital Dissolution / Domestic Relations) index — the only public
SC source for divorce filings. It writes
raw['divorce'] = {state, county, case_count, cases:[...], source:'sc_fccms'}
and adds 'divorce' to raw['distress_stack'].categories.

LIVE-VERIFIED FLOW (reproduced 2026-06-30, all compliant — free, public,
read-only; no login / CAPTCHA / paywall defeated)
-------------------------------------------------------------------------
The portal is an Angular SPA whose API client (chunk-*.js, read as public JS)
revealed the exact request shapes. One CSRF token + cookie session serves every
lead (we handshake ONCE, not per-lead):

  1. GET  /                          -> seats the SPA cookies (HTTP 200).
  2. POST /Home/GetAntiForgeryToken  -> HTTP 200, {"RequestVerificationToken":"<tok>"}.
     The Angular HTTP interceptor (main.js: pr()) replays <tok> as request
     header "X-CSRF-TOKEN" on every subsequent API call; we also send it as
     "RequestVerificationToken" + "Access-Control-Allow-Origin: *".
  3. POST /apiurl/api/FEPublicAccessValidationCodes/Validationcode
        body {"codeType":"LOCATION"|"CASECATEGORY","includeExpired":false}
        -> {"validationCodes":[{codeID, code, description}, ...]}.
     Confirmed core-county LOCATION codeIDs and CASECATEGORY codeIDs below
     (live-pulled, not hard-guessed).
  4. POST /apiurl/api/PublicPersonSearch  -> the divorce case rows.
     Body is a JSON ARRAY of property objects, assembled by the SPA's ve()
     payload builder (chunk-GSTQGXVR.js):
        [ {"PropertyName":"UpperLastName","Value":"SMITH","IsMerged":true,
           "IsWildCardSeacrh":false,"IsSoundex":false},
          {"PropertyName":"UpperFirstName","Value":"JOHN",...},   # when known
          {"PropertyName":"PALocation","Value":"1046","IsMerged":true},  # county codeID
          {"PropertyName":"MergedID","Value":1,"IsMerged":true},
          {"Source":"PublicAccess","PACaseCategoryId":1062} ]     # 110-Divorce
     ("IsWildCardSeacrh" is the portal's own spelling — kept verbatim.)
     Returns 200 with case rows: CaseId (e.g. "2000DR4200064", DR = Domestic
     Relations docket), CaseDescription ("LISA SMITH vs. JOHN SMITH" = parties),
     CaseInitialFilingDate, CaseCategory ("110 - Divorce"), LocationName,
     ParticipantRole. An OVER-CAP guard row returns
     {originalNumber, limitedNumber:500} with null fields when a query matches
     >500 rows (SMITH alone in Spartanburg = 1449) — proof thousands are
     indexed; we narrow with the owner's first name to drop under the cap.

COMPLIANCE: public + free court records, read-only party-name index lookups.
No CAPTCHA / login / paywall is defeated (the portal has none on this search).
Name-only matching means namesakes are possible, so flags are advisory; we trim
namesakes by requiring the owner's last (and first, if known) name in the case
style, exactly like the ROD enrichers. Default-ON (FORECLOSURE_SC_DIVORCE=1);
set FORECLOSURE_SC_DIVORCE=0 to disable.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

import structlog

try:
    from curl_cffi.requests import AsyncSession
except Exception:  # pragma: no cover
    AsyncSession = None

log = structlog.get_logger()


# ---------- Config -----------------------------------------------------------------

BASE = "https://portal.fccms.sccourts.org"
API = BASE + "/apiurl/api/"
TOKEN_URL = BASE + "/Home/GetAntiForgeryToken"
SEARCH_URL = API + "PublicPersonSearch"

# 7 Upstate-SC core counties -> FCCMS LOCATION codeID (live-pulled from the
# Validationcode LOCATION list 2026-06-30; matches config.SC_COUNTIES).
_COUNTY_CODE = {
    "Spartanburg": 1046,
    "Anderson": 1008,
    "Pickens": 1043,
    "Oconee": 1041,
    "Cherokee": 1015,
    "Union": 1048,
    "Laurens": 1034,
    # Greenville is geographically core but pruned from the scrape footprint;
    # included so a stray Greenville lead still resolves a code if present.
    "Greenville": 1027,
}

# Divorce / marital-dissolution CASECATEGORY codeIDs (live-pulled). We search
# each so a separate-support or "other dissolution" filing is also caught.
#   1062 = 110 - Divorce
#   1064 = 130 - Separate Support and Maintenance
#   1067 = 199 - Marital Dissolution - Other
_DIVORCE_CATEGORIES = (
    (1062, "110 - Divorce"),
    (1064, "130 - Separate Support and Maintenance"),
    (1067, "199 - Marital Dissolution - Other"),
)

# Per-run cap + refresh windows. The API is fast (~1 req/category/lead) so the
# cap is generous; bounded only so a single run can't sweep the whole board in
# one go if the operator wants to stage it. Idempotent across runs via fetched_at.
_DEFAULT_CAP = int(os.environ.get("FORECLOSURE_SC_DIVORCE_MAX", "400"))
_REFRESH_DAYS = float(os.environ.get("FORECLOSURE_SC_DIVORCE_REFRESH_DAYS", "30"))
_REFRESH_HOT_DAYS = float(os.environ.get("FORECLOSURE_SC_DIVORCE_REFRESH_HOT_DAYS", "7"))
_CALL_TIMEOUT_S = float(os.environ.get("FORECLOSURE_SC_DIVORCE_CALL_TIMEOUT_S", "20"))
# Wall-clock cap on the whole run so a throttled/hanging FCCMS can't drag it on for hours
# (it hung ~6h once on a 1,677-lead bulk pass). Unreached leads retry next run via the refresh window.
_BUDGET_S = float(os.environ.get("FORECLOSURE_SC_DIVORCE_BUDGET_S", "1800"))
_PER_QUERY_CAP = 25  # max case rows kept per lead


# ---------- Owner-name handling (mirrors the ROD + nc_divorce enrichers) ------------

def _name_parts(owner: str) -> tuple[str, str]:
    """('SMITH, JOHN') -> ('SMITH','JOHN'); board 'LAST FIRST &' / 'A;B' fall back.

    The board stores owners as 'LAST FIRST MIDDLE &' (no comma), sometimes with
    '&', '<br>' or ';' joining couples — we use the FIRST owner for the party
    query. Strips everything but letters/comma/space, so '&', '<br>' and digits
    drop out cleanly.
    """
    o = re.split(r"[;]|<br\s*/?>", owner or "", maxsplit=1)[0]
    o = re.sub(r"[^A-Za-z, ]", " ", o).upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def _owner_in_case(blob: str, last: str, first: str) -> bool:
    """Namesake trim: require the owner's last name (and first, if known) in the
    case style text."""
    up = (blob or "").upper()
    return bool(last) and last in up and (not first or first in up)


# ---------- Request payload (exact SPA ve() shape) ---------------------------------

def _search_payload(last: str, first: str, county_code: int, category_id: int) -> list:
    """Build the PublicPersonSearch JSON-array body the Angular SPA sends."""
    body: list = [
        {"PropertyName": "UpperLastName", "Value": last, "IsMerged": True,
         "IsWildCardSeacrh": False, "IsSoundex": False},
    ]
    if first:
        body.append({"PropertyName": "UpperFirstName", "Value": first, "IsMerged": True,
                     "IsWildCardSeacrh": False, "IsSoundex": False})
    body += [
        {"PropertyName": "PALocation", "Value": str(county_code), "IsMerged": True},
        {"PropertyName": "MergedID", "Value": 1, "IsMerged": True},
        {"Source": "PublicAccess", "PACaseCategoryId": category_id},
    ]
    return body


def _is_overcap(rows: list) -> bool:
    """The portal's over-limit guard row: originalNumber > limitedNumber with
    null case fields (matched too many to return)."""
    if not rows or not isinstance(rows[0], dict):
        return False
    r0 = rows[0]
    on, ln = r0.get("originalNumber"), r0.get("limitedNumber")
    return (isinstance(on, (int, float)) and isinstance(ln, (int, float))
            and on > ln and not r0.get("CaseId"))


def _parse_rows(rows: list, last: str, first: str, category_label: str) -> list[dict]:
    """Turn PublicPersonSearch rows into [{case_number, filed_date, parties,
    category}], namesake-trimmed + deduped."""
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        case_no = (r.get("CaseId") or "").strip()
        if not case_no:
            continue
        parties = re.sub(r"\s+", " ", (r.get("CaseDescription") or "")).strip()
        # Namesake trim against the case style (parties); fall back to the
        # person-name field the portal echoes.
        blob = f"{parties} {r.get('PersonName') or ''}"
        if not _owner_in_case(blob, last, first):
            continue
        key = re.sub(r"[^A-Z0-9]", "", case_no.upper())
        if key in seen:
            continue
        seen.add(key)
        filed = r.get("CaseInitialFilingDate")
        if isinstance(filed, str) and filed.startswith("0001-01-01"):
            filed = None
        elif isinstance(filed, str):
            filed = filed[:10]  # YYYY-MM-DD
        out.append({
            "case_number": case_no,
            "filed_date": filed,
            "parties": parties or None,
            "category": r.get("CaseCategory") or category_label,
            "role": r.get("ParticipantRole"),
        })
        if len(out) >= _PER_QUERY_CAP:
            break
    return out


# ---------- HOT/stale ordering (same windows as nc_divorce) ------------------------

def _divorce_age_days(li, now: datetime) -> float | None:
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
    """Write raw['divorce'] + add 'divorce' to distress_stack.categories (guarded)."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["divorce"] = {
        "state": li.state,
        "county": (li.county or "").strip(),
        "case_count": len(cases),
        "cases": cases,
        "source": "sc_fccms",
        "fetched_at": now.isoformat(),
    }
    if cases:
        ds = li.raw.get("distress_stack")
        if isinstance(ds, dict):
            cats = ds.setdefault("categories", [])
            if isinstance(cats, list) and "divorce" not in cats:
                cats.append("divorce")


# ---------- Session handshake (once, shared across all leads) ----------------------

async def _handshake(session) -> str | None:
    """GET / to seat cookies, POST GetAntiForgeryToken -> CSRF token. One per run."""
    try:
        await session.get(BASE + "/", impersonate="chrome", timeout=30)
        r = await session.post(TOKEN_URL, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("RequestVerificationToken")
    except Exception:  # noqa: BLE001
        return None


async def _search_one(session, headers, last: str, first: str, county_code: int) -> list[dict]:
    """Search all divorce categories for one owner; return merged, deduped cases."""
    found: list[dict] = []
    seen: set[str] = set()
    for cat_id, label in _DIVORCE_CATEGORIES:
        payload = _search_payload(last, first, county_code, cat_id)
        try:
            r = await asyncio.wait_for(
                session.post(SEARCH_URL, json=payload, headers=headers,
                             impersonate="chrome", timeout=_CALL_TIMEOUT_S),
                timeout=_CALL_TIMEOUT_S + 5,
            )
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200:
            continue
        try:
            rows = r.json()
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(rows, list) or not rows:
            continue
        if _is_overcap(rows):
            # Too many namesakes to return without a first name; skip this
            # category rather than emit a bogus hit. (Owners with a first name
            # almost never over-cap.)
            continue
        for c in _parse_rows(rows, last, first, label):
            key = re.sub(r"[^A-Z0-9]", "", c["case_number"].upper())
            if key not in seen:
                seen.add(key)
                found.append(c)
        await asyncio.sleep(0.2)
    return found


# ---------- Main entry -------------------------------------------------------------

async def enrich_sc_divorce(listings, max_lookups: int | None = None) -> dict:
    """For SC Upstate core-county leads with an owner_name, find Family-Court
    divorce / marital-dissolution cases by party name and attach raw['divorce']
    + the 'divorce' distress category.

    Default-ON (FORECLOSURE_SC_DIVORCE=1; set =0 to disable). One CSRF token +
    cookie session is reused across ALL leads (we handshake once). HOT/stale-first
    ordered, per-run capped (FORECLOSURE_SC_DIVORCE_MAX), idempotent via a
    fetched_at refresh window — exactly like the ROD + nc_divorce enrichers.

    COMPLIANCE: free public court records, read-only party-name index lookups; no
    CAPTCHA/login/paywall defeated.
    """
    if AsyncSession is None or os.environ.get("FORECLOSURE_SC_DIVORCE", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_SC_DIVORCE=0)"}

    now = datetime.now(timezone.utc)
    cap = max_lookups if max_lookups is not None else _DEFAULT_CAP

    targets = [li for li in listings
               if li.state == "SC"
               and (li.county or "").strip() in _COUNTY_CODE
               and li.owner_name
               and _stale(li, now)]
    # Never-fetched first, then stalest first — a cap-trimmed run still progresses.
    targets.sort(key=lambda li: (_divorce_age_days(li, now) is not None,
                                 -(_divorce_age_days(li, now) or 1e9)))
    total_pending = len(targets)
    targets = targets[:cap]

    stats = {"pending": total_pending, "targets": len(targets), "searched": 0,
             "with_divorce": 0, "cases_found": 0, "errors": 0, "budget_exhausted": False}
    if not targets:
        return stats

    import time as _time
    _t0 = _time.monotonic()
    consec_err = 0
    async with AsyncSession(verify=False) as s:
        token = await _handshake(s)
        if not token:
            return {**stats, "error": "handshake_failed"}
        headers = {
            "X-CSRF-TOKEN": token,
            "RequestVerificationToken": token,
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Referer": BASE + "/",
            "Origin": BASE,
        }
        for li in targets:
            if _time.monotonic() - _t0 > _BUDGET_S:
                stats["budget_exhausted"] = True
                break
            if consec_err >= 12:
                stats["aborted_throttled"] = True  # FCCMS is failing every call -> stop, retry later
                break
            last, first = _name_parts(li.owner_name)
            if not last:
                continue
            county_code = _COUNTY_CODE[(li.county or "").strip()]
            try:
                cases = await _search_one(s, headers, last, first, county_code)
                consec_err = 0
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
                consec_err += 1
                continue  # leave unstamped -> retried next run
            stats["searched"] += 1
            _apply(li, cases, now)
            if cases:
                stats["with_divorce"] += 1
                stats["cases_found"] += len(cases)
            await asyncio.sleep(0.2)

    log.info("sc_divorce.enrich.done", **stats)
    return stats
