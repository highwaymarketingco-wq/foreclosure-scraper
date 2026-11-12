"""Finkel Law Firm (SC) — monthly PDF docket.

Live-verified 2026-10-01: `images/Webs.pdf` on both finkellaw.com and
finkellawcharleston.com now sits behind a Cloudflare challenge (403 "Attention
Required!" to a plain-httpx request) that a real Chrome TLS fingerprint
(curl-cffi `impersonate="chrome"`) clears with a real 200 — confirmed with a
direct curl-cffi probe before changing any code. `fetch()` called the shared
`get_bytes()` helper with no escalation path, so it was silently returning 0
rows on every run (the `except Exception: continue` swallowed the 403). Fixed
by passing `impersonate=True` (the new http_client.get_bytes escalation tier,
see test_get_bytes_impersonate.py) — live `fetch()` went 0 -> 8 real rows.

Live-verified 2026-10-04: this PDF is a sale-RESULTS report, not just an
upcoming-sale calendar -- each record carries a "Bid Amount" (an advance
minimum, often blank) AND a separate "Sale Amount" + "Sold To" (the real
hammer price and winner). The original parser used pypdf's linear text,
whose reading order for this form-style PDF does not follow the real
layout: live-verified it placed the Sale Amount value where Bid Amount
visually sits and never read Sold To at all, so a real Union County row
with Bid Amount $71,400.00 and Sale Amount $93,000 (sold to a third party)
shipped as `opening_bid=93000` with no sale/buyer data whatsoever. Switched
to pdfplumber's position-aware `extract_text()` plus a label-anchored
regex. The sample text below mirrors the REAL live row shapes (grouped by
pdfplumber word y-coordinate, not hand-written), including the Lexington
record's genuine PDF-level defect where a COVID courthouse disclaimer box
physically overlaps the Docket Number/Plaintiff rows in the source file
itself -- confirmed live, not a pdfplumber artifact (pypdf shows the same
interleaving). `case_number` and `plaintiff` guard against that
contamination (strict docket-pattern search / first-line-only split);
`sale_location` is left best-effort since it is not load-bearing.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.law_firms import finkel


def test_fetch_passes_impersonate_true_to_get_bytes(monkeypatch):
    """Regression guard for the exact silent-0-rows bug: without
    impersonate=True, get_bytes raises on Cloudflare's 403 and fetch()
    swallows it via `except Exception: continue`, returning []."""
    calls = []

    async def fake_get_bytes(url, timeout=60.0, impersonate=False):
        calls.append((url, impersonate))
        raise RuntimeError("simulated Cloudflare 403")  # fetch() must survive this

    monkeypatch.setattr(finkel, "get_bytes", fake_get_bytes)
    out = asyncio.run(finkel.Finkel().fetch())
    assert out == []
    assert len(calls) == 2  # both finkellaw.com + finkellawcharleston.com mirrors
    assert all(impersonate is True for _url, impersonate in calls)


def test_fetch_parses_rows_when_pdf_bytes_come_back(monkeypatch):
    import importlib
    import io

    pypdf = importlib.import_module("pypdf")

    async def fake_get_bytes(url, timeout=60.0, impersonate=False):
        # A minimal real PDF (one blank page) proves the extraction path runs
        # end-to-end; the docket-regex parsing itself is covered by _parse's
        # own text-based tests below.
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    monkeypatch.setattr(finkel, "get_bytes", fake_get_bytes)
    out = asyncio.run(finkel.Finkel().fetch())
    assert out == []  # blank page has no docket text, but no exception either


# A clean record (Union County), matching the real live pdfplumber row
# order exactly: Bid Amount AND Sale Amount both populated and DIFFERENT,
# sold to a third party -- the exact shape the old parser collapsed into
# a single (wrong) opening_bid with no sale/buyer data at all.
_UNION_RECORD = (
    "County: Union Sale Date: 05/05/2025 Sale Time: 11:00 A.M. Sale Location: "
    "Union County Courthouse, 210 West Main Street, Union, South Carolina\n"
    "Docket Number: 2024CP4400034\n"
    "Plaintiff: Lakeview Loan Servicing, LLC\n"
    "Defendants: v. Michael Beaty; Darlene Beaty; The United States of America "
    "acting by and through its agency, the Rural Housing Service; Elite "
    "Capital, Inc.; Guy Roofing; and Republic Finance\n"
    "Property Address: 205 Springdale Drive, Union, SC 29379\n"
    "Bid Amount: 71,400.00\n"
    "Sale Amount: 93000 Sold To: Third Party Pine Investment Capital\n"
)

# A not-yet-sold record (Richland): both Bid Amount and Sale Amount/Sold To
# are blank -- must NOT be mistaken for a real $0 sale or a real buyer.
_RICHLAND_RECORD = (
    "County: Richland Sale Date: 05/05/2025 Sale Time: 12:00 P.M. Sale Location: "
    "Courtroom of the Master in Equity located at 2500 Decker Blvd, Courtroom "
    "#1, Columbia, SC 29206\n"
    "Docket Number: 2023CP4005075\n"
    "Plaintiff: Nationstar Mortgage LLC\n"
    "Defendants: v. Quashawnda T. Berry; Shafeka C. Carter\n"
    "Property Address: 3416 Hazelhurst Road, Columbia, SC 29203\n"
    "Bid Amount:\n"
    "Sale Amount: Sold To:\n"
)

# The real Lexington record's own PDF-level defect: a COVID courthouse
# disclaimer box physically overlaps the Docket Number/Plaintiff rows in
# the SOURCE file, live-confirmed by grouping pdfplumber words by
# y-coordinate (not a hand-written edge case). Sold back to the Plaintiff
# (no competing bid), Bid Amount blank.
_LEXINGTON_RECORD = (
    "County: Lexington Sale Date: 05/05/2025 Sale Time: 11:00 A.M, or Sale "
    "Location: The Lexington County Judicial Center in courtroom 3-A, 205 "
    "East Main St. Lexington SC 29072. Pursuant to South Carolina Supreme "
    "Court Administrative Order 2022-02-17-02,\n"
    "Docket Number: 2024CP3204157 on another date, protective masks are no "
    "longer required in county courthouses; however, any person who is at "
    "risk or concerned about the dangers of COVID-19 may continue to wear a "
    "mask inside any\n"
    "thereafter as courthouse, subject to a request from judges, courthouse "
    "staff, or law enforcement to briefly remove that mask during the "
    "presentation of a case or when necessary for security or identification\n"
    "Plaintiff: PIC Fund I, LLC\n"
    "approved by the purposes\n"
    "Defendants: v. Imperial Acquisition Group, LLC; and Dominkey P. Graham\n"
    "Property Address: 701 Seton Road, Columbia, SC 29212\n"
    "Bid Amount:\n"
    "Sale Amount: 95000 Sold To: Plaintiff PIC Fund I, LLC\n"
)


def test_parse_separates_bid_amount_from_sale_amount_and_captures_buyer():
    """THE correctness bug: Bid Amount and Sale Amount are different real
    numbers on this row (71,400 vs 93,000) -- the old parser reported
    whichever bare number it found first as opening_bid and dropped the
    other plus the buyer entirely."""
    out = finkel._parse(_UNION_RECORD, "https://www.finkellaw.com/images/Webs.pdf", "law_firms.finkel")
    assert len(out) == 1
    li = out[0]
    assert li.street_address == "205 Springdale Drive"
    assert li.city == "Union"
    assert li.county == "Union"
    assert li.case_number == "2024CP4400034"
    assert li.plaintiff == "Lakeview Loan Servicing, LLC"
    assert "Michael Beaty" in (li.defendant or "")
    assert li.opening_bid == 71400.0
    assert li.raw["actual_sold_price"] == 93000.0
    assert li.raw["sold_to"] == {"type": "third_party", "name": "Pine Investment Capital"}


def test_parse_blank_bid_and_sale_amount_stay_none_not_zero():
    out = finkel._parse(_RICHLAND_RECORD, "https://www.finkellaw.com/images/Webs.pdf", "law_firms.finkel")
    assert len(out) == 1
    li = out[0]
    assert li.opening_bid is None
    assert "actual_sold_price" not in li.raw
    assert "sold_to" not in li.raw


def test_parse_plaintiff_sold_to_distinguished_from_third_party():
    out = finkel._parse(_LEXINGTON_RECORD, "https://www.finkellaw.com/images/Webs.pdf", "law_firms.finkel")
    assert len(out) == 1
    li = out[0]
    assert li.raw["sold_to"] == {"type": "plaintiff", "name": "PIC Fund I, LLC"}
    assert li.raw["actual_sold_price"] == 95000.0


def test_parse_docket_and_plaintiff_survive_disclaimer_contamination():
    """Regression guard for the real source-side PDF defect: a courthouse
    disclaimer box overlaps Docket Number/Plaintiff for this one real
    location. case_number and plaintiff must come back clean, not padded
    with COVID-notice boilerplate text."""
    out = finkel._parse(_LEXINGTON_RECORD, "https://www.finkellaw.com/images/Webs.pdf", "law_firms.finkel")
    li = out[0]
    assert li.case_number == "2024CP3204157"
    assert li.plaintiff == "PIC Fund I, LLC"
    assert "protective masks" not in (li.case_number or "")
    assert "approved by the purposes" not in (li.plaintiff or "")


def test_parse_multiple_records_in_one_page():
    out = finkel._parse(
        _LEXINGTON_RECORD + _RICHLAND_RECORD + _UNION_RECORD,
        "https://www.finkellaw.com/images/Webs.pdf",
        "law_firms.finkel",
    )
    assert len(out) == 3
    assert {li.case_number for li in out} == {"2024CP3204157", "2023CP4005075", "2024CP4400034"}


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.finkel" in {s.slug for s in all_scrapers()}
