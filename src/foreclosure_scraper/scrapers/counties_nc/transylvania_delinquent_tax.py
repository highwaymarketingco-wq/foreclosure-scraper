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

Free, anonymous, compliant (public tax portal, no auth / captcha / token forgery).
Gate off with FORECLOSURE_TRANSYLVANIA_TAX=0.
Tunables: FORECLOSURE_TRANSYLVANIA_TAX_YEAR (default 2025),
          FORECLOSURE_TRANSYLVANIA_TAX_MAX_DETAIL (default 0 = enrich all),
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

BASE = "https://tax.transylvaniacounty.org/TaxBillSearch"
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
    return out


class TransylvaniaDelinquentTax(BaseScraper):
    slug = "counties_nc.transylvania_delinquent_tax"
    name = "Transylvania County (NC) Delinquent Tax Bills"
    category = "distress"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX", "1") == "0":
            return []

        tax_year = os.environ.get("FORECLOSURE_TRANSYLVANIA_TAX_YEAR", "2025").strip() or "2025"
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
                # (1) seed the session cookie
                try:
                    await c.get(BASE)
                except Exception:  # noqa: BLE001
                    return []

                # (2) store the search in server-side session (returns HTML shell)
                try:
                    await c.post(BASE + "/GetSearchTablePartial/", json=_search_model(tax_year))
                except Exception:  # noqa: BLE001
                    return []

                # (3) pull every unpaid bill row in one page
                rows: list[dict] = []
                try:
                    data_model = {"Page": 1, "NumRows": 5000, "SortBy": "AccountName1",
                                  "SortOrder": "Asc", "Table": "PayTaxBills", "PostData": ""}
                    r = await c.post(BASE + "/GetSearchTableData", json=data_model)
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                        rows = r.json().get("rows", []) or []
                except Exception:  # noqa: BLE001
                    rows = []

                if not rows:
                    return []

                # Detail enrichment (owner mailing address / parcel / value) — parallel,
                # bounded. ViewTaxBill needs only the seed cookie, so it is safe to fan out.
                to_enrich = rows if max_detail <= 0 else rows[:max_detail]
                sem = asyncio.Semaphore(concurrency)
                details: dict[str, dict] = {}

                async def _enrich(row: dict) -> None:
                    rid = row.get("id") or ""
                    if "/" not in rid:
                        return
                    year, bill = rid.split("/", 1)
                    async with sem:
                        try:
                            d = await c.post(BASE + "/ViewTaxBill",
                                             json={"taxYear": year, "billNumber": bill})
                            if d.status_code == 200 and d.text:
                                details[rid] = _parse_detail(d.text)
                        except Exception:  # noqa: BLE001
                            return

                try:
                    await asyncio.gather(*(_enrich(row) for row in to_enrich))
                except Exception:  # noqa: BLE001
                    pass

                for row in rows:
                    try:
                        rid = row.get("id") or ""
                        cell = row.get("cell") or []
                        if len(cell) < 7:
                            continue
                        year = str(cell[0]).strip()
                        bill_no = str(cell[1]).strip()
                        account = str(cell[2]).strip()
                        owner = html.unescape(re.sub(r"<[^>]+>", " ", str(cell[3]))).strip()
                        # cell[4] = "PARCEL<br/>MAP  MS<br /><br />ACREAGE LT"
                        desc_parts = [html.unescape(re.sub(r"<[^>]+>", " ", p)).strip()
                                      for p in re.split(r"<br\s*/?>", str(cell[4]))]
                        desc_parts = [p for p in desc_parts if p]
                        grid_parcel = desc_parts[0] if desc_parts else None
                        map_ref = desc_parts[1] if len(desc_parts) > 1 else None
                        size_ref = desc_parts[-1] if len(desc_parts) > 2 else None
                        original_levy = _f(cell[5])
                        balance = _f(cell[6])

                        det = details.get(rid, {})
                        parcel = (det.get("parcel_number") or grid_parcel or "").strip() or None
                        value = det.get("parcel_value_total") or det.get("land_value")
                        building = det.get("building_value")
                        land = det.get("land_value")
                        pk = PropertyKind.UNKNOWN
                        if building == 0.0 and (land or 0) > 0:
                            pk = PropertyKind.LAND

                        # Acreage from the grid size ref, e.g. "1.000 LT" / "1.32 AC"
                        acreage = None
                        if size_ref:
                            am = re.match(r"([\d.]+)\s*(AC|LT)?", size_ref)
                            if am and am.group(2) == "AC":
                                acreage = _f(am.group(1))

                        # street/city/zip come from the owner MAILING address; the property
                        # itself is in Transylvania County, NC (state stays NC for footprint).
                        street = det.get("mailing_street")
                        city = det.get("mailing_city")
                        zipc = det.get("mailing_zip")
                        mail_state = det.get("mailing_state")
                        # Drop a "street" that is really just the owner name or the city
                        # echoed (mailing blocks with no street line) — not a mailable street.
                        if street and owner and street.strip().lower() == owner.strip().lower():
                            street = None
                        if street and city and street.strip().lower() == city.strip().lower():
                            street = None

                        amount = balance or det.get("current_balance")
                        amt_str = f"${amount:,.2f}" if amount else "unknown amount"
                        out.append(Listing(
                            source=self.slug,
                            source_url=BASE,
                            listing_type=ListingType.TAX_LIEN,
                            property_kind=pk,
                            owner_name=owner or None,
                            street_address=street,
                            city=city,
                            state="NC",
                            county="Transylvania",
                            zip_code=zipc,
                            parcel_id=parcel,
                            legal_description=det.get("legal_description") or None,
                            assessed_value=_f(value),
                            tax_value=_f(value),
                            market_value=_f(value),
                            acreage=acreage,
                            description=(f"Delinquent {year} property tax bill #{bill_no} "
                                         f"(balance {amt_str}) open with Transylvania County. "
                                         f"Address shown is the owner mailing address."),
                            first_seen=now,
                            last_seen=now,
                            raw={"transylvania_tax": {
                                "tax_year": year,
                                "bill_number": bill_no,
                                "account_number": account or det.get("account_number"),
                                "parcel": parcel,
                                "map_reference": map_ref,
                                "size_reference": size_ref,
                                "original_levy": original_levy,
                                "balance_owed": amount,
                                "building_value": building,
                                "land_value": land,
                                "parcel_value_total": det.get("parcel_value_total"),
                                "owner_mailing_full": det.get("mailing_full"),
                                "mailing_state": mail_state,
                                "signal": "delinquent_property_tax",
                            }},
                        ))
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            return out
        return out
