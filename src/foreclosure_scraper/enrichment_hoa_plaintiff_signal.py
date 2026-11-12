"""HOA/POA/COA-plaintiff signal read straight off the plaintiff field already
collected for every judicial-foreclosure / lis-pendens listing — the
higher-value half of the 2026-10-02 `lt_hoa_sale` (ListingType.HOA_SALE)
investigation.

Context (counties_sc.charleston_mie.py, the "Canterbury Woods v. McCracken"
finding): `lt_hoa_sale` shows 0 rows board-wide even though real HOA
foreclosure sales ARE being scraped live. Charleston's own auction list
("MASTER'S AUCTION LIST") never tags HOA at all — only the UncontestedRoster
hearing roster's "HOA FORECLOSURES" section does, and small weekly volume /
the 18-county flip-footprint scope / a dedupe rule that used to drop the HOA
tag when a case also landed on the richer auction list (see that scraper's
own fix, same date) all combine to keep the literal HOA_SALE type near zero.

But both NC (G.S. 47F-3-116) and SC HOA lien foreclosures ride the SAME
public judicial / power-of-sale notice process as an ordinary mortgage
foreclosure, and this board already collects a `plaintiff` field for every
`foreclosure_sale` / `lis_pendens` row from dozens of sources
(sc_public_index, sc_public_index_export, sc_public_index_lis_pendens,
greenville_mie_adverts, nc_ecourts_lis_pendens, sc_public_notices,
national.foreclosure_dot_com, newspapers.*, charleston_mie itself, ...) --
`grep -rn "plaintiff" src/foreclosure_scraper/scrapers/` finds dozens of call
sites. So the HOA foreclosure leads are very likely ALREADY on the board,
just captioned as the generic `foreclosure_sale`/`lis_pendens` type because
nothing ever read the plaintiff text back for an HOA keyword.

This enricher is that read-back. It does NOT retype any listing (retyping is
a scope/scoring decision left for a future session per that investigation's
own note: "any actual board backfill with this new flag is separate future
work") — it only stamps a parallel, additive signal so the operator/dashboard
can filter on it without waiting for a rescrape or a retype:

    raw['hoa_plaintiff_signal'] = {
        "hoa_sale_suspected": True,
        "matched": "homeowners association",   # which classify_hoa_plaintiff pattern fired
        "plaintiff": "Amherst Homeowners Association Inc",
        "listing_type": "lis_pendens",          # the generic type this was captured under
    }

Design notes / house style (mirrors enrichment_co_defendant_signal.py, the
most recent sibling signal enricher):
  * Pure-Python, no network, no I/O.
  * Scoped to ListingType.FORECLOSURE_SALE and ListingType.LIS_PENDENS only --
    the two generic types the investigation named as hiding HOA plaintiffs.
    (A row already typed HOA_SALE needs no signal; AUCTION/SHERIFF_SALE/REO
    plaintiffs are a different question left for a future pass.)
  * Reuses enrichment_title_risk.classify_hoa_plaintiff() -- the SAME
    SENIOR-bank-table-wins-ties guard already proven live in that module, so
    a bank trustee carrying "National Association" (confirmed live: dozens of
    "U.S. Bank National Association" / "PNC Bank, National Association" /
    "JPMorgan Chase Bank, National Association" rows sit right next to real
    "... Homeowners Association" rows on the board today) is never
    misclassified as an HOA. Also reuses _party_text() for the same
    plaintiff/trustee/raw-fallback extraction enrichment_title_risk already
    uses, rather than re-deriving a second "best party string" rule.
  * Conservative: a bare, unqualified "... Association" plaintiff (real
    live-board examples: "Harbor Town Association, Inc.", "Tall Ship
    Association Inc", "Chickasaw Association Inc") is left untagged rather
    than guessed at -- see classify_hoa_plaintiff's own docstring.
"""
from __future__ import annotations

import structlog

from .enrichment_title_risk import _party_text, classify_hoa_plaintiff
from .models import Listing, ListingType

log = structlog.get_logger()

#: The two generic types the 2026-10-02 investigation found hiding HOA
#: plaintiffs. Kept as a frozenset (not reusing distress_score.FLIP_TYPES or
#: main._FLIP_LISTING_TYPES, which are broader scope/scoring concepts) because
#: this signal is specifically about captions, not about flip-footprint scope.
TARGET_LISTING_TYPES = frozenset({ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS})


def _ltype_value(li: Listing) -> str:
    lt = li.listing_type
    return lt.value if hasattr(lt, "value") else str(lt or "")


def enrich_hoa_plaintiff_signal(listings: list[Listing]) -> dict:
    """Stamp `raw['hoa_plaintiff_signal']` on foreclosure_sale/lis_pendens rows
    whose plaintiff text is an HOA/POA/COA entity. Pure computation, drops
    nothing."""
    before = len(listings)
    stats = {"checked": 0, "tagged": 0}
    for li in listings:
        if li.listing_type not in TARGET_LISTING_TYPES:
            continue
        party = _party_text(li)
        if not party:
            continue
        stats["checked"] += 1
        result = classify_hoa_plaintiff(party)
        if not result["is_hoa"]:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["hoa_plaintiff_signal"] = {
            "hoa_sale_suspected": True,
            "matched": result["matched"],
            "plaintiff": party[:200],
            "listing_type": _ltype_value(li),
        }
        stats["tagged"] += 1
    assert len(listings) == before, "hoa_plaintiff_signal must never drop a lead"
    if stats["tagged"]:
        log.info("hoa_plaintiff_signal.done", **stats)
    return stats
