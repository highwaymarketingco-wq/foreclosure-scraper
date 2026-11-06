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

2026-11-05: added Williamsburg, Darlington, Barnwell, Kershaw to
QPAYBILL_COUNTIES (see that dict's own comment for the live evidence and
Barnwell's new redash normalizer).

Same pass added rollback-tax detection. A SC agricultural-use change-of-use
rollback bill is a separate grid row whose Description literally reads
"<year> ROLLBACK TAX..." instead of the usual situs address/lot text --
confirmed live, both reproducing verification/verifiers/tax_lien_qpaybill.py's
own prior finding (Calhoun map 053-00-01-112: three rows, "2022/2023/2024
ROLLBACK TAX...", Paid) and independently against the same parcel this
session. Rare (0 hits across ~140 fresh live rows sampled, several surnames
each, across Cherokee + the four new counties) but real, and free: it rides
the same per-surname search this module already runs for tax_owed, so
detecting it costs no extra request. `_parse_rows` flags it (`rollback`, same
field name and same "ROLLBACK" in Description.upper() test tax_lien_qpaybill.py
already uses for this identical grid) and `enrich_qpaybill_tax` stamps the
shared raw['rollback_exposure'] contract (enrichment_rollback_deferral.py /
enrichment_greenville_rollback_exposure.py) whenever a flagged row's
Identification No. joins a board lead. Only the FACT of an already-billed
amount is recorded (`rollback_already_billed`, `rollback_billed_years`) --
never a projected estimate, since this vendor exposes no present-use/
market-value split anywhere on it (confirmed independently by
enrichment_qpaybill_multiyear_tax.py's and enrichment_greenville_rollback_
exposure.py's own docstrings; re-confirmed, not re-derived, here).
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
# Join key = the results Identification-No. column. For a REAL-PROPERTY (land)
# parcel it is the dashed parcel we store, so results join by exact parcel_id.
# (Numeric idents like Oconee "15268" are MANUFACTURED-HOME/personal-property
# tax accounts — different property, they simply never match a land lead, which
# is correct.) Verified live: Spartanburg, Oconee, Laurens, Union all join by
# exact parcel. Their non-Spartanburg yield is low (most of those counties'
# board leads are foreclosure/probate, not tax-delinquent) but exact-match with
# no false positives.
#
# Cherokee joins too, but its board parcels arrive 13-digit NUMERIC (e.g.
# sc_public_index_lis_pendens stores "0020000003000") while the portal's
# Identification-No. is dashed "002-00-00-003.000". A per-county key normalizer
# (see _norm_pid / PID_NORMALIZERS below) redashes the numeric board parcel so
# the position-4 grid id joins exactly — verified live 2026-07-01.
#
# Williamsburg, Darlington, Barnwell, Kershaw added 2026-11-05. All four were
# already independently verified live by scrapers/counties_sc/qpaybill_delinquent_
# roll.py (same subdomains, same shared Type4 form/parser, thousands of real
# board rows each -- that module imports _UA/_hidden/_url from this one); each
# was re-verified fresh here with real owner-name + Map-Number searches.
#
# Williamsburg, Darlington and Kershaw join by exact parcel_id: their board
# rows already carry the portal's own dashed id verbatim (the roll scraper
# stores the grid's Identification No. as-is), round-tripped exactly live --
# Williamsburg "45-061-009", Darlington "067-07-03-066", Kershaw
# "238-00-00-148" are each a real board parcel_id that the live grid echoed
# back unchanged.
#
# Barnwell mostly joins the same way, but 819 of its 2,059 board rows
# (2026-11-05) come from sc_heir_estate_parcel_cache instead, which picks the
# SHORTEST of a parcel's 1-3 cached id variants -- for Barnwell that is the
# digit-stripped 10-digit form ("0470303012"), not the portal's dashed
# "047-03-03-012". _norm_barnwell_pid redashes it; live-confirmed (owner
# surname RYAN's grid row is exactly "047-03-03-012", the predicted redash of
# board id "0470303012"). Williamsburg and Darlington carry the same small
# residual from the same cache effect (33 and ~30 rows respectively, out of
# ~2,950 and ~2,930) -- deliberately NOT normalized, too small a yield to
# justify a third near-duplicate function; those rows simply don't join, same
# as any other unmatched lead, not a false positive.
#
# ROLLBACK DETECTION (2026-11-05). The grid's Description column is a situs
# address or lot description for an ordinary bill ("148 COBB RD", "LOT #35
# SPT091-07"), but for a real agricultural-use change-of-use rollback bill it
# instead reads "<year> ROLLBACK TAX..." -- confirmed live, reproducing
# verification/verifiers/tax_lien_qpaybill.py's own prior finding (Calhoun map
# 053-00-01-112: three rows, "2022/2023/2024 ROLLBACK TAX...", Paid) and
# independently against that same parcel. See _parse_rows and
# enrich_qpaybill_tax for how it is read and stamped onto raw['rollback_exposure'].
#
# OUT: Anderson = 403 auth wall. Pickens = no bulk portal (qPublic per-parcel
# card only). SC PublicIndex = reachable but ToS-prohibits scraping.
QPAYBILL_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Spartanburg"): "spartanburgcountytax",
    ("SC", "Oconee"): "oconeesctax",
    ("SC", "Laurens"): "laurenstreasurer",
    ("SC", "Union"): "uniontreasurer",
    ("SC", "Cherokee"): "cherokeecountysctax",
    ("SC", "Williamsburg"): "williamsburgtreasurer",
    ("SC", "Darlington"): "darlingtontreasurer",
    ("SC", "Barnwell"): "barnwelltreasurer",
    ("SC", "Kershaw"): "kershawcounty",
}

# Statuses that count as an owed delinquent balance (exclude already-paid).
_OWED_STATUSES = ("unpaid", "sold at tax sale", "delinquent", "bankruptcy")
_TMS_RE = re.compile(r"\b\d-\d{2}-\d{2}-\d{3}\.\d{2}\b")
#: SC Code 12-43-220(d)(4) rollback lookback -- see enrichment_rollback_deferral.py's
#: module docstring (same constant, same citation, not re-derived).
_ROLLBACK_YEARS_SC = 3


def _norm_cherokee_pid(pid: str) -> str:
    """Re-dash a Cherokee parcel to the portal's Identification-No. format.

    Cherokee board parcels arrive two ways: already-dashed straight off the
    tax-sale PDF (``029-00-00-028.001``), or 13-digit NUMERIC from the court
    feed (``0020000003000`` via sc_public_index_lis_pendens). The qPayBill grid
    only ever shows the dashed ``NNN-NN-NN-NNN.NNN`` id, so a numeric board
    parcel never joins. Strip to digits and re-insert the fixed 3-2-2-3.3 dash
    pattern. Anything that isn't exactly 13 digits (already-dashed ids, or the
    rarer 16-digit sub-parcels) is returned unchanged — dashed ids already match
    and mangling them would only break a working join.
    """
    digits = re.sub(r"[^0-9]", "", pid or "")
    if len(digits) != 13:
        return pid
    return f"{digits[0:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:10]}.{digits[10:13]}"


def _norm_barnwell_pid(pid: str) -> str:
    """Re-dash a Barnwell parcel to the portal's Identification-No. format.

    Most Barnwell board parcels arrive already dashed, straight off the
    qPayBill delinquent-roll scraper (``047-07-09-005.01``). A large minority
    (819 of 2,059 board rows, 2026-11-05) instead come from
    sc_heir_estate_parcel_cache, which picks the SHORTEST of a parcel's 1-3
    cached id variants -- for Barnwell that is the digit-stripped 10-digit
    form (``0470303012``), not the portal's dashed ``NNN-NN-NN-NNN``. Strip to
    digits and re-insert the fixed 3-2-2-3 dash pattern. Anything that isn't
    exactly 10 digits (already-dashed ids, including a sub-parcel ``.NN``
    suffix) is returned unchanged -- live-confirmed 2026-11-05: searching
    owner surname RYAN returns grid Identification No. ``047-03-03-012``,
    exactly the redash of board id ``0470303012``.
    """
    digits = re.sub(r"[^0-9]", "", pid or "")
    if len(digits) != 10:
        return pid
    return f"{digits[0:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:10]}"


# (state, county-bare) -> parcel_id normalizer applied ONLY when building the
# TMS join index, so the board key matches the portal's Identification-No.
# Most counties store the dashed TMS already (identity); Cherokee and Barnwell
# need re-dash (see each normalizer's own docstring for which board source
# needs it and why).
PID_NORMALIZERS: dict[tuple[str, str], "callable"] = {
    ("SC", "Cherokee"): _norm_cherokee_pid,
    ("SC", "Barnwell"): _norm_barnwell_pid,
}


def _norm_pid(state: str, county_bare: str, pid: str) -> str:
    fn = PID_NORMALIZERS.get((state, county_bare))
    return fn(pid) if fn else pid


def _url(sub: str) -> str:
    return f"https://{sub}.qpaybill.com/Taxes/TaxesDefaultType4.aspx"


def _hidden(html: str, name: str) -> str:
    m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _parse_rows(html: str) -> list[dict]:
    """Parse the standardized qPayBill results grid into {tms, year, status,
    amount, description, rollback} rows. Columns are consistent across
    counties: 0 Receipt, 1 Name/Address, 2 Year, 3 Description, 4
    Identification No. (parcel id — format varies by county: dashed TMS in
    Spartanburg, plain numeric in Oconee), 5 Type, 6 Status, 7 Payment Date,
    8 Amount. Parse by POSITION, not by a county-specific id regex.

    `description` is the grid's own (often-truncated) Description cell, kept
    verbatim. `rollback` flags a real agricultural-use change-of-use rollback
    bill, whose Description reads "<year> ROLLBACK TAX..." instead of the
    usual situs-address/lot text — same field name and the same substring
    test verification/verifiers/tax_lien_qpaybill.py's own parse_grid()
    already uses for this identical grid ("ROLLBACK" in Description.upper()),
    confirmed live 2026-11-05 against Calhoun map 053-00-01-112.
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
        description = cells[3].strip()
        out.append({"tms": pid, "year": cells[2].strip(),
                    "status": cells[6].strip(), "amount": amt,
                    "description": description,
                    "rollback": "ROLLBACK" in description.upper()})
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
    counts = {"targets": 0, "queries": 0, "filled": 0, "misses": 0, "rollback_found": 0}
    if not _ENABLED:
        return counts

    # group in-scope, balance-less leads by (county-sub, surname); index by TMS
    by_query: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    tms_index: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    for li in listings:
        state = li.state or ""
        county_bare = (li.county or "").replace(" County", "").strip()
        sub = QPAYBILL_COUNTIES.get((state, county_bare))
        if not sub:
            continue
        if (li.raw or {}).get("tax_owed", {}).get("balance"):
            continue
        sn = _surname(li.owner_name or li.defendant)
        pid = (li.parcel_id or "").strip()
        if not sn or not pid:
            continue
        # index by the PORTAL id format so numeric board parcels (Cherokee)
        # still join the dashed grid Identification-No.
        pid_key = _norm_pid(state, county_bare, pid)
        by_query[(sub, sn)].append(li)
        tms_index[(sub, pid_key)].append(li)
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
                # aggregate owed + rollback rows per TMS. Rollback rows are
                # read from EVERY row regardless of status: rollback_exposure
                # records the FACT that a change-of-use rollback was billed,
                # not whether it is currently owed -- that part is already
                # covered by raw['tax_owed'] above whenever the same rollback
                # row is itself Unpaid/Sold at Tax Sale.
                owed: dict[str, dict] = {}
                rollback: dict[str, dict] = {}
                for row in rows:
                    if row.get("rollback"):
                        ragg = rollback.setdefault(row["tms"], {"amount": 0.0, "years": []})
                        ragg["amount"] += row["amount"]
                        if row["year"]:
                            ragg["years"].append(row["year"])
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
                for pid, ragg in rollback.items():
                    for li in tms_index.get((sub, pid), []):
                        raw = li.raw if isinstance(li.raw, dict) else {}
                        if isinstance(raw.get("rollback_exposure"), dict):
                            continue  # idempotent, matches every sibling rollback_exposure producer
                        raw["rollback_exposure"] = {
                            "rollback_already_billed": round(ragg["amount"], 2),
                            "rollback_billed_years": sorted(set(ragg["years"])),
                            "deferred_value": None,
                            "annual_deferred_tax": None,
                            "estimated_rollback": None,
                            "estimate_is_floor": None,
                            "tax_rate_source": "unavailable_grid_has_no_value_split",
                            "rollback_years": _ROLLBACK_YEARS_SC,
                            "basis": "agricultural_use_deferral",
                            "county": (li.county or "").replace(" County", "").strip(),
                            "state": li.state or "",
                            "source": f"qpaybill:{sub} (grid Description: '<year> ROLLBACK TAX...')",
                            "source_key": "qpaybill_grid_rollback",
                            "match_method": "parcel",
                        }
                        li.raw = raw
                        counts["rollback_found"] += 1

        await asyncio.gather(*(one(sub, sn) for sub, sn in queries))

    counts["misses"] = counts["targets"] - counts["filled"]
    log.info("qpaybill_tax.done", **counts)
    return counts
