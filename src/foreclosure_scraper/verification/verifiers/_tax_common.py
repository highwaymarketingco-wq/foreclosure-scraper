"""Shared pieces of the tax_lien verifiers (tax_lien_buncombe, tax_lien_ptscloud,
tax_lien_qpaybill).

Private (the leading underscore keeps the registry from loading it as a verifier). Pure: no I/O.
The scorer imports other_lien_listing() from here (stdlib-only at import time).

WHICH ROWS CARRY THE PROPERTY-TAX CLAIM. The reference used to take every row typed tax_lien
plus the two derived delinquency flags (tax_lien_buncombe v1/v2). That is not safe: a large
share of the rows typed tax_lien / tax_sale are OTHER liens that a county property-tax record
cannot speak to, measured on the 2026-10-05 board (board_stream, read-only):

    counties_sc.sc_dew_lien_registry          SC Dept. of Employment & Workforce UI-tax liens
                                              ("SC DEW UI-tax lien - balance $3,576"), 8,479
                                              rows with a tax_owed of that lien
    counties_sc.sc_state_tax_lien             SC Dept. of Revenue state tax liens
    counties_nc.nc_ecourts_lis_pendens        NC eCourts "Federal Tax Lien judgment" and "NC
                                              Certificate of Tax Liability judgment" (IRS / NCDOR)
    nc_ecourts_judgments                      the same judgment index, no description
    liensnc, counties_generic.liensnc         construction lien-agent filings (A8: the scorer
                                              already treats their type as context only)

Checked against the county tax portal, such a row would be refuted because the PROPERTY tax is
paid. So a listing-type claim from these sources is not a property-tax claim here, in all three
verifiers (tax_lien_buncombe since v3: 1,094 Buncombe rows typed tax_lien by liensnc / eCourts).
The row is still covered when it carries a property-tax claim of its own (a delinquency flag or
the vendor's roll block): a MIXED row. Its verdict is published as it is, refuted and stale
included; the scorer side below keeps it from touching the lien's own signal.

THE SCORER SIDE (GOVERNS). The ledger is keyed by PROPERTY, so a separate board row of another
lien on the same parcel inherits the parcel's property-tax verdict too. GOVERNS therefore names
the listing-type signals with a qualifier, "tax_lien:property_tax" / "tax_sale:property_tax"
(the "incarceration:jail" pattern): both readers (distress_score._collect,
enrichment_lead_signals._facet_signals) end tax_lien / tax_sale only where it comes from a
property-tax claim, never the listing type of an other_lien_listing() row, while the
property-tax-derived signals (tax_lien_chronic, the recorded_debt credit of the tax balance, the
sc_tax_delinquent facet) end on any row. A DEW / DOR lien keeps its own debt credit: its amount
is a judgment-sourced amount_owed, which "recorded_debt:tax" does not touch.

RETIRED (2026-10-06): a refuted/stale answer on a mixed row used to be published `unconfirmed`
(reason other_lien_listing, the answer kept as property_tax_verdict). With the qualified GOVERNS
that only hid the county's answer about the row's own property-tax claim (a paid tax balance
kept its debt credit), so it was dropped; restore_property_tax_verdicts() put the ledger's
downgraded answers back, offline.

TWO CLAIMS, JUDGED APART (2026-10-06 recheck of the 51 refuted entries: 25 were chronic late
payers). A tax_lien row asserts (1) the property is delinquent NOW (`tax_lien`, `tax_sale`, the
recorded_debt credit of the balance) and (2) it is a CHRONIC delinquent (`tax_lien_chronic`, the
scorer's FINANCIAL 24 weight; its only producer is raw['pickens_delinquent']['chronic'] =
len(cycles) >= 3, three or more separate delinquency publications). A parcel that is paid up today
can still have paid LATE in most recent levy years: its current claim is refuted or stale, its
chronic claim is confirmed by the bill history, and the verdict must not take the chronic signal
away. So each verifier reads the bill history (levy HISTORY_FROM_LEVY on) when nothing is owed,
records late_levy_years and the late payment dates in the evidence, judges the chronic claim
(`chronic_claim`: confirmed at CHRONIC_MIN_LATE_YEARS late levy years, not_confirmed when the
whole history was read and has fewer, unknown when part of it could not be read), and
governs_for() narrows the record's `governs` (registry.py: governs_for): tax_lien_chronic is left
out of it unless the chronic claim is not_confirmed. A discovery bill (omitted property, billed
after the fact) is never a late payment of the owner's: it is read for the current claim but not
counted toward late_levy_years.

THE CURRENT CLAIM'S VERDICT. stale when the claim WAS true: a claimed year's bill was paid late,
or a late payment of a bill that was already delinquent when the board first saw the row is dated
on or after that day (first_seen: the board saw an open delinquency and it was paid since);
refuted when the claimed years (else the latest delinquent-eligible year) were paid on time and no
payment fits the first rule.

WHICH ACCOUNT IS THE ROW'S (address vs parcel). A row's parcel id and its street address can name
different accounts (2026-10-06: 2614 / 2610 Old Fort Rd, 16 / 18 Rabbit Hill Dr: one parcel id,
one row with the owner's mailing-style address; 844 Rice Ave Ext, 2383 Jonesville Hwy in Union SC:
the board's parcel and the address search point at different accounts, with different payment
histories). account_choice() is the one policy: follow the address to the account that carries it
only with PROOF the row's own account is the wrong one (the portal retired it, a resolver attached
it, the board owner matches the address account and not the row's own); judge the row's own
account when the row's own data is that account's (the board's value equals its county value,
Buncombe); otherwise the verifier cannot tell which account is right and answers `unconfirmed`,
reason `ambiguous_account`, never refuted or stale. No account carries the address and the row's
own account carries another one: `address_not_found`. A confirmed answer goes through the same
policy when the row's own account names a different house number on the row's street
(other_number_same_street; tax_lien_buncombe v6: 915 Morgan Hill Rd was confirmed from the balance
of 909 Morgan Hill Rd's parcel).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

#: board sources whose tax_lien / tax_sale listing type is NOT a county property-tax delinquency
NON_PROPERTY_TAX_SOURCES = frozenset({
    "liensnc",
    "counties_generic.liensnc",
    "counties_nc.nc_ecourts_lis_pendens",
    "nc_ecourts_judgments",
    "counties_nc.nc_ecourts_judgments",
    "counties_sc.sc_dew_lien_registry",
    "counties_sc.sc_state_tax_lien",
})

TAX_LISTING_TYPES = frozenset({"tax_lien", "tax_sale"})

#: the qualifier the scorer reads on tax_lien / tax_sale (module docstring, THE SCORER SIDE)
PROPERTY_TAX = "property_tax"

#: what a refuted/stale property-tax verdict takes out of scoring, the same for all three
#: verifiers: the listing-type signals only where the row's claim is a property-tax one, the
#: chronic-delinquency flag (Pickens' roll, property tax), and the recorded_debt credit only
#: where the debt is the tax balance
GOVERNS = (f"tax_lien:{PROPERTY_TAX}", f"tax_sale:{PROPERTY_TAX}", "tax_lien_chronic",
           "recorded_debt:tax")

#: a confirmed balance under this is real but trivial (a payment shortfall); flagged, not dropped
DE_MINIMIS = 25.0

#: first levy year whose payment history is read (module doc, TWO CLAIMS)
HISTORY_FROM_LEVY = 2019
#: late levy years that make a parcel a chronic delinquent: the scorer's own rule for
#: tax_lien_chronic (scrapers/counties_sc/pickens_delinquent_parcels.py: `len(cycles) >= 3`, read by
#: distress_score._collect as raw['pickens_delinquent']['chronic'])
CHRONIC_MIN_LATE_YEARS = 3
#: cap on the bills (Buncombe, PTS Cloud) read for the history of one parcel
MAX_HISTORY_BILLS = 12


def history_claims(late_years: Iterable[int], history_complete: bool) -> str:
    """The chronic claim judged on the bill history: 'confirmed' at CHRONIC_MIN_LATE_YEARS late
    levy years, 'not_confirmed' when the whole history was read and has fewer, else 'unknown'."""
    n = len(set(late_years))
    if n >= CHRONIC_MIN_LATE_YEARS:
        return "confirmed"
    return "not_confirmed" if history_complete else "unknown"


def governs_for(record: Any) -> tuple[str, ...]:
    """The scorer signals a refuted / stale property-tax record removes (registry: governs_for).
    GOVERNS, except tax_lien_chronic when the bill history confirms the chronic claim, or could
    not be read completely: the record's current claim is refuted or stale, the chronic claim is
    a different claim and the evidence does not refute it."""
    ev = record.get("evidence") if isinstance(record, dict) else None
    ev = ev if isinstance(ev, dict) else {}
    if ev.get("chronic_claim") in ("confirmed", "unknown"):
        return tuple(g for g in GOVERNS if g != "tax_lien_chronic")
    return GOVERNS


def first_seen_date(row: Any) -> Optional[date]:
    """The day the board first saw the row (board rows carry first_seen), else None."""
    v = g(row, "first_seen") or g(row, "first_seen_at")
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")[:19]).date()
    except (TypeError, ValueError):
        return None


def paid_after_seen(first_seen: Optional[date], delinquent_from: date, last_late_payment: Any
                    ) -> bool:
    """A late payment dated on or after the day the board first saw the row, of a bill that was
    already delinquent that day: the board saw an open delinquency and it was paid since."""
    if first_seen is None or not last_late_payment:
        return False
    try:
        paid = date.fromisoformat(str(last_late_payment)[:10])
    except ValueError:
        return False
    return first_seen >= delinquent_from and paid >= first_seen


#: raw keys a parcel RESOLVER leaves when it attached the row's parcel id (not the source)
_RESOLVED_PARCEL_KEYS = ("parcel_from_geo", "parcel_from_address")


def parcel_resolved(row: Any) -> bool:
    """True when something other than the row's source attached its parcel id: a resolver
    (raw parcel_from_address / parcel_from_geo), or, for a lien-agent filing, anything at all (a
    liensnc filing names an address and, only when the filer typed one, a PIN: raw.liensnc.pin).
    Such a parcel is a guess, and the address the row's source gave is the better evidence of the
    property."""
    raw = raw_of(row)
    if any(raw.get(k) for k in _RESOLVED_PARCEL_KEYS):
        return True
    lien = raw.get("liensnc")
    return isinstance(lien, dict) and not str(lien.get("pin") or "").strip() \
        and bool(g(row, "parcel_id"))


def value_identity(row: Any, own_value: Optional[float], other_value: Optional[float],
                   tol: float = 0.01) -> bool:
    """True when one of the row's own values (assessed / market / tax) equals the county value of
    its own parcel within `tol` and none equals the other account's: the row's data IS its own
    parcel's record (a county layer row carries the county's value for its PIN), whatever address
    it carries."""
    vals = [float(v) for k in ("assessed_value", "market_value", "tax_value")
            if isinstance(v := g(row, k), (int, float)) and v > 0]

    def near(x: Optional[float]) -> bool:
        return bool(x) and any(abs(v - x) <= tol * x for v in vals)
    return near(own_value) and not near(other_value)


def account_choice(*, own_retired: bool, resolved: bool, own_owner: Optional[str],
                   address_owner: Optional[str], own_value_identity: bool = False
                   ) -> tuple[str, str]:
    """Which account decides, when the row's own account does not carry the row's address and
    exactly one other account does (module doc, WHICH ACCOUNT IS THE ROW'S). Returns
      ("follow", why)     the address account decides: the portal retired the row's own account
                          (own_retired), a resolver attached it (resolved), or the board owner
                          matches the address account and not the row's own (owner_follows_address)
      ("own", why)        the row's own account decides, the address is another property's
                          (own_value_identity: the board's value is its county value)
      ("ambiguous", "ambiguous_account")   nothing proves either: answer unconfirmed."""
    if own_retired:
        return "follow", "portal_retired"
    if resolved:
        return "follow", "parcel_resolved"
    if own_value_identity:
        return "own", "value_identity"
    if own_owner == "different" and address_owner in ("same", "partial"):
        return "follow", "owner_follows_address"
    return "ambiguous", "ambiguous_account"


def g(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def raw_of(row: Any) -> dict:
    r = g(row, "raw")
    return r if isinstance(r, dict) else {}


def ltype(row: Any) -> str:
    v = g(row, "listing_type")
    return str(getattr(v, "value", v) or "").strip().lower()


def to_int(v: Any) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def alnum(s: Any) -> str:
    """Identifier comparison key: uppercase [0-9A-Z] only ("0022-00-00-039." == "0022000039")."""
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def listing_tax_claim(row: Any) -> bool:
    """The row's listing type asserts a property-tax delinquency (not another lien's)."""
    return ltype(row) in TAX_LISTING_TYPES and str(g(row, "source") or "") not in NON_PROPERTY_TAX_SOURCES


def other_lien_listing(row: Any) -> bool:
    """The row is typed tax_lien/tax_sale by a federal/state/lien-agent source (see module doc).
    Takes a board dict, a ledger entry's row summary or a models.Listing."""
    return ltype(row) in TAX_LISTING_TYPES and str(g(row, "source") or "") in NON_PROPERTY_TAX_SOURCES


#: what the retired mixed-row downgrade added to an answer's evidence (module doc, RETIRED)
_DOWNGRADE_KEYS = ("property_tax_verdict", "reason", "listing_claim_source")


def restore_property_tax_verdicts(led: Any, now: datetime) -> list[dict]:
    """OFFLINE, no request: undo the retired mixed-row downgrade in a tax_lien ledger. Every
    entry whose latest is an `unconfirmed` answer with reason other_lien_listing and a refuted /
    stale property_tax_verdict gets that verdict back, the downgrade's three evidence keys
    removed and its checked_at set back to the county check's own time (for an answer the
    2026-10-06 offline migration downgraded: entry["migrated"]["from_checked_at"]). Version,
    keys, row and the rest of the evidence stay as they are. The version is NOT bumped: within
    one verifier version ledger._better lets a decisive answer beat `unconfirmed` in a merge,
    whichever is newer, so a copy of the file written before this cannot bring the downgrade
    back. The unconfirmed answer goes to history; entry["migrated"]["restored"] records the
    step. No entry is dropped. Returns one line per changed entry."""
    from ..core import iso_z         # lazy: this module stays stdlib-only at import time
    from ..ledger import HISTORY_MAX
    stamp = iso_z(now)
    out = []
    for key in sorted(led.rows):
        e = led.rows[key]
        lat = e.get("latest")
        if not isinstance(lat, dict) or lat.get("verdict") != "unconfirmed":
            continue
        ev = lat.get("evidence") or {}
        verdict = ev.get("property_tax_verdict")
        if ev.get("reason") != "other_lien_listing" or verdict not in ("refuted", "stale"):
            continue
        mig = e.get("migrated") if isinstance(e.get("migrated"), dict) else {}
        checked = mig.get("from_checked_at") or lat.get("checked_at")
        hist = [{k: lat.get(k) for k in ("verdict", "checked_at", "verifier", "verifier_version")},
                *(e.get("history") or [])]
        e["history"] = hist[:HISTORY_MAX]
        e["latest"] = dict(lat, verdict=verdict, checked_at=checked,
                           evidence={k: v for k, v in ev.items() if k not in _DOWNGRADE_KEYS})
        e["migrated"] = dict(mig, restored={
            "how": "offline: mixed-row downgrade retired, property_tax_verdict restored, no request",
            "at": stamp, "from_checked_at": lat.get("checked_at")})
        out.append({"key": key, "verdict": verdict, "verifier": lat.get("verifier"),
                    "version": lat.get("verifier_version"), "checked_at": checked,
                    "source": (e.get("row") or {}).get("source")})
    if out and hasattr(led, "_index"):
        led._index = None
    return out


def aging_claim(row: Any) -> bool:
    """The reference's two derived flags: a two-year-plus delinquency, or a surfaced tax-aging
    status with at least one delinquent year."""
    raw = raw_of(row)
    ty, ta = raw.get("two_year_delinquent"), raw.get("tax_aging_surfaced")
    return bool((isinstance(ty, dict) and ty.get("is_two_year_plus"))
                or (isinstance(ta, dict) and ta.get("status") not in (None, "current")
                    and to_int(ta.get("years_delinquent")) > 0))


def claims_property_tax(row: Any, own_block: bool) -> bool:
    return listing_tax_claim(row) or aging_claim(row) or bool(own_block)


def claimed_years_common(row: Any) -> set[int]:
    """Levy years the board's derived blocks say were delinquent."""
    raw = raw_of(row)
    years: set[int] = set()
    ty = raw.get("two_year_delinquent")
    if isinstance(ty, dict) and ty.get("is_two_year_plus"):
        years.add(to_int(ty.get("tax_year")))
    ta = raw.get("tax_aging_surfaced")
    if isinstance(ta, dict) and to_int(ta.get("years_delinquent")) > 0:
        years.add(to_int(ta.get("tax_year")))
    to = raw.get("tax_owed")
    if isinstance(to, dict) and (to.get("balance") or 0):
        years.add(to_int(to.get("year")))
        for y in to.get("years") or []:
            years.add(to_int(y))
    return {y for y in years if 1990 < y < 2100}


#: raw blocks of the board's tax sources that carry the levy year they list
_SKIP_BLOCKS = frozenset({"two_year_delinquent", "tax_aging_surfaced", "tax_owed"})


def source_block_years(row: Any) -> set[int]:
    """Levy years the row's own tax-source blocks name (horry_delinquent_xlsx.tax_year,
    rutherford_tax.tax_year, nc_county_pdf_delinquent_tax.tax_year, ...): any raw block whose
    key names a tax or delinquency source and carries a tax_year / years_unpaid. Only used to
    choose which paid bills to read, never to decide that something is owed."""
    years: set[int] = set()
    for k, v in raw_of(row).items():
        if k in _SKIP_BLOCKS or not isinstance(v, dict):
            continue
        if "tax" not in k and "delinq" not in k:
            continue
        years.add(to_int(v.get("tax_year")))
        for y in v.get("years_unpaid") or []:
            years.add(to_int(y))
    return {y for y in years if 1990 < y < 2100}


def owner_category(board: Optional[str], county_names: Iterable[Optional[str]]) -> Optional[str]:
    """The best owner-match CATEGORY between the board's owner and any owner the county record
    names ('same' > 'partial' > 'different'; None when either side is missing). The names
    themselves are never returned: the ledger is public."""
    from .tax_lien_buncombe import owner_match      # the reference's rule, unchanged
    rank = {"same": 3, "partial": 2, "different": 1}
    best = None
    for name in county_names:
        if not name:
            continue
        try:
            m = owner_match(board, name)
        except Exception:  # noqa: BLE001 - a category is evidence only
            m = None
        if m and (best is None or rank[m] > rank[best]):
            best = m
    return best


# ---------------------------------------------------------------------------
# address binding: does the parcel / account that was checked carry the ROW's address?
# ---------------------------------------------------------------------------
#
# The implementation lives in verification.core (address_key / address_relation / address_query:
# the ledger's address-aware lookup needs it too and must not import a verifier module). They are
# re-exported here under their old names.
from ..core import (  # noqa: E402,F401
    address_key, address_query, address_relation, _ADDR_ALIAS, _ADDR_DIRECTIONS, _ADDR_NOISE,
    _ADDR_SUFFIXES, _ADDR_UNIT)


def same_street(a: Any, b: Any) -> bool:
    """True when both addresses name the same street (the name tokens, whatever the house number
    or suffix): "RICE AVE EXT" is the street of "844 RICE AVENUE EXT"."""
    _, sa, _ = address_key(a)
    _, sb, _ = address_key(b)
    return bool(sa) and sa == sb


def other_number_same_street(row_addr: Any, county_addr: Any) -> bool:
    """True when the county record names a DIFFERENT house number on the row's own street (the row
    says 915 Morgan Hill Rd, the parcel page says 909 Morgan Hill Rd): a neighbor's parcel, which
    must not bind to the row even when it owes (tax_lien_buncombe v6 runs the address search,
    account_choice() and address_not_found for it before a confirmed answer). A record with no
    usable number, or a different street, is not this case."""
    na, _, _ = address_key(row_addr)
    nb, _, _ = address_key(county_addr)
    return bool(na and nb and na != nb and same_street(row_addr, county_addr))


def needs_proof(row_addr: Any, other_addrs: Iterable[Any]) -> bool:
    """Does the row's own account NAME an address that does not carry the row's (so following the
    row's address to another account needs proof the own account is wrong, account_choice)? Yes
    when one of the account's addresses is a different house-numbered address (conflict), or is on
    the row's street without a usable number (the account may well be the row's: same street). No
    when the account names no usable address at all (a county placeholder): it contradicts
    nothing, and the one account that carries the row's address decides."""
    addrs = [x for x in other_addrs if x]
    if any(address_relation(row_addr, x) == "conflict" for x in addrs):
        return True
    return any(same_street(row_addr, x) for x in addrs)


def next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def money_total(by_year: dict) -> float:
    return round(sum(float(v) for v in by_year.values()), 2)


def pick(ev: dict, keys: Iterable[str]) -> dict:
    """A whitelist copy of the evidence (the ledger is public: nothing unlisted is published)."""
    return {k: ev[k] for k in keys if k in ev and ev[k] is not None}
