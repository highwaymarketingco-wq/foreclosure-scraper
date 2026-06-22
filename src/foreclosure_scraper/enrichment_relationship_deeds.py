"""Detect probate + post-divorce deed-recording patterns in the ROD pool.

Both signals indicate motivated-seller leads:
  - **Probate**: someone died, the executor recorded a deed transferring
    the property to the estate or to heirs. Heirs typically want to
    liquidate fast (avoid carrying costs, simplify the inheritance split).
  - **Post-divorce**: a couple recorded a quitclaim / equitable-distribution
    deed transferring the marital property from joint to individual
    ownership. The newly-individual owner often sells within 6-12 months.

Both are FREE signals — we already scrape ROD recordings for the post-sale
foreclosure sweep. This module re-scans the same data with different
pattern detectors and tags listings with raw["relationship_signal"].

Signal types:
  - "probate"   — executor/administrator/PR deed, deed of distribution (SC),
                  devise, estate-of, will
  - "divorce"   — deed/memorandum of separation, OR quitclaim with $0
                  consideration AND a couple-to-single grantor pattern
  - "partition" — Commissioner's Deed (court-ordered partition / judicial
                  sale, often heirs' property). Tagged for distress context
                  only; not promoted to a new lead (sale already complete).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import structlog

from .models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Probate doc-type keywords — match against raw doc-type strings from ROD.
# 'WILL' is intentionally absent because it gets too many false positives
# ("the property will be sold"). EXECUTOR / TESTAMENTARY / DEVISE all
# imply WILL anyway and are unambiguous.
PROBATE_KEYWORDS = (
    "EXECUTOR",
    "ADMINISTRATOR",
    "PERSONAL REPRESENTATIVE",
    "DEED OF DISTRIBUTION",  # SC statutory PR instrument (SC Code §62-3-907/908)
    "DEVISE",
    "AFFIDAVIT OF HEIRS",
    "ESTATE OF",
    "DECEASED",
    "TESTAMENTARY",
    "LAST WILL",         # 'LAST WILL [AND TESTAMENT]' is unambiguous
    "WILL AND TESTAMENT",
)

# Partition / forced-sale instruments. A Commissioner's Deed conveys property
# sold under a court-ordered partition or judicial sale (often heirs' property
# being force-split) — a genuine distress marker. Require the full phrase: bare
# 'COMMISSIONER' is too broad (County Commissioner, commission language).
# NOTE: a commissioner's deed is the deed TO the purchaser, so the sale is
# usually already complete at recording — treated as a distress context/comp
# signal, not promoted to a new lead.
PARTITION_KEYWORDS = (
    "COMMISSIONER'S DEED",
    "COMMISSIONERS DEED",
)

# Quitclaim doc-type keywords — divorce candidates record one of these
QUITCLAIM_KEYWORDS = (
    "QUITCLAIM",
    "QUIT CLAIM",
    "QC DEED",
    "DIVORCE DECREE",
    "DECREE OF DIVORCE",
    "EQUITABLE DISTRIBUTION",
)

# Marital-separation instruments that ARE recorded at the ROD (NC G.S. §39-13.4).
# Direct, marital-specific matches — they bypass the consideration/grantor gate
# in _looks_divorce because the instrument itself is inherently a divorce signal.
SEPARATION_KEYWORDS = (
    "DEED OF SEPARATION",
    "MEMORANDUM OF SEPARATION",
)

# Grantor-grantee couple-to-single divorce pattern.
# Grantor "JOHN AND JANE SMITH" or "JOHN SMITH AND JANE SMITH" → grantee
# "JOHN SMITH" alone (one of the original two). Strong divorce signal.
COUPLE_GRANTOR_RE = re.compile(
    r"\b([A-Z][A-Za-z'\-]+)\s+(?:[A-Z][A-Za-z'\-]+\s+)?(?:AND|&)\s+"
    r"([A-Z][A-Za-z'\-]+)\s+([A-Z][A-Za-z'\-]+)\b",
    re.I,
)


def _looks_probate(li: Listing) -> Optional[str]:
    """Return the matched keyword if doc-type/text looks probate-driven."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    blob_parts = [
        raw.get("doc_type", ""),
        raw.get("notes", ""),
        li.description or "",
    ]
    rod_section = raw.get("rod") if isinstance(raw.get("rod"), dict) else {}
    blob_parts.extend([
        rod_section.get("doc_type", ""),
        rod_section.get("grantor", ""),
        rod_section.get("notes", ""),
    ])
    blob = " ".join(str(p) for p in blob_parts if p).upper()
    for kw in PROBATE_KEYWORDS:
        if kw in blob:
            return kw.strip()
    return None


def _looks_divorce(li: Listing) -> Optional[str]:
    """Return matched signal if this looks like a divorce-driven deed:

      - Doc type matches a quitclaim / divorce-decree keyword AND
      - Either consideration is $0/missing OR the grantor-grantee pattern
        indicates couple → single transfer.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    rod_section = raw.get("rod") if isinstance(raw.get("rod"), dict) else {}
    doc_type_blob = " ".join(
        str(x) for x in (raw.get("doc_type", ""), rod_section.get("doc_type", ""))
        if x
    ).upper()

    # Direct marital-instrument match — a deed/memorandum of separation IS the
    # divorce signal on its own; no $0-consideration / couple-name gate needed.
    if any(kw in doc_type_blob for kw in SEPARATION_KEYWORDS):
        return "deed_of_separation"

    if not any(kw in doc_type_blob for kw in QUITCLAIM_KEYWORDS):
        return None

    consideration = (
        raw.get("consideration_amount")
        or rod_section.get("consideration_amount")
        or raw.get("actual_sold_price")
        or 0
    )
    try:
        consideration = float(consideration)
    except (TypeError, ValueError):
        consideration = 0.0

    grantor = (raw.get("grantor") or rod_section.get("grantor") or "").upper()
    grantee = (raw.get("grantee") or rod_section.get("grantee") or "").upper()

    # Strongest signal: quitclaim + $0 consideration + couple-to-single
    if consideration <= 1.0 and grantor and grantee:
        m = COUPLE_GRANTOR_RE.search(grantor)
        if m and m.group(3).upper() in grantee:
            # Couple's last name appears in grantee — single-spouse transfer
            return "couple_to_single_quitclaim"

    # Weaker signal: quitclaim + $0 (no name pattern) — could be gift,
    # could be divorce. Tag conservatively.
    if consideration <= 1.0:
        return "zero_consideration_quitclaim"

    return None


def _looks_partition(li: Listing) -> Optional[str]:
    """Return the matched keyword if the doc-type looks like a court-ordered
    partition / judicial sale (Commissioner's Deed)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    rod_section = raw.get("rod") if isinstance(raw.get("rod"), dict) else {}
    blob = " ".join(
        str(x) for x in (
            raw.get("doc_type", ""), raw.get("notes", ""),
            rod_section.get("doc_type", ""), li.description or "",
        ) if x
    ).upper()
    for kw in PARTITION_KEYWORDS:
        if kw in blob:
            return kw.strip()
    return None


def enrich_with_relationship_deeds(
    listings: list[Listing],
    sold_pool: Optional[list[Listing]] = None,
) -> list[Listing]:
    """Tag ROD-derived listings with probate / divorce signals + emit
    new ListingType.PROBATE_NOTICE / DIVORCE_NOTICE listings for
    detected matches.

    Returns: list of newly-emitted Listing objects (caller can append
    to the active pool). Existing listings are mutated in-place to add
    raw["relationship_signal"].
    """
    # H5 FIX (2026-05-08): track which pool each listing came from so
    # we only emit derived listings for SOLD POOL matches (those need
    # surfacing into the active pool to be visible). For listings
    # already in the active pool, the in-place tag is enough — emitting
    # a derived copy was creating a duplicate of every probate ROD record.
    active_ids = {id(li) for li in (listings or [])}
    pool: list[Listing] = []
    pool.extend(listings or [])
    pool.extend(sold_pool or [])

    new_listings: list[Listing] = []
    counts = {
        "scanned": 0,
        "probate_tagged": 0,
        "divorce_tagged": 0,
        "partition_tagged": 0,
        "probate_emitted": 0,
        "divorce_emitted": 0,
        "emit_skipped_already_in_active": 0,
    }
    seen_keys: set[str] = set()

    for li in pool:
        counts["scanned"] += 1

        probate_kw = _looks_probate(li)
        divorce_kw = _looks_divorce(li)
        partition_kw = None if (probate_kw or divorce_kw) else _looks_partition(li)
        if not (probate_kw or divorce_kw or partition_kw):
            continue

        if not isinstance(li.raw, dict):
            li.raw = {}

        # Tag in-place on the original ROD recording
        if probate_kw:
            li.raw["relationship_signal"] = {
                "kind": "probate",
                "keyword": probate_kw,
                "tagged_at": datetime.utcnow().isoformat() + "Z",
            }
            counts["probate_tagged"] += 1
        elif divorce_kw:
            li.raw["relationship_signal"] = {
                "kind": "divorce",
                "keyword": divorce_kw,
                "tagged_at": datetime.utcnow().isoformat() + "Z",
            }
            counts["divorce_tagged"] += 1
        elif partition_kw:
            li.raw["relationship_signal"] = {
                "kind": "partition",
                "keyword": partition_kw,
                "tagged_at": datetime.utcnow().isoformat() + "Z",
            }
            counts["partition_tagged"] += 1
            # Partition (Commissioner's Deed) is the deed TO the purchaser —
            # the sale already happened, so tag the context but never promote
            # it to a new lead.
            continue

        # H5: when the source is ALREADY in the active pool, the in-place
        # tag (above) is sufficient — the dashboard reads
        # raw.relationship_signal to surface the lead. Emitting a separate
        # PROBATE_NOTICE/DIVORCE_NOTICE listing at the same address would
        # be a duplicate (same parcel, same street, same county, just
        # different listing_type). Only emit for sold-pool sources, where
        # the signal otherwise wouldn't surface in the active pool.
        if id(li) in active_ids:
            counts["emit_skipped_already_in_active"] += 1
            continue

        # Emit a new active-pool listing pointing at the same property
        # but tagged as the lead-type. Dedup on address+county.
        addr_key = (
            (li.street_address or "").upper().strip()
            + "|" + (li.county or "")
            + "|" + ("probate" if probate_kw else "divorce")
        )
        if addr_key.strip("|") in seen_keys:
            continue
        seen_keys.add(addr_key.strip("|"))

        if not li.street_address:
            # Without an address, we can't promote to an actionable lead
            continue

        lead_type = (
            ListingType.PROBATE_NOTICE if probate_kw else ListingType.DIVORCE_NOTICE
        )
        new_li = Listing(
            source=f"derived.{('probate' if probate_kw else 'divorce')}_deed",
            source_url=li.source_url,
            listing_type=lead_type,
            property_kind=li.property_kind or PropertyKind.UNKNOWN,
            street_address=li.street_address,
            city=li.city,
            state=li.state,
            zip_code=li.zip_code,
            county=li.county,
            parcel_id=li.parcel_id,
            description=(
                f"Derived {('probate' if probate_kw else 'divorce')} signal "
                f"from ROD recording ({probate_kw or divorce_kw})"
            ),
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={
                "derived_from": li.source,
                "relationship_signal": li.raw["relationship_signal"],
            },
        )
        new_listings.append(new_li)
        if probate_kw:
            counts["probate_emitted"] += 1
        else:
            counts["divorce_emitted"] += 1

    log.info("relationship_deeds.done", **counts)
    return new_listings
