"""Georgetown County SC assessor card (qPublic / Schneider) — heated sqft via PLAIN curl_cffi.

Unlike the render-class qPublic counties (Spartanburg/Oconee/Pickens/Union, which need the
stealth browser), Georgetown's card returns its data to a plain chrome-impersonated GET —
live-verified 2026-06-29 ("Finished Area 2336"). Keyed directly by the dashed parcel id, which
is the qPublic KeyValue our board already carries (e.g. 42-0171-011-00-00). Net-new sqft for
the coastal Georgetown leads (previously no adapter).

  GET .../Application.aspx?AppID=863&LayerID=16169&PageTypeID=4&PageID=7180&KeyValue={parcel}
  -> "Finished Area  2336" (heated/finished living area) + "Year Built 1996"
"""
from __future__ import annotations

import re

from .base import CardResult, money

try:
    from curl_cffi.requests import AsyncSession
except Exception:  # pragma: no cover
    AsyncSession = None

CARD = ("https://qpublic.schneidercorp.com/Application.aspx"
        "?AppID=863&LayerID=16169&PageTypeID=4&PageID=7180&KeyValue={key}")
SOURCE_URL = "https://qpublic.schneidercorp.com/"
COUNTY = ("SC", "Georgetown")   # auto-discovery key

_SQFT = re.compile(r"(?:Finished Area|Total Finished Living Area|Heated\s*Sq\w*)\D{0,18}([0-9][0-9,]{2,6})", re.I)
_YEAR = re.compile(r"Year Built\D{0,12}(\d{4})", re.I)


async def fetch(li) -> CardResult | None:
    if AsyncSession is None:
        return None
    key = (getattr(li, "parcel_id", "") or "").strip()
    if not key or "-" not in key:   # qPublic KeyValue is the dashed parcel id
        return None
    try:
        async with AsyncSession() as s:
            r = await s.get(CARD.format(key=key), impersonate="chrome", timeout=20)
    except Exception:
        return None
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text or ""))
    res = CardResult(source_url=SOURCE_URL)
    m = _SQFT.search(txt)
    if m:
        sf = money(m.group(1))
        if sf and sf > 100:        # ignore stray small numbers / story counts
            res.living_sqft = sf
            res.living_sqft_is_heated = True
    y = _YEAR.search(txt)
    if y:
        yb = int(y.group(1))
        if 1700 <= yb <= 2026:
            res.year_built = yb
    return res if res.has_fill() else None
