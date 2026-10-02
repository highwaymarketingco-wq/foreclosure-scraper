"""entity_type enricher -- computes owner entity type ONCE per listing and persists it.

GAP: owner entity type (individual vs. LLC/corp vs. trust vs. estate vs.
government) is computed ON THE FLY by roughly 10 different call sites across
this codebase (grep for ``is_entity(`` -- enrichment_repeat_tax_loss.py,
sc_parcel_mailing.py, enrichment_sc_phone.py, deed_index.py,
enrichment_sc_divorce.py, enrichment_resolve_name_to_property.py,
enrichment_notice_service_defect.py, enrichment_owner_cluster.py, plus the
one-off scripts/reset_divorce_wrong_order.py and
scripts/reset_divorce_slow_rounds.py). All ten import and call the SAME
name_normalize.is_entity() -- confirmed 2026-10-02, no drift in the base
check itself. But the result was never saved anywhere: every one of those
sites recomputes it from li.owner_name, for the same listing, independently,
every time it is needed. This enricher computes it ONCE per listing, using
name_normalize.classify_entity_type() (the richer individual/entity/trust/
estate/government/unknown classifier built on that SAME is_entity() marker
set, never a reimplementation of it), and persists raw['entity_type'] so a
future consumer can read instead of recompute.

NOT a backfill: this stamps whatever listings the CURRENT run passes through
this phase (new rows, and any existing board row this run's merge carries
into `enriched`). A row this code has never run over keeps raw['entity_type']
absent until a future run reaches it -- backfilling the rest of the published
board is explicitly separate, out-of-scope work (see docs/HANDOFF.md).

WIRING NOTE (main.py) -- WHY THIS PHASE SITS WHERE IT DOES:
owner_name is mutated by several EARLIER enrichers (enrichment_arcgis.py,
enrichment_gis_attrs.py, enrichment_lrcpwa_parcel.py,
enrichment_ncpts_lrc.py, enrichment_doc_ocr.py, enrichment_promote_owner.py,
enrichment_court_owner_verify.py -- the last of these runs latest of all of
them). This phase is wired AFTER every one of those so the persisted value
reflects the FINAL owner_name for the run, not a value a later phase then
changes out from under it.

Two of the ten call sites -- enrichment_sc_divorce.py and
enrichment_resolve_name_to_property.py -- run EARLIER in main.py's phase
order than enrich_court_owner_verify, so a persisted field from THIS phase
would not exist yet (or would reflect a stale owner_name) when they run. They
keep computing is_entity() fresh in place for exactly that reason: a genuine
timing dependency, not an oversight. The other candidates were checked too
and NOT switched over to reading the persisted field, each for its own
documented reason (generic name parameter rather than a specific listing's
owner_name, a different/combined field such as defendant-or-owner_name, a
Party object from deed parsing rather than a Listing at all, or a standalone
script that reprocesses already-published board rows where this field may
not exist per the no-backfill note above) -- see docs/HANDOFF.md for the
full call-site-by-call-site breakdown. enrichment_owner_cluster.py's
_cluster_key is the one call site actually switched to prefer the persisted
field (falling back to is_entity() when it is absent, so a standalone/offline
call into that function -- e.g. the dry-run its own docstring describes --
still works unchanged).
"""
from __future__ import annotations

from typing import Iterable

import structlog

from .models import Listing
from .name_normalize import classify_entity_type

log = structlog.get_logger()


def enrich_entity_type(listings: Iterable[Listing]) -> dict:
    """Stamp raw['entity_type'] on every listing (even one with no owner_name,
    which still gets the informative 'unknown' value rather than leaving the
    key absent on some rows and present on others).

    Additive only -- never drops a lead. Idempotent and unconditional: it
    always (re)computes and overwrites, rather than skipping a row that
    already carries a value, because owner_name itself can change between
    runs (see module docstring) and a stale entity_type would be worse than
    the small recompute cost.
    """
    stats = {"individual": 0, "entity": 0, "trust": 0, "estate": 0,
              "government": 0, "unknown": 0, "tagged_rows": 0}
    for li in listings:
        entity_type = classify_entity_type(li.owner_name)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["entity_type"] = entity_type
        stats[entity_type] = stats.get(entity_type, 0) + 1
        stats["tagged_rows"] += 1
    return stats
