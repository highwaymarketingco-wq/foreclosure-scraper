"""Edgecombe County tax-foreclosure extraction-completeness audit (2026-10-01).

Live-pulled table (2026-10-01) has 18 real data rows but the scraper's
_PARCEL_RE only matched 17 of them: it assumed every parcel number is a
strict 4-2-4(-2) digit grouping ("4738-71-6101-00"), but one real row
(case 26CV002193-320, "1739 Thru St., Rocky Mt") carries a 4-4-4-2 grouping
("3759-7002-2140-00"). Because the per-row loop treats "no parcel match" as
"not a data row" (header / divider), that whole row -- including its
STATUS of "Sale 10/14/2026", the single highest-priority signal this source
carries -- was silently dropped. Widened _PARCEL_RE's group widths to fix."""
from foreclosure_scraper.scrapers.counties_nc.edgecombe_tax_foreclosure import (
    _CASE_RE,
    _PARCEL_RE,
    _SALE_STATUS_RE,
)


def test_standard_4_2_4_2_parcel_still_matches():
    assert _PARCEL_RE.search("4738-71-6101-00").group(0) == "4738-71-6101-00"


def test_standard_4_2_4_parcel_without_trailing_group_matches():
    assert _PARCEL_RE.search("4724-21-1818").group(0) == "4724-21-1818"


def test_irregular_4_4_4_2_parcel_now_matches():
    """The real row this bug dropped: case 26CV002193-320, '1739 Thru St.'."""
    m = _PARCEL_RE.search("3759-7002-2140-00")
    assert m is not None
    assert m.group(0) == "3759-7002-2140-00"


def test_case_number_regex_ignores_trailing_ct_suffix():
    m = _CASE_RE.search("26CV001044-320 Ct 1")
    assert m.group(0) == "26CV001044-320"


def test_sale_status_regex_extracts_embedded_date():
    m = _SALE_STATUS_RE.search("Sale 10/14/2026")
    assert m is not None
    assert (m.group(1), m.group(2), m.group(3)) == ("10", "14", "2026")
