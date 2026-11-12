"""Pin the Pickens delinquent tax-sale results-PDF parser.

Pickens self-hosts its annual "Delinquent Tax Sale Results" PDF with
OWNER + MAP/PARCEL # + SALE/BID PRICE + prior/current-year TAX AMOUNTS on
one line per delinquent parcel — the source that closes the taxes-owed gap.

These tests use synthetic PDF-text chunks (the live PDF is fetched behind a
<base href> root redirect to the Revize store and is exercised by the live
smoke run, not the offline suite). They pin:
  * clean owner + parcel + current-year-owed extraction
  * pdfplumber glyph-garble handling (e.g. "$ 3 2.44" for 3,032.44) — the
    amount must be rejected (not fabricated) while the parcel/owner still land
  * PBO / BF disposition tagging
  * header / note lines producing no rows
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.pickens_tax_sale import (
    _money,
    discover_results_url,
    parse_results,
)

URL = "https://www.co.pickens.sc.us/TAX SALE RESULTS FOR WEBSITE.pdf"

# A representative slice of the live PDF text (extract_text output), including a
# header, clean rows, glyph-garbled rows, a PBO row and a BF row, and a footer.
SAMPLE = """BIDDER # ITEM # MAP/PARCEL # 11-4-2025 TAX SALE SALE/BID PRICE 2024 TAXES 2025 TAXES
292 00025 4133-00-17-8473 AMPHITRITE 20.22 LLC $ 11,000.00 $ 1,567.37 $ 1,212.48
150 00002 4185-00-38-3525 ABERCROMBIE, ROGER KEITH $ 55,000.00 $ 2,910.52 $ 3 2.44
PBO 00245 4175-01-06-1290 $ - $ - $ -
BF 00083 4130-00-77-4844 BEATTY, JOHN MARCUS
125 00216 4174-00-46-1166 CHAPMAN, ANDREA $ 34,000.00 $ 779.73 $ 657.81
Sale conducted November 4, 2025. All bids subject to SC Code 12-51 redemption.
"""


# ---- _money ----

def test_money_clean():
    assert _money("$ 55,000.00") == 55000.0
    assert _money("$ 1,212.48") == 1212.48
    assert _money("$ 657.81") == 657.81


def test_money_dash_is_none():
    assert _money("$ -") is None


def test_money_garbled_rejected():
    # pdfplumber dropped ",03" from 3,032.44 leaving "3 2.44"; interior space
    # between digits is unrecoverable -> must return None, never a wrong value.
    assert _money("$ 3 2.44") is None
    assert _money("$ 1 80,000.00") is None
    assert _money("$ 8 5.96") is None


# ---- parse_results ----

def test_row_count_and_no_header_rows():
    rows = parse_results(SAMPLE, URL)
    # 5 parcel rows (AMPHITRITE, ABERCROMBIE, PBO, BF, CHAPMAN); header + footer skipped
    assert len(rows) == 5
    assert all(r.parcel_id for r in rows)
    assert all(r.state == "SC" and r.county == "Pickens" for r in rows)
    assert all(r.foreclosure_process == "tax" for r in rows)


def test_clean_row_full_extraction():
    rows = parse_results(SAMPLE, URL)
    amph = next(r for r in rows if r.parcel_id == "4133-00-17-8473")
    assert amph.owner_name == "AMPHITRITE 20.22 LLC"
    assert amph.opening_bid == 11000.0
    p = amph.raw["pickens_tax_sale"]
    assert p["taxes_owed"] == 1212.48       # current-year (2025) owed
    assert p["taxes_owed_year"] == "current"
    assert p["tax_2024"] == 1567.37
    assert p["item_no"] == "00025"
    assert p["bidder"] == "292"


def test_garbled_current_year_falls_back_to_prior_not_fabricated():
    rows = parse_results(SAMPLE, URL)
    ab = next(r for r in rows if r.parcel_id == "4185-00-38-3525")
    # still a full lead (parcel + owner intact)
    assert ab.owner_name == "ABERCROMBIE, ROGER KEITH"
    p = ab.raw["pickens_tax_sale"]
    # current-year cell was garbled -> tax_2025 must be None (not 32.44)
    assert p["tax_2025"] is None
    # owed falls back to the (clean) prior-year figure, flagged as such
    assert p["taxes_owed"] == 2910.52
    assert p["taxes_owed_year"] == "prior"


def test_pbo_disposition_tagged():
    rows = parse_results(SAMPLE, URL)
    pbo = next(r for r in rows if r.parcel_id == "4175-01-06-1290")
    assert pbo.raw["pickens_tax_sale"]["disposition"] == "redeemed_or_pulled"
    # all-dash row: no owner, no amount, but the parcel still lands as a lead
    assert pbo.raw["pickens_tax_sale"]["taxes_owed"] is None
    assert pbo.owner_name is None


def test_bf_disposition_tagged():
    rows = parse_results(SAMPLE, URL)
    bf = next(r for r in rows if r.parcel_id == "4130-00-77-4844")
    assert bf.raw["pickens_tax_sale"]["disposition"] == "bid_off_to_flc"
    assert bf.owner_name == "BEATTY, JOHN MARCUS"


def test_parcel_dedupe():
    dup = SAMPLE + "999 00025 4133-00-17-8473 AMPHITRITE 20.22 LLC $ 9.00 $ 9.00 $ 9.00\n"
    rows = parse_results(dup, URL)
    assert sum(1 for r in rows if r.parcel_id == "4133-00-17-8473") == 1


# ---- discover_results_url ----

def test_discover_prefers_current_year():
    html = """
    <a href="OLD 2024 Tax Sale Results.pdf?t=1">2024 Delinquent Tax Sale Results</a>
    <a href="TAX SALE RESULTS FOR WEBSITE.pdf?t=2">2025 Delinquent Tax Sale Results</a>
    <a href="Bidder Registration.pdf">Bidder Registration Procedures</a>
    """
    u = discover_results_url(html, 2025)
    assert u is not None
    # picks the 2025 doc over the 2024 one and the registration doc
    assert "TAX SALE RESULTS FOR WEBSITE.pdf" in u
    # resolved against the domain root (base href), not the page dir. httpx
    # percent-encodes the spaces at fetch time.
    assert u.startswith("https://www.co.pickens.sc.us/")


def test_discover_none_when_no_results_pdf():
    html = '<a href="Bidder Registration.pdf">Bidder Registration Procedures</a>'
    assert discover_results_url(html, 2025) is None
