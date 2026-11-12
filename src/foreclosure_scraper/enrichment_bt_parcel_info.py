"""BT TaxPayer Portal "Parcel Information" panel — legal description + deed book/page/date +
account number + owner mailing address, the same 14 NC counties as enrichment_bt_appraisal_card.

WHY THIS EXISTS
    docs/gap_matrix flagged ~70 cells across these 14 counties as "sourced-not-built" against
    this same vendor for multi_year_delinquent_tax / repeat_tax_loss / rollback_exposure /
    tax_aging_surfaced / atty_tax_verified_confirmed / lt_tax_sale_overage. VERIFIED LIVE
    2026-10-16 (Warren County, a real board owner) that attribution is WRONG: this vendor is a
    CAMA/assessment system (owner, deed, legal description, current value) with no tax-payment
    or delinquency data anywhere, on the search results, the "Parcel Information" panel, or the
    PRC (Property Record Card -- the same PDF enrichment_bt_appraisal_card.py already parses:
    HEATED AREA / APPRAISED VALUE / beds-baths / SALES DATA only, confirmed by its own regexes).
    That half of the gap-list entries is not buildable here. See
    docs/path_to_100 memory for the full correction.

    What the SAME vendor genuinely has, correctly matching a DIFFERENT gap-list cluster
    (atty_legal_description, ~19 cells): the "Parcel Information" panel's Legal Description and
    Deed Information (date + book/page) fields, plus Account Number and the owner's mailing
    address -- none of which enrichment_bt_appraisal_card.py's PDF-only path reads.

THE FLOW (read live 2026-10-16, Warren County, ITSPublicWN)
    bt_appraisal_card.py's AppraisalCard.aspx needs the county's OWN short parcel id up front
    (id=<pid>/<year>) -- the same "ID FORMAT VARIES PER COUNTY" trap it already documents. This
    module avoids guessing that id: it SEARCHES for it first, by owner name, the same object the
    board already carries, then only trusts a result that ALSO matches the board's street
    address (never the search alone -- see _best_match).

    1. GET  {tenant}/                                            -- session cookie only
    2. POST {tenant}/BasicSearch/GetSearchOptionsPartial          {"searchType":"PropertyOwnerName"}
    3. POST {tenant}/basicsearch/GetSearchTablePartial/           {"PageSize":50,"ParcelSearch":
                                                                    "false","OwnerName":<query>}
    4. POST {tenant}/BasicSearch/GetSearchTableData                {"Page":1,"NumRows":50,
                                                                    "SortBy":"AccountName1",
                                                                    "SortOrder":"Asc",
                                                                    "Table":"BasicSearch"}
       -> JSON {total, numRecords, rows:[{id:"<parcel>/<year>", cell:[owner, co_owner, address,
          land, parcel, alt_text, tax_year, prc_link_html]}]}. A bare surname over-matches (SC:164
          rows for 'SMITH'); "SURNAME FIRST" (owner_last_first_middle) cuts a common surname down
          to the real candidates (SMITH JOHN: 1 row) without needing a separate structured
          last/first field -- there isn't one, OwnerName is a single fuzzy text field.
    5. POST {tenant}/BasicSearch/ViewParcel                        {"parcelNumber":<id>,
                                                                    "taxYear":<year>}
       -> HTML fieldsets (Parcel Number, Account Number, Owner Information, Tax Codes, Property
          Information, Township, Deed Information, Local Zoning, Property Values,
          AlternateParcelBasicSearchText, Legal Description), no search needed first -- it only
          needs the (parcel, year) pair step 4 already gave.

Free, public, no login, no CAPTCHA. Two requests per matched listing (search + detail), so it is
bounded and opt-in. Gate off with FORECLOSURE_BT_PARCEL_INFO=0.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Iterable, Optional

import httpx
import structlog

from .enrichment_bt_appraisal_card import TENANTS, _TENANTS_CI
from .models import Listing
from .name_normalize import is_entity, match_owner, owner_last_first_middle
from .verification.core import address_relation

log = structlog.get_logger()

BASE = "https://www.bttaxpayerportal.com"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MAX_LISTINGS = int(os.getenv("BT_PARCEL_INFO_MAX", "300"))
_CONCURRENCY = int(os.getenv("BT_PARCEL_INFO_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust (common-name
#: over-match, e.g. a bare surname on a big county) -- skipped rather than scanned.
MAX_CANDIDATES = 20

_LEGEND_RE = re.compile(r'<legend>\s*([^<]*?)\s*</legend>\s*<ol>(.*?)</ol>', re.S)
_LABELLED_RE = re.compile(
    r'<div class="indiv info-row-label">([^<]*?)\s*:</div>\s*'
    r'<div class="indiv info-row-text"[^>]*>([^<]*)</div>', re.S)
_LI_RE = re.compile(r'<li>\s*(.*?)\s*</li>', re.S)


def _tenant_base(county: Optional[str]) -> Optional[str]:
    code = _TENANTS_CI.get((county or "").strip().lower())
    return f"{BASE}/ITSPublic{code}" if code else None


def parse_search_rows(data: dict) -> list[dict]:
    """One dict per candidate row from GetSearchTableData's JSON. [] on anything unexpected --
    never raises on a malformed or empty response."""
    out = []
    for row in (data or {}).get("rows") or []:
        rid = str(row.get("id") or "")
        parcel, _, year = rid.partition("/")
        cell = row.get("cell") or []
        if not parcel or len(cell) < 7:
            continue
        out.append({
            "parcel_number": parcel,
            "tax_year": year or None,
            "owner_name": str(cell[0] or "").strip(),
            "co_owner": str(cell[1] or "").strip(),
            "property_address": str(cell[2] or "").strip(),
        })
    return out


def _best_match(li: Listing, candidates: list[dict]) -> Optional[dict]:
    """The one candidate that matches BOTH the board's street address (exact house number +
    street name, verification.core.address_relation) AND its owner name (name_normalize.
    match_owner) -- never a guess between several, never on one signal alone. None when zero or
    more than one candidate clears both bars."""
    hits = []
    for cand in candidates:
        if address_relation(li.street_address, cand["property_address"]) != "match":
            continue
        owner_hit = match_owner(li.owner_name, cand["owner_name"]) or \
            match_owner(li.owner_name, cand["co_owner"])
        if not owner_hit:
            continue
        hits.append(cand)
    if len(hits) == 1:
        return hits[0]
    return None


def parse_view_parcel(html: str) -> dict:
    """{legal_description, deed_date, deed_book, deed_page, account_number, mailing_address,
    market_value, assessed_value} off one ViewParcel response. Only keys actually found; never
    invents a value for a blank fieldset."""
    out: dict = {}
    sections = {m.group(1).strip(): m.group(2) for m in _LEGEND_RE.finditer(html or "")}

    def lis(name: str) -> list[str]:
        body = sections.get(name, "")
        return [t for t in (m.group(1).strip() for m in _LI_RE.finditer(body)) if t]

    def labelled(name: str) -> dict:
        return {k.strip(): v.strip() for k, v in _LABELLED_RE.findall(sections.get(name, ""))}

    acct = lis("Account Number")
    if acct:
        out["account_number"] = acct[0]
    legal = lis("Legal Description")
    if legal:
        out["legal_description"] = legal[0].replace("&amp;", "&")
    owner_lines = lis("Owner Information")
    if len(owner_lines) >= 2:
        out["mailing_address"] = ", ".join(owner_lines[1:])

    deed = labelled("Deed Information")
    if deed.get("Deed Date"):
        out["deed_date"] = deed["Deed Date"]
    bp = deed.get("Deed Book/Page", "")
    m = re.match(r"\s*(\S+)\s*/\s*(\S+)\s*$", bp)
    if m and m.group(1) not in ("0000", "00000") and m.group(2) not in ("0000", "00000"):
        out["deed_book"], out["deed_page"] = m.group(1), m.group(2)

    values = labelled("Property Values")
    # "Deferred" (2026-10-20, enrichment_harnett_rollback_exposure.py) -- the present-use/ag
    # deferral value sitting in the SAME fieldset as Market/Assessed, on the SAME ITSPublic
    # BasicSearch product this function already parses for every TENANTS county. Never checked
    # before this change (the 2026-10-16 Warren County investigation was looking for tax-PAYMENT
    # data, which this fieldset genuinely has none of -- a different question from whether it
    # carries a present-use VALUE field, which it does). Extracted here, not in a county-specific
    # module, so every TENANTS county benefits the same way the moment something reads it.
    for src, dst in (("Market", "market_value"), ("Assessed", "assessed_value"),
                     ("Deferred", "deferred_value")):
        v = re.sub(r"[^\d.]", "", values.get(src, ""))
        if v:
            try:
                out[dst] = float(v)
            except ValueError:
                pass
    return out


async def _search_owner(c: httpx.AsyncClient, tenant_base: str, query: str) -> list[dict]:
    hdr = {"X-Requested-With": "XMLHttpRequest"}
    await c.post(f"{tenant_base}/BasicSearch/GetSearchOptionsPartial",
                 json={"searchType": "PropertyOwnerName"}, headers=hdr)
    await c.post(f"{tenant_base}/basicsearch/GetSearchTablePartial/",
                 json={"PageSize": 50, "ParcelSearch": "false", "OwnerName": query}, headers=hdr)
    r = await c.post(f"{tenant_base}/BasicSearch/GetSearchTableData",
                      json={"Page": 1, "NumRows": 50, "SortBy": "AccountName1",
                            "SortOrder": "Asc", "Table": "BasicSearch"}, headers=hdr)
    r.raise_for_status()
    return parse_search_rows(r.json())


async def _view_parcel(c: httpx.AsyncClient, tenant_base: str, parcel: str, year: str) -> dict:
    r = await c.post(f"{tenant_base}/BasicSearch/ViewParcel",
                      json={"parcelNumber": parcel, "taxYear": year},
                      headers={"X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    return parse_view_parcel(r.text)


def _search_query(li: Listing) -> Optional[str]:
    """'SURNAME FIRST' -- narrow enough that a common surname alone (164 SC rows for 'SMITH' on
    Warren, measured live) doesn't drown the real candidate (1 row for 'SMITH JOHN')."""
    parts = owner_last_first_middle(li.owner_name)
    if not parts:
        return None
    last, first, _mi = parts
    return f"{last} {first}".strip()


def _eligible(li: Listing) -> bool:
    """Never re-targets a CONFIRMED match (a real result never goes stale -- a recorded deed
    doesn't change). A negative-result "status" marker (no_candidates / too_many_candidates /
    no_confident_match) is NOT a reason to exclude here: whether it's due for a retry is
    enrichment_tail_extras.bt_parcel_info_targets's own _due() check, by age -- gating it here
    too would make that age check dead code (every retry candidate already carries a block)."""
    blk = li.raw.get("bt_parcel_info") if isinstance(li.raw, dict) else None
    already_confirmed = isinstance(blk, dict) and "status" not in blk
    return bool(
        li.state == "NC" and _tenant_base(li.county) and li.owner_name
        and not is_entity(li.owner_name) and (li.street_address or "").strip()
        and not already_confirmed
    )


async def enrich_bt_parcel_info(listings: Iterable[Listing]) -> dict:
    """Legal description + deed book/page/date + account number + owner mailing address for the
    14 BT TaxPayer Portal counties, matched by owner name AND street address (never one alone).
    Writes raw['bt_parcel_info'].
    """
    targets = [li for li in listings if _eligible(li)]
    stats = {"eligible": len(targets), "searched": 0, "no_candidates": 0,
             "too_many_candidates": 0, "no_confident_match": 0, "matched": 0,
             "errors": 0, "filled_legal_description": 0, "filled_deed_ref": 0}
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        def _no_match(li: Listing, status: str) -> None:
            # Recorded even on a miss (status, not a result) so the next run's recheck cadence
            # (enrichment_tail_extras.bt_parcel_info_targets) skips this listing for
            # BT_RECHECK_DAYS instead of re-searching it from scratch every run -- the same
            # convention enrichment_bt_appraisal_card.py uses for its own "no_card" case.
            if not isinstance(li.raw, dict):
                li.raw = {}
            if not isinstance(li.raw.get("bt_parcel_info"), dict):
                li.raw["bt_parcel_info"] = {"status": status}

        async def one(li: Listing) -> None:
            query = _search_query(li)
            if not query:
                return
            tenant_base = _tenant_base(li.county)
            async with sem:
                try:
                    candidates = await _search_owner(c, tenant_base, query)
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
            stats["searched"] += 1
            if not candidates:
                stats["no_candidates"] += 1
                _no_match(li, "no_candidates")
                return
            if len(candidates) >= MAX_CANDIDATES:
                stats["too_many_candidates"] += 1
                _no_match(li, "too_many_candidates")
                return
            match = _best_match(li, candidates)
            if not match or not match["tax_year"]:
                stats["no_confident_match"] += 1
                _no_match(li, "no_confident_match")
                return
            async with sem:
                try:
                    detail = await _view_parcel(c, tenant_base, match["parcel_number"],
                                                match["tax_year"])
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
            if not detail:
                return
            stats["matched"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["bt_parcel_info"] = {
                **detail,
                "parcel_number": match["parcel_number"],
                "tax_year": match["tax_year"],
                "source_url": f"{tenant_base}/",
            }
            if detail.get("legal_description"):
                stats["filled_legal_description"] += 1
            if detail.get("deed_book"):
                stats["filled_deed_ref"] += 1

        await asyncio.gather(*(one(li) for li in targets))
    log.info("bt_parcel_info.done", **stats)
    return stats
