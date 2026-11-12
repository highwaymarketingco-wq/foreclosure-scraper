"""tax_lien, Greenville County SC: is there a real delinquent property-tax balance on this map number?

A tax_lien adapter (same SIGNAL, GOVERNS and verdict meanings as tax_lien_qpaybill and
tax_lien_paystar; one tax_lien ledger). Rules: verifiers/_sc_bills.py.

WHY (2026-10-09, audit tax_checkers_2). 3,440 Greenville board rows carry a county tax claim (the
county's tax-sale roster, counties_sc.greenville_delinquent_tax, and the unpaid-tax ArcGIS layer)
and no verifier knew the county's site, so none was ever checked; the call-ready gate kept them
all at tax_check_missing.

SOURCE. The county's own Real Property tax search (the treasurer's "Online Tax Search", reached
through a disclaimer page that only links to it; no cookie, no login, no CAPTCHA). Read live
2026-10-09:
    GET https://www.greenvillecounty.org/appsas400/votaxqry/RealTaxesResults.aspx
        ?SearchType=MapNumber&Criteria=<13-character map number>
    -> <span id="ctl00_bodyContent_lbl_Count">N</span> (0: not found) and one <tr> per bill, every
       levy year back to 2009 (real property only), seven cells:
         0  owner (bold span), the receipt "YYYY NNNNNNNNN II SSS" (a Details link carrying
            TaxYear), a red status line
         1  map number, SID          2  permit, district          3  exemption, "D" (delinquent)
         4  assessment, Date Paid    5  base amount, amount paid  6  balance due (base tax only)
No property address on the page: the map number is the only binding (as tax_lien_paystar). The
newest levy on the site lags the billing season (2026 not loaded on 2026-10-09).

THE "D" MARK. The county marks a bill paid after about mid-March, or still unpaid, with "D"; a
bill paid between January 16 and March 15 carries none (a 2024 bill paid 03/08/2025). Lateness is
decided from Date Paid against the January 15 deadline, with "D" as proof on its own
(_sc_bills.lateness). The county credits the postmark, so a receipt dated a few days after the
deadline without "D" is undecided (_sc_bills.GRACE_DAYS).

WHICH MAP NUMBER: the roster block's own map number (raw.greenville_delinquent_tax.map_number:
the claim's parcel), then the board's parcel_id; both forms are 13 characters, letter-prefixed
ones included (G015001200600). A bill row binds only when its map number IS the one searched.
When both are searched and one owes while the other does not: identity_conflict. A parcel a
resolver attached decides only with the owner agreeing (_sc_bills, parcel_resolved_unbound).

Evidence is a whitelist (public ledger): no names, no receipts, no addresses.
"""
from __future__ import annotations

import html as _html
import re
import weakref
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result
from . import _sc_bills as sb
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy")
TRANSIENT_RETRY_DAYS = 0.25
SOURCE = "greenvillecounty.org"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)

COUNTY = "greenville"
ROLL_KEY = "greenville_delinquent_tax"
BASE = "https://www.greenvillecounty.org/appsas400/votaxqry/RealTaxesResults.aspx"
TIMEOUT_S = 45.0
PORTAL_MAX_FAILURES = 3
_NAME = __name__.rsplit(".", 1)[-1]


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "SC":
        return False
    if str(row.get("county") or "").strip().lower() != COUNTY:
        return False
    return tc.claims_property_tax(row, roll_block(row) is not None)


def roll_block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(ROLL_KEY)
    return b if isinstance(b, dict) and tc.alnum(b.get("map_number")) else None


def map_number(v: Any) -> Optional[str]:
    """The 13-character map number the site takes, else None (a placeholder, a short id)."""
    k = tc.alnum(v)
    if len(k) != 13 or set(k) <= {"0"} or not re.search(r"\d{6}", k):
        return None
    return k


def subjects(row: Any) -> list[tuple[str, str]]:
    """[(map number, 'claim' | 'board')], the claim's own map number first, distinct."""
    out: list[tuple[str, str]] = []
    blk = roll_block(row)
    if blk:
        m = map_number(blk.get("map_number"))
        if m:
            out.append((m, "claim"))
    b = map_number(tc.g(row, "parcel_id"))
    if b and all(b != v for v, _ in out):
        out.append((b, "board"))
    return out


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


def search_url(m: str) -> str:
    return f"{BASE}?{urlencode({'SearchType': 'MapNumber', 'Criteria': m})}"


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_COUNT = re.compile(r'lbl_Count"[^>]*>\s*(\d+)\s*<', re.I)
_TBODY = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.S | re.I)
_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_DIV = re.compile(r"<div\b[^>]*>(.*?)</div>", re.S | re.I)
_SPAN = re.compile(r"<span\b[^>]*>(.*?)</span>", re.S | re.I)
_RECEIPT = re.compile(r"\b((?:19|20)\d{2})\s+\d{6,}\s+\d{2}\s+\d{3}\b")
_TAXYEAR = re.compile(r"TaxYear=((?:19|20)\d{2})", re.I)


def _text(s: Any) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).replace("\xa0", " ").split())


def _money(s: Any) -> float:
    t = re.sub(r"[^\d.\-]", "", str(s or ""))
    try:
        return round(float(t), 2) if t not in ("", ".", "-") else 0.0
    except ValueError:
        return 0.0


def _date(s: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(s or "").strip()[:10], "%m/%d/%Y").date()
    except ValueError:
        return None


def _status_flags(text: str) -> list[str]:
    t = text.upper()
    if not t:
        return []
    if "SALE" in t or "SOLD" in t:
        return ["tax_sale"]
    if "BANKRUPT" in t:
        return ["bankruptcy"]
    return ["county_status_note"]


def parse_results(page: str) -> dict:
    """{"count": int | None, "bills": [{year, map, owner, owed, paid_on, late_flag, billed,
    flags}]} from a RealTaxesResults page."""
    m = _COUNT.search(page or "")
    out: dict[str, Any] = {"count": int(m.group(1)) if m else None, "bills": []}
    body = _TBODY.search(page or "")
    if not body:
        return out
    for tr in _TR.findall(body.group(1)):
        tds = _TD.findall(tr)
        if len(tds) < 7:
            continue
        divs = [[_text(d) for d in _DIV.findall(td)] for td in tds]
        span = _SPAN.search(tds[0])
        year = None
        ym = _TAXYEAR.search(tds[0]) or _RECEIPT.search(_text(tds[0]))
        if ym:
            year = int(ym.group(1))
        if not year:
            continue
        status = divs[0][-1] if len(divs[0]) > 1 else ""
        out["bills"].append({
            "year": year,
            "map": (divs[1] or [""])[0],
            "owner": _text(span.group(1)) if span else None,
            "late_flag": any(x.strip().upper() == "D" for x in divs[3]),
            "paid_on": _date(divs[4][1]) if len(divs[4]) > 1 else None,
            "billed": _money(divs[5][0]) if divs[5] else None,
            "owed": _money(" ".join(divs[6]) or _text(tds[6])),
            "flags": _status_flags(status),
        })
    return out


# ---------------------------------------------------------------------------
# fetching (cache and health per sweep run)
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "failures": 0, "dead": None})
    except TypeError:
        return {"cache": {}, "failures": 0, "dead": None}


async def fetch(client: Any, m: str) -> dict:
    run = _run(client)
    if run["dead"]:
        raise PortalDown(run["dead"])
    if m in run["cache"]:
        return run["cache"][m]
    try:
        page = await client.get_text(search_url(m), timeout=TIMEOUT_S)
        parsed = parse_results(page)
        if parsed["count"] is None:
            raise ValueError("not a results page")
    except Exception as exc:  # noqa: BLE001
        run["failures"] += 1
        if run["failures"] >= PORTAL_MAX_FAILURES:
            run["dead"] = f"{run['failures']} failures in a row this run, last {type(exc).__name__}"
        raise
    run["failures"] = 0
    run["cache"][m] = parsed
    return parsed


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "county", "searched", "decided_on", "tax_parcel", "delinquent_parcel", "claim_map",
         "board_parcel", "latest_levy_year", "latest_delinquent_eligible_levy", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "under_500", "de_minimis", "not_yet_delinquent_due",
         "sold_at_tax_sale_years", "flags", "claimed_years", "bills_checked", "owner_match", "note",
         "error", "portal_health", "current_claim_basis", "history_from_levy", "history_complete",
         "late_levy_years", "chronic_claim", "balance_basis")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


def _bills(rows: list[dict], m: str) -> list[sb.Bill]:
    return [sb.Bill(year=r["year"], owed=r["owed"], paid_on=r["paid_on"], late_flag=r["late_flag"],
                    sold="tax_sale" in r["flags"] and r["owed"] > 0, owner=r["owner"],
                    billed=r["billed"], flags=list(r["flags"]))
            for r in rows if tc.alnum(r["map"]) == m]


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    claimed = claimed_years(row)
    subs = subjects(row)
    blk = roll_block(row)
    ev: dict[str, Any] = {"county": "Greenville", "claimed_years": claimed,
                          "claim_map": (blk or {}).get("map_number"),
                          "board_parcel": row.get("parcel_id"),
                          "balance_basis": "base tax (the site's balance leaves out penalties)"}
    if not subs:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    searched, found = [], {}
    for m, role in subs:
        try:
            got = await fetch(client, m)
        except PortalDown as exc:
            return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200],
                                            searched=searched))
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed", searched=searched,
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        bills = _bills(got["bills"], m)
        searched.append({"map_number": m, "role": role, "bills": len(bills)})
        if bills:
            found[role] = (m, bills)
    ev["searched"] = searched
    if not found:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))

    def owes(bills: list[sb.Bill]) -> bool:
        return any(b.owed > 0 and sb.is_eligible(b.year, today) for b in bills)
    if "claim" in found and "board" in found and owes(found["claim"][1]) != owes(found["board"][1]):
        return _res("unconfirmed", dict(ev, reason="identity_conflict",
                                        delinquent_parcel="claim" if owes(found["claim"][1]) else "board"))
    role = "claim" if "claim" in found else "board"
    m, bills = found[role]
    ev["decided_on"] = "claim_map" if role == "claim" else "board_parcel"
    ev["tax_parcel"] = m          # tax_binding.verified_checks_row compares it with the row's ids
    ev["url"] = search_url(m)
    newest = sorted(bills, key=lambda b: -b.year)
    owners = [b.owner for b in newest[:2]] + [b.owner for b in bills if b.owed > 0]
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), owners)
    unbound = role == "board" and tc.parcel_resolved(row)
    verdict, ev = sb.judge(bills, claimed=claimed, today=today, ev=ev, unbound=unbound)
    return _res(verdict, ev)
