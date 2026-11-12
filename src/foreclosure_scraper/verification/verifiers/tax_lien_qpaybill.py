"""tax_lien, SC counties on the qPayBill treasurer portal: is there a real delinquent property-tax
balance on this parcel?

The third tax_lien adapter (the reference is tax_lien_buncombe; docs/HANDOFF.md item 66). Same
SIGNAL, same GOVERNS, same verdict meanings, so its verdicts land in the one tax_lien ledger.

SOURCE. <tenant>.qpaybill.com/Taxes/TaxesDefaultType4.aspx, the county treasurer's own public
payment search (the one counties_sc.qpaybill_delinquent_roll enumerates; the tenant map is that
module's QPAYBILL_SUBS, 29 counties). An ASP.NET WebForms page: no login, no CAPTCHA, a session
cookie and a viewstate. NOT the SC Public Index (that one stays off-limits). The per-parcel
lookup, live-verified 2026-10-06:

    GET  the form                                    -> session cookie + viewstate
    POST __EVENTTARGET=ddlCriteriaList, Map Number   -> the criteria postback (a search posted
                                                        without it answers "No records matched"
                                                        even for a parcel on the roll)
    POST SearchType=Real Estate, Payment Status=All, Year=All, Search By=Map Number, <TMS>
        -> the grid: Notice | Name/Address | Year | Description | Identification No. | Type |
           Status (Unpaid / Paid / Sold at Tax Sale ...) | Payment Date | Amount
           every year on that map number, paid AND unpaid, sorted by identification number then
           year, newest first; 25 rows a page. The search also returns longer numbers that start
           with the same text ("45-338-010" brings "45-338-010.A"), so only rows whose
           identification number equals the one asked for are read.

One session per tenant and search criteria per sweep run (opened on the first row that needs it,
reused, re-opened after 15 minutes), so a parcel costs one request after two per county. Requests are one at a
time, paced by the sweep's Fetcher as ONE host for all tenants (fetch.SHARED_BACKENDS, 2.0 s).

TENANT HEALTH (v5, 2026-10-08). v4 condemned a tenant for the whole run on ONE generic error page
or two failures in a row, and its remaining rows answered tenant_unhealthy without a request. Two
things tripped it on the 10/8 sweep (6,000 rows, 2.5 h, 1,870 Spartanburg requests):
  * Horry (843 rows): the address binding posted Search By = "Address", which Horry's form does
    not offer (its list is Notice Number, Map Number, Owner Name, PIN, Tax ID); the server answers
    an unlisted dropdown value with GenericErrorPage.aspx, a per-request error, not an outage.
  * every other tenant (Spartanburg 288, Oconee 512, Union 57, Laurens 38, Calhoun, Clarendon):
    the whole vendor answered HTTP 503 or the generic error page in the same minute (18:34-18:35
    UTC; Clarendon on its first request of the run); six minutes later all 29 forms answered 200
    within a second. A vendor outage, not this sweep's pace on one tenant.
So now: (1) the criteria list each tenant's form offers is read when its first session opens and a
criteria it does not offer is never posted (CriteriaUnavailable: Horry has no address search, see
ADDRESS BINDING); (2) a transient failure (HTTP 408/429/5xx, the generic error page, a page with no
form, a timeout or connection error) is retried once after RETRY_BACKOFF_S (a Retry-After header is
honoured up to RETRY_AFTER_CAP_S); (3) a circuit breaker per tenant: TENANT_MAX_FAILURES failed
searches in a row OPEN it for COOLDOWN_BASE_S (doubling on each re-open, up to COOLDOWN_MAX_S;
the portal's own "site is currently off line" notice, Abbeville since 2026-10-08, opens it for
OFFLINE_COOLDOWN_S); while open, rows answer unconfirmed tenant_unhealthy without a request (a
cooldown ending within MAX_INLINE_WAIT_S is waited out); after it, ONE half-open search is let
through: success closes the circuit, failure re-opens it. Nothing condemns a tenant for the rest
of the run except HTTP 401/403 (a block is a wall: never retried in the run). (4) The evidence
names what happened: http_status, tenant_failure (http_503, generic_error_page, portal_offline,
timeout ...), tenant_state (closed / open / blocked) and retry_in_s. tenant_unhealthy (the
circuit is open), fetch_failed (this row's search failed twice, circuit still closed) and
address_search_failed are TRANSIENT_REASONS: the sweep re-checks them at the end of its run and
the ledger makes them due again after 6 hours, not 7 days.

WHICH ROWS. SC rows in a qPayBill county whose tax claim the county record can answer
(verifiers/_tax_common.py: a tax_lien/tax_sale listing type that is not a DEW / DOR lien, a
delinquency flag, or the roll's own qpaybill_roll block for this county). NC rows are never
touched (tax_lien_buncombe / tax_lien_ptscloud).

WHICH PARCEL. The claim's own identification number (the roll block's identification_no) and the
board's parcel_id (Cherokee's 13-digit numeric form re-dashed as enrichment_qpaybill_tax does; v4 also
re-dashes its 16-digit numeric SUB-ACCOUNTS, NNN-NN-NN-NNN.NNN.NNN, which that normalizer leaves as digits).
They differ on 3,995 of the roll's own rows (a resolver gave the row another parcel, often by a
road name), so when they differ BOTH are searched:
    both delinquent -> confirmed; neither -> stale/refuted read on the claim's parcel
    one delinquent, the other found and not -> unconfirmed (identity_conflict: which parcel the
        row really is cannot be told here, so nothing is decided and nothing suppressed)
    only one found -> decided on that one
Some tenants' grid identification number is not their Map Number (Horry shows the PIN in the
grid and searches the TMS; Orangeburg shows an account number). v5: a tenant whose form offers a
Search By option labelled "PIN" (Horry, Orangeburg; Lexington's "PIN" value is labelled "Decal
Number" and is not used) has an all-digit number searched by PIN first (live 2026-10-08: an
11-digit Horry PIN searched by PIN answers its whole bill history, 11 rows; the same number as a
Map Number answers "No records matched"; v4 answered 123 Horry rows parcel_not_found that way). When
neither finds the number, the claim's own bills are read by notice number instead (Search By =
Receipt Number, the block's notice_numbers, newest 2), which answers exactly the claimed bills.

ROLLBACK BILLS (v2). A rollback tax (a change of use, e.g. out of agricultural valuation) is a
separate bill whose Description says "<year> ROLLBACK TAX..." and that is filed under the year it
was BILLED: Calhoun's map 053-00-01-112 had its regular 2025 bill paid on time on 2025-12-08 and
three rollback bills (tax years 2022-2024) paid 2026-09-22, and the old verifier read all four as
"the 2025 bill" and called it stale. Now the regular bills decide stale / refuted on their own and
the rollback bills are read and reported separately (rollback_bills_checked). A regular bill paid
on time beside a rollback bill paid late cannot be called either way and is unconfirmed
(rollback_bills_mixed); an UNPAID rollback bill is still a delinquent balance (confirmed).

ADDRESS BINDING (v2). The grid's Name / Property Address cell names the property address under the
owner. Before a stale or refuted answer the account checked must be the one that carries the
row's address (2026-10-06 recheck: Union 2383 JONESVILLE HWY had been judged on two other parcels
while its own account, paid on time, was never delinquent; 844 RICE AVE EXT on a different account
than the one the address belongs to). A matching address on the bills binds. Otherwise the row's
address is searched (Search By = Property Address, "<number> <street>"): when the checked rows'
notice numbers are among the address's rows it is the same account; when they are not, the
ADDRESS'S rows decide instead (decided_on address_search), confirmed on an unpaid balance, stale
on a late payment, refuted when paid on time; an address with no rows of its own, or a full page
that may hide years, is unconfirmed (address_parcel_mismatch / page_capped). A row with no
house-numbered address has nothing to bind and is judged on its parcel as before.
v5: a tenant with no Property Address search (Horry) cannot run that search: the account's own
rows decide (address_binding no_address_search) unless they name another address (conflict) or
the account is a parcel a resolver attached to the row, which answer unconfirmed
(address_search_unavailable).

CONFIRMED IS BOUND TOO (v5). v4 confirmed on any delinquent balance of the parcel searched. When
that account's bills name a DIFFERENT house number on the row's own street
(_tax_common.other_number_same_street: a neighbor's parcel), or it is the board parcel a resolver
attached and its bills do not carry the row's address, the confirmed answer goes through the same
binding as stale / refuted: the address search, account_choice() (follow the address's own
account only with proof) and address_not_found / ambiguous_account. Never confirmed on a
neighbor's bills.

WHICH ACCOUNT, WHEN THE ADDRESS NAMES ANOTHER (v3). In v2 the address's rows decided whenever the
row's own account did not carry the address. That turned two Union SC rows from stale to refuted
on the strength of an account the two independent checks disagreed about (844 Rice Ave Ext: the
board / claim parcel paid its 2025 bill 2026-09-30 with a $2,336 penalty, the account the address
search returns paid on time; 2383 Jonesville Hwy: three parcel ids). When the portal names a REAL
other address for the row's own account and another account carries the row's address, the
address account decides only with proof the row's account is wrong (_tax_common.account_choice: a
resolver attached the board parcel, or the board owner matches the address account and not the
row's own); otherwise the verifier cannot tell which account is right and answers unconfirmed,
reason ambiguous_account, never stale or refuted. An account whose rows name no usable address
contradicts nothing (the address account decides, as in v2). The row's account names another
address and no account carries the row's: address_not_found.

TWO CLAIMS, THE PAYMENT HISTORY (v3; _tax_common, TWO CLAIMS). The grid holds every year's payment
date, so the history costs no request: the evidence records late_levy_years (regular bills of levy
2019 on paid after their deadline), the late payment dates per year and the chronic_claim judged
on them (confirmed at 3 late levy years, the scorer's tax_lien_chronic rule; `unknown` when the
history is partial: a claim read by receipt number, or a year with no readable payment).
`governs` is per record (governs_for): a parcel paid up today and paid late in most recent years is
refuted or stale for `tax_lien` and keeps `tax_lien_chronic`. stale: a claimed year, the latest
year, or a bill that was already delinquent when the board first saw the row (first_seen) was paid
late; refuted: those were paid on time.

SOLD AT TAX SALE (v4, 2026-10-07; observed live on Cherokee's portal, 3 requests: the land parcel of
229 Euphra Dr, map 052-00-00-013.010, shows Status "Sold at Tax Sale", Payment Date 11/04/24, for
tax years 2023 and 2024 with amounts $253.93 and $116.93, its 2025 bill "Paid" 03/25/26, while its
manufactured-home account .010.001 shows "Unpaid" for 2023-2025; the only statuses on that page are
Paid, Unpaid and Sold at Tax Sale; no Redeemed / Forfeited status was observed, so none is invented).
A sold row is its own state, not a payment: its Payment Date is the SALE date, not a payment, and
the sale is unresolved on the portal (the 12-month redemption period ended 11/04/25 and the portal
does not say whether the owner redeemed or the purchaser took the deed). So:
  * a Sold row of one of the last RECENT_SALE_YEARS eligible levies counts as the delinquent balance
    it is (as in v3) and the verdict carries reason sold_at_tax_sale beside the amounts, the years
    (sold_at_tax_sale_years) and the sale dates (sold_at_tax_sale_on);
  * a year with a Sold row is never judged paid or late (the 2025 bill that was paid late in March
    2026 on that same land parcel is not a reason for `stale`), and a recent Sold row stops stale and
    refuted altogether: with nothing else owed the answer is unconfirmed, reason sold_at_tax_sale,
    so the claim keeps scoring (a sold account whose row has no amount is the same);
  * a manufactured-home sub-account (ident NNN-NN-NN-NNN.NNN.NNN, the portal's STARTS-WITH search
    returns the land account's rows beside it) is read together with its land account:
    related_account in the evidence, and a recent sale of the land is the same machine reason.

VERDICTS (SC real-property tax is due January 15 of the next year, S.C. Code 12-45-70; unpaid
after it, penalties attach, so a levy-year Y bill is delinquent from January 16 of Y+1; a
deadline on a weekend rolls to Monday):
  confirmed    an Unpaid (or Delinquent / Bankruptcy) row of a delinquent-eligible year with an
               amount, or a Sold-at-Tax-Sale row of one of the last three eligible years (inside
               the 12-month redemption window); see identity_conflict above.
  stale        nothing delinquent today, and the claimed year (else the latest delinquent-eligible
               year) was paid after its deadline: the delinquency was real, paid since.
  refuted      nothing delinquent today and the year(s) checked were paid by the deadline.
  unconfirmed  no identifier, not on the portal, tenant unhealthy, page unreadable, a full page
               that may hide older years, billing ended before the latest eligible levy, no paid
               row to read, identity_conflict.
A row typed tax_lien by a DEW / DOR lien source that is covered through its own claim (a mixed
row) gets its verdict as is: the qualified GOVERNS (_tax_common) never ends that lien's listing
type.
Evidence (public ledger: a whitelist, no names, no addresses): the portal URL, tenant, the map
numbers searched and what each showed, per-year delinquent amounts, total, years, the
not-yet-delinquent current levy, tax-sale years, claimed years, the paid rows read (payment date,
deadline, late or not), and the county owner vs board owner CATEGORY only.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
import time
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v5"         # v5 (2026-10-08): tenant health is a circuit breaker with a half-open probe
                       # (never dead for the run on one error page or a vendor-wide minute of
                       # 503s), only the criteria a tenant's form offers are posted (Horry: no
                       # address search), Horry's PIN search, a confirmed answer is bound like a
                       # stale one when the bills name a neighbor's house number.
                       # v4 (2026-10-07): "Sold at Tax Sale" is its own state (never paid, late,
                       # stale or refuted; reason sold_at_tax_sale), the land account behind a
                       # sub-account (Cherokee .001) is read too, Cherokee's 16-digit sub-account
                       # parcels are re-dashed.
                       # v3 (2026-10-06): two claims judged apart (current vs chronic, the grid's
                       # whole payment history, per-record governs), stale for a claimed year / a
                       # bill delinquent at first_seen paid late, the address account decides only
                       # with proof (ambiguous_account / address_not_found), address-scoped
                       # ledger. v2: rollback bills judged apart; address binding
TTL_DAYS = 30
RETRY_DAYS = 7
#: answers about the portal's health, not the row (module doc, TENANT HEALTH; registry.py)
TRANSIENT_REASONS = ("tenant_unhealthy", "fetch_failed", "address_search_failed")
TRANSIENT_RETRY_DAYS = 0.25
SOURCE = "qpaybill.com"
GOVERNS = tc.GOVERNS          # tax_lien:property_tax, tax_sale:property_tax, ... (_tax_common)
governs_for = tc.governs_for  # per record: a confirmed chronic claim keeps tax_lien_chronic
priority = tc.flag_priority     # the "2+ years and $500" rows first within a tier
ROW_SUMMARY_EXCLUDE = ("owner_name",)

ROLL_SLUG = "counties_sc.qpaybill_delinquent_roll"
ROLL_KEY = "qpaybill_roll"
PAGE_CAP = 25
SESSION_MAX_AGE_S = 15 * 60
TENANT_MAX_FAILURES = 2        # failed searches in a row (each after its one retry) that open the circuit
RETRY_BACKOFF_S = 15.0         # pause before the one retry of a transient failure
RETRY_AFTER_CAP_S = 60.0       # a Retry-After header is honoured up to this
COOLDOWN_BASE_S = 60.0         # first open period of a tenant's circuit; doubles per re-open
COOLDOWN_MAX_S = 900.0
OFFLINE_COOLDOWN_S = 1800.0    # the portal's own "site is currently off line" notice
MAX_INLINE_WAIT_S = 20.0       # an open circuit about to half-open is waited out, not reported
GET_TIMEOUT_S = 45.0
POST_TIMEOUT_S = 60.0          # Darlington answers slowly but correctly (8028596d)
RECENT_SALE_YEARS = 3          # Sold-at-Tax-Sale rows still inside redemption

_NAME = __name__.rsplit(".", 1)[-1]

_CRITERIA = "ctl00$MainContent$ddlCriteriaList"
_GRID_ID = "ctl00_MainContent_gvSearchResults"
_NO_MATCH = "No records matched"


#: counties whose treasurer left qPayBill: the roll scraper still lists them, this verifier does not
#: (2026-10-08: abbevilletreasurer.qpaybill.com answers every request with Info.aspx, "Sorry the
#: site is currently off line."; the county's treasurer page links its PayStar search instead,
#: which tax_lien_paystar reads)
MOVED = {"abbeville": "taxes.paystar.io (tax_lien_paystar)"}


@lru_cache(maxsize=1)
def tenants() -> dict[str, tuple[str, str]]:
    """{county lowercased: (County, qpaybill subdomain)} from the roll scraper's QPAYBILL_SUBS,
    without the MOVED counties."""
    from ...scrapers.counties_sc.qpaybill_delinquent_roll import QPAYBILL_SUBS
    return {c.strip().lower(): (c, s) for c, s in QPAYBILL_SUBS.items()
            if c.strip().lower() not in MOVED}


def form_url(sub: str) -> str:
    return f"https://{sub}.qpaybill.com/Taxes/TaxesDefaultType4.aspx"


# ---------------------------------------------------------------------------
# which rows, which parcels (pure)
# ---------------------------------------------------------------------------

def tenant_of(row: Any) -> Optional[tuple[str, str]]:
    if str(tc.g(row, "state") or "").strip().upper() != "SC":
        return None
    return tenants().get(str(tc.g(row, "county") or "").strip().lower())


def roll_block(row: Any) -> Optional[dict]:
    """The roll's block when it is about this row's county (94 board rows carry another
    county's block after a merge; those are not this row's claim)."""
    b = tc.raw_of(row).get(ROLL_KEY)
    if not isinstance(b, dict) or not b.get("identification_no"):
        return None
    if str(b.get("county") or "").strip().lower() != str(tc.g(row, "county") or "").strip().lower():
        return None
    return b


def applies(row: dict) -> bool:
    return tenant_of(row) is not None and tc.claims_property_tax(row, roll_block(row) is not None)


def board_parcel(row: Any, county: str) -> Optional[str]:
    pid = str(tc.g(row, "parcel_id") or "").strip()
    if not pid:
        return None
    try:
        from ...enrichment_qpaybill_tax import _norm_pid     # Cherokee: 13 digits -> dashed TMS
        pid = _norm_pid("SC", county, pid)
    except Exception:  # noqa: BLE001
        pass
    digits = re.sub(r"[^0-9]", "", pid or "")
    if county.strip().lower() == "cherokee" and len(digits) == 16 and digits == pid:
        # a numeric SUB-ACCOUNT (the manufactured home on a land parcel): NNN-NN-NN-NNN.NNN.NNN;
        # _norm_pid leaves a 16-digit id as it is, and a search for it finds nothing (v4)
        pid = f"{digits[0:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:10]}.{digits[10:13]}.{digits[13:16]}"
    return pid or None


def subjects(row: Any, county: str) -> list[tuple[str, str]]:
    """[(map number, 'claim' | 'board')]: the claim's own identification number first."""
    blk = roll_block(row)
    out: list[tuple[str, str]] = []
    if blk:
        out.append((str(blk["identification_no"]).strip(), "claim"))
    bp = board_parcel(row, county)
    if bp and all(tc.alnum(bp) != tc.alnum(v) for v, _ in out):
        out.append((bp, "board"))
    return [(v, r) for v, r in out if tc.alnum(v) and set(tc.alnum(v)) != {"0"}]


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    blk = roll_block(row)
    if blk:
        years.update(tc.to_int(y) for y in blk.get("years_unpaid") or [])
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_HIDDEN = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


def viewstate(text: str) -> dict:
    out = {}
    for n in _HIDDEN:
        m = re.search(rf'id="{n}"[^>]*value="([^"]*)"', text)
        out[n] = m.group(1) if m else ""
    return out


def _fields(value: str, criteria: str = "Map") -> dict:
    return {"ctl00$MainContent$SearchType": "radRealEstateButton",
            "ctl00$MainContent$PaidStatus": "radAllPaymentsButton",
            "ctl00$MainContent$ddlYearList": "All",
            _CRITERIA: criteria,
            "ctl00$MainContent$txtCriteriaBox": value}


def criteria_data(state: dict, criteria: str = "Map") -> dict:
    return {"__EVENTTARGET": _CRITERIA, "__EVENTARGUMENT": "", "__LASTFOCUS": "", **state,
            **_fields("", criteria)}


def search_data(state: dict, value: str, criteria: str = "Map") -> dict:
    return {"__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "", **state,
            **_fields(value, criteria), "ctl00$MainContent$btnSearch": "Search"}


def _clean(x: str) -> str:
    x = re.sub(r"(?i)<br\s*/?>", "\n", x)
    x = _html.unescape(re.sub(r"<[^>]+>", " ", x))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", p).strip() for p in x.split("\n")).strip()


def _date(s: str) -> Optional[date]:
    s = (s or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _amount(s: str) -> Optional[float]:
    m = re.search(r"\$?\s*([\d,]+\.\d{2})", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_grid(text: str) -> dict:
    """{'rows': [...], 'no_match': bool, 'grid': bool} from a search answer. Every row, paid or
    not (the roll scraper's parse_grid keeps owed rows only)."""
    no_match = _NO_MATCH in text
    i = text.find(f'id="{_GRID_ID}"')
    if i < 0:
        return {"rows": [], "no_match": no_match, "grid": False}
    j = text.find("</table>", i)          # the pager's own table, if any, comes after the rows
    table = text[i: j if j > 0 else len(text)]
    rows = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table):
        tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)
        if len(tds) < 9:
            continue
        c = [_clean(t) for t in tds]
        year = tc.to_int(c[2])
        if not 1900 < year < 2100 or not c[4]:
            continue
        lines = [ln for ln in c[1].split("\n") if ln.strip()]
        rows.append({"notice": c[0] or None, "owner": (c[1].split("\n")[0] or None),
                     "address": lines[-1] if len(lines) >= 2 else None,
                     "description": c[3] or None, "rollback": "ROLLBACK" in c[3].upper(),
                     "year": year, "ident": c[4], "type": c[5], "status": c[6],
                     "paid_on": _date(c[7]), "amount": _amount(c[8])})
    return {"rows": rows, "no_match": no_match and not rows, "grid": True}


# ---------------------------------------------------------------------------
# the rules (pure)
# ---------------------------------------------------------------------------

def deadline(year: int) -> date:
    """The last day a levy-year bill is paid on time: January 15 of the next year (S.C. Code
    12-45-70), a weekend rolled to Monday."""
    return tc.next_weekday(date(year + 1, 1, 15))


def is_eligible(year: int, today: date) -> bool:
    return today > deadline(year)


def latest_eligible(today: date) -> int:
    return today.year - 1 if is_eligible(today.year - 1, today) else today.year - 2


def _kind(status: str) -> str:
    s = (status or "").strip().lower()
    if "sold" in s:
        return "sold"
    if "unpaid" in s or "delinquent" in s or "bankrupt" in s:
        return "owed"
    if s == "paid" or s.startswith("paid"):
        return "paid"
    return "other"


def select_rows(rows: list[dict], ident: str, notices: Optional[set] = None) -> list[dict]:
    """The rows of exactly this identification number (and, for a receipt search, of exactly
    these notice numbers)."""
    want = tc.alnum(ident)
    out = [r for r in rows if tc.alnum(r["ident"]) == want]
    if notices is not None:
        out = [r for r in out if tc.alnum(r["notice"]) in notices]
    return out


def assess(mine: list[dict], today: date) -> dict:
    """What the portal's rows say about one parcel (or one parcel's claimed bills)."""
    out: dict[str, Any] = {"found": bool(mine), "rows": len(mine)}
    if not mine:
        return out
    last_ok = latest_eligible(today)
    delinquent: dict[int, float] = {}
    current: dict[int, float] = {}
    sold: list[int] = []
    sold_on: list[str] = []
    recent_unpriced: list[int] = []
    for r in mine:
        k, y, amt = _kind(r["status"]), r["year"], r["amount"] or 0.0
        if k == "owed" and amt > 0:
            if is_eligible(y, today):
                delinquent[y] = round(delinquent.get(y, 0.0) + amt, 2)
            else:
                current[y] = round(current.get(y, 0.0) + amt, 2)
        elif k == "sold":
            # "Sold at Tax Sale": its Payment Date is the SALE date, not a payment (v4)
            sold.append(y)
            if r.get("paid_on"):
                sold_on.append(r["paid_on"].isoformat())
            if y > last_ok - RECENT_SALE_YEARS:
                if amt > 0:
                    delinquent[y] = round(delinquent.get(y, 0.0) + amt, 2)
                else:
                    recent_unpriced.append(y)
    out.update(latest_levy_year=max(r["year"] for r in mine),
               delinquent_by_year={str(y): a for y, a in sorted(delinquent.items(), reverse=True)},
               not_yet_delinquent_due={str(y): a for y, a in sorted(current.items(), reverse=True)},
               owners=[r["owner"] for r in sorted(mine, key=lambda r: -r["year"])[:2]])
    if sold:
        out["sold_at_tax_sale_years"] = sorted(set(sold), reverse=True)
        out["sold_at_tax_sale_on"] = sorted(set(sold_on))[-4:]
        out["sold_recent"] = any(y > last_ok - RECENT_SALE_YEARS for y in sold)
        out["_sold_years"] = set(sold)
    if recent_unpriced:
        out["sold_unpriced"] = sorted(set(recent_unpriced), reverse=True)
    by_year: dict[int, list[dict]] = {}
    rb_by_year: dict[int, list[dict]] = {}
    for r in mine:
        (rb_by_year if r.get("rollback") else by_year).setdefault(r["year"], []).append(r)
    out["_by_year"] = by_year             # regular bills: they decide stale / refuted
    out["_rb_by_year"] = rb_by_year       # rollback bills: read and reported apart (v2)
    out["_rows"] = mine
    return out


def page_capped(rows: list[dict], ident: str, capped: bool) -> bool:
    """A full page whose last row is still this parcel may hide its older years on page 2."""
    return bool(capped and rows and tc.alnum(rows[-1]["ident"]) == tc.alnum(ident))


def paid_check(by_year: dict, year: int) -> Optional[dict]:
    """The year's paid rows: late (after the deadline) or on time; None when none is readable."""
    paid = [r for r in by_year.get(year, []) if _kind(r["status"]) == "paid" and r["paid_on"]]
    if not paid:
        return None
    dl = deadline(year)
    last = max(r["paid_on"] for r in paid)
    return {"year": year, "status": "Paid", "paid_on": last.isoformat(), "deadline": dl.isoformat(),
            "paid_late": last > dl}


def late_payments(by_year: dict, year: int) -> list[str]:
    """The dates (ISO, oldest first) of the year's payments made after its deadline."""
    dl = deadline(year)
    return sorted({r["paid_on"].isoformat() for r in by_year.get(year, [])
                   if _kind(r["status"]) == "paid" and r["paid_on"] and r["paid_on"] > dl})


# ---------------------------------------------------------------------------
# the tenant sessions (one per county and search criteria per sweep run) and their health
# ---------------------------------------------------------------------------

@dataclass
class Health:
    """What one failed request said about the tenant (module doc, TENANT HEALTH)."""
    kind: str                           # http_503, generic_error_page, portal_offline, timeout ...
    http_status: Optional[int] = None   # the HTTP status the portal answered, None for no answer
    retry_after_s: Optional[float] = None
    transient: bool = True              # worth one retry after a pause
    blocked: bool = False               # 401 / 403: a wall, never retried in the run

    def text(self) -> str:
        return self.kind if self.http_status in (None, 200) or self.kind.startswith("http_") \
            else f"{self.kind} (HTTP {self.http_status})"


class SourceFailure(RuntimeError):
    """One search failed (after its retry) and the tenant's circuit is still closed."""

    def __init__(self, health: Health) -> None:
        super().__init__(health.text())
        self.health = health

    def evidence(self) -> dict:
        return {"tenant_health": self.health.text(), "http_status": self.health.http_status,
                "tenant_failure": self.health.kind, "tenant_state": "closed"}


class TenantDown(RuntimeError):
    """The tenant's circuit is open (or the tenant blocked us): no request is made for the row."""

    def __init__(self, health: Health, state: str = "open", retry_in_s: Optional[float] = None,
                 failures: int = 0) -> None:
        self.health, self.state, self.failures = health, state, failures
        self.retry_in_s = None if retry_in_s is None else max(0, int(round(retry_in_s)))
        when = "" if self.retry_in_s is None else f", half-open in {self.retry_in_s} s"
        super().__init__(f"{health.text()}: circuit {state}{when}")

    def evidence(self) -> dict:
        return {"tenant_health": str(self)[:200], "http_status": self.health.http_status,
                "tenant_failure": self.health.kind, "tenant_state": self.state,
                "retry_in_s": self.retry_in_s}


class CriteriaUnavailable(LookupError):
    """The tenant's form does not offer this Search By option (Horry has no Property Address):
    nothing was posted, the tenant is healthy."""


class _Session:
    def __init__(self) -> None:
        self.cm: Any = None
        self.session: Any = None
        self.state: dict = {}
        self.opened = 0.0


class _Tenant:
    def __init__(self, county: str, sub: str) -> None:
        self.county, self.sub, self.url = county, sub, form_url(sub)
        self.sessions: dict[str, _Session] = {}
        self.lock = asyncio.Lock()
        self.cache: dict[tuple[str, str], dict] = {}
        self.offered: Optional[dict[str, str]] = None    # Search By value -> label, from the form
        # the circuit breaker (module doc, TENANT HEALTH)
        self.failures = 0                    # failed searches in a row
        self.open_until = 0.0                # monotonic; > now: open, no request
        self.trips = 0                       # times opened since the last success
        self.half_open = False               # the next search is the one probe
        self.blocked: Optional[Health] = None
        self.last: Optional[Health] = None


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


async def _sleep(seconds: float) -> None:
    """Every pause of the health logic (a test replaces it to record the pauses)."""
    await asyncio.sleep(seconds)


def _tenant(client: Any, county: str, sub: str) -> _Tenant:
    try:
        per_run = _RUNS.setdefault(client, {})
    except TypeError:                                   # not weak-referenceable: no sharing
        per_run = {}
    t = per_run.get(sub)
    if t is None:
        t = per_run[sub] = _Tenant(county, sub)
    return t


_OFFLINE = re.compile(r"currently\s+off\s*line|site is (?:currently )?(?:down|unavailable)", re.I)
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _retry_after(resp: Any) -> Optional[float]:
    v = (getattr(resp, "headers", None) or {}).get("retry-after")
    try:
        return max(0.0, float(str(v).strip())) if v not in (None, "") else None
    except ValueError:
        return None                       # an HTTP-date: fall back to our own backoff


def _problem(resp: Any) -> Optional[Health]:
    """What is wrong with a portal answer, or None for a usable page."""
    st = int(resp.status)
    if st in (401, 403):
        return Health(f"http_{st}", st, transient=False, blocked=True)
    if st >= 400:
        return Health(f"http_{st}", st, retry_after_s=_retry_after(resp),
                      transient=st in _RETRYABLE_STATUS or st >= 500)
    url = str(resp.url).lower()
    if "genericerrorpage" in url or "GenericErrorPage" in resp.text[:20000]:
        return Health("generic_error_page", st)
    if url.rstrip("/").endswith("/info.aspx") or _OFFLINE.search(resp.text[:20000]):
        # "Sorry the site is currently off line." (Abbeville, 2026-10-08): the portal says so
        return Health("portal_offline", st, transient=False)
    if "__VIEWSTATE" not in resp.text:
        return Health("no_form_on_page", st)
    return None


def _exc_health(exc: BaseException) -> Health:
    name = type(exc).__name__
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in name.lower() \
            or "timed out" in str(exc).lower():
        return Health("timeout")
    return Health(f"request_error:{name}"[:60])


class _Failed(RuntimeError):
    def __init__(self, health: Health) -> None:
        super().__init__(health.text())
        self.health = health


def offered_criteria(text: str) -> dict[str, str]:
    """{Search By value: label} of the tenant form's criteria list ({} when there is none)."""
    m = re.search(r'name="ctl00\$MainContent\$ddlCriteriaList"[^>]*>(.*?)</select>', text, re.S)
    if not m:
        return {}
    return {v: _html.unescape(lbl).strip() for v, lbl in
            re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', m.group(1))}


def pin_search_offered(t: _Tenant) -> bool:
    """The tenant offers a Search By option that IS a parcel PIN (value "PIN" labelled "PIN":
    Horry, Orangeburg; Lexington's "PIN" value is labelled "Decal Number")."""
    return bool(t.offered) and (t.offered.get("PIN") or "").strip().upper() == "PIN"


async def _close(s: _Session) -> None:
    cm, s.cm, s.session = s.cm, None, None
    if cm is not None:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


async def _open(t: _Tenant, s: _Session, client: Any, criteria: str) -> None:
    await _close(s)
    s.cm = client.form_session()
    s.session = await s.cm.__aenter__()
    r = await s.session.get(t.url, timeout=GET_TIMEOUT_S)
    if (p := _problem(r)) is not None:
        raise _Failed(p)
    if _CRITERIA not in r.text:
        raise _Failed(Health("no_search_form", int(r.status)))
    offered = offered_criteria(r.text)
    if offered:
        t.offered = offered
    if t.offered is not None and criteria not in t.offered:
        raise CriteriaUnavailable(criteria)
    r = await s.session.post_form(t.url, criteria_data(viewstate(r.text), criteria),
                                  timeout=POST_TIMEOUT_S)
    if (p := _problem(r)) is not None:
        raise _Failed(p)
    s.state = viewstate(r.text)
    s.opened = time.monotonic()


async def _search_once(t: _Tenant, s: _Session, client: Any, criteria: str, value: str
                       ) -> tuple[dict, Any]:
    if s.session is None or time.monotonic() - s.opened > SESSION_MAX_AGE_S:
        await _open(t, s, client, criteria)
    r = await s.session.post_form(t.url, search_data(s.state, value, criteria),
                                  timeout=POST_TIMEOUT_S)
    if (p := _problem(r)) is not None:
        raise _Failed(p)
    g = parse_grid(r.text)
    if not g["grid"] and not g["no_match"]:
        raise _Failed(Health("search_answer_unreadable", int(r.status)))
    return g, r


async def _gate(t: _Tenant) -> None:
    """Let a search through, or raise TenantDown while the tenant's circuit is open. An open
    circuit about to half-open (within MAX_INLINE_WAIT_S) is waited out; after the cooldown the
    next search is the one half-open probe."""
    if t.blocked is not None:
        raise TenantDown(t.blocked, "blocked", None, t.failures)
    if t.open_until:
        wait = t.open_until - time.monotonic()
        if wait > MAX_INLINE_WAIT_S:
            raise TenantDown(t.last or Health("unknown"), "open", wait, t.failures)
        if wait > 0:
            await _sleep(wait)
        t.open_until = 0.0
        t.half_open = True


def _record_failure(t: _Tenant, h: Health) -> None:
    """Count a failed search; open the circuit at TENANT_MAX_FAILURES in a row, on a failed
    half-open probe, or on the portal's offline notice."""
    t.last = h
    t.failures += 1
    if h.blocked:
        t.blocked = h
        return
    if t.half_open or h.kind == "portal_offline" or t.failures >= TENANT_MAX_FAILURES:
        t.trips += 1
        cool = OFFLINE_COOLDOWN_S if h.kind == "portal_offline" else \
            min(COOLDOWN_BASE_S * 2 ** (t.trips - 1), COOLDOWN_MAX_S)
        if h.retry_after_s:
            cool = max(cool, min(h.retry_after_s, COOLDOWN_MAX_S))
        t.open_until = time.monotonic() + cool
    t.half_open = False


async def search(client: Any, county: str, sub: str, value: str, criteria: str = "Map") -> dict:
    """The grid for one search (cached for the run). Raises CriteriaUnavailable when the tenant's
    form does not offer `criteria`, TenantDown when its circuit is open (or this failure opened
    it), SourceFailure when this search failed twice and the circuit is still closed."""
    t = _tenant(client, county, sub)
    async with t.lock:
        key = (criteria, value)
        if key in t.cache:
            return t.cache[key]
        if t.offered is not None and criteria not in t.offered:
            raise CriteriaUnavailable(criteria)
        await _gate(t)
        probe = t.half_open
        s = t.sessions.setdefault(criteria, _Session())
        retried = False
        while True:
            try:
                g, r = await _search_once(t, s, client, criteria, value)
                break
            except CriteriaUnavailable:
                await _close(s)
                raise
            except _Failed as f:
                h = f.health
            except Exception as exc:  # noqa: BLE001 - a timeout, a connection error, no recording
                h = _exc_health(exc)
            await _close(s)                 # a fresh session for the next attempt
            if h.transient and not h.blocked and not retried and not probe:
                retried = True
                pause = RETRY_BACKOFF_S if h.retry_after_s is None \
                    else min(h.retry_after_s, RETRY_AFTER_CAP_S)
                if pause > 0:
                    await _sleep(pause)
                continue
            _record_failure(t, h)
            if t.blocked is not None:
                raise TenantDown(h, "blocked", None, t.failures)
            if t.open_until:
                raise TenantDown(h, "open", t.open_until - time.monotonic(), t.failures)
            raise SourceFailure(h)
        t.failures, t.trips, t.open_until, t.half_open = 0, 0, 0.0, False
        new = viewstate(r.text)
        if new.get("__VIEWSTATE"):
            s.state = new
        out = {"rows": g["rows"], "no_match": g["no_match"], "capped": len(g["rows"]) >= PAGE_CAP}
        t.cache[key] = out
        return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "tenant", "county", "searched", "decided_on", "delinquent_parcel",
         "claim_ident", "address_relation", "address_binding", "address_matches",
         "rollback_bills_checked", "board_parcel", "latest_levy_year", "latest_delinquent_eligible_levy",
         "delinquent_by_year", "total_delinquent", "years_delinquent", "under_500", "de_minimis",
         "not_yet_delinquent_due", "sold_at_tax_sale_years", "sold_at_tax_sale_on", "related_account",
         "claimed_years", "bills_checked",
         "owner_match", "note", "error", "tenant_health", "followed_because",
         "address_owner_match", "history_from_levy", "history_years_read", "history_complete",
         "late_levy_years", "late_payment_dates", "chronic_claim", "current_claim_basis",
         # v5: what the portal answered when it failed (module doc, TENANT HEALTH), and why a
         # confirmed answer was bound to the row's address first
         "http_status", "tenant_failure", "tenant_state", "retry_in_s", "bound_because")
_SEARCHED_KEYS = ("map_number", "receipt", "role", "found", "rows", "latest_levy_year",
                  "delinquent_by_year", "not_yet_delinquent_due", "sold_at_tax_sale_years",
                  "page_capped", "searched_by")
_RELATED_KEYS = ("map_number", "rows", "latest_levy_year", "delinquent_by_year",
                 "sold_at_tax_sale_years", "sold_at_tax_sale_on")
#: a manufactured-home sub-account of a land parcel: NNN-NN-NN-NNN.NNN.NNN (Cherokee); its land
#: account is the same number without the last segment
_SUBACCOUNT = re.compile(r"^(.+\.\d{3})\.\d{3}$")
MAX_RECEIPTS = 2


def public_evidence(ev: dict) -> dict:
    out = tc.pick(ev, _KEYS)
    if isinstance(out.get("searched"), list):
        out["searched"] = [tc.pick(s, _SEARCHED_KEYS) for s in out["searched"]]
    if isinstance(out.get("related_account"), dict):
        out["related_account"] = tc.pick(out["related_account"], _RELATED_KEYS)
    return out


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


def _down(ev: dict, searched: list, exc: BaseException, reason: str) -> VerificationResult:
    """An unconfirmed answer about the portal's health (TenantDown / SourceFailure)."""
    extra = exc.evidence() if hasattr(exc, "evidence") else {
        "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    if isinstance(exc, TenantDown):
        reason = "tenant_unhealthy"
    return _res("unconfirmed", dict(ev, reason=reason, searched=searched, **extra))


def claim_receipts(row: Any) -> list[str]:
    """The roll block's notice numbers, newest first (the block lists them oldest first)."""
    blk = roll_block(row) or {}
    return [str(n).strip() for n in reversed(blk.get("notice_numbers") or []) if str(n).strip()]


def _decide_paid(a: dict, claimed: list[int], today: date, first_seen: Optional[date] = None
                 ) -> tuple[str, list[dict], list[dict], dict]:
    """('stale' | 'refuted' | 'mixed' | 'none', regular checks, rollback checks, history) on one
    parcel with nothing delinquent. The regular bills decide; the rollback bills (Description
    "<year> ROLLBACK TAX") are checked apart: a regular bill on time beside a rollback paid late
    is 'mixed' (unconfirmed), and a parcel with only rollback rows is judged on them.

    v3: stale also when a payment of a bill that was already delinquent the day the board first
    saw the row (`first_seen`) is dated on or after that day, and the history (the grid already
    holds every year, so reading it costs no request): {late_levy_years, late_payment_dates,
    years_read, readable} over the regular bills of levy HISTORY_FROM_LEVY on."""
    by_year = a.get("_by_year") or {}
    sold_years = a.get("_sold_years") or set()
    # the claimed years, then the two latest delinquent-eligible ones
    order = [y for y in claimed if is_eligible(y, today) and y in by_year]
    for y in sorted((y for y in by_year if is_eligible(y, today)), reverse=True)[:2]:
        if y not in order:
            order.append(y)
    checks = []
    verdict = "none"
    for y in order[:4]:
        if y in sold_years:                  # v4: a year sold at tax sale is neither paid nor late
            checks.append({"year": y, "status": "Sold at Tax Sale", "paid_late": None})
            continue
        c = paid_check(by_year, y)
        if c is None:
            kinds = sorted({r["status"] for r in by_year.get(y, [])})
            checks.append({"year": y, "status": ", ".join(kinds) or None, "paid_late": None})
            continue
        checks.append(c)
        if c["paid_late"]:
            verdict = "stale"
            break
    if verdict == "none" and any(c.get("paid_late") is False for c in checks):
        verdict = "refuted"
    # the payment history, every delinquent-eligible regular year from HISTORY_FROM_LEVY on
    window = sorted(y for y in by_year if is_eligible(y, today) and y not in sold_years
                    and (y >= tc.HISTORY_FROM_LEVY or y in claimed))
    hist_checks = {y: paid_check(by_year, y) for y in window}
    late = {y: late_payments(by_year, y) for y, c in hist_checks.items() if c and c["paid_late"]}
    hist = {"late_levy_years": sorted(late),
            "late_payment_dates": {str(y): late[y][:4] for y in sorted(late)},
            "years_read": sum(1 for c in hist_checks.values() if c),
            "readable": all(c is not None for c in hist_checks.values())
            and not any(y in sold_years and y >= tc.HISTORY_FROM_LEVY and is_eligible(y, today)
                        for y in by_year)}
    seen = [y for y, dates in late.items() if tc.paid_after_seen(
        first_seen, deadline(y) + timedelta(days=1), dates[-1])]
    if seen and verdict in ("refuted", "none"):
        verdict = "stale"
        hist["paid_late_after_first_seen"] = sorted(seen)
    rb = a.get("_rb_by_year") or {}
    rb_checks = []
    for y in sorted((y for y in rb if is_eligible(y, today)), reverse=True)[:4]:
        c = paid_check(rb, y)
        rb_checks.append(c or {"year": y, "status": "unread", "paid_late": None})
    rb_late = any(c.get("paid_late") for c in rb_checks)
    rb_ok = any(c.get("paid_late") is False for c in rb_checks)
    if verdict == "refuted" and rb_late:
        verdict = "mixed"
    elif verdict == "none" and rb_checks:
        verdict = "stale" if rb_late else "refuted" if rb_ok else "none"
    return verdict, checks, rb_checks, hist


async def _lookup(client: Any, county: str, sub: str, value: str, role: str, today: date,
                  *, criteria: str = "Map", notices: Optional[set] = None) -> dict:
    g = await search(client, county, sub, value, criteria)
    if criteria in ("Map", "PIN"):
        mine = select_rows(g["rows"], value)
    else:                       # a receipt answers one bill; its row names the claim's ident
        mine = [r for r in g["rows"] if tc.alnum(r["notice"]) in (notices or set())]
    a = assess(mine, today)
    a["role"] = role
    if criteria in ("Map", "PIN"):
        a["map_number"] = value
        a["searched_by"] = criteria
        a["page_capped"] = page_capped(g["rows"], value, g["capped"]) if mine else False
    else:
        a["receipt"] = value
    return a


def _digits_only(value: str) -> bool:
    return bool(re.fullmatch(r"\d{6,}", str(value or "").strip()))


async def _find(client: Any, county: str, sub: str, value: str, role: str, today: date
                ) -> list[dict]:
    """The searches for one identification number, first found last: by PIN first when the
    tenant offers a real PIN search and the number is all digits (Horry), else by Map Number and
    then, if the form turned out to offer a PIN search, by PIN (v5)."""
    t = _tenant(client, county, sub)
    out: list[dict] = []
    if _digits_only(value) and pin_search_offered(t):
        out.append(await _lookup(client, county, sub, value, role, today, criteria="PIN"))
        if out[-1]["found"]:
            return out
    out.append(await _lookup(client, county, sub, value, role, today, criteria="Map"))
    if not out[-1]["found"] and _digits_only(value) and pin_search_offered(t) \
            and not any(a.get("searched_by") == "PIN" for a in out):
        out.append(await _lookup(client, county, sub, value, role, today, criteria="PIN"))
    return out


def parent_ident(ident: Any) -> Optional[str]:
    """The land account behind a sub-account number ('052-00-00-013.010.001' -> '052-00-00-013.010'),
    else None."""
    m = _SUBACCOUNT.match(str(ident or "").strip())
    return m.group(1) if m else None


async def _related_account(client: Any, county: str, sub: str, a: dict, today: date) -> Optional[dict]:
    """The assessment of the land account behind the sub-account `a` was read for (one search, the
    portal's STARTS-WITH search also returns the sub-account's rows), or None. Evidence only: a
    failure here never changes a verdict."""
    parent = parent_ident(a.get("map_number"))
    if not parent:
        return None
    try:
        g = await search(client, county, sub, parent)
    except Exception:  # noqa: BLE001
        return None
    mine = select_rows(g["rows"], parent)
    if not mine:
        return None
    ra = assess(mine, today)
    ra["map_number"] = parent
    return ra


def neighbor_risk(row: Any, a: dict) -> Optional[str]:
    """Why a DELINQUENT account must be bound to the row's address before it confirms (v5,
    CONFIRMED IS BOUND TOO), or None: its bills name another house number on the row's street
    (other_number_same_street), or it is the board parcel a resolver attached and no bill carries
    the row's address (resolver_parcel)."""
    addr = row.get("street_address") if isinstance(row, dict) else None
    if tc.address_query(addr) is None:
        return None
    addrs = [r.get("address") for r in a.get("_rows") or [] if r.get("address")]
    if any(tc.address_relation(addr, x) == "match" for x in addrs):
        return None
    if any(tc.other_number_same_street(addr, x) for x in addrs):
        return "other_number_same_street"
    if a.get("role") == "board" and tc.parcel_resolved(row):
        return "resolver_parcel"
    return None


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    ten = tenant_of(row)
    claimed = claimed_years(row)
    if ten is None:
        return _res("unconfirmed", {"reason": "no_qpaybill_tenant", "claimed_years": claimed})
    county, sub = ten
    url = form_url(sub)
    subs = subjects(row, county)
    blk = roll_block(row)
    claim_ident = (blk or {}).get("identification_no")
    ev: dict[str, Any] = {"url": url, "tenant": sub, "county": county, "claimed_years": claimed,
                          "claim_ident": claim_ident, "board_parcel": board_parcel(row, county)}
    if not subs:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))

    found: dict[str, dict] = {}
    searched: list[dict] = []
    try:
        for value, role in subs:
            tries = await _find(client, county, sub, value, role, today)
            searched.extend(tries)
            if tries[-1]["found"]:
                found[role] = tries[-1]
            elif role == "claim":
                # Some tenants' grid identification number is not their Map Number (Orangeburg
                # shows an account number): read the claim's own bills by notice number instead.
                for rc in claim_receipts(row)[:MAX_RECEIPTS]:
                    ra = await _lookup(client, county, sub, rc, "claim_receipt", today,
                                       criteria="Receipt", notices={tc.alnum(rc)})
                    searched.append(ra)
                    if ra["found"]:
                        prev = found.get("claim")
                        if prev is None:
                            found["claim"] = dict(ra, via_receipts=True)
                        else:           # merge two receipts of the same claim
                            merged = dict(prev)
                            for k in ("delinquent_by_year", "not_yet_delinquent_due"):
                                merged[k] = {**prev.get(k, {}), **ra.get(k, {})}
                            merged["_by_year"] = {**prev.get("_by_year", {}),
                                                  **ra.get("_by_year", {})}
                            merged["_rb_by_year"] = {**prev.get("_rb_by_year", {}),
                                                     **ra.get("_rb_by_year", {})}
                            merged["_rows"] = [*prev.get("_rows", []), *ra.get("_rows", [])]
                            merged["latest_levy_year"] = max(prev["latest_levy_year"],
                                                             ra["latest_levy_year"])
                            found["claim"] = merged
    except (TenantDown, SourceFailure) as exc:
        return _down(ev, searched, exc, "fetch_failed")
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed", searched=searched,
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["searched"] = searched
    if not found:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))

    claim, board = found.get("claim"), found.get("board")
    primary = claim or board
    claim_via = "claim_receipts" if (claim or {}).get("via_receipts") else "claim_ident"
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), primary.get("owners") or [])
    dl_claim = bool(claim and claim["delinquent_by_year"])
    dl_board = bool(board and board["delinquent_by_year"])
    if claim is not None and board is not None and dl_claim != dl_board:
        # the source's parcel and the board's parcel disagree: which one the row really is
        # cannot be told from here, so nothing is decided (and nothing suppressed)
        return _res("unconfirmed", dict(ev, reason="identity_conflict",
                                        delinquent_parcel="claim" if dl_claim else "board"))
    a = claim if dl_claim else board if dl_board else primary
    decided_on = claim_via if a is claim else "board_parcel"
    # v4: the land account behind a manufactured-home sub-account (evidence, and a sale of the land
    # is the same machine reason as a sale of the account itself)
    related = await _related_account(client, county, sub, a, today)
    if related is not None:
        ev["related_account"] = related
    ev.update(decided_on=decided_on, latest_levy_year=a["latest_levy_year"],
              not_yet_delinquent_due=a["not_yet_delinquent_due"],
              sold_at_tax_sale_years=a.get("sold_at_tax_sale_years"),
              sold_at_tax_sale_on=a.get("sold_at_tax_sale_on"))
    delinquent = bool(a["delinquent_by_year"])
    if not delinquent:
        ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
        if any(s.get("page_capped") for s in searched if s.get("found")):
            return _res("unconfirmed", dict(ev, reason="page_capped"))

    # Before any verdict on this account: does it carry the row's address? A stale / refuted answer
    # always asks (v2); a confirmed one when the bills name a neighbor's house number or the parcel
    # is a resolver's (v5)
    why_bind = None if not delinquent else neighbor_risk(row, a)
    if not delinquent or why_bind:
        if why_bind:
            ev["bound_because"] = why_bind
        try:
            action, what = await _bind(row, client, county, sub, a, today, ev)
        except (TenantDown, SourceFailure) as exc:
            return _down(ev, searched, exc, "address_search_failed")
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="address_search_failed", searched=searched,
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        if action == "unconfirmed":
            return _res("unconfirmed", dict(ev, reason=what))
        if action == "follow":
            a = what                                   # the address's own rows decide (v2)
            related = None                             # the sub-account's land is not this account's
            ev.pop("related_account", None)
            ev.update(decided_on="address_search", address_binding="followed",
                      latest_levy_year=a["latest_levy_year"],
                      not_yet_delinquent_due=a["not_yet_delinquent_due"],
                      sold_at_tax_sale_years=a.get("sold_at_tax_sale_years"),
                      sold_at_tax_sale_on=a.get("sold_at_tax_sale_on"))
            delinquent = bool(a["delinquent_by_year"])
            if not delinquent:
                ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)

    if delinquent:
        ev["delinquent_by_year"] = a["delinquent_by_year"]
        ev["total_delinquent"] = tc.money_total(a["delinquent_by_year"])
        ev["years_delinquent"] = len(a["delinquent_by_year"])
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        if a.get("sold_recent") or (related or {}).get("sold_recent"):
            ev["reason"] = "sold_at_tax_sale"
        return _res("confirmed", ev)

    # v4: an account (or its land) sold at tax sale is neither paid nor stale: with nothing else
    # owed the answer is unconfirmed and says why, so the claim keeps scoring
    if a.get("sold_recent") or a.get("sold_unpriced") or (related or {}).get("sold_recent"):
        return _res("unconfirmed", dict(ev, reason="sold_at_tax_sale"))
    last_ok = latest_eligible(today)
    if not a.get("via_receipts") and a["latest_levy_year"] < last_ok:
        # a receipt answers only the claimed bills, so this history test needs the Map search
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended",
                                        latest_delinquent_eligible_levy=last_ok))
    verdict, checks, rb_checks, hist = _decide_paid(a, claimed, today, tc.first_seen_date(row))
    ev["bills_checked"] = checks
    if rb_checks:
        ev["rollback_bills_checked"] = rb_checks
    complete = bool(hist["readable"]) and not a.get("via_receipts")
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_years_read=hist["years_read"],
              history_complete=complete, late_levy_years=hist["late_levy_years"],
              late_payment_dates=hist["late_payment_dates"],
              chronic_claim=tc.history_claims(hist["late_levy_years"], complete))
    if verdict == "none":
        return _res("unconfirmed", dict(ev, reason="no_paid_row_to_read"))
    if verdict == "mixed":
        return _res("unconfirmed", dict(ev, reason="rollback_bills_mixed"))
    if verdict == "refuted" and a["not_yet_delinquent_due"]:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    if verdict == "stale":
        late_dec = any(c.get("paid_late") for c in checks)
        claimed_late = any(c.get("paid_late") and c["year"] in claimed for c in checks)
        ev["current_claim_basis"] = ("claimed_year_paid_late" if claimed_late
                                     else "latest_year_paid_late" if late_dec
                                     else "paid_late_after_first_seen")
    elif verdict == "refuted":
        ev["current_claim_basis"] = ("claimed_years_on_time" if any(c["year"] in claimed for c in checks)
                                     else "latest_year_on_time")
    return _res(verdict, ev)


ADDRESS_CRITERIA = "Address"


async def _bind(row: dict, client, county: str, sub: str, a: dict, today: date, ev: dict
                ) -> tuple[str, Any]:
    """Does the account checked carry the row's address? ("ok", None), ("follow", assessment of
    the address's own rows) or ("unconfirmed", reason); see ADDRESS BINDING in the module
    docstring. Raises TenantDown / SourceFailure like search()."""
    addr = row.get("street_address")
    query = tc.address_query(addr)
    if query is None:
        ev["address_binding"] = "no_row_address"
        return "ok", None
    rows = a.get("_rows") or []
    rels = {tc.address_relation(addr, r.get("address")) for r in rows}
    rel = "match" if "match" in rels else "conflict" if "conflict" in rels else "unknown"
    ev["address_relation"] = rel
    if rel == "match":
        ev["address_binding"] = "bill_address"
        return "ok", None
    try:
        g = await search(client, county, sub, query, ADDRESS_CRITERIA)
    except CriteriaUnavailable:
        # v5: the tenant has no Property Address search (Horry). The account's own rows decide
        # unless they name another address, or the account is a parcel a resolver attached
        ev["address_binding"] = "no_address_search"
        if rel == "conflict" or (a.get("role") == "board" and tc.parcel_resolved(row)):
            return "unconfirmed", "address_search_unavailable"
        return "ok", None
    mine = [r for r in g["rows"] if tc.address_relation(addr, r.get("address")) == "match"]
    ev["address_matches"] = len(mine)
    if not mine:
        if rel == "conflict":              # the portal names another address for the account and
            return "unconfirmed", "address_not_found"   # no account carries the row's (v3)
        ev["address_binding"] = "unverified"
        return "ok", None
    notices = {tc.alnum(r["notice"]) for r in rows}
    if notices & {tc.alnum(r["notice"]) for r in mine}:
        ev["address_binding"] = "address_search"
        return "ok", None
    if g["capped"]:
        return "unconfirmed", "page_capped"
    a2 = assess(mine, today)
    a2["role"] = "address"
    # v3: the address's account is not the row's own account. When the portal names a REAL other
    # address for the row's account, the address account decides only with proof the row's account
    # is wrong (tc.account_choice); otherwise the verifier cannot tell which is right
    if tc.needs_proof(addr, [r.get("address") for r in rows]):
        owner_addr = tc.owner_category(row.get("owner_name"), [r.get("owner") for r in mine])
        choice, why = tc.account_choice(
            own_retired=False, resolved=a.get("role") == "board" and tc.parcel_resolved(row),
            own_owner=ev.get("owner_match"), address_owner=owner_addr)
        if choice == "ambiguous":
            ev["address_owner_match"] = owner_addr
            return "unconfirmed", why
        ev["followed_because"] = why
    else:
        ev["followed_because"] = "account_names_no_usable_address"
    return "follow", a2
