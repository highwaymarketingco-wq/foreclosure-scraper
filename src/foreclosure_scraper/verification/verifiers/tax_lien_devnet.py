"""tax_lien, NC counties whose tax bills are on DEVNET wEdge: is there a real delinquent
property-tax balance on this parcel?

A tax_lien adapter (same SIGNAL, GOVERNS and verdict meanings as tax_lien_itspublic; one tax_lien
ledger). One county today: GASTON.

WHY (2026-10-09, audit tax_checkers_2). 40 Gaston board rows carried a county tax claim no verifier
could check (8 of them lane A rows; 1 waiting on nothing but this check). Most carry an
advertisement-PDF block copied from one other parcel (county_id 87142 on six of six rows
sampled): the parcel's own bills are what decide.

SOURCE (read live 2026-10-09; no login, no cookie, no CAPTCHA; robots.txt disallows /parcel/*,
which is not a wall under the owner's 2026-09-20 decision):
    GET https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/MapServer/11/query
        ?where=PIN='<NNNN-NN-NNNN>'&outFields=PIN,PID,PHYSSTRADD&returnGeometry=false&f=json
        -> the PID (the tax site's parcel number) and PHYSSTRADD (the situs street). The tax site
           does not know the 10-digit PIN.
    GET https://gastonnc.devnetwedge.com/parcel/view/<PID>/<levy year>
        -> "Payment History" (every levy from 2009: Tax Year, Total Due, Total Paid, Amount Unpaid,
           Date Paid), "Physical Address". The Billing panel's "Paid By" (a payer's name) is never
           read. An exempt parcel has no payment history ("Not Billed").
VERDICTS (NC: a levy-year Y bill is late once unpaid on January 6 of Y+1; tax_calendar):
  confirmed    a late levy shows an Amount Unpaid on the row's own parcel (its PIN exactly; a
               resolver's PIN needs the situs to carry the row's address);
  stale        nothing late is owed and a claimed levy (else one of the two latest late levies) was
               paid on or after its delinquency date;
  refuted      as stale, paid before it;
  unconfirmed  no PIN, not found, exempt (no bills), the site failed, the parcel's bills end before
               the latest late levy, a payment with no date, or the situs names another house number
               than the row's (address_parcel_mismatch, before any harmful answer).
Evidence is a whitelist (public ledger): no names, no addresses.
"""
from __future__ import annotations

import html as _html
import json
import re
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc
from .tax_lien_itspublic import situs_street

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy")
TRANSIENT_RETRY_DAYS = 0.25
SOURCE = "devnetwedge.com"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)


@dataclass(frozen=True)
class Site:
    county: str
    base: str            # https://<tenant>.devnetwedge.com
    gis: str             # the parcel layer's /query endpoint (PIN -> PID, PHYSSTRADD)
    cities: tuple[str, ...] = ()


SITES: dict[str, Site] = {
    "gaston": Site("Gaston", "https://gastonnc.devnetwedge.com",
                   "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/MapServer/11/query",
                   cities=("SPENCER MOUNTAIN", "KINGS MOUNTAIN", "BESSEMER CITY", "IRON STATION",
                           "MOUNT HOLLY", "HIGH SHOALS", "MCADENVILLE", "CHERRYVILLE", "CRAMERTON",
                           "GASTONIA", "BELMONT", "STANLEY", "CROUSE", "LOWELL", "DALLAS", "ALEXIS",
                           "RANLO")),
}
TIMEOUT_S = 45.0
PORTAL_MAX_FAILURES = 3
MAX_DECIDE = 3
_NAME = __name__.rsplit(".", 1)[-1]


def site_of(row: Any) -> Optional[Site]:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return None
    return SITES.get(str(tc.g(row, "county") or "").strip().lower())


def applies(row: dict) -> bool:
    return site_of(row) is not None and tc.claims_property_tax(row, False)


def pin_of(v: Any) -> Optional[str]:
    """The dashed 10-digit PIN (NNNN-NN-NNNN) the GIS layer keys, from a dashed or bare form."""
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) != 10 or set(d) == {"0"} or re.search(r"[A-Za-z]", str(v or "")):
        return None
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

def _text(s: Any) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).split())


def _money(s: Any) -> float:
    t = re.sub(r"[^\d.\-]", "", str(s or ""))
    try:
        return round(float(t), 2) if t not in ("", ".", "-") else 0.0
    except ValueError:
        return 0.0


def _date(s: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(s or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _label(page: str, label: str) -> Optional[str]:
    m = re.search(r'inner-label[^>]*>\s*' + re.escape(label) + r'\s*</div>\s*<div[^>]*>(.*?)</div>', page,
                  re.S | re.I)
    return _text(m.group(1)) or None if m else None


def parse_parcel(page: str) -> Optional[dict]:
    """{"pid", "situs", "bills": [{year, due, paid, unpaid, paid_on}]} from a parcel page; None
    when the page is not a parcel page."""
    page = page or ""
    pid = _label(page, "Parcel Number")
    if not pid:
        return None
    bills = []
    i = page.find('id="PaymentHistory1"')
    if i >= 0:
        body = re.search(r"<tbody>(.*?)</tbody>", page[i:], re.S | re.I)
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S | re.I):
            tds = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if len(tds) < 5 or not re.fullmatch(r"(19|20)\d{2}", tds[0]):
                continue
            bills.append({"year": int(tds[0]), "due": _money(tds[1]), "paid": _money(tds[2]),
                          "unpaid": _money(tds[3]), "paid_on": _date(tds[4])})
    return {"pid": pid, "situs": _label(page, "Physical Address"), "bills": bills}


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "failures": 0, "dead": None})
    except TypeError:
        return {"cache": {}, "failures": 0, "dead": None}


async def _cached(client: Any, key: Any, coro_fn) -> Any:
    run = _run(client)
    if run["dead"]:
        raise PortalDown(run["dead"])
    if key in run["cache"]:
        return run["cache"][key]
    try:
        out = await coro_fn()
    except Exception as exc:  # noqa: BLE001
        run["failures"] += 1
        if run["failures"] >= PORTAL_MAX_FAILURES:
            run["dead"] = f"{run['failures']} failures in a row this run, last {type(exc).__name__}"
        raise
    run["failures"] = 0
    run["cache"][key] = out
    return out


def gis_url(site: Site, pin: str) -> str:
    return (f"{site.gis}?where={quote(f'PIN={chr(39)}{pin}{chr(39)}')}&outFields=PIN,PID,PHYSSTRADD"
            f"&returnGeometry=false&f=json")


async def lookup_pin(client: Any, site: Site, pin: str) -> Optional[dict]:
    async def go():
        data = await client.get_json(gis_url(site, pin), timeout=TIMEOUT_S)
        if not isinstance(data, dict) or "features" not in data:
            raise ValueError(f"not a layer answer: {str(data)[:120]}")
        feats = [f.get("attributes") or {} for f in data["features"] if isinstance(f, dict)]
        feats = [a for a in feats if tc.alnum(a.get("PIN")) == tc.alnum(pin) and a.get("PID")]
        return {"pid": str(feats[0]["PID"]).strip(), "situs": feats[0].get("PHYSSTRADD")} if len(feats) == 1 else None
    return await _cached(client, ("gis", site.county, pin), go)


def parcel_url(site: Site, pid: str, year: int) -> str:
    return f"{site.base}/parcel/view/{quote(pid)}/{year}"


async def fetch_parcel(client: Any, site: Site, pid: str, year: int) -> dict:
    async def go():
        parsed = parse_parcel(await client.get_text(parcel_url(site, pid, year), timeout=TIMEOUT_S))
        if parsed is None:
            raise ValueError("not a parcel page")
        return parsed
    return await _cached(client, ("parcel", site.county, pid, year), go)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "county", "board_parcel", "tax_parcel", "tax_parcel_row_own", "latest_levy_year",
         "latest_delinquent_eligible_levy", "delinquent_by_year", "total_delinquent", "years_delinquent",
         "under_500", "de_minimis", "not_yet_delinquent_due", "claimed_years", "bills_checked", "note",
         "error", "portal_health", "address_relation", "address_binding", "current_claim_basis",
         "history_from_levy", "history_complete", "late_levy_years", "chronic_claim")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    site = site_of(row)
    claimed = claimed_years(row)
    if site is None:
        return _res("unconfirmed", {"reason": "no_devnet_site", "claimed_years": claimed})
    county = site.county
    pin = pin_of(row.get("parcel_id"))
    ev: dict[str, Any] = {"county": county, "claimed_years": claimed, "board_parcel": row.get("parcel_id")}
    if not pin:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    try:
        hit = await lookup_pin(client, site, pin)
        if hit is None:
            return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
        page, last_exc = None, None
        for y in (today.year, today.year - 1):       # the current levy's page; before billing, the last
            try:
                page = await fetch_parcel(client, site, hit["pid"], y)
                break
            except PortalDown:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        if page is None:
            raise last_exc or RuntimeError("no parcel page")
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev.update(tax_parcel=pin, tax_parcel_row_own=not tc.parcel_resolved(row),
              url=parcel_url(site, hit["pid"], today.year))
    bills = page["bills"]
    if not bills:
        return _res("unconfirmed", dict(ev, reason="no_bills_exempt_or_not_billed"))
    situs = hit.get("situs") or situs_street(page.get("situs"), site.cities)
    addr = row.get("street_address")
    rel = tc.address_relation(addr, situs) if tc.address_query(addr) and situs else "unknown"
    ev["address_relation"] = rel
    late_after = {b["year"]: tax_calendar.delinquent_after(b["year"], "NC", county) for b in bills}
    delinquent = {b["year"]: b["unpaid"] for b in bills
                  if b["unpaid"] > 0 and tax_calendar.levy_year_is_delinquent(b["year"], "NC", county, today)}
    current = {b["year"]: b["unpaid"] for b in bills
               if b["unpaid"] > 0 and not tax_calendar.levy_year_is_delinquent(b["year"], "NC", county, today)}
    ev["latest_levy_year"] = max(b["year"] for b in bills)
    ev["not_yet_delinquent_due"] = {str(y): a for y, a in sorted(current.items(), reverse=True)}
    late_years = sorted(b["year"] for b in bills if b["year"] >= tc.HISTORY_FROM_LEVY and (
        b["year"] in delinquent or (b["paid_on"] and b["paid_on"] >= late_after[b["year"]])))
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_complete=True, late_levy_years=late_years,
              chronic_claim=tc.history_claims(late_years, True))
    resolved = tc.parcel_resolved(row)
    if delinquent:
        if resolved and rel != "match":
            return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch" if rel == "conflict"
                                            else "parcel_resolved_unbound"))
        ev["address_binding"] = "bill_address" if rel == "match" else "parcel_number"
        ev.update(delinquent_by_year={str(y): a for y, a in sorted(delinquent.items(), reverse=True)},
                  total_delinquent=tc.money_total(delinquent), years_delinquent=len(delinquent))
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        return _res("confirmed", ev)
    ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
    if rel == "conflict" or (resolved and rel != "match"):
        return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch" if rel == "conflict"
                                        else "parcel_resolved_unbound"))
    ev["address_binding"] = ("bill_address" if rel == "match" else "unverified" if tc.address_query(addr)
                             else "no_row_address")
    last_ok = tax_calendar.latest_delinquent_levy_year("NC", county, today)
    if ev["latest_levy_year"] < last_ok:
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended", latest_delinquent_eligible_levy=last_ok))
    by_year = {b["year"]: b for b in bills if tax_calendar.levy_year_is_delinquent(b["year"], "NC", county, today)}
    order = [y for y in claimed if y in by_year]
    for y in sorted(by_year, reverse=True)[:2]:
        if y not in order:
            order.append(y)
    checks = []
    for y in order[:MAX_DECIDE]:
        b = by_year[y]
        if b["due"] <= 0:
            continue
        checks.append({"year": y, "paid_on": b["paid_on"].isoformat() if b["paid_on"] else None,
                       "delinquent_from": late_after[y].isoformat(),
                       "paid_late": (b["paid_on"] >= late_after[y]) if b["paid_on"] else None})
    ev["bills_checked"] = checks
    if any(c["paid_late"] for c in checks):
        ev["current_claim_basis"] = ("claimed_year_paid_late" if any(c["paid_late"] and c["year"] in claimed
                                                                     for c in checks) else "latest_year_paid_late")
        return _res("stale", ev)
    if any(c["paid_late"] is False for c in checks) and not any(
            c["paid_late"] is None and c["year"] in claimed for c in checks):
        ev["current_claim_basis"] = ("claimed_years_on_time" if any(c["year"] in claimed for c in checks)
                                     else "latest_year_on_time")
        if current:
            ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
        return _res("refuted", ev)
    return _res("unconfirmed", dict(ev, reason="no_payment_date"))
