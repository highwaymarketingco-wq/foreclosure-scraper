"""Pipeline glue: for each listing, query the right county ROD vendor by owner name,
compute lien priority, and attach to listing.raw['rod'] and ['lien_priority'].
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from ..models import Listing
from . import aumentum, cchs, cott, kofile
from .models import LienPosition, RodDoc
from .priority import compute_priority

log = structlog.get_logger()


VENDORS = {
    # (state, county) -> vendor module
    **{k: cchs for k in cchs.CCHS_COUNTIES},
    **{k: aumentum for k in aumentum.AUMENTUM_COUNTIES},
    **{k: cott for k in cott.COTT_COUNTIES},
    **{k: kofile for k in kofile.KOFILE_COUNTIES},
}


def _owner_name(li: Listing) -> str | None:
    """Best-effort owner name to query the ROD."""
    gis = (li.raw or {}).get("gis") if isinstance(li.raw, dict) else None
    if isinstance(gis, dict):
        if gis.get("owner"):
            return gis["owner"]
    if li.defendant:
        # Foreclosure cases: defendant = current owner
        return li.defendant.split(",")[0].strip()
    return None


async def enrich_one(li: Listing) -> None:
    if not (li.county and li.state):
        return
    key = (li.state, li.county.replace(" County", "").strip().split(",")[0].strip())
    vendor = VENDORS.get(key)
    if not vendor:
        return  # county's ROD not yet adapted
    name = _owner_name(li)
    if not name:
        return
    try:
        docs: list[RodDoc] = await vendor.search_by_name(key[0], key[1], name, max_docs=30)
    except Exception as exc:
        log.debug("rod.search.error", county=key[1], state=key[0], error=str(exc)[:100])
        return
    if not docs:
        return

    # Compute priority. We don't always know the foreclosing doc's exact book/page,
    # so the engine infers it as the most recent mortgage when not provided.
    pos: LienPosition = compute_priority(docs, state=key[0])
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["rod_docs"] = [d.to_dict() for d in docs[:25]]
    li.raw["lien_priority"] = pos.to_dict()

    # NOD detection — flag if this owner has a Notice of Default recorded.
    # NOD is the FIRST step in NC foreclosure (filed 60-180 days before sale).
    # If we see one for the defendant, this is a confirmed pre-sale signal.
    from .models import DOC_BUCKETS, normalize_doc_type
    nod_docs = [d for d in docs
                if DOC_BUCKETS.get(normalize_doc_type(d.doc_type)) in ("notice_of_default", "notice_of_sale", "lis_pendens")]
    if nod_docs:
        nod_docs.sort(key=lambda d: d.recorded_date or __import__("datetime").datetime.min, reverse=True)
        li.raw["nod"] = {
            "found": True,
            "type": DOC_BUCKETS.get(normalize_doc_type(nod_docs[0].doc_type), "unknown"),
            "recorded_date": nod_docs[0].recorded_date.isoformat() if nod_docs[0].recorded_date else None,
            "book_page": f"{nod_docs[0].book or '?'}/{nod_docs[0].page or '?'}",
            "instrument_no": nod_docs[0].instrument_no,
            "all_count": len(nod_docs),
        }


async def enrich_all(listings: list[Listing], concurrency: int = 4) -> None:
    """Enrich every listing whose county is supported. Bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    matched = 0

    async def one(li: Listing) -> None:
        nonlocal matched
        async with sem:
            before = li.raw.get("rod_docs") if isinstance(li.raw, dict) else None
            await enrich_one(li)
            if isinstance(li.raw, dict) and li.raw.get("rod_docs") and li.raw.get("rod_docs") != before:
                matched += 1

    await asyncio.gather(*(one(li) for li in listings))
    log.info("rod.enrich.done", matched=matched, total=len(listings))
