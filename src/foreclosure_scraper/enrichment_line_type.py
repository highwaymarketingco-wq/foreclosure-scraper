"""Phone line-type / TCPA classification — turns the existing owner_phone set into a usable,
compliant call list.

Every owner_phone today is hardcoded line_type='unknown', so none can be confidently dialed. This
enricher does a FREE LERG lookup (localcallingguide.com xmlprefix, public, robots-allowed) per
NPA-NXX (deduped + cached), reads <company-type> (I=ILEC landline, W=wireless, C=CLEC), and routes:

  landline  -> tcpa_class 'callable'     (still DNC-scrub + 8am-9pm local; not an autodialer/cell)
  wireless  -> tcpa_class 'manual_only'  (no autodialer / no cold SMS without prior express consent)
  clec      -> tcpa_class 'manual_only'  (often VoIP/resold wireless -> treat conservatively)

Every number STAYS needs_dnc_scrub; this only adds routing, never relaxes compliance. No new lead
acquisition — it unlocks phones we already hold.
"""
from __future__ import annotations

import asyncio
import os
import re

from curl_cffi.requests import AsyncSession

# Cache survives the process so repeated runs (main + regenerate) don't re-hit the same prefixes.
_LERG_CACHE: dict[str, dict] = {}
_TYPE_MAP = {
    "I": ("landline", "callable"),    # ILEC incumbent landline
    "W": ("wireless", "manual_only"),
    "C": ("clec", "manual_only"),     # competitive LEC (frequently VoIP) -> conservative
}


def _npa_nxx(phone: str) -> tuple[str, str] | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return digits[:3], digits[3:6]


async def _lookup(session: AsyncSession, npa: str, nxx: str) -> dict:
    key = f"{npa}-{nxx}"
    if key in _LERG_CACHE:
        return _LERG_CACHE[key]
    out = {"line_type": "unknown", "tcpa_class": "manual_only", "carrier": None}
    try:
        r = await session.get(
            f"https://localcallingguide.com/xmlprefix.php?npa={npa}&nxx={nxx}",
            impersonate="chrome", timeout=20)
        if r.status_code == 200:
            body = r.text
            ct = re.search(r"<company-type>([^<]*)</company-type>", body)
            cn = re.search(r"<company-name>([^<]*)</company-name>", body)
            code = (ct.group(1).strip().upper() if ct else "")[:1]
            lt, tc = _TYPE_MAP.get(code, ("unknown", "manual_only"))
            out = {"line_type": lt, "tcpa_class": tc,
                   "carrier": (cn.group(1).strip() if cn and cn.group(1).strip() else None)}
    except Exception:  # noqa: BLE001
        pass
    _LERG_CACHE[key] = out
    return out


async def enrich_line_type(listings, concurrency: int = 6) -> dict:
    if os.environ.get("FORECLOSURE_LINE_TYPE", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_LINE_TYPE=0)"}
    targets = [li for li in listings
               if isinstance(li.raw, dict) and isinstance(li.raw.get("owner_phone"), dict)
               and li.raw["owner_phone"].get("line_type", "unknown") == "unknown"]
    stats = {"targets": len(targets), "landline": 0, "wireless": 0, "clec": 0, "unknown": 0}
    if not targets:
        return stats

    # Dedupe to unique NPA-NXX so we hit each prefix once.
    prefixes: dict[str, tuple[str, str]] = {}
    for li in targets:
        nn = _npa_nxx(li.raw["owner_phone"].get("phone", ""))
        if nn:
            prefixes[f"{nn[0]}-{nn[1]}"] = nn
    sem = asyncio.Semaphore(concurrency)

    async with AsyncSession() as session:
        async def _lk(nn: tuple[str, str]):
            async with sem:
                await _lookup(session, *nn)
        await asyncio.gather(*(_lk(nn) for nn in prefixes.values()))

    for li in targets:
        nn = _npa_nxx(li.raw["owner_phone"].get("phone", ""))
        res = _LERG_CACHE.get(f"{nn[0]}-{nn[1]}") if nn else None
        if not res:
            continue
        ph = li.raw["owner_phone"]
        ph["line_type"] = res["line_type"]
        ph["tcpa_class"] = res["tcpa_class"]
        if res.get("carrier"):
            ph["carrier"] = res["carrier"]
        stats[res["line_type"]] = stats.get(res["line_type"], 0) + 1
    stats["prefixes_looked_up"] = len(prefixes)
    return stats
