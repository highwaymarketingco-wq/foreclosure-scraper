"""Regression tests for the SC lis-pendens address resolver.

The corrector must produce CORRECT addresses (investors will use them)
and must REFUSE to commit when not confident. These tests pin every
policy decision so they don't drift on future weekly runs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.enrichment_lis_pendens_resolver import (
    _confident_match,
    _decode_case_county,
    _is_company,
    _is_placeholder,
    _is_target,
    _name_tokens,
    _resolve_address,
    enrich_lis_pendens_addresses,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


# ---------- _decode_case_county ----------

def test_decode_case_county_anderson():
    assert _decode_case_county("2026-CP-04-12345") == "Anderson"


def test_decode_case_county_charleston():
    assert _decode_case_county("2026-CP-10-99999") == "Charleston"


def test_decode_case_county_unknown():
    assert _decode_case_county("2026-CP-99-00001") is None


def test_decode_case_county_invalid_format():
    assert _decode_case_county("garbage") is None


def test_decode_case_county_none():
    assert _decode_case_county(None) is None


# ---------- _name_tokens ----------

def test_name_tokens_strips_stopwords():
    assert "JR" not in _name_tokens("HARRILL RONALD WAYNE JR")
    assert "RONALD" in _name_tokens("HARRILL RONALD WAYNE JR")


def test_name_tokens_strips_llc_etc():
    toks = _name_tokens("THE CLARITY COMPANY LLC")
    assert "CLARITY" in toks
    assert "LLC" not in toks
    assert "COMPANY" not in toks
    assert "THE" not in toks


def test_name_tokens_strips_personal_representative():
    toks = _name_tokens("Marcus Brown, Personal Representative")
    assert "MARCUS" in toks
    assert "BROWN" in toks
    assert "PERSONAL" not in toks
    assert "REPRESENTATIVE" not in toks


# ---------- _is_company ----------

def test_is_company_llc():
    assert _is_company("Smith Holdings LLC") is True


def test_is_company_individual():
    assert _is_company("John Smith") is False


def test_is_company_inc():
    assert _is_company("Acme Inc") is True


# ---------- _confident_match ----------

def test_confident_match_individual_full():
    # 2 distinctive tokens match, surname matches → confident
    assert _confident_match("Christina M Burke", "BURKE CHRISTINA M") is True


def test_confident_match_individual_surname_only_not_enough():
    # Only surname matches → not confident
    assert _confident_match("Christina M Burke", "BURKE JOHN") is False


def test_confident_match_llc_strict():
    # LLC requires every distinctive token
    assert _confident_match("THE CLARITY COMPANY LLC", "THE CLARITY COMPANY LLC") is True
    assert _confident_match("THE CLARITY COMPANY LLC", "OTHER CLARITY LLC") is False


def test_confident_match_jr_suffix_irrelevant():
    # "JR" is a stopword — match still confident
    assert _confident_match("Ronald Wayne Harrill Jr", "HARRILL RONALD WAYNE JR") is True


# ---------- _resolve_address policy ----------

LAURENS_SCHEMA = {
    "owner": ("Name1",), "situs": ("Property_A",),
    "situs_parts": ("Street_Num", "Street_Nam"),
    "mailing": ("Address1",), "city": ("Mailing_Ci",),
    "zip": ("ZIP_Code",), "parcel": ("TMS",), "owner_occ": ("Owner_Occu",),
}


def test_resolve_uses_real_situs_when_present():
    attrs = {
        "Name1": "BURKE CHRISTINA M",
        "Property_A": "204 W ROPER RD",
        "Mailing_Ci": "EASLEY  S.C. 29640",
        "ZIP_Code": "29640",
        "TMS": "265-00-00-025",
        "Owner_Occu": "Y",
    }
    out = _resolve_address(attrs, LAURENS_SCHEMA, "Christina M Burke")
    assert out["street_address"] == "204 W ROPER RD"
    assert out["address_source"] == "situs"
    assert out["city"] == "EASLEY"
    assert out["zip"] == "29640"
    assert out["parcel_id"] == "265-00-00-025"


def test_resolve_falls_back_to_mailing_for_homestead_individual():
    attrs = {
        "Name1": "BURKE CHRISTINA M",
        "Address1": "204 W ROPER RD",          # mailing only
        "Mailing_Ci": "EASLEY  S.C. 29640",
        "ZIP_Code": "29640",
        "TMS": "265",
        "Owner_Occu": "Y",
    }
    out = _resolve_address(attrs, LAURENS_SCHEMA, "Christina M Burke")
    assert out["street_address"] == "204 W ROPER RD"
    assert out["address_source"] == "mailing_homestead"


def test_resolve_refuses_mailing_when_po_box():
    attrs = {
        "Name1": "OWENS SAMUEL H JR",
        "Address1": "PO BOX 75",
        "ZIP_Code": "29323",
        "TMS": "002-00-00-030",
        "Owner_Occu": "Y",
    }
    out = _resolve_address(attrs, LAURENS_SCHEMA, "Samuel Herbert Owens Jr")
    assert "street_address" not in out
    # parcel still recorded
    assert out["parcel_id"] == "002-00-00-030"


def test_resolve_refuses_mailing_for_llc():
    """LLC mailing is the office, not the property."""
    attrs = {
        "Name1": "THE CLARITY COMPANY LLC",
        "Address1": "1140 WOODRUFF RD STE 106-214",
        "Mailing_Ci": "GREENVILLE SC",
        "TMS": "906-12-07-004",
    }
    out = _resolve_address(attrs, LAURENS_SCHEMA, "The Clarity Company LLC")
    assert "street_address" not in out
    assert out["parcel_id"] == "906-12-07-004"


def test_resolve_refuses_address_for_fiduciary_defendant():
    """Personal representative defendant — never commit address."""
    attrs = {
        "Name1": "CROWE KIMBERLY L",
        "Property_A": "7836 HWY 81 S",
        "Mailing_Ci": "STARR SC",
        "ZIP_Code": "29684",
        "TMS": "260-00-00-001",
        "Owner_Occu": "Y",
    }
    out = _resolve_address(attrs, LAURENS_SCHEMA, "Kimberly L Crowe As Personal Representative")
    assert out["_fiduciary"] is True
    assert "street_address" not in out
    # parcel still recorded for human review
    assert out["parcel_id"] == "260-00-00-001"


def test_resolve_strips_cherokee_leading_zero_zip():
    """Cherokee SCDOT layer pads zip+4 with leading zero. Real zip is 29340,
    not 02934."""
    schema = {
        "owner": ("SHEET1__Na",), "situs": (), "situs_parts": (),
        "mailing": ("SHEET1___1",), "city": ("SHEET1___2",),
        "zip": ("SHEET1__Zi",), "parcel": ("ParcelPoly",), "owner_occ": (),
    }
    attrs = {
        "SHEET1__Na": "MCDANIEL CHRISTIE M",
        "SHEET1___1": "169 HEMLOCK RD",
        "SHEET1___2": "GAFFNEY SC",
        "SHEET1__Zi": "0293400000",
        "ParcelPoly": "0010000123000",
    }
    out = _resolve_address(attrs, schema, "Christie M Mcdaniel")
    assert out["zip"] == "29340"


# ---------- _is_target ----------

def _li(**kw):
    base = dict(
        source="counties_sc.sc_public_index_lis_pendens",
        source_url="http://x", listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


def test_is_target_sc_lis_pendens():
    li = _li(state="SC", case_number="2026-CP-04-12345", defendant="X")
    assert _is_target(li) is True


def test_is_target_skips_non_sc():
    li = _li(state="NC", case_number="2026-CP-04-12345", defendant="X")
    assert _is_target(li) is False


def test_is_target_skips_no_case():
    li = _li(state="SC", defendant="X")
    assert _is_target(li) is False


def test_is_target_skips_unknown_county_code():
    li = _li(state="SC", case_number="2026-CP-99-00001", defendant="X")
    assert _is_target(li) is False


# ---------- end-to-end: county re-tag + confident GIS match ----------

def test_enrich_retags_wrong_county():
    """A listing tagged with the wrong county should have it corrected to
    the case#-decoded county on every weekly run."""
    li = _li(
        state="SC",
        county="Cherokee",                   # WRONG
        case_number="2026-CP-04-12345",      # → Anderson
        defendant="Smith John",
        street_address="Lis Pendens 2026-CP-04-12345 — Smith John",
    )
    # Make GIS query return nothing so we test ONLY the re-tag path.
    with patch(
        "foreclosure_scraper.enrichment_lis_pendens_resolver._query_layer",
        new=AsyncMock(return_value=[]),
    ):
        stats = asyncio.run(enrich_lis_pendens_addresses([li]))

    assert li.county == "Anderson", f"expected Anderson, got {li.county!r}"
    assert stats["retagged_county"] == 1
    assert stats["queried"] == 1
    assert stats["no_match"] == 1


def test_enrich_fills_address_from_confident_match():
    li = _li(
        state="SC",
        county="Pickens",
        case_number="2026-CP-39-00337",
        defendant="Ronnie L. Holder",
        street_address="Lis Pendens 2026-CP-39-00337 — Ronnie L. Holder",
    )
    fake_attrs = {
        "NAME1": "HOLDER RONNIE L",
        "LOCADD": "204 SPUR RD",
        "LOCCITY": "SIX MILE",
        "LOCZIP": "29682",
        "PIN": "4042-00-31-1956",
        "_centroid": (34.8, -82.8),
    }
    with patch(
        "foreclosure_scraper.enrichment_lis_pendens_resolver._query_layer",
        new=AsyncMock(return_value=[fake_attrs]),
    ):
        stats = asyncio.run(enrich_lis_pendens_addresses([li]))

    assert li.street_address == "204 SPUR RD"
    assert li.city == "SIX MILE"
    assert li.zip_code == "29682"
    assert li.parcel_id == "4042-00-31-1956"
    assert li.latitude == 34.8
    assert li.longitude == -82.8
    assert stats["address_filled"] == 1
    assert li.raw["lis_pendens_resolution"]["address_source"] == "situs"


def test_enrich_skips_ambiguous_multi_parcel():
    """Two confident hits for the same defendant → ambiguous, commit nothing
    but record candidates."""
    li = _li(
        state="SC",
        county="Pickens",
        case_number="2026-CP-39-00373",
        defendant="Melvin W Williford",
        street_address="Lis Pendens 2026-CP-39-00373 — Melvin W Williford",
    )
    candidates = [
        {"NAME1": "WILLIFORD MELVIN W", "PIN": "4053-13-04-8049",
         "LOCADD": "1 ONE ST", "_centroid": (34.8, -82.7)},
        {"NAME1": "WILLIFORD MELVIN W", "PIN": "4054-12-95-5550",
         "LOCADD": "2 TWO ST", "_centroid": (34.8, -82.6)},
    ]
    with patch(
        "foreclosure_scraper.enrichment_lis_pendens_resolver._query_layer",
        new=AsyncMock(return_value=candidates),
    ):
        stats = asyncio.run(enrich_lis_pendens_addresses([li]))

    assert li.street_address.startswith("Lis Pendens "), \
        "must NOT commit a single address when ambiguous"
    assert stats["ambiguous"] == 1
    assert li.raw["lis_pendens_resolution"]["ambiguous"] is True
    assert len(li.raw["lis_pendens_resolution"]["candidates"]) == 2


def test_enrich_skips_when_no_confident_match():
    """GIS returns hits but none satisfy confidence rule → no_match."""
    li = _li(
        state="SC",
        county="Pickens",
        case_number="2026-CP-39-00500",
        defendant="Christina M Burke",
        street_address="Lis Pendens 2026-CP-39-00500 — Christina M Burke",
    )
    # Only surname matches — not enough.
    weak = [{"NAME1": "BURKE JOHN", "LOCADD": "1 X ST", "_centroid": (1, 1)}]
    with patch(
        "foreclosure_scraper.enrichment_lis_pendens_resolver._query_layer",
        new=AsyncMock(return_value=weak),
    ):
        stats = asyncio.run(enrich_lis_pendens_addresses([li]))

    assert li.street_address.startswith("Lis Pendens ")
    assert stats["no_match"] == 1


def test_enrich_does_not_touch_real_addresses():
    """A listing that already has a real (non-placeholder) street_address
    should not be re-resolved (no GIS query)."""
    li = _li(
        state="SC",
        county="Anderson",                   # already correct
        case_number="2026-CP-04-12345",
        defendant="Smith John",
        street_address="123 Real Street",    # already filled
    )
    qm = AsyncMock(return_value=[])
    with patch(
        "foreclosure_scraper.enrichment_lis_pendens_resolver._query_layer",
        new=qm,
    ):
        stats = asyncio.run(enrich_lis_pendens_addresses([li]))

    assert qm.await_count == 0, "should not query GIS for real-address listings"
    assert stats["queried"] == 0
    assert li.street_address == "123 Real Street"
