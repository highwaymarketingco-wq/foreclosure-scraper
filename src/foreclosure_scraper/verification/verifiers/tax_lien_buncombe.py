"""tax_lien, Buncombe County NC: is there a real delinquent property-tax balance on this parcel?

THE REFERENCE VERIFIER. Copy its shape for a new one (docs/HANDOFF.md item 66 has the steps).

Evolved from docs/validation_2026-10-02/scripts/validate_tax_lien_buncombe.py (FINDINGS.md #1:
only 11.9% of sampled rows carried any real unpaid prior-year balance, and the board's value
was overstated ~1.78x). Same live endpoint, same no-auth plain HTML, no CAPTCHA:

    https://tax.buncombenc.gov/Parcel/Details/{15-digit PIN}   billing history, one card a bill
    https://tax.buncombenc.gov/Bill/Details/{bill number}      one bill's transactions

WHAT IT CHECKS. Every bill on the parcel page carries an Amount Due. A levy-year Y bill is
delinquent once it is unpaid after January 5 of Y+1 (G.S. 105-360: due September 1, payable
without interest through January 5), so today, 2026-10-05, the 2026 bill is not delinquent and
the 2025 one is. Verdicts:

  confirmed    at least one delinquent bill with an amount due today, OR a delinquent bill whose
               Amount Due is not a number ("See Legal", "Payment Unavailable, Contact Tax
               Collections": the bill is in legal collection; v4). Such a bill is an UNPAID balance
               of unknown size for its year, unless its own Bill Details page shows it paid off
               (v6, below); its remaining balance is read from that page when it can be read
               (tax + interest + costs - payments). A See Legal bill of a levy year that is not
               late yet is owed, not delinquent (v6): it never makes a late year by itself.
  stale        nothing delinquent today, the parcel is the row's (below), and the claim WAS true:
               a year the board claimed has a PAYMENT dated on or after the January 6 interest
               date, or a bill that was already delinquent the day the board first saw the row
               (row first_seen) was paid late on or after that day (v5). Lateness comes from the
               payment date against that date, never from interest charged alone (v4).
  refuted      nothing delinquent today, the parcel is the row's, and the claimed years (or, when
               the row names no year, the latest delinquent-eligible year) were paid on time and
               no payment fits the stale rule (or the only unpaid bill is the current, not-yet-
               delinquent levy).
  unconfirmed  no usable PIN on the row, the page could not be fetched, no bills parsed, the
               parcel's billing ends before the latest delinquent-eligible levy (a PIN retired by
               a split/recombination), the PIN is Inactive and the address cannot be followed to
               its parcel (pin_inactive), the address belongs to another parcel and cannot be
               followed (address_parcel_mismatch), the address belongs to another parcel and
               nothing proves which is the row's (ambiguous_account, v5), no parcel carries the
               row's address and the PIN's own page names another (address_not_found, v5),
               interest was charged but no late payment is on the bill
               (interest_without_late_payment), or the bill shows no payment at all.

TWO CLAIMS, THE BILL HISTORY (v5; _tax_common, TWO CLAIMS). When nothing is owed, the Bill
Details page of every delinquent-eligible regular bill from levy 2019 on is read (the claimed
years' and the latest bills first, at most 12 bills) and the evidence records late_levy_years, the
late payment dates per year, history_complete and the chronic_claim judged on them (confirmed at
3 late levy years, the scorer's tax_lien_chronic rule). `governs` is per record: a parcel that is
paid up today and paid late in most recent years is refuted or stale for `tax_lien`, and keeps
`tax_lien_chronic`. A confirmed answer reads no history (nothing to suppress).

BILLS ARE KEYED BY BILL NUMBER, NOT BY YEAR (v4). A bill number is
"<account>-<levy year>-<tax year>-<sequence>-<suffix>". A regular bill has sequence 0000 and the
same year twice. A discovery bill (sequence 0070: omitted or late-listed property, billed after
the fact) carries the year it was billed first and the tax year it is for second: four discovery
bills billed 2025-02-19 for tax years 2021-2024 sit beside the regular 2025 bill. The old parse
kept one bill per levy year, dropped every See Legal card, and so judged parcel 8792725038 stale
from the paid 2021 discovery bill while its 2023 and 2024 bills were unpaid in legal collection,
and judged 9686053926 refuted from its paid 2025 bill while its 2024 bill (and a 2015 one) sat in
legal collection. A bill's year here is its TAX year; the page's later 2026 bills (three on
parcel 9754697396) are all kept.

ADDRESS BINDING (v4). Before a stale or refuted answer, the parcel checked must be the one that
carries the row's address. The parcel page's heading is the county's situs; the Search page
(Search/Results?QueryType=Address) lists the parcels carrying an address. A page whose situs
matches is bound. Otherwise (a different address, a placeholder such as 99999, or an Inactive
PIN, one the county retired by a split or recombination) the row's address is searched: this PIN
among the matches binds it; exactly one other active parcel carries the address and is
verified INSTEAD (evidence followed_from_pin); anything else is unconfirmed. A row with no
house-numbered address has nothing to bind and is judged on its PIN (but an Inactive PIN is
never judged: pin_inactive). A confirmed answer needs no binding (an unpaid balance on the
parcel id the row carries is true of that parcel) but records address_relation and pin_inactive,
EXCEPT when the PIN's page names a different house number on the row's own street (v6, below).

WHICH PARCEL, WHEN THE ADDRESS NAMES ANOTHER (v5). The follow step used to go to the one other
parcel that carries the row's address whenever the row's own PIN did not (2026-10-06: 2614 Old Fort
Rd and 16 Rabbit Hill Dr were judged refuted from the neighbor's account while the row's own PIN,
2610 Old Fort Rd / 18 Rabbit Hill Dr, had paid its 2025 bill late the week before). The address
search always matched exactly (house number AND street name, _tax_common.address_relation: a
different number on the same street, or "GLENN" for "GLEN", is another property and never binds);
the defect was following AWAY from a county-supplied PIN. Now _tax_common.account_choice() decides:
follow the address parcel only with proof the row's PIN is wrong (Inactive PIN, a resolver attached
it, the board owner matches the address parcel and not the PIN's); judge the row's own PIN when the
board's value equals its county value (the layer row IS that parcel's record; the address is the
owner's mailing-style address); else `ambiguous_account`. A PIN whose own page names another
address while no parcel carries the row's: `address_not_found`.

LATE YEARS ONLY, PAID-OFF LEGAL BILLS, THE NEIGHBOR'S HOUSE NUMBER (v6, 2026-10-08 independent audit
of 160 ledger rows against the live site). Three defects:
  1. A See Legal bill counted as a late year whatever its levy year: every parcel in legal
     collection also shows its CURRENT bill as See Legal, so 41 ledger rows labelled two or more
     late years had one (8 of the 40 sampled "2+" rows were one year too high). A bill is late
     only after January 5 of the year after its levy, See Legal or not: years_delinquent,
     delinquent_by_year and total_delinquent count late years only, and the not-yet-late amount
     stays in not_yet_delinquent_due. A not-yet-late See Legal bill alone is not a delinquency.
  2. A See Legal card stays on the page after the bill is paid off in legal collection: parcel
     9618970338 carried See Legal on its 2011-2013 bills, each brought to $0 by one 2014
     payment, and was confirmed with 3 late years totalling $0. Each See Legal bill's own
     Transactions table is read first (late ones first); a payment row and nothing left in any
     column (legal_bill_paid) is a PAID bill: no late year, nothing owed
     (see_legal_paid_years in the evidence). An unreadable page keeps the bill unpaid.
  3. 915 Morgan Hill Rd was confirmed from the balance of its PIN, which is 909 Morgan Hill Rd's
     parcel (it held only because 915's own parcel owed too). When the PIN's page names a
     different house number on the row's own street (_tax_common.other_number_same_street), a
     confirmed answer is bound like any other: the address search, account_choice() (follow,
     own, ambiguous_account) and address_not_found. A different street or no usable number is
     unchanged.
balance_under_25 marks a confirmed balance under _tax_common.DE_MINIMIS (a marker, not a verdict:
9 of the 40 sampled one-year rows owed under $25).

Evidence also carries the two FINDINGS.md side checks: the county's current owner against the
board's owner_name (Finding C), as the match CATEGORY only (same / partial / different; never a
name: the ledger is pushed to a PUBLIC repo, and ROW_SUMMARY_EXCLUDE keeps owner_name out of the
entry's row summary too), and the county's assessed value against the board's value with the
ratio (Finding B). They are evidence only; the verdict is about the tax balance.

WHICH ROWS (v3). The validator's selection, except that a tax_lien listing type set by another
lien's source is not a property-tax claim (_tax_common.NON_PROPERTY_TAX_SOURCES: 1,094 Buncombe
rows on the 2026-10-06 board, liensnc lien-agent filings and NC eCourts federal / NCDOR tax-lien
judgments). Checked against the county's property-tax record, a paid tax bill refuted them and
the verdict took a real lien's signal away. Such a row is still covered when it carries a
property-tax claim of its own (a delinquency flag, or a county roll's block merged into it),
the same rule as tax_lien_ptscloud and tax_lien_qpaybill (_tax_common), and its verdict is
published as it is: the qualified GOVERNS below ends only the property-tax-derived signals on
that row, never the lien's own listing type.

GOVERNS (_tax_common.GOVERNS, shared): a refuted or stale verdict removes the scorer's
`tax_lien` listing-type signal (and `tax_sale` / `tax_lien_chronic`, the same fact under other
names) where the row's claim is a property-tax one ("tax_lien:property_tax": never the listing
type of another lien's row, whether it is the row checked or another row of the parcel), and the
`recorded_debt` credit where that debt is the tax balance ("recorded_debt:tax"; a judgment or an
opening bid still counts).
"""
from __future__ import annotations

import html as _html
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote_plus

from ..core import VerificationResult, digits, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v6"         # v6 (2026-10-08): late years only (a not-yet-late See Legal bill is not
                       # one), a See Legal bill its own transactions show paid off is paid, a PIN
                       # naming another house number on the row's street must bind before a
                       # confirmed answer, balance_under_25 marker.
                       # v5 (2026-10-06): two claims judged apart (current vs chronic, from the
                       # bill history of levy 2019 on; per-record governs), stale when a claimed
                       # year or a bill delinquent at first_seen was paid late, the address is
                       # followed only with proof (ambiguous_account / address_not_found), the
                       # ledger is address-scoped. v4: See Legal bills count as unpaid, bills
                       # keyed by bill number (discovery bills), lateness from payment dates,
                       # interest counted once, address binding / Inactive PINs. v3: another
                       # lien's tax_lien listing type (liensnc, NC eCourts federal / NCDOR
                       # judgments) is not a property-tax claim (applies(); _tax_common). v2: a
                       # parcel record that ends before the latest delinquent-eligible levy is
                       # unconfirmed
TTL_DAYS = 30          # a balance changes when paid; re-check monthly
RETRY_DAYS = 7         # an unreadable page is retried after a week
SOURCE = "tax.buncombenc.gov"
GOVERNS = tc.GOVERNS   # tax_lien:property_tax, tax_sale:property_tax, tax_lien_chronic,
                       # recorded_debt:tax
governs_for = tc.governs_for   # per record: a confirmed chronic claim keeps tax_lien_chronic
ROLL_KEY = "buncombe_delinquent_tax"   # the county roll's own block (counties_nc scraper)
ROW_SUMMARY_EXCLUDE = ("owner_name",)  # public ledger: no names (the sweep pops these)
#: the county's own delinquent-roll blocks: a property-tax claim of their own on a row whose
#: listing type is another lien's (multi_year_delinquent_tax: the county's per-year unpaid-bill
#: layers, counties_generic.multi_year_delinquent_tax)
OWN_BLOCKS = (ROLL_KEY, "multi_year_delinquent_tax")

BASE = "https://tax.buncombenc.gov"
PARCEL_URL = BASE + "/Parcel/Details/{pin}"
BILL_URL = BASE + "/Bill/Details/{bill}"
MAX_BILL_CHECKS = 2

_NAME = __name__.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def flagged(row: dict) -> bool:
    """The validator's own selection (FINDINGS.md #1): listing_type tax_lien, a two-year
    delinquency flag, or a surfaced tax-aging status with at least one delinquent year
    (_tax_common.aging_claim). Since v3 the listing type counts only as a property-tax claim:
    a row typed tax_lien by another lien's source (_tax_common.other_lien_listing) needs a flag
    or a county roll block (OWN_BLOCKS) of its own."""
    if row.get("listing_type") == "tax_lien" and (
            not tc.other_lien_listing(row)
            or any(isinstance(_raw(row).get(k), dict) for k in OWN_BLOCKS)):
        return True
    return tc.aging_claim(row)


def applies(row: dict) -> bool:
    return (str(row.get("state") or "").strip().upper() == "NC"
            and str(row.get("county") or "").strip().lower() == "buncombe"
            and flagged(row))


def pin_of(row: dict) -> Optional[str]:
    """The 15-character Buncombe PIN the tax site takes. A 10-digit board PIN is the base PIN
    (county GIS exports pad it with zeros, models._normalize_parcel strips them), so it gets
    its 00000 suffix back; 11-14 digits are accepted only when everything past the 10th digit
    is a zero pad. A condominium unit keeps its letter suffix ("9648-62-3059-C0401" ->
    9648623059C0401, "9644-95-3081-C0D17" -> 9644953081C0D17; both resolved live 2026-10-06).
    Anything else is not resolvable here."""
    an = re.sub(r"[^0-9A-Za-z]", "", str(row.get("parcel_id") or "")).upper()
    if re.fullmatch(r"\d{10}[A-Z][0-9A-Z]{4}", an):
        return an
    d = digits(an)
    if d != an:
        return None
    if len(d) == 15:
        return d
    if len(d) == 10:
        return d + "00000"
    if 10 < len(d) < 15 and set(d[10:]) <= {"0"}:
        return d[:10] + "00000"
    return None


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_CARD_SPLIT = re.compile(r'class="card history-card')
#: <account>-<levy year>-<tax year>-<sequence>-<suffix>; a regular bill is sequence 0000 with the
#: same year twice, a discovery bill (0070) is billed in the first year for the second
_BILL_LINK = re.compile(r'/Bill/Details/(\d{10}-(\d{4})-(\d{4})-(\d{4})-(\d{2}))')
_FIELD = re.compile(r'<small[^>]*>\s*(Owner|Value|PIN|Amount Due)\s*</small>\s*<div[^>]*>\s*([^<]*?)\s*</div>',
                    re.S)
# the validator's proven regexes, kept as the fallback for a layout change
_BILL_RE = re.compile(
    r'/Bill/Details/(\d{10}-(\d{4})-(\d{4})-(\d{4})-(\d{2}))".*?'
    r'Amount Due</small>\s*<div class="fw-semibold">\$([\d,]+\.\d{2})</div>', re.S)
_OWNER_RE = re.compile(r'Owner</small>\s*<div class="fw-semibold">\s*([^<]+?)\s*</div>')
_VALUE_RE = re.compile(r'Value</small>\s*<div class="fw-semibold">\$([\d,]+)</div>')
_TX_SECTION = re.compile(r'<section class="transactions.*?</section>', re.S)
_TR = re.compile(r'<tr>(.*?)</tr>', re.S)
_TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
_TAG = re.compile(r'<[^>]+>')
#: "Current Bills" rows: a bill with no payable amount says "Payment Unavailable" (legal collection)
_CURRENT_ROW = re.compile(r'<div class="row my-4">(.*?)(?=<div class="row my-4">|</section>)', re.S)
_H1 = re.compile(r'<h1[^>]*class="card-title[^>]*>\s*([^<]*?)\s*</h1>', re.S)
_SEARCH_CARD = re.compile(
    r'<h6 class="card-subtitle[^"]*">\s*([0-9A-Z]{15})\s*</h6>\s*'
    r'<a href="/Parcel/Details/[^"]*"[^>]*>\s*<h4[^>]*>\s*([^<]*?)\s*</h4>', re.S)
_PIN_RE = re.compile(r'[0-9]{10}[0-9A-Z]{5}')


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def money(s: Any) -> Optional[float]:
    """'$1,234.56' -> 1234.56, '($152.63)' -> -152.63, junk -> None."""
    t = _html.unescape(str(s or "")).strip()
    neg = t.startswith("(") and t.endswith(")")
    m = re.search(r"[\d,]+(?:\.\d+)?", t)
    if not m:
        return None
    v = float(m.group(0).replace(",", ""))
    return -v if neg else v


def _bill(m_groups: tuple, f: dict, amt: Optional[float], see_legal: bool) -> dict:
    number, levy, tax, seq, _suffix = m_groups
    return {"bill": number, "year": int(tax), "levy_year": int(levy), "seq": seq,
            "regular": seq == "0000", "owner": f.get("Owner") or None,
            "value": money(f.get("Value")),
            "amount_due": None if amt is None else round(amt, 2), "see_legal": see_legal}


def parse_parcel_page(text: str) -> dict:
    """{'bills', 'owner', 'value', 'inactive', 'situs', 'see_legal_text'} from a Parcel Details
    page. 'bills' holds EVERY bill card, one per bill NUMBER (v4: not one per year), newest tax
    year first, each {bill, year (the TAX year), levy_year, seq, regular, owner, value,
    amount_due (a number, or None when the card shows text), see_legal}. A card whose Amount Due
    is text ("See Legal") or whose bill the page's Current Bills list calls "Payment Unavailable"
    is see_legal: an unpaid balance of unknown size. Empty 'bills' means the page is not a
    readable parcel page. 'situs' is the county's address heading; 'inactive' the retired-parcel
    banner; 'see_legal_text' is True when the words appear on the page but no card read them
    (a layout change: the caller must not decide from such a page)."""
    unavailable = set()
    for row in _CURRENT_ROW.findall(text):
        if "Payment Unavailable" in row:
            unavailable.update(m.group(1) for m in _BILL_LINK.finditer(row))
    bills: dict[str, dict] = {}
    for chunk in _CARD_SPLIT.split(text)[1:]:
        m = _BILL_LINK.search(chunk)
        if not m:
            continue
        f = {k: _html.unescape(v).strip() for k, v in _FIELD.findall(chunk)}
        raw_amt = f.get("Amount Due")
        amt = money(raw_amt)
        legal = (amt is None and bool(raw_amt)) or m.group(1) in unavailable
        if amt is None and not legal:
            continue                                 # no Amount Due at all: unreadable card
        bills.setdefault(m.group(1), _bill(m.groups(), f, amt, legal))
    if not bills:
        for m in _BILL_RE.finditer(text):
            bills.setdefault(m.group(1), _bill(m.groups()[:5], {}, money(m.group(6)),
                                               m.group(1) in unavailable))
        om, vm = _OWNER_RE.search(text), _VALUE_RE.search(text)
        if bills:
            top = max(bills.values(), key=lambda b: (b["year"], b["levy_year"]))
            top["owner"] = top["owner"] or (om.group(1).strip() if om else None)
            top["value"] = top["value"] or (money(vm.group(1)) if vm else None)
    ordered = sorted(bills.values(), key=lambda b: (b["year"], b["levy_year"], b["seq"]),
                     reverse=True)
    latest = next((b for b in ordered if b["regular"]), ordered[0] if ordered else {})
    h1 = _H1.search(text)
    return {"bills": ordered, "owner": latest.get("owner"), "value": latest.get("value"),
            "inactive": "You are viewing an inactive parcel" in text,
            "situs": _html.unescape(h1.group(1)).strip() if h1 else None,
            "see_legal_text": ("See Legal" in text or "Payment Unavailable" in text)
                              and not any(b["see_legal"] for b in ordered)}


_NO_RESULTS = re.compile(r"(?i)didn(?:'|&#39;|&#x27;|&apos;|\u2019)t find any results")


def parse_search_results(text: str) -> Optional[list[dict]]:
    """[{pin, address}] for the PARCEL cards of an address Search page (the bill cards, whose
    heading is a bill number, are skipped); [] for the county's own "Sorry, we didn't find any
    results" answer (v5: it used to be read as an unreadable page, so an address no parcel
    carries was answered address_search_unreadable); None when the page is neither."""
    if 'class="search-results' not in text:
        return [] if _NO_RESULTS.search(text) else None
    return [{"pin": m.group(1), "address": _html.unescape(m.group(2)).strip()}
            for m in _SEARCH_CARD.finditer(text) if _PIN_RE.fullmatch(m.group(1))]


def parse_bill_page(text: str) -> dict:
    """The Transactions table of a Bill Details page:
    {'transactions': [{type, date, tax, late_fee, interest, cost, total}], 'readable': bool}.
    A bill still owed in legal collection has no number in the Total column (a red bar), so
    `total` is None there; the other columns are read as usual."""
    sec = _TX_SECTION.search(text)
    txs = []
    for tr in _TR.findall(sec.group(0) if sec else ""):
        cells = [_html.unescape(_TAG.sub("", c)).strip() for c in _TD.findall(tr)]
        if len(cells) < 8:
            continue
        d = None
        try:
            d = datetime.strptime(cells[1], "%m/%d/%Y").date().isoformat()
        except ValueError:
            pass
        txs.append({"type": cells[0].upper(), "date": d, "tax": money(cells[3]),
                    "late_fee": money(cells[4]), "interest": money(cells[5]),
                    "cost": money(cells[6]), "total": money(cells[7])})
    return {"transactions": txs, "readable": bool(sec)}


def remaining_balance(bill: dict) -> Optional[float]:
    """What a parsed Bill Details page says is still owed: every row's tax + late fee + interest
    + cost, charges positive and payments negative (a BILL of 305.27 + 54.33 + 4.76 and no
    payment: 364.36; the same bill part-paid by 285.31: 79.05). None when nothing was read."""
    txs = bill.get("transactions") or []
    if not txs:
        return None
    return round(sum((t.get(k) or 0.0) for t in txs for k in ("tax", "late_fee", "interest", "cost")), 2) + 0.0


_COLUMNS = ("tax", "late_fee", "interest", "cost")


def legal_bill_paid(bill: dict) -> bool:
    """v6: a parsed Bill Details page shows the bill PAID OFF: at least one payment row (PAYMENT,
    or a PAYMENTRELEASE writing off a residual) and nothing left in any column (tax, late fee,
    interest and cost each sum to zero or less). A See Legal card can outlive the payment: a
    2011 bill of 141.45 tax + 30.97 interest + 2.00 cost, paid by one 2014 payment of the same
    three amounts, still reads See Legal. A balance of zero with no payment row is not paid (the
    size is unknown, as before)."""
    txs = bill.get("transactions") or []
    if not any(str(t.get("type") or "").startswith("PAY") for t in txs):
        return False
    return all(round(sum((t.get(k) or 0.0) for t in txs), 2) <= 0.0 for k in _COLUMNS)


# ---------------------------------------------------------------------------
# the rules (pure)
# ---------------------------------------------------------------------------

def delinquent_after(year: int) -> date:
    """First day a levy-year bill is delinquent: January 6 of the next year (G.S. 105-360)."""
    return date(year + 1, 1, 6)


def is_delinquent_year(year: int, today: date) -> bool:
    return today >= delinquent_after(year)


def _is_payment(t: dict) -> bool:
    """A PAYMENT row. PAYMENTRELEASE (the county writing off a residual of a few dollars, seen
    2026-10-02 beside the last real payment) is not one."""
    return str(t.get("type") or "").startswith("PAY") and "RELEASE" not in str(t.get("type"))


def charged_interest(bill: dict) -> float:
    """Interest + late fee the county CHARGED on a bill. The Transactions table lists the charge
    on the BILL row and, as the same dollars negated, on each PAYMENT row that paid it: summing
    absolute values counted every interest dollar twice (all 39 Buncombe stale records of the
    2026-10-06 recheck carried exactly double). The charge is the positive amounts; when no
    charge row carries one, what the payments paid."""
    txs = bill.get("transactions") or []
    pos = sum(max(t.get("interest") or 0.0, 0.0) + max(t.get("late_fee") or 0.0, 0.0) for t in txs)
    paid = sum(max(-(t.get("interest") or 0.0), 0.0) + max(-(t.get("late_fee") or 0.0), 0.0)
               for t in txs)
    return round(max(pos, paid), 2)


def payment_check(bill_year: int, bill: dict) -> dict:
    """What a parsed bill says about WHEN it was paid. `paid_late` is a payment dated on or after
    the January 6 interest date and nothing else: interest charged with every payment before that
    date (interest_without_late_payment) is not lateness (v4; the old rule counted it, and judged
    parcel 8792725038 stale from a paid discovery bill that way). `paid_on` is the last payment's
    date whenever any payment is on the page; `late_payments` how many fell on or after the
    interest date, `late_payment_dates` those dates (v5: the bill history keeps them per year;
    first / last_late_payment_on are the earliest and latest)."""
    cutoff = delinquent_after(bill_year).isoformat()
    pays = sorted(t["date"] for t in bill["transactions"] if _is_payment(t) and t["date"])
    late_pay = [d for d in pays if d >= cutoff]
    charged = charged_interest(bill)
    out = {"paid_late": bool(late_pay), "paid_on": pays[-1] if pays else None,
           "interest_and_fees": charged, "delinquent_from": cutoff, "payments": len(pays)}
    if late_pay:
        out["late_payments"] = len(late_pay)
        out["first_late_payment_on"] = late_pay[0]
        out["last_late_payment_on"] = late_pay[-1]
        out["late_payment_dates"] = late_pay[:4]
    elif charged > 0:
        out["interest_without_late_payment"] = True
    if not pays:
        out["no_payment_on_bill"] = True
    return out


def paid_late(bill_year: int, bill: dict) -> Optional[dict]:
    """payment_check() when the bill was paid late, else None (the pre-v4 call shape)."""
    c = payment_check(bill_year, bill)
    return c if c["paid_late"] else None


def claim_pins(row: dict) -> set[str]:
    """The PINs the row's own county roll blocks name (buncombe_delinquent_tax.pin,
    multi_year_delinquent_tax.parcel_key): the parcel the CLAIM is about. A block merged into
    another parcel's row (a shared lien-agent filing joined two rows: Pole Creasman 756 carries
    586's roll block) names a PIN that is not the row's."""
    raw = _raw(row)
    out = set()
    for key, field in (("buncombe_delinquent_tax", "pin"), ("multi_year_delinquent_tax", "parcel_key")):
        blk = raw.get(key)
        if isinstance(blk, dict) and blk.get(field):
            p = pin_of({"parcel_id": blk[field]})
            if p:
                out.add(p)
    return out


def claimed_years(row: dict) -> list[int]:
    """Levy years the board's own data says were delinquent, newest first."""
    raw = _raw(row)
    years: set[int] = set()
    bdt = raw.get(ROLL_KEY)
    if isinstance(bdt, dict):
        years.add(_int(bdt.get("tax_year")))
    ty = raw.get("two_year_delinquent")
    if isinstance(ty, dict) and ty.get("is_two_year_plus"):
        years.add(_int(ty.get("tax_year")))
    ta = raw.get("tax_aging_surfaced")
    if isinstance(ta, dict) and _int(ta.get("years_delinquent")) > 0:
        years.add(_int(ta.get("tax_year")))
    to = raw.get("tax_owed")
    if isinstance(to, dict) and (to.get("balance") or 0):
        years.add(_int(to.get("year")))
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


def board_value(row: dict) -> Optional[float]:
    for k in ("assessed_value", "market_value", "tax_value"):
        v = row.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def owner_match(board: Optional[str], county: Optional[str]) -> Optional[str]:
    """'same' (name_normalize.match_owner, or half the identity tokens shared), 'partial'
    (some token shared), 'different', or None when either side is missing."""
    if not board or not county:
        return None
    from ...name_normalize import core_tokens, match_owner
    try:
        if match_owner(board, county) or match_owner(county, board):
            return "same"
    except Exception:  # noqa: BLE001
        pass
    a, b = set(core_tokens(board)), set(core_tokens(county))
    if not a or not b:
        return None
    j = len(a & b) / len(a | b)
    if j >= 0.5:
        return "same"
    return "partial" if a & b else "different"


def side_checks(row: dict, page: dict) -> dict:
    """Finding C as a category only (the names never leave this function) and Finding B."""
    out: dict[str, Any] = {"owner_match": owner_match(row.get("owner_name"), page.get("owner"))}
    cv, bv = page.get("value"), board_value(row)
    out["value_county"] = cv
    out["value_board"] = bv
    out["value_ratio_board_to_county"] = round(bv / cv, 3) if (cv and bv) else None
    return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

SEARCH_URL = BASE + "/Search/Results?QueryType=Address&Query={q}"
MAX_LEGAL_BILL_FETCHES = 6     # See Legal bills whose Bill Details page is read for the balance
MAX_FOLLOW_CANDIDATES = 1      # parcels carrying the row's address that may be followed to


def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, evidence, source=SOURCE, version=VERSION, verifier=_NAME)


def _addr_sum(by: dict[int, float], year: int, amount: float) -> None:
    by[year] = round(by.get(year, 0.0) + amount, 2)


def _is_delinquent_bill(b: dict, today: date) -> bool:
    return is_delinquent_year(b["year"], today)


async def _legal_balances(client, legal: list[dict]) -> list[dict]:
    """[{bill, year, remaining, paid?}] for the See Legal bills, in the order given (the caller
    puts the delinquent ones first): remaining is what the bill's own Transactions table says is
    still owed (None when the page cannot be read, or past MAX_LEGAL_BILL_FETCHES); paid=True
    when that table shows the bill paid off (legal_bill_paid, v6). A bill not shown paid stays
    unpaid, whatever its remaining says."""
    out = []
    for b in legal[:MAX_LEGAL_BILL_FETCHES]:
        row = {"bill": b["bill"], "year": b["year"], "remaining": None}
        try:
            bp = parse_bill_page(await client.get_text(BILL_URL.format(bill=b["bill"])))
            if bp["readable"]:
                row["remaining"] = remaining_balance(bp)
                if legal_bill_paid(bp):
                    row["paid"] = True
        except Exception:  # noqa: BLE001 - the balance is evidence; the bill stays unpaid
            pass
        out.append(row)
    out.extend({"bill": b["bill"], "year": b["year"], "remaining": None}
               for b in legal[MAX_LEGAL_BILL_FETCHES:])
    return out


async def _follow(row: dict, client, pin: str, page: dict, what: str, claimed: list[int],
                  today: date, ev: dict) -> Optional[VerificationResult]:
    """The address search names exactly one other parcel (`what`) for the row's address: decide
    which account is the row's (v5; tc.account_choice). Returns the answer (unconfirmed, or the
    followed parcel's own verdict), or None when the row's OWN parcel decides (value identity:
    the board's value is its county value; the evidence records the address parcel)."""
    url = PARCEL_URL.format(pin=what)
    try:
        text = await client.get_text(url)
    except Exception as exc:  # noqa: BLE001
        ev["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        ev["reason"] = "address_parcel_fetch_failed"
        return _res("unconfirmed", ev)
    page2 = parse_parcel_page(text)
    if not page2["bills"]:
        ev["reason"] = "address_parcel_unreadable"
        return _res("unconfirmed", ev)
    # v5: two parcels, the row's own and the one the address search names. When the row's
    # own PIN names a REAL other address the address account decides only with PROOF the
    # PIN is wrong (tc.account_choice); a PIN whose page names no usable address (a 99999
    # placeholder) contradicts nothing, and the one parcel that carries the address decides
    owner_addr = tc.owner_category(row.get("owner_name"), [page2.get("owner")])
    if not tc.needs_proof(row.get("street_address"), [page.get("situs")]):
        choice, why = "follow", "pin_names_no_usable_address"
    else:
        choice, why = tc.account_choice(
            own_retired=bool(page.get("inactive")), resolved=tc.parcel_resolved(row),
            own_owner=ev.get("owner_match"), address_owner=owner_addr,
            own_value_identity=tc.value_identity(row, page.get("value"), page2.get("value")))
    if choice == "ambiguous":
        ev.update(address_pins=[what], address_owner_match=owner_addr,
                  value_county_address_parcel=page2.get("value"), reason=why)
        return _res("unconfirmed", ev)
    if choice == "follow":
        ev2: dict[str, Any] = {"url": url, "followed_from_pin": pin,
                               "address_binding": "followed", "followed_because": why}
        if page.get("inactive"):
            ev2["followed_from_inactive_pin"] = True
        return await _decide(row, client, what, page2, claimed, today, ev2, can_follow=False)
    # "own": the row's data is its own parcel's record and the address is another property's
    # (the board's value equals this parcel's county value, not the address parcel's)
    ev.update(address_binding="own_parcel_value_identity", address_account_pin=what,
              value_county_address_parcel=page2.get("value"))
    return None


def _set_binding(ev: dict, how: str) -> None:
    """Record how the parcel was bound to the row's address; a followed parcel stays "followed"."""
    if "followed_from_pin" not in ev:
        ev["address_binding"] = how


async def _bind(row: dict, client, pin: str, page: dict, ev: dict, *, can_follow: bool
                ) -> tuple[str, Any]:
    """Is the parcel checked the one that carries the row's address? Returns
    ("ok", None), ("follow", pin) or ("unconfirmed", reason). See ADDRESS BINDING in the module
    docstring. Records address_binding / address_relation in `ev`."""
    row_addr = row.get("street_address")
    query = tc.address_query(row_addr)
    rel = tc.address_relation(row_addr, page.get("situs")) if query else "none"
    if query:
        ev["address_relation"] = rel
    inactive = bool(page.get("inactive"))
    if inactive:
        ev["pin_inactive"] = True
    if query is None:                       # no house-numbered address on the row: nothing to bind
        if inactive:
            return "unconfirmed", "pin_inactive"
        _set_binding(ev, "no_row_address")
        return "ok", None
    if rel == "match" and not inactive:
        _set_binding(ev, "page_address")
        return "ok", None
    surl = SEARCH_URL.format(q=quote_plus(query))
    ev["address_search_url"] = surl
    try:
        found = parse_search_results(await client.get_text(surl))
    except Exception as exc:  # noqa: BLE001
        ev["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return "unconfirmed", "address_search_failed"
    if found is None:
        return "unconfirmed", "address_search_unreadable"
    carry = [f["pin"] for f in found if tc.address_relation(row_addr, f["address"]) == "match"]
    ev["address_matches"] = len(carry)
    if pin in carry and not inactive:
        _set_binding(ev, "address_search")
        return "ok", None
    others = [p for p in dict.fromkeys(carry) if p != pin]
    if others:
        if can_follow and len(others) <= MAX_FOLLOW_CANDIDATES:
            return "follow", others[0]      # _decide: account_choice() says whether it decides
        ev["address_pins"] = others[:4]
        return "unconfirmed", "address_parcel_mismatch"
    if inactive:
        return "unconfirmed", "pin_inactive"
    if rel == "conflict":                   # the county's own page names another address and no
        return "unconfirmed", "address_not_found"   # parcel carries the row's (v5: own reason)
    _set_binding(ev, "unverified")    # unknown relation and nothing carries the address
    return "ok", None


async def _decide(row: dict, client, pin: str, page: dict, claimed: list[int], today: date,
                  ev: dict, *, can_follow: bool) -> VerificationResult:
    bills = page["bills"]
    delinquent: dict[int, float] = {}
    current: dict[int, float] = {}
    for b in bills:
        if not b["see_legal"] and b["amount_due"] is not None and b["amount_due"] > 0:
            if _is_delinquent_bill(b, today):
                _addr_sum(delinquent, b["year"], b["amount_due"])
            else:
                _addr_sum(current, b["year"], b["amount_due"])
    # See Legal bills (v6): each one's own Transactions table is read first, the delinquent ones
    # first; a bill shown paid off is paid, any other is unpaid. Only a DELINQUENT unpaid one makes
    # a late year; a not-yet-late one is owed (not_yet_delinquent_due), whatever its card says.
    legal = sorted((b for b in bills if b["see_legal"]),
                   key=lambda b: not _is_delinquent_bill(b, today))
    detail = await _legal_balances(client, legal) if legal else []
    legal_late: set[int] = set()
    size_unknown = False
    for b, d in zip(legal, detail):
        if d.get("paid"):
            continue
        rem = d["remaining"]
        amt = rem if rem is not None and rem > 0 else (
            b["amount_due"] if rem is None and (b["amount_due"] or 0) > 0 else None)
        if _is_delinquent_bill(b, today):
            legal_late.add(b["year"])
            if amt is None:
                size_unknown = True          # unpaid, size unknown: the total is a floor
            else:
                _addr_sum(delinquent, b["year"], amt)
        elif amt is not None:
            _addr_sum(current, b["year"], amt)
    late_years = set(delinquent) | legal_late
    regular = [b for b in bills if b["regular"]] or bills
    ev.update({
        "pin": pin, "latest_levy_year": regular[0]["year"] if regular else bills[0]["year"],
        "delinquent_by_year": {str(y): a for y, a in sorted(delinquent.items(), reverse=True)},
        "total_delinquent": round(sum(delinquent.values()), 2),
        "years_delinquent": len(late_years),
        "not_yet_delinquent_due": {str(y): a for y, a in sorted(current.items())},
        "claimed_years": claimed,
        **side_checks(row, page),
    })
    if legal:
        ev["see_legal_bills"] = detail
        ev["see_legal_years"] = sorted({d["year"] for d in detail if not d.get("paid")}, reverse=True)
        paid_years = sorted({d["year"] for d in detail if d.get("paid")}, reverse=True)
        if paid_years:
            ev["see_legal_paid_years"] = paid_years
    if page.get("inactive"):
        ev["pin_inactive"] = True
    cp = claim_pins(row)
    if cp and pin not in cp:
        ev["claim_pin_differs"] = True       # the roll block on the row is another parcel's claim
        ev["claim_pins"] = sorted(cp)
    rel_row = tc.address_query(row.get("street_address"))
    if rel_row:
        ev.setdefault("address_relation", tc.address_relation(row.get("street_address"),
                                                              page.get("situs")))
    if late_years:
        if legal:
            ev["total_delinquent_is_floor"] = size_unknown
        # v6: a PIN whose page names another house number on the row's own street is a neighbor's
        # parcel until the address search says otherwise (915 / 909 Morgan Hill Rd): bind it the
        # way a stale / refuted answer is bound, through account_choice() and address_not_found
        if "followed_from_pin" not in ev and tc.other_number_same_street(
                row.get("street_address"), page.get("situs")):
            action, what = await _bind(row, client, pin, page, ev, can_follow=can_follow)
            if action == "follow":
                res = await _follow(row, client, pin, page, what, claimed, today, ev)
                if res is not None:
                    return res
            elif action == "unconfirmed":
                ev["reason"] = what
                return _res("unconfirmed", ev)
        floor = bool(ev.get("total_delinquent_is_floor"))
        ev["under_500"] = ev["total_delinquent"] < 500 and not floor
        ev["balance_under_25"] = ev["total_delinquent"] < tc.DE_MINIMIS and not floor
        return _res("confirmed", ev)
    if page.get("see_legal_text"):
        # the words are on the page but no card read them: a layout change. Never decide.
        ev["reason"] = "see_legal_unparsed"
        return _res("unconfirmed", ev)

    # nothing owed today. Before stale / refuted: is this the parcel that carries the row's address?
    action, what = await _bind(row, client, pin, page, ev, can_follow=can_follow)
    if action == "follow":
        res = await _follow(row, client, pin, page, what, claimed, today, ev)
        if res is not None:
            return res
    elif action == "unconfirmed":
        ev["reason"] = what
        return _res("unconfirmed", ev)

    # If the parcel's billing stops before the latest levy that could be delinquent (a PIN
    # retired by a split or recombination: the 2026-10-06 sweep met records ending 2022 and 2024
    # under rows claiming 2025/2026), the property is billed elsewhere now and this record cannot
    # answer for it.
    latest_eligible = max(y for y in range(today.year - 2, today.year + 1)
                          if is_delinquent_year(y, today))
    if ev["latest_levy_year"] < latest_eligible:
        ev["reason"] = "parcel_record_ended"
        ev["latest_delinquent_eligible_levy"] = latest_eligible
        return _res("unconfirmed", ev)

    # Was it ever delinquent (paid late since) or not (paid on time)? Two claims, judged apart
    # (_tax_common, TWO CLAIMS): the CURRENT one (tax_lien) on the claimed years' bills (else the
    # latest delinquent-eligible regular bill), the CHRONIC one (tax_lien_chronic) on every bill
    # from levy HISTORY_FROM_LEVY on. The decision bills (at most MAX_BILL_CHECKS) are read first.
    eligible = [b for b in bills if is_delinquent_year(b["year"], today)]
    claimed_set = set(claimed)
    decision: list[dict] = []
    for y in claimed:
        decision.extend(b for b in eligible if b["year"] == y)
    first_regular = next((b for b in eligible if b["regular"]), None)
    if first_regular is not None and first_regular["year"] not in {b["year"] for b in decision}:
        decision.append(first_regular)
    decision = decision[:MAX_BILL_CHECKS]
    taken = {b["bill"] for b in decision}
    extra = sorted((b for b in eligible if b["bill"] not in taken
                    and (b["year"] >= tc.HISTORY_FROM_LEVY or b["year"] in claimed_set)),
                   key=lambda b: (b["year"] not in claimed_set, -b["year"], not b["regular"]))
    todo = (decision + extra)[:tc.MAX_HISTORY_BILLS]
    truncated = len(decision) + len(extra) > len(todo)
    checked = []
    for i, b in enumerate(todo):
        burl = BILL_URL.format(bill=b["bill"])
        base = {"year": b["year"], "bill": b["bill"], "url": burl}
        if not b["regular"]:
            base["kind"] = "discovery"
        try:
            bill = parse_bill_page(await client.get_text(burl))
        except Exception as exc:  # noqa: BLE001
            checked.append(dict(base, error=f"{type(exc).__name__}: {str(exc)[:120]}"))
            continue
        if not bill["readable"]:
            checked.append(dict(base, error="transactions_unreadable"))
            continue
        chk = payment_check(b["year"], bill)
        if i >= len(decision):                     # history only: the fields the history needs
            chk = {k: chk[k] for k in ("paid_late", "paid_on", "late_payment_dates",
                                       "last_late_payment_on", "delinquent_from") if k in chk}
            base.pop("url")
        checked.append({**base, **chk})
    ok = [c for c in checked if "error" not in c]
    regular_late = {c["year"]: c for c in ok if c["paid_late"] and c.get("kind") != "discovery"}
    complete = not truncated and len(ok) == len(checked)
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_bills_read=len(ok),
              history_complete=complete, late_levy_years=sorted(regular_late),
              late_payment_dates={str(y): regular_late[y]["late_payment_dates"]
                                  for y in sorted(regular_late)},
              chronic_claim=tc.history_claims(regular_late, complete))
    ev["bills_checked"] = checked
    first_seen = tc.first_seen_date(row)
    dchecks = checked[:len(decision)]
    claimed_late = sorted(c["year"] for c in ok if c["paid_late"] and c["year"] in claimed_set)
    decision_late = sorted(c["year"] for c in dchecks if c.get("paid_late"))
    seen_late = sorted(c["year"] for c in ok if c["paid_late"] and tc.paid_after_seen(
        first_seen, delinquent_after(c["year"]), c.get("last_late_payment_on")))
    if claimed_late or decision_late or seen_late:
        ev["current_claim_basis"] = ("claimed_year_paid_late" if claimed_late
                                     else "latest_year_paid_late" if decision_late
                                     else "paid_late_after_first_seen")
        return _res("stale", ev)
    if dchecks and all("error" in c for c in dchecks):
        ev["reason"] = "bill_pages_unreadable"
        return _res("unconfirmed", ev)
    if any(c.get("interest_without_late_payment") for c in dchecks):
        ev["reason"] = "interest_without_late_payment"   # charged interest is not a payment date
        return _res("unconfirmed", ev)
    if any(c.get("no_payment_on_bill") for c in dchecks):
        ev["reason"] = "no_payment_on_bill"              # a zero balance with nothing paid
        return _res("unconfirmed", ev)
    if current and not dchecks:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    ev["current_claim_basis"] = ("claimed_years_on_time" if claimed_set & {b["year"] for b in decision}
                                 else "latest_year_on_time")
    return _res("refuted", ev)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    pin = pin_of(row)
    claimed = claimed_years(row)
    if not pin:
        return _res("unconfirmed", {"reason": "parcel_unresolvable",
                                    "parcel_id": row.get("parcel_id"), "claimed_years": claimed})
    url = PARCEL_URL.format(pin=pin)
    try:
        text = await client.get_text(url)
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", {"reason": "fetch_failed", "url": url,
                                    "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    page = parse_parcel_page(text)
    if not page["bills"]:
        return _res("unconfirmed", {"reason": "no_bills_parsed", "url": url, "pin": pin,
                                    "page_chars": len(text)})
    ev: dict[str, Any] = {"url": url}
    return await _decide(row, client, pin, page, claimed, today, ev, can_follow=True)
