"""Court-lead owner verification — guards against a geo-snap stapling the WRONG property to a docket.

CourtListener / lis-pendens / bankruptcy leads carry a real docket DEFENDANT, but a low-precision
lat/lng on the docket can make parcel_from_geo snap to a NEIGHBOR's parcel, after which gis_attrs
overwrites owner_name with that stranger's name (e.g. defendant 'Roger Leonard Mason' -> snapped onto
the 'INMAN' parcel on Atlas Court). The result is a real case attached to the wrong house — which then
drives a wrong ARV, a wrong max bid, and outreach to the wrong person.

Fix: compare the GIS-resolved owner against the docket defendant's SURNAME. On a clear mismatch, strip
the mis-attached property (parcel / address / value / specs / gis owner), revert owner_name to the
defendant, and flag the lead so it reads as an unverified name-only court record instead of a vetted
lead. Conservative — only fires when the defendant's surname is absent from the owner string entirely.
Runs PRE-valuation so the stripped lead recomputes to 'insufficient data' rather than a bogus ARV.

STALE-FLAG-ON-MERGE bug (found + fixed 2026-10-03, live-verified on the real board): this function
only ever WRITES raw['owner_mismatch']; nothing ever cleared it. Listing.merge() deep-merges `raw`
(keeps every key either side has) but only overwrites owner_name/defendant/listing_type/source when
the PRIMARY side's own value is falsy (models.py's fill-only rule) — so once a court-sourced listing
this function already flagged and stripped (owner_name reverted to the docket defendant, parcel_id
cleared) later merges with a different, non-court record for the "same" property (matched by address/
situs once parcel_id was cleared, not uncommon — e.g. a Buncombe tax-lien `arcgis_distress` row), the
merged listing keeps the TAX record's own owner_name/defendant/listing_type (none of them falsy, so
none get overwritten) but ALSO keeps the orphaned `raw['owner_mismatch']` key from the old court-side
`raw`. Live-confirmed example: a merged row published as `tax_lien`/`counties_generic.arcgis_distress.
buncombe_unpaid_bills` with owner_name == defendant == "BUCKNER (LE), CHRISTOPHER" still carried
`owner_mismatch = {"defendant_surname": "craft", "snapped_owner": "VALDEZ MELISSA KATRINA;VALDEZ JOE"}`
— a flag naming two people with no relation to the row's current identity, surfaced verbatim as a
MEDIUM red flag by scripts/build_red_flags.py. 58 of 426 live board rows carrying this function's own
flag shape (2 keys, no 'source') are on a row that no longer qualifies as `is_court` — pure orphaned
noise inflating the tracked `owner_mismatch` coverage metric. Fixed: when a listing no longer qualifies
as court-sourced, this function now clears its OWN flag shape (never promote_ptscloud_block.py's, which
always carries a 'source' key and is a separate, still-valid mechanism) instead of silently skipping it.
"""
from __future__ import annotations

import re

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|esq|md|deceased|life\s*estate|estate|trustee|et\s*al|aka|"
                     r"individually|trust|llc|inc|corp)\b\.?", re.I)


def _toks(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z]{2,}", s or "")]


def _def_surname(name: str) -> str:
    """Best-effort surname of a docket defendant. 'Williams, Joseph' -> williams;
    'Roger Leonard Mason Jr' -> mason. Empty if undeterminable."""
    name = _SUFFIX.sub(" ", name or "")
    if "," in name:
        toks = _toks(name.split(",")[0])      # 'Last, First' -> Last
    else:
        toks = _toks(name)                     # 'First Middle Last' -> last token
    return toks[-1] if toks else ""


def _clear_stale_flag(li, raw: dict) -> bool:
    """Drop an orphaned flag THIS function wrote while `li` was still court-sourced, now that a
    merge has moved it onto a different, non-court record (see module docstring). Only ever
    touches our own shape (no 'source' key) — promote_ptscloud_block.py's Henderson PTS flag
    always carries one and must survive untouched."""
    om = raw.get("owner_mismatch")
    if not (isinstance(om, dict) and "source" not in om):
        return False
    raw.pop("owner_mismatch", None)
    flags = raw.get("qa_flags")
    if isinstance(flags, list) and "court_owner_mismatch" in flags:
        flags.remove("court_owner_mismatch")
    li.raw = raw
    return True


def enrich_court_owner_verify(listings) -> dict:
    stats = {"checked": 0, "mismatch": 0, "stripped": 0, "stale_cleared": 0}
    for li in listings:
        src = li.source or ""
        lt = li.listing_type.value if getattr(li, "listing_type", None) and hasattr(li.listing_type, "value") else ""
        is_court = src.startswith("national.courtlistener") or lt in ("lis_pendens", "bankruptcy")
        raw = li.raw if isinstance(li.raw, dict) else {}
        if not is_court:
            if _clear_stale_flag(li, raw):
                stats["stale_cleared"] += 1
            continue
        owner = li.owner_name or (raw.get("gis") or {}).get("owner") or ""
        defn = li.defendant or ""
        ds = _def_surname(defn)
        ot = set(_toks(owner))
        if not (ds and ot and defn and owner):
            continue
        stats["checked"] += 1
        if ds in ot:
            continue  # defendant surname present in the owner string -> consistent, keep
        # Mismatch: the on-title owner is a different family than the docket party.
        stats["mismatch"] += 1
        raw["owner_mismatch"] = {"defendant_surname": ds, "snapped_owner": owner[:80]}
        flags = raw.setdefault("qa_flags", [])
        if isinstance(flags, list) and "court_owner_mismatch" not in flags:
            flags.append("court_owner_mismatch")
        # Strip the mis-attached property -> honest name-only court record (the defendant + docket).
        li.owner_name = re.sub(r"\s+", " ", defn).strip()[:120] or None
        li.parcel_id = None
        li.street_address = None
        li.market_value = None
        li.assessed_value = None
        li.living_sqft = None
        if isinstance(raw.get("gis"), dict):
            for k in ("owner", "last_sale"):
                raw["gis"].pop(k, None)
        li.raw = raw
        stats["stripped"] += 1
    return stats
