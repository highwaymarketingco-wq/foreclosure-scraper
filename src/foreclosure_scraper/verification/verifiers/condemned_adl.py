"""vacant_structure (condemned), every scrapers/counties_generic/arcgis_distress_layers.py
Layer whose own `condemned=True` opt-in is set: does the matched address still read as
condemned on a freshly, fully reloaded copy of that exact layer today?

WHY THIS EXISTS (2026-11-16 round-6 gap-matrix sweep of `condemned`'s `built-not-verified`
cells -- see [[project_verify_layer_survey_2026-11-16]] Finding 1 and
[[project_condemned_gap_not_a_bug]]/[[project_gaston_condemned_investigation_2026-10-23]] for
the prior research this builds on). `condemned` had exactly ONE registered verifier before this
one (vacant_structure_hendersonville.py), hard-scoped to NC Henderson's own frozen register by a
state+county+source check. Every OTHER real producer's `raw['condemned']=True` rows -- built,
ran, a genuine case on the board -- fell through to `built-not-verified`, the same gap shape
code_enforcement_adl.py closed for the sibling `code_enforcement` signal the same day (read that
module's docstring for the fuller methodology this one reuses).

WHICH ROWS (applies). `raw['condemned']` is true AND the row's own top-level `source` is
`counties_generic.arcgis_distress.<slug>` for a `slug` that `_layers()` names below -- built
FRESH from `arcgis_distress_layers.LAYERS`'s own `condemned=True` entries every call, never a
hardcoded duplicate a future opt-in could silently outgrow (the same discipline
code_enforcement_adl.py's own `_layers()` already applies on this identical registry). Unlike
`code_enforcement`, `raw['condemned']` is a BARE boolean with no nested source/has_open wrapper
of its own (see vacant_structure_hendersonville.py's own docstring: "raw['condemned'] ... bare
flag with no provenance"), so the row's own top-level `source` field is the only identity this
module has to key on.

THE ONLY LAYER TODAY: `rockhill_code_demolition` (SC York, OpenCodeEnforcementCases/MapServer/5,
17 live rows counted 2026-11-16). `process="demolition_permit"`, `detail="Status"` -- the SAME
`Status` column, and the SAME "In Violation" (open) / closed-prefix convention,
code_enforcement_adl.py's own `_STATUS`/`_is_closed` already live-verified 2026-11-16 for
`rockhill_code_housing` on the same city service. Reused here rather than re-derived.

MATCHING: the row's street address, normalized, against the layer's own `situs` field
(`AddressText`) -- the identical shape `_to_listing()` builds (`case_id = parcel or situs`, and
no current `condemned=True` Layer sets `parcel=`, so situs is the only real key here too; see
code_enforcement_adl.py's own MATCHING section for the fuller reasoning, unchanged here).

VERDICTS: confirmed (still on the layer with an open-reading status, or a status this module
does not recognize -- the same conservative "found == still open" fallback
code_enforcement_adl.py uses for a future status vocabulary it has not been taught yet), stale
(still on the layer but every matched case now reads closed), refuted (a COMPLETE fresh reload
of the layer no longer carries this address at all), unconfirmed (the layer failed or came back
incomplete, or the row has no numbered street address).

TTL 30 days, retry 7 -- a county demolition-permit list is not a daily feed; matches
vacant_structure_hendersonville.py's own cadence for this identical signal rather than
code_enforcement_adl.py's tighter 14-day one (that module's layers are active violation
caseloads; a condemnation/demolition order changes far less often).

GOVERNS: deliberately omitted. `raw['condemned']` carries no per-source provenance to clear
selectively on a merged row (see vacant_structure_hendersonville.py's own GOVERNS docstring,
which excludes `condemned` from its tuple for exactly this reason even though it governs
`vacant_structure`/`code_enforcement` from the identical register) -- the risk a stale/refuted
verdict here could silently clear ANOTHER source's bare `raw['condemned']` on the same parcel is
real and this module has no way to scope around it, so it does not try.

EVIDENCE: the matched slug, the layer's own fetch/health evidence, and per matched case (at most
8) the raw status string and an open flag -- no field beyond the layer's own already-reviewed
`fields` tuple.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _arcgis_layer as agl

SIGNAL = "vacant_structure"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "arcgis_distress_layers.py condemned family (per-county/city ArcGIS)"
MAX_CASES_IN_EVIDENCE = 8
_NAME = __name__.rsplit(".", 1)[-1]

#: the DATELESS_PREFIX literal every arcgis_distress_layers.py row's top-level `source` carries
#: (scrapers/counties_generic/_layer_kit.py's own constant -- not imported, to keep this module
#: import-light the same way code_enforcement_adl.py keeps arcgis_distress_layers.py itself
#: lazy; the value is a stable, already-public string, not a guess).
_PREFIX = "counties_generic.arcgis_distress."

_CLOSED_PREFIXES = ("closed", "resolved", "void")
_CLOSED_EXACT = ("no violation", "not in violation")


def _is_closed(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s.startswith(_CLOSED_PREFIXES) or s in _CLOSED_EXACT


def _adl():
    """arcgis_distress_layers.py, imported on first use (the registry imports every verifier;
    the full scraper stack must not load in just to answer applies())."""
    from ...scrapers.counties_generic import arcgis_distress_layers as m
    return m


def _layers() -> dict[str, Any]:
    """slug -> Layer: every live `condemned=True` entry, rebuilt from the registry every call
    (cheap: a tuple of ~30 NamedTuples) so a future opt-in is covered the next time this is
    called, never a duplicate list here to fall out of date."""
    return {lay.slug: lay for lay in _adl().LAYERS if lay.condemned}


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _slug(row: dict) -> Optional[str]:
    src = str(row.get("source") or "")
    return src[len(_PREFIX):] if src.startswith(_PREFIX) else None


def applies(row: dict) -> bool:
    if not _raw(row).get("condemned"):
        return False
    slug = _slug(row)
    return bool(slug) and slug in _layers()


def _addr(v: Any) -> Optional[str]:
    from ...models import _normalize_addr
    from ..core import _house_numbered
    a = _normalize_addr(str(v)) if v not in (None, "") else None
    return a if a and _house_numbered(a) else None


def _situs(a: dict, lay) -> Optional[str]:
    return _addr(a.get(lay.situs)) if lay.situs else None


def _index(snap, lay) -> dict:
    idx = snap.cache.get("by_addr")
    if idx is None:
        by_addr: dict = {}
        for a in snap.rows:
            s = _situs(a, lay)
            if s:
                by_addr.setdefault(s, []).append(a)
        idx = snap.cache["by_addr"] = by_addr
    return idx


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    slug = _slug(row) or ""
    lay = _layers().get(slug)
    ev: dict[str, Any] = {"matched_slug": slug or None}
    if lay is None:
        ev["reason"] = "unknown_source"
        return _res("unconfirmed", ev)

    addr = _addr(row.get("street_address"))
    if not addr:
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)

    snap = await agl.layer_for(client, lay.url, out_fields=",".join(lay.fields),
                               order_by=lay.fields[0])
    ev.update(snap.evidence())
    if not snap.complete:
        ev["reason"] = snap.health
        return _res("unconfirmed", ev)

    rows = _index(snap, lay).get(addr, [])
    if not rows:
        ev["reason"] = "no_case_on_layer"
        return _res("refuted", ev)

    cases = []
    for a in rows[:MAX_CASES_IN_EVIDENCE]:
        status = a.get(lay.detail) if lay.detail else None
        status = str(status) if status not in (None, "") else None
        is_open = True if status is None else not _is_closed(status)
        cases.append({"status": status, "open": is_open})
    ev["cases"] = cases
    ev["cases_matched"] = len(rows)
    if any(c["open"] for c in cases):
        return _res("confirmed", ev)
    ev["reason"] = "case_closed"
    return _res("stale", ev)
