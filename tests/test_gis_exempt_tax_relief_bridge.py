"""2026-10-02 breadth fix: raw['gis_exempt'] -> raw['tax_relief'] bridge.

enrichment_gis_attrs.py's `apply_gis_attrs` has, since this field was added,
recognized a real statutory elderly/disabled/blind exemption code (ELD/DIS/
BLD, live-verified against Buncombe County's own ArcGIS layer: 3,319 / 139 /
100 real current parcels) and written it to raw['gis_exempt'] -- but
distress_score.py's `senior_exemption` LIFE_EVENT signal (w=8) has only ever
read raw['tax_relief']['kind'], the key enrichment_tax_relief.py's own
7-county _RELIEF_LAYERS classify path writes. The two modules model the exact
same real-world fact (a hard, county-recorded age/disability exemption) under
different keys, the same raw-key-naming-gap shape as the code_enforcement /
condemned / rollback_exposure / sos_dissolution fixes found the same day.

enrichment_tax_relief.py already wins outright for its own 7 counties (it
runs later in main.py's pipeline and unconditionally overwrites
raw['tax_relief']); this bridge only changes behavior for every OTHER county
enrichment_gis_attrs.py reaches, where gis_exempt was previously the only
record of the fact and nothing ever scored it.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper import enrichment_gis_attrs as mod
from foreclosure_scraper.distress_score import _signals_for
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(
        source="test", source_url="https://example.test",
        listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.SINGLE_FAMILY,
        state="NC", county="Mecklenburg", first_seen=now, last_seen=now,
    )
    base.update(kw)
    return Listing(**base)


def test_eld_code_bridges_into_tax_relief_elderly():
    li = _lead(parcel_id="123")
    mod.apply_gis_attrs(li, {"PIN": "123", "Exempt": "ELD"})
    assert li.raw["gis_exempt"] == {"code": "ELD", "tag": "elderly_exemption"}
    assert li.raw["tax_relief"]["kind"] == "elderly"
    assert li.raw["tax_relief"]["basis"] == "elderly_disabled_exclusion"
    names = [n for n, _c, _w in _signals_for(li)]
    assert "senior_exemption" in names


def test_dis_code_bridges_into_tax_relief_disabled():
    li = _lead(parcel_id="123")
    mod.apply_gis_attrs(li, {"PIN": "123", "Exempt": "DIS"})
    assert li.raw["tax_relief"]["kind"] == "disabled"
    names = [n for n, _c, _w in _signals_for(li)]
    assert "senior_exemption" in names


def test_bld_code_bridges_into_tax_relief_blind():
    li = _lead(parcel_id="123")
    mod.apply_gis_attrs(li, {"PIN": "123", "Exempt": "BLD"})
    assert li.raw["tax_relief"]["kind"] == "blind"
    names = [n for n, _c, _w in _signals_for(li)]
    assert "senior_exemption" in names


def test_vet_code_is_tagged_but_deliberately_not_bridged():
    """A disabled-veteran exemption is a real, different statutory category.
    enrichment_tax_relief.py has never modeled "veteran" as a distress kind,
    so inventing one here would be a new scoring decision, not a key-naming
    fix -- gis_exempt still records it, tax_relief must not."""
    li = _lead(parcel_id="123")
    mod.apply_gis_attrs(li, {"PIN": "123", "Exempt": "VET"})
    assert li.raw["gis_exempt"] == {"code": "VET", "tag": "disabled_veteran_exemption"}
    assert "tax_relief" not in li.raw


def test_no_exemption_code_leaves_both_keys_absent():
    li = _lead(parcel_id="123")
    mod.apply_gis_attrs(li, {"PIN": "123", "Exempt": "0"})
    assert "gis_exempt" not in li.raw
    assert "tax_relief" not in li.raw


def test_tax_relief_key_is_registered_in_raw_keep():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "tax_relief" in RAW_KEEP
    assert "gis_exempt" in RAW_KEEP
