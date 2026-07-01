"""Board split — heavy detail-only raw keys go to an index-aligned sidecar.

listings.json must NOT carry the lazy keys (comps/vision/etc.); they belong in
listings_detail.json, aligned by array index (the dashboard's join). Card-scope
keys (grade/calc/distress_stack/sos_agent) must stay in listings.json or the
filters break.
"""
from __future__ import annotations

import json

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import write_artifact, LAZY_DETAIL_KEYS


def _lead(i: int, with_lazy: bool) -> Listing:
    raw = {
        "grade": {"overall": "B"},              # card-scope — must stay
        "calc": {"arv_expected": 100000 + i},   # card-scope — must stay
        "sos_agent": {"sosid": str(i)},         # card-scope — must stay
    }
    if with_lazy:
        raw["comps"] = [{"addr": f"{i} Main St", "price": 200000}]
        raw["vision"] = {"parsed": True, "blob": "x" * 50}
        raw["cama"] = {"heated_sqft": 1500}
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", owner_name=f"Lead {i} LLC", raw=raw)


def test_split_strips_lazy_from_listings_keeps_in_detail(tmp_path):
    leads = [_lead(0, True), _lead(1, False), _lead(2, True)]
    write_artifact(leads, {"notes": "test"}, docs_dir=tmp_path)

    listings = json.loads((tmp_path / "listings.json").read_text())
    detail = json.loads((tmp_path / "listings_detail.json").read_text())

    # index-aligned
    assert len(listings) == len(detail) == 3

    # no lazy key remains in the card payload; card-scope keys survive
    for rec in listings:
        raw = rec.get("raw") or {}
        assert not any(k in raw for k in LAZY_DETAIL_KEYS), raw.keys()
        assert "grade" in raw and "calc" in raw and "sos_agent" in raw

    # lazy data lives in the aligned sidecar for the leads that had it
    assert detail[0].get("comps") and detail[0].get("vision") and detail[0].get("cama")
    assert detail[1] == {}                       # lead 1 had no lazy keys
    assert detail[2].get("comps")

    # alignment: detail[i] belongs to listings[i]
    assert detail[0]["comps"][0]["addr"] == "0 Main St"
    assert detail[2]["comps"][0]["addr"] == "2 Main St"
