"""Shared pieces of the per-vendor tax_lien verifiers (tax_lien_ptscloud, tax_lien_qpaybill).

Private (the leading underscore keeps the registry from loading it as a verifier). Pure: no I/O.

WHICH ROWS CARRY THE PROPERTY-TAX CLAIM. The reference (tax_lien_buncombe.flagged) takes every
row typed tax_lien plus the two derived delinquency flags. Outside Buncombe that is not safe: a
large share of the rows typed tax_lien / tax_sale are OTHER liens that a county property-tax
record cannot speak to, measured on the 2026-10-05 board (board_stream, read-only):

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
listing-type signal is never removed by a property-tax record.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
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
    """The row is typed tax_lien/tax_sale by a federal/state/lien-agent source (see module doc)."""
    return ltype(row) in TAX_LISTING_TYPES and str(g(row, "source") or "") in NON_PROPERTY_TAX_SOURCES


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
