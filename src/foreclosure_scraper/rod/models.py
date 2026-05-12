"""Shared models for ROD records + lien priority output."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any


@dataclass
class RodDoc:
    """A single recorded document from a county Register of Deeds."""

    county: str
    state: str
    doc_type: str          # DEED / MORT / DT / LIEN / TAX_LIEN / SAT / LP / NOS / ASSIGN
    recorded_date: datetime | None = None
    book: str | None = None
    page: str | None = None
    grantor: str | None = None
    grantee: str | None = None
    amount: float | None = None              # generic numeric column from grid (varies by vendor)
    consideration_amount: float | None = None  # sold/sale price ('Trustee's Deed Upon Sale')
    excise_tax_stamp: float | None = None      # NC: $1 stamp per $500 of consideration
    instrument_no: str | None = None
    parcel_id: str | None = None
    notes: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.recorded_date:
            d["recorded_date"] = self.recorded_date.isoformat()
        return d


@dataclass
class LienPosition:
    """Computed lien-priority output for one property."""

    foreclosing_position: int | None = None      # 1=1st mortgage, 2=2nd, etc.
    foreclosing_doc: dict | None = None
    senior_liens: list[dict] = field(default_factory=list)   # take subject to
    junior_liens: list[dict] = field(default_factory=list)   # wiped out at sale
    total_senior_amount: float | None = None
    total_junior_amount: float | None = None
    super_priority_warnings: list[str] = field(default_factory=list)
    title_risk_summary: str | None = None
    docs_examined: int = 0
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Doc-type taxonomy -> bucket
DOC_BUCKETS: dict[str, str] = {
    # Conveyances (ordered general -> specific intentionally; the
    # normalize function checks longer keys before shorter so post-sale
    # variants like "TRUSTEES DEED UPON SALE" don't collapse to "DEED")
    "DEED": "deed",
    "DT": "mortgage",        # Deed of Trust (NC) = mortgage equivalent
    "MORT": "mortgage",
    "MORTGAGE": "mortgage",
    "DEED OF TRUST": "mortgage",
    # Post-sale (foreclosure-auction-completed) recordings — keep the
    # original wording so _is_post_sale predicates work downstream.
    "TRUSTEES DEED UPON SALE": "post_sale_deed",
    "TRUSTEE'S DEED UPON SALE": "post_sale_deed",
    "TRUSTEES DEED": "post_sale_deed",
    "TRUSTEE'S DEED": "post_sale_deed",
    "SUBSTITUTE TRUSTEES DEED": "post_sale_deed",
    "SUBSTITUTE TRUSTEE'S DEED": "post_sale_deed",
    "FORECLOSURE DEED": "post_sale_deed",
    "DEED UNDER POWER OF SALE": "post_sale_deed",
    "COMMISSIONERS DEED": "post_sale_deed",
    "COMMISSIONER'S DEED": "post_sale_deed",
    # Liens
    "LIEN": "lien",
    "JUDGMENT": "lien",
    "TAX LIEN": "tax_lien",
    "TAX": "tax_lien",
    "MECHANICS LIEN": "mechanics_lien",
    "HOA LIEN": "hoa_lien",
    # Releases / cancellations
    "SAT": "satisfaction",
    "SATISFACTION": "satisfaction",
    "RELEASE": "satisfaction",
    "CANCELLATION": "satisfaction",
    # Lis pendens / NOS / NOD (pre-foreclosure trigger)
    "LIS PENDENS": "lis_pendens",
    "LP": "lis_pendens",
    "NOTICE OF SALE": "notice_of_sale",
    "NOS": "notice_of_sale",
    "NOTICE OF DEFAULT": "notice_of_default",
    "NOD": "notice_of_default",
    "NOTICE OF FORECLOSURE": "notice_of_default",
    "NOTICE OF FORECLOSURE SALE": "notice_of_sale",
    "DEFAULT NOTICE": "notice_of_default",
    # Assignments
    "ASSIGN": "assignment",
    "ASSIGNMENT": "assignment",
    # Probate-driven recordings (estate is settling, heirs may want to sell)
    "EXECUTORS DEED": "probate_deed",
    "EXECUTOR'S DEED": "probate_deed",
    "ADMINISTRATORS DEED": "probate_deed",
    "ADMINISTRATOR'S DEED": "probate_deed",
    "PERSONAL REPRESENTATIVES DEED": "probate_deed",
    "PERSONAL REPRESENTATIVE'S DEED": "probate_deed",
    "DEVISE": "probate_deed",
    "AFFIDAVIT OF HEIRS": "probate_deed",
    "WILL": "probate_deed",
    # Divorce-driven recordings: deed dividing marital property
    "DIVORCE DECREE": "divorce_deed",
    "DECREE OF DIVORCE": "divorce_deed",
    "EQUITABLE DISTRIBUTION": "divorce_deed",
    "QUITCLAIM DEED": "quitclaim",
    "QUIT CLAIM DEED": "quitclaim",
    "QC DEED": "quitclaim",
}


def normalize_doc_type(raw: str | None) -> str:
    """Map a raw recorder-of-deeds doc-type label to a canonical key.

    Substring matching prefers LONGER bucket keys first so that
    'TRUSTEES DEED UPON SALE' doesn't collapse to plain 'DEED'. The
    return value is the matched canonical key (still uppercase, still
    contains the word 'TRUSTEE' for post-sale predicates downstream)."""
    if not raw:
        return "UNKNOWN"
    s = raw.strip().upper()
    # Exact match wins
    if s in DOC_BUCKETS:
        return s
    # Longest-first substring match — protects against generic-key
    # capture (DEED, TAX, LIEN) over more-specific variants.
    for k in sorted(DOC_BUCKETS, key=len, reverse=True):
        if k in s:
            return k
    return s
