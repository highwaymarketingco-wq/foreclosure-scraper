"""tax_lien, Perquimans County NC: does the county's own tax site still show a balance on the
account the Albemarle Observer's delinquent list named?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_ptscloud, tax_lien_qpaybill,
tax_lien_pickens and tax_lien_itspublic: same SIGNAL, same GOVERNS, same verdict meanings, one
tax_lien ledger. Top-80 build list 2026-10-09, item 74 (lt_tax_lien), the Perquimans cell.

WHY. counties_nc.albemarle_observer_tax_lists turns the newspaper's yearly delinquent-property-tax
list into tax_lien leads (Perquimans 1,493 rows on the 2026-10-07 board, 1,544 with the lines of the
other counties' lists). A newspaper list is a snapshot of the county's June bill run; nothing
rechecks it, and a bill paid in July is still a lead in October. The row carries the county's own
map/parcel string ("2-D070-0022-BF") as parcel_id.

THE SOURCE. perqcotax.com, the county's public tax search (no login, no CAPTCHA; the only gate is a
liability disclaimer printed on the page, no click). One plain GET:

    GET /search?for=<map string>
        -> HTML, one block per tax ACCOUNT on that map: "Tax Account Number <n>", the Owner cell
           (<BR>-separated lines: the map string, the owner of record, the owner's MAILING lines),
           "Taxes Due $<total>", and a hidden payment form whose cde-PaymType-1 / cde-PaymAmou-2 fields
           break the total into its parts (PTax county tax, PDMV vehicle tax, HTax / HDMV / HMFee the
           City of Hertford, WTax / WDMV / WMFee Winfall, HDept, CDFee, PDFee, CPerry, Gates).
The "only show results with taxes owed" filter is NOT used: a paid account must show $0.00, not
vanish. Several accounts share a map string (owners, heirs, a vehicle account); the row's account is
the one whose owner of record matches the row's owner.

VERDICTS (a levy-year Y bill is late once unpaid on January 6 of Y+1, G.S. 105-360):
  confirmed    an account on the row's map with the row's owner (same, or a partial name match) shows
               property tax due (county + city tax parts) today. Evidence: the amount due now, the
               amount of other fees (vehicle tax, mowing, drainage), the number of accounts.
  stale        the matching account(s) show no property tax due: the bill the list named has been
               paid since the list (its date is in the evidence). Governs removes tax_lien:property_tax.
  unconfirmed  no parcel on the row / the map is not on the site / accounts on the map but none under
               the row's owner (the parcel changed hands: owner_differs) / only vehicle tax or fees
               due (no_property_tax_part) / the site did not answer (fetch_failed, retried in 6 hours).
  refuted      never: this site shows what is owed now, not what the list's year held.

Evidence is a whitelist (public ledger): no owner names, no mailing lines, no account numbers.
"""
from __future__ import annotations

import html as _html
import re
import weakref
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 7
SOURCE = "perqcotax.com (Perquimans County tax search)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "unreadable_answer")

COUNTY = "perquimans"
BASE = "https://perqcotax.com"
SEARCH_URL = BASE + "/search?for={q}"
BLOCK_KEY = "albemarle_observer_tax_list"
#: the payment form's parts that are PROPERTY tax (county and the two cities); the rest are vehicle
#: tax (PDMV, HDMV, WDMV), mowing fees (HMFee, WMFee), health, drainage and road fees
PROPERTY_PARTS = ("PTax", "HTax", "WTax")
_NAME = __name__.rsplit(".", 1)[-1]

_ACCOUNT_SPLIT = re.compile(r"Tax\s+Account\s+Number", re.I)
_ACCOUNT_NO = re.compile(r"<TD[^>]*>\s*(\d{3,10})\s*</TD>", re.I)
_OWNER_LINE = re.compile(r"^\s*([^<\n][^<]*?)\s*<BR>", re.I | re.M)
_DUE = re.compile(r"Taxes\s+Due\s+\$\s*([\d,]+\.\d{2})", re.I)
_TYPES = re.compile(r"NAME='cde-PaymType-\d+'\s+VALUE='([^']*)'", re.I)
_AMOUNTS = re.compile(r"NAME='cde-PaymAmou-\d+'\s+VALUE='([^']*)'", re.I)


def _block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(BLOCK_KEY)
    return b if isinstance(b, dict) and str(b.get("county") or "").strip().lower() == COUNTY else None


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    if str(tc.g(row, "county") or "").strip().lower() != COUNTY:
        return False
    return tc.claims_property_tax(row, _block(row) is not None)


def map_of(row: Any) -> Optional[str]:
    """The county's map/parcel string the list printed (the board parcel_id), else the block's."""
    for v in (tc.g(row, "parcel_id"), (_block(row) or {}).get("parcel")):
        s = str(v or "").strip()
        if tc.alnum(s):
            return s
    return None


# ---------------------------------------------------------------------------
# parsing (pure, tested on hand-written HTML)
# ---------------------------------------------------------------------------

def _money(s: str) -> float:
    try:
        return round(float(s.replace(",", "")), 2)
    except ValueError:
        return 0.0


def parse_accounts(page: str) -> list[dict]:
    """[{account, map, owner, due, property_due, other_due}] from a search-results page. An account
    block without a 'Taxes Due' figure is skipped."""
    out: list[dict] = []
    for chunk in _ACCOUNT_SPLIT.split(page or "")[1:]:
        due_m = _DUE.search(chunk)
        if not due_m:
            continue
        no = _ACCOUNT_NO.search(chunk)
        owner_cell = chunk.split("Owner", 1)[1] if "Owner" in chunk else chunk
        owner_cell = owner_cell.split("Taxes Due", 1)[0]
        lines = [_html.unescape(m.group(1)).strip() for m in _OWNER_LINE.finditer(owner_cell)]
        lines = [x for x in lines if x]
        types = (_TYPES.search(chunk).group(1).split("|")) if _TYPES.search(chunk) else []
        amounts = (_AMOUNTS.search(chunk).group(1).split("|")) if _AMOUNTS.search(chunk) else []
        parts = {t: _money(a) for t, a in zip(types, amounts)}
        due = _money(due_m.group(1))
        prop = round(sum(parts.get(k, 0.0) for k in PROPERTY_PARTS), 2) if parts else due
        out.append({"account": no.group(1) if no else None, "map": lines[0] if lines else None,
                    "owner": lines[1].rstrip(", ") if len(lines) > 1 else None, "due": due,
                    "property_due": prop, "other_due": round(max(due - prop, 0.0), 2)})
    return out


# ---------------------------------------------------------------------------
# fetch (one search per map per sweep run)
# ---------------------------------------------------------------------------

_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


async def _search(client: Any, map_str: str) -> list[dict]:
    try:
        cache = _RUNS.setdefault(client, {})
    except TypeError:
        cache = {}
    k = tc.alnum(map_str)
    if k not in cache:
        cache[k] = parse_accounts(await client.get_text(SEARCH_URL.format(q=quote(map_str, safe="")), timeout=40))
    return cache[k]


_KEYS = ("reason", "url", "map", "accounts_on_map", "accounts_matched", "owner_match", "amount_due",
         "property_tax_due", "other_fees_due", "list_post_date", "list_year", "list_total_due",
         "checked_on", "note", "error")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    blk = _block(row) or {}
    m = map_of(row)
    ev: dict[str, Any] = {"map": m, "checked_on": today.isoformat(), "list_post_date": blk.get("post_date"),
                          "list_year": blk.get("list_year"), "list_total_due": blk.get("total_due")}
    if not m:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    ev["url"] = SEARCH_URL.format(q=quote(m, safe=""))
    try:
        accounts = await _search(client, m)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return _res("unconfirmed", dict(ev, reason="fetch_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}"))
    on_map = [a for a in accounts if tc.alnum(a.get("map")) == tc.alnum(m)]
    ev["accounts_on_map"] = len(on_map)
    if not on_map:
        return _res("unconfirmed", dict(ev, reason="map_not_on_site"))
    owner = tc.g(row, "owner_name") or blk.get("owner")
    mine = []
    cats = []
    for a in on_map:
        cat = tc.owner_category(owner, [a.get("owner")])
        cats.append(cat)
        if cat in ("same", "partial"):
            mine.append((a, cat))
    ev["owner_match"] = "same" if any(c == "same" for _, c in mine) else (
        "partial" if mine else (tc.owner_category(owner, [a.get("owner") for a in on_map]) or "unknown"))
    if not mine:
        return _res("unconfirmed", dict(ev, reason="owner_differs"))
    ev["accounts_matched"] = len(mine)
    prop = round(sum(a["property_due"] for a, _ in mine), 2)
    other = round(sum(a["other_due"] for a, _ in mine), 2)
    ev.update(amount_due=round(prop + other, 2), property_tax_due=prop, other_fees_due=other)
    if prop > 0:
        return _res("confirmed", ev)
    if other > 0:
        return _res("unconfirmed", dict(ev, reason="no_property_tax_part"))
    return _res("stale", dict(ev, reason="paid_since_list",
                              note="the county shows no property tax due on the account the list named"))
