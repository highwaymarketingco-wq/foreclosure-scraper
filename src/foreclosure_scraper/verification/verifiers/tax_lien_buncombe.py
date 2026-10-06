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

  confirmed    at least one delinquent bill with an amount due today, OR any bill whose Amount Due
               is not a number ("See Legal", "Payment Unavailable, Contact Tax Collections": the
               bill is in legal collection; v4). Such a bill is an UNPAID balance of unknown size
               for its year: it counts as delinquent whatever year it is and the claim holds. Its
               remaining balance is read from its Bill Details page when that can be read
               (tax + interest + costs - payments), as evidence only.
  stale        nothing delinquent today, the parcel carries the row's address, and the year the
               board claimed (or, when the row names no year, the latest delinquent-eligible year)
               has a PAYMENT dated on or after the January 6 interest date. Lateness comes from
               the payment date against that date, never from interest charged alone (v4).
  refuted      nothing delinquent today, the parcel carries the row's address, and the bill(s)
               checked were paid on time (or the only unpaid bill is the current, not-yet-
               delinquent levy).
  unconfirmed  no usable PIN on the row, the page could not be fetched, no bills parsed, the
               parcel's billing ends before the latest delinquent-eligible levy (a PIN retired by
               a split/recombination), the PIN is Inactive and the address cannot be followed to
               its parcel (pin_inactive), the address belongs to another parcel and cannot be
               followed (address_parcel_mismatch), interest was charged but no late payment is
               on the bill (interest_without_late_payment), or the bill shows no payment at all.

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
parcel id the row carries is true of that parcel) but records address_relation and pin_inactive.

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
VERSION = "v4"         # v4 (2026-10-06): See Legal bills count as unpaid, bills keyed by bill
                       # number (discovery bills), lateness from payment dates, interest counted
                       # once, address binding / Inactive PINs. v3: another lien's tax_lien
                       # listing type (liensnc, NC eCourts federal / NCDOR judgments) is not a
                       # property-tax claim (applies(); _tax_common). v2: a parcel record that
                       # ends before the latest delinquent-eligible levy is unconfirmed
TTL_DAYS = 30          # a balance changes when paid; re-check monthly
RETRY_DAYS = 7         # an unreadable page is retried after a week
SOURCE = "tax.buncombenc.gov"
GOVERNS = tc.GOVERNS   # tax_lien:property_tax, tax_sale:property_tax, tax_lien_chronic,
                       # recorded_debt:tax
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


def parse_search_results(text: str) -> Optional[list[dict]]:
    """[{pin, address}] for the PARCEL cards of an address Search page (the bill cards, whose
    heading is a bill number, are skipped); None when the page is not a search-results page."""
    if 'class="search-results' not in text:
        return None
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
    interest date."""
    cutoff = delinquent_after(bill_year).isoformat()
    pays = sorted(t["date"] for t in bill["transactions"] if _is_payment(t) and t["date"])
    late_pay = [d for d in pays if d >= cutoff]
    charged = charged_interest(bill)
    out = {"paid_late": bool(late_pay), "paid_on": pays[-1] if pays else None,
           "interest_and_fees": charged, "delinquent_from": cutoff, "payments": len(pays)}
    if late_pay:
        out["late_payments"] = len(late_pay)
        out["first_late_payment_on"] = late_pay[0]
    elif charged > 0:
        out["interest_without_late_payment"] = True
    if not pays:
        out["no_payment_on_bill"] = True
    return out


def paid_late(bill_year: int, bill: dict) -> Optional[dict]:
    """payment_check() when the bill was paid late, else None (the pre-v4 call shape)."""
    c = payment_check(bill_year, bill)
    return c if c["paid_late"] else None


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
    """[{bill, year, remaining}] for the See Legal bills: remaining is what the bill's own
    Transactions table says is still owed (None when the page cannot be read). Evidence only: a
    See Legal bill is unpaid whatever this says."""
    out = []
    for b in legal[:MAX_LEGAL_BILL_FETCHES]:
        row = {"bill": b["bill"], "year": b["year"], "remaining": None}
        try:
            bp = parse_bill_page(await client.get_text(BILL_URL.format(bill=b["bill"])))
            if bp["readable"]:
                row["remaining"] = remaining_balance(bp)
        except Exception:  # noqa: BLE001 - the balance is evidence; the bill stays unpaid
            pass
        out.append(row)
    out.extend({"bill": b["bill"], "year": b["year"], "remaining": None}
               for b in legal[MAX_LEGAL_BILL_FETCHES:])
    return out


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
            return "follow", others[0]
        ev["address_pins"] = others[:4]
        return "unconfirmed", "address_parcel_mismatch"
    if inactive:
        return "unconfirmed", "pin_inactive"
    if rel == "conflict":                   # the county's own page names another address
        return "unconfirmed", "address_parcel_mismatch"
    _set_binding(ev, "unverified")    # unknown relation and nothing carries the address
    return "ok", None


async def _decide(row: dict, client, pin: str, page: dict, claimed: list[int], today: date,
                  ev: dict, *, can_follow: bool) -> VerificationResult:
    bills = page["bills"]
    delinquent: dict[int, float] = {}
    current: dict[int, float] = {}
    for b in bills:
        if b["amount_due"] is not None and b["amount_due"] > 0:
            if _is_delinquent_bill(b, today):
                _addr_sum(delinquent, b["year"], b["amount_due"])
            else:
                _addr_sum(current, b["year"], b["amount_due"])
    legal = [b for b in bills if b["see_legal"]]
    regular = [b for b in bills if b["regular"]] or bills
    ev.update({
        "pin": pin, "latest_levy_year": regular[0]["year"] if regular else bills[0]["year"],
        "delinquent_by_year": {str(y): a for y, a in sorted(delinquent.items(), reverse=True)},
        "total_delinquent": round(sum(delinquent.values()), 2),
        "years_delinquent": len(set(delinquent) | {b["year"] for b in legal}),
        "not_yet_delinquent_due": {str(y): a for y, a in sorted(current.items())},
        "claimed_years": claimed,
        **side_checks(row, page),
    })
    if page.get("inactive"):
        ev["pin_inactive"] = True
    rel_row = tc.address_query(row.get("street_address"))
    if rel_row:
        ev.setdefault("address_relation", tc.address_relation(row.get("street_address"),
                                                              page.get("situs")))
    if delinquent or legal:
        if legal:
            detail = await _legal_balances(client, legal)
            ev["see_legal_bills"] = detail
            ev["see_legal_years"] = sorted({b["year"] for b in legal}, reverse=True)
            known = [d["remaining"] for d in detail if d["remaining"] is not None]
            due = sum(d["remaining"] for d in detail if d["remaining"] and d["remaining"] > 0
                      and is_delinquent_year(d["year"], today))
            ev["total_delinquent"] = round(ev["total_delinquent"] + due, 2)
            ev["total_delinquent_is_floor"] = len(known) < len(legal) or any(x <= 0 for x in known)
            for d in detail:           # a current levy in legal collection is owed, not yet delinquent
                if d["remaining"] and d["remaining"] > 0 and not is_delinquent_year(d["year"], today):
                    ev["not_yet_delinquent_due"][str(d["year"])] = round(
                        ev["not_yet_delinquent_due"].get(str(d["year"]), 0.0) + d["remaining"], 2)
        ev["under_500"] = ev["total_delinquent"] < 500 and not ev.get("total_delinquent_is_floor")
        return _res("confirmed", ev)
    if page.get("see_legal_text"):
        # the words are on the page but no card read them: a layout change. Never decide.
        ev["reason"] = "see_legal_unparsed"
        return _res("unconfirmed", ev)

    # nothing owed today. Before stale / refuted: is this the parcel that carries the row's address?
    action, what = await _bind(row, client, pin, page, ev, can_follow=can_follow)
    if action == "follow":
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
        ev2: dict[str, Any] = {"url": url, "followed_from_pin": pin,
                               "address_binding": "followed"}
        if page.get("inactive"):
            ev2["followed_from_inactive_pin"] = True
        return await _decide(row, client, what, page2, claimed, today, ev2, can_follow=False)
    if action == "unconfirmed":
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

    # was it ever delinquent (paid late since) or not (paid on time)? The claimed years first
    # (every bill of the year, discovery bills too), then the latest delinquent-eligible regular bill.
    eligible = [b for b in bills if is_delinquent_year(b["year"], today)]
    order: list[dict] = []
    for y in claimed:
        order.extend(b for b in eligible if b["year"] == y)
    first_regular = next((b for b in eligible if b["regular"]), None)
    if first_regular is not None and first_regular["year"] not in {b["year"] for b in order}:
        order.append(first_regular)
    checked = []
    for b in order[:MAX_BILL_CHECKS]:
        burl = BILL_URL.format(bill=b["bill"])
        try:
            bill = parse_bill_page(await client.get_text(burl))
        except Exception as exc:  # noqa: BLE001
            checked.append({"year": b["year"], "url": burl,
                            "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        if not bill["readable"]:
            checked.append({"year": b["year"], "url": burl, "error": "transactions_unreadable"})
            continue
        chk = payment_check(b["year"], bill)
        entry = {"year": b["year"], "url": burl, **chk}
        if not b["regular"]:
            entry["kind"] = "discovery"
        checked.append(entry)
        if chk["paid_late"]:
            ev["bills_checked"] = checked
            return _res("stale", ev)
    ev["bills_checked"] = checked
    if checked and all("error" in c for c in checked):
        ev["reason"] = "bill_pages_unreadable"
        return _res("unconfirmed", ev)
    if any(c.get("interest_without_late_payment") for c in checked):
        ev["reason"] = "interest_without_late_payment"   # charged interest is not a payment date
        return _res("unconfirmed", ev)
    if any(c.get("no_payment_on_bill") for c in checked):
        ev["reason"] = "no_payment_on_bill"              # a zero balance with nothing paid
        return _res("unconfirmed", ev)
    if current and not checked:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
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
