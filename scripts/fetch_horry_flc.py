#!/usr/bin/env python3
"""Horry County Forfeited Land Commission list -> board leads.

WHAT FLC IS
    A property that went to tax sale and did NOT sell reverts to the county's
    Forfeited Land Commission. The county then holds it and will take a bid. That
    is not a lead to chase — it is inventory that can be bought, which is exactly
    the buy-cheap/clear-title/sell-as-is line.

WHY THIS SOURCE
    Horry publishes NO public parcel layer (114 services checked, none carry
    parcels with addresses), so its 4,191 board rows sit at 41% addresses with no
    value. This layer is small but it is real, priced inventory in the same county.

FIELD NOTE
    FLC_Bid_Amount is a STRING with thousands separators and stray whitespace
    (' 4,942.85'). Parsed to float; a row whose bid will not parse keeps the raw
    string in `raw` and leaves opening_bid null rather than guessing a number.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402
from foreclosure_scraper.web_artifact import _to_dict  # noqa: E402

URL = ("https://services1.arcgis.com/If0JkGr8ABreBTuS/arcgis/rest/services/"
       "DelinquentTaxParcels2025/FeatureServer/0/query")
OUT = REPO / "logs" / "horry_flc.json"


def money(v) -> float | None:
    if v is None:
        return None
    s = re.sub(r"[^\d.]", "", str(v))
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def main() -> int:
    r = httpx.get(URL, params={"where": "1=1", "outFields": "*",
                               "returnGeometry": "false", "f": "json"}, timeout=40)
    r.raise_for_status()
    feats = r.json().get("features", [])
    now = datetime.utcnow()
    out: list[Listing] = []
    unparsed = 0
    for f in feats:
        a = f.get("attributes", {})
        pin = str(a.get("PIN_1") or "").strip()
        owner = (a.get("Owner_Name") or a.get("OwnerName") or "").strip()
        if not pin and not owner:
            continue
        bid = money(a.get("FLC_Bid_Amount"))
        if bid is None and a.get("FLC_Bid_Amount"):
            unparsed += 1
        out.append(Listing(
            source="counties_sc.horry_flc",
            source_url="https://www.horrycountysc.gov/departments/delinquent-tax/",
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Horry",
            parcel_id=pin or None,
            owner_name=owner or None,
            opening_bid=bid,
            description=("Forfeited Land Commission — county-held after an unsold tax "
                         f"sale. Item {a.get('Item_Number')}. "
                         f"{(a.get('Description') or '').strip()}").strip(),
            first_seen=now, last_seen=now,
            raw={"horry_flc": {k: v for k, v in a.items()
                               if k not in ("Shape__Area", "Shape__Length", "OBJECTID")}},
        ))
    OUT.write_text(json.dumps([_to_dict(li) for li in out]))
    bids = [li.opening_bid for li in out if li.opening_bid]
    print(f"Horry FLC: {len(out)} properties -> {OUT}")
    if bids:
        bids.sort()
        print(f"  bids parsed {len(bids)} | median ${bids[len(bids)//2]:,.0f} "
              f"| min ${bids[0]:,.0f} | max ${bids[-1]:,.0f}")
    if unparsed:
        print(f"  {unparsed} bid strings would not parse — left null, raw kept")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
