"""Repeat tax/foreclosure-sale loser — owner who lost a parcel before and
still holds another one now.

Direct implementation of Dirty Deeds Tier A #34 (docs/dirty_deeds_synthesis_
2026-09-10.md): "Match tax-deed grantors back to the current owner index. A
proven non-payer with proven capitulation. Ep 032's $350k-spread seller had
already lost one inherited property; ep 034's decedent lost parcels in 2016
and 'still got like three properties in her name.'" Rated free, easy build.

Built on top of enrichment_deed_chain.py's distress_transfers, which as of
2026-09-17 recognizes tax-sale/foreclosure-sale conveyances (TAX DEED,
SHERIFF'S DEED, TRUSTEE'S DEED/SUBSTITUTE TRUSTEE, MASTER IN EQUITY,
CLERK'S DEED) as a distress-type class -- this enricher is the cross-parcel
JOIN the synthesis says is the only missing piece, not a new scraper.

TWO PASSES, same shape as enrichment_owner_cluster.py:
  1. Scan every listing's deed_chain distress_transfers for a tax-sale/
     foreclosure-sale conveyance with a recorded grantor (the party who LOST
     that parcel). Index those grantor names by (surname, given, county,
     state), the same scoping owner_cluster.py uses and for the same reason:
     a bare name match nationwide is noise, county+state keeps it plausible.
  2. For every CURRENT listing on the board, check whether its owner_name
     matches a name in that loser index (same county/state) on a DIFFERENT
     property than the one they lost. A match means this owner has already
     lost real estate to a tax/foreclosure sale and is still holding
     property today -- a proven non-payer, proven capitulation signal.

Self-match guard: a listing whose OWN deed_chain shows itself being
reacquired via tax deed by the same person who lost it (a redemption/
buy-back) must not flag as "repeat loser elsewhere" -- excluded by property
key, not just row identity.

100% offline. No network calls; pure re-organization of deed_chain +
owner_name + county + state + parcel_id/street_address, all already on
the board.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import structlog

from .models import Listing
from .name_normalize import is_entity, person_orderings

log = structlog.get_logger()

_LOSS_DOC_TYPES = (
    "TAX DEED", "SHERIFF'S DEED", "SHERIFF DEED",
    "TRUSTEE'S DEED", "TRUSTEE DEED", "SUBSTITUTE TRUSTEE",
    "MASTER IN EQUITY", "MASTER'S DEED", "CLERK'S DEED", "CLERK DEED",
)


def _surname_first_reading(owner_name: str):
    """Board owner_name is SURNAME-FIRST (see enrichment_owner_cluster.py's
    identical helper, live-verified against real board data)."""
    orderings = person_orderings(owner_name)
    if not orderings:
        return None
    return orderings[1] if len(orderings) > 1 else orderings[0]


def _name_key(owner_name: str) -> tuple[str, str] | None:
    if not owner_name or is_entity(owner_name):
        return None
    person = _surname_first_reading(owner_name)
    if person is None or not person.given:
        return None
    return (person.surname, person.given[0])


def _property_key(li: Listing) -> str:
    if li.parcel_id:
        return f"pid:{li.parcel_id.strip().upper()}"
    if li.street_address:
        return f"addr:{li.street_address.strip().upper()}"
    return f"src:{li.source_url}"


def _is_loss_doc(doc_type: str | None) -> bool:
    if not doc_type:
        return False
    dt = doc_type.upper()
    return any(k in dt for k in _LOSS_DOC_TYPES)


def enrich_repeat_tax_loss(listings: Iterable[Listing]) -> dict:
    """Stamp raw['repeat_tax_loss'] on any listing whose current owner has a
    tax-sale/foreclosure-sale loss on a DIFFERENT board property. Never
    drops a lead; additive only."""
    listings = list(listings)
    stats = {"losses_indexed": 0, "tagged_rows": 0}

    # Pass 1: index loser names by (surname, given, county, state) -> the
    # property they lost + when + how.
    losers: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        dc = raw.get("deed_chain")
        if not isinstance(dc, dict):
            continue
        transfers = (dc.get("summary") or {}).get("distress_transfers") or []
        if not transfers:
            continue
        if not li.county or not li.state:
            continue
        county = li.county.replace(" County", "").strip().upper()
        state = li.state.upper()
        for t in transfers:
            if not isinstance(t, dict) or not _is_loss_doc(t.get("doc_type")):
                continue
            grantor = t.get("grantor") or dc.get("summary", {}).get("prior_owner")
            if not grantor:
                continue
            key = _name_key(grantor)
            if key is None:
                continue
            losers[(key[0], key[1], county, state)].append({
                "date": t.get("date"),
                "doc_type": t.get("doc_type"),
                "lost_property_key": _property_key(li),
                "lost_parcel_id": li.parcel_id,
                "lost_source": li.source,
            })
            stats["losses_indexed"] += 1

    if not losers:
        return stats

    # Pass 2: match every CURRENT owner against the loser index, excluding
    # the property they lost (a redemption/buy-back of the same parcel is
    # not "still holds ANOTHER property").
    for li in listings:
        if not li.owner_name or not li.county or not li.state:
            continue
        key = _name_key(li.owner_name)
        if key is None:
            continue
        county = li.county.replace(" County", "").strip().upper()
        state = li.state.upper()
        candidates = losers.get((key[0], key[1], county, state))
        if not candidates:
            continue
        this_property = _property_key(li)
        other_losses = [c for c in candidates if c["lost_property_key"] != this_property]
        if not other_losses:
            continue
        other_losses.sort(key=lambda c: c.get("date") or "", reverse=True)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["repeat_tax_loss"] = {
            "prior_losses": len(other_losses),
            "most_recent_loss_date": other_losses[0]["date"],
            "most_recent_loss_doc_type": other_losses[0]["doc_type"],
            "county": county,
            "state": state,
        }
        stats["tagged_rows"] += 1

    if stats["tagged_rows"]:
        log.info("repeat_tax_loss.done", **stats)
    return stats
