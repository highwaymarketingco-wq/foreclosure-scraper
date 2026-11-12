"""counties_nc.johnston_delinquent_tax_crosswalk -- pure-function coverage.

Johnston County NC's static delinquent-tax file carries only a LEGACY map/block/lot parcel id,
not the board's modern 12-digit PIN, so this producer crosswalks it through NC OneMap by owner
name (exact last + prefix first) and then GATES on address agreement
(`verification.core.address_relation`) before accepting a match. Owner name alone is not
sufficient evidence: an HOA entity ("CHANDLER RIDGE OWNERS ASSOCIATION INC") can share name
tokens with an unrelated individual ("RIDGE", "CHANDLER") with no real relationship between the
two properties -- see the module docstring's "THE MATCH RULE" section. These tests cover that
rejection, the plain owner-not-found case, the ambiguous (address-silent) case, the
multiple-candidates-agree case, and the happy path, plus the pure CSV parsing/aggregation and the
current-file-link extraction. Hermetic -- no network.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc import johnston_delinquent_tax_crosswalk as m

# --------------------------------------------------------------------------- extract_file_url

_FILES_PAGE_HTML = """
<html><body>
<li><a href="https://www.johnstonnc.gov/files/taxoffice/ARFLAT_09012026.txt">Accounts Receivable</a></li>
<li><a href="https://www.johnstonnc.gov/files/taxoffice/DelinquentTaxPublicRecordsFile2026108.txt">Delinquent Taxes</a></li>
</body></html>
"""


def test_extract_file_url_finds_the_current_dated_link():
    url = m.extract_file_url(_FILES_PAGE_HTML)
    assert url == "https://www.johnstonnc.gov/files/taxoffice/DelinquentTaxPublicRecordsFile2026108.txt"


def test_extract_file_url_tracks_a_rotated_suffix():
    """The filename's numeric suffix rotates on republish -- never hardcoded."""
    html = _FILES_PAGE_HTML.replace("2026108", "2026231")
    assert m.extract_file_url(html) == (
        "https://www.johnstonnc.gov/files/taxoffice/DelinquentTaxPublicRecordsFile2026231.txt")


def test_extract_file_url_none_when_the_page_no_longer_links_one():
    assert m.extract_file_url("<html><body>nothing here</body></html>") is None


# --------------------------------------------------------------------------- CSV parse + aggregate

def _utf16_csv(rows: list[str]) -> bytes:
    header = "Taxyear,ParcelNumber,LastName,FirstName,PropertyAddress,ZipCode,TotalDue,Bill,LandUnits,Type"
    text = "\r\n".join([header, *rows]) + "\r\n"
    return text.encode("utf-16")


def test_parse_delinquent_csv_strips_excel_formula_wrapper_and_decodes_utf16():
    data = _utf16_csv([
        '2015,="08019024",RADFORD,EULA,400 KEEN ST,27406,1154.38,2015075784,0.320     ,AC        ',
    ])
    rows = m.parse_delinquent_csv(data)
    assert len(rows) == 1
    r = rows[0]
    assert r["parcel"] == "08019024"
    assert r["year"] == 2015
    assert r["last_name"] == "RADFORD"
    assert r["first_name"] == "EULA"
    assert r["address"] == "400 KEEN ST"
    assert r["due"] == 1154.38
    assert r["land_use_type"] == "AC"


def test_aggregate_by_parcel_sums_across_years_and_keeps_per_year_breakdown():
    data = _utf16_csv([
        '2015,="08019024",RADFORD,EULA,400 KEEN ST,27406,1154.38,2015075784,0.320,AC',
        '2016,="08019024",RADFORD,EULA,400 KEEN ST,27406,1143.85,2016076295,0.320,AC',
        '2015,="15K11023",BROWN,LAURA,BRODGEN RD,27614,689.56,2015013798,1.000,LT',
    ])
    agg = m.aggregate_by_parcel(m.parse_delinquent_csv(data))
    assert set(agg) == {"08019024", "15K11023"}
    radford = agg["08019024"]
    assert radford["years_delinquent"] == 2
    assert radford["total_delinquent"] == 2298.23
    assert radford["delinquent_by_year"] == {2015: 1154.38, 2016: 1143.85}
    assert radford["last_name"] == "RADFORD" and radford["first_name"] == "EULA"
    brown = agg["15K11023"]
    assert brown["years_delinquent"] == 1
    assert brown["total_delinquent"] == 689.56


def test_aggregate_by_parcel_skips_rows_with_no_parcel():
    data = _utf16_csv(['2015,,RADFORD,EULA,400 KEEN ST,27406,1154.38,2015075784,0.320,AC'])
    agg = m.aggregate_by_parcel(m.parse_delinquent_csv(data))
    assert agg == {}


# --------------------------------------------------------------------------- build_where

def test_build_where_is_exact_last_prefix_first_scoped_to_johnston():
    where = m.build_where("RADFORD", "EULA")
    assert where == ("UPPER(cntyname) = 'JOHNSTON' AND "
                     "UPPER(ownname) LIKE UPPER('RADFORD, EULA%')")


def test_build_where_escapes_single_quotes():
    where = m.build_where("O'BRIEN", "MARY")
    assert "O''BRIEN" in where


# --------------------------------------------------------------------------- classify_match

def test_classify_match_happy_path_unique_address_match():
    candidates = [
        {"parno": "167109-16-4845", "ownname": "RADFORD, EULA L", "siteadd": "400  KEEN   ST",
         "structno": 0, "improvval": 128030.0},
    ]
    result = m.classify_match("400 KEEN ST", candidates)
    assert result["status"] == "matched"
    assert result["reason"] == "unique_address_match"
    assert result["resolved_pin"] == "167109164845"
    assert result["candidate"]["ownname"] == "RADFORD, EULA L"


def test_classify_match_owner_not_found_when_no_candidates():
    result = m.classify_match("400 KEEN ST", [])
    assert result == {"status": "rejected", "reason": "owner_not_found", "candidates": 0}


def test_classify_match_rejects_hoa_entity_false_positive_on_address_conflict():
    """The real false positive this gate exists for: Johnston's file lists a delinquent owner
    LastName=CHANDLER/FirstName=RIDGE (an individual, "Ridge Chandler") at a house-numbered
    address. NC OneMap's owner-name search can surface an unrelated HOA entity whose name
    happens to overlap those same tokens ("CHANDLER RIDGE OWNERS ASSOCIATION INC") sitting on a
    completely different parcel. Owner-name overlap alone must never resolve this -- the address
    has to agree too, and here it doesn't (different house number), so the whole legacy parcel is
    rejected rather than guessed."""
    candidates = [
        {"parno": "999999999999", "ownname": "CHANDLER RIDGE OWNERS ASSOCIATION INC",
         "siteadd": "1 CHANDLER RIDGE DR", "structno": 0, "improvval": 0.0},
    ]
    result = m.classify_match("81 LYNSHIRE AVE", candidates)
    assert result["status"] == "rejected"
    assert result["reason"] == "address_conflict"
    assert "resolved_pin" not in result


def test_classify_match_rejects_when_two_candidates_both_agree_on_address():
    """Two different NC OneMap records both claiming the same house number: genuinely ambiguous
    (e.g. a condo/duplex, or two owner-name hits that collapse to one address) -- never guessed."""
    candidates = [
        {"parno": "111111111111", "ownname": "SMITH, JOHN", "siteadd": "10 MAIN ST"},
        {"parno": "222222222222", "ownname": "SMITH, JOHN A", "siteadd": "10 MAIN ST"},
    ]
    result = m.classify_match("10 MAIN ST", candidates)
    assert result["status"] == "rejected"
    assert result["reason"] == "multiple_address_matches"


def test_classify_match_ambiguous_when_no_address_signal_either_way():
    """A single candidate whose siteadd carries no usable house number (a road name alone, or
    blank) proves nothing either way -- not accepted, not rejected as conflicting."""
    candidates = [{"parno": "333333333333", "ownname": "DOE, JANE", "siteadd": ""}]
    result = m.classify_match("200 ELM ST", candidates)
    assert result["status"] == "ambiguous_no_address_signal"
    assert result["reason"] == "single_candidate_no_house_number"


def test_classify_match_no_parcel_number_when_match_candidate_carries_no_parno():
    candidates = [{"parno": "", "ownname": "RADFORD, EULA L", "siteadd": "400 KEEN ST"}]
    result = m.classify_match("400 KEEN ST", candidates)
    assert result["status"] == "rejected"
    assert result["reason"] == "no_parcel_number"


# --------------------------------------------------------------------------- to_listing

def test_to_listing_shape_and_evidence():
    rec = {
        "parcel": "08019024", "last_name": "RADFORD", "first_name": "EULA",
        "address": "400 KEEN ST", "zip": "27406", "land_use_type": "AC",
        "delinquent_by_year": {2015: 1154.38, 2016: 1143.85},
        "total_delinquent": 2298.23, "years_delinquent": 2,
        "bills": [{"year": 2015, "bill": "2015075784", "amount": 1154.38}],
    }
    match = {"status": "matched", "reason": "unique_address_match", "candidates": 1,
            "resolved_pin": "167109164845",
            "candidate": {"parno": "167109-16-4845", "ownname": "RADFORD, EULA L",
                          "siteadd": "400  KEEN   ST"}}
    li = m.to_listing("08019024", rec, match,
                      file_url="https://www.johnstonnc.gov/files/taxoffice/DelinquentTaxPublicRecordsFile2026108.txt",
                      file_label="DelinquentTaxPublicRecordsFile2026108.txt")

    assert li.source == "counties_nc.johnston_delinquent_tax_crosswalk"
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.property_kind == PropertyKind.UNKNOWN
    assert li.state == "NC"
    assert li.county == "Johnston"
    assert li.parcel_id == "167109164845"
    assert li.street_address == "400 KEEN ST"
    assert li.defendant == "RADFORD, EULA L"
    assert li.owner_name == "RADFORD, EULA L"
    assert li.foreclosure_process == "tax"

    ev = li.raw["johnston_delinquent_tax_crosswalk"]
    assert ev["legacy_parcel"] == "08019024"
    assert ev["resolved_pin"] == "167109164845"
    assert ev["years_delinquent"] == 2
    assert ev["delinquent_by_year"] == {"2016": 1143.85, "2015": 1154.38}
    assert ev["total_delinquent"] == 2298.23
    assert ev["land_use_type"] == "AC"
    assert ev["crosswalk_method"] == "nc_onemap_owner_address_match"
    assert ev["crosswalk_confidence"] == "unique_address_match"
    assert ev["file_snapshot"] == "DelinquentTaxPublicRecordsFile2026108.txt"
    assert ev["url"].endswith("DelinquentTaxPublicRecordsFile2026108.txt")


# --------------------------------------------------------------------------- fetch() gate

def test_fetch_short_circuits_when_env_disabled(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_JOHNSTON_TAX_CROSSWALK", "0")
    rows = asyncio.run(m.JohnstonDelinquentTaxCrosswalk().fetch())
    assert list(rows) == []


def test_fetch_returns_empty_and_logs_when_files_page_has_no_link(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_JOHNSTON_TAX_CROSSWALK", raising=False)

    class _FakeResp:
        text = "<html>no link here</html>"
        status_code = 200

        def raise_for_status(self):
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResp()

    with patch.object(m, "client", lambda *a, **k: _FakeClient()):
        rows = asyncio.run(m.JohnstonDelinquentTaxCrosswalk().fetch())
    assert list(rows) == []
