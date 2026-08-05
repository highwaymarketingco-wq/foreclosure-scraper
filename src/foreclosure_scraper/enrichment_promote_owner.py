"""Promote a recoverable owner into the empty owner_name field.

The GIS/mailing enrichers stash the current tax-record owner in raw['owner_mailing']['owner']
and raw['gis']['owner'] but deliberately never overwrite owner_name (to avoid clobbering a parsed
foreclosure-defendant name). That leaves ~343 leads with a BLANK owner_name even though the owner
is sitting right there — which blocks mailing labels, voter-phone matching, ROD name search, and
skip-trace links downstream.

This enricher fills owner_name ONLY when it is currently empty, preferring the tax/mailing owner
(most authoritative for who to contact) over the GIS parcel owner. Tagged with the source so the
provenance is auditable. Must run AFTER owner_mailing/gis and BEFORE voter_phone + gaston_rod so
those consume the promoted names.
"""
from __future__ import annotations

from .enrichment_owner_mailing import mailing_dict


def _cand(li) -> str | None:
    r = li.raw if isinstance(li.raw, dict) else {}
    gis = r.get("gis")
    gis = gis if isinstance(gis, dict) else {}
    for src in (mailing_dict(r).get("owner"), gis.get("owner")):
        if isinstance(src, str) and len(src.strip()) > 2:
            return src.strip()
    return None


def enrich_promote_owner(listings) -> dict:
    promoted = 0
    for li in listings:
        if getattr(li, "owner_name", None):
            continue
        cand = _cand(li)
        if cand:
            li.owner_name = cand
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["owner_name_source"] = "promoted_tax_gis"
            promoted += 1
    return {"promoted": promoted}
