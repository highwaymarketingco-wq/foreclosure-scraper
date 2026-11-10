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
from datetime import date, datetime
from typing import Any, Iterable, Optional

import structlog

from .models import Listing
from .rod.inst_class import LOSS_CLASSES, classify_instrument, is_deed_class

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
    # Tax-sale / foreclosure-sale conveyances -- missing until 2026-09-17.
    # dirty_deeds_synthesis Tier A #34: a grantor who lost a parcel this way
    # and still holds OTHER board parcels is a proven non-payer, but that
    # signal only exists if the loss itself shows up as a distress transfer
    # first. NC tax sales run through the Clerk of Superior Court/sheriff;
    # NC power-of-sale foreclosures convey via a substitute trustee; SC's
    # judicial foreclosure sales run through the county Master in Equity.
    "TAX DEED", "SHERIFF'S DEED", "SHERIFF DEED",
    "TRUSTEE'S DEED", "TRUSTEE DEED", "SUBSTITUTE TRUSTEE",
    "MASTER IN EQUITY", "MASTER'S DEED", "CLERK'S DEED", "CLERK DEED",
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
    # Vendor short codes (TR/D, COM/D, SHF/D) and spellings the list above misses
    # ("TRUSTEES DEED" has no apostrophe, so "TRUSTEE'S DEED" never matched it).
    if classify_instrument(dt) in LOSS_CLASSES:
        return True
    if price is not None and price in _LOVE_AND_AFFECTION:
        return True
    return False


def _collect_records(li: Listing, fallback_point: bool = False) -> list[dict]:
    """Gather all sale/deed records from every source on this listing.

    `fallback_point`: this row has no parcel id and no house-numbered address of its own, and its
    point is a flagged geocoder fallback (block_binding.imprecise_point() and not own_location()) --
    the same test block_binding.py's own POINT_BLOCKS rule uses. assessor_card.sales, county_sales
    and gis.last_sale are each resolved by a parcel/point lookup (sc_assessor_cama / parcel_cache /
    enrichment_county_sales / enrichment_gis_attrs): on such a row they are some OTHER parcel's
    record, the one that happens to sit at the shared fallback point, carried into `raw` before
    that parcel was withdrawn (enrichment_prior_correction.withdraw_fallback_parcel) or by a source
    this module alone cannot re-check. Folding them into THIS row's own deed chain (audit
    2026-10-18, block-binding-family-deed-sale) presents a stranger's sale as this row's acquisition
    history. rod_docs and relationship_signal are matched by owner NAME or case, not by point, and
    stay regardless."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    records: list[dict] = []

    # 1. assessor_card.sales — richest source, has grantor + price + book/page
    ac = None if fallback_point else raw.get("assessor_card")
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
    cs = None if fallback_point else raw.get("county_sales")
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
    gis = None if fallback_point else raw.get("gis")
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
            draw = d.get("raw") if isinstance(d.get("raw"), dict) else {}
            # The vendor code in raw["ki"] (TR/D, COM/D, SHF/D) says what the
            # normalized doc_type may have flattened to a bare "DEED".
            inst_class = classify_instrument(dt, draw.get("ki"))
            # Only include deed-type documents (not mortgages/liens)
            if is_deed_class(inst_class) or any(k in dt.upper() for k in (
                    "DEED", "QUITCLAIM", "WARRANTY", "DISTRIBUTION", "COMMISSIONER",
                    "SURVIVORSHIP", "EXECUTOR", "ADMINISTRATOR")):
                rec = {
                    "date": _parse_date(d.get("recorded_date")),
                    "price": _money(d.get("amount")),
                    "book": d.get("book"),
                    "page": d.get("page"),
                    "doc_type": dt,
                    "county": d.get("county"),
                    "source": "rod_docs",
                }
                # Parties only for a real conveyance. A deed of trust also passes
                # the keyword test above, and its grantor is the CURRENT owner:
                # carrying it would make him his own prior_owner.
                if is_deed_class(inst_class):
                    rec.update({
                        "inst_class": inst_class,
                        "grantor": d.get("grantor"),
                        "grantee": d.get("grantee"),
                        "grantors": draw.get("grantors"),
                    })
                records.append(rec)

    # 5. relationship_signal — probate/divorce deed patterns. Matched by case/person, not by
    # point, so it stays on a fallback-point row -- but only when it actually says something
    # (a signal with every field empty was only ever noise inflating chain_length to 1 with
    # nothing in it; audit 2026-10-18, block-binding-family-deed-sale).
    rs = raw.get("relationship_signal")
    if isinstance(rs, dict) and any(rs.get(f) for f in ("date", "signal", "grantor", "grantee")):
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
        # A rod_docs record carries the class read from its vendor code, which can
        # be stronger than the doc_type an older normalize_doc_type flattened to DEED.
        inst_class = r.get("inst_class") or classify_instrument(doc_type)
        if _is_distress_sale(price, doc_type) or inst_class in LOSS_CLASSES:
            entry = {
                "date": r.get("date"),
                "price": price,
                "doc_type": doc_type or None,
                "source": r.get("source"),
            }
            # Keep who conveyed and who received, plus the instrument's identity.
            # repeat_tax_loss needs the loser's own name; without it, it fell back
            # to summary.prior_owner, which is the grantor of the newest transfer
            # that HAS one and is rarely the person who lost that parcel.
            for k, v in (("grantor", r.get("grantor")), ("grantee", r.get("grantee")),
                         ("grantors", r.get("grantors")), ("book", r.get("book")),
                         ("page", r.get("page")),
                         ("inst_class", inst_class if inst_class != "OTHER" else None)):
                if v:
                    entry[k] = v
            summary["distress_transfers"].append(entry)

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


def enrich_deed_chain(listings: Iterable[Listing], *, shared_pts: Optional[set] = None) -> dict:
    """Build unified deed chain timeline from all available sale records.

    100% OFFLINE — no network calls. Reorganizes data already gathered
    by assessor_card, county_sales, gis, rod_docs, and relationship_signal
    enrichers into a chronological chain with summary flags.

    `shared_pts`: pass a precomputed block_binding.shared_points() result (just (lat,lng) tuples
    -- cheap, no raw data) when calling this over the board in batches, so each batch's fallback-
    point detection still sees the WHOLE board's clustering rather than only its own rows. Added
    2026-10-22: a full-board call with every row's raw dict held at once was live-measured at
    19+ GB RSS and still climbing (killed before OOM) -- the batched caller computes this once,
    cheaply, in its own first pass over just (lat,lng), then passes it to every batch."""
    listings = list(listings)
    from .block_binding import imprecise_point, own_location, shared_points
    if shared_pts is None:
        try:
            shared_pts = shared_points(listings)
        except Exception:  # noqa: BLE001 - no shared points is the lenient side
            shared_pts = set()
    stamped = 0
    total_records = 0
    has_chain = 0
    has_distress = 0
    has_breaks = 0
    skipped_fallback_point = 0
    cleared_fallback_point = 0

    for li in listings:
        fallback = imprecise_point(li, shared_pts) and not own_location(li)
        if fallback:
            skipped_fallback_point += 1
        records = _collect_records(li, fallback)
        if not records:
            # a stale deed_chain already on this row (built before this row's point was flagged
            # a fallback, or before this guard existed) is nothing but the shared point's OTHER
            # parcel's history -- rod_docs/relationship_signal would have kept `records` non-empty
            # if there were a real, name-matched basis for a chain.
            if fallback and isinstance(li.raw, dict) and li.raw.pop("deed_chain", None) is not None:
                cleared_fallback_point += 1
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
             with_breaks=has_breaks,
             skipped_fallback_point=skipped_fallback_point,
             cleared_fallback_point=cleared_fallback_point)

    return {
        "stamped": stamped,
        "total_records": total_records,
        "with_chain": has_chain,
        "with_distress_transfers": has_distress,
        "with_chain_breaks": has_breaks,
        "skipped_fallback_point": skipped_fallback_point,
        "cleared_fallback_point": cleared_fallback_point,
    }


# --------------------------------------------------------------------------- fraud against an heir
#
# DPA master_sources_and_signals.md item B.20 names this narrowly: forged deeds / fake POA /
# impersonation at closing, verified via notary records, litigation, and identity cross-checks.
# This is DETECTION ONLY, cross-referencing data two enrichers already gathered -- deed_chain
# (this module) and heir_candidates (enrichment_heir_candidates.py) -- plus death_fact() from
# call_ready.py. It is deliberately NOT wired into distress_score.py or any ListingType; scoring
# integration is a separate decision.
#
# Must run AFTER both enrich_deed_chain() AND enrich_heir_candidates() have stamped their raw
# fields on every row. It is NOT called from this module's own per-row loop above: main.py runs
# enrich_heir_candidates() well after enrich_deed_chain(), so raw['heir_candidates'] does not exist
# yet during that loop. main.py instead calls enrich_fraud_signals() as its own separate pass,
# right after the heir_candidates block, where both are already present together on the row.

# A transfer within this many days of the recorded date of death counts as near-death timing.
_NEAR_DEATH_DAYS = 90
# Second, broader undervalue threshold vs. the four fixed nominal prices in _LOVE_AND_AFFECTION
# above: a deed price under half the county's own 100%-basis appraisal. Kept as a separate signal
# -- a transfer _LOVE_AND_AFFECTION already catches is reported under that stricter check, not
# duplicated here.
_UNDERVALUE_RATIO = 0.5


def _transfer_date_obj(date_str: Any) -> Optional[date]:
    """A day-precision date for a transfer's `date` field, or None for a partial date (bare year
    or year-month, which _parse_date can also return) that cannot support a 90-day comparison."""
    s = str(date_str or "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _name_tokens(name: Any) -> frozenset:
    words = re.sub(r"[^\w\s]", " ", str(name or "")).upper().split()
    return frozenset(w for w in words if len(w) > 1)  # drop bare initials


def _names_match(heir_name: Any, grantor: Any) -> bool:
    """Same person on both sides, allowing for a given/surname order flip or a dropped middle
    name/initial -- a deed grantor string and a heir-candidate name are read from different
    sources and rarely format identically. Requires >=2 real words on each side so a one-word
    grantor (a bare surname, an entity fragment) never counts as a match."""
    a, b = _name_tokens(heir_name), _name_tokens(grantor)
    if len(a) < 2 or len(b) < 2:
        return False
    return a == b or a <= b or b <= a


def _fraud_signals_for(li: Listing) -> Optional[dict]:
    """fraud-against-an-heir detection for one row. Pure read over raw['deed_chain'],
    raw['heir_candidates'] and death_fact(li) -- nothing here is fetched or computed elsewhere.
    Returns None when there is no deed chain to evaluate (nothing to cross-reference), matching
    enrich_deed_chain's own rule of only stamping rows that have real chain data."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    chain = raw.get("deed_chain")
    transfers = chain.get("transfers") if isinstance(chain, dict) else None
    if not isinstance(transfers, list) or not transfers:
        return None

    from .call_ready import death_fact
    from .enrichment_heir_candidates import PUBLISHABLE_HEIR_RELATIONS
    from .fullmer_rank import cad_value

    details: dict[str, Any] = {}

    # 1. Near-death timing: a transfer within _NEAR_DEATH_DAYS of the recorded date of death.
    # Both sides need day precision -- a transfer or death date that only resolved to a bare
    # year or year-month cannot support a 90-day comparison, so it is skipped, not guessed at.
    near_death = False
    dod_str = (death_fact(li) or {}).get("date_of_death")
    dod = _transfer_date_obj(dod_str)
    if dod is not None:
        for r in transfers:
            td = _transfer_date_obj(r.get("date"))
            if td is None:
                continue
            days = abs((td - dod).days)
            if days <= _NEAR_DEATH_DAYS:
                near_death = True
                details["near_death_transfer"] = {
                    "transfer_date": r.get("date"), "death_date": dod_str, "days": days,
                }
                break

    # 2. Co-heir cutout: >=2 publishable-tier heir candidates AND exactly 1 of them matches a
    # transfer's grantor. The >=2 heir-count gate alone is not corroboration (heir_candidates is
    # admittedly incomplete per its own docstring) -- the grantor match is required too, and
    # "exactly 1" is what separates a targeted cutout from an ordinary joint conveyance by two
    # or more co-heirs together (which would match more than one of them on the same transfer).
    co_heir_cutout = False
    hc = raw.get("heir_candidates")
    heirs = [c for c in hc if isinstance(c, dict)
             and str(c.get("relation") or "").strip().lower() in PUBLISHABLE_HEIR_RELATIONS] \
        if isinstance(hc, list) else []
    if len(heirs) >= 2:
        matches = []
        for h in heirs:
            for r in transfers:
                if r.get("grantor") and _names_match(h.get("name"), r["grantor"]):
                    matches.append((h, r))
                    break
        if len(matches) == 1:
            co_heir_cutout = True
            h, r = matches[0]
            details["co_heir_cutout"] = {
                "heir_name": h.get("name"), "heir_count": len(heirs),
                "grantor": r.get("grantor"), "transfer_date": r.get("date"),
            }

    # 3. Undervalued transfer: price under _UNDERVALUE_RATIO of the county's own appraisal
    # (fullmer_rank.cad_value -- the "County 100%-basis appraisal", the same number fullmer_rank
    # underwrites off), and not already the stricter, separate _LOVE_AND_AFFECTION nominal-price
    # check above.
    undervalued = False
    assessed, assessed_src = cad_value(li)
    if assessed:
        for r in transfers:
            price = r.get("price")
            if price is None or price in _LOVE_AND_AFFECTION:
                continue
            if price < _UNDERVALUE_RATIO * assessed:
                undervalued = True
                details["undervalued_transfer"] = {
                    "transfer_date": r.get("date"), "price": price,
                    "assessed_value": assessed, "assessed_value_source": assessed_src,
                    "ratio": round(price / assessed, 3),
                }
                break

    return {
        "near_death_transfer": near_death,
        "co_heir_cutout": co_heir_cutout,
        "undervalued_transfer": undervalued,
        "details": details,
    }


def enrich_fraud_signals(listings: Iterable[Listing]) -> dict:
    """Cross-reference deed_chain against heir_candidates and the recorded date of death to flag
    a conveyance that looks like fraud against an heir (DPA master_sources_and_signals.md item
    B.20). Stamps raw['fraud_signals'] = {near_death_transfer, co_heir_cutout, undervalued_transfer,
    details} on every row that has a deed chain to evaluate. Detection only -- see the module-level
    note above: not wired into distress_score.py or any ListingType.

    Call this AFTER both enrich_deed_chain() and enrich_heir_candidates() have already run over
    the same rows (main.py wires it in as its own pass right after the heir_candidates block)."""
    listings = list(listings)
    stamped = 0
    near_death = 0
    cutout = 0
    undervalued = 0

    for li in listings:
        signals = _fraud_signals_for(li)
        if signals is None:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["fraud_signals"] = signals
        stamped += 1
        if signals["near_death_transfer"]:
            near_death += 1
        if signals["co_heir_cutout"]:
            cutout += 1
        if signals["undervalued_transfer"]:
            undervalued += 1

    log.info("fraud_signals.done", listings=len(listings), stamped=stamped,
             near_death_transfer=near_death, co_heir_cutout=cutout, undervalued_transfer=undervalued)

    return {
        "stamped": stamped,
        "near_death_transfer": near_death,
        "co_heir_cutout": cutout,
        "undervalued_transfer": undervalued,
    }
