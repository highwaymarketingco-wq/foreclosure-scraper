"""Unit tests for the local parcel-cache id/field logic — the parts that silently
mis-joined leads before (float PKs, 15↔10-digit PIN padding, split situs)."""
from foreclosure_scraper.parcel_cache import _norm_id, _id_variants, _map_val


def test_norm_id_strips_float_zero():
    # ArcGIS returns internal PKs as floats (122973.0) — must match a board id "122973"
    assert _norm_id(122973.0) == "122973"
    assert _norm_id("122973.0") == "122973"
    assert _norm_id(122973) == "122973"


def test_norm_id_basic():
    assert _norm_id("500-23-01-004") == "5002301004"
    assert _norm_id(None) == ""
    assert _norm_id(" 4605711048 ") == "4605711048"


def test_norm_id_keeps_real_zeros_in_punctuated_parcel():
    # Spartanburg GISParcelNumber "7102-28-3341.88" must match a board id "710228334188"
    assert _norm_id("7102-28-3341.88") == "710228334188"
    assert _norm_id("710228334188") == "710228334188"
    # a GISParcelNumber ending .00 keeps those zeros (only PURE float-strings get trimmed)
    assert _norm_id("1234-56-7890.00") == "123456789000"


def test_id_variants_pin_padding():
    # 15-digit board PIN ending 00000 <-> 10-digit layer PIN, both directions
    assert "9634707498" in _id_variants("963470749800000")
    assert "963470749800000" in _id_variants("9634707498")
    # a plain internal id has just itself
    assert _id_variants("90537") == {"90537"}


def test_map_val_split_address_drops_zero_number():
    assert _map_val({"STREETNUM": "8615", "STREETNAME": "OLD NC 18"}, "address",
                    ["STREETNUM", "STREETNAME"]) == "8615 OLD NC 18"
    # rural parcel with STREETNUM 0 -> just the street, no bogus "0"
    assert _map_val({"STREETNUM": "0", "STREETNAME": "OLD NC 18"}, "address",
                    ["STREETNUM", "STREETNAME"]) == "OLD NC 18"


def test_map_val_numeric_coercion_and_none():
    assert _map_val({"parval": "73680"}, "market_value", "parval") == 73680.0
    assert isinstance(_map_val({"parval": "73680"}, "market_value", "parval"), float)
    assert _map_val({}, "market_value", None) is None          # county without a value field
    assert _map_val({"v": "N/A"}, "acreage", "v") is None      # unparseable -> None, no crash
