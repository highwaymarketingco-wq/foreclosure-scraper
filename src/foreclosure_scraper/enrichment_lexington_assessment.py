"""Lexington SC value + assessment-ratio enricher.

WHY THIS EXISTS
    Lexington landed 2,214 leads on 2026-09-13 and every one ranked D, because the
    buy-box arithmetic needs a VALUE and the qPayBill roll does not carry one.
    Lexington has no free ArcGIS parcel layer (its own maps host is a bare Apache
    default page, and SCDOT's statewide parcel service is token-walled), so the
    value has to come from the county's own property-search API.

WHAT IS OPEN AND WHAT IS NOT
    www.lex-co.com/PropSearchAPI is the Angular app's backend. Most of it is gated
    behind a reCAPTCHA-issued Bearer token, which is out of bounds. Two endpoints
    answer WITHOUT any token and are used here:

        /property?tms=<undashed>     owner, situs address, deed, acres
        /assessment?tms=<undashed>   taxYear, owner, fmv, assessment

    The TMS must be UNDASHED. "004121-01-024" returns [] and looks like a miss;
    "00412101024" returns the record. That silent-empty-on-wrong-format behaviour is
    exactly the shape that makes a source look dead when it is not.

THE ASSESSMENT RATIO IS A FREE ABSENTEE SIGNAL
    SC assesses an owner-occupied legal residence at 4% and everything else at 6%.
    So assessment/fmv distinguishes a homeowner from a landlord, second-home owner
    or LLC without needing a mailing address at all. Verified on live rows:
    fmv 250,000 / assessed 15,000 = 6.0% for A & K ENTERPRISES LLC.

    This is reported as `assessment_ratio` and `owner_occupied` (True at ~4%,
    False at ~6%, None when it is neither). It is NOT written to
    owner_mailing.absentee: that field means "mails from elsewhere", which is a
    different claim from "is not a legal residence", and conflating them would put
    a signal on the board that no mailing address supports.
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

API = "https://www.lex-co.com/PropSearchAPI"
CONCURRENCY = 4
TIMEOUT = 25.0


def _tms(parcel_id: str) -> Optional[str]:
    """Undashed TMS, or None when the id is not a TMS at all.

    Some Lexington board rows carry a short ACCOUNT number ("26811") rather than a
    TMS. Those return [] from the API, so they are filtered out here instead of
    being counted as misses.
    """
    t = "".join(ch for ch in (parcel_id or "") if ch.isdigit())
    return t if len(t) >= 10 else None


def classify_ratio(fmv, assessed) -> tuple[Optional[float], Optional[bool]]:
    """(ratio_pct, owner_occupied). None/None when it cannot be decided.

    4% = owner-occupied legal residence, 6% = everything else. A tolerance is used
    because agricultural and manufacturing classes sit at other ratios and must NOT
    be forced into one of the two buckets.
    """
    try:
        fmv = float(fmv or 0)
        assessed = float(assessed or 0)
    except (TypeError, ValueError):
        return None, None
    if fmv <= 0 or assessed <= 0:
        return None, None
    ratio = round(100.0 * assessed / fmv, 2)
    if 3.5 <= ratio <= 4.5:
        return ratio, True
    if 5.5 <= ratio <= 6.5:
        return ratio, False
    return ratio, None


async def _one(client: httpx.AsyncClient, li: Listing, stats: dict) -> None:
    tms = _tms(li.parcel_id or "")
    if not tms:
        stats["not_a_tms"] += 1
        return
    try:
        r = await client.get(f"{API}/assessment", params={"tms": tms})
        if r.status_code != 200:
            stats["http_error"] += 1
            return
        recs = r.json()
    except Exception as exc:  # noqa: BLE001
        stats["error"] += 1
        log.warning("lexington_assessment.error", tms=tms,
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return
    if not isinstance(recs, list) or not recs:
        stats["no_records"] += 1
        return

    def _yr(x):
        try:
            return int(x.get("taxYear") or 0)
        except (TypeError, ValueError):
            return 0

    latest = max(recs, key=_yr)
    fmv = latest.get("fmv") or latest.get("currentFMV")
    ratio, occupied = classify_ratio(fmv, latest.get("assessment"))

    if not isinstance(li.raw, dict):
        li.raw = {}
    block = {"tax_year": latest.get("taxYear"), "fmv": fmv,
             "assessed": latest.get("assessment"), "assessment_ratio": ratio,
             "owner_occupied": occupied, "source": "lex-co PropSearchAPI/assessment"}
    li.raw["lexington_assessment"] = {k: v for k, v in block.items() if v is not None}

    if fmv and not li.tax_value:
        try:
            li.tax_value = float(fmv)
            stats["filled_value"] += 1
        except (TypeError, ValueError):
            pass
    if occupied is False:
        stats["not_owner_occupied"] += 1
    elif occupied is True:
        stats["owner_occupied"] += 1
    stats["enriched"] += 1


async def enrich_lexington(listings: list[Listing], max_rows: int | None = None) -> dict:
    targets = [li for li in listings
               if (li.county or "") == "Lexington" and (li.state or "") == "SC"
               and li.parcel_id]
    if max_rows:
        targets = targets[:max_rows]
    stats = {k: 0 for k in ("enriched", "filled_value", "owner_occupied",
                            "not_owner_occupied", "no_records", "not_a_tms",
                            "http_error", "error")}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers={"Accept": "application/json",
                                          "User-Agent": "Mozilla/5.0"}) as client:
        async def guarded(li):
            async with sem:
                await _one(client, li, stats)
        for i in range(0, len(targets), 200):
            await asyncio.gather(*(guarded(li) for li in targets[i:i + 200]))
            log.info("lexington_assessment.progress", done=min(i + 200, len(targets)),
                     total=len(targets), **stats)
    log.info("lexington_assessment.done", targets=len(targets), **stats)
    return stats
