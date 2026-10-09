"""tax_lien, Florence County SC: is there a real delinquent property-tax balance on this parcel?

A tax_lien adapter (same SIGNAL, GOVERNS and verdict meanings as tax_lien_qpaybill; one tax_lien
ledger). Rules: verifiers/_sc_bills.py.

WHY (2026-10-09, audit tax_checkers_2). 1,829 Florence board rows (the county's tax-sale list,
counties_sc.florence_delinquent_tax) carry a tax claim no verifier could check. The county's
PayStar tenant (florence-county-tax) cannot search by map number and holds only the not-yet-due
2026 levy, so it is not a source (tax_lien_paystar stays Abbeville only).

SOURCE. The treasurer's own tax inquiry (linked from florencecountysc.gov services): plain GETs,
no cookie, no login, no CAPTCHA, a daily snapshot ("As of ... 07:00"). Read live 2026-10-09:
    GET http://web.florenceco.org/cgi-bin/ta/tax-inq.cgi?step=2&file=<F>&name=&street=
        &map=<MMMMM>&block=<BB>&parcel=<PPP>&acct=&cat=&num=&rc1=&rc2=
        one levy year's bills of the parcel. F: rpcpubf (the current levy), rpcpubp1 (the one
        before), rpcpubp2, rpcpubp3. A delinquent unpaid bill's cells are painted #ffa0a0 ("Red
        Entries Are Delinquent Taxes").
    GET http://web.florenceco.org/cgi-bin/ta/tax-del.cgi?step=2&<the same parcel fields>
        every bill of the parcel that went delinquent and was paid later, back to 1981, with its
        paid date (a still-open delinquent bill is in its year file, red, not here).
The map must be zero-padded to five digits (map 143 finds nothing, 00143 finds it); the board's
TMS forms 34000-47-051, 143-31-031 and 43-31-031 all become 00143 31 031. "No match found for your
search" is not found. Each bill row: the notice number (its first two digits are the levy year),
"MMMMM BB PPP", type ("Real") and district, owner and lot description (no situs: the parcel number
is the only binding), billing address, messages ("S SCHEDULED FOR TAX SALE", "PAID FROM TAX SALE
- REDEEMED", "H HOLD"), assessment, taxes and the Total Due / Total Paid label, and the dates
Posted / Paid / Abated / Refund (MM/DD/YY).

A ROW'S CHECK reads the latest late levy's year file, the one before it, and the delinquent list
(three requests): an unpaid red bill confirms; a bill on the delinquent list was paid late (stale);
a year-file bill paid by the deadline is on time (refuted). Older late levies come from the
delinquent list, so the chronic claim is judged on the whole history.

WHICH PARCEL: the sale list block's own TMS (raw.florence_delinquent_tax.tms: the claim's parcel),
then the board's parcel_id; both searched when they differ, identity_conflict when one owes and the
other does not (tax_lien_paystar's rule). A resolver's parcel decides only with the owner agreeing.

Evidence is a whitelist (public ledger): no names, no notice numbers, no addresses.
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
SOURCE = "web.florenceco.org"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)

COUNTY = "florence"
ROLL_KEY = "florence_delinquent_tax"
BASE = "http://web.florenceco.org/cgi-bin/ta/"
YEAR_FILES = ("rpcpubf", "rpcpubp1", "rpcpubp2", "rpcpubp3")
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
    return b if isinstance(b, dict) and tc.alnum(b.get("tms")) else None


_TMS = re.compile(r"^\s*(\d{1,5})[-\s.]+(\d{1,2})[-\s.]+(\d{1,3})\s*$")


def mbp(v: Any) -> Optional[tuple[str, str, str]]:
    """('00143', '31', '031') from a board TMS ('143-31-031', '00143-31-031'), else None."""
    m = _TMS.match(str(v or ""))
    if not m:
        return None
    a, b, c = m.group(1).zfill(5), m.group(2).zfill(2), m.group(3).zfill(3)
    return None if set(a + b + c) <= {"0"} else (a, b, c)


def subjects(row: Any) -> list[tuple[tuple[str, str, str], str]]:
    out: list[tuple[tuple[str, str, str], str]] = []
    blk = roll_block(row)
    if blk:
        m = mbp(blk.get("tms"))
        if m:
            out.append((m, "claim"))
    b = mbp(tc.g(row, "parcel_id"))
    if b and all(b != v for v, _ in out):
        out.append((b, "board"))
    return out


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


def _query(m: tuple[str, str, str]) -> list[tuple[str, str]]:
    return [("name", ""), ("street", ""), ("map", m[0]), ("block", m[1]), ("parcel", m[2]),
            ("acct", ""), ("cat", ""), ("num", ""), ("rc1", ""), ("rc2", "")]


def year_url(m: tuple[str, str, str], file: str) -> str:
    return f"{BASE}tax-inq.cgi?{urlencode([('step', 2), ('file', file)] + _query(m))}"


def del_url(m: tuple[str, str, str]) -> str:
    return f"{BASE}tax-del.cgi?{urlencode([('step', 2)] + _query(m))}"


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_ANCHOR = re.compile(r"key=(\d{6,10})>\s*\d{6,10}\s*</a>", re.I)
_MBP = re.compile(r"</table>\s*(\d{5}\s+\d{2}\s+\d{3})\s*</td>", re.I)
_TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_BR = re.compile(r"<br\s*/?>|<hr\s*/?>", re.I)
_NOT_FOUND = re.compile(r"No match found", re.I)


def _parts(cell: str) -> list[str]:
    return [" ".join(_html.unescape(re.sub(r"<[^>]+>", " ", p)).split()) for p in _BR.split(cell or "")]


def _num(s: Any) -> Optional[float]:
    t = re.sub(r"[^\d.\-]", "", str(s or ""))
    try:
        return round(float(t), 2) if t not in ("", ".", "-") else None
    except ValueError:
        return None


def _d(s: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(s or "").strip(), "%m/%d/%y").date()
    except ValueError:
        return None


def _flags(msgs: list[str]) -> list[str]:
    t = " ".join(msgs).upper()
    out = []
    if "SCHEDULED FOR TAX SALE" in t:
        out.append("scheduled_for_tax_sale")
    if "REDEEMED" in t or "PAID FROM TAX SALE" in t:
        out.append("redeemed_from_tax_sale")
    if re.search(r"\bSOLD\b", t):
        out.append("sold_at_tax_sale")
    if re.search(r"(^|\s)H HOLD\b", t):
        out.append("hold")
    return out


def parse_bills(page: str) -> Optional[list[dict]]:
    """The bills of a tax-inq / tax-del answer: [{notice_year, mbp, real, owner, delinquent (red),
    label, total, posted, paid, abated, flags}]; [] for "No match found"; None when the page is
    not an answer at all."""
    page = page or ""
    if _NOT_FOUND.search(page):
        return []
    if "Notice #" not in page:
        return None
    hits = list(_ANCHOR.finditer(page))
    # each bill row opens with <tr><td ...><center>...<table><tr><td><a key=...>: the row's own <tr>
    # is the one before the notice table's <tr>
    starts = [max(page.rfind("<tr", 0, page.rfind("<tr", 0, h.start())), 0) for h in hits]
    out = []
    for i, h in enumerate(hits):
        start = starts[i]
        seg = page[start:starts[i + 1] if i + 1 < len(hits) else len(page)]
        head = page[start:h.start()]
        mm = _MBP.search(seg)
        rest = seg[mm.end():] if mm else seg[seg.find("</table>") + 8:]
        tds = _TD.findall(rest)
        if len(tds) < 7:
            continue
        typ, owner_lot, _billing, msgs, assess, money, dates = (_parts(t) for t in tds[:7])
        notice = h.group(1)
        yy = int(notice[:2])
        label = next((p for p in reversed(assess) if p.lower().startswith("total")), "")
        nums = [x for x in (_num(p) for p in money) if x is not None]
        dts = [_d(x) for x in dates] + [None] * 4
        out.append({"notice_year": 2000 + yy if yy < 80 else 1900 + yy,
                    "mbp": " ".join(mm.group(1).split()) if mm else "",
                    "real": (typ[0] if typ else "").strip().lower().startswith("real"),
                    "owner": owner_lot[0] if owner_lot else None,
                    "delinquent": "ffa0a0" in head.lower(),
                    "label": label, "total": nums[-1] if nums else None,
                    "posted": dts[0], "paid": dts[1], "abated": dts[2],
                    "flags": _flags(msgs)})
    return out


def to_bills(year_rows: list[dict], del_rows: list[dict], key: str) -> list[sb.Bill]:
    """sb.Bill per levy year of the parcel `key` ('00143 31 031'): a year-file bill, with a bill
    of the same levy on the delinquent list marked late."""
    late = {r["notice_year"]: r for r in del_rows if r["mbp"] == key and r["real"]}
    out: dict[int, sb.Bill] = {}
    for r in year_rows:
        if r["mbp"] != key or not r["real"]:
            continue
        y = r["notice_year"]
        open_ = r["paid"] is None and r["abated"] is None and (
            r["delinquent"] or r["label"].lower() == "total due")
        b = sb.Bill(year=y, owed=(r["total"] or 0.0) if open_ else 0.0, paid_on=r["paid"],
                    late_flag=True if (r["delinquent"] or y in late) else None,
                    sold="sold_at_tax_sale" in r["flags"], owner=r["owner"], billed=r["total"],
                    flags=list(r["flags"]))
        out[y] = b
    for y, r in late.items():
        if y in out:
            continue
        open_ = r["paid"] is None and r["abated"] is None
        out[y] = sb.Bill(year=y, owed=(r["total"] or 0.0) if open_ else 0.0, paid_on=r["paid"],
                         late_flag=True, sold="sold_at_tax_sale" in r["flags"], owner=r["owner"],
                         billed=r["total"], flags=list(r["flags"]))
    return sorted(out.values(), key=lambda b: -b.year)


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "failures": 0, "dead": None, "current": None})
    except TypeError:
        return {"cache": {}, "failures": 0, "dead": None, "current": None}


async def _get(client: Any, url: str) -> list[dict]:
    run = _run(client)
    if run["dead"]:
        raise PortalDown(run["dead"])
    if url in run["cache"]:
        return run["cache"][url]
    try:
        rows = parse_bills(await client.get_text(url, timeout=TIMEOUT_S))
        if rows is None:
            raise ValueError("not an inquiry answer")
    except Exception as exc:  # noqa: BLE001
        run["failures"] += 1
        if run["failures"] >= PORTAL_MAX_FAILURES:
            run["dead"] = f"{run['failures']} failures in a row this run, last {type(exc).__name__}"
        raise
    run["failures"] = 0
    run["cache"][url] = rows
    return rows


def current_levy(today: date) -> int:
    """The levy the 'current' year file holds: the new roll posts in September."""
    return today.year if today.month >= 9 else today.year - 1


async def year_rows(client: Any, m: tuple[str, str, str], year: int, today: date) -> list[dict]:
    """The parcel's bills of levy `year` from its year file; when the file turns out to hold
    another levy (the roll moved), the file the answer points at is read once."""
    run = _run(client)
    cur = run["current"] or current_levy(today)
    off = cur - year
    if not 0 <= off < len(YEAR_FILES):
        return []
    rows = await _get(client, year_url(m, YEAR_FILES[off]))
    years = {r["notice_year"] for r in rows if r["real"]}
    if rows and year not in years and len(years) == 1:
        got = years.pop()
        run["current"] = cur - (year - got)       # the file at offset `off` holds levy `got`
        off2 = run["current"] - year
        if 0 <= off2 < len(YEAR_FILES) and off2 != off:
            rows = await _get(client, year_url(m, YEAR_FILES[off2]))
    return [r for r in rows if r["notice_year"] == year]


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "county", "searched", "decided_on", "tax_parcel", "delinquent_parcel", "claim_tms",
         "board_parcel", "latest_levy_year", "latest_delinquent_eligible_levy", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "under_500", "de_minimis", "not_yet_delinquent_due",
         "sold_at_tax_sale_years", "flags", "claimed_years", "bills_checked", "owner_match", "note",
         "error", "portal_health", "current_claim_basis", "history_from_levy", "history_complete",
         "late_levy_years", "chronic_claim")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


async def _parcel(client: Any, m: tuple[str, str, str], today: date) -> list[sb.Bill]:
    last = sb.latest_eligible(today)
    rows = await year_rows(client, m, last, today)
    rows += await year_rows(client, m, last - 1, today)
    dels = await _get(client, del_url(m))
    return to_bills(rows, dels, " ".join(m))


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    claimed = claimed_years(row)
    subs = subjects(row)
    blk = roll_block(row)
    ev: dict[str, Any] = {"county": "Florence", "claimed_years": claimed,
                          "claim_tms": (blk or {}).get("tms"), "board_parcel": row.get("parcel_id")}
    if not subs:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    searched, found = [], {}
    for m, role in subs:
        try:
            bills = await _parcel(client, m, today)
        except PortalDown as exc:
            return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200],
                                            searched=searched))
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed", searched=searched,
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        searched.append({"tms": "-".join(m), "role": role, "bills": len(bills)})
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
    ev["decided_on"] = "claim_tms" if role == "claim" else "board_parcel"
    ev["tax_parcel"] = "-".join(m)   # tax_binding.verified_checks_row compares it with the row's ids
    ev["url"] = del_url(m)
    ev["owner_match"] = tc.owner_category(row.get("owner_name"),
                                          [b.owner for b in bills[:2]] + [b.owner for b in bills if b.owed > 0])
    unbound = role == "board" and tc.parcel_resolved(row)
    verdict, ev = sb.judge(bills, claimed=claimed, today=today, ev=ev, unbound=unbound)
    return _res(verdict, ev)
