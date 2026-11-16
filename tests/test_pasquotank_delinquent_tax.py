"""enrichment_pasquotank_delinquent_tax: Pasquotank County NC's own annual NCGS 105-369
delinquent-tax PDF (www.pasquotankcountync.org/s/DTax2026-edmn.pdf), matched to board rows by
owner name only (no parcel/address field on the document at all -- see the module's own
docstring for why). No network for the pure parsing/matching tests below -- the row text is
built from the real, live-read format (dot-leader "OWNER.....PARCEL.....$AMOUNT", two columns
read back-to-back by pdfplumber with no intervening newline, confirmed live 2026-11-05 and
again 2026-11-16) rather than a captured page, since the cases that matter here -- several
distinct parcels under one owner, the missing-space extraction artifact, a bare negative
screen -- are edge cases, not guaranteed to appear in any one day's live PDF.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_pasquotank_delinquent_tax import (
    build_multiyear_block,
    build_parcel_index,
    despaced_name_key,
    find_candidates,
    parse_pdf_text,
)


def test_parse_pdf_text_reads_two_interleaved_columns_on_one_line() -> None:
    # pdfplumber's own reading order prints both of the PDF's visual columns back to back on
    # one logical text line (module docstring) -- finditer, not a per-line match, has to pull
    # BOTH records out of a line shaped like this.
    line = ("COASTERSDOWNTOWNDRAUGHT.......2-A-4.......$3,708.63 "
            "FORBES,JOSEPHHJR.......14-F-3,4,5,6.......$2,500.91")
    rows = parse_pdf_text(line)
    assert len(rows) == 2
    assert rows[0] == {"owner": "COASTERSDOWNTOWNDRAUGHT", "parcel": "2-A-4", "amount": 3708.63}
    assert rows[1] == {"owner": "FORBES,JOSEPHHJR", "parcel": "14-F-3,4,5,6", "amount": 2500.91}


def test_parse_pdf_text_ignores_rows_with_no_real_amount() -> None:
    assert parse_pdf_text("SOME HEADER TEXT, no dot-leader row at all.") == []
    # A $0.00 row is excluded upstream of the regex match itself (amount must be > 0 per
    # _money()), not something parse_pdf_text needs to special-case.
    assert parse_pdf_text("NOBODY OWES.......1-A-1.......$0.00") == []


def test_build_parcel_index_dedupes_and_sums_same_parcel_duplicate_bills() -> None:
    rows = [
        {"owner": "WYNN, ADAM", "parcel": "35-B-11", "amount": 100.0},
        {"owner": "WYNN, ADAM", "parcel": "35-B-11", "amount": 50.0},     # split bill, same parcel -> summed
        {"owner": "WYNN, ADAM", "parcel": "9-C-2", "amount": 200.0},      # a 2nd, distinct parcel
    ]
    idx = build_parcel_index(rows)
    parcels = {p["parcel"]: p["amount"] for p in idx["WYNN, ADAM"]}
    assert parcels == {"35-B-11": 150.0, "9-C-2": 200.0}


def test_find_candidates_owner_spanning_two_parcels_is_never_guessed_between() -> None:
    # "several owners hold 2-4 distinct parcels each" (module docstring) -- an owner must
    # resolve to EXACTLY ONE distinct parcel to ever be matched; 2+ is left ambiguous.
    idx = build_parcel_index([
        {"owner": "WYNN, ADAM", "parcel": "35-B-11", "amount": 100.0},
        {"owner": "WYNN, ADAM", "parcel": "9-C-2", "amount": 200.0},
    ])
    cands = find_candidates("Wynn, Adam", idx)
    assert len(cands) == 2  # both surfaced to the caller, which then marks it ambiguous_owner


def test_find_candidates_single_parcel_owner_matches() -> None:
    idx = build_parcel_index([{"owner": "TAYLOR, JONATHON ERIC &", "parcel": "7995719210", "amount": 450.25}])
    cands = find_candidates("Taylor, Jonathon Eric &", idx)
    assert len(cands) == 1
    assert cands[0] == {"parcel": "7995719210", "amount": 450.25}


def test_despaced_name_key_recovers_pdfplumber_missing_space_artifact() -> None:
    # pdfplumber's own extraction artifact (module docstring): "Perry, Mary Beth" can come back
    # as "PERRY,MARYBETH&" with no space at all between two real name words. Stripping spaces
    # from REST (never from LAST) makes the two forms compare equal without ever guessing WHERE
    # a space belongs.
    assert despaced_name_key("PERRY, MARY BETH") == ("PERRY", "MARYBETH")
    assert despaced_name_key("PERRY,MARYBETH&") == ("PERRY", "MARYBETH")
    # Genuinely different last names must never collide.
    assert despaced_name_key("PERRY, MARY BETH") != despaced_name_key("TERRY, MARY BETH")


def test_build_multiyear_block_needs_two_matured_years_and_accumulates() -> None:
    # One levy year alone (this county's real situation today -- only one annual ad has ever
    # been linked) never clears the gate.
    assert build_multiyear_block({2025: 450.25}, today=date(2026, 11, 16)) is None

    # The SAME accumulation shape every sibling multi-year restater in this codebase uses: once
    # a second year is merged in by a LATER run, the gate fires without this module changing.
    block = build_multiyear_block({2024: 300.0, 2025: 450.25}, today=date(2026, 11, 16))
    assert block is not None
    assert block["years"] == [2024, 2025]
    assert block["years_delinquent"] == 2
    assert block["total_owed"] == 750.25
    assert block["amount_basis"] == "annual_advertisement"
