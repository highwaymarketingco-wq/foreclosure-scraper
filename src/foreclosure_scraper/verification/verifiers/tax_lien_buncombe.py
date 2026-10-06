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

  confirmed    at least one delinquent bill with an amount due today.
  stale        nothing delinquent today, but the year the board claimed (or, when the row
               names no year, the latest delinquent-eligible year) was PAID LATE: a payment
               dated after the January 5 deadline, or interest / a late fee on the bill. The
               delinquency was real and has been paid since. One or two Bill/Details fetches.
  refuted      nothing delinquent today and the bill(s) checked were paid on time (or the only
               unpaid bill is the current, not-yet-delinquent levy).
  unconfirmed  no usable PIN on the row, the page could not be fetched, no bills parsed, or
               the parcel's billing ends before the latest delinquent-eligible levy (a PIN
               retired by a split/recombination: this record no longer answers for the
               property); or a refuted/stale answer on a row typed tax_lien by another lien's
               source (other_lien_listing, see _tax_common: v3).

Evidence also carries the two FINDINGS.md side checks: the county's current owner against the
board's owner_name (Finding C) and the county's assessed value against the board's value with
the ratio (Finding B). They are evidence only; the verdict is about the tax balance.

WHICH ROWS (v3). The validator's selection, except that a tax_lien listing type set by another
lien's source is not a property-tax claim (_tax_common.NON_PROPERTY_TAX_SOURCES: 1,094 Buncombe
rows on the 2026-10-06 board, liensnc lien-agent filings and NC eCourts federal / NCDOR tax-lien
judgments). Checked against the county's property-tax record, a paid tax bill refuted them and
the verdict took a real lien's signal away. Such a row is still covered when it carries a
property-tax claim of its own (a delinquency flag, or a county roll's block merged into it),
and then a refuted/stale answer is published unconfirmed (other_lien_listing), the same rule
and the same code as tax_lien_ptscloud and tax_lien_qpaybill.

GOVERNS (_tax_common.GOVERNS, shared): a refuted or stale verdict removes the scorer's
`tax_lien` listing-type signal (and `tax_sale` / `tax_lien_chronic`, the same fact under other
names) where the row's claim is a property-tax one ("tax_lien:property_tax": never the listing
type of another lien's row on the same parcel), and the `recorded_debt` credit where that debt
is the tax balance ("recorded_debt:tax"; a judgment or an opening bid still counts).
"""
from __future__ import annotations

import html as _html
import re
from datetime import date, datetime
from typing import Any, Optional

from ..core import VerificationResult, digits, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v3"         # v3 (2026-10-06): another lien's tax_lien listing type (liensnc, NC
                       # eCourts federal / NCDOR judgments) is not a property-tax claim, and a
                       # refuted/stale answer on such a row is unconfirmed (_tax_common).
                       # v2: a parcel record that ends before the latest delinquent-eligible
                       # levy is unconfirmed, not refuted/stale
TTL_DAYS = 30          # a balance changes when paid; re-check monthly
RETRY_DAYS = 7         # an unreadable page is retried after a week
SOURCE = "tax.buncombenc.gov"
GOVERNS = tc.GOVERNS   # tax_lien:property_tax, tax_sale:property_tax, tax_lien_chronic,
                       # recorded_debt:tax
ROLL_KEY = "buncombe_delinquent_tax"   # the county roll's own block (counties_nc scraper)
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
_BILL_LINK = re.compile(r'/Bill/Details/(\d{10}-(\d{4})-\d{4}-\d{4}-\d{2})')
_FIELD = re.compile(r'<small[^>]*>\s*(Owner|Value|PIN|Amount Due)\s*</small>\s*<div[^>]*>\s*([^<]*?)\s*</div>',
                    re.S)
# the validator's proven regexes, kept as the fallback for a layout change
_BILL_RE = re.compile(
    r'/Bill/Details/(\d{10}-(\d{4})-\d{4}-\d{4}-\d{2})".*?'
    r'Amount Due</small>\s*<div class="fw-semibold">\$([\d,]+\.\d{2})</div>', re.S)
_OWNER_RE = re.compile(r'Owner</small>\s*<div class="fw-semibold">\s*([^<]+?)\s*</div>')
_VALUE_RE = re.compile(r'Value</small>\s*<div class="fw-semibold">\$([\d,]+)</div>')
_TX_SECTION = re.compile(r'<section class="transactions.*?</section>', re.S)
_TR = re.compile(r'<tr>(.*?)</tr>', re.S)
_TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
_TAG = re.compile(r'<[^>]+>')


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


def parse_parcel_page(text: str) -> dict:
    """{'bills': [{bill, year, owner, value, amount_due}], 'owner', 'value'} from a Parcel
    Details page; bills newest first, one per levy year (the history cards; the validator's
    regex as fallback). Empty 'bills' means the page is not a readable parcel page."""
    bills: dict[int, dict] = {}
    for chunk in _CARD_SPLIT.split(text)[1:]:
        m = _BILL_LINK.search(chunk)
        if not m:
            continue
        f = {k: _html.unescape(v).strip() for k, v in _FIELD.findall(chunk)}
        amt = money(f.get("Amount Due"))
        if amt is None:
            continue
        year = int(m.group(2))
        bills.setdefault(year, {"bill": m.group(1), "year": year, "owner": f.get("Owner") or None,
                                "value": money(f.get("Value")), "amount_due": round(amt, 2)})
    if not bills:
        for m in _BILL_RE.finditer(text):
            year = int(m.group(2))
            bills.setdefault(year, {"bill": m.group(1), "year": year, "owner": None,
                                    "value": None, "amount_due": money(m.group(3))})
        om, vm = _OWNER_RE.search(text), _VALUE_RE.search(text)
        if bills:
            top = bills[max(bills)]
            top["owner"] = top["owner"] or (om.group(1).strip() if om else None)
            top["value"] = top["value"] or (money(vm.group(1)) if vm else None)
    ordered = [bills[y] for y in sorted(bills, reverse=True)]
    latest = ordered[0] if ordered else {}
    return {"bills": ordered, "owner": latest.get("owner"), "value": latest.get("value")}


def parse_bill_page(text: str) -> dict:
    """The Transactions table of a Bill Details page:
    {'transactions': [{type, date, tax, late_fee, interest, cost, total}], 'readable': bool}."""
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


# ---------------------------------------------------------------------------
# the rules (pure)
# ---------------------------------------------------------------------------

def delinquent_after(year: int) -> date:
    """First day a levy-year bill is delinquent: January 6 of the next year (G.S. 105-360)."""
    return date(year + 1, 1, 6)


def is_delinquent_year(year: int, today: date) -> bool:
    return today >= delinquent_after(year)


def paid_late(bill_year: int, bill: dict) -> Optional[dict]:
    """The late-payment evidence on a parsed bill (a payment on/after the delinquency date,
    or interest / a late fee charged), else None."""
    cutoff = delinquent_after(bill_year).isoformat()
    late_pay = [t for t in bill["transactions"]
                if t["type"].startswith("PAY") and t["date"] and t["date"] >= cutoff]
    charged = sum(abs(t.get("interest") or 0) + abs(t.get("late_fee") or 0)
                  for t in bill["transactions"])
    if late_pay or charged > 0:
        return {"paid_on": (late_pay[-1]["date"] if late_pay else None),
                "interest_and_fees": round(charged, 2), "delinquent_from": cutoff}
    return None


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
    out: dict[str, Any] = {"owner_county": page.get("owner"), "owner_board": row.get("owner_name"),
                           "owner_match": owner_match(row.get("owner_name"), page.get("owner"))}
    cv, bv = page.get("value"), board_value(row)
    out["value_county"] = cv
    out["value_board"] = bv
    out["value_ratio_board_to_county"] = round(bv / cv, 3) if (cv and bv) else None
    return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, evidence: dict, row: Optional[dict] = None) -> VerificationResult:
    verdict, evidence = tc.other_lien_downgrade(verdict, evidence, row)   # the mixed-row rule
    return result(SIGNAL, verdict, evidence, source=SOURCE, version=VERSION, verifier=_NAME)


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

    delinquent = {b["year"]: b["amount_due"] for b in page["bills"]
                  if b["amount_due"] > 0 and is_delinquent_year(b["year"], today)}
    current = {b["year"]: b["amount_due"] for b in page["bills"]
               if b["amount_due"] > 0 and not is_delinquent_year(b["year"], today)}
    ev: dict[str, Any] = {
        "url": url, "pin": pin, "latest_levy_year": page["bills"][0]["year"],
        "delinquent_by_year": {str(y): a for y, a in sorted(delinquent.items(), reverse=True)},
        "total_delinquent": round(sum(delinquent.values()), 2),
        "years_delinquent": len(delinquent),
        "not_yet_delinquent_due": {str(y): a for y, a in current.items()},
        "claimed_years": claimed,
        **side_checks(row, page),
    }
    if delinquent:
        ev["under_500"] = ev["total_delinquent"] < 500
        return _res("confirmed", ev, row)

    # nothing delinquent today. If the parcel's billing stops before the latest levy that
    # could be delinquent (a PIN retired by a split or recombination: the 2026-10-06 sweep
    # met records ending 2022 and 2024 under rows claiming 2025/2026), the property is billed
    # elsewhere now and this record cannot answer for it.
    latest_eligible = max(y for y in range(today.year - 2, today.year + 1)
                          if is_delinquent_year(y, today))
    if ev["latest_levy_year"] < latest_eligible:
        ev["reason"] = "parcel_record_ended"
        ev["latest_delinquent_eligible_levy"] = latest_eligible
        return _res("unconfirmed", ev)

    # was it ever delinquent (paid late since) or not (paid on time)?
    eligible = [b for b in page["bills"] if is_delinquent_year(b["year"], today)]
    by_year = {b["year"]: b for b in eligible}
    order = [y for y in claimed if y in by_year]
    if eligible and eligible[0]["year"] not in order:
        order.append(eligible[0]["year"])          # the latest delinquent-eligible levy
    checked = []
    for year in order[:MAX_BILL_CHECKS]:
        burl = BILL_URL.format(bill=by_year[year]["bill"])
        try:
            bill = parse_bill_page(await client.get_text(burl))
        except Exception as exc:  # noqa: BLE001
            checked.append({"year": year, "url": burl,
                            "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        if not bill["readable"]:
            checked.append({"year": year, "url": burl, "error": "transactions_unreadable"})
            continue
        late = paid_late(year, bill)
        checked.append({"year": year, "url": burl, "paid_late": bool(late), **(late or {})})
        if late:
            ev["bills_checked"] = checked
            return _res("stale", ev, row)
    ev["bills_checked"] = checked
    if checked and all("error" in c for c in checked):
        ev["reason"] = "bill_pages_unreadable"
        return _res("unconfirmed", ev)
    if current and not checked:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    return _res("refuted", ev, row)
