"""vacant_structure (condemned), scrapers/counties_nc/rocky_mount_blight_survey.py's own
"dilapidated" layers (Edgecombe, Nash): is the parcel still on the city planning consultant's
2025 survey's dilapidated layer today?

WHY THIS EXISTS: see condemned_adl.py's docstring for the full 2026-11-16 round-6 gap-matrix
investigation this is part of. This is the SECOND-largest slice of `condemned`'s gap (209 of
1,906 rows live-sampled 2026-11-16: Edgecombe 121, Nash 88) and, despite shipping its rows under
the SAME `counties_generic.arcgis_distress.<slug>` source-tag family every
arcgis_distress_layers.py row uses (`rocky_mount_blight_survey.py`'s own module docstring: "rows
ship under the counties_generic.arcgis_distress. family prefix that main.DATELESS_OK_SOURCES
already admits"), it is NOT an arcgis_distress_layers.LAYERS entry at all -- confirmed by reading
that registry directly, zero slug match -- so condemned_adl.py's generic Layer-registry lookup
correctly does not, and should not, claim it. A separate, dedicated module for a separate,
standalone scraper, same as this project's existing one-module-per-real-producer convention.

THE SOURCE (live-checked 2026-11-16): six public ArcGIS Online FeatureServer layers published
by the city's planning consultant (owner `tpursley_colliersgis`), confirmed anonymous/no-login/
no-CAPTCHA by the scraper's own module docstring (2026-10-13 attachments audit: `hasAttachments:
false` on all six). Only the two "dilapidated" layers matter to THIS signal -- the scraper's own
`to_listing()` sets `raw['condemned']=True` only `if "dilapidated" in classes`, never for
"deteriorated" (-> `raw['distressed']` only) or "vacant_boarded" (-> `raw['vacancy']`). Edgecombe
124 rows, Nash 92, live-counted 2026-11-16 (near-identical to the scraper's own 2026-10-07 counts
of 124/92 in its module docstring -- a STATIC one-time 2025 survey, confirmed unchanged since).

MATCHING mirrors the scraper's OWN `parcel_of()`/`_key()` exactly: PARNO (the county's native
parcel id, which is also the row's own `parcel_id`), falling back to ALTPARNO, falling back to
the normalized SITEADD -- never a different rule. Live-verified 2026-11-16 on two real sampled
rows per county (Edgecombe PARNO "3759-86-6196" -> SITEADD "806 LONG AVE"; Nash PARNO "027989"
-> SITEADD "218 N TILLERY ST"): both still present, unchanged, on today's live layer.

ONE LOAD PER LAYER PER SWEEP RUN via `_arcgis_layer.layer_for()` -- each layer is small (124/92
rows, live-counted), the same "cache the whole layer, never a per-row query" choice
code_enforcement_adl.py already makes for layers this size (contrast condemned_spartanburg.py/
condemned_greenwood.py, whose county-wide CAMA rolls are two orders of magnitude bigger and use
a targeted per-row query instead for exactly that reason).

NO STATUS FIELD. Unlike code_enforcement's case layers, a dilapidated-survey row carries no
open/closed lifecycle at all -- being ON the layer IS the claim, the same "a COMPLETE fresh
reload no longer carrying the row is itself the end of the claim" principle
code_enforcement_adl.py's own docstring documents for Durham's `durham_open_code_violations`
(a case dropped from that feed once resolved, never flagged closed in place). This is a STATIC
survey the scraper's own docstring says to "re-check... each quarter", so an address dropping
off between re-publications is the only way this ever stops being true.

VERDICTS: confirmed (still on the layer), stale (was on the layer, the layer has been RE-
PUBLISHED since the row was first seen -- i.e. `layer_data_last_edit` is newer than the row's own
`first_seen` -- and it is gone now: a genuine removal, not merely "never looked again"), refuted
((kept for symmetry with the other `condemned` verifiers' vocabulary, but not reachable here: a
row this module `applies()` to was BY DEFINITION produced by reading this very layer, so an
address missing on a layer that has never been updated since cannot mean "never belonged" --
see UNCONFIRMED below), unconfirmed (the layer failed or came back incomplete, the row has no
parcel id AND no numbered address, or the row is missing from a layer that has NOT been
republished since the row was first seen -- the conservative "not re-checkable yet" answer,
since a 2025 one-time survey's own publisher could simply not have touched it).

TTL 60 days, retry 14 -- a quarterly-cadence static survey; checking more often than the
publisher itself re-surveys would only ever re-confirm the same answer.

GOVERNS: deliberately omitted, same reasoning as condemned_adl.py's docstring.

EVIDENCE: the layer's own fetch/health evidence, the matched PARNO/ALTPARNO or SITEADD, and
whether the layer has been republished since the row was first seen -- no field beyond
PARNO/ALTPARNO/SITEADD (never OWNNAME/MAILADD/MCITY/MSTATE/MZIP, the scraper's own owner-mailing
columns).
"""
from __future__ import annotations

from datetime import date, timezone
from typing import Any, NamedTuple, Optional

from ..core import VerificationResult, parse_ts, result
from . import _arcgis_layer as agl

SIGNAL = "vacant_structure"
VERSION = "v1"
TTL_DAYS = 60
RETRY_DAYS = 14
ROW_SOURCE = "counties_generic.arcgis_distress.rocky_mount_blight_survey_2025"
SOURCE = "Rocky Mount NC 2025 dilapidated-parcels survey (ArcGIS Online)"
MAX_CASES_IN_EVIDENCE = 8
_NAME = __name__.rsplit(".", 1)[-1]

_BASE = "https://services.arcgis.com/mmindpmdbSZXPVNc/arcgis/rest/services/"


class _Layer(NamedTuple):
    county: str
    url: str


#: the two "dilapidated" layers -- rocky_mount_blight_survey.py's own LAYERS tuple, filtered to
#: klass=="dilapidated" (the only class this signal reads). Hardcoded rather than imported live:
#: unlike arcgis_distress_layers.LAYERS (a shared, frequently-extended registry), this scraper's
#: own LAYERS is a fixed, one-time 2025 survey's six URLs, never added to since; importing the
#: module merely to read a tuple that has not changed would cost a full scraper-stack import for
#: no benefit condemned_adl.py's live-registry reasoning actually buys here.
_LAYERS: dict[str, _Layer] = {
    "edgecombe": _Layer("Edgecombe", _BASE + "Edgecombe_Dilapidated_Parcels_2025/FeatureServer/1"),
    "nash": _Layer("Nash", _BASE + "Nash_Dilapidated_Parcels_2025/FeatureServer/1"),
}
_FIELDS = "PARNO,ALTPARNO,SITEADD"


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def applies(row: dict) -> bool:
    if not _raw(row).get("condemned"):
        return False
    if row.get("source") != ROW_SOURCE:
        return False
    return str(row.get("county") or "").strip().lower() in _LAYERS


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


def _clean(v: Any) -> Optional[str]:
    s = str(v).strip() if v not in (None, "") else None
    return s or None


def _index(snap) -> dict:
    """{parno-or-altparno-or-lower-siteadd: attrs}, built once per layer snapshot."""
    idx = snap.cache.get("by_key")
    if idx is None:
        by_key: dict = {}
        for a in snap.rows:
            for k in (_clean(a.get("PARNO")), _clean(a.get("ALTPARNO"))):
                if k:
                    by_key.setdefault(k, a)
            site = _clean(a.get("SITEADD"))
            if site:
                by_key.setdefault("a:" + site.lower(), a)
        idx = snap.cache["by_key"] = by_key
    return idx


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    county = str(row.get("county") or "").strip().lower()
    lay = _LAYERS.get(county)
    ev: dict[str, Any] = {"county": row.get("county")}
    if lay is None:
        ev["reason"] = "unknown_county"
        return _res("unconfirmed", ev)

    pid = _clean(row.get("parcel_id"))
    site = _clean(row.get("street_address"))
    if not pid and not site:
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)

    snap = await agl.layer_for(client, lay.url, out_fields=_FIELDS, order_by="PARNO")
    ev.update(snap.evidence())
    if not snap.complete:
        ev["reason"] = snap.health
        return _res("unconfirmed", ev)

    idx = _index(snap)
    match = None
    if pid:
        match = idx.get(pid)
    if match is None and site:
        match = idx.get("a:" + site.lower())
    if match is not None:
        ev["matched"] = {"PARNO": match.get("PARNO"), "ALTPARNO": match.get("ALTPARNO"),
                        "SITEADD": match.get("SITEADD")}
        return _res("confirmed", ev)

    # Not found. A one-time survey's own publisher may simply not have touched this layer
    # since the row was first seen -- that is "not re-checkable yet" (unconfirmed), never a
    # claim this module can prove false on its own. Only a layer republished SINCE first_seen
    # and still missing the row is a genuine removal (stale).
    republished = False
    first_seen = parse_ts(row.get("first_seen"))
    last_edit = parse_ts(snap.data_last_edit) if snap.data_last_edit else None
    if first_seen and last_edit:
        fs = first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=timezone.utc)
        le = last_edit if last_edit.tzinfo else last_edit.replace(tzinfo=timezone.utc)
        republished = le > fs
    if republished:
        ev["reason"] = "dropped_off_layer"
        return _res("stale", ev)
    ev["reason"] = "not_on_layer_yet_unrepublished"
    return _res("unconfirmed", ev)
