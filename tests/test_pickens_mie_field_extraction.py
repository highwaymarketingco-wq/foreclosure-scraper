"""Pin the Pickens MIE field-extraction fixes made 2026-10-01.

Live-verified against the current sales_rosters.php PDFs before any fix:
34/34 real rows came back with plaintiff=defendant=None (PARTIES_RE required
a literal lowercase "v." with no re.I flag, but Pickens captions use a bare
capital "V" with no period: "CORP. V JOHN K. SHIVERS"), 0/34 carried a
parcel_id despite every row printing its SC TMS/PIN right after the address
("5029-11-66-6731"), and several addresses were garbled by the same
missing-\\b-boundary bug ADDR_RE had in the sibling anderson_master_in_equity.py
("CARDINAL FINANCIAL" -> "CARD", "SOUTH STATE BANK" -> "ST", and the case
number's own trailing digits read as a fake house number).

Fixtures are real PDF-extracted text (pypdf), captured live 2026-10-01 from
co.pickens.sc.us sales_rosters.php PDFs. No network calls in these tests.
"""
from __future__ import annotations

import re

from foreclosure_scraper.scrapers.counties_sc.pickens_master_in_equity import (
    ADDR_RE,
    PARTIES_RE,
    TMS_RE,
    _LEADING_ATTY_RE,
)

# Real roster-PDF chunk: case# -> plaintiff "V" defendant (no period) -> ET AL
# -> address (line-wrapped) -> city/state/zip -> TMS.
CHUNK_BASIC = (
    "2026-CP-39-00843 FEDERAL HOME LOAN \nMORTGAGE CORP. V JOHN \n"
    "K. SHIVERS, ET AL \n504 GRANT ST., \nEASLEY, SC 29640 \n5029-11-66-6731  \n2."
)

# The case-number-digit-bleed case: no comma before "SOUTH STATE BANK", so the
# old ADDR_RE matched "00559 SOUTH ST" (the case number's own tail + "ST"
# matched bare inside "STATE").
CHUNK_CASE_BLEED = (
    "2026-CP-39-00559 SOUTH STATE BANK NA V \nCHLOE PERKINS \n111 ARBORS CT., "
    "\nCENTRAL, SC 29630 \n4055-12-76-8397 DEFICIENCY \nDEMANDED"
)

# A line-wrapped street name ("SLAB BRIDGE" / "RD." split across lines) that
# the old character class (no \s) could never bridge.
CHUNK_LINE_WRAP_STREET = (
    "2025-CP-39-01577 LONGBRIDGE FINANCIAL, \nLLC V JAMES CARLYLE \nKAY, ET AL "
    "\n333 SLAB BRIDGE \nRD., LIBERTY, SC \n29657 \n5006-00-24-2155 CANCELLED  \n2."
)


def _region(chunk: str) -> str:
    case_m = re.search(r"\b\d{2,4}-CP-\d{2}-\d{4,6}\b", chunk)
    return _LEADING_ATTY_RE.sub("", chunk[case_m.end():])


def test_parties_re_matches_bare_capital_v_no_period():
    """The exact bug: the old pattern required literal 'v.' (lowercase,
    with period) and had no re.I -- it never matched Pickens' bare 'V'."""
    region = _region(CHUNK_BASIC)
    m = PARTIES_RE.search(region)
    assert m is not None
    plaintiff = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
    defendant = re.sub(r"\s+", " ", m.group(2)).strip()
    assert plaintiff == "FEDERAL HOME LOAN MORTGAGE CORP"
    assert defendant.startswith("JOHN")
    assert "SHIVERS" in defendant


def test_tms_parcel_id_captured():
    region = _region(CHUNK_BASIC)
    m = TMS_RE.search(region)
    assert m is not None
    assert m.group(1) == "5029-11-66-6731"


def test_address_not_matched_against_case_number_tail():
    """Searching the full chunk (old behavior) let '00559' from the case
    number masquerade as the house number. Searching only the post-case-
    number region (the fix) must not."""
    region = _region(CHUNK_CASE_BLEED)
    m = ADDR_RE.search(region)
    assert m is not None
    addr = re.sub(r"\s+", " ", m.group(1)).strip()
    assert addr == "111 ARBORS CT."
    assert "00559" not in addr
    assert "SOUTH ST" not in addr


def test_address_suffix_boundary_rejects_substring_match():
    """'STATE' contains 'ST' and 'CARDINAL' contains 'RD' as bare
    substrings -- the \\b fix must reject both as false suffix matches."""
    assert ADDR_RE.search("SOUTH STATE BANK NA") is None
    assert ADDR_RE.search("00468 CARDINAL FINANCIAL COMPANY") is None


def test_address_bridges_a_pdf_line_wrap():
    region = _region(CHUNK_LINE_WRAP_STREET)
    m = ADDR_RE.search(region)
    assert m is not None
    addr = re.sub(r"\s+", " ", m.group(1)).strip()
    assert addr == "333 SLAB BRIDGE RD."
