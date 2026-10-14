"""Transylvania County (NC) DELINQUENT tax bills — a tax-delinquency distress source.

The county tax portal (bitek/ITSPublic, host ``tax.transylvaniacounty.org``) exposes a
"pay unpaid bills" search that lists every OPEN tax bill for a given year. Unpaid property
tax is a hard motivated-seller / pre-foreclosure signal: the county can eventually enforce
the lien and force a tax sale, and heirs / absentee owners of delinquent parcels are prime
outreach targets.

This is NOT an ArcGIS layer. It is a 3-step JSON/cookie chain on one ASP.NET-MVC host:
  1. GET  /TaxBillSearch                     -> seeds the ASP.NET_SessionId cookie.
  2. POST /TaxBillSearch/GetSearchTablePartial/  {full search-input model, UnpaidBillsOnly:true,
     TaxYear:"2025", ...}  -> stores the search criteria in server-side session and returns an
     HTML results shell (empty body if the model is incomplete — every search-value field must
     be present, which is why we send the whole model, not just the two flags).
  3. POST /TaxBillSearch/GetSearchTableData      {Page, NumRows, Table:"PayTaxBills", PostData:""}
     -> reads the session search and returns JSON {total, numRecords, rows:[{id, cell:[...]}]}.

The grid rows carry: Year, Bill#, Account#, Owner, Description (parcel + map + acreage), Original
Levy, Balance. They do NOT carry a street address. The owner MAILING address, the parcel PIN,
the legal description and the taxable value live only on the per-bill detail
(POST /TaxBillSearch/ViewTaxBill {taxYear, billNumber}). ViewTaxBill needs only the seed cookie
(not the session search), so detail enrichment is parallelized with a small semaphore off a
direct httpx.AsyncClient — the shared rate-limited client() would serialize ~450 calls to a
single host into many minutes.

The grid also mixes in PERSONAL PROPERTY bills (vehicles/boats/business
personal property) with no source-type column -- the only tell is the
description cell literally reading "Personal Property" instead of a
parcel/map/acreage block. Live-verified 2026-10-03: 188 of 429 current
unpaid bills (44%) are Personal Property; these are filtered out (see
``_is_personal_property``) before enrichment and emission, since they are
not real property.

DATE COVERAGE (fixed 2026-10-14, date-coverage audit): this file used to query a single
hardcoded ``FORECLOSURE_TRANSYLVANIA_TAX_YEAR`` (default "2025") and stop -- the SAME
platform as the sibling ``nc_its_public_tax.py`` (same TaxBillSearch -> GetSearchTablePartial
-> GetSearchTableData call shape), whose multi-year loop already proves the portal answers
any year asked, but this file was never generalized the same way. A parcel that caught up on
2025 but still owes 2022-2024 was invisible. Live-verified real depth 2026-10-14: every year
2014-2025 (12 years) answers a nonzero unpaid-bill count; 2013 and every year before it
answers 0. The fix loops ``TaxYear`` back to ``YEARS_BACK`` (a safety ceiling, default 15,
comfortably past the measured 12-year depth), stopping early once two years in a row answer
nothing (a single empty year never trips it, same convention as ``nc_its_public_tax.py``).
Bills across every year read are grouped by PARCEL (falling back to account+situs when the
grid carries no parcel, same as the sibling file), their balances and levies summed, and
``years``/``years_delinquent``/``oldest_year``/``two_year_delinquent`` published the same
shape the rest of this codebase's multi-year tax sources use -- live-measured: 240 real-
estate bills (2025 only, the old behavior) become 308 distinct parcels across 2014-2025, 135
of them (44%) delinquent in 2+ separate years, several delinquent EVERY year since 2014.
Only the group's NEWEST-year bill gets the expensive ``ViewTaxBill`` detail fetch (owner
mailing / parcel / assessed value do not change by which year's bill you view), so enrichment
cost tracks the number of distinct parcels (308), not the number of bill-rows read (909) --
the existing ``FORECLOSURE_TRANSYLVANIA_TAX_MAX_DETAIL`` cap still applies to that
representative set. ``FORECLOSURE_TRANSYLVANIA_TAX_YEAR`` still works -- set it to read
exactly one year, same as before this fix, for a quick/cheap sample run.

Free, anonymous, compliant (public tax portal, no auth / captcha / token forgery).
Gate off with FORECLOSURE_TRANSYLVANIA_TAX=0.
Tunables: FORECLOSURE_TRANSYLVANIA_TAX_YEAR (single-year override; unset = multi-year),
          FORECLOSURE_TRANSYLVANIA_TAX_YEARS_BACK (default 15, a safety ceiling),
          FORECLOSURE_TRANSYLVANIA_TAX_MAX_DETAIL (default 0 = enrich all representative bills),
          FORECLOSURE_TRANSYLVANIA_TAX_CONCURRENCY (default 6).
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime
from typing import Iterable

import httpx

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

SLUG = "counties_nc.transylvania_delinquent_tax"
BASE = "https://tax.transylvaniacounty.org/TaxBillSearch"
#: A safety CEILING, not a target -- live-verified real depth is 2014-2025 (12 years); 15
#: leaves headroom without reading years that will never answer (2013 and earlier all 0).
YEARS_BACK = int(os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX_YEARS_BACK", "15"))
#: Stop reading further back once this many years IN A ROW came back with zero rows.
_CONSECUTIVE_EMPTY_STOP = 2
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE,
    "Origin": "https://tax.transylvaniacounty.org",
    "Accept": "application/json, text/javascript, text/html, */*; q=0.01",
}

# City, ST 12345  (optionally -6789)
_CSZ_RE = re.compile(r"^(.*),\s*([A-Za-z]{2})\.?\s+(\d{5})(?:-\d{4})?$")

#: The "UnpaidBillsOnly" grid mixes REAL ESTATE and PERSONAL PROPERTY (vehicle/
#: boat/business-personal-property) bills with no source-type flag to tell them
#: apart by column -- unlike the sibling Rutherford scrapers' explicit
#: BILL_TYPE=="REI" filter, this grid's only tell is the description cell
#: (cell[4]) literally reading "Personal Property" instead of a parcel/map/
#: acreage block. Live-verified 2026-10-03: 188 of 429 current unpaid bills
#: (44%) are Personal Property -- previously emitted anyway, with cell[4]'s
#: literal text "Personal Property" published as parcel_id (there is no real
#: parcel, so ViewTaxBill's "Parcel Number :" line is also absent and the grid
#: fallback took over), i.e. nearly half of this source's leads were fake
#: "properties" that are actually a delinquent vehicle/boat tax bill.
_PERSONAL_PROPERTY_RE = re.compile(r"^\s*Personal\s+Property\b", re.I)


def _is_personal_property(cell4) -> bool:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", str(cell4 or ""))).strip()
    return bool(_PERSONAL_PROPERTY_RE.match(plain))


def _f(v) -> float | None:
    """Float-coerce, stripping $ and commas; None if empty/non-positive."""
    try:
        f = float(re.sub(r"[^0-9.\-]", "", str(v)).strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _search_model(tax_year: str) -> dict:
    """The full search-input model the browser posts. All ``.search-value`` fields
    must be present or GetSearchTablePartial returns an empty body (no session write)."""
    return {
        "PageSize": 50,
        "OwnerLastName": "",
        "OwnerFirstName": "",
        "AccountNumber": "",
        "ParcelNumber": "",
        "ParcelSearch": "false",
        "TaxYear": tax_year,
        "BillNumber": "",
        "UnpaidBillsOnly": True,
        "FormattedPropertyAddress": "",
        "SortBy": "AccountName1-Asc",
    }


def tax_years(latest: int | None = None, back: int | None = None) -> list[int]:
    """Tax years to ask for, newest first. ``FORECLOSURE_TRANSYLVANIA_TAX_YEAR`` (unchanged
    from before this fix) still reads exactly one year when set -- a quick/cheap sample run.
    Otherwise every year back to ``YEARS_BACK`` (see its own docstring for why this is a
    ceiling, not a target -- the real stop is ``_CONSECUTIVE_EMPTY_STOP`` in ``fetch()``)."""
    override = os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX_YEAR")
    if override and override.strip():
        try:
            return [int(override.strip())]
        except ValueError:
            pass
    latest = latest if latest is not None else datetime.utcnow().year
    n = YEARS_BACK if back is None else back
    return [latest - i for i in range(max(1, n))]


_ACRE_OR_LOT_RE = re.compile(r"^([\d.]+)\s*(AC|LT)?")


def parse_grid_row(row: dict) -> dict | None:
    """One ``PayTaxBills`` grid row -> a bill dict, or None for personal property / a row
    too malformed to use (len(cell) < 7, or no digit tax year). Carries its own ``year`` so
    bills read across many years can be merged by parcel later."""
    cell = row.get("cell") or []
    if len(cell) < 7:
        return None
    if _is_personal_property(cell[4]):
        return None
    year_s = str(cell[0]).strip()
    if not year_s.isdigit():
        return None
    desc_parts = [html.unescape(re.sub(r"<[^>]+>", " ", p)).strip()
                 for p in re.split(r"<br\s*/?>", str(cell[4]))]
    desc_parts = [p for p in desc_parts if p]
    grid_parcel = desc_parts[0] if desc_parts else None
    map_ref = desc_parts[1] if len(desc_parts) > 1 else None
    size_ref = desc_parts[-1] if len(desc_parts) > 2 else None
    acreage = None
    if size_ref:
        am = _ACRE_OR_LOT_RE.match(size_ref)
        if am and am.group(2) == "AC":
            acreage = _f(am.group(1))
    return {
        "id": row.get("id") or "", "year": int(year_s), "bill_no": str(cell[1]).strip(),
        "account": str(cell[2]).strip(),
        "owner": html.unescape(re.sub(r"<[^>]+>", " ", str(cell[3]))).strip() or None,
        "grid_parcel": grid_parcel, "map_ref": map_ref, "size_ref": size_ref, "acreage": acreage,
        "original_levy": _f(cell[5]), "balance": _f(cell[6]),
    }


def group_by_parcel(bills: list[dict]) -> dict[str, list[dict]]:
    """Every bill read (any year), grouped by its grid parcel id, falling back to
    account+year-independent account number when the grid carries no parcel at all
    (Transylvania's grid never prints a situs, so there is no address to fall back to)."""
    groups: dict[str, list[dict]] = {}
    for b in bills:
        key = b["grid_parcel"] or f"acct:{b['account']}"
        groups.setdefault(key, []).append(b)
    return groups


def _text_lines(page_html: str) -> list[str]:
    txt = re.sub(r"<[^>]+>", "\n", page_html)
    return [re.sub(r"\s+", " ", ln).strip() for ln in txt.split("\n") if ln.strip()]


def _slice_between(lines: list[str], start: str, end: str) -> list[str]:
    try:
        i = lines.index(start)
    except ValueError:
        return []
    try:
        j = lines.index(end, i + 1)
    except ValueError:
        j = len(lines)
    return lines[i + 1:j]


def _label_value(lines: list[str], label: str) -> str | None:
    try:
        i = lines.index(label)
    except ValueError:
        return None
    return lines[i + 1] if i + 1 < len(lines) else None


def _owner_mailing_block(det: dict, owner: str | None, parcel: str | None) -> dict | None:
    """The bill's owner MAILING address as raw['owner_mailing'] (the shape mailing_shape.
    mailing_of() reads), or None. It is never the property's street/city/ZIP: the bill
    carries no situs at all."""
    street = det.get("mailing_street")
    city = det.get("mailing_city")
    zipc = det.get("mailing_zip")
    mail_state = det.get("mailing_state")
    # Drop a "street" that is really just the owner name or the city echoed (mailing
    # blocks with no street line) -- not a mailable street.
    if street and owner and street.strip().lower() == owner.strip().lower():
        street = None
    if street and city and street.strip().lower() == city.strip().lower():
        street = None
    mailing = det.get("mailing_full") or " ".join(
        b for b in (street, city, mail_state, zipc) if b) or None
    if not mailing:
        return None
    out_of_state = bool(mail_state and mail_state.upper() != "NC")
    return {
        "owner": owner or None, "mailing": mailing,
        "street": street, "city": city, "state": mail_state, "zip": zipc,
        "situs": None, "parcel_id": parcel, "mail_state": mail_state,
        "out_of_state": out_of_state,
        # An out-of-state owner is absentee; otherwise unknown until a situs is
        # resolved to compare against.
        "absentee": True if out_of_state else None,
        "source": "transylvania_tax_bill",
    }


def _parse_detail(page_html: str) -> dict:
    """Extract owner mailing address, parcel, legal, and taxable value from a ViewTaxBill page."""
    lines = _text_lines(page_html)
    out: dict = {}

    # Mailing block sits between "Account Number :" and "Bill Info":
    #   [account_number, owner_name(s)..., street?, "City, ST ZIP"]
    block = _slice_between(lines, "Account Number :", "Bill Info")
    if block:
        out["account_number"] = block[0] or None
        addr_lines = [x for x in block[1:] if x]
        csz_idx = None
        for k, ln in enumerate(addr_lines):
            if _CSZ_RE.match(ln):
                csz_idx = k  # keep last match
        if csz_idx is not None:
            m = _CSZ_RE.match(addr_lines[csz_idx])
            out["mailing_city"] = (m.group(1) or "").strip() or None
            out["mailing_state"] = (m.group(2) or "").strip().upper() or None
            out["mailing_zip"] = (m.group(3) or "").strip() or None
            # line right before the city/state/zip = street (index >= 1 so it's not the owner line)
            if csz_idx >= 1:
                out["mailing_street"] = addr_lines[csz_idx - 1] or None
        out["mailing_full"] = ", ".join(addr_lines) or None

    out["parcel_number"] = _label_value(lines, "Parcel Number :")
    out["legal_description"] = _label_value(lines, "Legal Description :")
    building = _f(_label_value(lines, "Building Value :"))
    out["building_value"] = building
    out["land_value"] = _f(_label_value(lines, "Land Value :"))
    out["parcel_value_total"] = _f(_label_value(lines, "Parcel Value Total :"))
    out["current_balance"] = _f(_label_value(lines, "Current Balance :"))
    # 2026-10-01 (per-source extraction audit, HERMES sec 8): ViewTaxBill
    # publishes several more fields that were never read. outbuilding_value
    # flags a barn/shed/second structure the building_value alone misses
    # (CAMA-spec gap, HERMES sec 9: "only 32% have real CAMA specs"). The two
    # dates are a real distress-severity signal: a bill with no last_payment_
    # date at all has NEVER been paid (worse than a lapsed payer), and a
    # recent last_transaction_date on a delinquent bill flags a new owner
    # already behind. Live-verified 2026-10-01 against account 70094770.
    out["outbuilding_value"] = _f(_label_value(lines, "Outbuilding Value :"))
    # A blank "Last Payment Date :" line is followed by the NEXT section
    # header ("Taxes/fees"), not an empty string -- live-verified 2026-10-01
    # (account 70094770 has never made a payment, so this field is blank on
    # the live page). _label_value has no way to tell "blank" from "the next
    # real line", so guard both dates with a date-shape check; a non-match
    # means the field was genuinely empty, which is itself the signal (a
    # delinquent bill with NO last_payment_date at all has never been paid).
    _date_shape = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
    last_txn = _label_value(lines, "Last Transaction Date :")
    out["last_transaction_date"] = last_txn if last_txn and _date_shape.match(last_txn) else None
    last_pmt = _label_value(lines, "Last Payment Date :")
    out["last_payment_date"] = last_pmt if last_pmt and _date_shape.match(last_pmt) else None
    # 2026-10-03: three more "Taxable Values" lines on the same already-fetched
    # detail page, live-verified against a 30-bill sample. "Exemption :" (1/30
    # live, $116,285 on account 70527110) is the dollar amount knocked off the
    # taxable value by a homestead/elderly/veteran/disability exemption -- a
    # direct "elderly" lead-source signal (HERMES sec 1 lists elderly as one of
    # the named distress types), not just a value adjustment. "Deferred Value :"
    # (present-use-value deferral, e.g. agricultural land) and "Personal Value :"
    # (12/30 live -- often a mobile home value riding on an otherwise-real-estate
    # account, distinct from a standalone personal-property BILL) were also
    # dropped. A probed companion "TaxDistrictsData" AJAX table (tax/fee line
    # items by district) turned out to be dead on the vendor's OWN site --
    # POST /TaxDistrictsData/GetSearchTableData 404s ("controller ... was not
    # found"), confirmed from the vendor's own PageTable.js routing logic -- so
    # NOT pursued further, not a gap on our side.
    out["exemption"] = _f(_label_value(lines, "Exemption :"))
    out["deferred_value"] = _f(_label_value(lines, "Deferred Value :"))
    out["personal_value"] = _f(_label_value(lines, "Personal Value :"))
    out["net_taxable_valuation"] = _f(_label_value(lines, "Net Taxable Valuation :"))
    return out


def build_listing(bills: list[dict], det: dict, now: datetime) -> Listing:
    """One parcel's bills (any number of years, already grouped by `group_by_parcel`) plus
    its representative (newest-year) `ViewTaxBill` detail -> one TAX_LIEN Listing, balance
    and levy summed across every year read -- the same per-parcel-sum shape the sibling
    `nc_its_public_tax.aggregate` uses, so a parcel delinquent since 2014 carries its full
    accumulated depth, not just whichever single year happened to be read."""
    bills_sorted = sorted(bills, key=lambda b: b["year"], reverse=True)
    head = bills_sorted[0]
    years = sorted({b["year"] for b in bills})
    total_balance = round(sum(b["balance"] or 0 for b in bills), 2) or None
    total_levy = round(sum(b["original_levy"] or 0 for b in bills), 2) or None
    owner = head["owner"]
    parcel = (det.get("parcel_number") or head.get("grid_parcel") or "").strip() or None
    value = det.get("parcel_value_total") or det.get("land_value")
    building = det.get("building_value")
    land = det.get("land_value")
    pk = PropertyKind.LAND if building == 0.0 and (land or 0) > 0 else PropertyKind.UNKNOWN
    mail_state = det.get("mailing_state")
    owner_mailing = _owner_mailing_block(det, owner, parcel)
    amount = total_balance or det.get("current_balance")
    amt_str = f"${amount:,.2f}" if amount else "unknown amount"
    span = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
    return Listing(
        source=SLUG,
        source_url=BASE,
        listing_type=ListingType.TAX_LIEN,
        property_kind=pk,
        owner_name=owner or None,
        street_address=None,
        city=None,
        state="NC",
        county="Transylvania",
        zip_code=None,
        parcel_id=parcel,
        legal_description=det.get("legal_description") or None,
        assessed_value=_f(value),
        tax_value=_f(value),
        market_value=_f(value),
        acreage=head.get("acreage"),
        description=(f"Delinquent NC property tax {span} ({len(bills)} bill"
                     f"{'s' if len(bills) != 1 else ''}) open with Transylvania County"
                     + (f": {amt_str} due" if amount else "")),
        first_seen=now, last_seen=now,
        raw={**({"owner_mailing": owner_mailing} if owner_mailing else {}),
             "transylvania_tax": {
                "tax_year": head["year"],
                "bill_number": head["bill_no"],
                "account_number": head["account"] or det.get("account_number"),
                "parcel": parcel,
                "map_reference": head.get("map_ref"),
                "size_reference": head.get("size_ref"),
                "original_levy": total_levy,
                "balance_owed": amount,
                "building_value": building,
                "land_value": land,
                "parcel_value_total": det.get("parcel_value_total"),
                "outbuilding_value": det.get("outbuilding_value"),
                "last_transaction_date": det.get("last_transaction_date"),
                "last_payment_date": det.get("last_payment_date"),
                "owner_mailing_full": det.get("mailing_full"),
                "mailing_state": mail_state,
                "exemption": det.get("exemption"),
                "deferred_value": det.get("deferred_value"),
                "personal_value_on_account": det.get("personal_value"),
                "net_taxable_valuation": det.get("net_taxable_valuation"),
                "signal": "delinquent_property_tax",
                # Multi-year depth, 2026-10-14 fix -- same shape as nc_its_public_tax.aggregate.
                "years": years, "years_delinquent": len(years), "oldest_year": years[0],
                "is_two_year_plus": len(years) >= 2,
                "bills": [{"year": b["year"], "bill": b["bill_no"], "balance": b["balance"],
                           "original_levy": b["original_levy"]} for b in bills_sorted],
             },
             # The shared, published key fullmer_rank reads for delinquency ripeness (same
             # key nc_its_public_tax publishes, already registered -- see web_artifact.py).
             "two_year_delinquent": {"is_two_year_plus": len(years) >= 2, "years": len(years),
                                     "oldest_year": years[0], "source": SLUG},
             **({"tax_owed": {"balance": amount, "kind": "delinquent_tax", "source": SLUG,
                              "year": head["year"], "basis": "own_record"}} if amount else {}),
            },
    )


class TransylvaniaDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Transylvania County (NC) Delinquent Tax Bills"
    category = "distress"
    #: Raised from 120s (2026-10-14): up to YEARS_BACK sequential year-searches plus
    #: detail-enrichment of every distinct parcel across all years read (up from one
    #: year's ~240 parcels to ~308, live-measured) no longer fits the old single-year budget.
    timeout_s = 600.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX", "1") == "0":
            return []

        years = tax_years()
        try:
            max_detail = int(os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX_MAX_DETAIL", "0"))
        except ValueError:
            max_detail = 0
        try:
            concurrency = max(1, int(os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX_CONCURRENCY", "6")))
        except ValueError:
            concurrency = 6

        now = datetime.utcnow()
        out: list[Listing] = []

        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True,
                                         headers=_HEADERS) as c:
                # (1) seed the session cookie -- once, not per year
                try:
                    await c.get(BASE)
                except Exception:  # noqa: BLE001
                    return []

                # (2)+(3) per tax year: store the search in server-side session, then pull
                # every unpaid bill row in one page. YEARS_BACK is a ceiling, not a target --
                # stop once two years IN A ROW answer nothing (a single-year gap in the real
                # data, same shape as the sibling nc_its_public_tax.py, must not stop it).
                all_rows: list[dict] = []
                consecutive_empty = 0
                for year in years:
                    try:
                        await c.post(BASE + "/GetSearchTablePartial/",
                                    json=_search_model(str(year)))
                        data_model = {"Page": 1, "NumRows": 5000, "SortBy": "AccountName1",
                                     "SortOrder": "Asc", "Table": "PayTaxBills", "PostData": ""}
                        r = await c.post(BASE + "/GetSearchTableData", json=data_model)
                        rows = (r.json().get("rows", []) or []
                               if r.status_code == 200
                               and r.headers.get("content-type", "").startswith("application/json")
                               else [])
                    except Exception:  # noqa: BLE001
                        rows = []
                    all_rows.extend(rows)
                    consecutive_empty = 0 if rows else consecutive_empty + 1
                    if len(years) > 1 and consecutive_empty >= _CONSECUTIVE_EMPTY_STOP:
                        break

                if not all_rows:
                    return []

                # Drop Personal Property bills (vehicles/boats/business personal property)
                # and malformed rows before enrichment too -- no point spending a
                # ViewTaxBill request on a bill that will be discarded below.
                bills = [b for b in (parse_grid_row(r) for r in all_rows) if b is not None]
                groups = group_by_parcel(bills)

                # Detail enrichment (owner mailing address / parcel / value) — parallel,
                # bounded, and only ONE representative bill per PARCEL (its newest year):
                # these fields are account-level, not per-year, so enriching every bill of a
                # parcel delinquent 10 years would spend 10x the requests for no new data.
                reps: dict[str, dict] = {key: max(g, key=lambda b: b["year"])
                                        for key, g in groups.items()}
                rep_items = list(reps.items())
                to_enrich = rep_items if max_detail <= 0 else rep_items[:max_detail]
                sem = asyncio.Semaphore(concurrency)
                details: dict[str, dict] = {}

                async def _enrich(key: str, bill: dict) -> None:
                    rid = bill.get("id") or ""
                    if "/" not in rid:
                        return
                    year, bill_no = rid.split("/", 1)
                    async with sem:
                        try:
                            d = await c.post(BASE + "/ViewTaxBill",
                                             json={"taxYear": year, "billNumber": bill_no})
                            if d.status_code == 200 and d.text:
                                details[key] = _parse_detail(d.text)
                        except Exception:  # noqa: BLE001
                            return

                try:
                    await asyncio.gather(*(_enrich(key, bill) for key, bill in to_enrich))
                except Exception:  # noqa: BLE001
                    pass

                for key, group_bills in groups.items():
                    try:
                        out.append(build_listing(group_bills, details.get(key, {}), now))
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            return out
        return out
