"""Pin SC Master-in-Equity results-PDF parsing for Spartanburg + Anderson.

Live PDF text format documented from real downloads on 2026-05-07:

  Spartanburg /DocumentCenter/View/3392/Sale-Results.pdf — pdfplumber
    extracts a 9-column table; column 6 = bid amount, column 1 = status
    (Final / Def. Sale / blank), √ in last col = cancelled.

  Anderson */YYYY/MM/{Month}-{D}-{YYYY}-Sale-Results.pdf and
    *-Deficiency-Sale-Results.pdf — flat text rows; sold price appears
    inline as 'To Third Party $X' / 'To Plaintiff $X' / 'Plaintiff bid
    $X'. WD / WD/BR rows have no sale.

These tests use synthetic PDF text (live PDFs not always reachable
from local env). The shape is verified against real downloads.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.scrapers.counties_sc.anderson_master_in_equity import (
    ANDERSON_NON_SALE_RE,
    ANDERSON_SOLD_RE,
    RESULTS_HREF_RE,
    _parse_results_pdf,
)
from foreclosure_scraper.scrapers.counties_sc.spartanburg_master_in_equity import (
    _is_results_pdf,
)


# ---- Spartanburg: results-PDF detection ----

def test_spartanburg_detects_sale_results_url():
    assert _is_results_pdf(
        "https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results"
    ) is True


def test_spartanburg_detects_deficiency_url():
    assert _is_results_pdf(
        "https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale"
    ) is True


def test_spartanburg_doesnt_misdetect_unrelated_url():
    assert _is_results_pdf(
        "https://www.spartanburgcounty.gov/DocumentCenter/View/9999/Future-Roster"
    ) is False


# ---- Anderson: results-PDF URL discovery ----

def test_anderson_results_url_pattern_matches():
    url = "https://www.andersoncountysc.org/wp-content/uploads/2026/05/May-5-2026-Sale-Results.pdf"
    m = RESULTS_HREF_RE.search(url)
    assert m is not None
    assert m.group(3).lower() == "may"
    assert m.group(4) == "5"
    assert m.group(5) == "2026"


def test_anderson_deficiency_results_url_matches():
    url = "https://x/wp-content/uploads/2026/04/April-2-2026-Deficiency-Sale-Results.pdf"
    m = RESULTS_HREF_RE.search(url)
    assert m is not None


def test_anderson_results_url_with_trailing_number_matches():
    """Some PDFs have suffixes like '-1' (e.g. March-3-2026-Sale-Results-1.pdf)
    when the file was reuploaded."""
    url = "https://x/wp-content/uploads/2026/03/March-3-2026-Sale-Results-1.pdf"
    m = RESULTS_HREF_RE.search(url)
    assert m is not None


def test_anderson_upcoming_sale_list_NOT_matched_by_results_pattern():
    url = "https://x/wp-content/uploads/2026/05/May-5-2026-Sale-List.pdf"
    assert RESULTS_HREF_RE.search(url) is None


# ---- Anderson sold-price regex ----

def test_anderson_to_third_party_pattern():
    chunk = "5. 25-1292 Hutchens CitiMortgage v. Hicks 1904 East Calhoun To Third Party $95,000.00"
    m = ANDERSON_SOLD_RE.search(chunk)
    assert m is not None
    assert m.group(1) == "95,000.00"


def test_anderson_to_plaintiff_pattern():
    chunk = "1. 25-733 Hutchens US Bank v. Holdings 504 Caughlin To Plaintiff $78,000.00"
    m = ANDERSON_SOLD_RE.search(chunk)
    assert m is not None


def test_anderson_plaintiff_bid_pattern():
    chunk = "5. 25-733 Hutchens US Bank Plaintiff bid $164,000.00"
    m = ANDERSON_SOLD_RE.search(chunk)
    assert m is not None
    assert m.group(1) == "164,000.00"


def test_anderson_wd_status_skipped():
    """WD = withdrawn, no sale happened."""
    assert ANDERSON_NON_SALE_RE.search("2. 24-1352 B&S PennyMac WD") is not None


def test_anderson_wd_br_combo_skipped():
    """WD/BR = withdrawn due to bankruptcy, no sale."""
    assert ANDERSON_NON_SALE_RE.search("4. 25-255 BCP Sierra Pacific WD/BR") is not None


# ---- Anderson _parse_results_pdf integration ----

ANDERSON_RESULTS_SAMPLE = """
CASE NO. ATTY. CAPTION DESCRIPTION RESULTS

1. 25-733 Hutchens US Bank v. Holdings
504 Caughlin Avenue, Anderson
To Plaintiff $78,000.00

2. 24-1352 B&S PennyMac Loan v. Smith
1023 Blythewood Drive, Piedmont
WD

3. 25-1292 Hutchens CitiMortgage v. Hicks
1904 East Calhoun Street, Anderson
To Third Party $95,000.00

4. 25-2546 RT PennyMac Loan v. Kay
312 Phillips Dr., Pendleton
To Third Party $228,500.00

5. 25-2503 RT PennyMac Loan v. Kurtz
1412 Simpson Rd., Pendleton
WD/BR
"""


def test_anderson_parse_results_extracts_3_sold_skips_2_wd():
    listings = _parse_results_pdf(
        ANDERSON_RESULTS_SAMPLE,
        "https://example.com/test.pdf",
        "counties_sc.anderson_master_in_equity",
        sale_date=datetime(2026, 5, 5),
    )
    assert len(listings) == 3
    prices = sorted(li.opening_bid for li in listings)
    assert prices == [78000.0, 95000.0, 228500.0]
    for li in listings:
        assert li.county == "Anderson"
        assert li.state == "SC"
        # Each carries actual_sold_price at top of raw for the
        # foreclosure_sold_comps enrichment.
        assert li.raw["actual_sold_price"] == li.opening_bid
        assert li.sale_date == datetime(2026, 5, 5)


def test_anderson_parse_results_skips_wd_rows():
    listings = _parse_results_pdf(
        ANDERSON_RESULTS_SAMPLE,
        "https://example.com/test.pdf",
        "counties_sc.anderson_master_in_equity",
        sale_date=datetime(2026, 5, 5),
    )
    cases = {li.case_number for li in listings}
    assert "24-1352" not in cases  # WD
    assert "25-2503" not in cases  # WD/BR
    assert "25-733" in cases       # SOLD
    assert "25-1292" in cases      # SOLD
    assert "25-2546" in cases      # SOLD
