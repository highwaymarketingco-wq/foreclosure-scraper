"""Publication-reach / competition signal — how much PUBLIC ATTENTION a lead draws.

The point (Dad's): a widely-published foreclosure sale — a big trustee firm's
prominent, well-trafficked public sales list (Hutchens is the archetype) — draws
MORE bidders, so it is MORE COMPETITIVE and LESS of a quiet off-market steal than,
say, a lone tax-delinquent parcel that nobody has looked at yet.

This is deliberately NOT a distress boost. "How motivated is the seller"
(distress) and "how many other buyers already see this" (competition) are
orthogonal axes. A widely-published sale can be just as distressed — it is simply
more contested. So we stamp a TRANSPARENT tag the dashboard/operator can read and
filter on, and we do NOT silently change any grade, tier, or intent score.

    raw['competition'] = {
        'level': 'high' | 'medium' | 'low',
        'reason': <machine-stable reason slug>,
        'widely_published': bool,   # any widely-published trustee list in source set
        'sources': [<slug>, ...],   # full source set considered (sorted)
    }

Levels:
  high   — the lead appears on a WIDELY-PUBLISHED trustee sale list (see
           WIDELY_PUBLISHED_SOURCES). Prominent roster, lots of eyeballs, many
           bidders → most competitive.
  low    — a single QUIET off-market signal (a lone tax-delinquent /
           code-enforcement / probate lead) with NO other corroborating source.
           Nobody else is looking → least competitive, best steal potential.
  medium — everything in between (e.g. a court filing not on a big published
           roster, or a multi-source lead that isn't widely published).

The set of widely-published firms lives in ONE named constant,
WIDELY_PUBLISHED_SOURCES — adding a firm later is a one-line append. Matched as a
lowercased-substring against the lead's full source set (li.source + every
also_seen_in source), so a new slug (e.g. "law_firms.alaw") lands automatically.

Pure-Python, offline, idempotent — safe to re-run. Mirrors the structure of
enrichment_corroboration.py (sync, cheap, stamps raw, returns stats).
"""
from __future__ import annotations

from typing import Iterable

from .models import Listing

# Widely-published trustee / substitute-trustee firms whose public foreclosure
# sale lists are prominent and well-trafficked — a listing here is seen by many
# bidders, so it is MORE competitive. Matched as a lowercased substring against
# each source slug (e.g. "law_firms.hutchens" contains "hutchens"). Add a firm
# later in ONE line by appending its slug fragment here.
WIDELY_PUBLISHED_SOURCES = (
    "hutchens",
    "shapiro_ingle",
    "brock_scott",
    "aldridge_pite",
    "bell_carrington",
    "rogers_townsend",
    # newer / to-be-built firm rosters — tagged automatically once their
    # scrapers exist and start emitting slugs.
    "alaw",
    "foundation_legal",
    "cannon_law",
)

# Quiet off-market distress signals: a property that shows up ONLY on one of
# these — with no corroborating source — is one almost nobody else is watching,
# the classic low-competition steal. Substring match against the slug.
_QUIET_SIGNAL_SOURCES = (
    "delinquent_tax",
    "tax_delinquent",
    "code_enforcement",
    "code_enf",
    "probate",
    "estate",
    "obituar",
    "condemned",
    "vacant",
)

# machine-stable reason slugs (kept as constants so the dashboard/tests can key
# off them without matching prose).
REASON_WIDELY_PUBLISHED = "widely_published_trustee_sale_list"
REASON_QUIET_SINGLE_SOURCE = "single_source_quiet_signal"
REASON_MODERATE = "moderate_reach"


def _is_widely_published(slug: str) -> bool:
    s = (slug or "").lower()
    return bool(s) and any(p in s for p in WIDELY_PUBLISHED_SOURCES)


def _is_quiet_signal(slug: str) -> bool:
    s = (slug or "").lower()
    return bool(s) and any(p in s for p in _QUIET_SIGNAL_SOURCES)


def _collect_sources(li: Listing) -> list[str]:
    """Distinct source slugs for a lead: primary li.source + every also_seen_in
    source, dropping falsy / duplicate values (order-preserving). Same rule the
    corroboration enricher uses, so the two tags always consider the same set."""
    slugs: list[str] = []
    seen: set[str] = set()

    def _add(s):
        if s and s not in seen:
            seen.add(s)
            slugs.append(s)

    _add(li.source)
    for d in (li.raw or {}).get("also_seen_in", []) or []:
        if isinstance(d, dict):
            _add(d.get("source"))
    return slugs


def _classify(slugs: list[str]) -> tuple[str, str, bool]:
    """Return (level, reason, widely_published) for a lead's full source set."""
    widely = any(_is_widely_published(s) for s in slugs)
    if widely:
        return "high", REASON_WIDELY_PUBLISHED, True
    if len(slugs) == 1 and _is_quiet_signal(slugs[0]):
        return "low", REASON_QUIET_SINGLE_SOURCE, False
    return "medium", REASON_MODERATE, False


def enrich_competition(listings: Iterable[Listing]) -> dict:
    """Stamp raw['competition'] on leads. Returns distribution stats.

    SIZE NOTE: docs/listings.json is committed to git, which has a hard 100 MB
    per-file limit, and the board already sits near it. A per-lead tag on all
    ~30k leads (esp. the 'sources' list) added ~3.7 MB and pushed the file over,
    so we persist ONLY the actionable 'high' leads (widely-published trustee sale
    lists — dad's point: those draw the most bidders). 'medium'/'low' are the
    uninformative middle/quiet default; they are counted in stats but NOT stamped,
    so absence of the tag == not-high. Tag kept minimal (no 'sources' list —
    that is already recoverable from raw['also_seen_in']).

    Transparent tag only — never mutates grade / tier / intent. Idempotent."""
    stats = {"tagged": 0, "high": 0, "medium": 0, "low": 0, "widely_published": 0}
    for li in listings:
        slugs = _collect_sources(li)
        if not slugs:
            continue
        level, reason, widely = _classify(slugs)
        stats[level] += 1
        if widely:
            stats["widely_published"] += 1
        # Only the 'high' (widely-published / crowded) leads carry the tag — the
        # signal the operator asked for — to stay under git's 100 MB file limit.
        if level != "high":
            if isinstance(li.raw, dict):
                li.raw.pop("competition", None)  # clear any stale full-shape tag
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["competition"] = {"level": "high", "reason": reason}
        stats["tagged"] += 1
    return stats
