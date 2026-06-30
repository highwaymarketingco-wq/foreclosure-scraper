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


def enrich_court_owner_verify(listings) -> dict:
    stats = {"checked": 0, "mismatch": 0, "stripped": 0}
    for li in listings:
        src = li.source or ""
        lt = li.listing_type.value if getattr(li, "listing_type", None) and hasattr(li.listing_type, "value") else ""
        is_court = src.startswith("national.courtlistener") or lt in ("lis_pendens", "bankruptcy")
        if not is_court:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
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
