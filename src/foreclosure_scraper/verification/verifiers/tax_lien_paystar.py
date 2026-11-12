"""tax_lien, SC counties whose treasurer bills on PayStar (taxes.paystar.io): is there a real
delinquent property-tax balance on this parcel?

The fifth tax_lien adapter (same SIGNAL, GOVERNS and verdict meanings as tax_lien_buncombe,
tax_lien_ptscloud, tax_lien_qpaybill and tax_lien_pickens). One county today: ABBEVILLE.

WHY (2026-10-08). Abbeville's qPayBill tenant (abbevilletreasurer.qpaybill.com) redirects every
request to Info.aspx, "Sorry the site is currently off line."; the county treasurer's page now
links taxes.paystar.io/app/customer/abbeville-county-taxes, the county's own public search and pay
page (no login, no CAPTCHA). tax_lien_qpaybill no longer claims Abbeville (its MOVED map).

SOURCE (read live 2026-10-08, 6 requests). The page is a React app over a plain JSON API:
    GET /api/business-units/<slug>/context
        -> data.id (the business unit, 17), assetConfigurations [{id, key "property-taxes"}, ...]
    GET /api/business-units/<slug>/asset-configurations/property-taxes/search-configuration
        -> data.id (the search configuration, 40), searchFields[0].id (55)
    GET /api/business-units/<slug>/invoices/search-configurations/<cfg>/search
        ?BusinessUnitId&AssetSearchConfigurationId&Page&PageSize&Search.SearchFieldId
        &Search.FieldNames=AssetIdentifier&Search.SearchText=<map number>&Search.ExactMatch=true
        -> data.items: one per bill, every year back to 1995 (a parcel showed 20): taxYear,
           assetType (Real Property / Mobile Home / Watercraft / Vehicle), paymentStatus (Paid,
           Unpaid, Pending, Tax Sale), assetDescription (THE MAP NUMBER), invoiceNumberHash, the
           owner's name and MAILING address (never the situs: no address binding is possible here)
    GET /api/business-units/<slug>/invoices/<invoiceNumberHash>
        -> data.paymentStatus, data.paymentDate (ISO), data.invoiceAmountMinor (total due, cents),
           data.delinquent
The search list carries no payment date and no amount, so a bill's detail is read only when the
verdict needs it: each unpaid bill of a delinquent-eligible year (its amount, at most MAX_OWED),
or, with nothing owed, the bills that decide stale / refuted (the claimed years, then the two
latest eligible years; at most MAX_DECIDE). One run reads the tenant's ids once (2 requests).

VERDICTS (SC: a levy-year Y bill is late after January 15 of Y+1, weekend rolled to Monday;
tax_lien_qpaybill.deadline / tax_calendar):
  confirmed    an Unpaid bill of a delinquent-eligible year with an amount due, or a Tax Sale bill
               of one of the last RECENT_SALE_YEARS eligible levies that still shows an amount
               (reason sold_at_tax_sale).
  stale        nothing owed, and a claimed year (else the latest eligible one) was paid after its
               deadline, or a bill already late on the board's first_seen date was paid since.
  refuted      nothing owed and the bills checked were paid by the deadline.
  unconfirmed  no identifier, not on the portal, a resolver's parcel with no claim of its own
               (parcel_resolved_unbound: nothing binds it to the row's address here), a Tax Sale
               bill with nothing else owed (sold_at_tax_sale, its own state: never paid or late),
               a Pending payment, the record ended before the latest eligible levy, the claim's
               parcel and the board's disagree (identity_conflict), the portal unhealthy.
WHICH PARCEL: the qPayBill roll block's identification number (the claim's own map number),
then the board's parcel, as tax_lien_qpaybill (subjects()); a bill binds only when its
assetDescription IS that number.

HEALTH: one search or detail that fails is retried once by http_client; two failed rows in a row
open a circuit for COOLDOWN_BASE_S (doubling, up to COOLDOWN_MAX_S) during which rows answer
portal_unhealthy without a request; HTTP 401 / 403 is a wall for the run. The evidence names the
HTTP status.

Evidence (public ledger): a whitelist, no names and no addresses.
"""
from __future__ import annotations

import asyncio
import time
import weakref
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result
from . import _tax_common as tc
from . import tax_lien_qpaybill as qp

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
TRANSIENT_REASONS = ("portal_unhealthy", "fetch_failed")
TRANSIENT_RETRY_DAYS = 0.25
SOURCE = "taxes.paystar.io"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority     # the "2+ years and $500" rows first within a tier
ROW_SUMMARY_EXCLUDE = ("owner_name",)

BASE = "https://taxes.paystar.io"
#: county lowercased -> (County, PayStar business-unit slug)
TENANTS: dict[str, tuple[str, str]] = {"abbeville": ("Abbeville", "abbeville-county-taxes")}
ASSET_KEY = "property-taxes"
PAGE_SIZE = 100
MAX_OWED = 6
MAX_DECIDE = 4
RECENT_SALE_YEARS = 3
COOLDOWN_BASE_S = 60.0
COOLDOWN_MAX_S = 900.0
FAILURES_TO_OPEN = 2
_NAME = __name__.rsplit(".", 1)[-1]
_HEADERS = {"Accept": "application/json"}


def headers(slug: str) -> dict:
    return {**_HEADERS, "Referer": f"{BASE}/app/customer/{slug}"}


# ---------------------------------------------------------------------------
# which rows, which parcels (pure)
# ---------------------------------------------------------------------------

def tenant_of(row: Any) -> Optional[tuple[str, str]]:
    if str(tc.g(row, "state") or "").strip().upper() != "SC":
        return None
    return TENANTS.get(str(tc.g(row, "county") or "").strip().lower())


def applies(row: dict) -> bool:
    return tenant_of(row) is not None and tc.claims_property_tax(row, qp.roll_block(row) is not None)


def context_url(slug: str) -> str:
    return f"{BASE}/api/business-units/{slug}/context"


def config_url(slug: str) -> str:
    return f"{BASE}/api/business-units/{slug}/asset-configurations/{ASSET_KEY}/search-configuration"


def search_url(slug: str, ids: dict, value: str) -> str:
    q = urlencode([("BusinessUnitId", ids["bu"]), ("AssetSearchConfigurationId", ids["cfg"]),
                   ("Page", 1), ("PageSize", PAGE_SIZE), ("Search.SearchFieldId", ids["field"]),
                   ("Search.FieldNames", "AssetIdentifier"), ("Search.SearchText", value),
                   ("Search.ExactMatch", "true")])
    return f"{BASE}/api/business-units/{slug}/invoices/search-configurations/{ids['cfg']}/search?{q}"


def detail_url(slug: str, invoice_hash: str) -> str:
    return f"{BASE}/api/business-units/{slug}/invoices/{invoice_hash}"


def _kind(status: Any) -> str:
    s = str(status or "").strip().lower()
    if "sale" in s:
        return "sold"
    if s.startswith("unpaid") or "delinq" in s:
        return "owed"
    if s.startswith("paid"):
        return "paid"
    if "pend" in s:
        return "pending"
    return "other"


def _date(v: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date() if v else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# the portal, per sweep run
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    def __init__(self, kind: str, http_status: Optional[int], state: str,
                 retry_in_s: Optional[float]) -> None:
        self.kind, self.http_status, self.state = kind, http_status, state
        self.retry_in_s = None if retry_in_s is None else max(0, int(round(retry_in_s)))
        super().__init__(f"{kind}: circuit {state}")

    def evidence(self) -> dict:
        return {"tenant_health": str(self), "http_status": self.http_status,
                "tenant_failure": self.kind, "tenant_state": self.state,
                "retry_in_s": self.retry_in_s}


class _State:
    def __init__(self) -> None:
        self.ids: dict[str, dict] = {}
        self.failures = 0
        self.trips = 0
        self.open_until = 0.0
        self.blocked: Optional[tuple[str, Optional[int]]] = None
        self.last: tuple[str, Optional[int]] = ("unknown", None)
        self.lock = asyncio.Lock()


_RUNS: "weakref.WeakKeyDictionary[Any, _State]" = weakref.WeakKeyDictionary()


def _state(client: Any) -> _State:
    try:
        st = _RUNS.get(client)
        if st is None:
            st = _RUNS[client] = _State()
        return st
    except TypeError:
        return _State()


def _failure(exc: BaseException) -> tuple[str, Optional[int]]:
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    if isinstance(code, int):
        return f"http_{code}", code
    name = type(exc).__name__
    if "timeout" in name.lower() or "timed out" in str(exc).lower():
        return "timeout", None
    return f"request_error:{name}"[:60], None


async def _get(client: Any, st: _State, url: str, slug: str) -> Any:
    """One JSON GET through the sweep's client, behind the run's circuit breaker."""
    if st.blocked is not None:
        raise PortalDown(st.blocked[0], st.blocked[1], "blocked", None)
    if st.open_until:
        wait = st.open_until - time.monotonic()
        if wait > 0:
            raise PortalDown(st.last[0], st.last[1], "open", wait)
        st.open_until = 0.0
    try:
        data = await client.get_json(url, headers=headers(slug))
        if not isinstance(data, dict) or data.get("hasErrors"):
            raise ValueError(f"unexpected answer: {str(data)[:120]}")
    except Exception as exc:  # noqa: BLE001
        kind, code = _failure(exc)
        st.last = (kind, code)
        st.failures += 1
        if code in (401, 403):
            st.blocked = (kind, code)
            raise PortalDown(kind, code, "blocked", None) from exc
        if st.failures >= FAILURES_TO_OPEN:
            st.trips += 1
            cool = min(COOLDOWN_BASE_S * 2 ** (st.trips - 1), COOLDOWN_MAX_S)
            st.open_until = time.monotonic() + cool
            raise PortalDown(kind, code, "open", cool) from exc
        raise
    st.failures, st.trips = 0, 0
    return data


async def tenant_ids(client: Any, st: _State, slug: str) -> dict:
    """{bu, cfg, field} of the tenant's property-tax search, read once per run."""
    async with st.lock:
        if slug in st.ids:
            return st.ids[slug]
        ctx = (await _get(client, st, context_url(slug), slug)).get("data") or {}
        cfg = (await _get(client, st, config_url(slug), slug)).get("data") or {}
        fields = cfg.get("searchFields") or []
        ids = {"bu": ctx.get("id"), "cfg": cfg.get("id"), "field": (fields[0] or {}).get("id") if fields else None}
        if not all(ids.values()):
            raise ValueError(f"search configuration unreadable: {ids}")
        st.ids[slug] = ids
        return ids


async def bills(client: Any, st: _State, slug: str, ids: dict, value: str) -> dict:
    """The bills whose map number IS `value`: {found, rows: [{year, kind, hash, asset_type}],
    capped}."""
    data = (await _get(client, st, search_url(slug, ids, value), slug)).get("data") or {}
    items = data.get("items") or []
    mine = [{"year": tc.to_int(i.get("taxYear")), "kind": _kind(i.get("paymentStatus")),
             "status": i.get("paymentStatus"), "hash": i.get("invoiceNumberHash"),
             "asset_type": i.get("assetType"), "owner": i.get("invoiceeName") or i.get("assetOwner")}
            for i in items if tc.alnum(i.get("assetDescription")) == tc.alnum(value)]
    mine = [r for r in mine if 1990 < r["year"] < 2100 and r["hash"]]
    total = tc.to_int(data.get("totalItemCount"))
    return {"found": bool(mine), "rows": mine, "capped": total > len(items)}


async def detail(client: Any, st: _State, slug: str, row: dict) -> dict:
    d = (await _get(client, st, detail_url(slug, row["hash"]), slug)).get("data") or {}
    amt = d.get("invoiceAmountMinor")
    return {"paid_on": _date(d.get("paymentDate")), "status": d.get("paymentStatus"),
            "kind": _kind(d.get("paymentStatus")),
            "amount": round(float(amt) / 100.0, 2) if isinstance(amt, (int, float)) else None}


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "tenant", "county", "searched", "decided_on", "delinquent_parcel", "claim_ident",
         "board_parcel", "latest_levy_year", "latest_delinquent_eligible_levy", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "under_500", "de_minimis", "not_yet_delinquent_years",
         "sold_at_tax_sale_years", "pending_years", "claimed_years", "bills_checked", "owner_match",
         "asset_types", "note", "error", "tenant_health", "http_status", "tenant_failure",
         "tenant_state", "retry_in_s", "current_claim_basis", "late_levy_years", "chronic_claim",
         "page_capped")
_SEARCHED_KEYS = ("map_number", "role", "found", "rows", "latest_levy_year")


def _res(verdict: str, ev: dict) -> VerificationResult:
    out = tc.pick(ev, _KEYS)
    if isinstance(out.get("searched"), list):
        out["searched"] = [tc.pick(s, _SEARCHED_KEYS) for s in out["searched"]]
    return result(SIGNAL, verdict, out, source=SOURCE, version=VERSION, verifier=_NAME)


def _summary(found: dict, value: str, role: str) -> dict:
    rows = found["rows"]
    return {"map_number": value, "role": role, "found": found["found"], "rows": len(rows),
            "latest_levy_year": max((r["year"] for r in rows), default=None)}


async def _owed(client, st, slug, rows: list[dict], today: date) -> dict[int, float]:
    """{year: amount} of the unpaid bills of delinquent-eligible years (details read, newest
    first, at most MAX_OWED); a recent Tax Sale bill that still shows an amount counts too."""
    last_ok = qp.latest_eligible(today)
    out: dict[int, float] = {}
    want = sorted((r for r in rows if qp.is_eligible(r["year"], today) and (
        r["kind"] == "owed" or (r["kind"] == "sold" and r["year"] > last_ok - RECENT_SALE_YEARS))),
        key=lambda r: -r["year"])[:MAX_OWED]
    for r in want:
        d = await detail(client, st, slug, r)
        if d["kind"] in ("owed", "sold") and (d["amount"] or 0) > 0:
            out[r["year"]] = round(out.get(r["year"], 0.0) + d["amount"], 2)
    return out


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    ten = tenant_of(row)
    claimed = qp.claimed_years(row)
    if ten is None:
        return _res("unconfirmed", {"reason": "no_paystar_tenant", "claimed_years": claimed})
    county, slug = ten
    subs = qp.subjects(row, county)
    blk = qp.roll_block(row)
    ev: dict[str, Any] = {"tenant": slug, "county": county, "claimed_years": claimed,
                          "claim_ident": (blk or {}).get("identification_no"),
                          "board_parcel": qp.board_parcel(row, county)}
    if not subs:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    st = _state(client)
    searched: list[dict] = []
    found: dict[str, dict] = {}
    owed: dict[str, dict[int, float]] = {}
    try:
        ids = await tenant_ids(client, st, slug)
        for value, role in subs:
            b = await bills(client, st, slug, ids, value)
            searched.append(_summary(b, value, role))
            if b["capped"] and b["found"]:
                ev["page_capped"] = True
            if b["found"]:
                found[role] = b
                owed[role] = await _owed(client, st, slug, b["rows"], today)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", searched=searched,
                                        **exc.evidence()))
    except Exception as exc:  # noqa: BLE001
        kind, code = _failure(exc)
        return _res("unconfirmed", dict(ev, reason="fetch_failed", searched=searched,
                                        tenant_failure=kind, http_status=code,
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["searched"] = searched
    if not found:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
    if "claim" in found and "board" in found and bool(owed["claim"]) != bool(owed["board"]):
        return _res("unconfirmed", dict(ev, reason="identity_conflict",
                                        delinquent_parcel="claim" if owed["claim"] else "board"))
    role = "claim" if "claim" in found else "board"
    b, dl = found[role], owed[role]
    rows = b["rows"]
    ev["decided_on"] = "claim_ident" if role == "claim" else "board_parcel"
    ev["owner_match"] = tc.owner_category(row.get("owner_name"),
                                          [r.get("owner") for r in sorted(rows, key=lambda r: -r["year"])[:2]])
    ev["asset_types"] = sorted({str(r["asset_type"]) for r in rows if r.get("asset_type")})
    ev["latest_levy_year"] = max(r["year"] for r in rows)
    ev["not_yet_delinquent_years"] = sorted({r["year"] for r in rows if r["kind"] == "owed"
                                             and not qp.is_eligible(r["year"], today)}, reverse=True)
    last_ok = qp.latest_eligible(today)
    sold = sorted({r["year"] for r in rows if r["kind"] == "sold"}, reverse=True)
    if sold:
        ev["sold_at_tax_sale_years"] = sold
    sold_recent = any(y > last_ok - RECENT_SALE_YEARS for y in sold)
    unbound = role == "board" and tc.parcel_resolved(row)
    if dl:
        if unbound and ev["owner_match"] not in ("same", "partial"):
            return _res("unconfirmed", dict(ev, reason="parcel_resolved_unbound"))
        ev.update(delinquent_by_year={str(y): a for y, a in sorted(dl.items(), reverse=True)},
                  total_delinquent=tc.money_total(dl), years_delinquent=len(dl))
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        if any(y in sold for y in dl) or sold_recent:
            ev["reason"] = "sold_at_tax_sale"
        return _res("confirmed", ev)
    ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
    if sold_recent:
        return _res("unconfirmed", dict(ev, reason="sold_at_tax_sale"))
    if unbound:
        return _res("unconfirmed", dict(ev, reason="parcel_resolved_unbound"))
    if ev.get("page_capped"):
        return _res("unconfirmed", dict(ev, reason="page_capped"))
    if ev["latest_levy_year"] < last_ok:
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended",
                                        latest_delinquent_eligible_levy=last_ok))
    pending = sorted({r["year"] for r in rows if r["kind"] == "pending" and qp.is_eligible(r["year"], today)})
    if pending:
        return _res("unconfirmed", dict(ev, reason="payment_pending", pending_years=pending))
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        if r["kind"] == "paid" and qp.is_eligible(r["year"], today):
            by_year.setdefault(r["year"], []).append(r)
    order = [y for y in claimed if y in by_year]
    for y in sorted(by_year, reverse=True)[:2]:
        if y not in order:
            order.append(y)
    first_seen = tc.first_seen_date(row)
    checks: list[dict] = []
    verdict = "none"
    try:
        for y in order[:MAX_DECIDE]:
            dates = []
            for r in by_year[y]:
                d = await detail(client, st, slug, r)
                if d["kind"] == "paid" and d["paid_on"]:
                    dates.append(d["paid_on"])
            if not dates:
                checks.append({"year": y, "status": "Paid", "paid_late": None})
                continue
            dl_ = qp.deadline(y)
            last = max(dates)
            c = {"year": y, "status": "Paid", "paid_on": last.isoformat(), "deadline": dl_.isoformat(),
                 "paid_late": last > dl_}
            checks.append(c)
            if c["paid_late"]:
                verdict = "stale"
                if tc.paid_after_seen(first_seen, dl_ + timedelta(days=1), last.isoformat()):
                    ev["note"] = "a bill already late on the board's first_seen date was paid since"
                break
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", **exc.evidence()))
    except Exception as exc:  # noqa: BLE001
        kind, code = _failure(exc)
        return _res("unconfirmed", dict(ev, reason="fetch_failed", tenant_failure=kind,
                                        http_status=code, error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["bills_checked"] = checks
    late = sorted(c["year"] for c in checks if c.get("paid_late"))
    ev["late_levy_years"] = late
    ev["chronic_claim"] = tc.history_claims(late, False)
    if verdict == "none" and any(c.get("paid_late") is False for c in checks):
        verdict = "refuted"
    if verdict == "none":
        return _res("unconfirmed", dict(ev, reason="no_paid_row_to_read"))
    if verdict == "stale":
        ev["current_claim_basis"] = ("claimed_year_paid_late"
                                     if any(c.get("paid_late") and c["year"] in claimed for c in checks)
                                     else "latest_year_paid_late")
    else:
        ev["current_claim_basis"] = ("claimed_years_on_time" if any(c["year"] in claimed for c in checks)
                                     else "latest_year_on_time")
        if ev["not_yet_delinquent_years"]:
            ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    return _res(verdict, ev)
