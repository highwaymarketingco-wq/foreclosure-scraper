"""foreclosure_sale_list, NC + SC: is the sale the row was built from still on the trustee's (or
tax-foreclosure attorney's) own public sale list, for this property, or did the firm take it off
before the sale date (cancelled, reinstated, postponed off the calendar)?

THE CLAIMS. Law-firm scrapers turn each firm's public sale calendar into a foreclosure_sale (or a
tax-foreclosure tax_sale) lead with the court case number, the sale date and the address. The row
is carried after the firm drops the sale, so a cancelled sale keeps scoring until its date passes.
Measured on the 2026-10-08 pre_publish checkpoint sample (30 NC + 30 SC foreclosure_sale rows, 30
NC tax_sale rows): every row of a firm this module reads was still listed with the same date but
one (a Shapiro & Ingle sale set for 2026-11-17, gone from the firm's list on 2026-10-08).

THE SOURCES (each the firm's own public page, read the way the production scraper reads it, with
the scraper's own parser; one list per firm per sweep process, cached):
    law_firms.hutchens              sales.hutchenslawfirm.com NC / SC sales lists (one page each,
                                    "page 1 of 1"; the plain GET only, never the scraper's browser
                                    fallback)
    law_firms.shapiro_ingle_powerbi the firm's public Power BI report (JSON querydata)
    law_firms.bell_carrington       the firm's published Google Sheet (CSV)
    law_firms.rogers_townsend       the firm's SC listings PDF
    law_firms.kania                 the tax-foreclosure listings JSON (also national.nc_upset_bids
                                    rows whose source_url is that page)
    counties_sc.terry_howe_flc      Terry Howe & Associates' free unauthenticated WordPress REST
                                    catalog (terryhowe.com/wp-json/wp/v2/auctions), the SC
                                    Forfeited Land Commission auctioneer for Chester, Fairfield,
                                    Laurens and Spartanburg today -- the producer's own `.fetch()`,
                                    re-used directly, no new parsing code. Added round 78
                                    (2026-11-20): a genuine "verifier narrower than producer" gap
                                    -- the module is live, wired in main.py's DATELESS_OK_SOURCES,
                                    and gap_matrix.py's own fresh run that day carried Chester (28
                                    rows) and Fairfield (7) as `built-not-verified` before this
                                    entry existed, with nothing in this file or elsewhere ever
                                    having recognized the source. Live-checked 2026-11-20: of its
                                    54 current board rows, 30 carry a usable house-numbered street
                                    address (e.g. "817 Saxon Ave") this file's existing address
                                    match already handles with zero new matching code; the other
                                    24 are "Off <street>" locator parcels or bundle rows with
                                    neither a case number nor a numbered address and correctly
                                    stay out of `applies()`'s scope, same as every other firm here.
NOT read (walls, recorded in docs/walls_register.json): Brock & Scott (answers 'Forbidden' to a
plain client; its scraper falls back to a stealth browser), Zacchaeus (stealth browser only), the
ncnotices.com / scpublicnotices.com notice bodies (cards nc_notice_body, sc_notice_body), and the
special-proceeding file itself in NC eCourts (card nc_sp: hearing, sale, report of sale, upset
bids). Aggregators (foreclosure.com, Zillow, Realtor) are not a primary source. counties_sc.sc_flc
(the statewide SC FLC doc scraper, Anderson's own producer) is NOT added here even though it is
the same claim shape: its `.fetch()` is a multi-page OCR run against a shared, quota-limited OCR
pool (600s timeout) and re-running it from inside a verification sweep risks starving that pool
for the production scrape -- a bigger, riskier lift than reusing a single free JSON endpoint,
not this round's fix.

MATCHING. By the court case number (letters and digits only), else, for a row with no case number,
by a house-numbered address that core.address_relation calls a match, in the same county.

VERDICTS (core.py's meanings):
  confirmed    the case is on the firm's list today. Evidence: the sale date now (a postponed sale
               shows its new date), the row's date, the bid text when the list carries one.
  stale        the case is NOT on a healthy list (at least MIN_LIST_ROWS rows parsed) and the
               row's sale date is today or later: the firm took it off before the sale
               (removed_before_sale). The sale is not going ahead as the row says.
  refuted      the case is on the list but for another property: the row has a numbered address
               and the firm's address for that case is a different house (case_address_conflict).
  unconfirmed  not listed and the sale date has passed (sale_held_or_cancelled: the list cannot
               tell a held sale from a cancelled one; the scorer's own date rule ends a passed
               sale), not listed with no sale date on the row, an unreadable or empty list
               (list_unreadable / list_empty, retried in 6 hours).

GOVERNS (per record): a foreclosure claim ("foreclosure_sale", "upset_bid", "court_sale"), a tax
foreclosure claim ("tax_sale", "upset_bid"). A sale taken off the calendar opens no upset-bid
window either.

PRIVACY: evidence holds the firm, the case number, dates, the match basis and the address
relation category; never a name. ROW_SUMMARY_EXCLUDE drops owner_name.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from ..core import VerificationResult, address_relation, case_id, result

SIGNAL = "foreclosure_sale_list"
VERSION = "v1"
TTL_DAYS = 7           # firms re-post their calendars weekly; a sale moves within days
RETRY_DAYS = 2
SOURCE = "trustee / tax-foreclosure attorney public sale lists"
GOVERNS = ("foreclosure_sale", "upset_bid", "court_sale", "tax_sale")
ROW_SUMMARY_EXCLUDE = ("owner_name",)
IDENTITY = "case"
TRANSIENT_REASONS = ("list_unreadable", "list_empty")
MIN_LIST_ROWS = 5

KANIA_PAGE = "kanialawfirm.com/tax-foreclosures"
#: board source slug -> (list key, claim kind)
FIRMS: dict[str, tuple[str, str]] = {
    "law_firms.hutchens": ("hutchens_{st}", "foreclosure"),
    "law_firms.shapiro_ingle_powerbi": ("shapiro", "foreclosure"),
    "law_firms.bell_carrington": ("bell_carrington", "foreclosure"),
    "law_firms.rogers_townsend": ("rogers_townsend", "foreclosure"),
    "law_firms.kania": ("kania", "tax"),
    "counties_sc.terry_howe_flc": ("terry_howe_flc", "tax"),
}

#: firm keys whose OWN catalog never carries a case/docket number (an FLC auction has no court
#: case) -- a row's board-level case_number for one of these is cross-source enrichment noise
#: (e.g. a dedupe fingerprint like "trulia-11805212_ZPID", live-confirmed on real Spartanburg
#: counties_sc.terry_howe_flc board rows 2026-11-20), never this firm's own identifier, so find()
#: below must not let it block its address fallback the way a REAL non-matching case number
#: correctly would for every other firm here.
NO_CASE_FIRMS = frozenset({"terry_howe_flc"})
_NAME = __name__.rsplit(".", 1)[-1]

#: list key -> async () -> list of Listing (the firm's current list); tests replace entries
PROVIDERS: dict[str, Callable[[], Awaitable[list]]] = {}
_LISTS: dict[str, Any] = {}


def reset_caches() -> None:
    _LISTS.clear()


async def _hutchens(state: str) -> list:
    from ...http_client import get_text
    from ...scrapers.law_firms import hutchens as h
    url = {s: u for u, s in h.URLS}[state]
    html = await get_text(url, timeout=120.0)
    _, kept = h.Hutchens()._parse_grid(html or "", url, state)
    return list(kept)


async def _scraper_list(module: str, cls: str) -> list:
    import importlib
    m = importlib.import_module(f"...scrapers.law_firms.{module}", __package__)
    return list(await getattr(m, cls)().fetch())


async def _terry_howe_flc() -> list:
    """The same free WordPress REST catalog counties_sc.terry_howe_flc.TerryHoweFLC already
    fetches for production -- one call returns every SC county's current FLC auction, not a
    per-firm page the way the law_firms.* providers above are, so this lives in counties_sc, not
    law_firms (_scraper_list's import path is hardcoded to the latter)."""
    from ...scrapers.counties_sc.terry_howe_flc import TerryHoweFLC
    return list(await TerryHoweFLC().fetch())


def _default_providers() -> dict:
    return {
        "hutchens_NC": lambda: _hutchens("NC"),
        "hutchens_SC": lambda: _hutchens("SC"),
        "shapiro": lambda: _scraper_list("shapiro_ingle_powerbi", "ShapiroInglePowerBI"),
        "bell_carrington": lambda: _scraper_list("bell_carrington", "BellCarrington"),
        "rogers_townsend": lambda: _scraper_list("rogers_townsend", "RogersTownsend"),
        "kania": lambda: _scraper_list("kania", "KaniaLawFirm"),
        "terry_howe_flc": _terry_howe_flc,
    }


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def firm_of(row: Any) -> Optional[tuple[str, str]]:
    """(list key, claim kind) of the row's firm, or None."""
    src = str(_get(row, "source") or "")
    st = str(_get(row, "state") or "").strip().upper()
    if src == "national.nc_upset_bids" and KANIA_PAGE in str(_get(row, "source_url") or ""):
        return "kania", "tax"
    f = FIRMS.get(src)
    if not f:
        return None
    return f[0].format(st=st), f[1]


def ncase(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def _numbered(addr: Any) -> bool:
    return bool(re.match(r"\s*\d+\s+\S", str(addr or "")))


def applies(row: dict) -> bool:
    if str(_get(row, "state") or "").strip().upper() not in ("NC", "SC"):
        return False
    f = firm_of(row)
    if f is None:
        return False
    return bool(ncase(_get(row, "case_number")) or _numbered(_get(row, "street_address")))


def case_identity(row: Any) -> Optional[str]:
    f = firm_of(row)
    if f is None:
        return None
    c = ncase(_get(row, "case_number"))
    if c:
        return case_id("fsale", f[0], c)
    a = str(_get(row, "street_address") or "")
    return case_id("fsale", f[0], str(_get(row, "county") or ""), a) if _numbered(a) else None


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


async def current_list(key: str) -> list:
    if key in _LISTS:
        v = _LISTS[key]
        if isinstance(v, Exception):
            raise v
        return v
    prov = PROVIDERS.get(key) or _default_providers().get(key)
    if prov is None:
        raise LookupError(f"no list provider for {key}")
    try:
        v = list(await prov())
    except Exception as exc:  # noqa: BLE001 - remembered for this process: one failure per firm
        _LISTS[key] = exc
        raise
    _LISTS[key] = v
    return v


def find(row: Any, listings: list) -> tuple[Optional[Any], str]:
    """The firm's listing of the row's sale. One case can list several parcels (a tax
    foreclosure of a person's lots, one row each): the listing of the case whose address is the
    row's own wins, then one with no conflicting address, then the first.

    A row whose firm is in NO_CASE_FIRMS always goes straight to the address path below: its
    board-level case_number (when it has one at all) is enrichment noise from a different
    source, never this firm's own docket -- matching it against a catalog that has no case
    numbers of its own would only ever miss, masking a real address match."""
    f = firm_of(row)
    c = "" if f and f[0] in NO_CASE_FIRMS else ncase(_get(row, "case_number"))
    if c:
        same = [li for li in listings if ncase(_get(li, "case_number")) == c]
        if not same:
            return None, ""
        a = _get(row, "street_address")
        rels = [address_relation(a, _get(li, "street_address")) for li in same]
        for want in ("match", "unknown"):
            for li, rel in zip(same, rels):
                if rel == want:
                    return li, "case_number"
        return same[0], "case_number"
    a = _get(row, "street_address")
    co = str(_get(row, "county") or "").strip().lower()
    for li in listings:
        if str(_get(li, "county") or "").strip().lower() == co and \
                address_relation(a, _get(li, "street_address")) == "match":
            return li, "address"
    return None, ""


def governs_for(record: dict) -> tuple[str, ...]:
    kind = ((record or {}).get("evidence") or {}).get("claim_kind")
    if kind == "tax":
        return ("tax_sale", "upset_bid")
    if kind == "foreclosure":
        return ("foreclosure_sale", "upset_bid", "court_sale")
    return GOVERNS


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client=None, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.utcnow().date()
    f = firm_of(row)
    if f is None:
        return _res("unconfirmed", {"reason": "no_firm"})
    key, kind = f
    sale_row = _day(_get(row, "sale_date"))
    ev: dict = {"firm": key, "claim_kind": kind, "case_number": _get(row, "case_number") or None,
                "sale_date_row": sale_row.isoformat() if sale_row else None}
    try:
        listings = await current_list(key)
    except Exception as exc:  # noqa: BLE001
        ev.update(reason="list_unreadable", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    ev["list_rows"] = len(listings)
    if len(listings) < MIN_LIST_ROWS:
        ev["reason"] = "list_empty"
        return _res("unconfirmed", ev)
    li, basis = find(row, listings)
    if li is not None:
        sale_now = _day(_get(li, "sale_date"))
        rel = address_relation(_get(row, "street_address"), _get(li, "street_address"))
        ev.update(match_basis=basis, sale_date_now=sale_now.isoformat() if sale_now else None,
                  address_relation=rel)
        if basis == "case_number" and rel == "conflict" and _numbered(_get(row, "street_address")) \
                and _numbered(_get(li, "street_address")):
            ev["reason"] = "case_address_conflict"
            return _res("refuted", ev)
        ev["reason"] = "listed"
        if sale_row and sale_now and sale_now != sale_row:
            ev["reason"] = "listed_new_date"
        return _res("confirmed", ev)
    if sale_row is None:
        ev["reason"] = "not_listed_no_date"
        return _res("unconfirmed", ev)
    if sale_row >= today:
        ev["reason"] = "removed_before_sale"
        return _res("stale", ev)
    ev["reason"] = "sale_held_or_cancelled"
    return _res("unconfirmed", ev)
