"""Burke County NC cached WPCOG parcel spine.

Two invariants carry this module: the PIN join must refuse to guess when a PIN
covers more than one account, and the 2017 vacancy flag must never leak into the
board as a present-tense "vacant" (empty structure) signal.

Rows in tests/fixtures/burke_spine_rows.json are verbatim samples from the live
layers on 2026-08-03. Hermetic — no network, no cache reads or writes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper import nc_burke_spine as bs
from foreclosure_scraper.models import Listing

ROWS = json.loads((Path(__file__).parent / "fixtures" / "burke_spine_rows.json").read_text())
VACANT, BIG, ROLL, GOVT = ROWS["vacant"], ROWS["big"], ROWS["roll"], ROWS["govt"]


def _listing(**kw) -> Listing:
    kw.setdefault("source", "test")
    kw.setdefault("source_url", "https://example.test/lead")
    kw.setdefault("state", "NC")
    kw.setdefault("county", "Burke")
    return Listing(**kw)


@pytest.fixture
def index(monkeypatch):
    """Build the index from the fixture and install it, bypassing the cache."""
    idx = bs._build_index(VACANT, BIG, ROLL, GOVT)
    monkeypatch.setattr(bs, "_INDEX", idx)
    return idx


# ------------------------------------------------------------- pure helpers --

@pytest.mark.parametrize("raw,expected", [
    ("2703905385", "2703905385"),
    ("2647-50-6616", "2647506616"),      # dashed board spelling
    (" 1791609195 ", "1791609195"),
    (None, ""),
])
def test_norm_pin(raw, expected):
    assert bs.norm_pin(raw) == expected


def test_squash_treats_space_padding_as_empty():
    # WPCOG fills unused text columns with a single space, not NULL.
    assert bs.squash(" ") == ""
    assert bs.squash("  MORGANTON   NC ") == "MORGANTON NC"


def test_clean_owner_strips_lead_space_and_normalises_co_owners():
    assert bs.clean_owner(" BARRON, HARVEY C; BARRON, PATRICIA M") == \
        "BARRON, HARVEY C; BARRON, PATRICIA M"
    assert bs.clean_owner(" MTC LLC") == "MTC LLC"


def test_build_mailing_skips_the_space_filler_columns():
    assert bs.build_mailing(ROLL[0]) == "8 HARDWICK COURT, SUGAR GROVE IL 60554"


def test_is_absentee_reads_the_mailing_state():
    assert bs.is_absentee(ROLL[0]) is True          # mails from IL
    assert bs.is_absentee(ROLL[1]) is False         # mails from NC
    assert bs.is_absentee({"OWNER_MA_4": " "}) is None


@pytest.mark.parametrize("raw,expected", [
    ("0   WILL HUDSON RD", ""),      # unaddressed parcel — a street with no number
    ("0  E UNION ST", ""),
    ("105  E PARKER RD", "105 E PARKER RD"),
    ("2072 A/C  SKYLAND DR", "2072 A/C SKYLAND DR"),
    (" ", ""),
])
def test_clean_situs_rejects_the_zero_house_number(raw, expected):
    assert bs.clean_situs(raw) == expected


def test_epoch_ms_to_iso_rejects_sentinels():
    assert bs._epoch_ms_to_iso(220665600000) == "1976-12-29"
    assert bs._epoch_ms_to_iso(0) == ""
    assert bs._epoch_ms_to_iso(None) == ""
    assert bs._epoch_ms_to_iso("not a date") == ""


# --------------------------------------------------------------- index join --

def test_ambiguous_pin_resolves_to_nothing(index):
    """PIN 2713194819 is two separate REIDs (4644 / 53574) on different streets
    with different acreage and value. Guessing hands a lead the wrong parcel."""
    assert bs.norm_pin("2713194819") not in index


def test_unambiguous_pin_carries_owner_mailing_and_reid(index):
    rec = index["2703905385"]
    assert rec["reid"] == "2796"
    assert rec["owner"] == "MTC LLC"
    assert rec["mailing"] == "8 HARDWICK COURT, SUGAR GROVE IL 60554"
    assert rec["absentee"] is True
    assert rec["tax_value"] == 187111.0
    assert rec["deed_date"] == "2000-12-12"


def test_vacant_flag_is_dated_not_present_tense(index):
    rec = index["1791609195"]
    assert rec["vacant_land"] is True
    assert rec["vacant_land_as_of"] == bs.VACANT_AS_OF == "2017-01-10"
    assert rec["township"] == "Morganton"


def test_blank_land_class_is_not_evidence_of_vacancy(index):
    """47 of the 21,879 vacant-roll rows carry LAND_CLASS ' '. Absence of a
    class is not a vacancy claim."""
    rec = index["2711078864"]
    assert "vacant_land" not in rec
    assert "land_class" not in rec


def test_big_tract_layer_marks_over_20_acres(index):
    rec = index["1658728292"]
    assert rec["over_20_acres"] is True
    assert rec["acreage"] == 35.8
    assert rec["deed_book"] == "000518" and rec["deed_page"] == "00876"


def test_government_owned_block(index):
    rec = index["1772372806"]
    g = rec["govt_owned"]
    assert g["government"] == "TOWN OF GLEN ALPINE"
    assert g["facility"] == "SIMPSON PARK"
    assert g["county"] == "Burke"
    assert g["reid"] == "38434"


def test_govt_records_filters_by_county(index):
    assert {r["county"] for r in bs.govt_records()} == {"Burke", "Catawba"}
    assert len(bs.govt_records("Burke")) == 2
    assert len(bs.govt_records("Catawba")) == 1


def test_reid_for_is_the_lrcpwa_bridge(index):
    # Board Burke leads arrive as 10-digit PINs; lrcpwa searches on the REID.
    assert bs.reid_for("2647-50-6616") == "20828"
    assert bs.reid_for("2713194819") is None      # ambiguous, no guess
    assert bs.reid_for("") is None


def test_lookup_tolerates_pin_ext_zero_padding(index):
    assert bs.lookup("2703905385000") is index["2703905385"]
    assert bs.lookup("2703905385123") is None     # a real different parcel


# ------------------------------------------------------------------ enrich --

def test_enrich_fills_only_what_is_missing(index):
    li = _listing(parcel_id="2703905385", tax_value=999.0)
    stats = bs.enrich([li], auto_refresh=False)
    assert stats["matched"] == 1 and stats["reid"] == 1
    assert li.tax_value == 999.0                   # never overwritten
    assert li.street_address == "105 E PARKER RD"
    assert li.city == "Morganton" and li.zip_code == "28655"
    assert li.owner_name == "MTC LLC"
    assert li.raw["gis"]["mailing"] == "8 HARDWICK COURT, SUGAR GROVE IL 60554"
    assert li.raw["gis"]["absentee"] is True
    assert li.raw["burke_spine"]["reid"] == "2796"


def test_enrich_never_writes_a_bare_vacant_flag(index):
    """Downstream lead-signal code reads raw['vacant'] as an empty STRUCTURE.
    This roll means unimproved LAND, off a 2017 snapshot."""
    li = _listing(parcel_id="1791609195")
    bs.enrich([li], auto_refresh=False)
    assert "vacant" not in li.raw
    assert "vacant" not in li.raw.get("gis", {})
    assert li.raw["burke_spine"]["vacant_land"] is True
    assert li.raw["burke_spine"]["vacant_land_as_of"] == "2017-01-10"


def test_enrich_does_not_invent_an_address_for_an_unaddressed_parcel(index):
    li = _listing(parcel_id="2647-50-6616")
    bs.enrich([li], auto_refresh=False)
    assert li.street_address is None               # LOCATION_A was "0   WILL HUDSON RD"
    assert li.city == "Connelly Springs"           # the rest of the record still lands


def test_enrich_flags_a_government_owned_parcel(index):
    li = _listing(parcel_id="1772372806")
    stats = bs.enrich([li], auto_refresh=False)
    assert stats["govt_owned"] == 1
    assert li.raw["burke_spine"]["govt_owned"]["government"] == "TOWN OF GLEN ALPINE"


def test_eligibility_is_burke_nc_with_a_parcel(index):
    assert bs.is_eligible(_listing(parcel_id="2703905385"))
    assert bs.is_eligible(_listing(parcel_id="2703905385", county="Burke County"))
    assert not bs.is_eligible(_listing(parcel_id="2703905385", county="Catawba"))
    assert not bs.is_eligible(_listing(parcel_id="2703905385", state="SC"))
    assert not bs.is_eligible(_listing(parcel_id=""))


def test_enrich_is_idempotent(index):
    li = _listing(parcel_id="2703905385")
    first = bs.enrich([li], auto_refresh=False)
    snapshot = json.dumps(li.raw, sort_keys=True, default=str)
    second = bs.enrich([li], auto_refresh=False)
    assert second["fields_filled"] == 0
    assert json.dumps(li.raw, sort_keys=True, default=str) == snapshot
    assert first["matched"] == second["matched"] == 1


def test_kill_switch(index, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_BURKE_SPINE", "0")
    li = _listing(parcel_id="2703905385")
    assert bs.enrich([li], auto_refresh=False)["matched"] == 0
    assert li.raw == {}


# ------------------------------------------------------------------ privacy --

def test_sensitive_columns_are_dropped_before_they_reach_a_record(monkeypatch):
    """Lincoln has historically exposed TCSSN on a public layer. If a Burke
    layer ever grows one, the allow-list must not carry it out of fetch_layer."""
    captured = {}

    def fake_get(url, params, timeout=120.0):
        captured["outFields"] = params["outFields"]
        return {"features": [{"attributes": {"PIN": "1791609195", "REID": "2366",
                                             "TCSSN1": "123-45-6789",
                                             "DOB": "1950-01-01"}}]}

    monkeypatch.setattr(bs, "_get_json", fake_get)
    rows = bs.fetch_layer(bs.ROLL_URL, ("PIN", "REID", "TCSSN1", "DOB"), "FID", size=1000)
    assert "TCSSN1" not in captured["outFields"] and "DOB" not in captured["outFields"]
    assert rows == [{"PIN": "1791609195", "REID": "2366"}]


def test_field_allow_lists_carry_no_sensitive_column():
    for fields in (bs._VACANT_FIELDS, bs._BIG_FIELDS, bs._ROLL_FIELDS, bs._GOVT_FIELDS):
        assert not [f for f in fields if bs._SENSITIVE_RE.search(f)]


def test_no_wildcard_outfields_in_the_module_code():
    """Docstrings and comments discuss outFields=*; the CODE must never emit one."""
    import io
    import tokenize

    src = Path(bs.__file__).read_text()
    code = "".join(
        tok.string for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        or (tok.type == tokenize.STRING and not tok.line.strip().startswith(('"""', "'''")))
    )
    assert "outFields=*" not in code
    assert '"*"' not in code and "'*'" not in code


# --------------------------------------------------------------- pagination --

def test_fetch_layer_pages_with_offset_and_a_stable_sort(monkeypatch):
    """Without orderByFields the server may reorder between pages and the
    offsets silently duplicate/drop rows."""
    pages = [
        {"features": [{"attributes": {"PIN": str(i)}} for i in range(1000)]},
        {"features": [{"attributes": {"PIN": str(1000 + i)}} for i in range(7)]},
    ]
    seen: list[dict] = []

    def fake_get(url, params, timeout=120.0):
        seen.append(params)
        return pages[len(seen) - 1]

    monkeypatch.setattr(bs, "_get_json", fake_get)
    rows = bs.fetch_layer(bs.VACANT_URL, ("PIN",), "OID", size=1000)
    assert len(rows) == 1007
    assert [p["resultOffset"] for p in seen] == [0, 1000]
    assert all(p["orderByFields"] == "OID" for p in seen)
    assert all(p["returnGeometry"] == "false" for p in seen)


def test_fetch_layer_raises_on_an_arcgis_error_envelope(monkeypatch):
    """ArcGIS answers 200 with an error body; a silent empty list would look
    like a legitimately empty layer and quietly wipe the index."""
    monkeypatch.setattr(bs, "_get_json",
                        lambda url, params, timeout=120.0: {"error": {"code": 400}})
    with pytest.raises(RuntimeError):
        bs.fetch_layer(bs.ROLL_URL, ("PIN",), "FID")


def test_layer_signature_survives_a_missing_last_edit_date(monkeypatch):
    """Vacant_BurkeCo reports editingInfo.lastEditDate = None; the row count has
    to carry the change token on its own there."""
    monkeypatch.setattr(bs, "_get_json", lambda url, params, timeout=60:
                        {"count": 21879} if params.get("returnCountOnly")
                        else {"editingInfo": {"lastEditDate": None}})
    assert bs.layer_signature(bs.VACANT_URL) == {"count": 21879, "last_edit": None}


def test_refresh_skips_the_pull_when_the_cache_is_fresh(monkeypatch, tmp_path):
    import time
    monkeypatch.setattr(bs, "_META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(bs, "_INDEX_PATH", tmp_path / "idx.json.gz")
    (tmp_path / "idx.json.gz").write_bytes(b"")
    (tmp_path / "meta.json").write_text(json.dumps({"built_at": time.time()}))

    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("refresh hit the network with a fresh cache")

    monkeypatch.setattr(bs, "_get_json", boom)
    assert bs.refresh()["built_at"] > 0
