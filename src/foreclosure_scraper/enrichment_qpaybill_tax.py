"""qPayBill county tax portal -> delinquent real-property tax BALANCE.

Fills the per-parcel delinquent tax balance that the tax-sale-LIST scrapers
can't (those PDFs carry parcel + owner but no dollar amount). Several SC
counties publish their treasurer data on a shared qPayBill ASP.NET portal
(<county>countytax.qpaybill.com) that IS searchable free + no-login:

  search RealEstate + Unpaid + Owner-Name -> a results grid whose columns are
  Receipt | Name/Address | Year | Description | Identification No.(=TMS) |
  Type | Status | Payment Date | Amount

We search by owner SURNAME (deduped across the board so one query covers many
leads), parse the grid, and match rows back to a board lead by
Identification No. == parcel_id (both N-NN-NN-NNN.NN). A parcel's delinquent
balance = sum of its Unpaid/Sold-at-Tax-Sale rows across years. Writes the
canonical raw['tax_owed'] = {balance, kind, source, basis, years, status} that
the dashboard + distress engine already read.

Live-verified on Spartanburg 2026-07-01. Free public ASP.NET form (viewstate),
no login, no CAPTCHA. Network-heavy (one query per unique surname) -> gated OFF
by default (QPAYBILL_TAX=1); meant for a scheduled/opt-in pass, bounded by a
per-query timeout, an overall budget, and a consecutive-failure breaker.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections import defaultdict
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

_ENABLED = os.environ.get("QPAYBILL_TAX") == "1"
_MAX_QUERIES = int(os.environ.get("QPAYBILL_MAX_QUERIES", "1500"))
_MAX_SECONDS = float(os.environ.get("QPAYBILL_MAX_SECONDS", "1200"))
_QUERY_TIMEOUT_S = float(os.environ.get("QPAYBILL_QUERY_TIMEOUT_S", "25"))
_BREAKER_FAILS = int(os.environ.get("QPAYBILL_BREAKER_FAILS", "8"))
_CONCURRENCY = int(os.environ.get("QPAYBILL_CONCURRENCY", "3"))

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# (state, county) -> qPayBill subdomain. Add a county here once its portal is
# verified AND its results Identification-No. matches our board parcel_id format.
#
# Spartanburg is the clean win: its qPayBill Identification No. IS the dashed TMS
# we store, so results join by exact parcel_id (+408 balances live).
#
# Oconee/Laurens/Cherokee/Union qPayBill portals ALSO return real delinquent
# balances (live-verified), but their Identification No. is an internal county
# account id (e.g. Oconee "15268", Cherokee dashed) that does NOT match our
# board parcel format — so results can't be reliably joined without a per-county
# parcel<->account cross-reference. They also carry few tax-delinquent board
# leads. Left out until a join key exists. Anderson = 403 auth wall; Pickens =
# no bulk portal (qPublic per-parcel card only).
QPAYBILL_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Spartanburg"): "spartanburgcountytax",
}

# Statuses that count as an owed delinquent balance (exclude already-paid).
_OWED_STATUSES = ("unpaid", "sold at tax sale", "delinquent", "bankruptcy")
_TMS_RE = re.compile(r"\b\d-\d{2}-\d{2}-\d{3}\.\d{2}\b")


def _url(sub: str) -> str:
    return f"https://{sub}.qpaybill.com/Taxes/TaxesDefaultType4.aspx"


def _hidden(html: str, name: str) -> str:
    m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _parse_rows(html: str) -> list[dict]:
    """Parse the standardized qPayBill results grid into {tms, year, status,
    amount} rows. Columns are consistent across counties: 0 Receipt, 1 Name/
    Address, 2 Year, 3 Description, 4 Identification No. (parcel id — format
    varies by county: dashed TMS in Spartanburg, plain numeric in Oconee), 5
    Type, 6 Status, 7 Payment Date, 8 Amount. Parse by POSITION, not by a
    county-specific id regex.
    """
    out: list[dict] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 9:
            continue
        pid = cells[4].strip()
        amt_m = re.search(r"\$([\d,]+\.\d{2})", cells[8])
        if not (pid and amt_m):
            continue
        amt = float(amt_m.group(1).replace(",", ""))
        if amt <= 0 or amt == 99999.00 or amt >= 1_000_000:  # qPayBill placeholder / misfire
            continue
        out.append({"tms": pid, "year": cells[2].strip(),
                    "status": cells[6].strip(), "amount": amt})
    return out


async def _search_surname(client: httpx.AsyncClient, sub: str, vs: dict, surname: str) -> list[dict]:
    data = {
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__VIEWSTATE": vs["vs"], "__VIEWSTATEGENERATOR": vs["gen"], "__EVENTVALIDATION": vs["ev"],
        "ctl00$MainContent$SearchType": "radRealEstateButton",
        "ctl00$MainContent$PaidStatus": "radUnpaidButton",
        "ctl00$MainContent$ddlYearList": "All",
        "ctl00$MainContent$ddlCriteriaList": "Name",
        "ctl00$MainContent$txtCriteriaBox": surname,
        "ctl00$MainContent$btnSearch": "Search",
    }
    r = await client.post(_url(sub), data=data)
    return _parse_rows(r.text)


def _surname(name: Optional[str]) -> Optional[str]:
    """First alphabetic token of an owner string — qPayBill indexes 'LAST FIRST'."""
    for tok in re.split(r"[\s,]+", (name or "").strip()):
        if len(tok) >= 2 and tok.isalpha():
            return tok.upper()
    return None


async def enrich_qpaybill_tax(listings: list[Listing]) -> dict:
    """Fill raw['tax_owed'] for county-tax leads whose county has a qPayBill portal."""
    counts = {"targets": 0, "queries": 0, "filled": 0, "misses": 0}
    if not _ENABLED:
        return counts

    # group in-scope, balance-less leads by (county-sub, surname); index by TMS
    by_query: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    tms_index: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    for li in listings:
        sub = QPAYBILL_COUNTIES.get((li.state or "", (li.county or "").replace(" County", "").strip()))
        if not sub:
            continue
        if (li.raw or {}).get("tax_owed", {}).get("balance"):
            continue
        sn = _surname(li.owner_name or li.defendant)
        pid = (li.parcel_id or "").strip()
        if not sn or not pid:
            continue
        by_query[(sub, sn)].append(li)
        tms_index[(sub, pid)].append(li)
    counts["targets"] = sum(len(v) for v in by_query.values())
    queries = list(by_query.keys())[:_MAX_QUERIES]
    if not queries:
        return counts

    log.info("qpaybill_tax.start", targets=counts["targets"], queries=len(queries))
    sem = asyncio.Semaphore(_CONCURRENCY)
    state = {"consec_fail": 0, "deadline": time.monotonic() + _MAX_SECONDS, "tripped": False}
    # per-county cached viewstate (fetched once)
    vs_cache: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=_QUERY_TIMEOUT_S, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        async def get_vs(sub: str) -> Optional[dict]:
            if sub not in vs_cache:
                try:
                    b = (await client.get(_url(sub))).text
                    vs_cache[sub] = {"vs": _hidden(b, "__VIEWSTATE"),
                                     "gen": _hidden(b, "__VIEWSTATEGENERATOR"),
                                     "ev": _hidden(b, "__EVENTVALIDATION")}
                except Exception:  # noqa: BLE001
                    vs_cache[sub] = None
            return vs_cache[sub]

        async def one(sub: str, surname: str) -> None:
            if state["tripped"] or time.monotonic() > state["deadline"]:
                return
            async with sem:
                if state["tripped"] or time.monotonic() > state["deadline"]:
                    return
                vs = await get_vs(sub)
                if not vs:
                    return
                try:
                    rows = await asyncio.wait_for(_search_surname(client, sub, vs, surname),
                                                  timeout=_QUERY_TIMEOUT_S)
                    counts["queries"] += 1
                    state["consec_fail"] = 0
                except (Exception, asyncio.TimeoutError):
                    state["consec_fail"] += 1
                    if _BREAKER_FAILS and state["consec_fail"] >= _BREAKER_FAILS:
                        state["tripped"] = True
                        log.warning("qpaybill_tax.circuit_open", queries=counts["queries"])
                    return
                # aggregate owed rows per TMS
                owed: dict[str, dict] = {}
                for row in rows:
                    if not any(s in row["status"].lower() for s in _OWED_STATUSES):
                        continue
                    agg = owed.setdefault(row["tms"], {"balance": 0.0, "years": [], "status": row["status"]})
                    agg["balance"] += row["amount"]
                    if row["year"]:
                        agg["years"].append(row["year"])
                for pid, agg in owed.items():
                    for li in tms_index.get((sub, pid), []):
                        if (li.raw or {}).get("tax_owed", {}).get("balance"):
                            continue
                        if not isinstance(li.raw, dict):
                            li.raw = {}
                        li.raw["tax_owed"] = {
                            "balance": round(agg["balance"], 2), "kind": "delinquent_tax",
                            "source": f"qpaybill:{sub}", "basis": "own_record",
                            "years": sorted(set(agg["years"])), "status": agg["status"],
                        }
                        counts["filled"] += 1

        await asyncio.gather(*(one(sub, sn) for sub, sn in queries))

    counts["misses"] = counts["targets"] - counts["filled"]
    log.info("qpaybill_tax.done", **counts)
    return counts
