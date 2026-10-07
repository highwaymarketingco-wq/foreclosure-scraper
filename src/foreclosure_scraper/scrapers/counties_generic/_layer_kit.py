"""Small shared helpers for the single-purpose county/city ArcGIS layer scrapers added
2026-10-07 (docs/new_sources_2026-10-07_distress.md).

Leading underscore: the registry skips this module (it holds no scraper).

Every attribute bag read through :func:`fetch_attrs` goes through
``sensitive_fields.drop_sensitive`` before any caller sees it, and ``out_fields`` must be an
explicit list (``arcgis_webmap.query_features`` refuses ``*``).

DATELESS SOURCES: ``main._active_only`` drops a row with no ``sale_date`` unless its
``source`` is whitelisted in ``main.DATELESS_OK_SOURCES``. That set already admits the
whole ``counties_generic.arcgis_distress.<layer>`` family by prefix, which is what these
modules are (one county ArcGIS layer that IS the distress signal). :data:`DATELESS_PREFIX`
is that family's prefix, so a dateless lead from these modules reaches the board without
editing ``main.py``.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from ... import arcgis_webmap as agw
from ...sensitive_fields import drop_sensitive

DATELESS_PREFIX = "counties_generic.arcgis_distress."


def clean(v: Any) -> Optional[str]:
    """Whitespace-squashed text, or None for blank/None."""
    s = " ".join(str(v).split()) if v is not None else ""
    return s or None


def num(v: Any) -> Optional[float]:
    """A positive number from a numeric or '$1,234' string, else None."""
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def norm_addr(s: Optional[str]) -> str:
    return " ".join((s or "").lower().replace(",", " ").split())


def owner_mailing(owner: Optional[str], parts: Iterable[Any], mail_state: Any,
                  situs: Optional[str], parcel: Optional[str], home_state: str,
                  source: str) -> Optional[dict]:
    """The raw['owner_mailing'] block the rest of the pipeline reads (absentee and
    out-of-state flags). None when the layer carries no mailing line."""
    mailing = " ".join(b for b in (clean(p) for p in parts) if b) or None
    if not mailing:
        return None
    st = (clean(mail_state) or "").upper()[:2] or None
    return {
        "owner": owner,
        "mailing": mailing,
        "situs": situs,
        "parcel_id": parcel,
        "mail_state": st,
        "absentee": bool(situs and norm_addr(situs) not in norm_addr(mailing)),
        "out_of_state": bool(st and st != home_state),
        "source": source,
    }


async def fetch_attrs(http, layer_url: str, fields: Iterable[str], where: str = "1=1",
                      page: int = 1000) -> list[dict]:
    """Every row of one layer (paged), attribute dicts only, sensitive columns dropped."""
    rows = await agw.query_attributes(http, layer_url, out_fields=",".join(fields),
                                      where=where, page=page)
    return [drop_sensitive(a) for a in rows]
