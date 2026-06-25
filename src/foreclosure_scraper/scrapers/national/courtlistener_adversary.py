"""CourtListener bankruptcy lift-stay + §363 sale scraper (RECAP full-text search).

Two high-signal filings inside NC/SC bankruptcy dockets:

  1. Motion to lift the automatic stay (11 U.S.C. §362)
     The lender is asking the bankruptcy court for permission to proceed
     with foreclosure DESPITE the automatic stay. This is the LATEST
     possible pre-foreclosure indicator — typically within 30-60 days of
     the lender restarting the state-court foreclosure process.

  2. Section 363 sale / abandonment motion (11 U.S.C. §363, §554)
     The bankruptcy estate is selling or abandoning debtor real estate.
     Often deeply discounted because the trustee wants liquidity over
     market price.

Why the rewrite (2026-06-25):
  The previous implementation fanned out one docket-entries sub-fetch PER
  docket across thousands of recent dockets. That is request-heavy enough
  that safe_run()'s soft timeout hard-killed the run to 0 every pass.

  This version makes ONE CourtListener `GET /search/?type=r` (RECAP)
  full-text call per (court, phrase) instead. The full-text search engine
  IS the relevance gate: only dockets containing a document matching the
  phrase ("relief from stay", "motion for relief", "363 sale",
  "abandonment", "lift stay") come back. Each result carries the docket
  metadata directly (caseName=debtor, docketNumber, court_id, dateFiled,
  chapter, docket_absolute_url) plus nested recap_documents[]. No
  per-docket fan-out, no PACER PDF downloads (we store URL refs only).

  type=r result shape (live-verified): top-level short_description /
  description / snippet are ALL None. The classifiable result-level text
  lives on caseName, suitNature, and recap_documents[].short_description
  (e.g. "Relief from Stay", "Notice and Application for Abandonment").
  recap_documents[].description is empty in the type=r shape, so the
  classifier is run on the result-level blob, NOT on rd.description.

Fee impact: free under the standard CourtListener API (publicly-mirrored
PACER, no per-page billing). Same auth token as the working
courtlistener_bankruptcy scraper.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from .courtlistener_bankruptcy import (
    API_BASE,
    COURTS,
    COURT_STATE,
    _county_from_text,
    _load_token,
)

log = structlog.get_logger()

# Full-text phrases issued to the RECAP search engine. Each is run once per
# court. These are the document-text phrases that surface lift-stay and
# §363/abandonment motions. "relief from stay" / "motion for relief" carry
# the volume; the others catch edge phrasings. Live-verified the engine
# returns NC/SC dockets for each.
SEARCH_PHRASES = (
    "relief from stay",
    "motion for relief",
    "lift stay",
    "363 sale",
    "abandonment",
)

# Only mine dockets filed this recently. The RECAP search engine sorts by
# dateFiled (case-open date); a lift-stay motion lands weeks after the case
# opens, so a generous window keeps entry-bearing dockets in range without
# the dateless tail. ~18 months of bankruptcy cases.
FILED_AFTER = "2025-01-01"

# Pages to pull per (court, phrase). Page 1 = 20 hits; two pages keeps the
# whole fan-out well under 30s while reaching ~40 in-footprint leads.
MAX_PAGES_PER_QUERY = 2

# ---------------------------------------------------------------------------
# Classification on the RESULT-LEVEL text blob (caseName + suitNature +
# recap_documents[].short_description). Order matters: lift-stay is the most
# actionable, then §363 sale, then abandonment.
# ---------------------------------------------------------------------------
LIFT_STAY_RE = re.compile(
    r"relief\s+from\s+(?:the\s+)?(?:automatic\s+)?stay"
    r"|lift\s+(?:the\s+)?(?:automatic\s+)?stay"
    r"|motion\s+for\s+relief"
    r"|stay\s+relief",
    re.I,
)
SECTION_363_RE = re.compile(
    r"(?:11\s*U\.?S\.?C\.?\s*(?:section|§)\s*363|section\s*363|§\s*363|\b363\b)"
    r".{0,80}?(?:sale|sell|sold)"
    r"|(?:sale|sell|sold).{0,80}?(?:section\s*363|§\s*363|\b363\b)",
    re.I | re.S,
)
ABANDONMENT_RE = re.compile(
    r"abandon(?:ment|ing|ed)?(?:\s+of\s+(?:real\s+)?propert)?",
    re.I,
)

# Drop obvious non-real-property relief-from-stay noise: vehicle / auto /
# consumer-goods stay motions are common and irrelevant to foreclosure.
NON_REALTY_RE = re.compile(
    r"\b(?:vehicle|automobile|\bauto\b|\bcar\b|truck|motorcycle|"
    r"boat|rv\b|atv\b|repossess)\b",
    re.I,
)
# Positive real-property cues that override the non-realty filter when both
# appear (a motion can reference both a car and the house).
REALTY_RE = re.compile(
    r"\b(?:real\s+propert|real\s+estate|residen|dwelling|mortgage|"
    r"deed\s+of\s+trust|foreclos|homestead|\bproperty\s+located\b|"
    r"\bpremises\b|\bland\b|lot\s+\d)\b",
    re.I,
)


def _result_blob(result: dict) -> str:
    """Combine the result-level text that IS populated in the type=r shape.

    Top-level short_description / description / snippet are None in RECAP
    search results; the descriptive text lives on caseName, suitNature and
    each recap_documents[].short_description. recap_documents[].description
    is empty in this shape, so it is intentionally excluded.
    """
    parts = [
        result.get("caseName") or "",
        result.get("suitNature") or "",
        result.get("cause") or "",
    ]
    for rd in result.get("recap_documents") or []:
        if isinstance(rd, dict):
            parts.append(rd.get("short_description") or "")
    return " ".join(p for p in parts if p)


def _classify(blob: str) -> str | None:
    """Return 'lift_stay' / '363_sale' / 'abandonment' / None for a result.

    The full-text search already guarantees the docket contains the phrase,
    so a blank result-level blob (motion text only in the document body)
    still classifies as lift_stay when the query that produced it was a
    lift-stay phrase — handled by the caller's query-label fallback. Here we
    only assign a label from the visible result text.
    """
    if not blob:
        return None
    # Real-property gate for relief-from-stay: skip vehicle/consumer stays
    # unless a positive realty cue is present.
    if LIFT_STAY_RE.search(blob):
        if NON_REALTY_RE.search(blob) and not REALTY_RE.search(blob):
            return None
        return "lift_stay"
    if SECTION_363_RE.search(blob):
        return "363_sale"
    if ABANDONMENT_RE.search(blob):
        if NON_REALTY_RE.search(blob) and not REALTY_RE.search(blob):
            return None
        return "abandonment"
    return None


# Backward-compatible alias. The previous docket-entries implementation
# exposed _classify_entry(description); tests and the recap-enrichment module
# still import it. The classifier logic is identical — it runs on a text blob.
_classify_entry = _classify


# Map each search phrase to the classification it implies, so a result whose
# visible blob is blank (motion text lives only in the un-returned document
# body) still gets the correct label from the query that found it.
PHRASE_LABEL = {
    "relief from stay": "lift_stay",
    "motion for relief": "lift_stay",
    "lift stay": "lift_stay",
    "363 sale": "363_sale",
    "abandonment": "abandonment",
}


async def _search(c, token: str, court: str, phrase: str) -> list[dict]:
    """One RECAP full-text search for (court, phrase), paginated up to
    MAX_PAGES_PER_QUERY. Best-effort, never raises."""
    results: list[dict] = []
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    params = {
        "type": "r",
        "q": f'"{phrase}"',
        "court": court,
        "filed_after": FILED_AFTER,
        "order_by": "dateFiled desc",
    }
    url: str | None = f"{API_BASE}/search/"
    page = 0
    while url and page < MAX_PAGES_PER_QUERY:
        try:
            r = await c.get(
                url,
                params=params if page == 0 else None,
                headers=headers,
            )
            if r.status_code != 200:
                if page == 0:
                    log.warning("courtlistener_adv.search_error",
                                court=court, phrase=phrase, status=r.status_code)
                break
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("courtlistener_adv.search_exc",
                        court=court, phrase=phrase, error=str(exc)[:120])
            break
        results.extend(data.get("results") or [])
        url = data.get("next")  # absolute URL with all params baked in
        page += 1
    return results


class CourtListenerAdversary(BaseScraper):
    """Lift-stay motions + §363 sale / abandonment motions inside NC + SC
    bankruptcy dockets, via one RECAP full-text search per (court, phrase).
    Each docket is its own Listing (deduped on court+docket)."""

    slug = "national.courtlistener_adversary"
    name = "CourtListener bankruptcy adversary (lift stay + 363 sale)"
    category = "federal_court"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        token = _load_token()
        if not token:
            log.info("courtlistener_adv.no_token")
            return []

        t0 = time.monotonic()
        out: list[Listing] = []
        # Dedup on (court, docket_number) — the same docket surfaces under
        # multiple phrases (a case with both a relief-from-stay and an
        # abandonment motion). First label wins (phrase order = priority).
        seen: set[tuple[str, str]] = set()

        async with client(timeout=30.0) as c:
            # Fan out all (court, phrase) searches concurrently — 15 calls,
            # ~10s wall-clock. Each returns the docket metadata directly; no
            # per-docket sub-fetch.
            tasks = [
                (court, phrase, _search(c, token, court, phrase))
                for court in COURTS
                for phrase in SEARCH_PHRASES
            ]
            gathered = await asyncio.gather(
                *(t[2] for t in tasks), return_exceptions=True
            )

            for (court, phrase, _), results in zip(tasks, gathered):
                if isinstance(results, Exception) or not results:
                    continue
                for res in results:
                    docket_no = (res.get("docketNumber") or "").strip()
                    case_name = res.get("caseName") or ""
                    if not docket_no and not case_name:
                        continue

                    key = (court, docket_no or case_name[:60])
                    if key in seen:
                        continue
                    seen.add(key)

                    blob = _result_blob(res)
                    cls = _classify(blob) or PHRASE_LABEL.get(phrase)
                    if not cls:
                        continue

                    state_default = COURT_STATE.get(court, "NC")
                    state_match, county_match = _county_from_text(case_name)

                    chapter = res.get("chapter")
                    date_filed = res.get("dateFiled")
                    abs_url = res.get("docket_absolute_url") or ""
                    source_url = (
                        ("https://www.courtlistener.com" + abs_url)
                        if abs_url.startswith("/")
                        else (abs_url or "")
                    )

                    label = {
                        "lift_stay": "Motion for Relief from Automatic Stay",
                        "363_sale": "§363 Real-Property Sale Motion",
                        "abandonment": "Motion to Abandon Real Property",
                    }[cls]
                    desc = (
                        f"{label} in Ch.{chapter or '?'} bankruptcy "
                        f"{docket_no or '?'} ({court.upper()}) filed "
                        f"{date_filed or '?'} — Debtor: {case_name[:120]}"
                    )[:500]

                    # recap_documents short labels (URL refs only — never the PDF).
                    rd_refs = []
                    for rd in (res.get("recap_documents") or [])[:8]:
                        if not isinstance(rd, dict):
                            continue
                        rd_refs.append({
                            "short_description": rd.get("short_description"),
                            "document_number": rd.get("document_number"),
                            "entry_date_filed": rd.get("entry_date_filed"),
                            "absolute_url": rd.get("absolute_url"),
                        })

                    out.append(Listing(
                        source=self.slug,
                        source_url=source_url,
                        listing_type=ListingType.LIS_PENDENS,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state_match or state_default,
                        county=county_match,
                        case_number=docket_no or None,
                        defendant=case_name[:200] or None,
                        description=desc,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"courtlistener_adversary": {
                            "court": court,
                            "classification": cls,
                            "matched_phrase": phrase,
                            "docket_number": docket_no,
                            "case_name": case_name,
                            "chapter": chapter,
                            "date_filed": date_filed,
                            "suit_nature": res.get("suitNature"),
                            "party": res.get("party"),
                            "docket_id": res.get("docket_id"),
                            "docket_absolute_url": abs_url,
                            "recap_documents": rd_refs,
                        }},
                    ))

        log.info("courtlistener_adv.done",
                 listings=len(out),
                 courts=len(COURTS),
                 phrases=len(SEARCH_PHRASES),
                 elapsed_s=round(time.monotonic() - t0, 1))
        return out
