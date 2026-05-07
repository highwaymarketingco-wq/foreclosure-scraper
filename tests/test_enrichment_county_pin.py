"""Pin the case-pinned county enforcer.

Run #16 forensics: 15 NC eCourts listings had their county silently
overwritten by cross-county defendant-name GIS matches in earlier
address enrichments. This enforcement pass runs LAST and re-tags
county from the case# (which encodes venue per NCGS §45-21.2 / SC
§15-11-10), AND nulls out a real-looking street_address that came
from the wrong county.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_county_pin import (
    NC_COURT_ID_BY_CODE,
    SC_COUNTY_BY_CODE,
    decode_case_pinned_county,
    enforce_case_pinned_county,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, case_number: str | None = None, state: str | None = None,
        county: str | None = None, street_address: str | None = None,
        source: str = "test", **kw) -> Listing:
    base = dict(
        source=source,
        source_url=f"https://example.com/{case_number or 'x'}",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        case_number=case_number,
        state=state,
        county=county,
        street_address=street_address,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---- decode_case_pinned_county ----

def test_sc_case_decodes_to_county():
    assert decode_case_pinned_county("2024-CP-30-12345", "SC") == "Laurens"
    assert decode_case_pinned_county("2024-CP-10-00001", "SC") == "Charleston"
    assert decode_case_pinned_county("2024-CP-46-99999", "SC") == "York"


def test_nc_case_decodes_to_county():
    assert decode_case_pinned_county("26M000113-640", "NC") == "New Hanover"
    assert decode_case_pinned_county("26M000463-910", "NC") == "Wake"
    assert decode_case_pinned_county("26M000218-400", "NC") == "Guilford"
    assert decode_case_pinned_county("26M000131-890", "NC") == "Union"


def test_unknown_court_id_returns_none():
    """Tyler portal has gaps in the 000-999 court ID range; unknown IDs
    must return None rather than guessing."""
    assert decode_case_pinned_county("26M000001-999", "NC") is None


def test_non_sc_cp_format_returns_none():
    assert decode_case_pinned_county("RANDOM-1234", "SC") is None


def test_state_mismatch_returns_none():
    """SC case# under state=NC: don't decode (case format won't match)."""
    assert decode_case_pinned_county("2024-CP-30-12345", "NC") is None


def test_no_state_or_case_returns_none():
    assert decode_case_pinned_county(None, "NC") is None
    assert decode_case_pinned_county("26M000113-640", None) is None


# ---- enforce_case_pinned_county ----

def test_nc_wrong_county_retagged_address_nulled():
    """Run #16 scenario: case# pins New Hanover (640) but cross-county
    GIS match left county=Burke + a real-looking address. Must retag +
    null."""
    li = _li(
        case_number="26M000113-640",
        state="NC",
        county="Burke",
        street_address="564 HICKORY AIRPORT RD",
    )
    stats = enforce_case_pinned_county([li])
    assert li.county == "New Hanover"
    assert li.street_address is None  # wrong-county address nulled
    cp = li.raw["county_pin"]
    assert cp["original_county"] == "Burke"
    assert cp["pinned_to"] == "New Hanover"
    assert cp["address_nulled"] is True
    assert cp["statute"] == "NCGS §45-21.2"
    assert stats["retagged_county"] == 1
    assert stats["address_nulled"] == 1


def test_sc_wrong_county_retagged_address_nulled():
    """Same bug in SC — case# pins Laurens (30) but listing tagged Charleston."""
    li = _li(
        case_number="2024-CP-30-12345",
        state="SC",
        county="Charleston",
        street_address="123 King St",
    )
    enforce_case_pinned_county([li])
    assert li.county == "Laurens"
    assert li.street_address is None
    assert li.raw["county_pin"]["statute"] == "SC Code §15-11-10"


def test_synthesized_placeholder_address_kept():
    """If street_address is already a synthesized placeholder ('Lis Pendens
    26M... — Smith'), don't null it — the user already knows it's not real,
    and the synthesizer will re-make it next run. Just retag county."""
    li = _li(
        case_number="26M000218-400",
        state="NC",
        county="Mecklenburg",
        street_address="Lis Pendens 26M000218-400 — Henry, Collin G, Sr.",
    )
    enforce_case_pinned_county([li])
    assert li.county == "Guilford"
    # Synthesized placeholder kept (still labeled as not-real)
    assert li.street_address is not None
    assert li.raw["county_pin"]["address_nulled"] is False


def test_already_correct_county_no_change():
    """Listing with case# pinning Wake AND county=Wake: no change."""
    li = _li(
        case_number="26M000463-910",
        state="NC",
        county="Wake",
        street_address="123 Real St",
    )
    enforce_case_pinned_county([li])
    assert li.county == "Wake"
    assert li.street_address == "123 Real St"
    assert "county_pin" not in li.raw  # no correction marker
    # stats reflect already-correct
    stats = enforce_case_pinned_county([li])  # idempotent
    assert stats["already_correct"] == 1


def test_no_decodable_case_skipped():
    """Listings without a case# (or with a case# the regex doesn't match)
    are left alone."""
    li = _li(
        case_number=None,
        state="NC",
        county="Wake",
    )
    stats = enforce_case_pinned_county([li])
    assert stats["no_case_decode"] == 1
    assert li.county == "Wake"


def test_idempotent():
    """Running twice on the same data is a no-op after the first pass."""
    li = _li(
        case_number="26M000113-640",
        state="NC",
        county="Burke",
        street_address="564 HICKORY AIRPORT RD",
    )
    s1 = enforce_case_pinned_county([li])
    s2 = enforce_case_pinned_county([li])
    assert s1["retagged_county"] == 1
    assert s2["retagged_county"] == 0
    assert s2["already_correct"] == 1


def test_full_nc_court_id_mapping_is_complete():
    """All 100 NC counties (NC has 100 counties) should be in the court
    ID table. This catches a future case where a new county shows up
    in the data and we silently fail to retag it."""
    # NC has exactly 100 counties.
    assert len(NC_COURT_ID_BY_CODE) == 100


def test_sc_county_mapping_is_complete():
    """SC has 46 counties (codes 01-46)."""
    assert len(SC_COUNTY_BY_CODE) == 46


def test_real_run16_mismatches_all_get_fixed():
    """End-to-end: the actual 15 NC mismatches observed in Run #16 all
    get retagged correctly."""
    cases = [
        ("26M000113-640", "Burke", "New Hanover"),
        ("26M000486-910", "Polk", "Wake"),
        ("26M000107-310", "Polk", "Durham"),
        ("26M000218-400", "Mecklenburg", "Guilford"),
        ("26M000221-400", "Transylvania", "Guilford"),
        ("26M000131-890", "Mecklenburg", "Union"),
        ("26M000014-580", "Mecklenburg", "McDowell"),
        ("26M000046-120", "Henderson", "Cabarrus"),
        ("26M000125-330", "Burke", "Forsyth"),
        ("26M000776-910", "Henderson", "Wake"),
        ("26M000759-590", "Polk", "Mecklenburg"),
        ("26M000776-590", "Henderson", "Mecklenburg"),
        ("26M000128-330", "Mecklenburg", "Forsyth"),
        ("26M000133-310", "Transylvania", "Durham"),
        ("26M000091-500", "Transylvania", "Johnston"),
    ]
    listings = [
        _li(case_number=cn, state="NC", county=wrong)
        for (cn, wrong, _) in cases
    ]
    enforce_case_pinned_county(listings)
    for li, (cn, _, expected) in zip(listings, cases):
        assert li.county == expected, (
            f"case={cn} expected county={expected} got={li.county}"
        )
