"""Pull RECAP document bodies for high-signal CourtListener motions.

CourtListener's RECAP archive (free public PACER mirror) contains the
actual motion PDFs as plain-text. For lift-stay and §363 sale motions
the body text typically includes:

  * Property address (the lender's complaint specifies which property
    they want stay-relief on)
  * Lender's outstanding balance (mortgage balance proxy)
  * Lien priority / title chain references

This enrichment runs ONLY on listings sourced by the
courtlistener_adversary scraper. For each, it looks up the
document's plain_text via the RECAP API and writes:

    raw["recap"] = {
        "plain_text": "...",        # capped to 50KB to bound size
        "page_count": int,
        "document_url": "..."
    }

The judgment_amount enrichment (already in the pipeline) then text-
mines the body for the lender's claim amount automatically.

Free, uses the existing COURTLISTENER_TOKEN, rate-limited politely
(2 req/sec — well under the 5000/hr free-tier ceiling).
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx
import structlog

from .models import Listing
from .scrapers.national.courtlistener_bankruptcy import API_BASE, _load_token

log = structlog.get_logger()


# Cap the body text we keep per document so 100s of motions don't blow
# up listings.json. 50KB is plenty for the address + amounts + lien
# section any judgment_amount mining needs.
_MAX_BODY_CHARS = 50_000


async def _fetch_recap_doc_for_entry(
    c: httpx.AsyncClient,
    token: str,
    docket_id: int,
    entry_id: int,
) -> Optional[dict]:
    """For a docket-entry, find its associated RECAP document and pull
    the plain_text. RECAP nests documents under the entry's
    docket_entries/<id>/recap_documents/ endpoint.
    """
    try:
        r = await c.get(
            f"{API_BASE}/recap-documents/?docket_entry={entry_id}",
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=20.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    results = data.get("results") or []
    if not results:
        return None
    # Take the first available document; usually one entry has one doc.
    doc = results[0]
    plain = (doc.get("plain_text") or "")[:_MAX_BODY_CHARS]
    if not plain:
        return None
    return {
        "plain_text": plain,
        "page_count": doc.get("page_count"),
        "document_url": doc.get("filepath_local") or doc.get("absolute_url"),
        "doc_id": doc.get("id"),
    }


async def enrich_recap_documents(listings: list[Listing]) -> dict:
    """Fetch RECAP document bodies for adversary-source listings."""
    targets = [
        li for li in listings
        if li.source == "national.courtlistener_adversary"
        and isinstance(li.raw, dict)
        and isinstance(li.raw.get("courtlistener_adversary"), dict)
        and li.raw["courtlistener_adversary"].get("entry_id")
        and li.raw["courtlistener_adversary"].get("docket_id")
    ]
    if not targets:
        return {"queried": 0, "annotated": 0}

    token = _load_token()
    if not token:
        log.info("recap_doc.no_token")
        return {"queried": 0, "annotated": 0, "skipped_no_token": len(targets)}

    log.info("recap_doc.start", target_count=len(targets))
    stats = {"queried": 0, "annotated": 0, "no_doc": 0}

    sem = asyncio.Semaphore(2)  # be polite — RECAP serves shared infra

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        async with sem:
            adv = li.raw.get("courtlistener_adversary") or {}
            doc = await _fetch_recap_doc_for_entry(
                c, token,
                docket_id=adv["docket_id"],
                entry_id=adv["entry_id"],
            )
            stats["queried"] += 1
            if not doc:
                stats["no_doc"] += 1
                return
            li.raw["recap"] = doc
            stats["annotated"] += 1
            await asyncio.sleep(0.5)

    async with httpx.AsyncClient() as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("recap_doc.done", **stats)
    return stats
