"""Extract judgment_amount (mortgage balance proxy) from text we already have.

Foreclosure notices, lis pendens filings, and trustee sale notices almost
always quote a dollar amount somewhere in the public text — "Pursuant to a
Judgment in the amount of $123,456.78", "Outstanding principal: $X",
"Total amount due: $Y". The investor uses this as a proxy for "mortgage
balance remaining" which would otherwise require servicer access.

This enrichment text-mines li.description and li.raw for those patterns
WITHOUT issuing any HTTP requests. Free, fast, idempotent.

Confidence policy:
  * Patterns are anchored to context phrases ("judgment", "balance due",
    "principal sum", "amount of", "indebtedness") to avoid catching
    sale prices, opening bids, or unrelated dollar figures elsewhere
    in the text.
  * Validates the amount is in [$1,000, $50,000,000] — anything outside
    is almost certainly a parse error or unrelated number.
  * Skipped silently when judgment_amount is already populated.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


# Money-amount regex. Matches $123,456.78 / $123,456 / $1.23M / 123,456.78.
# We require the leading $ for high precision (fewer false positives) when
# scanning generic body text — the context patterns below also require it.
_AMOUNT = r"\$\s*([\d,]+(?:\.\d+)?(?:\s*[Mm]illion)?)"

# Context phrases that PRECEDE a judgment-relevant amount. We allow up to
# ~40 chars of connector words between the phrase and the dollar amount
# ("the outstanding principal balance is $X", "principal sum due of $Y")
# since the legal-notice prose varies. Order: most-specific first.
_JUDGMENT_PATTERNS = [
    re.compile(
        rf"judgment\s+(?:amount|sum|in\s+the\s+(?:total\s+)?amount\s+of)\s*[:=]?\s*{_AMOUNT}",
        re.I,
    ),
    re.compile(
        rf"pursuant\s+to\s+(?:a|that\s+certain|the)\s+judgment.{{0,80}}?in\s+the\s+(?:total\s+)?amount\s+of\s+{_AMOUNT}",
        re.I | re.S,
    ),
    re.compile(
        rf"(?:total\s+amount\s+due|outstanding\s+(?:principal\s+)?balance|"
        rf"outstanding\s+principal|outstanding\s+indebtedness|"
        rf"principal\s+(?:sum|balance)|balance\s+due)\b.{{0,40}}?{_AMOUNT}",
        re.I,
    ),
    re.compile(
        rf"(?:indebtedness|amount\s+owing|debt\s+secured)\b.{{0,40}}?{_AMOUNT}",
        re.I,
    ),
    re.compile(
        rf"(?:foreclosure\s+judgment|deficiency\s+judgment)\s*[:=]?\s*{_AMOUNT}",
        re.I,
    ),
]

# Phrases that, when nearby, indicate the amount is NOT the judgment (sale
# price, opening bid, asking, etc.). Used to filter false positives.
_NON_JUDGMENT_NEAR = re.compile(
    r"\b(opening\s+bid|sale\s+price|asking|listing\s+price|reserve\s+price|"
    r"appraised\s+value|tax\s+value|assessed\s+value|earnest\s+money|"
    r"deposit\b)",
    re.I,
)


def _parse_amount(s: str) -> Optional[float]:
    """Parse a money-amount string. Handles "1,234.56", "1.23 million", etc."""
    if not s:
        return None
    s = s.strip()
    is_million = bool(re.search(r"million", s, re.I))
    digits = re.sub(r"[^\d.]", "", s)
    if not digits:
        return None
    try:
        amt = float(digits)
    except ValueError:
        return None
    if is_million:
        amt *= 1_000_000
    return amt


def _extract_from_text(text: str) -> Optional[float]:
    """Search a single text body for a judgment-context amount."""
    if not text or len(text) < 20:
        return None
    for pat in _JUDGMENT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        # Reject only when the BEFORE-context (the 80 chars leading up to
        # the matched phrase) talks about sale price / opening bid /
        # asking. The judgment context already won the precedence battle
        # by matching first; we just guard against the case where the
        # pattern matched inside a sentence that was actually about
        # something else ("...for opening bid see judgment...").
        window_start = max(0, m.start() - 80)
        ctx_before = text[window_start:m.start()]
        if _NON_JUDGMENT_NEAR.search(ctx_before):
            continue
        amt = _parse_amount(m.group(1))
        if amt is not None and 1_000 <= amt <= 50_000_000:
            return amt
    return None


def _texts_to_search(li: Listing) -> list[str]:
    """Collect every text blob on the listing that might contain the
    judgment amount. Order from most-specific to most-generic."""
    out: list[str] = []
    if li.description:
        out.append(li.description)
    if isinstance(li.raw, dict):
        # Per-source structured payloads — most law-firm scrapers stash the
        # full notice text under raw[source_slug] or raw["notice_text"].
        for key in ("notice_text", "trustee_notice", "case_summary", "judgment_text"):
            v = li.raw.get(key)
            if isinstance(v, str):
                out.append(v)
        # Source-specific blobs
        for k, v in li.raw.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    if isinstance(sub_v, str) and len(sub_v) > 50:
                        out.append(sub_v)
    return out


def enrich_judgment_amount(listings: list[Listing]) -> dict:
    """Populate li.judgment_amount from already-available text. Pure-Python,
    no I/O. Returns a stats dict for the run summary."""
    stats = {"scanned": 0, "matched": 0, "already_set": 0}
    for li in listings:
        if li.judgment_amount is not None and li.judgment_amount > 0:
            stats["already_set"] += 1
            continue
        stats["scanned"] += 1
        for text in _texts_to_search(li):
            amt = _extract_from_text(text)
            if amt is not None:
                li.judgment_amount = round(amt, 2)
                stats["matched"] += 1
                break
    log.info("judgment_amount.done", **stats)
    return stats
