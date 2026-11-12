"""tax_lien, SC counties whose delinquent-tax collector bills on BillTrax: is the delinquent bill on
this map number still owed?

A tax_lien adapter (same SIGNAL, GOVERNS and verdict meanings as tax_lien_qpaybill; one tax_lien
ledger). One tenant today: DORCHESTER.

WHY (2026-10-09, audit tax_checkers_2). 1,307 Dorchester board rows (the county's delinquent roll,
counties_sc.dorchester_billtrax_delinquent_tax) carried a tax claim no verifier could check. The
county's regular tax site (dorchestercountytaxesonline.com, Catalis) loads a Google reCAPTCHA and
its data host answers 403 "Request blocked", and dorchestercountysc.gov answers Akamai "Access
Denied": walls, recorded in docs/walls_register.json. The delinquent-tax collector's BillTrax
site is open (no login, no CAPTCHA; the static "ar" app id is baked into its public bundle).

SOURCE (the roll scraper's own calls, read live 2026-10-09; the JSON body travels in one form
field, RequestData; form-encoded is accepted as the app's multipart is):
    POST https://dorchestercountyscdelinquenttaxapi.billtrax.com/crm/api/utilities/getbyidquickpay
         RequestData={"utilityId": "6832cda4f10fe04836869fcc"}      -> the search template
    POST .../crm/api/payment/SearchNewForQuickPayRawBsonExecutorWithRateLimit
         RequestData=<the template, Filter "", IsPaid "All", the AccountNumber field = the dashed
         map number NNN-NN-NN-NNN-NNN, PageCriteria>
    -> Results[0].Rows[].BillsAndPayments[]: Bill (AccountNumber, BillNumber "R-YYYY-########",
       PropertyLocation: the street name only, TotalDueNow, BillDate, the owner), Payment
       (PaymentDate, Amount), IsPaid, IsPending, IsBillAbated, IsDeliquent (true on every bill).

WHAT IT CAN SAY. BillTrax holds only bills that WENT delinquent, so:
  confirmed    a real-estate ("R-") bill of a late levy with TotalDueNow > 0, not paid, not abated;
  stale        nothing is owed and the claimed levy's (else the latest late levy's) bill is on the
               delinquent books and was paid: it was paid late by definition;
  refuted      never: an on-time payment leaves no bill here, and the treasurer's own site, which
               would show it, is walled;
  unconfirmed  not on the delinquent books (not_on_delinquent_list: absence is not proof of an
               on-time payment), abated, a pending payment, the claim's map number and the board's
               disagree (identity_conflict), a resolver's parcel whose owner does not agree, the site
               failed.
WHICH MAP NUMBER: the roll block's own account (raw.billtrax_dorchester_delinquent_tax
.account_number: the claim's parcel; 1 of the first 3 board rows sampled carried another parcel id
than its own block), then the board's parcel_id, both searched when they differ.

TWO CLAIMS: every levy from 2019 with a bill on the delinquent books is a late levy; the books'
reach back is not known, so the history counts as incomplete (chronic_claim confirmed at 3 late
levies, else unknown: governs_for keeps tax_lien_chronic).

Evidence is a whitelist (public ledger): no names, no bill numbers, no addresses.
"""
from __future__ import annotations

import json
import re
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _sc_bills as sb
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy")
TRANSIENT_RETRY_DAYS = 0.25
SOURCE = "billtrax.com"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)


@dataclass(frozen=True)
class Tenant:
    county: str
    api: str
    site: str
    utility_id: str
    app_id: str            # the "ar" header the public bundle sends on every call
    roll_key: str


TENANTS: dict[str, Tenant] = {
    "dorchester": Tenant("Dorchester", "https://dorchestercountyscdelinquenttaxapi.billtrax.com",
                         "https://dorchestercountyscdelinquenttax.billtrax.com/",
                         "6832cda4f10fe04836869fcc", "5e3d803410d9620e488249eb",
                         "billtrax_dorchester_delinquent_tax"),
}
TEMPLATE_PATH = "/crm/api/utilities/getbyidquickpay"
SEARCH_PATH = "/crm/api/payment/SearchNewForQuickPayRawBsonExecutorWithRateLimit"
PAGE_SIZE = 50
TIMEOUT_S = 60.0
PORTAL_MAX_FAILURES = 3
_NAME = __name__.rsplit(".", 1)[-1]
_TMS = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}-\d{3}$")


def tenant_of(row: Any) -> Optional[Tenant]:
    if str(tc.g(row, "state") or "").strip().upper() != "SC":
        return None
    return TENANTS.get(str(tc.g(row, "county") or "").strip().lower())


def roll_block(row: Any) -> Optional[dict]:
    t = tenant_of(row)
    b = tc.raw_of(row).get(t.roll_key) if t else None
    return b if isinstance(b, dict) else None


def applies(row: dict) -> bool:
    return tenant_of(row) is not None and tc.claims_property_tax(row, roll_block(row) is not None)


def tms(v: Any) -> Optional[str]:
    """The dashed map number the site takes (NNN-NN-NN-NNN-NNN), from a dashed or a bare form."""
    s = str(v or "").strip()
    if _TMS.match(s):
        return None if set(re.sub(r"\D", "", s)) <= {"0"} else s
    d = re.sub(r"\D", "", s)
    if len(d) == 13 and s.replace("-", "").isdigit() and set(d) != {"0"}:
        return f"{d[:3]}-{d[3:5]}-{d[5:7]}-{d[7:10]}-{d[10:]}"
    return None


def subjects(row: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    blk = roll_block(row)
    if blk:
        m = tms(blk.get("account_number"))
        if m:
            out.append((m, "claim"))
    b = tms(tc.g(row, "parcel_id"))
    if b and all(b != v for v, _ in out):
        out.append((b, "board"))
    return out


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    blk = roll_block(row)
    for y in (blk or {}).get("years") or []:
        years.add(tc.to_int(y))
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

def _fields(lst: Any) -> dict:
    return {f.get("FieldName"): f.get("FieldValue") for f in (lst or []) if isinstance(f, dict)}


def _day(v: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date() if v else None
    except ValueError:
        return None


def _num(v: Any) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def parse_search(payload: Any) -> list[dict]:
    """[{map, year, real, owed, paid, paid_on, pending, abated, owner}] of a search answer."""
    if not isinstance(payload, dict) or payload.get("HasErrors"):
        raise ValueError(f"unexpected answer: {str(payload)[:120]}")
    res = (payload.get("Results") or [{}])[0] or {}
    out = []
    for row in res.get("Rows") or []:
        for bp in (row or {}).get("BillsAndPayments") or []:
            b = _fields(bp.get("Bill"))
            pay = bp.get("Payment")
            pay = _fields(pay) if isinstance(pay, list) else (pay if isinstance(pay, dict) else {})
            num = str(b.get("BillNumber") or "")
            m = re.match(r"^([A-Z]+)-((?:19|20)\d{2})-", num)
            if not m:
                continue
            out.append({"map": str(b.get("AccountNumber") or "").strip(), "year": int(m.group(2)),
                        "real": m.group(1) == "R", "owed": _num(b.get("TotalDueNow")),
                        "paid": bool(bp.get("IsPaid")), "paid_on": _day(pay.get("PaymentDate")),
                        "pending": bool(bp.get("IsPending")), "abated": bool(bp.get("IsBillAbated")),
                        "owner": b.get("PropertyOwner")})
    return out


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "template": {}, "failures": 0, "dead": None,
                                         "session": None, "cm": None})
    except TypeError:
        return {"cache": {}, "template": {}, "failures": 0, "dead": None, "session": None, "cm": None}


def _headers(t: Tenant) -> dict:
    return {"ar": t.app_id, "Accept": "application/json", "Referer": t.site, "Origin": t.site.rstrip("/")}


async def _post(client: Any, t: Tenant, path: str, body: dict) -> Any:
    run = _run(client)
    if run["session"] is None:
        cm = client.form_session()
        run["session"], run["cm"] = await cm.__aenter__(), cm
    r = await run["session"].post_form(t.api + path, {"RequestData": json.dumps(body)},
                                       headers=_headers(t), timeout=TIMEOUT_S)
    if r.status in (401, 403):
        run["dead"] = f"HTTP {r.status}: the host refused the request"
        raise PortalDown(run["dead"])
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}")
    return json.loads(r.text)


async def search(client: Any, t: Tenant, m: str) -> list[dict]:
    run = _run(client)
    if run["dead"]:
        raise PortalDown(run["dead"])
    ck = (t.county, m)
    if ck in run["cache"]:
        return run["cache"][ck]
    try:
        tpl = run["template"].get(t.county)
        if tpl is None:
            tpl = await _post(client, t, TEMPLATE_PATH, {"utilityId": t.utility_id})
            if not isinstance(tpl, dict) or not tpl.get("NewQuickPayParams"):
                raise ValueError("search template unreadable")
            run["template"][t.county] = tpl
        body = dict(tpl, Filter="", IsPaid="All",
                    NewQuickPayParams=[dict(p, FieldValue=(m if p.get("FieldName") == "AccountNumber" else ""))
                                       for p in tpl["NewQuickPayParams"]],
                    PageCriteria={"PageNumberToFetch": 0, "PageSize": PAGE_SIZE, "SortOrder": "Desc",
                                  "SortColumn": ""})
        rows = parse_search(await _post(client, t, SEARCH_PATH, body))
    except PortalDown:
        raise
    except Exception:  # noqa: BLE001
        run["failures"] += 1
        if run["failures"] >= PORTAL_MAX_FAILURES:
            run["dead"] = f"{run['failures']} failures in a row this run"
        raise
    run["failures"] = 0
    run["cache"][ck] = rows
    return rows


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "tenant", "county", "searched", "decided_on", "tax_parcel", "delinquent_parcel", "claim_map",
         "board_parcel", "latest_levy_year", "latest_delinquent_eligible_levy", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "under_500", "de_minimis", "claimed_years",
         "bills_checked", "owner_match", "note", "error", "portal_health", "current_claim_basis",
         "history_from_levy", "history_complete", "late_levy_years", "chronic_claim", "pending_years",
         "abated_years", "source_scope")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    t = tenant_of(row)
    claimed = claimed_years(row)
    if t is None:
        return _res("unconfirmed", {"reason": "no_billtrax_tenant", "claimed_years": claimed})
    blk = roll_block(row)
    ev: dict[str, Any] = {"tenant": t.site, "county": t.county, "claimed_years": claimed,
                          "claim_map": (blk or {}).get("account_number"), "board_parcel": row.get("parcel_id"),
                          "source_scope": "the delinquent-tax collector's books: bills that went delinquent only"}
    subs = subjects(row)
    if not subs:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    searched, found = [], {}
    for m, role in subs:
        try:
            rows = await search(client, t, m)
        except PortalDown as exc:
            return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200],
                                            searched=searched))
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed", searched=searched,
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        mine = [r for r in rows if r["real"] and r["map"] == m]
        searched.append({"map_number": m, "role": role, "bills": len(mine)})
        found[role] = mine
    ev["searched"] = searched

    def owed(rs: list[dict]) -> dict[int, float]:
        out: dict[int, float] = {}
        for r in rs:
            if r["owed"] > 0 and not r["paid"] and not r["abated"] and sb.is_eligible(r["year"], today):
                out[r["year"]] = round(out.get(r["year"], 0.0) + r["owed"], 2)
        return out
    if found.get("claim") and found.get("board") and bool(owed(found["claim"])) != bool(owed(found["board"])):
        return _res("unconfirmed", dict(ev, reason="identity_conflict",
                                        delinquent_parcel="claim" if owed(found["claim"]) else "board"))
    role = "claim" if found.get("claim") else ("board" if found.get("board") else None)
    if role is None:
        return _res("unconfirmed", dict(ev, reason="not_on_delinquent_list"))
    rows = found[role]
    ev["decided_on"] = "claim_map" if role == "claim" else "board_parcel"
    ev["tax_parcel"] = next(m for m, r in subs if r == role)   # tax_binding.verified_checks_row
    ev["latest_levy_year"] = max(r["year"] for r in rows)
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), [r["owner"] for r in rows])
    late = sorted({r["year"] for r in rows if r["year"] >= tc.HISTORY_FROM_LEVY and sb.is_eligible(r["year"], today)})
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_complete=False, late_levy_years=late,
              chronic_claim=tc.history_claims(late, False))
    unbound = role == "board" and tc.parcel_resolved(row)
    dl = owed(rows)
    if dl:
        if unbound and ev["owner_match"] not in ("same", "partial"):
            return _res("unconfirmed", dict(ev, reason="parcel_resolved_unbound"))
        ev.update(delinquent_by_year={str(y): a for y, a in sorted(dl.items(), reverse=True)},
                  total_delinquent=tc.money_total(dl), years_delinquent=len(dl))
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        return _res("confirmed", ev)
    ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
    if unbound:
        return _res("unconfirmed", dict(ev, reason="parcel_resolved_unbound"))
    pending = sorted({r["year"] for r in rows if r["pending"]})
    if pending:
        return _res("unconfirmed", dict(ev, reason="payment_pending", pending_years=pending))
    years = [y for y in claimed if sb.is_eligible(y, today)] or [sb.latest_eligible(today)]
    checks = []
    for y in years[:3]:
        bills = [r for r in rows if r["year"] == y]
        if not bills:
            checks.append({"year": y, "on_delinquent_list": False})
            continue
        if all(r["abated"] for r in bills):
            checks.append({"year": y, "on_delinquent_list": True, "abated": True})
            continue
        dates = [r["paid_on"] for r in bills if r["paid"] and r["paid_on"]]
        checks.append({"year": y, "on_delinquent_list": True, "paid_on": max(dates).isoformat() if dates else None,
                       "deadline": sb.deadline(y).isoformat(), "paid_late": True if dates else None})
    ev["bills_checked"] = checks
    if any(c.get("paid_late") for c in checks):
        ev["current_claim_basis"] = ("claimed_year_paid_late" if any(c["year"] in claimed and c.get("paid_late")
                                                                     for c in checks) else "latest_year_paid_late")
        return _res("stale", ev)
    if any(c.get("abated") for c in checks):
        return _res("unconfirmed", dict(ev, reason="abated",
                                        abated_years=[c["year"] for c in checks if c.get("abated")]))
    if all(not c["on_delinquent_list"] for c in checks):
        return _res("unconfirmed", dict(ev, reason="not_on_delinquent_list"))
    return _res("unconfirmed", dict(ev, reason="no_payment_date"))
