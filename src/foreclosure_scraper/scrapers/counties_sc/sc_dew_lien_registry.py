"""SC DEW Lien Registry — UI Tax Lien + Benefit Lien (one WCF service, two lien types).

The SC Dept of Employment & Workforce publishes ALL of its filed liens in a
single public, name-searchable, login-free registry. Two public front doors:

  (a) UI Tax Lien Registry — https://uitax.dew.sc.gov/LienRegistry/  (Angular 13
      SPA, hash route #/registry). Employer unemployment-INSURANCE-tax liens.
  (b) Benefit Lien Registry — https://dew.sc.gov/benefit-lien-registry (a Drupal
      info page). Benefit-OVERPAYMENT liens against claimants.

Per the DEW Benefit Lien FAQ ("all liens held by SCDEW are listed on the Lien
Registry"), BOTH lien types live in the SAME store and are served by the same
WCF endpoint the SPA calls:

  POST https://uitax.dew.sc.gov/CoreServices/Lien/TaxLienRegistry.svc/SearchTaxLienRegistry
  Header: SecurityKey: <static key shipped in the SPA bundle>
  Body (JSON): {BusinessName, EmployerFEIN, EmployerAccountId, FirstName,
                LastName, IssuedFrom, IssuedTo, LienID}   -> name/ID search
           or  {IPAddress, Export_All_Ind:"Y"}            -> dump full active set

  Response (JSON array of):
    {LienID, TaxpayerName, DBAName, EmployerAddress, EmployerAccountId,
     EmployerFEIN, LienType, LienStatus, StatusDescription, LeinAmount,
     BalanceAmount, LienDateFiled, LienDateStatisfied, LienIssued, ...}

The SearchTaxLienRegistry call is what the SPA itself fires, so we drive it the
compliant way: StealthyFetcher renders the real SPA, then we invoke the same
fetch() from the page's own origin (same SecurityKey, same headers). No CAPTCHA
is involved — reCAPTCHA in the bundle gates ONLY the by-SSN search path, never
name / business / LienID / export search.

Strategy: try Export_All_Ind="Y" first (one call, the active registry as of the
1st of the month). The DEW backend (a net.tcp WCF service) intermittently times
out on the big export; if it does, fall back to a bounded sweep of common-surname
searches so a run still returns rows. Each row becomes an address-less,
debtor-name-keyed Listing (LienType -> tax vs benefit) feeding the lien-stack +
name->property enrichers. When EmployerAddress carries an SC county/city we keep
it for footprint scoping; otherwise the row is retained statewide for name
cross-reference.

IMPORTANT — live behavior verified 2026-06-26: the service does NOT filter a
name search to a substring; a bare LastName returns the ENTIRE registry
(active + released, ~190MB). So the in-page fetch (a) reads the body in capped
streaming chunks and aborts past a byte ceiling, and (b) keeps only ACTIVE
liens (drops RLSD / "Released") on the fallback path — active unpaid liens are
the distress signal; satisfied ones are noise. Export_All_Ind already returns
active-only.

Statewide SC. Dateless. Free, no login, no bot-detection bypass.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...config import in_scope
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

REGISTRY_URL = "https://uitax.dew.sc.gov/LienRegistry/"
SVC_URL = (
    "https://uitax.dew.sc.gov/CoreServices/Lien/"
    "TaxLienRegistry.svc/SearchTaxLienRegistry"
)
# Static SecurityKey shipped in the public SPA bundle (main.*.js). Public,
# non-secret — every browser hitting the registry sends it. Not a credential.
SECURITY_KEY = "LbBr3hPJ2qw9mHvmE+Px7gI8HiDaU+F3fWx68Z39YBw="
SOURCE_URL = "https://dew.sc.gov/benefit-lien-registry"

# Empty search model the SPA posts; we override individual fields per query.
_EMPTY_MODEL = {
    "BusinessName": "", "EmployerFEIN": "", "EmployerAccountId": "",
    "FirstName": "", "LastName": "", "IssuedFrom": "", "IssuedTo": "",
    "LienID": "",
}

# Surname sweep used ONLY if the full export times out. A bare LastName returns
# the whole registry, so ONE surname is enough to seed active rows; we keep a
# couple as retries against the flaky backend. Bounded hard by _MAX_BYTES.
_FALLBACK_SURNAMES = ("SMITH", "JOHNSON")

# Byte ceiling for any single response read in-page. A bare name search can
# stream ~190MB (whole registry); we abort well before that and parse only what
# arrived, which still yields thousands of rows.
_MAX_BYTES = 12_000_000

# Build the in-page fetch JS once. Reads the body in capped streaming chunks so
# a 190MB name-search response can't blow up the browser/Python bridge; returns
# {status, len, truncated, text} or {err}.
_FETCH_JS = """async (payload) => {
    try {
        const r = await fetch(%s, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "SecurityKey": %s
            },
            body: JSON.stringify(payload)
        });
        const CAP = %d;
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "", total = 0, truncated = false;
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            total += value.length;
            buf += dec.decode(value, {stream: true});
            if (total > CAP) { truncated = true; try { await reader.cancel(); } catch (e) {} break; }
        }
        return {status: r.status, len: total, truncated: truncated, text: buf};
    } catch (e) {
        return {err: String(e)};
    }
}""" % (json.dumps(SVC_URL), json.dumps(SECURITY_KEY), _MAX_BYTES)

# Trailing 'CITY, ST[ ]ZIP' — the export format is "STREET, CITY, SC29036" /
# "..., North Myrtle Beach, SC29582-1234" (no space before the zip). State and
# zip optional-spaced; state captured so out-of-SC debtors keep their real state.
_CITY_STATE_ZIP = re.compile(
    r",\s*([A-Za-z .'-]+?)\s*,?\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)?\s*$"
)
_COUNTY_RE = re.compile(r"\b([A-Za-z]+)\s+COUNTY\b", re.I)


def _benefit_lien(lien_type: str | None, status_desc: str | None) -> bool:
    """True when a row is a UI-BENEFIT (overpayment) lien rather than an
    employer unemployment-TAX lien. The registry mingles both; LienType /
    StatusDescription carry the distinction ('benefit' / 'overpayment')."""
    blob = f"{lien_type or ''} {status_desc or ''}".lower()
    return "benefit" in blob or "overpay" in blob or "claimant" in blob


def _money(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f else None


def _parse_date(v) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    s = v.strip()
    # WCF serializes /Date(ms)/, ISO, or "M/D/YYYY h:mm:ss AM". Handle all.
    m = re.search(r"/Date\((\d+)", s)
    if m:
        try:
            return datetime.utcfromtimestamp(int(m.group(1)) / 1000.0)
        except (ValueError, OverflowError):
            return None
    head = s.split()[0]  # date token before any time component
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(head if "T" not in fmt else s.rstrip("Z"), fmt)
        except ValueError:
            continue
    return None


def _county_for_city(city: str | None, state: str | None) -> str | None:
    """Resolve a city to its county via the shared SC city->county maps
    (upstate map is statewide-SC; coastal map adds beach towns)."""
    if not city:
        return None
    try:
        from ..._upstate_city_to_county import upstate_county_for
        from ..._coastal_city_to_county import coastal_county_for
    except ImportError:
        return None
    return upstate_county_for(city, state) or coastal_county_for(city, state)


def _split_address(
    addr: str | None,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Best-effort split of EmployerAddress -> (street, city, state, zip, county).

    Export rows are mailing strings like "103 BEAUFORT ST, CHAPIN, SC29036".
    We pull the trailing 'CITY, ST ZIP', keep the real state (so out-of-SC
    debtors aren't mislabeled SC), and resolve county from an explicit
    'X COUNTY' token or, failing that, the city via the shared maps. Purely to
    enable footprint scoping; nothing fabricated."""
    if not addr or not isinstance(addr, str):
        return None, None, None, None, None
    s = " ".join(addr.split())
    county = None
    mc = _COUNTY_RE.search(s)
    if mc:
        county = mc.group(1).title()
    city = state = zipc = None
    street = s
    mz = _CITY_STATE_ZIP.search(s)
    if mz:
        city = (mz.group(1) or "").strip().title() or None
        state = (mz.group(2) or "").strip().upper() or None
        zipc = (mz.group(3) or "").strip()[:5] or None
        street = s[: mz.start()].rstrip(" ,") or None
    if not county:
        county = _county_for_city(city, state)
    return street, city, state, zipc, county


def _to_listing(row: dict, slug: str) -> Listing | None:
    if not isinstance(row, dict):
        return None
    # A backend-error sentinel row carries ErrorMessage + all-null/zero fields.
    if row.get("ErrorMessage") and not (row.get("TaxpayerName") or row.get("DBAName")):
        return None
    name = (row.get("TaxpayerName") or row.get("DBAName") or "").strip()
    if not name:
        return None
    lien_id = row.get("LienID") or None
    lien_type = row.get("LienType")
    status = row.get("LienStatus") or row.get("StatusDescription")
    balance = _money(row.get("BalanceAmount"))
    lien_amt = _money(row.get("LeinAmount"))  # NB: backend misspells "Lein"
    filed = _parse_date(row.get("LienDateFiled"))

    street, city, addr_state, zipc, county = _split_address(row.get("EmployerAddress"))
    state = (addr_state or "SC").upper()
    # LienIssued is the filing COUNTY (e.g. "Greenville"), not a date — use it as
    # a county fallback only for SC debtors when the mailing address lacked one.
    issued = (row.get("LienIssued") or "").strip()
    if not county and issued and state == "SC" and not any(ch.isdigit() for ch in issued):
        county = issued.title()
    # We KEEP every row statewide (name cross-ref is the point); footprint is just
    # a flag. Only meaningful for SC; out-of-state debtors are not in footprint.
    in_footprint = in_scope(county, state) if (county and state == "SC") else False

    is_benefit = _benefit_lien(lien_type, status)
    kind_label = "benefit-overpayment" if is_benefit else "UI-tax"
    desc = f"SC DEW {kind_label} lien"
    if lien_id:
        desc += f" #{lien_id}"
    if status:
        desc += f" ({str(status).strip()})"
    if balance:
        desc += f" — balance ${balance:,.0f}"

    return Listing(
        source=slug,
        source_url=SOURCE_URL,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county,
        city=city,
        zip_code=zipc,
        street_address=street,
        defendant=name,
        judgment_amount=balance or lien_amt,
        foreclosure_process="lien",
        first_seen=filed or datetime.utcnow(),
        last_seen=datetime.utcnow(),
        description=desc,
        raw={
            # Mirror the SCDOR state-tax-lien shape so enrichment_lien_stack
            # can index this debtor's balance against matching property owners.
            "sc_state_tax_lien": {
                "owner": name,
                "balance": balance,
                "source": "sc_dew_lien_registry",
            },
            "sc_dew_lien_registry": {
                "lien_id": lien_id,
                "lien_type": lien_type,
                "lien_kind": kind_label,
                "is_benefit_lien": is_benefit,
                "status": status,
                "lien_amount": lien_amt,
                "balance": balance,
                "dba_name": (row.get("DBAName") or None),
                "employer_account_id": row.get("EmployerAccountId") or None,
                "employer_fein": row.get("EmployerFEIN") or None,
                "raw_address": row.get("EmployerAddress") or None,
                "date_filed": filed.isoformat() if filed else None,
                "in_footprint": in_footprint,
            },
        },
    )


def _decode_rows(text: str) -> list[dict]:
    """Parse the WCF JSON payload into a list of row dicts.

    Tolerant of a TRUNCATED body: a capped stream cuts mid-array, so a plain
    json.loads fails. We first try strict parse; on failure we scan out every
    complete top-level {...} object and parse each individually, discarding the
    final partial one. Returns [] only on genuine garbage."""
    if not text:
        return []
    s = text.strip()
    # Strict path (complete payload, possibly WCF-wrapped {d:[...]}).
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            for key in ("d", "SearchTaxLienRegistryResult", "Results", "results"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        if isinstance(data, list):
            return data
    except (ValueError, TypeError):
        pass
    # Tolerant path: extract balanced top-level objects from a truncated array.
    out: list[dict] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                frag = s[start:i + 1]
                try:
                    obj = json.loads(frag)
                    if isinstance(obj, dict):
                        out.append(obj)
                except (ValueError, TypeError):
                    pass
                start = -1
    return out


def _is_active(row: dict) -> bool:
    """True for an unpaid/active lien. Drops satisfied/released rows (RLSD,
    'Released', 'Satisfied') and rows carrying a satisfaction date — only live
    unpaid liens are a distress signal."""
    status = f"{row.get('LienStatus') or ''} {row.get('StatusDescription') or ''}".upper()
    if any(k in status for k in ("RLSD", "RELEAS", "SATISF", "PAID", "CANCEL", "EXPIRE")):
        return False
    if row.get("LienDateStatisfied"):
        return False
    return True


async def _run_queries(
    queries: list[dict], *, active_only: bool, max_rows: int,
) -> list[dict]:
    """Render the SPA once, then fire each search payload from the page origin.

    Returns deduped raw row dicts across all queries that returned a non-error
    array. Stops the export-all probe early once it succeeds, and stops the whole
    sweep once `max_rows` is reached. When `active_only`, satisfied/released
    liens are dropped (used on the fallback name sweep, which returns the whole
    registry incl. released rows; the export path is already active-only)."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("dew_lien.scrapling_missing")
        return []

    holder: dict = {"rows": [], "any_ok": False, "errors": []}

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        seen_ids: set = set()
        for payload in queries:
            try:
                res = await page.evaluate(_FETCH_JS, payload)
            except Exception as exc:  # noqa: BLE001
                holder["errors"].append(f"eval:{type(exc).__name__}")
                continue
            if not isinstance(res, dict) or res.get("err"):
                holder["errors"].append((res or {}).get("err", "no-result"))
                continue
            if res.get("status") != 200:
                holder["errors"].append(f"http:{res.get('status')}")
                continue
            if res.get("truncated"):
                holder["errors"].append(f"truncated@{res.get('len')}b")
            rows = _decode_rows(res.get("text") or "")
            # Drop the backend-timeout sentinel (single row, all null + ErrorMessage)
            real = [
                r for r in rows
                if isinstance(r, dict)
                and (r.get("TaxpayerName") or r.get("DBAName"))
            ]
            if active_only:
                real = [r for r in real if _is_active(r)]
            if real:
                holder["any_ok"] = True
                for r in real:
                    rid = r.get("LienID")
                    key = rid if rid else json.dumps(r, sort_keys=True)[:200]
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    holder["rows"].append(r)
                    if len(holder["rows"]) >= max_rows:
                        return page
                # If this was the full export and it worked, we're done.
                if payload.get("Export_All_Ind") == "Y":
                    break
            else:
                # Distinguish a clean empty (valid query, 0 matches) from the
                # backend-timeout sentinel so the report is honest.
                if any(r.get("ErrorMessage") for r in rows if isinstance(r, dict)):
                    holder["errors"].append("backend_timeout")
        return page

    try:
        await StealthyFetcher.async_fetch(
            REGISTRY_URL, headless=True, network_idle=True, timeout=600000,
            page_action=page_action, solve_cloudflare=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("dew_lien.render_failed", error=str(exc)[:160])
        return []
    if holder["errors"]:
        log.info("dew_lien.query_errors", errors=holder["errors"][:8])
    return holder["rows"]


class SCDEWLienRegistry(BaseScraper):
    slug = "counties_sc.sc_dew_lien_registry"
    name = "SC DEW Lien Registry (UI tax + benefit liens)"
    category = "state_lien"
    expected_min_count = 0   # backend net.tcp service intermittently times out
    requires_render = True
    requires_apify = False
    timeout_s = 600.0

    #: Hard cap on rows kept per run. The registry is ~190MB / hundreds of
    #: thousands of liens statewide; these are name cross-ref records, not
    #: property listings, so we keep a bounded slice rather than the whole set.
    max_rows = 8000

    async def fetch(self) -> Iterable[Listing]:
        # 1) Try the single full-registry export first (already active-only).
        queries: list[dict] = [{"IPAddress": "", "Export_All_Ind": "Y"}]
        rows = await _run_queries(queries, active_only=False, max_rows=self.max_rows)

        # 2) If the export timed out / returned nothing, sweep common surnames
        #    (which return the whole registry) keeping ACTIVE liens only.
        if not rows:
            fallback = [
                {**_EMPTY_MODEL, "LastName": sn} for sn in _FALLBACK_SURNAMES
            ]
            rows = await _run_queries(fallback, active_only=True, max_rows=self.max_rows)

        out: list[Listing] = []
        seen: set = set()
        for row in rows:
            li = _to_listing(row, self.slug)
            if li is None:
                continue
            key = (li.defendant or "", str(row.get("LienID") or ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(li)
        log.info("dew_lien.done", count=len(out), rows=len(rows))
        return out
