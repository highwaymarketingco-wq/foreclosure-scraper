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

ALEXANDER AND ROCKINGHAM ARE THE SAME VENDOR, PARCEL SEARCH REJECTED, NAME SEARCH WIRED
INSTEAD (2026-10-16). The board's own parcel_id search returns "0 Records" for both (confirmed
live, not a fetch error — the page renders a normal 0-match results page): Alexander
account.cfm?parcelID=0002451 (board parcel_id 3736984870 for the same row), Rockingham
parcelID=152358 (board parcel_id 792800687243). Neither resembles the board's GIS-style
parcel_id — the same "ID FORMAT VARIES PER COUNTY" trap enrichment_bt_appraisal_card.py hit on
Moore/Anson/Caswell/Duplin/Person/Scotland/Warren/Yadkin — and there is still no parcel_id ->
county-account crosswalk in this project to translate one into the other (see REJECTED_TENANTS).
But the vendor's OWN search form sidesteps needing one: it has separate lastName/firstName/
businessName fields (search_url_by_name), not BT TaxPayer Portal's single fuzzy OwnerName text
box, so a real board owner_name finds the right account directly -- confirmed live for both
counties (Alexander lastName=RHYNE&firstName=DENNIS, Rockingham businessName=Bms investment).
The risk this reintroduces -- a common name returning someone ELSE's account -- is closed by
`_confirm_by_address`: the row's own `situs` column (cells[5], read for the first time; Robeson
publishes a placeholder there, "> CONTACT COUNTY FOR", which address_relation() correctly never
matches, so the parcel-id path is unaffected) must address_relation()-"match" the board's
street_address, or nothing is stamped — the same name, spelled exactly right, is never enough
on its own (NAME_SEARCH_TENANTS docstring). The other 10 counties from the gap-list cluster
were never probed at all (unknown whether they share this vendor or this ID mismatch) and are
not claimed here either.

Note for whoever next reads the gap list: this unlocks multi_year_delinquent_tax /
repeat_tax_loss / tax_aging_surfaced / atty_tax_verified_confirmed / lt_tax_sale_overage for
Alexander and Rockingham -- the delinquent-tax-history columns this vendor actually has data
for. It does NOT touch rollback_exposure: this vendor has no present-use/land-use-deferral
field at all (checked; the multi-year table is paid/unpaid status only), and the gap list's
listing of rollback_exposure against ustaxdata.com tenants is itself imprecise, the same way
it is against bttaxpayerportal.com tenants (enrichment_bt_parcel_info.py's own docstring).

Free, public, no login, no CAPTCHA. One request per parcel (or per confirmed name-search hit),
so it is bounded and opt-in. Gate off with FORECLOSURE_USTAXDATA=0.
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
from .name_normalize import is_entity, owner_last_first_middle
from .verification.core import address_relation

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

#: Same vendor, parcel-id search REJECTED (board parcel_id doesn't match this vendor's own
#: account numbering, confirmed live: both are real, live "0 Records" searches, not a fetch
#: error) -- kept so nobody re-tries a parcelNum search without reading NAME_SEARCH_TENANTS
#: below first.
REJECTED_TENANTS = {
    "Alexander": "alexander.ustaxdata.com — board parcel_id 3736984870 is 0 Records; the "
                 "real account (found via lastName=RHYNE&firstName=DENNIS) is parcelID="
                 "0002451 / account 0202921, unrelated to the board's id",
    "Rockingham": "ustaxdata.com/nc/rockingham — board parcel_id 792800687243 is 0 Records; "
                  "the real account (found via businessName=Bms investment) is parcelID="
                  "152358 / account 1326686, unrelated to the board's id",
}

#: Same two counties, reached by OWNER NAME instead of the parcel id REJECTED_TENANTS gives up
#: on. The search form has separate lastName/firstName/businessName fields (no fuzzy single-
#: text-field over-match risk the way BT TaxPayer Portal's OwnerName has), so a name search
#: here is exact-token, not a substring scan. Verified live 2026-10-16: Alexander lastName=
#: RHYNE&firstName=DENNIS and Rockingham businessName=Bms investment both return the real,
#: previously-unreachable account. A hit is trusted only when exactly one distinct account
#: among the results carries a situs address (parse_results' new `situs` field, never read
#: before this -- cells[5], confirmed live by inspecting the raw row) that address_relation()
#: calls "match" against the board's own street_address -- the same name, even spelled exactly
#: right, is not enough on its own (two different people can share one; see _confirm_by_address).
NAME_SEARCH_TENANTS: dict[str, str] = {
    "Alexander": "https://alexander.ustaxdata.com/taxlist.cfm",
    "Rockingham": "https://www.ustaxdata.com/nc/rockingham/Rockinghamtaxlist.cfm",
}

_TENANTS_CI = {k.lower(): v for k, v in TENANTS.items()}
_NAME_SEARCH_TENANTS_CI = {k.lower(): v for k, v in NAME_SEARCH_TENANTS.items()}

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


def search_url_by_name(county: Optional[str], owner_name: Optional[str]) -> Optional[str]:
    """The same search form, filled by owner name instead of parcel id — only for a county in
    NAME_SEARCH_TENANTS (module docstring on why Alexander/Rockingham need this instead of
    `search_url`). An entity name goes in businessName whole; a person's name is split via
    owner_last_first_middle into the form's separate lastName/firstName fields (exact-token
    fields, not a fuzzy single-text search, so no formatting trick is needed here the way BT
    TaxPayer Portal's single OwnerName field needs "SURNAME FIRST"). None when the county isn't
    one of these two tenants or there's no usable name."""
    base = _NAME_SEARCH_TENANTS_CI.get(_county_key(county))
    name = (owner_name or "").strip()
    if not base or not name:
        return None
    params = {"parcelNum": "", "lastName": "", "firstName": "", "businessName": "",
              "streetNumber": "", "StreetName": "", "accountNum": "", "billNum": "",
              "Submit": "Next"}
    if is_entity(name):
        params["businessName"] = name
    else:
        parts = owner_last_first_middle(name)
        if not parts:
            return None
        params["lastName"], params["firstName"] = parts[0], parts[1]
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
    """One dict per tax-year bill row (year, account, bill_no, owner_name, situs, status,
    taxable_value), page order (newest first, as the vendor lists it). [] on a 0-match search
    or any page that isn't a results table — never raises on unexpected markup.

    `situs` (cells[5], the row's own property address) was never read before 2026-10-16 — the
    parcel-id search path doesn't need it (the id already identifies the parcel), but a NAME
    search (search_url_by_name) has no parcel id to trust yet, only a name, and a name alone
    is never enough to confirm which of possibly several same-named people's accounts this
    board row's parcel actually is (see _confirm_by_address)."""
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
        situs_m = _CELL_TEXT_RE.search(cells[5])
        status_m = _IMG_RE.search(cells[6])
        value_m = _CELL_TEXT_RE.search(cells[7])
        out.append({
            "year": int(year_m.group(1).strip()),
            "tax_year": int(year_m.group(1).strip()),
            "account": acct_m.group(1).strip() if acct_m else None,
            "bill_no": bill_m.group(1).strip() if bill_m else None,
            "owner_name": re.sub(r"\s+", " ", owner_m.group(1)).strip() if owner_m else None,
            "situs": re.sub(r"\s+", " ", situs_m.group(1).replace("&nbsp;", " ")).strip() or None
                     if situs_m else None,
            "status": _STATUS_MAP.get(status_m.group(1), "unknown") if status_m else "unknown",
            "taxable_value": _money(value_m.group(1) if value_m else None),
        })
    return out


def _confirm_by_address(bills: list[dict], street_address: Optional[str]) -> Optional[str]:
    """The one account among `bills` (a search-by-name result set, possibly several different
    people) whose own situs address_relation()-matches the board's street_address, or None when
    zero or more than one distinct account qualifies. Deliberately fail-closed: a name search
    can return several different people sharing a searched name (see NAME_SEARCH_TENANTS), and
    this project's own policy is to never guess between them (name_normalize's module
    docstring: "errs toward committing nothing")."""
    if not street_address:
        return None
    confirmed = {b["account"] for b in bills
                 if b.get("account") and b.get("situs")
                 and address_relation(b["situs"], street_address) == "match"}
    return next(iter(confirmed)) if len(confirmed) == 1 else None


def bill_detail_url(county: Optional[str], account: Optional[str], bill_no: Optional[str],
                    year: Optional[int]) -> Optional[str]:
    """The "View Tax Bill" page for one year's bill — the only place this vendor states a real
    dollar amount (module docstring). None when any piece is missing."""
    key = _county_key(county)
    base = _TENANTS_CI.get(key) or _NAME_SEARCH_TENANTS_CI.get(key)
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


def _name_search_eligible(li: Listing) -> bool:
    return bool(li.owner_name and li.street_address
                and _county_key(li.county) in _NAME_SEARCH_TENANTS_CI)


async def enrich_ustaxdata(listings: Iterable[Listing]) -> dict:
    """Multi-year paid/unpaid tax-bill history for Robeson County NC parcels, fetched by the
    board's own parcel_id -- or, for Alexander/Rockingham (NAME_SEARCH_TENANTS), by owner name
    with the match confirmed against the board's street_address before anything is trusted.
    Writes raw['ustaxdata_delinquent_tax'] = {bills, years_unpaid, balance, taxpayer_of_record,
    assessed_value, source_url}. Every unpaid/partial bill gets a second fetch (bill_detail_url)
    for its real dollar amount — see the module docstring for why that hop is not optional. No
    separate wiring needed in enrichment_tax_owed.py beyond the _LIVE_ROLL_BLOCKS entry: Pass B
    there picks up any tax-ish-named raw block with a `balance` (the generic scan) the same way
    qpaybill_roll's blocks are, and tax_binding.py's _TAXISH keyword match recognizes the block
    name the same way.
    """
    def _already_done(li: Listing) -> bool:
        return isinstance(li.raw, dict) and isinstance(li.raw.get("ustaxdata_delinquent_tax"), dict)

    targets = [li for li in listings
               if not _already_done(li)
               and ((li.parcel_id and search_url(li.county, li.parcel_id)) or _name_search_eligible(li))]
    stats = {"eligible": len(targets), "fetched": 0, "parsed": 0, "errors": 0,
             "no_record": 0, "multi_year_delinquent": 0, "filled_value": 0,
             "bills_detail_fetched": 0, "bills_detail_errors": 0,
             "name_search_tried": 0, "name_search_confirmed": 0, "name_search_unconfirmed": 0}
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
            pid_url = search_url(li.county, li.parcel_id)
            by_name = not pid_url
            url = pid_url or search_url_by_name(li.county, li.owner_name)
            if not url:
                return
            if by_name:
                stats["name_search_tried"] += 1
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
            if by_name and bills:
                # Several different people can share a searched name (module docstring on
                # NAME_SEARCH_TENANTS) -- only the one account whose own situs confirms this
                # board row's street_address is trusted; everyone else in the result set is
                # discarded here, never guessed between.
                account = _confirm_by_address(bills, li.street_address)
                if account is None:
                    stats["name_search_unconfirmed"] += 1
                    li.raw["ustaxdata_delinquent_tax"] = {
                        "status": "name_search_unconfirmed", "source_url": url,
                        "checked_at": checked_at}
                    return
                stats["name_search_confirmed"] += 1
                bills = [b for b in bills if b.get("account") == account]
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
