"""Spartanburg County SC — Tyler EnerGov self-service Code Case + Permit records,
read off the county's own citizen-facing permitting/code-enforcement search API.

STATUS AS OF 2026-11-19: BACKEND CONFIRMED DOWN, NOT A WALL
    POST .../apps/selfservice/api/energov/search/search answers an unconditional
    HTTP 500 {"Message":"An error has occurred."} on EVERY request, regardless of
    body content (verification pass, 12/12 attempts across curl + httpx/HTTP1.1/
    HTTP2, including the server's OWN authoritative default template; independently
    RE-CONFIRMED live at build time, same signature, same URL). This is a textbook
    ASP.NET Web API unhandled-exception response in production error mode -- not a
    CAPTCHA, not a WAF, not an auth requirement, not a rate limit (robots.txt is a
    bare 404; ~14 requests over ~10 min drew no throttling or escalation). The
    sibling GET .../search/criteria endpoint is fully healthy (200, real JSON) and
    POST to the same URL with the wrong verb answers a clean, specific 405 -- so
    routing and model binding both work fine; only the search ACTION itself throws,
    most likely a broken backing index/Elasticsearch dependency for this tenant.
    Same family of failure this codebase already has two precedents for treating
    exactly this way -- build the client, don't fabricate data against it:
      * counties_nc/iredell_delinquent_tax.py: "Iredell['s] ... PTS tenant answers
        HTTP 500" -- scraped nothing until an alternate GIS source was found.
      * counties_nc/nc_its_public_tax.py _TENANT_NOTES: several ITS tenants
        documented as "answers HTTP 500" and excluded, not guessed around.
    base_scraper.py's own safe_run() already classifies any 5xx raised via
    raise_for_status() as OUTCOME_BLOCKED (not a silent OUTCOME_ZERO) -- this module
    leans on that existing machinery rather than inventing its own, so a run against
    the still-down backend reports "blocked" honestly instead of looking like a
    clean empty county.

    THIS MODULE IS THEREFORE SHIPPED CODE-COMPLETE BUT LIVE-UNVALIDATED. The request
    shape is 100% confirmed (built straight off the live `criteria` endpoint's own
    SearchCriteriaModel field names). The RESPONSE/row shape below is NOT -- the
    search action has never once returned real data to confirm field names against.
    `_to_listing_code_case`/`_to_listing_permit` read several plausible candidate
    field names (seen as Angular grid-column bindings in the self-service bundle,
    energov_bundle.js) per value rather than committing to one that turns out wrong;
    re-validate against a real response the first time this comes back 200 with
    rows, and tighten `_first(...)`'s candidate lists down to whatever actually
    shows up. Do not assume the EMISSION MODEL below (parcel merge, stalled-permit
    read) is correct until that happens.

SOURCE
    https://spartanburgcountysc-energovweb.tylerhost.net/apps/selfservice/api/energov/search/search
    (POST, JSON). The self-service portal's Angular app calls this one endpoint for
    every record type (Plan/Permit/Inspection/CodeCase/Request/License); which
    type(s) a call targets is picked with `SearchModule`/`FilterModule`. The exact
    int->module enum mapping could not be read cleanly out of the minified bundle
    and (see above) has never been confirmed against a live success. `_MODULE_CODE_CASE`
    = 5 and `_MODULE_PERMIT` = 2 are the values the verification pass's own narrowed,
    single-module reproduction attempts used (CodeCaseCriteria.ParcelNumber and
    PermitCriteria.Address respectively) -- the most evidence-grounded guess
    available, not independently proven. Re-verify once the backend answers for real.

WHY NOT counties_sc/spartanburg_condemned.py
    That module's whole "dead end" finding was about a DIFFERENT access surface --
    the county's own ArcGIS `Condemned_Properties` MapServer, a live-but-empty GIS
    shell with 0 queryable layers. This EnerGov self-service search API is a
    different system entirely (Tyler EnerGov, not the county's ArcGIS server) that
    the condemned module's dead-end reasoning never touched or ruled out; it just
    hadn't been found yet. spartanburg_condemned.py's own docstring now cross-
    references this module so the two "dead end" findings aren't conflated.

EMISSION MODEL (per the parcel-keyed backbone, same house style as
spartanburg_condemned.py's own EMISSION MODEL section)
    Code Case rows -> raw['code_enforcement'] (code_enforcement_open() / distress_
    score's w=14 PROPERTY hook, same as every other code-enforcement source). The
    search result has never been observed to carry a confirmed open/closed status
    enum, so -- same principle code_enforcement_open() itself documents ("a shape
    that says nothing about status is kept, because dropping a real case on a field
    the source never wrote is the worse error") -- no `has_open` key is invented.
    Instead a case with an opened date and no closed date ages out via `stale_after`
    = opened + 365 days, identical to charleston_energov_history.py's own documented
    convention for the same missing-status situation.

    Permit rows -> raw['permit_activity'] (NEW context key, NOT wired into
    distress_score.py in this pass -- see FOLLOW-UPS). A permit issued, never
    finaled, and either expired or >365 days old is flagged `stalled: true` -- the
    classic abandoned-renovation motivated-seller pattern (the fork session's Boca
    Raton lead that prompted this build: a renovation that died mid-stream, trailer
    and porta-potty still on site). charleston_energov_history.py's own precedent
    deliberately does NOT treat an ordinary demolition permit as condemned ("a
    demolition permit is an owner's or buyer's application, not a condemnation");
    this module follows the same restraint and does not set raw['condemned'] from a
    permit alone.

    Government/utility owners are dropped (not sellers), same regex family as
    spartanburg_condemned.py. Dateless standing inventory -> main.DATELESS_OK_SOURCES.

    OPEN QUESTION, do not assume: spartanburg_condemned.py's own parcel keys
    (GISParcelNumber, e.g. "6189-56-5809.33") are confirmed to normalize onto the
    same dedupe_key() as the county's compact 12-digit PIN. This module's
    ParcelNumber values (e.g. "7-21-12-027.00", the verification pass's own test
    parcel) have NOT been cross-checked against that same normalized space -- they
    may be the same TMS numbering under different punctuation, or a different
    numbering entirely. Confirm this the first time real rows land before assuming
    a Code Case / Permit row merges cleanly onto an existing CAMA-sourced lead
    instead of standing alone.

SCOPE -- COUNTY TENANT ONLY, CITY COVERAGE UNVERIFIED
    This is the COUNTY's EnerGov tenant. Spartanburg CITY runs its own, entirely
    separate condemnation/code docket (see counties_sc/spartanburg_city_condemned.py
    -- a different PDF source, a different parcel-key namespace; the codebase
    already treats City and County as non-overlapping jurisdictions for this
    exact signal family). Whether this county tenant's data is itself restricted to
    unincorporated county territory, or also covers incorporated small towns
    (Wellford/Woodruff/Chesnee/Duncan/Lyman/etc. -- NOT the same as Spartanburg
    City), could not be tested live (the endpoint returns no data for anything).
    Treat "unincorporated + small-town-adjacent, excluding Spartanburg City proper"
    as the working assumption, not a confirmed boundary, and recheck once real rows
    exist.

FOLLOW-UPS (not built in this pass -- see task scope note: ship Spartanburg clean
first, don't speculative-build multi-county on an unconfirmed naming pattern)
    * Generalizing to other Tyler EnerGov counties: the exact subdomain pattern
      (`spartanburgcountysc-energovweb.tylerhost.net`) does NOT appear to be a
      simple per-county template -- DNS probes for the obvious guess
      (`<county>countysc-energovweb.tylerhost.net`) failed to resolve for
      Charleston, Greenville, York, Richland and Horry, and Charleston's own real
      self-service portal lives at a totally different, county-owned domain
      (egovweb.charlestoncounty.org). Resolving this needs a per-county discovery
      pass (web search or asking Tyler/the counties), not a naming guess.
    * raw['permit_activity']['stalled'] is not yet scored in distress_score.py.
      Wiring a new weighted signal is a scoring-policy decision outside this
      module's scope (and can't be validated against real data yet anyway); it
      rides as raw context for now, same as spartanburg_condemned.py's own
      `cama_specs` block rides unscored for downstream skip-trace/ARV reuse.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import httpx
import structlog
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SEARCH_URL = ("https://spartanburgcountysc-energovweb.tylerhost.net/"
              "apps/selfservice/api/energov/search/search")

# SearchModule/FilterModule values -- see module docstring's SOURCE section for
# exactly how evidence-grounded (vs. confirmed) these are.
_MODULE_CODE_CASE = 5
_MODULE_PERMIT = 2

_PAGE_SIZE = 50
_MAX_PAGES = 200           # hard safety ceiling -- never loop unbounded on an unconfirmed stop condition

# Standing-condition signal (same DATELESS philosophy as spartanburg_condemned.py):
# pull a wide multi-year history rather than guessing a narrow recent window.
_HISTORY_YEARS = 10

_GOV = re.compile(
    r"\b(CITY OF|COUNTY OF|STATE OF|SPARTANBURG COUNTY|HOUSING AUTHORITY|"
    r"REDEVELOPMENT|SCHOOL DISTRICT|UNITED STATES|SECRETARY OF|DEPARTMENT OF|"
    r"COMMISSIONERS OF PUBLIC WORKS|SC DEPARTMENT|MUNICIPAL)\b", re.I)


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _first(d: dict, *keys: str) -> Any:
    """First non-empty value among several CANDIDATE field names. The real
    search-result row shape has never been observed live (module docstring) --
    several plausible names (grid-column bindings seen in the self-service
    Angular bundle) are tried rather than committing to one that turns out wrong."""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", " "):
            return v
    return None


def _parse_date(v: Any) -> date | None:
    if not v:
        return None
    s = str(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m2 = re.search(r"/Date\((\d+)", s)   # ASP.NET JSON date form, in case the backend uses it
    if m2:
        try:
            return datetime.utcfromtimestamp(int(m2.group(1)) / 1000).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _unwrap_rows(body: dict) -> list[dict]:
    """The confirmed-live /search/criteria endpoint wraps its payload in
    {"Result": {...}, "Success":..., "StatusCode":..., ...} -- this EnerGov
    install's uniform API envelope. /search/search has never answered with real
    data to confirm it follows the same shape, so that envelope is tried first and
    a few other plausible shapes are tried after, rather than assuming one blindly."""
    if not isinstance(body, dict):
        return []
    result = body.get("Result")
    if isinstance(result, dict):
        for key in ("Results", "Rows", "Items", "Data", "Records"):
            rows = result.get(key)
            if isinstance(rows, list):
                return rows
    if isinstance(result, list):
        return result
    for key in ("Results", "Rows", "Items", "Data", "Records"):
        rows = body.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _owner_mailing(row: dict) -> str | None:
    parts = [_first(row, "ContactAddress", "MailingAddress"),
             _first(row, "ContactCity", "MailingCity"),
             _first(row, "ContactState", "MailingState"),
             _first(row, "ContactZip", "MailingZip")]
    out = " ".join(str(p).strip() for p in parts if p not in (None, "", " "))
    return re.sub(r"\s+", " ", out).strip() or None


class SpartanburgEnergovSelfservice(BaseScraper):
    slug = "counties_sc.spartanburg_energov_selfservice"
    name = "Spartanburg County EnerGov Self-Service Code Cases + Permits"
    category = "motivated_seller"
    # Backend confirmed down (see module docstring) -- 0 is a legitimate, expected
    # outcome until Tyler's tenant heals, so a strict min-count would just manufacture
    # a false "regression" alarm every run. Raise this once the source has proven it
    # can return real rows.
    expected_min_count = 0
    timeout_s = 240.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_keys: set[str] = set()
        since = (date.today() - timedelta(days=365 * _HISTORY_YEARS)).isoformat()

        async with client(timeout=45.0) as c:
            for module, kind in ((_MODULE_CODE_CASE, "code_case"), (_MODULE_PERMIT, "permit")):
                page = 1
                while page <= _MAX_PAGES:
                    payload = self._body(module, kind, page, since)
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential_jitter(initial=1, max=8),
                        retry=retry_if_exception_type(
                            (httpx.TransportError, httpx.TimeoutException, TimeoutError)),
                        reraise=True,
                    ):
                        with attempt:
                            r = await c.post(SEARCH_URL, json=payload)
                    # A bad HTTP status (including the confirmed 500 backend outage)
                    # is not a transient blip, so it is raised UNRETRIED here -- same
                    # convention spartanburg_condemned.py and most SC siblings use.
                    # safe_run() (base_scraper.py) already classifies any 401/403/
                    # 406/429/5xx raised this way as OUTCOME_BLOCKED (with a reason
                    # naming the status), so this module doesn't need to invent its
                    # own "is the backend down" detection on top of that.
                    r.raise_for_status()
                    parsed = r.json() or {}
                    rows = _unwrap_rows(parsed)
                    if not rows:
                        break
                    for row in rows:
                        li = (self._to_listing_code_case(row) if kind == "code_case"
                              else self._to_listing_permit(row))
                        if li is None:
                            continue
                        key = li.parcel_id or (li.street_address or "")
                        if not key or key in seen_keys:
                            continue
                        seen_keys.add(key)
                        out.append(li)
                        self.partial.append(li)   # survive a soft-timeout mid-run with what we have
                    if len(rows) < _PAGE_SIZE:
                        break
                    page += 1

        log.info("spartanburg_energov.parsed", listings=len(out))
        return out

    # -- request body (CONFIRMED shape -- built straight off the live `criteria`
    # endpoint's own SearchCriteriaModel field names) --------------------------
    def _body(self, module: int, kind: str, page: int, since_iso: str) -> dict:
        base: dict[str, Any] = {
            "Keyword": "", "ExactMatch": False, "SearchModule": module,
            "FilterModule": module, "SearchMainAddress": False,
            "PlanCriteria": {"PageNumber": 0, "PageSize": 0},
            "PermitCriteria": {"PageNumber": 0, "PageSize": 0},
            "InspectionCriteria": {"PageNumber": 0, "PageSize": 0},
            "CodeCaseCriteria": {"PageNumber": 0, "PageSize": 0},
            "RequestCriteria": {"PageNumber": 0, "PageSize": 0},
            "BusinessLicenseCriteria": {}, "ProfessionalLicenseCriteria": {},
            "LicenseCriteria": {}, "ProjectCriteria": {},
            "ExcludeCases": None, "HiddenInspectionTypeIDs": None,
            "PageNumber": page, "PageSize": _PAGE_SIZE,
            "SortBy": None, "SortAscending": False,
        }
        if kind == "code_case":
            base["CodeCaseCriteria"] = {
                "OpenedDateFrom": since_iso, "PageNumber": page, "PageSize": _PAGE_SIZE,
            }
        else:
            base["PermitCriteria"] = {
                "IssueDateFrom": since_iso, "PageNumber": page, "PageSize": _PAGE_SIZE,
            }
        return base

    # -- response parsing (UNCONFIRMED field names -- see module docstring) ----
    def _to_listing_code_case(self, row: dict) -> Listing | None:
        owner = _clean(_first(row, "OwnerName", "ContactName", "Owner"))
        address = _clean(_first(row, "MainAddress", "Address", "FullAddress", "SiteAddress"))
        parcel = _clean(_first(row, "ParcelNumber", "ParcelNo", "Parcel"))
        if not (address or parcel):
            return None
        if owner and _GOV.search(owner):
            return None

        case_no = _clean(_first(row, "CaseNumber", "CodeCaseNumber"))
        opened = _parse_date(_first(row, "OpenedDate", "EnteredDate"))
        closed = _parse_date(_first(row, "ClosedDate"))
        case_type = _clean(_first(row, "CaseType", "RecordType", "Module"))
        status = _clean(_first(row, "StatusName", "RequestStatus", "Status"))

        ce: dict[str, Any] = {
            "source": "spartanburg_energov_code_case",
            "case_number": case_no,
            "case_type": case_type,
            "status_text": status,   # raw text only -- no confirmed open/closed enum to key off
            "opened_date": opened.isoformat() if opened else None,
            "closed_date": closed.isoformat() if closed else None,
        }
        if closed is None and opened is not None:
            # charleston_energov_history.py's own convention for the same missing-
            # status situation: age the case out 365 days after it opened instead
            # of asserting it open forever.
            ce["stale_after"] = (opened + timedelta(days=365)).isoformat()
        ce = {k: v for k, v in ce.items() if v is not None}

        desc = f"Spartanburg EnerGov code case {case_no or '(no case #)'} ({case_type or 'unspecified type'})"

        raw = {k: v for k, v in {
            "code_enforcement": ce or True,
            "distressed": True,
            "owner_mailing": _owner_mailing(row),
        }.items() if v not in (None, {}, [])}

        return Listing(
            source=self.slug, source_url=SEARCH_URL,
            listing_type=ListingType.UNKNOWN, property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Spartanburg",
            street_address=address, parcel_id=parcel,
            defendant=owner, owner_name=owner, description=desc,
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )

    def _to_listing_permit(self, row: dict) -> Listing | None:
        owner = _clean(_first(row, "OwnerName", "ContactName", "Owner"))
        address = _clean(_first(row, "MainAddress", "Address", "FullAddress", "SiteAddress"))
        parcel = _clean(_first(row, "ParcelNumber", "ParcelNo", "Parcel"))
        if not (address or parcel):
            return None
        if owner and _GOV.search(owner):
            return None

        permit_no = _clean(_first(row, "PermitNumber"))
        issued = _parse_date(_first(row, "IssueDate", "IssuedDate"))
        finaled = _parse_date(_first(row, "FinalDate", "FinalizedDate"))
        expired = _parse_date(_first(row, "ExpireDate"))
        permit_type = _clean(_first(row, "PermitType", "WorkClass"))
        status = _clean(_first(row, "StatusName", "PermitStatus", "Status"))

        stalled = bool(
            issued is not None and finaled is None
            and (expired is not None or (date.today() - issued).days > 365)
        )

        activity: dict[str, Any] = {
            "source": "spartanburg_energov_permit",
            "permit_number": permit_no,
            "permit_type": permit_type,
            "status_text": status,
            "issue_date": issued.isoformat() if issued else None,
            "final_date": finaled.isoformat() if finaled else None,
            "expire_date": expired.isoformat() if expired else None,
            "stalled": stalled,
        }
        activity = {k: v for k, v in activity.items() if v is not None}

        desc = f"Spartanburg EnerGov permit {permit_no or '(no permit #)'} ({permit_type or 'unspecified type'})"

        raw = {k: v for k, v in {
            "permit_activity": activity or None,
            "owner_mailing": _owner_mailing(row),
        }.items() if v not in (None, {}, [])}

        return Listing(
            source=self.slug, source_url=SEARCH_URL,
            listing_type=ListingType.UNKNOWN, property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Spartanburg",
            street_address=address, parcel_id=parcel,
            defendant=owner, owner_name=owner, description=desc,
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = SpartanburgEnergovSelfservice()
        rows = await s.safe_run()
        code_cases = sum(1 for x in rows if (x.raw or {}).get("code_enforcement"))
        permits = sum(1 for x in rows if (x.raw or {}).get("permit_activity"))
        print(f"outcome={s.last_outcome} reason={s.last_reason!r} "
              f"count={len(rows)} code_cases={code_cases} permits={permits}")

    asyncio.run(_main())
