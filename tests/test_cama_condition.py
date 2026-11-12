"""Unit tests for enrichment_cama_condition — the bulk CAMA condition/grade/year
PIN-join layer. Pure-function coverage (no network); a live smoke lives in the
module docstring / the enricher's own log line.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_cama_condition import (
    _normalize_condition,
    _pin_key,
    _year_int,
    _distressed_tier,
    _apply,
    _county_key,
    CAMA_SOURCES,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


# ---- condition normalization ----------------------------------------------------

def test_normalize_distressed_codes_and_words():
    for val, label in (("P", "poor"), ("Poor", "poor"), ("VP", "very_poor"),
                       ("Very Poor", "very_poor"), ("U", "unsound"),
                       ("Unsound", "unsound"), ("DL", "dilapidated")):
        lab, distressed = _normalize_condition(val)
        assert lab == label
        assert distressed is True


def test_normalize_non_distressed():
    for val in ("N", "Average", "G", "Good", "F", "Fair", "R", "E", "Excellent",
                "Very Good"):
        _, distressed = _normalize_condition(val)
        assert distressed is False


def test_normalize_blank_and_null():
    assert _normalize_condition(None) == (None, False)
    assert _normalize_condition("") == (None, False)
    assert _normalize_condition("<Null>") == (None, False)
    assert _normalize_condition("   ") == (None, False)


def test_normalize_unknown_code_kept_not_distressed():
    lab, distressed = _normalize_condition("XZ")
    assert lab == "xz"
    assert distressed is False


# ---- pin key building -----------------------------------------------------------

def test_pin_pad15_extends_short_pin():
    assert _pin_key("9639454911", pad15=True) == "963945491100000"


def test_pin_pad15_leaves_full_pin():
    assert _pin_key("965885199400000", pad15=True) == "965885199400000"


def test_pin_strips_nondigits():
    assert _pin_key("0629-354-795", pad15=False) == "0629354795"


def test_pin_none_and_empty():
    assert _pin_key(None, pad15=True) is None
    assert _pin_key("", pad15=True) is None
    assert _pin_key("ABC-XYZ", pad15=True) is None  # no digits


def test_pin_no_pad_when_disabled():
    # York SC ParcelID is a 10-digit taxmap; must NOT be padded.
    assert _pin_key("7261201194", pad15=False) == "7261201194"


# ---- year parsing ---------------------------------------------------------------

def test_year_int_valid_and_bounds():
    assert _year_int(1959) == 1959
    assert _year_int("1900") == 1900
    assert _year_int(0) is None
    assert _year_int(9999) is None
    assert _year_int(None) is None
    assert _year_int("") is None


# ---- tier mapping ---------------------------------------------------------------

def test_distressed_tier_mapping():
    assert _distressed_tier("unsound") == "gut"
    assert _distressed_tier("dilapidated") == "gut"
    assert _distressed_tier("poor") == "major"
    assert _distressed_tier("very_poor") == "major"
    assert _distressed_tier("fair") is None
    assert _distressed_tier("good") is None


# ---- county keying --------------------------------------------------------------

def _li(**kw):
    base = dict(source="x", source_url="http://x", listing_type=ListingType.REO,
                property_kind=PropertyKind.SINGLE_FAMILY)
    base.update(kw)
    return Listing(**base)


def test_county_key_normalizes():
    assert _county_key(_li(state="NC", county="Buncombe County")) == ("NC", "Buncombe")
    assert _county_key(_li(state="NC", county="Carteret, NC")) == ("NC", "Carteret")
    assert _county_key(_li(state=None, county="Buncombe")) is None


def test_all_sources_are_in_footprint_and_shaped():
    # every configured source must carry a url + pin_field + a join mode
    for key, cfg in CAMA_SOURCES.items():
        assert cfg["url"].startswith("https://")
        assert cfg["pin_field"]
        assert cfg["join"] in ("pin", "address")
        # at least ONE data field must be present or the source is pointless
        assert any(cfg.get(f) for f in ("condition_field", "grade_field", "year_field"))


# ---- apply: stamping + distress feed + non-clobber ------------------------------

def test_apply_stamps_condition_and_feeds_distress():
    li = _li(state="NC", county="Buncombe")
    _apply(li, {"condition": "P", "grade": "D", "year": 1900},
           "cama:NC:Buncombe", _fresh_stats())
    blk = li.raw["condition_cama"]
    assert blk["condition"] == "poor"
    assert blk["condition_code"] == "P"
    assert blk["distressed"] is True
    assert blk["grade"] == "D"
    assert blk["year_built"] == 1900
    assert li.year_built == 1900             # backfilled
    assert li.raw["distressed"] is True      # feeds distress_score
    assert li.raw["condition_tier"] == "major"
    assert li.raw["condition_source"] == "cama"


def test_apply_does_not_clobber_vision_tier():
    li = _li(state="NC", county="Buncombe")
    li.raw = {"vision": {"condition_tier": "move_in_ready"}}
    _apply(li, {"condition": "Unsound", "grade": None, "year": None},
           "cama:NC:Carteret", _fresh_stats())
    # distressed still stamped + raw['distressed'] set, but the Vision-grounded
    # condition_tier must survive.
    assert li.raw["condition_cama"]["distressed"] is True
    assert li.raw["distressed"] is True
    assert "condition_tier" not in li.raw  # vision tier lives under raw['vision']


def test_apply_does_not_overwrite_existing_year():
    li = _li(state="SC", county="York", year_built=1980)
    _apply(li, {"condition": None, "grade": None, "year": 2002},
           "cama:SC:York", _fresh_stats())
    assert li.year_built == 1980                       # kept
    assert li.raw["condition_cama"]["year_built"] == 2002  # still recorded


def test_apply_noop_when_empty_record():
    li = _li(state="NC", county="Onslow")
    _apply(li, {"condition": None, "grade": None, "year": None},
           "cama:NC:Onslow", _fresh_stats())
    assert "condition_cama" not in li.raw


def _fresh_stats():
    return {"stamped": 0, "filled_year": 0, "distressed": 0, "seeded_tier": 0}
