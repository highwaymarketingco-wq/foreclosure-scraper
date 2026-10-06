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

A refuted or stale verdict GOVERNS tax_lien / tax_sale, so checking such a row against the county
tax portal would strip a federal or state lien's signal because the PROPERTY tax is paid. So a
listing-type claim from these sources is not a property-tax claim here; the row is still covered
when it carries a property-tax claim of its own (a delinquency flag or the vendor's roll block),
and then a refuted/stale answer is downgraded to unconfirmed (other_lien_listing) so the lien's
listing-type signal is never removed by a property-tax record. All three verifiers apply this
(tax_lien_buncombe since v3: 1,094 Buncombe rows typed tax_lien by liensnc / eCourts).

THE SCORER SIDE (GOVERNS). The ledger is keyed by PROPERTY, so a separate board row of another
lien on the same parcel inherits the parcel's property-tax verdict. GOVERNS therefore names the
listing-type signals with a qualifier, "tax_lien:property_tax" / "tax_sale:property_tax" (the
"incarceration:jail" pattern): both readers (distress_score._collect,
enrichment_lead_signals._facet_signals) end tax_lien / tax_sale only where it comes from a
property-tax claim, never the listing type of an other_lien_listing() row.
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

#: verdicts the mixed-row rule downgrades
_DOWNGRADED = frozenset({"refuted", "stale"})

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


def other_lien_downgrade(verdict: str, ev: dict, row: Any) -> tuple[str, dict]:
    """The mixed-row rule, one copy for every tax_lien verifier: a refuted or stale property-tax
    answer on a row typed tax_lien/tax_sale by another lien's source is published `unconfirmed`
    (reason other_lien_listing, the property-tax answer kept as property_tax_verdict), so a paid
    property tax never removes that lien's signal. Anything else passes through unchanged."""
    if verdict in _DOWNGRADED and row is not None and other_lien_listing(row):
        return "unconfirmed", dict(ev, property_tax_verdict=verdict, reason="other_lien_listing",
                                   listing_claim_source=g(row, "source"))
    return verdict, ev


def downgrade_other_lien_entries(led: Any, verifier: str, version: str, now: datetime
                                 ) -> list[dict]:
    """OFFLINE, no request: apply other_lien_downgrade() to the ledger entries `verifier` wrote
    before it had the rule (tax_lien_buncombe v1/v2). An entry whose latest is that verifier's
    refuted/stale answer on a row typed tax_lien/tax_sale by another lien's source (the entry's
    `row` summary: the row that answer was recorded on) gets the answer the rule produces, as
    `version`: verdict unconfirmed, the same evidence plus property_tax_verdict / reason /
    listing_claim_source. The old latest goes to history; entry["migrated"] keeps its version,
    verdict and checked_at. Its checked_at is `now`: ledger._better lets the newer of two
    different-version answers win, so a merge with an older copy of the file cannot bring the
    refuted/stale answer back. No entry is dropped. Returns one line per changed entry
    ({key, from_verdict, from_version, source})."""
    from ..core import iso_z         # lazy: this module stays stdlib-only at import time
    from ..ledger import HISTORY_MAX
    stamp = iso_z(now)
    out = []
    for key in sorted(led.rows):
        e = led.rows[key]
        lat = e.get("latest")
        row = e.get("row")
        if not isinstance(lat, dict) or lat.get("verifier") != verifier \
                or lat.get("verifier_version") == version or not isinstance(row, dict):
            continue
        verdict, ev = other_lien_downgrade(str(lat.get("verdict") or ""),
                                           dict(lat.get("evidence") or {}), row)
        if verdict == lat.get("verdict"):
            continue
        hist = [{k: lat.get(k) for k in ("verdict", "checked_at", "verifier", "verifier_version")},
                *(e.get("history") or [])]
        e["history"] = hist[:HISTORY_MAX]
        e["latest"] = dict(lat, verdict=verdict, evidence=ev, verifier_version=version,
                           checked_at=stamp)
        e["migrated"] = {"how": "offline: _tax_common.other_lien_downgrade, no request",
                         "at": stamp, "from_version": lat.get("verifier_version"),
                         "from_verdict": lat.get("verdict"),
                         "from_checked_at": lat.get("checked_at")}
        out.append({"key": key, "from_verdict": lat.get("verdict"),
                    "from_version": lat.get("verifier_version"), "source": row.get("source")})
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


def next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def money_total(by_year: dict) -> float:
    return round(sum(float(v) for v in by_year.values()), 2)


def pick(ev: dict, keys: Iterable[str]) -> dict:
    """A whitelist copy of the evidence (the ledger is public: nothing unlisted is published)."""
    return {k: ev[k] for k in keys if k in ev and ev[k] is not None}
