"""Multi-year delinquency: year resolution, real-property filter, history math.

Fixtures in tests/fixtures/multi_year_delinquent_tax_rows.json are field-for-field
captures of the live ArcGIS attribute payloads (2026-08-03).

What is locked in here is everything that silently rots if a county reshuffles
its services:
  * Buncombe's year comes from ``levy_year`` in the DATA, because the service
    titled "Unpaid Property Bills from 2021" holds levy year 2022.
  * Oconee/Pickens take the year from the LAYER NAME, because their ``TAXYEAR``
    column is a CAMA-snapshot field (dqnt_2023 carries TAXYEAR=2024).
  * ``pin<>''`` is the only thing separating 1,076 real-property bills from
    6,846 vehicle/business-personal bills in one Buncombe service.
  * the outFields allowlist is intersected with the live schema (never ``*``).
  * the current-levy year is excluded from the "matured" arrears count so the
    entire county's unpaid current bill run doesn't read as distress.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.counties_generic import (
    multi_year_delinquent_tax as myd,
)

FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "multi_year_delinquent_tax_rows.json").read_text()
)


def _layer(county: str, year: int, fields: myd._Fields, **kw) -> myd._Layer:
    state = "NC" if county == "Buncombe" else "SC"
    return myd._Layer(
        state=state, county=county, year=year, url="https://example.invalid/0",
        fields=fields, page_url="https://example.invalid/",
        label=f"{county.lower()}:{year}", **kw,
    )


BUNC = lambda y: _layer("Buncombe", y, myd._BUNCOMBE_FIELDS)          # noqa: E731
OCON = lambda y, f=myd._OCONEE_DT_FIELDS: _layer("Oconee", y, f)      # noqa: E731
PICK = lambda y, f=myd._PICKENS_FULL_FIELDS: _layer("Pickens", y, f)  # noqa: E731


# --------------------------------------------------------------------------
# privacy / query construction
# --------------------------------------------------------------------------
def test_out_fields_is_always_an_explicit_allowlist_never_star():
    for flds in (myd._BUNCOMBE_FIELDS, myd._OCONEE_DT_FIELDS,
                 myd._OCONEE_DT_FIELDS_LEGACY, myd._OCONEE_2015_FIELDS,
                 myd._PICKENS_FULL_FIELDS, myd._PICKENS_THIN_FIELDS,
                 myd._PICKENS_AD_FIELDS):
        out = flds.out_fields()
        assert out and "*" not in out
        # No SSN/DOB-shaped column may ever be requested (Lincoln-County rule).
        low = out.lower()
        for banned in ("ssn", "social", "dob", "birth"):
            assert banned not in low


def test_out_fields_intersects_with_the_live_schema():
    """ArcGIS 400s the whole query if ONE requested column is unknown — which is
    how every Pickens layer failed before this filter existed (dqnt_2023 has no
    Max_AMT_DU; the 2025 news-ad layer has no MAP_PARCEL)."""
    available = frozenset({"PIN", "NAME1", "LOCADD", "AMOUNT_DUE", "ACRES"})
    got = myd._PICKENS_FULL_FIELDS.out_fields(available).split(",")
    assert set(got) <= available
    assert "PIN" in got and "AMOUNT_DUE" in got
    assert "Max_AMT_DU" not in got and "MAP_PARCEL" not in got


# --------------------------------------------------------------------------
# Buncombe: real property only, owner/situs assembly
# --------------------------------------------------------------------------
def test_buncombe_personal_property_row_has_no_parcel_and_is_dropped():
    """Vehicle / business-personal bills carry pin='' and are 6,846 of the 7,922
    rows in the 2025 service. Their address_line1 is a mailing address, not a
    parcel — they are not leads."""
    assert myd.row_to_obs(FIX["buncombe_2025_personal_property_no_pin"],
                          BUNC(2025)) is None


def test_buncombe_owner_and_situs_come_from_the_right_columns():
    key, ob = myd.row_to_obs(FIX["buncombe_2025_real_property"], BUNC(2025))
    assert key == "960810874500000"  # 9608-10-8745-00000, punctuation stripped
    assert ob.owner == "CONNER RICKEY DEWAYNE & CONNER AMANDA LAUREL"
    assert ob.situs == "1068 MONTE VISTA RD"
    assert ob.amount == 890.17
    assert ob.value == 130600.0
    assert ob.acres == 1.0


def test_buncombe_situs_is_not_the_mailing_address():
    """house_num='0' + street 'TIPTON HILL RD' is the parcel; '23 BULLMAN DR' is
    where the taxpayer gets mail. Confusing the two invents a fake situs and
    destroys the absentee signal."""
    _, ob = myd.row_to_obs(FIX["buncombe_2025_absentee_situs_differs"], BUNC(2025))
    assert ob.situs == "TIPTON HILL RD"
    assert ob.mailing.startswith("23 BULLMAN DR")


def test_buncombe_keeps_the_owed_components():
    _, ob = myd.row_to_obs(FIX["buncombe_2024_real_property"], BUNC(2024))
    assert ob.amount == 924.10
    assert ob.extra["interest_due"] == 44.00
    assert ob.extra["levy_year"] == "2024"


# --------------------------------------------------------------------------
# Oconee / Pickens row shapes
# --------------------------------------------------------------------------
def test_oconee_money_parses_from_text_and_from_float():
    """DT2023 stores ' $1,979.70' as TEXT; DT2024/DT2025 store a float."""
    _, legacy = myd.row_to_obs(FIX["oconee_dt2023_text_money"],
                               OCON(2023, myd._OCONEE_DT_FIELDS_LEGACY))
    assert legacy.amount == 1979.70
    assert legacy.owner.startswith("ROBINSON BELINDA A")
    _, modern = myd.row_to_obs(FIX["oconee_dt2025_float_money"], OCON(2025))
    assert modern.amount == 201.58
    assert modern.owner == "HILL ASHLEY P"
    # X/Y are plain attribute columns, already WGS84.
    assert modern.lat == pytest.approx(34.9423, abs=1e-3)
    assert modern.lng == pytest.approx(-83.0388, abs=1e-3)


def test_pickens_zip_plus_four_int_is_trimmed_to_five():
    """Pickens stores ZIP as an int that may already carry the +4 (296730000)."""
    _, ob = myd.row_to_obs(FIX["pickens_dqnt_2024_zip_plus_four_int"],
                           PICK(2024))
    assert ob.zip_code == "29640"          # situs zip, not the mailing zip
    assert ob.situs == "153 ROBERT P JEANES RD"
    assert ob.amount == 212.24             # Max_AMT_DU on this year's layer
    assert ob.lat == pytest.approx(34.8475, abs=1e-3)


def test_pickens_blank_situs_placeholders_do_not_become_addresses():
    """LOCADD=' ' / LOCCITY=' ' / LOCZIP=0 mean 'absent', not an address."""
    _, ob = myd.row_to_obs(FIX["pickens_dqnt_2023_out_of_state"], PICK(2023))
    assert ob.situs is None and ob.city is None and ob.zip_code is None
    assert ob.mail_state == "FL"


def test_pickens_thin_layer_without_owner_still_yields_a_parcel_year():
    """del_2021 / delinquent_2020 have no owner column. They still have to
    contribute a YEAR to the history — that is the whole point."""
    key, ob = myd.row_to_obs(FIX["pickens_del_2021_thin_no_owner"],
                             PICK(2021, myd._PICKENS_THIN_FIELDS))
    assert key == "403700832164"   # 4037-00-83-2164, punctuation stripped
    assert ob.owner is None and ob.year == 2021


# --------------------------------------------------------------------------
# current-levy detection
# --------------------------------------------------------------------------
def test_current_levy_year_flags_buncombes_whole_county_bill_run():
    """Live 2026-08-03 shape: 103,285 real-property parcels in levy 2026 vs
    1,076 in 2025. Without this, every taxpaying parcel in the county reads as
    distressed."""
    assert myd.current_levy_year({2024: 376, 2025: 1076, 2026: 103285}) == 2026


def test_current_levy_year_leaves_sc_past_due_lists_alone():
    """Oconee's newest roll (DT2025, 645) is already a past-due list, only ~1.3x
    the prior year — it is real arrears, not an un-matured levy."""
    assert myd.current_levy_year({2023: 440, 2024: 476, 2025: 645}) is None
    assert myd.current_levy_year({2024: 954, 2025: 412}) is None
    assert myd.current_levy_year({2025: 645}) is None


# --------------------------------------------------------------------------
# history math
# --------------------------------------------------------------------------
def _obs(year, amount=None, **kw):
    return myd._Obs(year=year, amount=amount, layer=f"L{year}", **kw)


def test_single_year_parcel_is_not_emitted():
    """A one-off missed bill is already covered by the single-year sources; the
    repeat signal is this source's entire reason to exist."""
    assert myd.build_listing("SC", "Oconee", "P1", [_obs(2025, 500.0)],
                             "https://x.invalid", None) is None


def test_current_levy_only_parcel_is_not_emitted():
    """In the current levy but nowhere else = simply hasn't paid this cycle."""
    assert myd.build_listing("NC", "Buncombe", "P1", [_obs(2026, 900.0)],
                             "https://x.invalid", 2026) is None


def test_current_levy_plus_one_matured_year_is_emitted():
    li = myd.build_listing("NC", "Buncombe", "P1",
                           [_obs(2025, 890.0), _obs(2026, 940.0)],
                           "https://x.invalid", 2026)
    assert li is not None
    b = li.raw["multi_year_delinquent_tax"]
    assert b["years"] == [2025, 2026]
    assert b["matured_years"] == [2025]
    assert b["current_levy_year"] == 2026
    assert b["in_current_levy"] is True
    assert b["total_owed"] == pytest.approx(1830.0)
    assert b["matured_owed"] == pytest.approx(890.0)


def test_history_fields_for_a_five_year_repeat_offender():
    obs = [_obs(2021, 400.0, owner="OLD OWNER"), _obs(2022, 500.0),
           _obs(2023, 600.0), _obs(2024, 700.0),
           _obs(2025, 800.0, owner="NEW OWNER", situs="9 MAIN ST")]
    li = myd.build_listing("SC", "Pickens", "P9", obs, "https://x.invalid", None)
    b = li.raw["multi_year_delinquent_tax"]
    assert b["years_delinquent"] == 5
    assert b["matured_years_delinquent"] == 5
    assert b["consecutive_years"] == 5
    assert b["first_year"] == 2021 and b["latest_year"] == 2025
    assert b["total_owed"] == pytest.approx(3000.0)
    assert b["trend"] == "growing"
    # SC lists publish an advertised balance; Buncombe publishes a per-levy-year
    # bill. The label keeps the sum from being read as a payoff quote.
    assert b["amount_basis"] == "advertised_balance"
    assert b["still_accruing"] is True
    # Newest non-empty value wins for descriptive fields.
    assert li.owner_name == "NEW OWNER" and li.street_address == "9 MAIN ST"
    assert li.judgment_amount == pytest.approx(3000.0)
    assert li.listing_type.value == "tax_lien"
    assert li.foreclosure_process == "tax"


def test_still_accruing_is_measured_against_the_countys_newest_roll():
    """Regression: comparing against max(this parcel's own years) is trivially
    true, which made the flag meaningless (it read True for 100% of the SC
    parcels). It has to compare against the newest roll the COUNTY publishes."""
    stale = myd.build_listing("SC", "Pickens", "P20",
                              [_obs(2020, 100.0), _obs(2022, 100.0)],
                              "https://x.invalid", None, county_latest_year=2025)
    assert stale.raw["multi_year_delinquent_tax"]["still_accruing"] is False
    live = myd.build_listing("SC", "Pickens", "P21",
                             [_obs(2024, 100.0), _obs(2025, 100.0)],
                             "https://x.invalid", None, county_latest_year=2025)
    assert live.raw["multi_year_delinquent_tax"]["still_accruing"] is True
    assert live.raw["multi_year_delinquent_tax"]["county_latest_year"] == 2025


def test_consecutive_years_counts_the_longest_run_not_the_total():
    obs = [_obs(2015, 100.0), _obs(2023, 100.0), _obs(2024, 100.0),
           _obs(2025, 100.0)]
    b = myd.build_listing("SC", "Oconee", "P2", obs,
                          "https://x.invalid", None).raw["multi_year_delinquent_tax"]
    assert b["years_delinquent"] == 4
    assert b["consecutive_years"] == 3


def test_trend_shrinking_and_flat():
    shrink = myd.build_listing("SC", "Oconee", "P3",
                               [_obs(2023, 2000.0), _obs(2025, 500.0)],
                               "https://x.invalid", None)
    assert shrink.raw["multi_year_delinquent_tax"]["trend"] == "shrinking"
    flat = myd.build_listing("SC", "Oconee", "P4",
                             [_obs(2023, 1000.0), _obs(2025, 1010.0)],
                             "https://x.invalid", None)
    assert flat.raw["multi_year_delinquent_tax"]["trend"] == "flat"


def test_overlapping_layers_in_the_same_year_do_not_double_count():
    """Pickens publishes both a newspaper-ad layer and a posting layer for 2025;
    the same parcel appears in both. Summing them would inflate what is owed."""
    obs = [_obs(2024, 300.0), _obs(2025, 638.80), _obs(2025, 638.80)]
    b = myd.build_listing("SC", "Pickens", "P5", obs,
                          "https://x.invalid", None).raw["multi_year_delinquent_tax"]
    assert b["years"] == [2024, 2025]
    assert b["total_owed"] == pytest.approx(938.80)


def test_owed_amount_never_lands_in_tax_value():
    """calc.py reads tax_value as the PROPERTY value (ARV = tax_value x 1.25).
    Writing taxes-owed there collapses the lead's economics to ~$1k."""
    li = myd.build_listing("NC", "Buncombe", "P6",
                           [_obs(2024, 924.10), _obs(2025, 890.17)],
                           "https://x.invalid", None)
    assert li.tax_value is None
    li2 = myd.build_listing("NC", "Buncombe", "P7",
                            [_obs(2024, 924.10, value=130600.0),
                             _obs(2025, 890.17, value=130600.0)],
                            "https://x.invalid", None)
    assert li2.tax_value == 130600.0
    assert li2.judgment_amount == pytest.approx(1814.27)
    assert li2.raw["multi_year_delinquent_tax"]["amount_basis"] == "annual_bill"


def test_tax_owed_enrichment_can_read_the_raw_block():
    """enrichment_tax_owed scans tax-ish sources for a generic amount key; the
    raw block has to expose total_due + year for it to stamp raw['tax_owed']."""
    from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed

    li = myd.build_listing("SC", "Oconee", "P8",
                           [_obs(2024, 476.0), _obs(2025, 645.0)],
                           "https://x.invalid", None)
    li.parcel_id = "035-00-01-005"
    enrich_tax_owed([li])
    assert li.raw["tax_owed"]["balance"] == pytest.approx(1121.0)
    assert li.raw["tax_owed"]["year"] == 2025


# --------------------------------------------------------------------------
# owner mailing / absentee
# --------------------------------------------------------------------------
def test_absentee_and_out_of_state_are_derived_from_the_tax_roll():
    """The roll already carries both situs and taxpayer mailing, so the absentee
    flag is free — no GIS round-trip needed."""
    li = myd.build_listing(
        "SC", "Pickens", "P10",
        [_obs(2023, 295.22, owner="DAVIS, JOHN THOMAS", situs="12 OAK ST",
              mailing="30343 TAKARA TERRACE MOUNT DORA FL 32757",
              mail_state="FL"),
         _obs(2024, 310.0)],
        "https://x.invalid", None)
    om = li.raw["owner_mailing"]
    assert om["absentee"] is True
    assert om["out_of_state"] is True
    assert om["mail_state"] == "FL"


def test_owner_occupied_parcel_is_not_flagged_absentee():
    li = myd.build_listing(
        "NC", "Buncombe", "P11",
        [_obs(2024, 924.10, situs="1068 MONTE VISTA RD",
              mailing="1068 MONTE VISTA RD CANDLER NC 28715", mail_state="NC"),
         _obs(2025, 890.17)],
        "https://x.invalid", None)
    om = li.raw["owner_mailing"]
    assert om["absentee"] is False and om["out_of_state"] is False


# --------------------------------------------------------------------------
# assemble(): cross-layer join
# --------------------------------------------------------------------------
def test_assemble_joins_the_same_parcel_across_years_and_counties():
    rows = [
        (BUNC(2024), [FIX["buncombe_2024_real_property"],
                      FIX["buncombe_2025_personal_property_no_pin"]]),
        (BUNC(2025), [FIX["buncombe_2025_real_property"],
                      FIX["buncombe_2025_absentee_situs_differs"]]),
        (PICK(2023), [FIX["pickens_dqnt_2023_local"]]),
        (PICK(2021, myd._PICKENS_THIN_FIELDS),
         [FIX["pickens_del_2021_thin_no_owner"]]),
    ]
    out = myd.assemble(rows)
    by_county = {li.county: li for li in out}
    # Buncombe: only the parcel present in BOTH 2024 and 2025 survives.
    b = by_county["Buncombe"]
    assert b.parcel_id == "9608-10-8745-00000"   # human-formatted id, not the key
    assert b.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025]
    assert b.raw["multi_year_delinquent_tax"]["total_owed"] == pytest.approx(1814.27)
    # Pickens: the thin 2021 layer has no owner, the 2023 layer does — the join
    # still produces a 2-year history.
    p = by_county["Pickens"]
    assert p.parcel_id == "4037-00-83-2164"
    assert p.raw["multi_year_delinquent_tax"]["years"] == [2021, 2023]
    assert p.owner_name == "LADD, PEGGY S."
    assert p.raw["multi_year_delinquent_tax"]["consecutive_years"] == 1


def test_assemble_dedupe_keys_are_unique_per_parcel():
    rows = [(BUNC(2024), [FIX["buncombe_2024_real_property"]]),
            (BUNC(2025), [FIX["buncombe_2025_real_property"]])]
    out = myd.assemble(rows)
    assert len(out) == 1
    assert out[0].dedupe_key() == "parcel:NC:buncombe:9608108745"


# --------------------------------------------------------------------------
# discovery guards
# --------------------------------------------------------------------------
def test_oconee_demo_layer_is_excluded_by_name():
    """Delinquent_Tax_Properties is a 2-row template whose owner is 'John Doe'
    at 'Your Town, State Zip'."""
    assert "delinquent_tax_properties" in myd._OCONEE_SKIP
    assert FIX["oconee_demo_layer_row"]["PROPERTYOWNER1"] == "John Doe"


def test_pickens_duplicate_and_flc_layers_are_excluded():
    assert "delqparcels_ad_paperlisting2" in myd._PICKENS_SKIP  # join duplicate
    assert "flc_2022" in myd._PICKENS_SKIP                      # post-sale, not arrears


def test_pickens_layer_name_regex_covers_all_three_prefixes():
    for name, year in (("delinquent_2020", 2020), ("del_2021", 2021),
                       ("dqnt_2022", 2022), ("dqnt_2024", 2024)):
        m = myd._PICKENS_YEAR_RE.match(name)
        assert m and int(m.group(1)) == year
    assert myd._PICKENS_YEAR_RE.match("dev_zones") is None
    assert myd._PICKENS_YEAR_RE.match("disadv_census") is None


def test_oconee_layer_name_regex_matches_dt_and_sale_layers_only():
    assert myd._OCONEE_DT_RE.match("DT2025").group(1) == "2025"
    assert myd._OCONEE_SALE_RE.match("DelqTaxSale_2015").group(1) == "2015"
    assert myd._OCONEE_DT_RE.match("Delinquent_Tax_Properties") is None


def test_scraper_is_registered_and_slug_is_stable():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    slugs = {s.slug for s in all_scrapers()}
    assert "counties.multi_year_delinquent_tax" in slugs
    assert myd.MultiYearDelinquency.slug == myd.SLUG


def test_source_must_be_dateless_ok():
    """An arrears history has no sale date; without this entry main.py's
    is_actionable() filter drops every single row."""
    from foreclosure_scraper import main

    assert myd.SLUG in main.DATELESS_OK_SOURCES, (
        f'add "{myd.SLUG}" to main.DATELESS_OK_SOURCES'
    )
