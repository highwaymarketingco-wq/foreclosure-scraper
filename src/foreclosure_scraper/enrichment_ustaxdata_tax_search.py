"""ustaxdata.com per-parcel tax-bill history — Robeson County, NC.

WHY THIS EXISTS
    docs/gap_matrix: `sqft, repeat_tax_loss, atty_tax_verified_confirmed, tax_aging_surfaced,
    rollback_exposure, beds_baths, lt_tax_sale, lt_tax_sale_overage, multi_year_delinquent_tax`
    sat sourced-not-built across 13 NC counties (Anson, Yadkin, Duplin, Graham, Caswell, Person,
    Clay, Carteret, Swain, Jones, Alleghany, Warren, Scotland) that use the `ustaxdata.com`
    per-parcel tax vendor. A prior audit pass (docs/audit_2026-10-09/top80_checks.md) opened
    Robeson and noted "no list" (no county-wide export, parcel lookup only) and did not probe
    Alexander/Rockingham (same vendor, assumed) any further. This module is that probe, finished:
    it fetches the one real signal the vendor gives for free — a multi-year, per-levy-year
    paid/unpaid/partial status table, the county's own account number and owner-of-record name,
    and the taxable (assessed) value — keyed by parcel number, no CAPTCHA/login/WAF.

    `sqft` / `beds_baths` are NOT in this vendor's data: every row's "Asset Description" cell
    reads the literal placeholder "> CONTACT COUNTY FOR" on every year, every county tried
    (confirmed live 2026-10-16, not a fetch error) — the vendor simply doesn't publish a
    property characteristics card the way BT TaxPayer Portal does (enrichment_bt_appraisal_
    card.py). Those two columns are still a real gap here; this module does not claim them.

VERIFIED LIVE 2026-10-16, Robeson parcel 021903073 (423 Turkey Branch Rd, the board's own
`parcel_id`, unchanged): 13 Records Found, years 2014-2026, every one `bill_paid.gif`, account
1004106001, owner "BALDWIN RODERICK LEVERNE", taxable value $74,700-$94,600 across the span.
The status-icon legend is printed on the search form itself: bill_open.gif = unpaid,
bill_paid.gif = paid, bill_partial.gif = partially paid.

THE SUMMARY TABLE HAS NO DOLLAR AMOUNT — a real gap, not an oversight it shares with sqft/
beds_baths. Its own "Asset Description" column is the same "> CONTACT COUNTY FOR" placeholder;
the dollar figure lives one click deeper, on the "View Tax Bill" page (taxbill.cfm?ownerID=
<account>&billNo=<bill_no>&TaxYear=<year>, linked from every row). Verified live on that same
bill (2026, paid): "TOTAL AMOUNT OWED: $ 0.00" (correct — it's paid) next to a separate
"Amount Taxed: $ 974.73" (the year's gross levy). Fetching this is the only way a `balance`
here can be real rather than invented, so it is read, but ONLY for a bill this module's own
summary read already flagged unpaid/partial — a clean parcel costs one request, a delinquent
one costs 1 + (its bad years), never the full 13-year history. Without this second hop,
raw['ustaxdata_delinquent_tax'] would carry years_unpaid but no balance, and
enrichment_tax_owed.py's generic Pass B (which gates on a _GENERIC_KEYS dollar amount, not a
years list) would never fire — tax_owed / tax_aging_surfaced / two_year_delinquent would
silently stay empty even on a genuinely delinquent parcel. Confirmed by writing the test for
it first (tests/test_ustaxdata_tax_search.py) and watching it fail without this.

ALEXANDER AND ROCKINGHAM ARE THE SAME VENDOR, NOT WIRED: the board's own parcel_id search
returns "0 Records" for both (confirmed live, not a fetch error — the page renders a normal
0-match results page). A name/business-name search on a real board row for each county found
the vendor's REAL key: Alexander account.cfm?parcelID=0002451 (board parcel_id 3736984870 for
the same row), Rockingham parcelID=152358 (board parcel_id 792800687243). Neither resembles the
board's GIS-style parcel_id — the same "ID FORMAT VARIES PER COUNTY" trap enrichment_bt_
appraisal_card.py hit on Moore/Anson/Caswell/Duplin/Person/Scotland/Warren/Yadkin. There is no
parcel_id -> county-account crosswalk in this project to translate one into the other, so
wiring them would silently query the wrong (or no) account on every row. See REJECTED_TENANTS;
don't re-add either without building that crosswalk first. The other 10 counties from the
gap-list cluster were never probed at all (unknown whether they share this vendor or this ID
mismatch) and are not claimed here either.

Free, public, no login, no CAPTCHA. One request per parcel, so it is bounded and opt-in.
Gate off with FORECLOSURE_USTAXDATA=0.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import urlencode

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

#: county -> search endpoint. Confirmed live 2026-10-16: the board's own parcel_id, passed
#: as-is to `parcelNum`, matches this vendor's account directly. Add a county here ONLY after
#: confirming the same (a live parcelNum search on a real board parcel_id returns that row's
#: own account, not "0 Records" — see the module docstring for how Alexander/Rockingham failed
#: this check).
TENANTS: dict[str, str] = {
    "Robeson": "https://www.ustaxdata.com/nc/robeson/Robesontaxlist.cfm",
}

#: Same vendor, probed and REJECTED — kept so nobody re-adds them without a parcel_id ->
#: county-account crosswalk (module docstring).
REJECTED_TENANTS = {
    "Alexander": "alexander.ustaxdata.com — board parcel_id 3736984870 is 0 Records; the "
                 "real account (found via lastName=RHYNE&firstName=DENNIS) is parcelID="
                 "0002451 / account 0202921, unrelated to the board's id",
    "Rockingham": "ustaxdata.com/nc/rockingham — board parcel_id 792800687243 is 0 Records; "
                  "the real account (found via businessName=Bms investment) is parcelID="
                  "152358 / account 1326686, unrelated to the board's id",
}

_TENANTS_CI = {k.lower(): v for k, v in TENANTS.items()}

MAX_PARCELS = int(os.getenv("USTAXDATA_MAX_PARCELS", "300"))
_CONCURRENCY = int(os.getenv("USTAXDATA_CONCURRENCY", "3"))

_STATUS_MAP = {"bill_paid": "paid", "bill_open": "unpaid", "bill_partial": "partial"}
_CELL_TEXT_RE = re.compile(r'<font color="#000000">\s*([^<]*)</font>')
_IMG_RE = re.compile(r'images/(bill_\w+)\.gif')
_ACCOUNT_RE = re.compile(r'account\.cfm\?parcelID=[^"]*">\s*([^<]*?)\s*</a>')
_ZERO_RECORDS_RE = re.compile(r'<font color="#3333CC">0</font></strong>\s*Records', re.I)
_OWED_RE = re.compile(r'TOTAL\s*AMOUNT OWED:.*?\$\s*([\d,\.]+)', re.S | re.I)
_TAXED_RE = re.compile(r'<td width="40%">\s*<div align="left" class="smallT1">\$\s*([\d,\.]+)</div>',
                       re.I)

#: taxbill.cfm lives one path segment up from the search page (…/nc/robeson/Robesontaxlist.cfm
#: -> …/nc/robeson/taxbill.cfm), confirmed live from the summary page's own "View Tax Bill" link.
_DETAIL_PATH = re.compile(r'/[^/]+\.cfm$')


def _county_key(county: Optional[str]) -> str:
    return (county or "").replace(" County", "").strip().lower()


def search_url(county: Optional[str], parcel_id: Optional[str]) -> Optional[str]:
    """The tax-search results URL, or None when the county isn't a verified tenant or there's
    no parcel id to search with."""
    base = _TENANTS_CI.get(_county_key(county))
    pid = (parcel_id or "").strip()
    if not base or not pid:
        return None
    params = {"parcelNum": pid, "lastName": "", "firstName": "", "businessName": "",
              "streetNumber": "", "StreetName": "", "accountNum": "", "billNum": "",
              "Submit": "Next"}
    return f"{base}?{urlencode(params)}"


def _cells(row_chunk: str) -> list[str]:
    """One row's <td>...</td> contents, in column order: split on <td ...> tag starts (the
    leading piece before the first <td is the row's own open tag, dropped)."""
    return re.split(r'<td\b[^>]*>', row_chunk)[1:]


def _money(s: Optional[str]) -> Optional[float]:
    s = re.sub(r"[^\d.]", "", s or "")
    if not s or s == ".":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_results(html: str) -> list[dict]:
    """One dict per tax-year bill row (year, account, bill_no, owner_name, status,
    taxable_value), page order (newest first, as the vendor lists it). [] on a 0-match search
    or any page that isn't a results table — never raises on unexpected markup."""
    if not html or "Records" not in html or _ZERO_RECORDS_RE.search(html):
        return []
    out: list[dict] = []
    for raw_row in html.split('<tr valign="middle" class="style16">')[1:]:
        chunk = raw_row.split("</tr>")[0]
        cells = _cells(chunk)
        if len(cells) < 8:
            continue
        year_m = _CELL_TEXT_RE.search(cells[1])
        if not year_m or not year_m.group(1).strip().isdigit():
            continue
        acct_m = _ACCOUNT_RE.search(cells[2])
        bill_m = _CELL_TEXT_RE.search(cells[3])
        owner_m = _CELL_TEXT_RE.search(cells[4])
        status_m = _IMG_RE.search(cells[6])
        value_m = _CELL_TEXT_RE.search(cells[7])
        out.append({
            "year": int(year_m.group(1).strip()),
            "tax_year": int(year_m.group(1).strip()),
            "account": acct_m.group(1).strip() if acct_m else None,
            "bill_no": bill_m.group(1).strip() if bill_m else None,
            "owner_name": re.sub(r"\s+", " ", owner_m.group(1)).strip() if owner_m else None,
            "status": _STATUS_MAP.get(status_m.group(1), "unknown") if status_m else "unknown",
            "taxable_value": _money(value_m.group(1) if value_m else None),
        })
    return out


def bill_detail_url(county: Optional[str], account: Optional[str], bill_no: Optional[str],
                    year: Optional[int]) -> Optional[str]:
    """The "View Tax Bill" page for one year's bill — the only place this vendor states a real
    dollar amount (module docstring). None when any piece is missing."""
    base = _TENANTS_CI.get(_county_key(county))
    if not base or not account or not bill_no or not year:
        return None
    detail_base = _DETAIL_PATH.sub("/taxbill.cfm", base)
    return f"{detail_base}?{urlencode({'ownerID': account, 'billNo': bill_no, 'TaxYear': year})}"


def parse_bill_detail(html: str) -> dict:
    """{"amount_owed": ..., "amount_taxed": ...} off one taxbill.cfm page. amount_owed is the
    page's own "TOTAL AMOUNT OWED" (what's actually outstanding today — $0.00 on a paid bill);
    amount_taxed is the gross "Amount Taxed" for the year (what was originally billed). Either
    key is absent, never 0.0-but-wrong, when its field isn't found."""
    out: dict = {}
    m = _OWED_RE.search(html or "")
    if m:
        v = _money(m.group(1))
        out["amount_owed"] = v if v is not None else 0.0   # _money() drops a real $0.00
    m = _TAXED_RE.search(html or "")
    if m:
        v = _money(m.group(1))
        if v is not None:
            out["amount_taxed"] = v
    return out


async def enrich_ustaxdata(listings: Iterable[Listing]) -> dict:
    """Multi-year paid/unpaid tax-bill history for Robeson County NC parcels, fetched by the
    board's own parcel_id. Writes raw['ustaxdata_delinquent_tax'] = {bills, years_unpaid,
    balance, taxpayer_of_record, assessed_value, source_url}. Every unpaid/partial bill gets a
    second fetch (bill_detail_url) for its real dollar amount — see the module docstring for why
    that hop is not optional. No separate wiring needed in enrichment_tax_owed.py beyond the
    _LIVE_ROLL_BLOCKS entry: Pass B there picks up any tax-ish-named raw block with a `balance`
    (the generic scan) the same way qpaybill_roll's blocks are, and tax_binding.py's _TAXISH
    keyword match recognizes the block name the same way.
    """
    targets = [li for li in listings
               if li.parcel_id and search_url(li.county, li.parcel_id)
               and not (isinstance(li.raw, dict) and isinstance(li.raw.get("ustaxdata_delinquent_tax"), dict))]
    stats = {"eligible": len(targets), "fetched": 0, "parsed": 0, "errors": 0,
             "no_record": 0, "multi_year_delinquent": 0, "filled_value": 0,
             "bills_detail_fetched": 0, "bills_detail_errors": 0}
    if not targets:
        return stats
    targets = targets[:MAX_PARCELS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        async def fetch_detail(li: Listing, bill: dict) -> None:
            url = bill_detail_url(li.county, bill.get("account"), bill.get("bill_no"), bill.get("year"))
            if not url:
                return
            async with sem:
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                except Exception:  # noqa: BLE001
                    stats["bills_detail_errors"] += 1
                    return
                await asyncio.sleep(0.5)
            got = parse_bill_detail(r.text)
            if "amount_owed" in got:
                bill["total_due"] = got["amount_owed"]
            if "amount_taxed" in got:
                bill["amount_taxed"] = got["amount_taxed"]
            stats["bills_detail_fetched"] += 1

        async def one(li: Listing) -> None:
            url = search_url(li.county, li.parcel_id)
            async with sem:
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.5)
            stats["fetched"] += 1
            bills = parse_results(r.text)
            if not isinstance(li.raw, dict):
                li.raw = {}
            checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if not bills:
                stats["no_record"] += 1
                li.raw["ustaxdata_delinquent_tax"] = {
                    "status": "no_record", "source_url": url, "checked_at": checked_at}
                return
            stats["parsed"] += 1
            bills.sort(key=lambda b: b["year"], reverse=True)
            unpaid = [b for b in bills if b["status"] != "paid"]
            if unpaid:
                await asyncio.gather(*(fetch_detail(li, b) for b in unpaid))
            years_unpaid = sorted({b["year"] for b in unpaid})
            balance = round(sum(b["total_due"] for b in unpaid if b.get("total_due")), 2)
            latest = bills[0]
            block = {
                "bills": bills,
                "years_unpaid": years_unpaid,
                "taxpayer_of_record": latest["owner_name"] or None,
                "assessed_value": latest["taxable_value"],
                "source_url": url,
                "checked_at": checked_at,
            }
            if balance:
                block["balance"] = balance
                block["total_due"] = balance
            li.raw["ustaxdata_delinquent_tax"] = block
            if len(years_unpaid) >= 2:
                stats["multi_year_delinquent"] += 1
            if latest["taxable_value"] and not li.tax_value:
                li.tax_value = latest["taxable_value"]
                stats["filled_value"] += 1

        await asyncio.gather(*(one(li) for li in targets))
    log.info("ustaxdata.done", **stats)
    return stats
