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
    # "judgment amount [of] $X" / "judgment sum [of] $X" / "judgment in the (total) amount of $X"
    # The "of" between "amount" and "$X" is optional — both phrasings appear.
    re.compile(
        rf"judgment\s+(?:amount|sum)(?:\s+of)?\s*[:=]?\s*{_AMOUNT}",
        re.I,
    ),
    re.compile(
        rf"judgment\s+in\s+the\s+(?:total\s+)?amount\s+of\s*[:=]?\s*{_AMOUNT}",
        re.I,
    ),
    # "pursuant to a/that/the judgment ... in the amount of $X" — multi-line
    re.compile(
        rf"pursuant\s+to\s+(?:a|that\s+certain|the)\s+judgment.{{0,80}}?in\s+the\s+(?:total\s+)?amount\s+of\s+{_AMOUNT}",
        re.I | re.S,
    ),
    # "money judgment ... in the (total) amount of $X" (NC notice variant)
    re.compile(
        rf"money\s+judgment.{{0,80}}?(?:in\s+the\s+(?:total\s+)?amount\s+of|of)\s+{_AMOUNT}",
        re.I | re.S,
    ),
    # Common "outstanding..." / "balance due" / "principal sum/balance" phrasings
    re.compile(
        rf"(?:total\s+amount\s+due|outstanding\s+(?:principal\s+)?balance|"
        rf"outstanding\s+principal|outstanding\s+indebtedness|"
        rf"unpaid\s+(?:principal\s+)?balance|unpaid\s+principal|"
        rf"principal\s+(?:sum|balance)|balance\s+(?:due|owed|owing))\b.{{0,40}}?{_AMOUNT}",
        re.I,
    ),
    # "indebtedness" / "amount owing" / "debt secured"
    re.compile(
        rf"(?:indebtedness|amount\s+owing|debt\s+secured)\b.{{0,40}}?{_AMOUNT}",
        re.I,
    ),
    # "foreclosure judgment" / "deficiency judgment" with attached amount
    re.compile(
        rf"(?:foreclosure\s+judgment|deficiency\s+judgment)\s*[:=]?\s*{_AMOUNT}",
        re.I,
    ),
    # NC notice variant: "evidenced by ... promissory note in the (original)
    # principal (amount/sum) of $X"
    re.compile(
        rf"promissory\s+note\b.{{0,60}}?(?:original\s+)?principal\s+(?:amount|sum)\s+of\s+{_AMOUNT}",
        re.I | re.S,
    ),
    # NC notice variant: "secured by ... in the original principal amount of $X"
    re.compile(
        rf"original\s+principal\s+(?:amount|sum)\s+of\s+{_AMOUNT}",
        re.I,
    ),
    # "the sum of $X" when paired with judgment/note/balance context
    # within the surrounding 60 chars
    re.compile(
        rf"(?:judgment|debt|note|loan|principal)\b[^\n$]{{0,60}}?the\s+sum\s+of\s+{_AMOUNT}",
        re.I,
    ),
]

# Phrases that, when nearby, indicate the amount is NOT the judgment.
# Tightened scope: only reject when the non-judgment phrase appears
# IMMEDIATELY before the amount (within 30 chars). The previous 80-char
# window was killing valid matches like "opening bid will not be less
# than the judgment amount of $X" where "opening bid" sits 50+ chars
# before the judgment phrase.
_NON_JUDGMENT_NEAR = re.compile(
    r"\b(opening\s+bid|sale\s+price|asking\s+price|listing\s+price|"
    r"reserve\s+price|appraised\s+value|tax\s+value|assessed\s+value|"
    r"earnest\s+money|deposit\s+(?:of|amount))\b",
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
        # Reject only when the BEFORE-context (the 30 chars IMMEDIATELY
        # leading up to the matched amount) talks about sale price /
        # opening bid / asking. Previous 80-char window was too wide
        # and killed valid matches like "opening bid will not be less
        # than the judgment amount of $X" where "opening bid" sits
        # 50+ chars before the judgment phrase. Tightened to 30 chars
        # so only adjacent context (e.g., "the opening bid of $X")
        # triggers rejection.
        window_start = max(0, m.start() - 30)
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
    no I/O. Returns a stats dict for the run summary.

    Diagnostic: tracks WHY matches fail (no text vs text-but-no-pattern-match)
    so we know whether to enhance scrapers (need more text) or patterns
    (need broader regex).
    """
    stats = {
        "scanned": 0, "matched": 0, "already_set": 0,
        "no_text": 0, "text_no_match": 0,
        "by_source_matched": {},
    }
    for li in listings:
        if li.judgment_amount is not None and li.judgment_amount > 0:
            stats["already_set"] += 1
            continue
        stats["scanned"] += 1
        texts = _texts_to_search(li)
        if not texts:
            stats["no_text"] += 1
            continue
        matched = False
        for text in texts:
            amt = _extract_from_text(text)
            if amt is not None:
                li.judgment_amount = round(amt, 2)
                stats["matched"] += 1
                src = li.source or "unknown"
                stats["by_source_matched"][src] = stats["by_source_matched"].get(src, 0) + 1
                matched = True
                break
        if not matched:
            stats["text_no_match"] += 1
    log.info("judgment_amount.done", **stats)
    return stats
