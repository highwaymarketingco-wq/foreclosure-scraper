"""Surface ONE display-ready last-sale fact per lead: raw['last_sale'] = {date, amount, basis, source}.

The pieces are usually present but scattered (recorded GIS sale, county CAMA sale date, assessor market
value) so the dashboard shows nothing. This assembles the best available, honestly labeled:
  basis 'recorded_sale'  — a real recorded sale amount + date (GIS deed / CAMA sale)
  basis 'assessor_value' — sale DATE known but price isn't; we show the county MARKET value as of it
  basis 'date_only'      — only a sale date is known
So the operator at least sees "last sold ~2022-05-06, ~$315,000 (assessor value)" instead of nothing.
"""
from __future__ import annotations

import re


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
        return f if f > 1000 else None
    except (TypeError, ValueError):
        return None


def _date(v) -> str | None:
    s = str(v or "")
    m = re.search(r"(19|20)\d\d[-/]\d{1,2}[-/]\d{1,2}", s)
    if m:
        return m.group(0).replace("/", "-")[:10]
    m = re.search(r"(19|20)\d\d", s)            # year-only fallback
    return m.group(0) if m else None


def enrich_last_sale(listings) -> dict:
    stats = {"set": 0, "recorded": 0, "assessor_value": 0, "date_only": 0}
    for li in listings:
        if not isinstance(li.raw, dict):
            continue
        raw = li.raw
        gis_ls = (raw.get("gis") or {}).get("last_sale") or {}
        cama = raw.get("cama") or {}
        out = None

        # 1) recorded GIS sale (real amount + date) — best
        g_amt, g_dt = _num(gis_ls.get("amount")), _date(gis_ls.get("date"))
        if g_amt and g_dt:
            out = {"date": g_dt, "amount": g_amt, "basis": "recorded_sale",
                   "source": gis_ls.get("source") or "gis"}
            stats["recorded"] += 1
        else:
            # 2) CAMA sale date (+ amount if present)
            c_dt = _date(cama.get("last_sale_date"))
            c_amt = _num(cama.get("last_sale_amount") or cama.get("last_sale_price"))
            if c_dt and c_amt:
                out = {"date": c_dt, "amount": c_amt, "basis": "recorded_sale", "source": "cama"}
                stats["recorded"] += 1
            elif c_dt and _num(li.market_value):
                # sale date known, price not — show the county MARKET value, labeled honestly
                out = {"date": c_dt, "amount": _num(li.market_value), "basis": "assessor_value",
                       "source": "cama+assessor"}
                stats["assessor_value"] += 1
            elif c_dt:
                out = {"date": c_dt, "amount": None, "basis": "date_only", "source": "cama"}
                stats["date_only"] += 1

        if out:
            raw["last_sale"] = out
            stats["set"] += 1
    return stats
