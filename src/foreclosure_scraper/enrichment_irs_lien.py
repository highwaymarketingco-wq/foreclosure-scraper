"""IRS / federal tax lien search via CourtListener RECAP archive.

Federal tax liens are recorded when the IRS files a Notice of Federal Tax Lien (NFTL).
While the lien is recorded at the county ROD, enforcement actions (collection,
seizure, suit) appear in federal court. CourtListener's RECAP archive mirrors
PACER docket entries for free.

This enricher searches CourtListener for cases matching the property owner's
name + "tax lien" or "IRS" in the case description. It writes findings to
raw['liens'] (appending to the existing lien stack) so the equity engine
subtracts them.

Free, uses COURTLISTENER_TOKEN, rate-limited (2 req/sec).
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

API_BASE = "https://www.courtlistener.com/api/rest/v4"
CONCURRENCY = int(os.environ.get("IRS_LIEN_CONCURRENCY", "3"))
FETCH_TIMEOUT = float(os.environ.get("IRS_LIEN_TIMEOUT_S", "20"))
MAX_LOOKUPS = int(os.environ.get("IRS_LIEN_MAX_LOOKUPS", "300"))


def _load_token() -> Optional[str]:
    tok = os.environ.get("COURTLISTENER_TOKEN") or os.environ.get("COURTLISTENER_API_TOKEN")
    if not tok:
        # Try secrets file
        for p in (".secrets/courtlistener_token.txt", "~/.secrets/courtlistener_token.txt"):
            p = os.path.expanduser(p)
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        tok = f.read().strip()
                    if tok:
                        break
                except Exception:
                    pass
    return tok


_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "DDS", "ESQ"}
_BIZ = {"LLC", "INC", "CORP", "TRUST", "TR", "LP", "LLP", "COMPANY", "CO",
        "BANK", "ASSOCIATION", "ESTATE", "ENTERPRISES", "PROPERTIES", "HOLDINGS"}


_ESTATE_WORDS = {"ESTATE", "OF", "HEIRS", "HEIR", "DECEDENT", "DECEASED",
                 "TRUST", "TRUSTEE", "ET", "AL", "PROBATE", "LATE"}

def _name_query(name: str | None) -> Optional[str]:
    """Build a search query from owner name for CourtListener search.
    Requires 2+ real name tokens after stripping estate/trust language."""
    if not name:
        return None
    toks = [t for t in re.split(r"[^A-Za-z]+", name.upper()) if t]
    toks = [t for t in toks if t not in _SUFFIXES and t not in _ESTATE_WORDS]
    if len(toks) < 2:
        return None
    if toks[-1] in _BIZ:
        return None
    # Use last name + first name as the query (CourtListener handles partial matches)
    last = toks[-1]
    first = toks[0]
    return f"{first} {last}"


async def _search_cl(
    client: httpx.AsyncClient,
    token: str,
    name_query: str,
) -> list[dict]:
    """Search CourtListener for tax lien / IRS cases matching the name."""
    # Search for cases with the owner name + tax-related keywords
    url = f"{API_BASE}/search/"
    params = {
        "type": "r",          # RECAP (federal court dockets)
        "q": f'"{name_query}" IRS tax lien',
        "order_by": "score desc",
        "court": "ncmd,nces,ncwd,scmd,sced,scwd",  # NC + SC federal courts
        "filed_after": "2020-01-01",
    }
    headers = {"Authorization": f"Token {token}"}
    try:
        r = await client.get(url, params=params, headers=headers, timeout=FETCH_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results", [])
        return results[:5]  # cap at 5 hits per name
    except Exception as exc:
        log.debug("irs_lien.search_fail", query=name_query[:60], error=str(exc)[:120])
        return []


def _parse_lien_amount(text: str) -> Optional[float]:
    """Extract dollar amounts from case description / case_name fields."""
    amounts = []
    for m in re.finditer(r"\$[\d,]{3,}(?:\.\d{2})?", text):
        try:
            amounts.append(float(m.group().replace("$", "").replace(",", "")))
        except ValueError:
            continue
    return max(amounts) if amounts else None


async def enrich_irs_liens(listings: list[Listing]) -> dict:
    """Search CourtListener RECAP for IRS tax lien cases matching property owners.
    Appends findings to raw['liens'] so the equity engine counts them.

    Only searches listings that have an owner name and haven't already been
    flagged with an IRS lien.
    """
    token = _load_token()
    if not token:
        log.warning("irs_lien.no_token")
        return {"searched": 0, "matched": 0, "skipped_no_token": True}

    # Build eligible set — need owner name, skip if already has irs_lien
    eligible: list[Listing] = []
    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        # Get best owner name
        owner = None
        gis = li.raw.get("gis") or {}
        if isinstance(gis, dict):
            owner = gis.get("owner")
        if not owner:
            owner = getattr(li, "defendant", None) or getattr(li, "owner_name", None)
        if not owner:
            continue
        # Skip if already has an irs_lien in the lien stack
        existing_liens = li.raw.get("liens") or []
        if isinstance(existing_liens, list):
            if any(x.get("source") == "irs_lien" for x in existing_liens if isinstance(x, dict)):
                continue
        eligible.append(li)

    # Limit lookups per run
    if len(eligible) > MAX_LOOKUPS:
        eligible = eligible[:MAX_LOOKUPS]

    if not eligible:
        log.info("irs_lien.no_eligible")
        return {"searched": 0, "matched": 0, "eligible": 0}

    log.info("irs_lien.start", eligible=len(eligible), max_lookups=MAX_LOOKUPS)
    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"searched": 0, "matched": 0, "eligible": len(eligible)}

    async with httpx.AsyncClient() as client:
        async def one(li: Listing) -> None:
            owner = None
            gis = li.raw.get("gis") or {}
            if isinstance(gis, dict):
                owner = gis.get("owner")
            if not owner:
                owner = getattr(li, "defendant", None) or getattr(li, "owner_name", None)

            query = _name_query(owner)
            if not query:
                return
            async with sem:
                stats["searched"] += 1
                hits = await _search_cl(client, token, query)

            if not hits:
                return
            # Check if any hit looks like a real IRS tax lien
            for hit in hits:
                case_name = (hit.get("caseName") or "") + " " + (hit.get("case_description") or "")
                case_name = case_name.upper()
                if any(kw in case_name for kw in ("IRS", "TAX LIEN", "INTERNAL REVENUE",
                                                    "FEDERAL TAX", "U.S. v", "UNITED STATES v")):
                    amount = _parse_lien_amount(case_name)
                    liens = list(li.raw.get("liens") or [])
                    liens.append({
                        "type": "federal_tax_lien",
                        "amount": amount,
                        "source": "irs_lien",
                        "holder": "IRS",
                        "super_priority": True,
                        "case_number": hit.get("docketNumber"),
                        "court": hit.get("court"),
                        "case_url": hit.get("absolute_url"),
                    })
                    li.raw["liens"] = liens
                    stats["matched"] += 1
                    return

        await asyncio.gather(*(one(li) for li in eligible))

    log.info("irs_lien.done", **stats)
    return stats
