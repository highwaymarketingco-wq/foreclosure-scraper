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

It searches each SC lead's owner_name (all 46 counties since 2026-10-07) by PARTY NAME in the SC
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

ACCURACY FIX (2026-10-02) -- 0% real matches at population scale.
-------------------------------------------------------------------------
A live population-scale check (n=58/5,052, the FULL previously-flagged
population) found ZERO confirmed real divorce cases against SC's own public
court index -- 98.3% genuine negatives, one inconclusive (a common name that
hit the portal's 250-row display cap). Investigated whether this was a
wrong-index/wrong-case-type problem (a real possibility the validation
raised explicitly) before touching the matching logic:

  * Re-pulled the LOCATION and CASECATEGORY validation-code lists LIVE
    2026-10-02 and confirmed every one of `_COUNTY_CODE`'s 8 codeIDs and
    `_DIVORCE_CATEGORIES`'s 3 codeIDs still resolves to exactly the county/
    category this module's own comments claim (1046=Spartanburg,
    1062="110 - Divorce", etc.) -- the index and the case-type filter are
    BOTH correct and current. This rules out the wrong-index hypothesis.
  * Live-probed real searches instead and found the actual mechanism: a
    PublicPersonSearch row's `ParticipantRole` can be "Attorney", "Mediator",
    "Guardian Ad Litem", "Third Party Defendant", etc. -- a court OFFICER,
    not a divorcing spouse -- and `_owner_in_case()`'s namesake trim checked
    a blob of the case caption PLUS the row's own `PersonName` field, which
    by construction ALWAYS contains the searched name (it is literally who
    matched the query). So the trim was a no-op for any non-party row:
    searching the common surname "Davis" returns "Davis, Davis, Joy C C" /
    role=Attorney for ~30 UNRELATED real divorce cases (a real SC family-law
    attorney with many clients), none of whose captions mention "Davis" at
    all, and the OLD code matched every single one.
  * Separately, even a role-CORRECT match on a common name is frequently
    the wrong same-named person: `party_middle_verdict()` was already
    computed for every hit since 2026-09-21 (41% of comparable hits proven
    conflicts) but only ever stored as advisory metadata -- an 'unverified'
    verdict (46% of all hits) passed straight through to
    distress_stack.categories with zero corroboration. The single highest-
    confidence pre-fix match on the board (an exact full name with 32 real
    FCCMS records under it) had none that could be confirmed as the actual
    property owner -- consistent with this exact ambiguity, not a wrong
    index.

Fixed both: `_is_party_role` rejects a non-party row before it ever reaches
`_owner_in_case` or raw['divorce']['cases'] (see its own comment), and
`_apply()` now requires `party_middle_verdict(...) == "agrees"` before
adding 'divorce' to distress_stack.categories (see its own docstring).
raw['divorce']['cases'] + ['match'] are still written for every hit
regardless of verdict -- never silent -- only the ACTIONABLE category is
gated. Measured impact on the existing board (read-only, not applied here):
of 5,052 existing hits, 40 become case-less (pure non-party echo) and 3,347
more fail the verdict gate -- 3,387/5,052 (67.0%) would be rejected, 1,665
(33.0%) would remain. This is distinct from the SAME-DAY commit that split
an already-matched case's caption into plaintiff/defendant fields -- that
fix never touched whether the underlying match was correct in the first
place.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

import structlog

from .divorce_caption import split_divorce_caption
from .name_normalize import first_last_parts, is_entity, party_middle_verdict

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

# All 46 SC counties -> FCCMS LOCATION codeID. The first 8 (Spartanburg 1046,
# Anderson 1008, Pickens 1043, Oconee 1041, Cherokee 1015, Union 1048, Laurens 1034,
# Greenville 1027) were live-pulled 2026-06-30 and re-checked 2026-10-02. The other
# 38 were added 2026-10-07 (distressed leads are statewide, owner's rule) from the
# same Validationcode LOCATION list, re-pulled live that day: 46 entries, codeIDs
# 1005-1050 in alphabetical order, no CAPTCHA, challenge or login on the portal.
# Per-run cap, refresh windows, budget and worker count are unchanged.
_COUNTY_CODE = {
    "Abbeville": 1005, "Aiken": 1006, "Allendale": 1007, "Anderson": 1008,
    "Bamberg": 1009, "Barnwell": 1010, "Beaufort": 1011, "Berkeley": 1012,
    "Calhoun": 1013, "Charleston": 1014, "Cherokee": 1015, "Chester": 1016,
    "Chesterfield": 1017, "Clarendon": 1018, "Colleton": 1019, "Darlington": 1020,
    "Dillon": 1021, "Dorchester": 1022, "Edgefield": 1023, "Fairfield": 1024,
    "Florence": 1025, "Georgetown": 1026, "Greenville": 1027, "Greenwood": 1028,
    "Hampton": 1029, "Horry": 1030, "Jasper": 1031, "Kershaw": 1032,
    "Lancaster": 1033, "Laurens": 1034, "Lee": 1035, "Lexington": 1036,
    "Marion": 1037, "Marlboro": 1038, "McCormick": 1039, "Newberry": 1040,
    "Oconee": 1041, "Orangeburg": 1042, "Pickens": 1043, "Richland": 1044,
    "Saluda": 1045, "Spartanburg": 1046, "Sumter": 1047, "Union": 1048,
    "Williamsburg": 1049, "York": 1050,
}
_COUNTY_CODE_BY_KEY = {k.lower(): v for k, v in _COUNTY_CODE.items()}


def _county_code(county) -> int | None:
    """The FCCMS LOCATION codeID for a board county ("McCormick", "Mccormick",
    "York County" all resolve), or None outside SC's 46 counties."""
    c = (county or "").strip()
    if c.lower().endswith(" county"):
        c = c[:-7].strip()
    return _COUNTY_CODE_BY_KEY.get(c.lower())


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
# 45s, not 20s: in the portal's slow mode (2026-09-19) a call takes ~10s and a
# call queued behind the portal's parallel limit takes ~21s (see _CONCURRENCY).
# At 20s the queued call timed out; the run logged 84 errors, every one a Timeout.
_CALL_TIMEOUT_S = float(os.environ.get("FORECLOSURE_SC_DIVORCE_CALL_TIMEOUT_S", "45"))
# Wall-clock cap on the whole run so a throttled/hanging FCCMS can't drag it on for hours
# (it hung ~6h once on a 1,677-lead bulk pass). Unreached leads retry next run via the refresh window.
_BUDGET_S = float(os.environ.get("FORECLOSURE_SC_DIVORCE_BUDGET_S", "1800"))
_PER_QUERY_CAP = 25  # max case rows kept per lead
# Real-surname searches measured 2-7s each even at 0 rows (2026-09-18), so one
# sequential worker did ~6-13 leads/min. 4 workers keeps at most 4 requests in
# flight against a public court index (a browser opens 6 per host) and the
# consecutive-failure abort below still stops the run if the portal pushes back.
#
# 3 workers, not 4 (measured 2026-09-19, 18 uncached searches): one call alone
# takes ~9.7s flat; with 4 in flight three finish together at ~11s and the
# fourth waits a full cycle and finishes at 16-22s. The portal serves about 3
# in parallel, so a 4th worker adds latency, not throughput, and its calls
# tripped the old 20s timeout (a quarter of all calls) until the 12-failure
# guard stopped the run. 3 matches what the portal actually serves.
_CONCURRENCY = int(os.environ.get("FORECLOSURE_SC_DIVORCE_CONCURRENCY", "3"))


# ---------- Owner-name handling (mirrors the ROD + nc_divorce enrichers) ------------

def _name_parts(owner: str) -> tuple[str, str]:
    """('SMITH, JOHN') -> ('SMITH','JOHN'); board 'LAST FIRST &' / 'A;B' fall back.

    Two name conventions live on this board, and reading one as the other
    searches a person who does not exist:
      * county-GIS / tax-roll owners are ALL-CAPS SURNAME-FIRST with no comma
        ('BYRD SANDRA D', 'SMITH JOHN C & MELINDA P') -- the board default;
      * court-party and probate-notice sources (sc_public_index,
        sc_probate_notices.*) are Title Case FIRST [MIDDLE] LAST
        ('Krystal  Henderson', 'Joshua D Smith', 'Susan Lee Meaders').
    Found 2026-09-18: ~5,000 of those leads were searched as last=KRYSTAL,
    first=HENDERSON, so their "no divorce" stamps were false negatives (0.3%
    hit rate vs 20-32% for tax rolls). Mixed case (any lowercase letter) is
    the reliable tell for the second convention; a comma always wins and
    means LAST, FIRST.
    """
    fl = first_last_parts(owner)
    if fl is not None:
        return fl
    raw = re.split(r"[;]|<br\s*/?>", owner or "", maxsplit=1)[0]
    o = re.sub(r"[^A-Za-z, ]", " ", raw).upper()
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


# A PublicPersonSearch row's ParticipantRole for the two actual divorcing
# spouses -- nobody else. Live-verified 2026-10-02 (see docs/HANDOFF.md,
# "SC divorce 0%-real accuracy fix"): every role actually returned by the
# portal across 7 counties x 3 categories is {Plaintiff, Defendant, Attorney,
# Mediator, Third Party Defendant, Guardian Ad Litem}; the board itself (5,052
# existing hits) additionally carries GAL-Children and Pro Hac Vice. Only
# Plaintiff/Defendant/Petitioner/Respondent are a PARTY to the marriage being
# dissolved (the last two reused from distress_score._DIVORCE_PARTY_ROLES,
# the project's own existing party-role vocabulary -- not newly invented
# here, and not actually observed live, but kept for the same case types that
# constant was already defensive about) -- an Attorney/Mediator/Guardian Ad
# Litem is a court OFFICER, never "this owner is getting divorced." The old
# code never filtered by role AT ALL when building raw['divorce']['cases'],
# and because `_owner_in_case`'s blob also includes the row's own PersonName
# (the person who matched the search query, by construction always
# containing `last`), the role-blind trim was a no-op for a non-party row:
# searching "DAVIS" returns "Davis, Davis, Joy C C" / role=Attorney for ~30
# UNRELATED divorce cases (Joy C. Davis is a practicing SC family-law
# attorney with many clients), none of whose captions contain "DAVIS" at all
# -- yet the old trim passed every one of them. Board-wide, 2,293 of 14,741
# existing case rows (15.6%) carry a non-party role; this is the dominant
# mechanism behind the 0% real-match rate a live population-scale check found
# 2026-10-01. distress_score._divorce_signal already skips a non-party role
# when picking the newest filing date for its SCORE WEIGHT, but that is the
# only place the old code ever consulted role -- raw['divorce']['case_count'],
# distress_stack.categories, and party_middle_verdict's own input all still
# saw the attorney-echo row, so anything reading the board directly (not
# through the scorer) still saw a "divorce" hit. Filtering at parse time, here,
# means a non-party row is never written to raw['divorce'] at all.
def _is_party_role(role) -> bool:
    """True only for a role that means "this person is a party to the case" --
    see the module-level comment above. A missing/blank role is kept
    (conservatively: the portal does not always populate it, and an
    unpopulated role is not evidence the row is NOT a party)."""
    if not role:
        return True
    from .distress_score import _DIVORCE_PARTY_ROLES
    return str(role).strip().lower() in _DIVORCE_PARTY_ROLES


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
        # Role filter FIRST, unconditionally -- a non-party row (Attorney,
        # Mediator, Guardian Ad Litem, ...) is never "this owner is getting
        # divorced" no matter how well the name matches; see _is_party_role's
        # module comment. Matters BEFORE the namesake trim below, not after:
        # the trim's blob includes PersonName, which by construction always
        # contains `last` (it is literally who matched the search query), so
        # a non-party row would otherwise sail through the trim every time.
        if not _is_party_role(r.get("ParticipantRole")):
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
        split = split_divorce_caption(parties)
        out.append({
            "case_number": case_no,
            "filed_date": filed,
            "parties": parties or None,
            # Structured spouse names split from `parties` (divorce_caption.py).
            # None when the caption carries no recognized separator — has not
            # happened live (every SC CaseDescription has one) but is possible
            # on a malformed/truncated row, so this is defensive, not a cap.
            "plaintiff": split["plaintiff"] if split else None,
            "defendant": split["defendant"] if split else None,
            "additional_parties": split["additional_parties"] if split else None,
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


# Ordering only, never a filter: every lead still gets searched if the budget
# allows. Measured 2026-09-18 on the board (SC core counties): person-sourced
# leads (delinquent-tax rolls, condemned/vacant lists, Pickens parcels) hit
# 13-26%; business-style sources hit ~0% (sc_dew_lien_registry 1 hit in 2,318
# checked). With ~12K leads still never-checked, the last two run rounds
# searched 64% then 80% company names and found 96 then 1 case.
_MIN_SOURCE_SAMPLE = 30
_UNSEEN_SOURCE_PRIOR = 0.10
_BUSINESS_NAME_FACTOR = 0.2


def _source_hit_rates(listings, now: datetime) -> dict[str, float]:
    """Observed divorce hit rate per lead source, from leads already searched
    in this same list. Sources with too few searched leads are omitted (their
    prior is unknown, not zero)."""
    seen: dict[str, int] = {}
    hits: dict[str, int] = {}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        dv = raw.get("divorce") if raw else None
        if not isinstance(dv, dict) or not dv.get("fetched_at"):
            continue
        src = li.source or ""
        seen[src] = seen.get(src, 0) + 1
        hits[src] = hits.get(src, 0) + (1 if dv.get("case_count") else 0)
    return {s: hits[s] / n for s, n in seen.items() if n >= _MIN_SOURCE_SAMPLE}


def _yield_prior(li, rates: dict[str, float]) -> float:
    """Expected chance this lead's owner has a divorce case: the source's
    observed hit rate when known, a neutral prior otherwise, discounted when
    the name reads as an entity."""
    prior = rates.get(li.source or "", _UNSEEN_SOURCE_PRIOR)
    if is_entity(li.owner_name or ""):
        prior *= _BUSINESS_NAME_FACTOR
    return prior


def _stale(li, now: datetime) -> bool:
    age = _divorce_age_days(li, now)
    window = _REFRESH_HOT_DAYS if _imminent(li, now) else _REFRESH_DAYS
    return age is None or age >= window


# ---------- Apply to a single lead -------------------------------------------------

def _apply(li, cases: list[dict], now: datetime) -> None:
    """Write raw['divorce'] + add 'divorce' to distress_stack.categories, GATED
    on party_middle_verdict() == 'agrees'.

    Fixed 2026-10-02: a live population-scale check against SC's own court
    index found 0% real matches at n=58/5,052 -- the full previously-flagged
    population. `cases` here is already role-filtered to real parties
    (_is_party_role, see its module comment) by the time it reaches this
    function, which fixes the dominant mechanism (an attorney/mediator echo).
    But a role-correct first+last name match on a common name is still
    frequently the WRONG same-named person (41% of comparable hits measured
    2026-09-21, name_normalize.party_middle_verdict's own origin). This
    project's established convention for exactly that problem -- requiring
    `party_middle_verdict(...) == "agrees"`, not merely "not a proven
    conflict" -- was computed here since 2026-09-21 but only ever stored as
    advisory metadata; 'unverified' (46% of hits, no middle initial on one
    side -- "nothing says the match is wrong OR right") passed straight
    through to distress_stack.categories uncorroborated. That gap, combined
    with the role bug above, is consistent with the observed 0% real rate.
    raw['divorce']['cases'] (role-filtered) and ['match'] are still written
    for EVERY case_count > 0 hit regardless of verdict -- this never goes
    silent — but only an 'agrees' verdict now reaches distress_stack.categories
    (and, symmetrically, distress_score._divorce_signal; see that function).
    """
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
        verdict = party_middle_verdict(li.owner_name, [c.get("parties") for c in cases])
        li.raw["divorce"]["match"] = verdict
        if verdict == "agrees":
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


class _IncompleteSearch(Exception):
    """A category call timed out, returned non-200, or returned unparseable /
    non-list JSON. The owner was NOT actually searched, so the lead must stay
    unstamped and be retried -- never recorded as "checked, no divorce"."""


async def _search_one(session, headers, last: str, first: str, county_code: int) -> list[dict]:
    """Search all divorce categories for one owner; return merged, deduped cases.

    Raises _IncompleteSearch if ANY category call failed. Before 2026-09-18 every
    failure `continue`d, so a timeout or 5xx read as "no cases" and the lead was
    stamped as checked (raw['divorce'] with case_count 0, refresh window 30 days)
    without ever being searched -- a silent false negative, and the reason the
    run's `errors` counter always read 0.
    """
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
        except Exception as exc:  # noqa: BLE001
            raise _IncompleteSearch(type(exc).__name__) from exc
        if r.status_code != 200:
            raise _IncompleteSearch(f"http_{r.status_code}")
        try:
            rows = r.json()
        except Exception as exc:  # noqa: BLE001
            raise _IncompleteSearch("bad_json") from exc
        if not isinstance(rows, list):
            raise _IncompleteSearch("non_list_payload")
        if not rows:
            continue  # a definitive empty answer: this category has no cases
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
    """For SC leads (all 46 counties since 2026-10-07) with an owner_name, find Family-Court
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
               and _county_code(li.county) is not None
               and li.owner_name
               and _stale(li, now)]
    # Never-fetched first, then stalest first — a cap-trimmed run still progresses.
    # Within the never-fetched group, most-likely-a-person first (see
    # _yield_prior): a company cannot be a divorce party, and the pool that is
    # left after the person-sourced leads are done is mostly companies.
    rates = _source_hit_rates(listings, now)

    def _order(li):
        age = _divorce_age_days(li, now)
        if age is not None:
            return (True, -age)
        return (False, -_yield_prior(li, rates))

    targets.sort(key=_order)
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
        it = iter(targets)

        async def _worker() -> None:
            nonlocal consec_err
            while True:
                if _time.monotonic() - _t0 > _BUDGET_S:
                    stats["budget_exhausted"] = True
                    return
                if consec_err >= 12:
                    stats["aborted_throttled"] = True  # FCCMS is failing every call -> stop, retry later
                    return
                li = next(it, None)   # single event-loop thread: no race on the shared iterator
                if li is None:
                    return
                last, first = _name_parts(li.owner_name)
                if not last:
                    continue
                county_code = _county_code(li.county)
                try:
                    cases = await _search_one(s, headers, last, first, county_code)
                    consec_err = 0
                except Exception as exc:  # noqa: BLE001  (incl. _IncompleteSearch)
                    stats["errors"] += 1
                    consec_err += 1
                    # Tally WHY, so a run's log says whether the portal is throttling
                    # (http_429/http_503) or our own timeout is too tight for its
                    # current latency (TimeoutError). Before this, both looked alike.
                    kind = str(exc) if isinstance(exc, _IncompleteSearch) else type(exc).__name__
                    kinds = stats.setdefault("error_kinds", {})
                    kinds[kind] = kinds.get(kind, 0) + 1
                    continue  # leave unstamped -> retried next run
                stats["searched"] += 1
                _apply(li, cases, now)
                if cases:
                    stats["with_divorce"] += 1
                    stats["cases_found"] += len(cases)
                await asyncio.sleep(0.2)

        await asyncio.gather(*[_worker() for _ in range(max(1, _CONCURRENCY))])

    log.info("sc_divorce.enrich.done", **stats)
    return stats
