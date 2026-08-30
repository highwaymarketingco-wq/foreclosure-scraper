"""Deed chain history enricher — synthesize ownership transfer timeline.

Aggregates deed/sale records from ALL available sources into a single
chronological chain at raw["deed_chain"], then stamps summary fields:
  - prior_owner    : previous grantor (before current owner)
  - prior_sale_date: when current owner acquired
  - prior_sale_price: acquisition price (if known)
  - chain_length   : number of recorded transfers
  - chain_breaks   : quitclaim, $1 sales, inheritance, divorce patterns
  - first_recorded : earliest deed on record (original grant)

SOURCES (all already gathered by other enrichers — this is OFFLINE/sync):
  1. assessor_card.sales  — qpublic/Schneider assessor cards (6.9% coverage)
  2. county_sales         — ArcGIS sales rolls (5.2% coverage)
  3. gis.last_sale        — GIS parcel last-sale data (46.1% coverage)
  4. rod_docs             — ROD name-index documents (0.4% coverage)
  5. relationship_signal  — probate/divorce deed signals (from enrichment_relationship_deeds)

This enricher is 100% OFFLINE — no network calls. It only reorganizes data
that was already gathered by network enrichers into a unified timeline.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# Dollar amounts that indicate non-arms-length transfers
_LOVE_AND_AFFECTION = {1.0, 0.0, 10.0, 100.0}
# Doc types that indicate non-arms-length / distress transfers
_DISTRESS_TYPES = (
    "QUITCLAIM", "QUIT CLAIM", "QC",
    "DEED OF DISTRIBUTION", "PERSONAL REPRESENTATIVE",
    "EXECUTOR", "ADMINISTRATOR",
    "COMMISSIONER",  # court-ordered partition/judicial sale
    "SURVIVORSHIP",
    "AFFIDAVIT OF HEIR",
    "WARRANTY DEED TO TRUST",
)
# Pattern for extracting year from date strings
_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})")


def _parse_date(val: Any) -> Optional[str]:
    """Normalize a date value to ISO date string (YYYY-MM-DD or YYYY-MM)."""
    if val is None or val == "":
        return None
    s = str(val).strip()
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if re.match(r"^\d{4}-\d{2}$", s):
        return s
    # MM/DD/YYYY
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            m, d, y = parts
            if len(y) == 4:
                return f"{y}-{int(m):02d}-{int(d):02d}"
    # Epoch millis
    if s.isdigit() and len(s) >= 13:
        try:
            return datetime.fromtimestamp(int(s) / 1000).date().isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    # YYYYMMDD
    if s.isdigit() and len(s) == 8:
        y, m, d = s[:4], s[4:6], s[6:8]
        if "1700" <= y <= "2100":
            return f"{y}-{m}-{d}"
    # Just a year
    m = _YEAR_RE.match(s)
    if m:
        return m.group(1)
    return None


def _parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    m = _YEAR_RE.search(str(date_str))
    if m:
        return int(m.group(1))
    return None


def _money(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s or s == ".":
        return None
    try:
        f = float(s)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _is_distress_sale(price: Optional[float], doc_type: str = "") -> bool:
    """Flag quitclaims, $1 sales, executor deeds, etc."""
    dt = doc_type.upper().strip()
    if any(k in dt for k in _DISTRESS_TYPES):
        return True
    if price is not None and price in _LOVE_AND_AFFECTION:
        return True
    return False


def _collect_records(li: Listing) -> list[dict]:
    """Gather all sale/deed records from every source on this listing."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    records: list[dict] = []

    # 1. assessor_card.sales — richest source, has grantor + price + book/page
    ac = raw.get("assessor_card")
    if isinstance(ac, dict) and isinstance(ac.get("sales"), list):
        for s in ac["sales"]:
            if not isinstance(s, dict):
                continue
            records.append({
                "date": _parse_date(s.get("sale_date")),
                "price": _money(s.get("price")),
                "book": s.get("book"),
                "page": s.get("page"),
                "grantor": s.get("grantor"),
                "grantee": s.get("grantee"),
                "reason": s.get("reason"),
                "source": "assessor_card",
            })

    # 2. county_sales — ArcGIS sales roll comps
    cs = raw.get("county_sales")
    if isinstance(cs, dict) and isinstance(cs.get("sales"), list):
        for s in cs["sales"]:
            if not isinstance(s, dict):
                continue
            records.append({
                "date": _parse_date(s.get("date")),
                "price": _money(s.get("price")),
                "sale_type": s.get("sale_type"),
                "arms_length": s.get("arms_length"),
                "source": "county_sales",
            })

    # 3. gis.last_sale — single most recent sale
    gis = raw.get("gis")
    if isinstance(gis, dict):
        ls = gis.get("last_sale")
        if isinstance(ls, dict) and ls:
            records.append({
                "date": _parse_date(ls.get("date")),
                "price": _money(ls.get("amount")),
                "book": ls.get("book"),
                "page": ls.get("page"),
                "source": "gis.last_sale",
            })

    # 4. rod_docs — ROD name-index documents
    rod = raw.get("rod_docs")
    if isinstance(rod, list):
        for d in rod:
            if not isinstance(d, dict):
                continue
            dt = str(d.get("doc_type") or "")
            # Only include deed-type documents (not mortgages/liens)
            if any(k in dt.upper() for k in ("DEED", "QUITCLAIM", "WARRANTY",
                                              "DISTRIBUTION", "COMMISSIONER",
                                              "SURVIVORSHIP", "EXECUTOR",
                                              "ADMINISTRATOR")):
                records.append({
                    "date": _parse_date(d.get("recorded_date")),
                    "price": _money(d.get("amount")),
                    "book": d.get("book"),
                    "page": d.get("page"),
                    "doc_type": dt,
                    "county": d.get("county"),
                    "source": "rod_docs",
                })

    # 5. relationship_signal — probate/divorce deed patterns
    rs = raw.get("relationship_signal")
    if isinstance(rs, dict):
        records.append({
            "date": _parse_date(rs.get("date")),
            "doc_type": rs.get("signal"),
            "grantor": rs.get("grantor"),
            "grantee": rs.get("grantee"),
            "source": "relationship_signal",
        })

    return records


def _build_chain(records: list[dict]) -> list[dict]:
    """Sort records into a chronological deed chain, newest first."""
    # Dedupe by (date, book, page, source) — same deed from multiple sources
    seen = set()
    deduped = []
    for r in records:
        key = (r.get("date"), r.get("book"), r.get("page"), r.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # Sort newest first; None dates go to the end
    def _sort_key(r):
        d = r.get("date") or ""
        return (d != "", d) if d else (False, "")

    deduped.sort(key=_sort_key, reverse=True)
    return deduped


def _summarize(chain: list[dict], li: Listing) -> dict:
    """Extract summary fields from the deed chain."""
    summary: dict[str, Any] = {
        "chain_length": len(chain),
        "prior_owner": None,
        "prior_sale_date": None,
        "prior_sale_price": None,
        "first_recorded": None,
        "chain_breaks": [],
        "distress_transfers": [],
    }

    if not chain:
        return summary

    # First recorded deed (oldest = last in chain since newest-first)
    oldest = chain[-1]
    summary["first_recorded"] = oldest.get("date")
    if _parse_year(oldest.get("date")):
        summary["first_recorded_year"] = _parse_year(oldest.get("date"))

    # Most recent sale = chain[0] (newest first)
    most_recent = chain[0]
    summary["prior_sale_date"] = most_recent.get("date")
    summary["prior_sale_price"] = most_recent.get("price")

    # Find the grantor on the most recent transfer = previous owner
    for r in chain:
        if r.get("grantor"):
            summary["prior_owner"] = r["grantor"]
            break

    # Flag distress transfers (quitclaims, $1 sales, probate, divorce)
    for r in chain:
        price = r.get("price")
        doc_type = str(r.get("doc_type") or r.get("reason") or "")
        if _is_distress_sale(price, doc_type):
            summary["distress_transfers"].append({
                "date": r.get("date"),
                "price": price,
                "doc_type": doc_type or None,
                "source": r.get("source"),
            })

    # Chain breaks: $1 sales, quitclaim, no consideration
    for r in chain:
        price = r.get("price")
        dt = str(r.get("doc_type") or r.get("reason") or "").upper()
        if price is not None and price in _LOVE_AND_AFFECTION:
            summary["chain_breaks"].append({
                "type": "love_and_affection",
                "date": r.get("date"),
                "price": price,
            })
        elif any(k in dt for k in ("QUITCLAIM", "QUIT CLAIM", "QC")):
            summary["chain_breaks"].append({
                "type": "quitclaim",
                "date": r.get("date"),
            })
        elif any(k in dt for k in ("EXECUTOR", "ADMINISTRATOR", "DISTRIBUTION",
                                    "COMMISSIONER", "AFFIDAVIT OF HEIR")):
            summary["chain_breaks"].append({
                "type": "probate_or_court",
                "date": r.get("date"),
                "doc_type": dt,
            })

    # Ownership duration: years since most recent recorded transfer
    yr = _parse_year(most_recent.get("date"))
    if yr:
        now_yr = datetime.now().year
        summary["ownership_years"] = now_yr - yr
        # Long ownership = potential inherited/old-money property
        if summary["ownership_years"] >= 20:
            summary["long_ownership"] = True

    # Transfer velocity: multiple transfers in short period = flipping activity
    years_with_dates = [r for r in chain if _parse_year(r.get("date"))]
    if len(years_with_dates) >= 3:
        yrs_list = sorted([y for y in [_parse_year(r.get("date")) for r in years_with_dates] if y is not None])
        span = yrs_list[-1] - yrs_list[0]
        if span > 0:
            summary["transfer_rate"] = round(len(years_with_dates) / span, 2)

    return summary


def enrich_deed_chain(listings: Iterable[Listing]) -> dict:
    """Build unified deed chain timeline from all available sale records.

    100% OFFLINE — no network calls. Reorganizes data already gathered
    by assessor_card, county_sales, gis, rod_docs, and relationship_signal
    enrichers into a chronological chain with summary flags.
    """
    listings = list(listings)
    stamped = 0
    total_records = 0
    has_chain = 0
    has_distress = 0
    has_breaks = 0

    for li in listings:
        records = _collect_records(li)
        if not records:
            continue

        chain = _build_chain(records)
        if not chain:
            continue

        summary = _summarize(chain, li)

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["deed_chain"] = {
            "transfers": chain,
            "summary": summary,
        }

        stamped += 1
        total_records += len(chain)
        if summary.get("chain_length", 0) > 0:
            has_chain += 1
        if summary.get("distress_transfers"):
            has_distress += 1
        if summary.get("chain_breaks"):
            has_breaks += 1

    log.info("deed_chain.done",
             listings=len(listings),
             stamped=stamped,
             total_records=total_records,
             with_distress=has_distress,
             with_breaks=has_breaks)

    return {
        "stamped": stamped,
        "total_records": total_records,
        "with_chain": has_chain,
        "with_distress_transfers": has_distress,
        "with_chain_breaks": has_breaks,
    }
