"""quarantine_flip_leaks: which rows count as a flip outside the 18-county footprint. The script stamps only;
these tests pin the rule it stamps by."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import quarantine_flip_leaks as Q  # noqa: E402
from _dq_common import footprint  # noqa: E402


def test_the_footprint_is_the_18_counties_and_is_state_qualified():
    fp = footprint()
    assert len(fp) == 18
    assert ("SC", "union") in fp and ("NC", "union") not in fp
    assert ("SC", "cherokee") in fp and ("NC", "cherokee") not in fp
    assert ("NC", "buncombe") in fp and ("SC", "horry") not in fp


@pytest.mark.parametrize("state,county,lt,verdict", [
    ("SC", "Charleston", "foreclosure_sale", "leak"),
    ("NC", "Pender", "reo", "leak"),
    ("NC", "Dare", "hoa_sale", "leak"),
    ("SC", "Georgetown", "auction", "leak"),
    ("NC", "Union", "foreclosure_sale", "leak"),                  # NC Union is not the footprint's Union SC
    ("SC", "Union", "foreclosure_sale", "in_footprint"),
    ("NC", "Buncombe", "sheriff_sale", "in_footprint"),
    ("NC", "Buncombe County", "reo", "in_footprint"),
    ("SC", "Charleston", "tax_lien", "not_flip"),                 # a distressed LEAD is anywhere in NC + SC
    ("SC", "Charleston", "probate_notice", "not_flip"),
    ("NC", None, "reo", "no_county"),
    ("NC", "Statewide", "foreclosure_sale", "no_county"),
])
def test_flip_verdict(state, county, lt, verdict):
    assert Q.flip_verdict(state, county, lt) == verdict


def test_the_listing_type_may_be_an_enum():
    from foreclosure_scraper.models import ListingType
    assert Q.flip_verdict("SC", "Charleston", ListingType.FORECLOSURE_SALE) == "leak"
    assert Q.flip_verdict("SC", "Charleston", ListingType.TAX_LIEN) == "not_flip"


def test_stamp_value_is_the_one_the_scorer_reads():
    assert Q.STAMP == "flip_outside_footprint"


def test_admission_path_names_the_main_py_branch():
    from foreclosure_scraper import main as M
    src = next(iter(M.COASTAL_COUNTY_BYPASS_SOURCES))
    assert "COASTAL_COUNTY_BYPASS_SOURCES" in Q.admission_path(src, "SC", "Charleston", None, None, None)
    assert "downtown" in Q.admission_path("law_firms.hutchens", "SC", "Charleston", 32.79, -79.93, "Charleston")
    assert "oceanfront" in Q.admission_path("national.fannie_homepath", "NC", "Pender", 34.4, -77.5, "Surf City")
    assert "no_county" in Q.admission_path("reo.vrm_va_reo", "NC", None, None, None, None)
