"""A life-event record folded into a row under another record still scores (audit 2026-10-09,
area regressions).

THE DEFECT. A merged row's listing_type is its BASE record's, and the base is whichever row came
first; main.run() collects scraper results from an unordered set, so the order changes every run.
The gated d42058b3 run folded heir-estate parcels under tax-roll rows (and the other way round):
estate_lead disappeared from 125 rows the 10/7 board scored with it, and other rows went to HOT only
because the base flipped toward the estate record. Listing.merge also kept one also_seen_in entry
per URL, so a second source citing the same county page vanished from the row (149 rows).

THE FIX. Listing.merge keeps one also_seen_in entry per (source, url) and records each absorbed
record's listing_type; distress_score credits the absorbed life-event types (ABSORBED_LIFE_TYPES).
Fixtures are invented.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.distress_score import _signals_for, absorbed_life_types
from foreclosure_scraper.models import Listing, ListingType

T = datetime(2026, 10, 8, 2, 0)
PAGE = "https://example.invalid/county/delinquent-tax"


def _li(source, lt, url, **kw):
    base = dict(source=source, source_url=url, listing_type=lt, state="NC", county="Rutherford",
                parcel_id="1600000001", owner_name="OWNER A", first_seen=T, last_seen=T, raw={})
    base.update(kw)
    return Listing(**base)


def _names(li):
    return {n for n, _c, _w in _signals_for(li)}


def test_an_estate_record_under_a_tax_row_keeps_estate_lead_either_way():
    tax = _li("counties_nc.rutherford_tax", ListingType.TAX_LIEN, "https://example.invalid/roll.xlsx")
    estate = _li("counties_nc.nc_heir_estate_parcels", ListingType.ESTATE_LEAD,
                 "https://example.invalid/heir-layer")
    tax_first, estate_first = tax.merge(estate), estate.merge(tax)
    assert tax_first.listing_type == ListingType.TAX_LIEN            # the base's type, as before
    assert "estate_lead" in _names(tax_first)                         # ... but the record still counts
    assert "estate_lead" in _names(estate_first)
    entry = tax_first.raw["also_seen_in"][0]
    assert entry == {"source": "counties_nc.nc_heir_estate_parcels",
                     "url": "https://example.invalid/heir-layer", "listing_type": "estate_lead"}


def test_two_sources_citing_one_page_both_stay_attributed():
    a = _li("counties_sc.pickens_delinquent_parcels", ListingType.TAX_LIEN, PAGE)
    b = _li("counties.multi_year_delinquent_tax", ListingType.TAX_LIEN, PAGE)
    m = a.merge(b)
    assert [e["source"] for e in m.raw["also_seen_in"]] == ["counties.multi_year_delinquent_tax"]
    # the same source on the same page is still the primary record, never an entry
    assert "also_seen_in" not in a.merge(_li("counties_sc.pickens_delinquent_parcels",
                                               ListingType.TAX_LIEN, PAGE)).raw


def test_types_survive_a_chain_of_merges_and_an_old_entry_gains_its_type():
    a = _li("src.a", ListingType.TAX_LIEN, "https://example.invalid/a")
    b = _li("src.b", ListingType.DIVORCE_NOTICE, "https://example.invalid/b")
    c = _li("src.c", ListingType.TAX_LIEN, "https://example.invalid/c",
            raw={"also_seen_in": [{"source": "src.b", "url": "https://example.invalid/b"}]})
    m = c.merge(a.merge(b))
    types = {e["source"]: e.get("listing_type") for e in m.raw["also_seen_in"]}
    assert types == {"src.b": "divorce_notice", "src.a": "tax_lien"}
    assert absorbed_life_types(m.raw, "tax_lien") == [("divorce_notice", ["src", "b"])]


def test_an_absorbed_type_is_never_counted_twice_or_from_a_filing_date_source():
    raw = {"also_seen_in": [
        {"source": "src.b", "url": "u1", "listing_type": "estate_lead"},
        {"source": "src.c", "url": "u2", "listing_type": "estate_lead"},
        {"source": "counties_generic.liensnc", "url": "u3", "listing_type": "probate_notice"},
        {"source": "src.d", "url": "u4", "listing_type": "lis_pendens"},      # not a life event
        {"source": "src.e", "url": "u5"},                                      # an old entry
    ]}
    assert absorbed_life_types(raw, "tax_lien") == [("estate_lead", ["src", "b", "src", "c"])]
    assert absorbed_life_types(raw, "estate_lead") == []
    li = _li("src.a", ListingType.TAX_LIEN, "https://example.invalid/a", raw=raw)
    assert sorted(n for n in (s[0] for s in _signals_for(li)) if n == "estate_lead") == ["estate_lead"]
    assert "lis_pendens" not in _names(li) and "probate_notice" not in _names(li)
