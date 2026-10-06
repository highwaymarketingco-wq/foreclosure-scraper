"""dedupe(): a parcel id shared by many properties is no identity, no match key, and the address
written from it is no house number (2026-10-06, second identity fix).

THE BUG THIS PINS (replay of main.run()'s second dedupe on the 10/5 checkpoint, 13 counties)
    After the 2026-10-06 identity rule (240b8de9) one output row still held 608 different
    properties. Rutherford parcel 1654116, a church at the Rutherfordton county-seat point, sat on
    619 rows of 10 sources: the geocoder's Tier-4 fallback put each address-less row on its county
    seat and enrichment_parcel_from_geo took the parcel under that point. A resolver parcel was no
    identity, but pass 1 still BUCKETED the rows under it, and a 'parcel:' key counts as PARCEL
    evidence, which merges two unnumbered rows. scripts/fill_address_from_parcel.py then copied the
    parcel's situs onto the address-less rows, so 104 New Hanover lis pendens and divorces read
    '100 RALEIGH ST' (parcel 3115-88-8610.000) and merged on the address too. A SOURCE can also give
    one id to several houses: spartanburg_property_cleanup's 5-20-01-037.00 is on '113 OAKDALE
    COURT', '113 HOLMES DRIVE' and '113 WEST VICTORIA ROAD', and they merged (same number, same
    valid parcel).

Rows are the real shapes from that checkpoint; owner names are replaced.
"""
from __future__ import annotations

from foreclosure_scraper import placeholder_twins as pt
from foreclosure_scraper.board_dedupe_stream import _light_listing_for_dedupe
from foreclosure_scraper.dedupe import (
    OVERSHARED_MIN_STREETS, dedupe, identity, numbered_street, overshared_parcels,
)
from foreclosure_scraper.enrichment_address_final import enrich_with_address_synthesis
from foreclosure_scraper.models import Listing, ListingType

RUTH_SEAT = {"source": "nc_onemap_point", "lat": 35.371, "lng": -81.957}      # county seat
WILM_POINT = {"source": "nc_onemap_point", "lat": 34.1808, "lng": -77.9462}   # shared city point


def _row(n, source, *, county, state="NC", addr=None, parcel=None, case=None, defendant=None,
         lt=ListingType.TAX_LIEN, desc=None, raw=None, zip_code=None, city=None):
    return Listing(source=source, source_url=f"https://example.test/{source}/{n}", listing_type=lt,
                   state=state, county=county, street_address=addr, parcel_id=parcel,
                   case_number=case, defendant=defendant, description=desc, zip_code=zip_code,
                   city=city, raw={f"_rid_{n}": 1, **(raw or {})})


def _rids(out):
    return sorted(sorted(k for k in li.raw if k.startswith("_rid_")) for li in out)


def _groups(out):
    return [g for g in _rids(out) if len(g) > 1]


# ------------------------------------------------------------------ 1654116: the county-seat parcel
def _ruth_tax(n, name, acct):
    return _row(n, "counties_nc.rutherford_tax", county="Rutherford", parcel="1654116",
                desc=f"{name} — Rutherford NC delinquent tax $620 owed — parcel {acct} — TY2025",
                raw={"parcel_from_geo": dict(RUTH_SEAT), "geo_imprecise": "centroid_snap"})


def _ruth_divorce(n, case, name):
    return _row(n, "counties_nc.nc_ecourts_divorce", county="Rutherford", parcel="1654116",
                case=case, defendant=name, lt=ListingType.DIVORCE_NOTICE,
                raw={"parcel_from_geo": dict(RUTH_SEAT), "geo_imprecise": "centroid_snap"})


def _ruth_land(n, city):
    """A land listing given the church's situs by fill_address_from_parcel."""
    return _row(n, "national.landandfarm", county="Rutherford", parcel="1654116",
                addr="252 N WASHINGTON ST", city=city, lt=ListingType.UNKNOWN,
                raw={"parcel_from_geo": dict(RUTH_SEAT), "geo_imprecise": "centroid_snap",
                     "situs_address_source": "parcel_cache:exact"})


def _ruth_rows():
    return [
        _ruth_tax(1, "Parcel — DOE, JANE", "422620"),
        _ruth_tax(2, "Parcel — ROE, RICHARD", "426770"),
        _ruth_tax(3, "Parcel — POE, EDGAR", "514474"),
        _ruth_divorce(4, "26CVD000111-800", "SMITH, ALEX"),
        _ruth_divorce(5, "26CVD000222-800", "JONES, BLAKE"),
        _ruth_land(6, "Bostic"), _ruth_land(7, "Rutherfordton"), _ruth_land(8, "Lake Lure"),
    ]


def test_the_county_seat_parcel_no_longer_merges_different_properties():
    rows = _ruth_rows()
    enrich_with_address_synthesis(rows)          # main.run() synthesizes before dedupe2
    out = dedupe(rows)
    assert _groups(out) == []
    assert len(out) == 8


def test_address_less_rows_off_a_fallback_parcel_do_not_fall_into_one_url_bucket():
    """Without the parcel key, an address-less row must not be keyed by a URL that one county
    roll's PDF gives to every row (the board's 4,229 Guilford ptscloud rows share one)."""
    rows = [_ruth_tax(i, f"Parcel — OWNER {i}", str(422620 + i)) for i in range(1, 5)]
    for li in rows:
        li.source_url = "https://example.test/rutherford/TR-452.pdf"
        li.description = None
    assert len(dedupe(rows)) == 4


# --------------------------------------------------- 100 RALEIGH ST: the situs of a shared-point parcel
def _raleigh(n, case, name):
    return _row(n, "counties_nc.nc_ecourts_lis_pendens", county="New Hanover",
                parcel="3115-88-8610.000", addr="100 RALEIGH ST", case=case, defendant=name,
                lt=ListingType.LIS_PENDENS,
                raw={"parcel_from_geo": dict(WILM_POINT), "geo_imprecise": "centroid_snap",
                     "situs_address_source": "parcel_cache:exact"})


def test_a_situs_copied_from_a_fallback_point_parcel_is_no_house_number():
    rows = [_raleigh(1, "26CV000101-640", "DOE, JANE"), _raleigh(2, "26CV000102-640", "ROE, RICH"),
            _raleigh(3, "26CV000103-640", "POE, EDGAR"), _raleigh(4, "26CV000104-640", "LEE, ANN")]
    assert identity(rows[0]).hn == ""
    assert len(dedupe(rows)) == 4
    # same case scraped twice still merges
    rows.append(_raleigh(5, "26CV000101-640", "DOE, JANE"))
    assert _groups(dedupe(rows)) == [["_rid_1", "_rid_5"]]


def test_the_same_situs_on_a_row_whose_own_point_resolved_it_still_counts():
    """A parcel resolved at the row's own precise point (a UST facility's coordinates) is a fine
    parcel; its situs stays a house number, as before."""
    raw = {"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.571105, "lng": -82.593601},
           "situs_address_source": "parcel_cache:exact"}
    a = _row(1, "counties_generic.state_contamination.nc_ust_incidents", county="Buncombe",
             parcel="963812512100000", addr="191 BREVARD RD", lt=ListingType.UNKNOWN, raw=raw)
    assert identity(a).hn == "191"
    b = _row(2, "counties_nc.buncombe_tax", county="Buncombe", parcel="9638125121",
             addr="191 BREVARD RD")
    assert _groups(dedupe([a, b])) == [["_rid_1", "_rid_2"]]


def test_two_unnumbered_rows_on_a_precise_resolver_parcel_still_merge():
    raw = {"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.5367306, "lng": -82.7501403}}
    a = _row(1, "counties_generic.state_contamination.nc_ust_incidents", county="Buncombe",
             parcel="868741417400000", addr="OLD US 19 23 HWY", lt=ListingType.UNKNOWN, raw=raw)
    b = _row(2, "counties_generic.state_contamination.nc_dam_safety", county="Buncombe",
             parcel="868741417400000", lt=ListingType.UNKNOWN, raw=dict(raw))
    assert _groups(dedupe([a, b])) == [["_rid_1", "_rid_2"]]


# ------------------------------------------------------- 5-20-01-037.00: one source id, three houses
CLEANUP = "counties_generic.arcgis_distress.spartanburg_property_cleanup"


def _cleanup(n, addr, parcel="5-20-01-037.00"):
    return _row(n, CLEANUP, state="SC", county="Spartanburg", addr=addr, parcel=parcel,
                lt=ListingType.UNKNOWN)


def test_numbered_street_counts_spellings_of_one_address_once():
    assert numbered_street("113 OAKDALE COURT, SPARTANBURG, 29306") == "113 oakdale ct"
    assert numbered_street("113 Oakdale Ct") == "113 oakdale ct"
    assert numbered_street("113 WEST VICTORIA ROAD, SPARTANBURG, 29301") == "113 victoria rd"
    assert numbered_street("000141 LEVI DR") == "141 levi dr"
    assert numbered_street("4518 WYNBROOK WY #15") == numbered_street("4518 WYNBROOK WY #27")
    assert numbered_street("0 PATCH DR") == "" and numbered_street("PATCH DR") == ""


def test_a_source_parcel_on_three_streets_is_overshared_two_is_not():
    three = [_cleanup(1, "113 OAKDALE COURT, SPARTANBURG, 29306"),
             _cleanup(2, "113 HOLMES DRIVE, SPARTANBURG, 29303"),
             _cleanup(3, "113 WEST VICTORIA ROAD, SPARTANBURG, 29301")]
    ref = pt.parcel_ref("SC", "Spartanburg", "5-20-01-037.00")
    assert OVERSHARED_MIN_STREETS == 3
    assert overshared_parcels(three) == frozenset({ref})
    assert overshared_parcels(three[:2]) == frozenset()
    assert pt.parcel_key("SC", "Spartanburg", "5-20-01-037.00") == ref
    assert pt.parcel_key("SC", "Spartanburg", "5-20-01-037.00", overshared_parcels(three)) is None


def test_three_houses_under_one_source_parcel_stay_three_rows():
    rows = [_cleanup(1, "113 OAKDALE COURT, SPARTANBURG, 29306"),
            _cleanup(2, "113 HOLMES DRIVE, SPARTANBURG, 29303"),
            _cleanup(3, "113 WEST VICTORIA ROAD, SPARTANBURG, 29301")]
    assert len(dedupe(rows)) == 3


def test_one_house_spelled_twice_under_an_overshared_parcel_still_merges():
    rows = [_cleanup(1, "113 OAKDALE COURT, SPARTANBURG, 29306"),
            _cleanup(2, "113 HOLMES DRIVE, SPARTANBURG, 29303"),
            _cleanup(3, "113 WEST VICTORIA ROAD, SPARTANBURG, 29301"),
            _cleanup(4, "113 Oakdale Ct")]
    assert _groups(dedupe(rows)) == [["_rid_1", "_rid_4"]]


def test_a_liensnc_master_tract_pin_does_not_merge_its_unnumbered_rows():
    """Wake 1734532748 sits on 15 numbered houses of one subdivision (liensnc); two rows of it
    whose address is a lot description have no number and nothing else in common."""
    rows = [_row(i, "counties.liensnc", county="Wake", parcel="1734532748",
                 addr=f"{3000 + 2 * i} SUNRISE VALLEY PL") for i in range(1, 5)]
    rows += [_row(10, "counties.liensnc", county="Wake", parcel="1734532748", addr="LOT 12 PHASE 2"),
             _row(11, "counties.liensnc", county="Wake", parcel="1734532748", addr="LOT 31 PHASE 2")]
    assert len(dedupe(rows)) == 6


def test_a_parcel_with_one_house_keeps_merging_its_sentinel_twin():
    """Item 63's twin: a county roll's '0 PATCH DR' and the board's '499 PATCH DR', one valid parcel,
    one street. Not over-shared, so it still merges and shows the number."""
    a = _row(1, "counties_sc.spartanburg_vacant", state="SC", county="Spartanburg",
             parcel="714252203123", addr="0 PATCH DR SPARTANBURG")
    b = _row(2, "counties_sc.spartanburg_vacant", state="SC", county="Spartanburg",
             parcel="714252203123", addr="499 PATCH DR SPARTANBURG",
             raw={"situs_address_source": "parcel_cache:exact"})
    out = dedupe([a, b])
    assert len(out) == 1 and out[0].street_address == "499 PATCH DR SPARTANBURG"


def test_the_streamed_finder_carries_what_identity_reads():
    rec = {"source": "national.landandfarm", "source_url": "u", "state": "NC",
           "county": "Rutherford", "parcel_id": "1654116", "street_address": "252 N WASHINGTON ST",
           "raw": {"parcel_from_geo": dict(RUTH_SEAT), "geo_imprecise": "centroid_snap",
                   "situs_address_source": "parcel_cache:exact", "comps": [1, 2]}}
    li = _light_listing_for_dedupe(rec, "h")
    for k in ("parcel_from_geo", "geo_imprecise", "situs_address_source"):
        assert li.raw[k] == rec["raw"][k]
    assert "comps" not in li.raw
    assert identity(li).hn == "" and identity(rec).hn == ""
