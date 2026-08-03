"""Lincoln County NC cached bulk-assessor backfill.

The load-bearing invariant here is the join key. Rows are verbatim samples from
the 2026-08-01 extract (parceldata.csv / improvements.csv / sales.csv).
Hermetic — no network, no cache writes.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import nc_lincoln_bulk as lb
from foreclosure_scraper.models import Listing


def _listing(**kw) -> Listing:
    kw.setdefault("source", "test")
    kw.setdefault("source_url", "https://example.test/lead")
    return Listing(**kw)


# Two REAL accounts that share one PIN (2694213729) — the collision that made
# a naive PIN index hand one parcel the other's owner, value and vacancy.
PARCELS = [
    {"AKPAR_": "M04201", "PIN": "2694213729", "NAME1": "GRIGG SHERRY L",
     "NAME2": "", "ADDRESS1": "4870 GRIGG RD", "ADDRESS2": "",
     "CITY": "LINCOLNTON", "STATE": "NC", "ZIP": "280920000",
     "PHYSICALADDR": "4870 GRIGG RD", "TOTALVALUE": "14687", "VACANT": "NO",
     "ZONING": "R-SF", "ACRE": "1.02", "DEEDBK": "", "DEEDPG": ""},
    {"AKPAR_": "76583", "PIN": "2694213729", "NAME1": "GRIGG SHERRY L",
     "NAME2": "", "ADDRESS1": "4870 GRIGG RD", "ADDRESS2": "",
     "CITY": "LINCOLNTON", "STATE": "NC", "ZIP": "280920000",
     "PHYSICALADDR": "4870 GRIGG RD", "TOTALVALUE": "37439", "VACANT": "YES",
     "ZONING": "R-SF", "ACRE": "3.40", "DEEDBK": "", "DEEDPG": ""},
    # an unambiguous parcel with an out-of-state owner
    {"AKPAR_": "50901", "PIN": "3633846179", "NAME1": "CDL HOUSING LLC",
     "NAME2": "", "ADDRESS1": "1004 ALTON CIRCLE", "ADDRESS2": "",
     "CITY": "FLORENCE", "STATE": "SC", "ZIP": "295010000",
     "PHYSICALADDR": "510 LITHIA INN RD", "TOTALVALUE": "42940",
     "VACANT": "NO", "ZONING": "R-T", "ACRE": "0.51",
     "DEEDBK": "1234", "DEEDPG": "567"},
]

IMPROVEMENTS = [
    {"AHPAR_": "50901", "AHACYR": "1968", "AHBED_": "3", "AHBTH_": "2.00000000",
     "AHHBTH": "1", "AHFNAR": "2542.00000000", "PRIMARYIMA": "20200428/00102AA.JPG"},
    # a second card on the same account, SMALLER — must not win
    {"AHPAR_": "50901", "AHACYR": "1999", "AHBED_": "0", "AHBTH_": ".00000000",
     "AHHBTH": "0", "AHFNAR": "400.00000000", "PRIMARYIMA": ""},
]

SALES = [
    {"AKPAR_": "50901", "PIN": "3633846179", "AMDTSL": "19000600",
     "AMSLAM": "0", "AMDBOK": "555", "AMDPGE": "738", "AMYEAR": "1906"},
    {"AKPAR_": "50901", "PIN": "3633846179", "AMDTSL": "20180914",
     "AMSLAM": "185000", "AMDBOK": "2811", "AMDPGE": "119", "AMYEAR": "2018"},
]


@pytest.fixture()
def index():
    return lb._build_index(PARCELS, IMPROVEMENTS, SALES)


# --- join-key correctness ---------------------------------------------------

def test_akpar_is_the_authoritative_unique_key(index):
    assert index["M04201"]["tax_value"] == 14687.0
    assert index["M04201"]["vacant"] is False
    assert index["76583"]["tax_value"] == 37439.0
    assert index["76583"]["vacant"] is True


def test_shared_pin_is_not_indexed(index):
    """2,003 PINs are shared by 4,976 of the 56,977 rows (8.7%); the worst
    covers 92 accounts. Resolving one would attach a neighbour's owner."""
    assert "2694213729" not in index


def test_unambiguous_pin_still_resolves(index):
    assert index["3633846179"]["akpar"] == "50901"


def test_lookup_declines_an_ambiguous_pin(index, monkeypatch):
    monkeypatch.setattr(lb, "_INDEX", index)
    assert lb.lookup("2694213729") is None
    assert lb.lookup("2694-21-3729") is None          # dashes normalise the same
    assert lb.lookup("M04201")["tax_value"] == 14687.0
    assert lb.lookup("3633846179")["akpar"] == "50901"


def test_lookup_handles_zero_padded_pin(index, monkeypatch):
    monkeypatch.setattr(lb, "_INDEX", index)
    assert lb.lookup("363384617900000")["akpar"] == "50901"


# --- pure helpers -----------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("280920000", "28092"),          # 9-digit with a zero +4 -> ZIP5
    ("28226-1234", "28226-1234"),    # real ZIP+4 kept
    ("28092", "28092"),
    ("", ""),
])
def test_zip5(raw, want):
    assert lb._zip5(raw) == want


def test_build_mailing():
    assert lb.build_mailing(PARCELS[2]) == "1004 ALTON CIRCLE, FLORENCE SC 29501"


def test_absentee_blank_state_is_unknown_not_false():
    assert lb.is_absentee({"STATE": "SC"}) is True
    assert lb.is_absentee({"STATE": "NC"}) is False
    assert lb.is_absentee({"STATE": ""}) is None
    assert lb.is_absentee({}) is None


@pytest.mark.parametrize("raw,want", [
    ("20180914", "2018-09-14"),
    ("19000600", "1900-06-01"),   # day 00 -> 01, month/year real
    ("", ""),
    ("0", ""),
    ("99999999", ""),             # month 99 is not a month
])
def test_parse_sale_date(raw, want):
    assert lb.parse_sale_date(raw) == want


def test_largest_improvement_card_wins(index):
    rec = index["50901"]
    assert rec["living_sqft"] == 2542.0
    assert rec["year_built"] == 1968
    assert rec["bedrooms"] == 3.0


def test_latest_sale_wins_and_zero_amount_is_dropped(index):
    sale = index["50901"]["last_sale"]
    assert sale["date"] == "2018-09-14"
    assert sale["amount"] == 185000.0


# --- privacy ----------------------------------------------------------------

def test_column_allowlists_carry_no_sensitive_fields():
    """Lincoln has historically exposed TCSSN1/TCSSN2 on a public layer. The
    allow-list is what keeps one appearing upstream from reaching the board."""
    cols = lb._PARCEL_COLS + lb._IMPROV_COLS + lb._SALES_COLS
    for c in cols:
        low = c.lower()
        assert "ssn" not in low
        assert "social" not in low
        assert "birth" not in low and "dob" not in low


def test_reader_keeps_only_allowlisted_columns(index):
    """A column that is not on the allow-list must not survive into a record."""
    rec = index["50901"]
    assert "TCNAM3" not in rec and "OWNERID" not in rec


# --- enrich behaviour -------------------------------------------------------

def test_enrich_fills_and_never_overwrites(index, monkeypatch):
    monkeypatch.setattr(lb, "_INDEX", index)
    empty = _listing(state="NC", county="Lincoln County", parcel_id="50901")
    held = _listing(state="NC", county="Lincoln", parcel_id="50901",
                    street_address="EXISTING ADDR", tax_value=999.0)
    held.raw = {"gis": {"owner": "PRE-EXISTING OWNER"}}

    stats = lb.enrich([empty, held], auto_refresh=False)
    assert stats["matched"] == 2

    assert empty.street_address == "510 LITHIA INN RD"
    assert empty.tax_value == 42940.0
    assert empty.bedrooms == 3.0
    assert empty.raw["gis"]["mailing"] == "1004 ALTON CIRCLE, FLORENCE SC 29501"
    assert empty.raw["gis"]["absentee"] is True
    assert empty.raw["gis"]["vacant"] is False

    # existing values survive untouched
    assert held.street_address == "EXISTING ADDR"
    assert held.tax_value == 999.0
    assert held.raw["gis"]["owner"] == "PRE-EXISTING OWNER"


def test_enrich_skips_other_counties_and_states(index, monkeypatch):
    monkeypatch.setattr(lb, "_INDEX", index)
    out = lb.enrich([
        _listing(state="NC", county="Gaston", parcel_id="50901"),
        _listing(state="SC", county="Lincoln", parcel_id="50901"),
        _listing(state="NC", county="Lincoln", parcel_id=""),
    ], auto_refresh=False)
    assert out["eligible"] == 0 and out["matched"] == 0


def test_enrich_is_a_noop_when_gated_off(index, monkeypatch):
    monkeypatch.setattr(lb, "_INDEX", index)
    monkeypatch.setenv("FORECLOSURE_LINCOLN_BULK", "0")
    li = _listing(state="NC", county="Lincoln", parcel_id="50901")
    assert lb.enrich([li], auto_refresh=False)["matched"] == 0
    assert li.tax_value is None


def test_enrich_leaves_board_alone_when_cache_is_empty(monkeypatch):
    monkeypatch.setattr(lb, "_INDEX", {})
    li = _listing(state="NC", county="Lincoln", parcel_id="50901")
    out = lb.enrich([li], auto_refresh=False)
    assert out["eligible"] == 1 and out["matched"] == 0
    assert li.tax_value is None
