"""tax_lien, SC counties on PayStar's newer per-county portal (<county>.paystar.io, the unified
/api/search): is the bill on this map number still unpaid?

A tax_lien adapter beside tax_lien_paystar (which reads the older taxes.paystar.io generation for
Abbeville): same SIGNAL, GOVERNS and verdict meanings, one tax_lien ledger. One tenant today:
BERKELEY.

WHY (2026-10-09, audit tax_checkers_2). 2,365 Berkeley board rows (the county's own unpaid roll,
counties_sc.berkeley_paystar_tax) carried a tax claim no verifier could check.

SOURCE (the roll scraper's own API, read live 2026-10-09; no login, no CAPTCHA, no cookie):
    POST https://berkeleycountysc.paystar.io/api/search
         {"searchTerm": "<TMS NNN-NN-NN-NNN>", "facetFilters": {"PaymentStatus": [],
          "AssetType": ["Real Property"], "TaxYear": []}, "page": 1, "pageSize": 50}
         -> data.results [{invoiceNumber, invoiceNumberHash, taxYear, paymentStatus}] (no TMS: the
            detail names it). The bare digits find nothing; the dashed TMS does.
    GET  https://berkeleycountysc.paystar.io/api/invoices/<invoiceNumberHash>
         -> data: taxYear, paymentStatus (Unpaid / Paid / Pending), paymentDate, invoiceAmountMinor
            (cents), delinquent, assetIdentifierDisplay (THE TMS), invoiceeName (the owner),
            assetMetaJson (the county record: SiteAddress = the situs, ActualPaymentDate,
            DelinquentCode). invoiceNumberHash is base64 of the invoice number, so the roll's own
            invoice (raw.berkeley_paystar_tax.invoice_number) is read directly; an invoice the
            portal no longer holds answers HTTP 400.
THE PORTAL DROPS PAID BILLS. On 2026-10-09 the Real Property facet held 123,256 Unpaid, 249 Paid and
42 Pending bills: almost every paid bill leaves the portal. So:
  confirmed    an Unpaid real-property bill of a late levy (S.C.: after January 15 of Y+1) with an
               amount, on the row's TMS (the detail's assetIdentifierDisplay);
  stale        the claimed levy's bill is still on the portal, Paid, dated after the deadline;
  refuted      the same, paid by the deadline (rare: paid bills seldom stay);
  unconfirmed  the claimed levy's bill is gone from the portal (claimed_bill_not_on_portal: most
               likely paid, but no date and no status say so), a pending payment, the bill's situs
               names another house number than the row's (address_parcel_mismatch, before any
               harmful answer), a resolver's parcel whose owner does not agree
               (parcel_resolved_unbound), the portal failed.
Evidence is a whitelist (public ledger): no names, no invoice numbers or hashes, no addresses.
"""
from __future__ import annotations

import base64
import json
import re
import weakref
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
SOURCE = "paystar.io"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)

#: county lowercased -> (County, portal host, the roll's raw block key)
TENANTS: dict[str, tuple[str, str, str]] = {
    "berkeley": ("Berkeley", "https://berkeleycountysc.paystar.io", "berkeley_paystar_tax"),
}
PAGE_SIZE = 50
MAX_DETAILS = 6
TIMEOUT_S = 60.0
PORTAL_MAX_FAILURES = 3
_NAME = __name__.rsplit(".", 1)[-1]
_TMS = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}[A-Z]?$")


def tenant_of(row: Any) -> Optional[tuple[str, str, str]]:
    if str(tc.g(row, "state") or "").strip().upper() != "SC":
        return None
    return TENANTS.get(str(tc.g(row, "county") or "").strip().lower())


def roll_block(row: Any) -> Optional[dict]:
    t = tenant_of(row)
    b = tc.raw_of(row).get(t[2]) if t else None
    return b if isinstance(b, dict) else None


def applies(row: dict) -> bool:
    return tenant_of(row) is not None and tc.claims_property_tax(row, roll_block(row) is not None)


def tms(v: Any) -> Optional[str]:
    """The dashed TMS the portal searches (NNN-NN-NN-NNN, a letter suffix kept), from a dashed or
    a bare 10-digit form."""
    s = str(v or "").strip().upper()
    if _TMS.match(s):
        return None if set(re.sub(r"\D", "", s)) <= {"0"} else s
    d = re.sub(r"[^0-9A-Z]", "", s)
    m = re.fullmatch(r"(\d{3})(\d{2})(\d{2})(\d{3})([A-Z]?)", d)
    if m and set(d[:10]) != {"0"}:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}{m.group(5)}"
    return None


def invoice_hash(number: Any) -> Optional[str]:
    n = str(number or "").strip()
    return base64.b64encode(n.encode()).decode() if re.fullmatch(r"\d{4}-\d{5,10}", n) else None


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

def _day(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    if not s or s == "0":
        return None
    for f in (lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")).date(),
              lambda x: datetime.strptime(x[:8], "%Y%m%d").date(),
              lambda x: datetime.strptime(x[:10], "%m/%d/%Y").date()):
        try:
            return f(s)
        except ValueError:
            continue
    return None


def parse_detail(payload: Any) -> Optional[dict]:
    """{tms, year, status, amount, paid_on, delinquent, situs, owner} of an invoice detail."""
    if not isinstance(payload, dict) or payload.get("hasErrors"):
        return None
    d = payload.get("data")
    if not isinstance(d, dict) or not d.get("taxYear"):
        return None
    meta = d.get("assetMetaJson")
    try:
        meta = json.loads(meta) if isinstance(meta, str) else (meta if isinstance(meta, dict) else {})
    except ValueError:
        meta = {}
    amt = d.get("invoiceAmountMinor")
    status = str(d.get("paymentStatus") or d.get("status") or "").strip().lower()
    return {"tms": str(d.get("assetIdentifierDisplay") or "").strip().upper(),
            "year": tc.to_int(d.get("taxYear")),
            "real": str(d.get("assetType") or "Real Property").lower().startswith("real"),
            "status": "paid" if status.startswith("paid") else "pending" if "pend" in status
            else "unpaid" if status.startswith("unpaid") else status or "other",
            "amount": round(float(amt) / 100.0, 2) if isinstance(amt, (int, float)) else None,
            "paid_on": _day(d.get("paymentDate")) or _day(meta.get("ActualPaymentDate")),
            "delinquent": bool(d.get("delinquent")),
            "situs": str(meta.get("SiteAddress") or "").strip() or None,
            "owner": d.get("invoiceeName") or meta.get("BillName")}


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "failures": 0, "dead": None, "session": None})
    except TypeError:
        return {"cache": {}, "failures": 0, "dead": None, "session": None}


async def _session(client: Any) -> Any:
    run = _run(client)
    if run["session"] is None:
        cm = client.form_session()
        run["session"] = await cm.__aenter__()
    return run["session"]


def _note(run: dict, ok: bool, why: str = "") -> None:
    if ok:
        run["failures"] = 0
        return
    run["failures"] += 1
    if run["failures"] >= PORTAL_MAX_FAILURES:
        run["dead"] = f"{run['failures']} failures in a row this run, last {why}"[:200]


async def search(client: Any, host: str, t: str) -> list[dict]:
    run = _run(client)
    if run["dead"]:
        raise PortalDown(run["dead"])
    ck = ("search", host, t)
    if ck in run["cache"]:
        return run["cache"][ck]
    s = await _session(client)
    r = await s.post_json(f"{host}/api/search",
                          {"searchTerm": t, "facetFilters": {"PaymentStatus": [], "AssetType": ["Real Property"],
                                                             "TaxYear": []}, "page": 1, "pageSize": PAGE_SIZE},
                          headers={"Accept": "application/json"}, timeout=TIMEOUT_S)
    if r.status in (401, 403):
        run["dead"] = f"HTTP {r.status}: the portal refused the request"
        raise PortalDown(run["dead"])
    try:
        if r.status != 200:
            raise RuntimeError(f"search HTTP {r.status}")
        data = (json.loads(r.text) or {}).get("data") or {}
        rows = [{"hash": x.get("invoiceNumberHash"), "year": tc.to_int(x.get("taxYear")),
                 "status": str(x.get("paymentStatus") or "").lower()}
                for x in data.get("results") or [] if x.get("invoiceNumberHash")]
    except Exception as exc:  # noqa: BLE001
        _note(run, False, type(exc).__name__)
        raise
    _note(run, True)
    run["cache"][ck] = rows
    return rows


async def detail(client: Any, host: str, h: str) -> Optional[dict]:
    """The invoice's detail; None when the portal no longer holds it (HTTP 400 / an error body)."""
    run = _run(client)
    if run["dead"]:
        raise PortalDown(run["dead"])
    ck = ("detail", host, h)
    if ck in run["cache"]:
        return run["cache"][ck]
    s = await _session(client)
    r = await s.get(f"{host}/api/invoices/{h}", timeout=TIMEOUT_S)
    if r.status in (401, 403):
        run["dead"] = f"HTTP {r.status}: the portal refused the request"
        raise PortalDown(run["dead"])
    if r.status in (400, 404):
        out = None
    elif r.status != 200:
        _note(run, False, f"HTTP {r.status}")
        raise RuntimeError(f"detail HTTP {r.status}")
    else:
        try:
            out = parse_detail(json.loads(r.text))
        except ValueError:
            out = None
    _note(run, True)
    run["cache"][ck] = out
    return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "tenant", "county", "board_parcel", "tax_parcel", "searched", "latest_levy_year",
         "delinquent_by_year", "total_delinquent", "years_delinquent", "under_500", "de_minimis",
         "not_yet_delinquent_due", "claimed_years", "bills_checked", "owner_match", "note", "error",
         "portal_health", "current_claim_basis", "address_relation", "pending_years", "claim_bill",
         "late_levy_years", "chronic_claim", "source_scope")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    ten = tenant_of(row)
    claimed = claimed_years(row)
    if ten is None:
        return _res("unconfirmed", {"reason": "no_paystar_tenant", "claimed_years": claimed})
    county, host, _ = ten
    blk = roll_block(row) or {}
    own_roll = tc.g(row, "source") == f"counties_sc.{ten[2]}"
    t = tms(row.get("parcel_id"))
    ev: dict[str, Any] = {"tenant": host, "county": county, "claimed_years": claimed,
                          "board_parcel": row.get("parcel_id"), "tax_parcel": t,
                          "source_scope": "the portal keeps unpaid bills; almost every paid bill leaves it"}
    if not t:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    try:
        found = await search(client, host, t)
        last_ok = sb.latest_eligible(today)
        want = sorted(found, key=lambda x: -x["year"])
        hashes = [x["hash"] for x in want if x["year"] >= last_ok - 3][:MAX_DETAILS]
        claim_h = invoice_hash(blk.get("invoice_number")) if own_roll else None
        claim_d = None
        if claim_h:
            claim_d = await detail(client, host, claim_h)
            ev["claim_bill"] = "on_portal" if claim_d else "not_on_portal"
        bills = []
        for h in hashes:
            d = await detail(client, host, h)
            if d and d["real"] and tc.alnum(d["tms"]) == tc.alnum(t):
                bills.append(d)
        if claim_d and claim_d["real"] and tc.alnum(claim_d["tms"]) == tc.alnum(t) and \
                all(b["year"] != claim_d["year"] or b["status"] != claim_d["status"] for b in bills):
            bills.append(claim_d)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["searched"] = [{"by": "tms", "results": len(found), "bills_of_parcel": len(bills)}]
    if claim_d and tc.alnum(claim_d["tms"]) != tc.alnum(t):
        return _res("unconfirmed", dict(ev, reason="identity_conflict"))
    if not bills:
        reason = "claimed_bill_not_on_portal" if (claim_h and claim_d is None) or found else "parcel_not_found"
        return _res("unconfirmed", dict(ev, reason=reason))
    ev["latest_levy_year"] = max(b["year"] for b in bills)
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), [b["owner"] for b in bills])
    addr = row.get("street_address")
    rels = {tc.address_relation(addr, b["situs"]) for b in bills if b["situs"]}
    rel = "match" if "match" in rels else "conflict" if "conflict" in rels else "unknown"
    ev["address_relation"] = rel
    resolved = tc.parcel_resolved(row)
    owed: dict[int, float] = {}
    current: dict[int, float] = {}
    for b in bills:
        if b["status"] == "unpaid" and (b["amount"] or 0) > 0:
            tgt = owed if sb.is_eligible(b["year"], today) else current
            tgt[b["year"]] = round(tgt.get(b["year"], 0.0) + b["amount"], 2)
    ev["not_yet_delinquent_due"] = {str(y): a for y, a in sorted(current.items(), reverse=True)}
    late = sorted({b["year"] for b in bills if sb.is_eligible(b["year"], today) and (
        b["year"] in owed or (b["status"] == "paid" and b["paid_on"] and b["paid_on"] > sb.deadline(b["year"])))})
    ev.update(late_levy_years=late, chronic_claim=tc.history_claims(late, False))
    if owed:
        if resolved and ev["owner_match"] not in ("same", "partial"):
            return _res("unconfirmed", dict(ev, reason="parcel_resolved_unbound"))
        if resolved and rel == "conflict":
            return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch"))
        ev.update(delinquent_by_year={str(y): a for y, a in sorted(owed.items(), reverse=True)},
                  total_delinquent=tc.money_total(owed), years_delinquent=len(owed))
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        return _res("confirmed", ev)
    ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
    pending = sorted({b["year"] for b in bills if b["status"] == "pending"})
    if pending:
        return _res("unconfirmed", dict(ev, reason="payment_pending", pending_years=pending))
    if resolved:
        return _res("unconfirmed", dict(ev, reason="parcel_resolved_unbound"))
    if rel == "conflict":
        return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch"))
    years = [y for y in claimed if sb.is_eligible(y, today)] or [last_ok]
    checks = []
    for y in years[:3]:
        paid = [b for b in bills if b["year"] == y and b["status"] == "paid" and b["paid_on"]]
        if not paid:
            checks.append({"year": y, "on_portal": any(b["year"] == y for b in bills)})
            continue
        last = max(b["paid_on"] for b in paid)
        checks.append({"year": y, "on_portal": True, "paid_on": last.isoformat(),
                       "deadline": sb.deadline(y).isoformat(), "paid_late": last > sb.deadline(y)})
    ev["bills_checked"] = checks
    if any(c.get("paid_late") for c in checks):
        ev["current_claim_basis"] = "claimed_year_paid_late" if any(
            c.get("paid_late") and c["year"] in claimed for c in checks) else "latest_year_paid_late"
        return _res("stale", ev)
    if checks and all(c.get("paid_late") is False for c in checks):
        ev["current_claim_basis"] = "claimed_years_on_time" if claimed else "latest_year_on_time"
        return _res("refuted", ev)
    return _res("unconfirmed", dict(ev, reason="claimed_bill_not_on_portal"))
