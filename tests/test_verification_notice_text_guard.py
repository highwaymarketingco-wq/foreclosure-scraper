"""The public verification ledger never carries foreclosure-notice text.

Some sources put the first sentence of a foreclosure notice in street_address ("Under and by virtue
of the power of sale contained in a certain Deed of Trust made by <names> ..."). A ledger key or row
summary built from it published private people's names in the public repo (found 2026-10-06 in 5
foreclosure_rod entries, two of them naming individuals). Names below are invented.
"""
from __future__ import annotations

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.ledger import Ledger

NOTICE = ("100 Under and by virtue of the power of sale contained in a certain Deed of Trust "
          "made by Jane Q. Example and John Q. Example")
REAL = "98 Dorman Drive"
GEOCODER_STYLE = "98, Dorman Drive, Buncombe County, North Carolina, 28787, United States"


def _row(street, **kw):
    return {"state": "NC", "county": "Buncombe", "street_address": street, "listing_type": "foreclosure_sale",
            "source": "x", **kw}


def test_looks_like_address():
    assert core.looks_like_address(REAL)
    assert core.looks_like_address(GEOCODER_STYLE)
    assert not core.looks_like_address(NOTICE)
    assert not core.looks_like_address("100 IN THE MATTER OF THE FORECLOSURE OF A DEED OF TRUST")
    assert not core.looks_like_address("")
    assert not core.looks_like_address(None)
    assert not core.looks_like_address("1 " + "x" * 120)


def test_notice_text_makes_no_addr_key():
    keys = core.row_keys(_row(NOTICE, case_number="22SP000481"))
    assert not any(k.startswith("addr:") for k in keys)
    assert any(k.startswith("case:") for k in keys)
    assert not any("example" in k.lower() for k in keys)


def test_a_real_address_still_makes_its_key():
    keys = core.row_keys(_row(REAL))
    assert any(k.startswith("addr:NC:buncombe:98") for k in keys)


def test_row_summary_drops_notice_text_only():
    assert "street_address" not in core.row_summary(_row(NOTICE))
    assert core.row_summary(_row(REAL))["street_address"] == REAL


def test_scrub_removes_entries_keys_and_addresses():
    bad_key = "fcrod:4ff41dc82a1717f7@addr:NC:buncombe:100 under and by virtue of the power of sale made by jane example"
    led = Ledger("foreclosure_rod", {
        bad_key: {"keys": [bad_key, "fcrod:4ff41dc82a1717f7@case:NC:buncombe:26sp000083100"],
                  "row": {"street_address": NOTICE, "county": "Buncombe"}, "latest": {"verdict": "unconfirmed"}},
        "fcrod:1@parcel:NC:buncombe:123": {
            "keys": ["fcrod:1@parcel:NC:buncombe:123", "fcrod:1@addr:NC:buncombe:100 under and by virtue of the power of sale"],
            "row": {"street_address": NOTICE, "county": "Buncombe"}, "latest": {"verdict": "stale"}},
        "fcrod:2@parcel:NC:buncombe:456": {
            "keys": ["fcrod:2@parcel:NC:buncombe:456"], "row": {"street_address": REAL},
            "latest": {"verdict": "confirmed"}},
    })
    out = led.scrub_notice_text()
    assert out == {"entries": 1, "keys": 1, "street_addresses": 1}
    assert bad_key not in led.rows
    assert led.rows["fcrod:1@parcel:NC:buncombe:123"]["keys"] == ["fcrod:1@parcel:NC:buncombe:123"]
    assert "street_address" not in led.rows["fcrod:1@parcel:NC:buncombe:123"]["row"]
    assert led.rows["fcrod:2@parcel:NC:buncombe:456"]["row"]["street_address"] == REAL
    assert led.scrub_notice_text() == {"entries": 0, "keys": 0, "street_addresses": 0}   # idempotent


def test_save_never_writes_notice_text(tmp_path):
    led = Ledger("foreclosure_rod", {
        "fcrod:1@parcel:NC:buncombe:123": {
            "keys": ["fcrod:1@parcel:NC:buncombe:123"],
            "row": {"street_address": NOTICE}, "latest": {"verdict": "unconfirmed"}}})
    p = led.save(tmp_path / "foreclosure_rod.json")
    text = p.read_text()
    assert "Example" not in text and "power of sale" not in text.lower()


def test_the_roll_scrapers_stand_in_for_a_missing_address_names_an_owner_and_is_dropped():
    """nc_ptscloud_delinquent_tax writes "Parcel - <OWNER> - <County> NC delinquent tax $N owed (parcel
    ..." into street_address when the roll has no situs; two ledger entries carried it (an agency and
    an association; an individual's would be the same). Invented names."""
    standin = "Parcel \u2014 EXAMPLE FAMILY HOLDINGS \u2014 Orange NC delinquent tax $200 owed (parcel 9"
    assert not core.looks_like_address(standin)
    assert not core.looks_like_address("Parcel - EXAMPLE FAMILY HOLDINGS - Orange NC delinquent tax $200 owed")
    assert core.looks_like_address("98 Dorman Drive") and core.looks_like_address("12 Parcel Rd")
    assert "street_address" not in core.row_summary(_row(standin))
    led = Ledger("tax_lien", {"parcel:NC:orange:1": {"keys": ["parcel:NC:orange:1"], "latest": {"verdict": "confirmed"},
                                                      "row": {"street_address": standin, "county": "Orange"}}})
    assert led.scrub_notice_text()["street_addresses"] == 1
    assert "street_address" not in led.rows["parcel:NC:orange:1"]["row"]
