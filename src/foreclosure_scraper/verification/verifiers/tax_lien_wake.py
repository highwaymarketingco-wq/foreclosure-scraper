"""tax_lien, Wake County NC: is there a real delinquent property-tax balance on this parcel, read
live from the county's own tax-bill search?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_rowan, tax_lien_devnet and
the rest: same SIGNAL, same GOVERNS, same verdict meanings, one tax_lien ledger.

WHY IT EXISTS. docs/gap_matrix/gap_list_2026-10-18.csv: Wake NC is the single biggest
"sourced-not-built" target in the whole gap matrix -- multi_year_delinquent_tax (12,941 applicable,
0 hits), atty_tax_verified_confirmed (7,029 applicable, 0 hits) and others, all naming the same
source: "tax/property card: services.wake.gov". No tax_lien verifier and no multi-year reader
existed for Wake at all; Wake's only existing module (scrapers/counties_nc/wake_tax_foreclosure.py)
reads a tiny accordion of ~a dozen already-in-judgment properties, not the general board.

THE SITE (live-verified 2026-10-18). services.wake.gov is a custom, Wake-County-only system --
NOT iasWorld, NOT DevNetWedge, NOT ArcGIS. Two separate applications under one host:
  /realestate/            classic ASP (Account.asp etc) -- the CAMA property-card side, already
                          read by wake_tax_foreclosure.py for its own handful of rows.
  /ptax/main/billing/      ASP.NET WebForms, but THIS page needs no postback at all: a plain GET
                          with a query string returns the full bill-history HTML directly.
No login, no CAPTCHA, no click-through disclaimer on either page (robots.txt disallows the whole
host -- the same host wake_tax_foreclosure.py already crawls in production; per this project's
2026-09-20 "robots.txt is not a wall" decision, only CAPTCHA/login/403/click-through are walls).

THE KEY PROBLEM: BRIDGING PIN -> REID. Wake's tax/property-card system is keyed by its own
7-digit "Real Estate ID" (REID, e.g. "0047895"), but the board's Wake parcel_id is the statewide
10-digit PIN (e.g. "1713252770") -- the same PIN NC OneMap's own parcel layer carries for every
other NC county. Confirmed live: NC OneMap's NC1Map_Parcels layer (parcel_cache.NC_ONEMAP_URL,
the same free ArcGIS REST endpoint docs/gap_matrix/gap_list_2026-10-18.csv already names as
Wake's atty_taxpayer_of_record / assessed_value / owner_name source) carries BOTH keys on the same
row: `parno` is the 10-digit PIN, `altparno` is the REID this site needs, zero-padded to 7 digits
exactly as services.wake.gov prints it. Live-checked: PIN 1713252770 -> altparno "0047895" ->
Account.asp?id=0047895 is the exact same account, owner "MITCHELL, GEORGE JR HEIRS ...". A row
whose parcel_id is already 7 digits or fewer (all-numeric) is read as a REID directly -- no bridge
call needed -- the same defensive both-formats handling enrichment_county_sales.py documents for
Henderson's PIN/REID split.

THE CALLS:
    GET {ONEMAP_URL}?where=cntyname='Wake' AND parno='<pin>'&outFields=altparno&f=json
        -> the bridge (skipped when parcel_id already looks like a REID)
    GET https://services.wake.gov/ptax/main/billing/acctsummary.aspx
        ?search=re&yrs=2&prev=re&id=<reid>
        -> one <TR> per open BILL (one per levy year the county still tracks as unpaid or
           recently closed), each carrying its own 26-digit bill account number
           ("0000047895-2026-2026-000000" -- the second dash segment is the levy year), a
           "billFlag" status cell (blank, "Collection Proceeding Active", "Delinquent<br>
           Collection Proceeding Active", or "Subject to Rollback" for a present-use parcel's
           deferred-value tracking row), "Current Due" (today's payoff amount for that year,
           already netting any payment/interest), "Due Date" and "Interest Begins".
    Live-verified 2026-10-18 on 3 real Wake parcels across the full range of shapes:
      PIN 1713252770 (REID 0047895, 610 Cumberland St, Raleigh) -- 5 open-year bills, 2022-2026,
          4 of them ("Delinquent") carrying real unpaid balances $1,710-$3,099 each -- a genuine,
          live, multi-year delinquency.
      PIN 0765045120 (REID 0210739, 100 Montauk Point Pl, Cary) -- 2024/2025 bills $0.00 (paid),
          2026 bill $5,600.17 due but NOT flagged Delinquent (due 09/01/2026, interest begins
          01/06/2027): the ordinary current-year case, correctly NOT a delinquency.
      PIN 1797953869 (REID 0167151, 0 Ferrell Rd, Zebulon, a 55-acre present-use farm) -- carries
          both an ordinary "000000" bill AND a second "002000" bill per year flagged "Subject to
          Rollback" (the county's own deferred-value tracking row, $0.00 balance -- a fact used by
          the rollback_exposure extension in enrichment_rollback_deferral.py, not here).

VERDICTS (a levy-year Y bill is late once unpaid on January 6 of Y+1, G.S. 105-360;
tax_calendar.delinquent_after -- the SAME rule every other NC tax_lien verifier uses, applied to
the bill's own levy year rather than trusting the site's "Delinquent" wording verbatim, for
consistency with the rest of this ledger):
  confirmed    a late levy year's bill has a Current Due > 0 on the row's own bridged account.
  stale        nothing late is owed today, and at least one levy year the BOARD's own claim named
               now shows $0.00 in this table.
  refuted      never. Like tax_lien_rowan, this table has no payment-DATE column, so there is no
               way to tell a bill paid before its delinquency date from one paid after it.
  unconfirmed  no parcel on the row, the PIN->REID bridge found no match or failed, the live site
               could not be reached, the account carried no bill rows at all, or none of the
               board's claimed years could be confirmed resolved.

Evidence is a whitelist (public ledger): no owner names, no mailing addresses, no account numbers
beyond the bridged REID itself (a public county identifier, not a secret).
"""
from __future__ import annotations

import re
import weakref
from datetime import date
from typing import Any, Optional

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 7
SOURCE = "services.wake.gov (Wake County property tax)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "bridge_failed")

COUNTY = "wake"
BASE = "https://services.wake.gov"
ONEMAP_URL = ("https://services.nconemap.gov/secure/rest/services/"
             "NC1Map_Parcels/FeatureServer/1/query")
BILLS_URL = BASE + "/ptax/main/billing/acctsummary.aspx?search=re&yrs=2&prev=re&id={reid}"

_NAME = __name__.rsplit(".", 1)[-1]


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    if str(tc.g(row, "county") or "").strip().replace(" County", "").lower() != COUNTY:
        return False
    return tc.claims_property_tax(row, False)


def claimed_years(row: Any) -> list[int]:
    return sorted(tc.claimed_years_common(row) | tc.source_block_years(row), reverse=True)


# ---------------------------------------------------------------------------
# PIN -> REID bridge (pure parse + the one live call)
# ---------------------------------------------------------------------------

_REID_RE = re.compile(r"^\d{1,7}$")
_PIN_RE = re.compile(r"^\d{8,10}$")


def reid_of(parcel_id: Optional[str]) -> Optional[str]:
    """The row's parcel_id read directly as a Wake REID when it already looks like one (<= 7
    digits, zero-padded to 7): None when it looks like a 10-digit statewide PIN instead, which
    needs `bridge_pin_to_reid`."""
    s = re.sub(r"[^0-9]", "", str(parcel_id or ""))
    if s and _REID_RE.match(s) and len(s) <= 7:
        return s.zfill(7)
    return None


def _bridge_url(pin: str) -> str:
    return (f"{ONEMAP_URL}?where=cntyname='Wake' AND parno='{pin}'"
            f"&outFields=altparno&f=json")


async def bridge_pin_to_reid(client: Any, pin: str) -> Optional[str]:
    """The Wake REID (7-digit, zero-padded) for a 10-digit statewide PIN, read off NC OneMap's
    own parcel layer (altparno), or None when the layer has no match or the call fails."""
    import json
    try:
        txt = await client.get_text(_bridge_url(pin), timeout=30.0)
    except Exception:  # noqa: BLE001 - a bridge failure is reported by the caller
        return None
    try:
        data = json.loads(txt)
    except (ValueError, TypeError):
        return None
    feats = data.get("features") if isinstance(data, dict) else None
    if not feats:
        return None
    reid = (feats[0].get("attributes") or {}).get("altparno")
    reid = re.sub(r"[^0-9]", "", str(reid or ""))
    return reid.zfill(7) if reid else None


async def resolve_reid(client: Any, parcel_id: Optional[str]) -> Optional[str]:
    """reid_of(parcel_id), else bridge_pin_to_reid for a 10-digit PIN. None for anything else
    (no parcel, or a parcel id that is neither shape)."""
    direct = reid_of(parcel_id)
    if direct:
        return direct
    pin = re.sub(r"[^0-9]", "", str(parcel_id or ""))
    if _PIN_RE.match(pin):
        return await bridge_pin_to_reid(client, pin)
    return None


# ---------------------------------------------------------------------------
# bill-history parsing (pure, live-verified against 3 real accounts, module docstring)
# ---------------------------------------------------------------------------

_BILL_ANCHOR_RE = re.compile(r">(\d+-(\d{4})-\d{4}-(\d+))</A>", re.I)
_FLAG_RE = re.compile(r'class="billFlag">(.*?)</TD>', re.S | re.I)
_DUE_RE = re.compile(
    r'Current Due:.*?</TD>\s*<TD[^>]*class="medFontBold"[^>]*>\$?([\d,]+\.\d{2})', re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
#: the window after a bill's own anchor this account's status/amount cells live within (live-
#: measured: well under 1000 chars on every sampled page; generous margin for a longer owner block)
_WINDOW = 2500


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", s or "")).strip()


def parse_bills(html: str) -> list[dict]:
    """[{account, year, suffix, flag, amount_due}] from the acctsummary.aspx bill table, in the
    page's own order. `suffix` is the bill account's own trailing segment: "000000" is the
    ordinary annual bill, a non-zero suffix ("002000") is a secondary tracking row (a present-use
    parcel's own deferred-value row, flagged "Subject to Rollback" -- not a second tax bill).
    `flag` is the billFlag cell's cleaned text ("", "Collection Proceeding Active", "Delinquent
    Collection Proceeding Active", "Subject to Rollback"); never itself the late/not-late
    decision (verify() asks tax_calendar, module docstring's VERDICTS note)."""
    out = []
    for m in _BILL_ANCHOR_RE.finditer(html or ""):
        window = html[m.end(): m.end() + _WINDOW]
        flag_m = _FLAG_RE.search(window)
        due_m = _DUE_RE.search(window)
        if due_m is None:
            continue   # not a real bill row (a malformed/partial window) -- never guess an amount
        out.append({
            "account": m.group(1), "year": int(m.group(2)), "suffix": m.group(3),
            "flag": _clean(flag_m.group(1)) if flag_m else "",
            "amount_due": float(due_m.group(1).replace(",", "")),
        })
    return out


# ---------------------------------------------------------------------------
# fetching (one bills fetch per REID per run; cached per-client like tax_lien_perquimans)
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _cache(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {})
    except TypeError:          # not weak-referenceable: no sharing
        return {}


async def fetch_bills(client: Any, reid: str) -> list[dict]:
    """Every open-year bill row for one Wake REID, cached per run. Raises on a fetch failure --
    the caller turns that into `unconfirmed`/fetch_failed, same as every other tax_lien verifier;
    there is no multi-failure circuit breaker here (a single plain GET, not a stateful session)."""
    cache = _cache(client)
    if reid in cache:
        return cache[reid]
    html = await client.get_text(BILLS_URL.format(reid=reid), timeout=40.0)
    bills = parse_bills(html)
    cache[reid] = bills
    return bills


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "reid", "bridged_from_pin", "latest_levy_year", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "not_yet_delinquent_due", "claimed_years",
         "resolved_claimed_years", "error")


def public_evidence(ev: dict) -> dict:
    return tc.pick(ev, _KEYS)


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claimed = claimed_years(row)
    ev: dict[str, Any] = {"claimed_years": claimed}
    pid = str(tc.g(row, "parcel_id") or "").strip()
    if not pid:
        return _res("unconfirmed", dict(ev, reason="no_parcel"))

    direct = reid_of(pid)
    if direct:
        reid = direct
    else:
        pin = re.sub(r"[^0-9]", "", pid)
        if not _PIN_RE.match(pin):
            return _res("unconfirmed", dict(ev, reason="parcel_unrecognized"))
        try:
            reid = await bridge_pin_to_reid(client, pin)
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        ev["bridged_from_pin"] = pin
        if not reid:
            return _res("unconfirmed", dict(ev, reason="bridge_failed"))
    ev["reid"] = reid
    ev["url"] = BILLS_URL.format(reid=reid)

    try:
        bills = await fetch_bills(client, reid)
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    # the ordinary annual bill only: a "002000"-style suffix is a present-use rollback-tracking
    # row, not a second tax bill (parse_bills docstring) -- never double-count it as owed.
    bills = [b for b in bills if b["suffix"] in ("000000", "0")]
    if not bills:
        return _res("unconfirmed", dict(ev, reason="no_bills"))

    ev["latest_levy_year"] = max(b["year"] for b in bills)
    delinquent: dict[str, float] = {}
    current: dict[str, float] = {}
    resolved_claimed: list[int] = []
    for b in bills:
        due = b["amount_due"] or 0.0
        late = tax_calendar.levy_year_is_delinquent(b["year"], "NC", "Wake", today)
        if due > 0 and late:
            delinquent[str(b["year"])] = round(due, 2)
        elif due > 0:
            current[str(b["year"])] = round(due, 2)
        elif b["year"] in claimed:
            resolved_claimed.append(b["year"])

    if current:
        ev["not_yet_delinquent_due"] = current
    if delinquent:
        ev["delinquent_by_year"] = delinquent
        ev["total_delinquent"] = tc.money_total(delinquent)
        ev["years_delinquent"] = len(delinquent)
        return _res("confirmed", ev)
    if resolved_claimed:
        ev["resolved_claimed_years"] = sorted(resolved_claimed, reverse=True)
        return _res("stale", ev)
    return _res("unconfirmed", dict(ev, reason="claimed_year_not_in_bill_history"))
