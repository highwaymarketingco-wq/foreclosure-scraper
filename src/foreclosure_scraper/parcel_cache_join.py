"""Join the local parcel cache (data/parcel_cache) onto listings: owner mailing, owner name,
county values, sqft, acreage, last sale, year built, bedrooms, bathrooms. Fill-only.

ONE copy of the join, used by two callers:
  * enrichment_gis_attrs.enrich_gis_attrs runs `join_listings` over EVERY listing first,
    before its own per-lead loop, so a normal pipeline run applies the cache to the whole
    board; and
  * scripts/join_parcel_cache_to_board.py (and apply_board_fixes --steps join) runs it on
    a loaded board, adding its own situs-address rule on top.

WHY THE PIPELINE MISSED 36,469 ROWS (measured 2026-10-07, docs/new_sources_2026-10-07_contact_and_facts.md)
    Board rows with a parcel id and no owner mailing whose county cache already held the
    mailing. enrich_gis_attrs did read the cache, but only inside its per-lead coroutine
    and only AFTER two idempotency gates written for the expensive LIVE query:
      1. a row a prior run had marked raw["gis"]["queried"] returned before the lookup, so
         a row first queried before the caches gained the mailing column (2026-09-10) was
         never joined again;
      2. a row that already had value + owner + sqft returned before the lookup;
    and the per-lead loop runs in batches of 2,500 behind a live-query semaphore inside a
    RESOLVER_PHASE_MAX_SECONDS (2,400 s) cap, so on a 350k-row board the later batches
    never ran at all. The lookup itself is local and costs microseconds; gating it behind
    the network budget was the bug. The per-lead block also wrote only
    raw["gis"]["mailing"], never the canonical raw["owner_mailing"] block the absentee
    flag, the ranker and the slim payload read.

SAFETY (same rules the offline join has carried since 2026-09-21)
  * Fill-only: never overwrites a value a row already has.
  * TAX_SALE_OVERAGE rows are skipped (the cache describes the parcel's CURRENT owner,
    not the claimant).
  * A parcel id shared by 4+ distinct addresses (dedupe.suspicious_parcel_keys) is not
    looked up.
  * A dual-state county name with no state is not looked up (parcel_cache.lookup also
    refuses).
  * The OWNER's mailing is withheld when the row's parcel came from its street address
    and the resolver recorded owner_agrees False.
  * Value fields from a cache older than CACHE_VALUE_MAX_AGE_DAYS are already dropped by
    parcel_cache.lookup.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Iterable, Optional

from . import parcel_cache as pc
from .models import Listing, ListingType

_MAIL_STATE_RE = re.compile(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def mail_state(mailing: str) -> Optional[str]:
    """Two-letter state from the tail of a mailing string ('... SUMTER SC 29150' -> 'SC')."""
    m = _MAIL_STATE_RE.search((mailing or "").strip().upper())
    return m.group(1) if m else None


def _int(v) -> Optional[int]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == f else None


def apply_hit(li: Listing, hit: dict, c: Counter) -> None:
    """Fill one listing from one cache row. Fill-only; counts each fill in `c`."""
    from .enrichment_owner_mailing import _is_absentee

    if not isinstance(li.raw, dict):
        li.raw = {}
    pfa = li.raw.get("parcel_from_address")
    owner_differs = isinstance(pfa, dict) and pfa.get("owner_agrees") is False
    mailing = hit.get("owner_mailing")
    if owner_differs and mailing:
        c["mailing withheld: parcel owner differs from the lead's party"] += 1
    if mailing and not owner_differs:
        g = li.raw.setdefault("gis", {})
        if not g.get("mailing"):
            g["mailing"] = mailing
            c["filled owner mailing"] += 1
        # The canonical block: the absentee derivation, fullmer_rank and the slim payload
        # read raw["owner_mailing"], not raw["gis"]["mailing"]. A string here already is a
        # mailing address (shape drift seen before); leave it rather than clobber it.
        om_existing = li.raw.get("owner_mailing")
        if om_existing is not None and not isinstance(om_existing, dict):
            c["owner_mailing was a string — left as is"] += 1
            om = None
        else:
            om = li.raw.setdefault("owner_mailing", {})
        if om is not None and not om.get("mailing"):
            om["mailing"] = mailing
            om.setdefault("source", "parcel_cache")
            situs = hit.get("address") or li.street_address
            om["absentee"] = _is_absentee(situs, mailing)
            st = mail_state(mailing)
            if st:
                om["mail_state"] = st
                om["out_of_state"] = bool(li.state and st != li.state)
            if om["absentee"]:
                c["flagged absentee"] += 1
    if hit.get("owner") and not (li.owner_name or "").strip():
        li.owner_name = hit["owner"]
        c["filled owner name"] += 1
    if hit.get("market_value") and not li.market_value:
        li.market_value = hit["market_value"]
        c["filled market value"] += 1
    if hit.get("tax_value") and not li.tax_value:
        li.tax_value = hit["tax_value"]
        c["filled tax value"] += 1
    if hit.get("living_sqft") and not li.living_sqft:
        li.living_sqft = hit["living_sqft"]
        c["filled sqft"] += 1
    if hit.get("acreage") and not li.acreage:
        li.acreage = hit["acreage"]
        c["filled acreage"] += 1
    yb = _int(hit.get("year_built"))
    if yb and 1700 < yb <= 2100 and not li.year_built:
        li.year_built = yb
        c["filled year built"] += 1
    beds = pc._num(hit.get("bedrooms"))
    if beds and 0 < beds < 100 and not li.bedrooms:
        li.bedrooms = beds
        c["filled bedrooms"] += 1
    baths = pc._num(hit.get("bathrooms"))
    if baths and 0 < baths < 100 and not li.bathrooms:
        li.bathrooms = baths
        c["filled bathrooms"] += 1
    if hit.get("stories") and not (li.raw.get("gis") or {}).get("stories"):
        li.raw.setdefault("gis", {})["stories"] = hit["stories"]
        c["filled stories"] += 1
    amt = pc.sale_amount(hit.get("sale_price"))
    if amt or hit.get("sale_date"):
        ls = li.raw.setdefault("gis", {}).setdefault("last_sale", {})
        if amt and not ls.get("amount"):
            ls["amount"] = amt
            c["filled last sale"] += 1
        if hit.get("sale_date") and not ls.get("date"):
            ls["date"] = hit["sale_date"]
            c["filled last sale date"] += 1


def _dual_lower() -> set[str]:
    return {n.lower() for n in pc.DUAL_STATE_COUNTIES}


def join_listings(listings: Iterable[Listing], *,
                  situs_fill: Optional[Callable[[Listing, dict, Counter], None]] = None,
                  suspicious: Optional[frozenset] = None) -> Counter:
    """Look every listing with a parcel id up in its county cache and fill from the hit.

    `situs_fill(li, hit, counter)` is an optional extra step (the offline script uses it to
    write a numbered situs address). `suspicious` is the set of over-shared parcel dedupe
    keys; computed from `listings` when not given. Never changes the number of rows."""
    rows = listings if isinstance(listings, list) else list(listings)
    if suspicious is None:
        from .dedupe import suspicious_parcel_keys
        suspicious = suspicious_parcel_keys(rows)
    dual = _dual_lower()
    c: Counter = Counter()
    for li in rows:
        if li.listing_type == ListingType.TAX_SALE_OVERAGE:
            c["skipped: tax_sale_overage, owner != cache owner"] += 1
            continue
        if not li.parcel_id:
            c["no parcel_id"] += 1
            continue
        county = (li.county or "").replace(" County", "").strip()
        if not county:
            c["no county"] += 1
            continue
        if county.lower() in dual and not li.state:
            c["skipped: dual-state name, li.state is empty"] += 1
            continue
        if suspicious and li.dedupe_key() in suspicious:
            c["skipped: parcel id shared by many distinct addresses"] += 1
            continue
        try:
            hit = pc.lookup(county, li.parcel_id, li.state)
        except Exception:  # noqa: BLE001 - one bad cache must not stop the join
            c["lookup error"] += 1
            continue
        if not hit:
            c["cache miss"] += 1
            continue
        c["cache HIT"] += 1
        apply_hit(li, hit, c)
        if situs_fill is not None:
            situs_fill(li, hit, c)
    return c
