"""counties_nc.rutherford_wildfire_tax: the county PIN for the roll's Parcel_Number (2026-10-08).

The feed's ParcelNumber is the 6-7 digit county Parcel_Number that counties_nc.rutherford_tax
already maps to the 10-digit PIN (owner decision 2026-10-07, parcel_alias.py). validation.py nulls
the six-digit ones (896 rows on the 2026-10-08 run). The PIN is applied only once
parcel_alias.ALIAS_SOURCES registers this slug (a shared-file change), so the board merge folds
the old short-id row into the new PIN row instead of publishing both. Ids and names are invented.
"""
from __future__ import annotations

import asyncio
import json

from foreclosure_scraper import parcel_alias
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_nc import rutherford_tax as rt
from foreclosure_scraper.scrapers.counties_nc import rutherford_wildfire_tax as m


def _row(parcel: str) -> Listing:
    return Listing(source=m.SLUG, source_url="u", listing_type=ListingType.TAX_LIEN, state="NC",
                   county="Rutherford", parcel_id=parcel,
                   raw={"rutherford_wildfire": {"parcel": parcel}})


def test_the_pin_replaces_the_parcel_number_and_the_number_stays_in_raw():
    rows = [_row("123456"), _row("1234567"), _row("999999")]
    n = m.apply_county_pins(rows, {"123456": "0612345678", "1234567": "0698765432"})
    assert n == 2
    assert [r.parcel_id for r in rows] == ["0612345678", "0698765432", "999999"]
    assert rows[0].raw["rutherford_wildfire"] == {"parcel": "123456", "pin": "0612345678"}


def test_a_pin_shared_by_two_parcel_numbers_is_not_applied():
    rows = [_row("111111"), _row("222222")]
    assert m.apply_county_pins(rows, {"111111": "0600000001", "222222": "0600000001"}) == 0
    assert [r.parcel_id for r in rows] == ["111111", "222222"]


def test_pins_wait_for_the_alias_registration(monkeypatch):
    calls = []

    async def fake_map(http):
        calls.append(1)
        return {"123456": "0612345678"}

    monkeypatch.setattr(rt, "pin_map_cached", fake_map)
    monkeypatch.delenv("RUTHERFORD_WILDFIRE_PINS", raising=False)
    monkeypatch.setattr(parcel_alias, "ALIAS_SOURCES", dict(parcel_alias.ALIAS_SOURCES))
    parcel_alias.ALIAS_SOURCES.pop(m.SLUG, None)
    rows = asyncio.run(m._with_pins([_row("123456")]))
    assert rows[0].parcel_id == "123456" and calls == []          # unregistered: unchanged

    parcel_alias.ALIAS_SOURCES[m.SLUG] = ("rutherford_wildfire", "parcel")
    rows = asyncio.run(m._with_pins([_row("123456")]))
    assert rows[0].parcel_id == "0612345678" and calls == [1]

    monkeypatch.setenv("RUTHERFORD_WILDFIRE_PINS", "0")
    rows = asyncio.run(m._with_pins([_row("123456")]))
    assert rows[0].parcel_id == "123456"


def test_registered_rows_build_the_alias_table():
    """Once registered, parcel_alias.build() reads both ids off the fresh rows (what the merge
    and dedupe use to fold the old short-id rows)."""
    saved = dict(parcel_alias.ALIAS_SOURCES)
    try:
        parcel_alias.ALIAS_SOURCES[m.SLUG] = ("rutherford_wildfire", "parcel")
        rows = [_row("123456")]
        m.apply_county_pins(rows, {"123456": "0612345678"})
        table = parcel_alias.build(rows)
        assert list(table.values()) == ["0612345678"]
    finally:
        parcel_alias.ALIAS_SOURCES.clear()
        parcel_alias.ALIAS_SOURCES.update(saved)


def test_rutherford_tax_reuses_a_recent_pin_map_in_process(monkeypatch):
    monkeypatch.setattr(rt, "_PIN_MEMO", {"at": 0.0, "map": {}})
    pages = []

    class R:
        status_code = 200

        def __init__(self, body):
            self._b = body

        def json(self):
            return self._b

    class Http:
        async def get(self, url, params=None, timeout=None):
            pages.append(params["resultOffset"])
            return R({"features": [{"attributes": {"Parcel_Number": "123456", "PIN": "0612345678"}}]})

    a = asyncio.run(rt.pin_map_cached(Http()))
    b = asyncio.run(rt.pin_map_cached(Http()))
    assert a == b == {"123456": "0612345678"} and pages == ["0"]
