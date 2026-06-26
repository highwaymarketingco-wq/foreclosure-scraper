"""Pull RECAP document bodies for high-signal CourtListener motions.

CourtListener's RECAP archive (free public PACER mirror) contains the
actual motion PDFs as plain-text. For lift-stay and §363 sale motions
the body text typically includes:

  * Property address (the lender's complaint specifies which property
    they want stay-relief on)
  * Lender's outstanding balance (mortgage balance proxy)
  * Lien priority / title chain references

This enrichment runs ONLY on listings sourced by the
courtlistener_adversary scraper. The rewritten adversary scraper
(2026-06-25) stores, per docket, raw["courtlistener_adversary"] =
{... "docket_id": int, "recap_documents": [{"document_number": int,
"absolute_url": str, "short_description": str, ...}], ...} but does
NOT carry an entry_id. So we resolve the document body from
docket_id + each ref's document_number via the RECAP filter endpoint:

    GET /recap-documents/?docket_entry__docket=<docket_id>
                          &document_number=<document_number>

and write the first one that has plain_text:

    raw["recap"] = {
        "plain_text": "...",        # capped to 50KB to bound size
        "page_count": int,
        "document_url": "...",
        "document_number": int,
        "doc_id": int,
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


def _doc_payload(doc: dict) -> Optional[dict]:
    """Build the raw['recap'] payload from a RECAP document record, or None
    if it has no usable plain_text."""
    plain = (doc.get("plain_text") or "")[:_MAX_BODY_CHARS]
    if not plain:
        return None
    return {
        "plain_text": plain,
        "page_count": doc.get("page_count"),
        "document_url": doc.get("filepath_local") or doc.get("absolute_url"),
        "document_number": doc.get("document_number"),
        "doc_id": doc.get("id"),
    }


async def _fetch_recap_doc(
    c: httpx.AsyncClient,
    token: str,
    docket_id: int,
    document_number,
) -> Optional[dict]:
    """Resolve one RECAP document's plain_text from (docket_id, document_number).

    The adversary scraper stores recap_documents[] refs with a document_number
    but no recap-document id, so we query the filter endpoint scoped to the
    docket. RECAP exposes documents at:
        /recap-documents/?docket_entry__docket=<docket_id>
                         &document_number=<document_number>
    Returns the first result carrying plain_text, else None. Best-effort,
    never raises.
    """
    try:
        r = await c.get(
            f"{API_BASE}/recap-documents/",
            params={
                "docket_entry__docket": docket_id,
                "document_number": document_number,
            },
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=20.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    for doc in (data.get("results") or []):
        if not isinstance(doc, dict):
            continue
        payload = _doc_payload(doc)
        if payload:
            return payload
    return None


async def _fetch_recap_doc_for_listing(
    c: httpx.AsyncClient,
    token: str,
    docket_id: int,
    recap_documents: list,
) -> Optional[dict]:
    """Walk a docket's stored recap_documents[] refs (highest document_number
    first — the latest filing on the docket) and return the first one whose
    body is available as plain_text on RECAP."""
    # Sort refs by document_number desc so the most recent motion wins; refs
    # without a numeric document_number sort last.
    def _num(rd):
        try:
            return int(rd.get("document_number"))
        except (TypeError, ValueError):
            return -1

    refs = sorted(
        (rd for rd in (recap_documents or []) if isinstance(rd, dict)),
        key=_num,
        reverse=True,
    )
    for rd in refs:
        dn = rd.get("document_number")
        if dn in (None, ""):
            continue
        payload = await _fetch_recap_doc(c, token, docket_id, dn)
        if payload:
            return payload
    return None


async def enrich_recap_documents(listings: list[Listing]) -> dict:
    """Fetch RECAP document bodies for adversary-source listings."""
    targets = [
        li for li in listings
        if li.source == "national.courtlistener_adversary"
        and isinstance(li.raw, dict)
        and isinstance(li.raw.get("courtlistener_adversary"), dict)
        and li.raw["courtlistener_adversary"].get("docket_id")
        and li.raw["courtlistener_adversary"].get("recap_documents")
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
            doc = await _fetch_recap_doc_for_listing(
                c, token,
                docket_id=adv["docket_id"],
                recap_documents=adv.get("recap_documents") or [],
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
