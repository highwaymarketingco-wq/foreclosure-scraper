"""A parcel's situs is where the property IS. Never store the owner's mailing there.

THE BUG THIS PINS. parcel_cache's Spartanburg entry mapped
    "address": "StreetAddress"
with a comment calling StreetAddress "clean situs". In the county's CAMA layer
StreetAddress is the OWNER'S MAILING ADDRESS; the situs lives in StreetNumber /
StreetName / StreetCommunity / StreetZip.

The two coincide for owner-occupants, so the error hid in the majority case. Measured
over a 1,000-parcel sample of the live layer, 2026-09-13:

    559 (56%)  mailing == situs   owner-occupied, no visible harm
    441 (44%)  mailing != situs   the stored "situs" was the mailing address

    3-22-00-019.04  stored "194 WATERFRONT ROW, PROSPERITY"; property is 251 NEAL RD, SPARTANBURG
    5-10-00-023.08  stored "PO BOX 145, INMAN"  as a street address

It did its worst damage exactly where the value is. A wrong situs breaks routing and
geocoding, and it silently defeats the absentee test -- comparing the mailing address
against itself always reports "not absentee", so every Spartanburg absentee was invisible.
Spartanburg is the largest footprint county on the board at 10,054 rows.
"""
from __future__ import annotations

import re

import pytest

from foreclosure_scraper.parcel_cache import PARCEL_LAYERS

#: A PO Box is a mail destination. It can never be where a house stands.
PO_BOX_RE = re.compile(r"\b(p\.?\s*o\.?\s*box|post\s+office\s+box)\b", re.I)


def looks_like_a_mailbox(value: str | None) -> bool:
    return bool(value and PO_BOX_RE.search(str(value)))


@pytest.mark.parametrize("v,expect", [
    ("PO BOX 145 INMAN SC", True), ("P.O. Box 12", True), ("Post Office Box 9", True),
    ("po box 145", True),
    ("251 NEAL RD SPARTANBURG", False), ("1101 PARTRIDGE RD", False),
    ("120 BOXWOOD LN", False),          # "box" inside a word is not a PO Box
    (None, False), ("", False),
])
def test_po_box_detector(v, expect):
    assert looks_like_a_mailbox(v) is expect


def test_spartanburg_situs_is_the_situs_fields_not_streetaddress():
    """THE regression guard. StreetAddress is the owner's mailing address in this layer."""
    m = PARCEL_LAYERS["Spartanburg"]["map"]
    assert m["address"] != "StreetAddress", (
        "StreetAddress is the OWNER MAILING address in Spartanburg's CAMA layer. "
        "The situs is StreetNumber / StreetName / StreetCommunity."
    )
    assert m["address"] == ["StreetNumber", "StreetName", "StreetCommunity"]
    assert m["owner_mailing"] == ["StreetAddress", "City", "State", "Zip"]


def test_no_county_maps_the_same_source_field_to_both_situs_and_mailing():
    """One field cannot be both where the property is and where the post goes. If a
    county ever maps the same source column to both, one of them is wrong."""
    for county, cfg in PARCEL_LAYERS.items():
        m = cfg.get("map", {})
        situs, mail = m.get("address"), m.get("owner_mailing")
        if not situs or not mail:
            continue
        s = set(situs if isinstance(situs, list) else [situs])
        d = set(mail if isinstance(mail, list) else [mail])
        assert not (s & d), (
            f"{county} maps {sorted(s & d)} to BOTH situs and owner_mailing — "
            f"one of the two is wrong")


@pytest.mark.parametrize("county", sorted(PARCEL_LAYERS))
def test_no_county_uses_an_obviously_mailing_named_field_as_its_situs(county):
    """A field whose NAME says mailing must never be the situs. Cheap, and it would have
    caught Laurens (Mailing_Address) and Transylvania (ADDRESS_1/3) had they been wired
    that way."""
    situs = PARCEL_LAYERS[county].get("map", {}).get("address")
    if not situs:
        return
    for f in (situs if isinstance(situs, list) else [situs]):
        assert not re.search(r"mail", str(f), re.I), (
            f"{county} uses {f!r} as its situs, and the field name says mailing")
