"""tax_lien, NC counties billed on Farragut's NC PTS Cloud (BillPWA): is there a real delinquent
property-tax balance on this parcel?

The second tax_lien adapter (the reference is tax_lien_buncombe; docs/HANDOFF.md item 66). Same
SIGNAL, same GOVERNS, same verdict meanings, so its verdicts land in the one tax_lien ledger.

SOURCE. bcpwa.ncptscloud.com, the county's own public tax-bill search (the same Farragut app the
counties_nc.nc_ptscloud_delinquent_tax roll downloads from). Plain JSON GETs, no login, no CAPTCHA,
the county chosen by an X-Tenant header (the SPA sends the URL's first path segment). Read from
the SPA bundle and live-verified 2026-10-06:

    GET /api/SimpleBillSearch?query=<parcel>&pageIndex=0&pageSize=100&billSubtypes=Real Property
        -> {totalCount, results: [{id, billNumber, taxYear, parcelId, billParentType, billType,
            billStatus (PAID/UNPAID/DEFERRED), originalBillAmount, amountDue, flags, owner...}]}
           every bill on the parcel, all years (the query also matches bill numbers and
           addresses, so results are kept only where parcelId equals the parcel asked for)
    GET /api/GetbillDetails?BillId=<id>
        -> {interestBeginDate, lastPaymentDate, interestPaid, transactions: [{transactionType,
            transactionCreationDate, ...}], ...}   one bill: was it paid after interest began?

A `tenant=` query parameter is appended to both (the API ignores it) so every URL names its
county: the capture/replay key and the evidence URL are unique per tenant.

TENANTS. Of the 17 X-Tenant values the roll scraper declares, the bill search answers for 8
(GetBillSearchFilters 200 and a real parcel found, 2026-10-06): Beaufort, Forsyth, Guilford,
Henderson, Hyde, Madison, Orange, Pitt. Burke, Cumberland, Durham, Hertford, Mecklenburg,
Randolph, Rutherford, Stokes and Wayne answer HTTP 500 there (IsValidTenant is false for
Rutherford and Burke; the others hold a download list but no bill search); they are not covered.

WHICH ROWS. NC rows (never Buncombe: tax_lien_buncombe owns those) whose tax claim this county's
record can answer (verifiers/_tax_common.py: a tax_lien/tax_sale listing type that is not a
federal/state/lien-agent lien, a delinquency flag, or the roll's own block), in a covered county,
or carrying the roll's block when the row IS the roll's row (source nc_ptscloud_delinquent_tax)
whatever county a geocoder later gave it (95 such rows sit in Catawba/Lincoln/Cleveland...).
A block merged into a row of another county from another source is not trusted.

WHICH PARCEL. The billing system keys bills by its own parcel number (Henderson/Hyde: the REID,
Guilford/Pitt/Beaufort: an account number, Forsyth/Orange: the PIN), not always the board's
parcel_id. Tried in order, until one returns bills for exactly that parcelId, at most 2 searches:
the roll block's PARCEL_NUM (parcel_raw, parcel), the land-records REID (raw.lrcpwa.reid, Henderson
/Madison/Hyde: the same number there), the board's parcel_id.

VERDICTS (a levy-year Y bill is delinquent once unpaid on January 6 of Y+1, G.S. 105-360; the
bill's own interestBeginDate decides "paid late"):
  confirmed    a Real Property bill of a delinquent-eligible year with an amount due today.
  stale        nothing delinquent today, and the claimed year (else the latest delinquent-eligible
               year) was paid on or after its interest-begin date, or interest was paid on it.
  refuted      nothing delinquent today and the bill(s) checked were paid before interest began.
  unconfirmed  no tenant / no parcel / not found / fetch or parse failure / tenant unhealthy this
               run / parcel billing ended before the latest eligible levy / only a deferred
               balance / bill details unreadable; or a refuted/stale answer on a row typed by
               another lien's source (other_lien_listing, see _tax_common).
Evidence (public ledger: a whitelist, no names, no mailing addresses): API and page URLs, tenant,
the tax parcel searched and where it came from, the board parcel, per-year delinquent amounts,
total, years, the not-yet-delinquent current levy, deferred amounts, the county's bill flags
(DLQ, FORECLOSURE, ADVERTISED, ...), claimed years and bill, bills checked (paid-on, interest
begin, interest paid), and the county owner vs board owner CATEGORY only.

FETCHING. One request at a time per host (the sweep's Fetcher paces it), every search and bill
cached for the run, a tenant that fails twice in a run (or answers a non-JSON page) is skipped
for the rest of the run (unconfirmed, never refuted).
"""
from __future__ import annotations

import json
import weakref
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote

from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "bcpwa.ncptscloud.com"
GOVERNS = ("tax_lien", "tax_sale", "tax_lien_chronic", "recorded_debt:tax")
ROW_SUMMARY_EXCLUDE = ("owner_name",)

BASE = "https://bcpwa.ncptscloud.com"
SEARCH_URL = (BASE + "/api/SimpleBillSearch?query={q}&pageIndex=0&pageSize=100&taxYears="
              "&billStatuses=&billSubtypes=Real%20Property&tenant={tenant}")
DETAIL_URL = BASE + "/api/GetbillDetails?BillId={bill_id}&tenant={tenant}"
PAGE_URL = BASE + "/{slug}/bill-search"
BILL_PAGE_URL = BASE + "/{slug}/bill-detail/{bill_id}"

#: X-Tenant values whose bill search answers (live-verified 2026-10-06; see TENANTS above)
BILL_TENANTS = ("Beaufort", "Forsyth", "Guilford", "Henderson", "Hyde", "Madison", "Orange", "Pitt")
_BY_COUNTY = {t.lower(): t for t in BILL_TENANTS}
#: land-records REID == the billing parcelId (Henderson 106725, Hyde 15796, live 2026-10-06)
LRC_REID_TENANTS = frozenset({"Henderson", "Madison", "Hyde"})
ROLL_SLUG = "counties_nc.nc_ptscloud_delinquent_tax"
ROLL_KEY = "nc_ptscloud_delinquent_tax"
MAX_SEARCHES = 2
MAX_BILL_CHECKS = 2
TENANT_MAX_FAILURES = 2
TIMEOUT_S = 30.0

_NAME = __name__.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# which rows, which tenant, which parcel (pure)
# ---------------------------------------------------------------------------

def roll_block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(ROLL_KEY)
    return b if isinstance(b, dict) else None


def tenant_of(row: Any) -> tuple[Optional[str], Optional[dict]]:
    """(X-Tenant, the roll block when it is this row's own claim) or (None, None)."""
    county = str(tc.g(row, "county") or "").strip().lower()
    blk = roll_block(row)
    if blk is not None:
        t = str(blk.get("tenant") or "").strip()
        if t in BILL_TENANTS and (t.lower() == county or tc.g(row, "source") == ROLL_SLUG):
            return t, blk
    t = _BY_COUNTY.get(county)
    return (t, None) if t else (None, None)


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    if str(row.get("county") or "").strip().lower() == "buncombe":
        return False                                   # tax_lien_buncombe's rows, never both
    tenant, blk = tenant_of(row)
    return tenant is not None and tc.claims_property_tax(row, blk is not None)


def parcel_candidates(row: Any, tenant: str, blk: Optional[dict]) -> list[tuple[str, str]]:
    """[(parcel, where it came from)], best first, distinct, placeholders dropped."""
    out: list[tuple[str, str]] = []
    if blk:
        for k in ("parcel_raw", "parcel"):
            out.append((str(blk.get(k) or "").strip(), "roll_block"))
    lrc = tc.raw_of(row).get("lrcpwa")
    if tenant in LRC_REID_TENANTS and isinstance(lrc, dict) and \
            str(tc.g(row, "county") or "").strip().lower() == tenant.lower():
        out.append((str(lrc.get("reid") or "").strip(), "lrcpwa_reid"))
    out.append((str(tc.g(row, "parcel_id") or "").strip(), "board_parcel"))
    seen, keep = set(), []
    for p, src in out:
        k = tc.alnum(p)
        if not k or set(k) <= {"0"} or k in seen:
            continue
        seen.add(k)
        keep.append((p, src))
    return keep


def claimed_years(row: Any, blk: Optional[dict]) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    if blk:
        years.add(tc.to_int(blk.get("tax_year")))
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# the rules (pure)
# ---------------------------------------------------------------------------

def delinquent_from(year: int) -> date:
    """First day a levy-year bill is delinquent: January 6 of the next year (G.S. 105-360)."""
    return date(year + 1, 1, 6)


def is_eligible(year: int, today: date) -> bool:
    return today >= delinquent_from(year)


def latest_eligible(today: date) -> int:
    return today.year - 1 if is_eligible(today.year - 1, today) else today.year - 2


def bills_of(payload: Any, parcel: str) -> list[dict]:
    """The Real Property bills of exactly this parcel from a SimpleBillSearch answer."""
    res = payload.get("results") if isinstance(payload, dict) else None
    want = tc.alnum(parcel)
    out = []
    for r in res or []:
        if not isinstance(r, dict) or tc.alnum(r.get("parcelId")) != want:
            continue
        if not str(r.get("billParentType") or "").lower().startswith("real"):
            continue
        y = tc.to_int(r.get("taxYear"))
        if not 1900 < y < 2100:
            continue
        due = r.get("amountDue")
        out.append({"id": str(r.get("id") or ""), "bill": r.get("billNumber"), "year": y,
                    "status": str(r.get("billStatus") or "").upper(),
                    "due": round(float(due), 2) if isinstance(due, (int, float)) else 0.0,
                    "original": r.get("originalBillAmount"),
                    "flags": [str(f) for f in (r.get("flags") or []) if f],
                    "owners": [r.get("ownerName1"), r.get("ownerName2"),
                               *[(a.get("formattedName") or a.get("name")) if isinstance(a, dict)
                                 else a for a in (r.get("additionalOwners") or [])]]})
    out.sort(key=lambda b: (-b["year"], b["bill"] or ""))
    return out


def _dt(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "")[:19]).date()
    except ValueError:
        return None


def paid_late(detail: dict, year: int) -> dict:
    """Late-payment evidence from a GetbillDetails answer."""
    begin = _dt(detail.get("interestBeginDate")) or delinquent_from(year)
    pays = [d for d in (_dt(t.get("transactionCreationDate")) for t in detail.get("transactions") or []
                        if isinstance(t, dict) and str(t.get("transactionType") or "").upper() == "PAYMENT")
            if d]
    last = _dt(detail.get("lastPaymentDate")) or (max(pays) if pays else None)
    interest = detail.get("interestPaid")
    interest = float(interest) if isinstance(interest, (int, float)) else 0.0
    late = bool((last and last >= begin) or any(d >= begin for d in pays) or interest > 0)
    return {"paid_on": last.isoformat() if last else None, "interest_begin": begin.isoformat(),
            "interest_paid": round(interest, 2), "status": str(detail.get("statusType") or "").upper()
            or None, "paid_late": late}


# ---------------------------------------------------------------------------
# fetching (per-run cache, tenant health)
# ---------------------------------------------------------------------------

_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "failures": {}, "dead": {}})
    except TypeError:                                   # not weak-referenceable: no sharing
        return {"cache": {}, "failures": {}, "dead": {}}


class TenantDown(RuntimeError):
    pass


async def _get_json(client: Any, url: str, tenant: str) -> Any:
    run = _run(client)
    if url in run["cache"]:
        return run["cache"][url]
    if tenant in run["dead"]:
        raise TenantDown(run["dead"][tenant])
    try:
        text = await client.get_text(url, timeout=TIMEOUT_S,
                                     headers={"X-Tenant": tenant, "Accept": "application/json"})
        data = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        n = run["failures"][tenant] = run["failures"].get(tenant, 0) + 1
        why = f"{type(exc).__name__}: {str(exc)[:120]}"
        if n >= TENANT_MAX_FAILURES:
            run["dead"][tenant] = f"{n} failures this run, last {why}"
        raise
    run["failures"][tenant] = 0
    run["cache"][url] = data
    return data


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "page_url", "tenant", "claim_county_differs", "tax_parcel", "tax_parcel_from", "board_parcel",
         "searched", "results_total", "latest_levy_year", "latest_delinquent_eligible_levy",
         "delinquent_by_year", "total_delinquent", "years_delinquent", "under_500", "de_minimis",
         "not_yet_delinquent_due", "deferred_by_year", "flags", "claimed_years", "claimed_bill",
         "bills_checked", "owner_match", "note", "error", "tenant_health", "property_tax_verdict",
         "listing_claim_source")


def public_evidence(ev: dict) -> dict:
    return tc.pick(ev, _KEYS)


def _res(verdict: str, ev: dict, row: Any = None) -> VerificationResult:
    if verdict in ("refuted", "stale") and row is not None and tc.other_lien_listing(row):
        ev = dict(ev, property_tax_verdict=verdict, reason="other_lien_listing",
                  listing_claim_source=tc.g(row, "source"))
        verdict = "unconfirmed"
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    tenant, blk = tenant_of(row)
    claimed = claimed_years(row, blk)
    ev: dict[str, Any] = {"tenant": tenant, "board_parcel": row.get("parcel_id"),
                          "claimed_years": claimed,
                          "claimed_bill": (blk or {}).get("bill_number")}
    if not tenant:
        return _res("unconfirmed", dict(ev, reason="no_bill_tenant"))
    slug = tenant.lower()
    ev["page_url"] = PAGE_URL.format(slug=slug)
    if slug != str(row.get("county") or "").strip().lower():
        ev["claim_county_differs"] = True      # the roll's row, geocoded into another county
    cands = parcel_candidates(row, tenant, blk)
    if not cands:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))

    bills: list[dict] = []
    searched = []
    for parcel, src in cands[:MAX_SEARCHES]:
        url = SEARCH_URL.format(q=quote(parcel, safe=""), tenant=quote(tenant))
        try:
            payload = await _get_json(client, url, tenant)
        except TenantDown as exc:
            return _res("unconfirmed", dict(ev, reason="tenant_unhealthy", url=url,
                                            tenant_health=str(exc)[:200]))
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed", url=url,
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return _res("unconfirmed", dict(ev, reason="unreadable_answer", url=url))
        bills = bills_of(payload, parcel)
        searched.append({"parcel": parcel, "from": src, "bills": len(bills)})
        if bills:
            ev.update(url=url, tax_parcel=parcel, tax_parcel_from=src,
                      results_total=payload.get("totalCount"))
            break
    ev["searched"] = searched
    if not bills:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found",
                                        url=SEARCH_URL.format(q=quote(cands[0][0], safe=""),
                                                              tenant=quote(tenant))))

    latest = bills[0]
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), latest["owners"])
    ev["latest_levy_year"] = latest["year"]
    delinquent: dict[int, float] = {}
    current: dict[int, float] = {}
    deferred: dict[int, float] = {}
    flags: set[str] = set()
    for b in bills:
        if b["due"] <= 0:
            continue
        if b["status"] == "DEFERRED":
            deferred[b["year"]] = round(deferred.get(b["year"], 0.0) + b["due"], 2)
        elif b["status"] == "UNPAID" and is_eligible(b["year"], today):
            delinquent[b["year"]] = round(delinquent.get(b["year"], 0.0) + b["due"], 2)
            flags.update(b["flags"])
        elif b["status"] == "UNPAID":
            current[b["year"]] = round(current.get(b["year"], 0.0) + b["due"], 2)
    ev["delinquent_by_year"] = {str(y): a for y, a in sorted(delinquent.items(), reverse=True)}
    ev["total_delinquent"] = tc.money_total(delinquent)
    ev["years_delinquent"] = len(delinquent)
    ev["not_yet_delinquent_due"] = {str(y): a for y, a in sorted(current.items(), reverse=True)}
    if deferred:
        ev["deferred_by_year"] = {str(y): a for y, a in sorted(deferred.items(), reverse=True)}
    if flags:
        ev["flags"] = sorted(flags)
    if delinquent:
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        return _res("confirmed", ev, row)

    last_ok = latest_eligible(today)
    if latest["year"] < last_ok:
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended",
                                        latest_delinquent_eligible_levy=last_ok))
    if any(is_eligible(y, today) for y in deferred):
        return _res("unconfirmed", dict(ev, reason="only_deferred_balance"))

    # was it ever delinquent (paid late since) or not (paid on time)?
    def rank(b: dict) -> tuple:          # the claimed bill first, else the year's largest bill
        orig = b["original"] if isinstance(b["original"], (int, float)) else 0.0
        return (b["bill"] == ev.get("claimed_bill"), float(orig))

    paid: dict[int, dict] = {}
    for b in bills:
        if b["status"] != "PAID" or not b["id"] or not is_eligible(b["year"], today):
            continue
        if b["year"] not in paid or rank(b) > rank(paid[b["year"]]):
            paid[b["year"]] = b
    # the claimed years first, then the latest delinquent-eligible ones (2 bill pages at most)
    order = [y for y in claimed if y in paid]
    for y in sorted(paid, reverse=True)[:2]:
        if y not in order:
            order.append(y)
    checked = []
    for y in order[:MAX_BILL_CHECKS]:
        b = paid[y]
        durl = DETAIL_URL.format(bill_id=quote(b["id"]), tenant=quote(tenant))
        try:
            d = await _get_json(client, durl, tenant)
            if not isinstance(d, dict) or not d.get("statusType"):
                raise ValueError("not a bill")
        except Exception as exc:  # noqa: BLE001
            checked.append({"year": y, "bill": b["bill"], "url": durl,
                            "error": f"{type(exc).__name__}: {str(exc)[:100]}"})
            continue
        late = paid_late(d, y)
        checked.append({"year": y, "bill": b["bill"], "url": durl,
                        "page_url": BILL_PAGE_URL.format(slug=slug, bill_id=b["id"]), **late})
        if late["paid_late"]:
            ev["bills_checked"] = checked
            return _res("stale", ev, row)
    ev["bills_checked"] = checked
    if not checked:
        return _res("unconfirmed", dict(ev, reason="no_paid_bill_to_check"))
    if all("error" in c for c in checked):
        return _res("unconfirmed", dict(ev, reason="bill_details_unreadable"))
    if current:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    return _res("refuted", ev, row)
