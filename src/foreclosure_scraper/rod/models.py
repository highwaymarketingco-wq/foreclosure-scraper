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
    amount: float | None = None
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
    # Conveyances
    "DEED": "deed",
    "DT": "mortgage",        # Deed of Trust (NC) = mortgage equivalent
    "MORT": "mortgage",
    "MORTGAGE": "mortgage",
    "DEED OF TRUST": "mortgage",
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
    # Lis pendens / NOS
    "LIS PENDENS": "lis_pendens",
    "LP": "lis_pendens",
    "NOTICE OF SALE": "notice_of_sale",
    "NOS": "notice_of_sale",
    # Assignments
    "ASSIGN": "assignment",
    "ASSIGNMENT": "assignment",
}


def normalize_doc_type(raw: str | None) -> str:
    if not raw:
        return "UNKNOWN"
    s = raw.strip().upper()
    # First try exact bucket match
    if s in DOC_BUCKETS:
        return s
    # Substring match for variants
    for k in DOC_BUCKETS:
        if k in s:
            return k
    return s
