"""parcel_cache.lookup id tolerance (2026-09-21): a delimited all-zero sub-parcel suffix and zero-padding
differences now resolve, and nothing that resolved before changes. Non-zero sub-parcels and short ids stay misses."""
from __future__ import annotations

import sqlite3

import pytest

from foreclosure_scraper import parcel_cache as pc


def _make_cache(tmp_path, monkeypatch, name, rows, state=None):
    """rows: [(id, owner, address, mailing)]"""
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    pc._CONN.clear()
    stem = name if state is None else f"{name}_{state.lower()}"
    con = sqlite3.connect(tmp_path / f"{stem}.sqlite")
    con.execute("CREATE TABLE parcels(id TEXT, owner TEXT, address TEXT, owner_mailing TEXT, market_value REAL, "
                "tax_value REAL, acreage REAL, living_sqft REAL, land_use TEXT, sale_price REAL, sale_date TEXT)")
    for pid, owner, addr, mail in rows:
        con.execute("INSERT INTO parcels(id, owner, address, owner_mailing) VALUES(?,?,?,?)", (pid, owner, addr, mail))
    con.commit()
    con.close()


@pytest.fixture(autouse=True)
def _clear():
    yield
    pc._CONN.clear()


def test_exact_forms_still_win_and_are_reported_exact(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "darlington", [("0520002212", "MITCHELL J", "1 OAK ST", None)])
    hit, tier = pc.lookup_with_tier("Darlington", "052-00-02-212", "SC")
    assert tier == "exact" and hit["owner"] == "MITCHELL J"
    assert pc.lookup("Darlington", "052-00-02-212", "SC")["address"] == "1 OAK ST"


def test_delimited_all_zero_suffix_resolves_to_the_bare_parcel(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "darlington", [("0520002212", "MITCHELL J", "1 OAK ST", None)])
    hit, tier = pc.lookup_with_tier("Darlington", "052-00-02-212.000", "SC")
    assert tier == "zero_suffix" and hit["owner"] == "MITCHELL J"
    _make_cache(tmp_path, monkeypatch, "anderson", [("1510601006", "P", "3101 CAMDEN DR", None)])
    assert pc.lookup_with_tier("Anderson", "151-06-01-006-000", "SC")[1] == "zero_suffix"


def test_a_non_zero_sub_parcel_suffix_is_not_resolved_to_its_parent(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "darlington", [("1680001104", "PARENT OWNER", "1 OAK ST", None)])
    assert pc.lookup("Darlington", "168-00-01-104.012", "SC") is None      # .012 is a real sub-parcel
    assert pc.lookup("Darlington", "168-00-01-104.001", "SC") is None
    assert pc.lookup("Darlington", "0119-00-070.01-001", "SC") is None


def test_zero_padding_difference_resolves_for_10_plus_digit_pins(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "harnett", [("0546741638000", "SCHACHTER", "3603 MCLEAN CHAPEL CHURCH RD", None)])
    hit, tier = pc.lookup_with_tier("Harnett", "0546-74-1638", "NC")
    assert tier == "zero_pad" and hit["owner"] == "SCHACHTER"
    _make_cache(tmp_path, monkeypatch, "forsyth", [("6807694940", "GREEN", "0 SHATTALON DR", None)])
    assert pc.lookup_with_tier("Forsyth", "6807-69-4940-0", "NC")[0]["owner"] == "GREEN"


def test_zero_pad_is_refused_when_two_different_parcels_could_match(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "harnett", [("0546741638000", "OWNER ONE", "1 OAK ST", None),
                                                   ("05467416380000", "OWNER TWO", "9 ELM ST", None)])
    assert pc.lookup("Harnett", "0546-74-1638", "NC") is None


def test_zero_pad_never_applies_to_short_ids(tmp_path, monkeypatch):
    # Rutherford Parcel_Number: 616146 and 6161460 are two different parcels
    _make_cache(tmp_path, monkeypatch, "rutherford", [("6161460", "OTHER PARCEL", "2 ELM ST", None)])
    assert pc.lookup("Rutherford", "616146", "NC") is None
    assert pc.lookup("Rutherford", "8587", "NC") is None


def test_dual_state_names_still_need_a_state(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "cherokee", [("0990100022", "X", "1 OAK ST", None)], state="SC")
    assert pc.lookup("Cherokee", "099-01-00-022", None) is None
    assert pc.lookup("Cherokee", "099-01-00-022", "SC")["owner"] == "X"
    assert pc.lookup("Cherokee", "099-01-00-022", "NC") is None            # no NC cache exists


def test_candidates_put_exact_forms_first():
    c = pc._lookup_candidates("052-00-02-212.000")
    assert c[0] == ("0520002212000", "exact")
    tiers = [t for _k, t in c]
    assert tiers.index("zero_suffix") < tiers.index("zero_pad")
    assert pc._lookup_candidates("") == []
