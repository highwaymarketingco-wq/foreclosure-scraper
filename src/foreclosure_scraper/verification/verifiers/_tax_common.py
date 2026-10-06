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
# WHY (2026-10-06 recheck of all 103 stale verdicts, 7 of them wrong): a row's parcel id and its
# street address can belong to DIFFERENT parcels (a retired / recombined PIN, a roll block merged
# into another parcel's row, a resolver that matched a road name). A stale or refuted verdict
# removes the claim from the lead's score, so it may only be issued from the parcel that carries
# the row's address. address_relation() is the shared yes / no / cannot-tell; each verifier
# decides what to do with a "conflict" (follow the address, or answer unconfirmed).

_ADDR_ALIAS = {
    "ROAD": "RD", "STREET": "ST", "DRIVE": "DR", "TERRACE": "TER", "TERR": "TER",
    "AVENUE": "AVE", "BOULEVARD": "BLVD", "LANE": "LN", "COURT": "CT", "CIRCLE": "CIR",
    "TRAIL": "TRL", "HIGHWAY": "HWY", "EXTENSION": "EXT", "PLACE": "PL", "PARKWAY": "PKWY",
    "MOUNTAIN": "MTN", "POINT": "PT", "COVE": "CV", "RIDGE": "RDG", "HEIGHTS": "HTS",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
    "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
_ADDR_SUFFIXES = frozenset({"RD", "ST", "DR", "TER", "AVE", "BLVD", "LN", "CT", "CIR", "TRL",
                            "HWY", "EXT", "PL", "PKWY", "WAY", "LOOP", "PT", "CV", "RDG", "HTS",
                            "PIKE", "ALY", "SQ", "XING", "TRCE", "RUN", "PATH", "BND", "CRK"})
_ADDR_DIRECTIONS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})
_ADDR_UNIT = frozenset({"APT", "UNIT", "STE", "SUITE", "LOT", "TRLR", "BLDG", "BUILDING", "SPC",
                        "SPACE", "FL", "FLOOR", "RM", "ROOM"})
#: words the counties append that are not part of the street ("242 P GIBBS RD UNINCORPORATED")
_ADDR_NOISE = frozenset({"UNINCORPORATED", "UNINCORPORAT", "UNINC", "NC", "SC", "USA", "UNITED",
                         "STATES", "COUNTY"})


def address_key(addr: Any) -> tuple[Optional[str], frozenset, frozenset]:
    """(house number or None, street name tokens, suffix + direction tokens) of an address.
    The city / state / zip after the first comma are dropped (a Nominatim style "804, Trailwinds
    Drive, Oconee County, ..." keeps its second part), "1/2" and a unit tail are dropped, leading
    zeros are stripped ("000399 OAKHILL DRIVE" == "399 OAKHILL DR"), suffixes are normalized
    (ROAD == RD). A placeholder number (all nines, zero) is no number."""
    s = str(addr or "").upper()
    parts = [p.strip() for p in s.split(",")]
    head = parts[0] if parts else ""
    if re.fullmatch(r"\d+[A-Z]?", head) and len(parts) > 1:
        head = f"{head} {parts[1]}"
    head = re.sub(r"\b\d+\s*/\s*\d+\b", " ", head)
    toks = re.findall(r"[A-Z0-9]+", head)
    for i, t in enumerate(toks):
        if i > 0 and t in _ADDR_UNIT:
            toks = toks[:i]
            break
    number = None
    if toks:
        m = re.fullmatch(r"(\d+)([A-Z]?)", toks[0])
        if m:
            digits_ = m.group(1).lstrip("0")
            if digits_ and not (len(digits_) >= 4 and set(digits_) == {"9"}):
                number = digits_ + m.group(2)
            toks = toks[1:]
    toks = [_ADDR_ALIAS.get(t, t) for t in toks
            if t not in _ADDR_NOISE and not re.fullmatch(r"\d{5}(\d{4})?", t)]
    name = frozenset(t for t in toks if t not in _ADDR_SUFFIXES and t not in _ADDR_DIRECTIONS)
    tail = frozenset(t for t in toks if t in _ADDR_SUFFIXES or t in _ADDR_DIRECTIONS)
    return number, name, tail


def address_relation(a: Any, b: Any) -> str:
    """'match' | 'conflict' | 'unknown' between a row's address and the one on a county record.
    unknown: either side has no usable house number or street name (a road name alone, a
    placeholder number): nothing is claimed either way. match: same house number, same street
    name tokens, and suffix / direction tokens equal or missing on one side. conflict: anything
    else (a different number or street: the record is another property's)."""
    na, sa, ta = address_key(a)
    nb, sb, tb = address_key(b)
    if not na or not nb or not sa or not sb:
        return "unknown"
    if na == nb and sa == sb and (ta == tb or not ta or not tb):
        return "match"
    return "conflict"


def address_query(addr: Any) -> Optional[str]:
    """The house number and street NAME of a row's address as a search string ("810 ROBINSON"
    for "810 ROBINSON TERRACE"), or None when the row has no house-numbered address (a road name
    alone cannot identify a parcel). The suffix is left off on purpose: the portals' address
    searches match text as THEY write it (Henderson's "807 ROBINSON TER" is not found by
    "807 ROBINSON TERRACE"); address_relation() then keeps only the exact matches."""
    s = str(addr or "")
    parts = [p.strip() for p in s.split(",")]
    head = parts[0].upper() if parts else ""
    if re.fullmatch(r"\d+[A-Z]?", head) and len(parts) > 1:
        head = f"{head} {parts[1].upper()}"
    head = re.sub(r"\b\d+\s*/\s*\d+\b", " ", head)
    toks = re.findall(r"[A-Z0-9]+", head)
    if not toks or not re.fullmatch(r"\d+[A-Z]?", toks[0]):
        return None
    number, name, _ = address_key(s)
    if not number or not name:
        return None
    stem = [toks[0].lstrip("0") or toks[0]]
    for t in toks[1:]:
        if t in _ADDR_UNIT or t in _ADDR_NOISE:
            break
        a = _ADDR_ALIAS.get(t, t)
        if (a in _ADDR_SUFFIXES or a in _ADDR_DIRECTIONS) and len(stem) > 1 and stem[-1] not in _ADDR_DIRECTIONS:
            break
        stem.append(t)
    return " ".join(stem)


def next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def money_total(by_year: dict) -> float:
    return round(sum(float(v) for v in by_year.values()), 2)


def pick(ev: dict, keys: Iterable[str]) -> dict:
    """A whitelist copy of the evidence (the ledger is public: nothing unlisted is published)."""
    return {k: ev[k] for k in keys if k in ev and ev[k] is not None}
