"""Parser tests for SC Notice-to-Creditors probate notices.

Every fixture below keeps the LAYOUT of a page fetched on 2026-08-06 (the
field-layout differences between the three papers and the two junk values that
sit exactly where a representative's name sits); the names and street lines were
replaced with invented ones on 2026-10-08 (the repo is public).
"""
import asyncio

import pytest

from foreclosure_scraper.scrapers.counties_sc import sc_probate_notices as m
from foreclosure_scraper.scrapers.counties_sc.sc_probate_notices import (
    SC_COUNTY_CODE, Paper, body_text, parse_estates,
)

HEADER = (
    "NOTICE TO CREDITORS\nOF ESTATES\n"
    "All persons having claims against the following estates MUST file their "
    "claims on Form #371ES with the Probate Court.\n"
)

PICKENS = HEADER + (
    "Estate: Testa Lyn Sampleton\n"
    "Date of Death: 5/30/2026\n"
    "Case Number: 2026ES3900446\n"
    "Personal Representative:\n"
    "Rowan E. Sampleton\n"
    "Address: 117 Example Dr., \n"
    "Clemson, SC 29631\n"
    "July 22, 29, Aug. 5\n"
)

CHEROKEE = HEADER + (
    "Estate: Dana Fowlerton Testcase\n"
    "Death: 06/19/2026\n"
    "Case# 2026ES1100303\n"
    "PR: Jordan Placeholder\n"
    "115 Sampleriver Dr.\n"
    "Moore, SC 29369\n"
    "Published: July 29, August 5 & 12, 2026\n"
)

LAURENS = HEADER + (
    "ESTATE OF: Lee Edward Exampleman Jr. \n"
    "Date of Death: May 10, 2026\n"
    "Case Number: 2026ES3000274\n"
    "Personal Representative: Casey Fulton Exampleman\n"
    "Address: 192 Sample Road, Laurens, SC 29360\n"
    "July22,29Aug5\n"
)


def _one(text):
    rows = parse_estates(text)
    assert len(rows) == 1, rows
    return rows[0]


def test_pickens_dialect_name_on_following_line():
    r = _one(PICKENS)
    assert r["estate"] == "Testa Lyn Sampleton"
    assert r["case_number"] == "2026ES3900446"
    assert r["county"] == "Pickens"
    assert r["date_of_death"] == "5/30/2026"
    assert r["personal_representative"] == "Rowan E. Sampleton"
    # The city line lives BELOW the "Address:" line and must be joined onto it.
    assert r["pr_address"] == "117 Example Dr., Clemson, SC 29631"


def test_cherokee_dialect_short_labels_and_unlabelled_address():
    r = _one(CHEROKEE)
    assert r["estate"] == "Dana Fowlerton Testcase"
    assert r["county"] == "Cherokee"
    assert r["date_of_death"] == "06/19/2026"
    assert r["personal_representative"] == "Jordan Placeholder"
    # No "Address:" label at all on this paper.
    assert r["pr_address"] == "115 Sampleriver Dr., Moore, SC 29369"


def test_laurens_dialect_estate_of_and_spelled_out_date():
    r = _one(LAURENS)
    assert r["estate"] == "Lee Edward Exampleman Jr."
    assert r["county"] == "Laurens"
    assert r["date_of_death"] == "May 10, 2026"
    assert r["personal_representative"] == "Casey Fulton Exampleman"


def test_county_comes_from_the_case_number_not_the_paper():
    """A Spartanburg estate printed in the Cherokee paper files as Spartanburg."""
    r = _one(CHEROKEE.replace("2026ES1100303", "2026ES4200999"))
    assert r["county"] == "Spartanburg"


def test_out_of_footprint_case_number_is_kept_under_its_own_county():
    # 23 = Greenville, outside the 18-county FLIP footprint. A probate notice is a
    # distressed lead, admitted anywhere in NC/SC (owner rule 2026-09-15), so since
    # 2026-10-08 it is kept and filed under the county its case number names.
    r = _one(CHEROKEE.replace("2026ES1100303", "2026ES2300999"))
    assert r["county"] == "Greenville"


def test_unknown_county_code_is_dropped():
    # SC codes stop at 46 (York); 47+ is not a county.
    assert parse_estates(CHEROKEE.replace("2026ES1100303", "2026ES4700999")) == []


def test_body_without_the_literal_phrase_yields_nothing():
    """WP search is fuzzy: a story can match the query without being a notice."""
    story = ("A personal representative of the family said the personal art "
             "collection sold. Estate: Someone Real\nCase Number: 2026ES3900001\n")
    assert parse_estates(story) == []


def test_missing_case_number_yields_nothing():
    assert parse_estates(PICKENS.replace("Case Number: 2026ES3900446", "")) == []


def test_case_number_tail_echoed_in_the_name_is_trimmed():
    """'Estate: Edna J. Mockley 276' beside case ...100276 — real published text."""
    r = _one(CHEROKEE.replace("Estate: Dana Fowlerton Testcase",
                              "Estate: Edna J. Mockley 276")
                     .replace("2026ES1100303", "2026ES1100276"))
    assert r["estate"] == "Edna J. Mockley"


def test_a_number_that_is_not_the_case_tail_is_kept():
    r = _one(CHEROKEE.replace("Estate: Dana Fowlerton Testcase",
                              "Estate: Dana Fowlerton Testcase 2nd"))
    assert r["estate"] == "Dana Fowlerton Testcase 2nd"


def test_publication_date_run_is_not_read_as_a_representative():
    r = _one(LAURENS.replace("Personal Representative: Casey Fulton Exampleman",
                             "Personal Representative:\nFeb11,18,25"))
    assert r["personal_representative"] is None


def test_po_box_is_an_address_not_a_representative_name():
    r = _one(PICKENS.replace("Rowan E. Sampleton\nAddress: 117 Example Dr., \n"
                             "Clemson, SC 29631\n",
                             "Post Office Box 219\nPickens, SC 29671\n"))
    assert r["personal_representative"] is None
    assert r["pr_address"] == "Post Office Box 219, Pickens, SC 29671"


def test_repeated_estate_is_emitted_once_per_page():
    """Notices run three consecutive weeks; the same case must not triple."""
    rows = parse_estates(PICKENS + PICKENS.replace(HEADER, ""))
    assert len(rows) == 1


def test_multiple_distinct_estates_on_one_page():
    second = ("Estate: Thurman Duncan\nDate of Death: 5/29/2026\n"
              "Case Number: 2026ES3900466\nPersonal Representative:\n"
              "Linda Gail Bagwell\nAddress: 156 Bagwell Street, Easley, SC 29640\n")
    rows = parse_estates(PICKENS + second)
    assert [r["case_number"] for r in rows] == ["2026ES3900446", "2026ES3900466"]


def test_body_text_preserves_line_breaks():
    """The shared strip_html() collapses these to spaces, which breaks parsing."""
    out = body_text("<p>Estate: A B<br/>Case Number: 2026ES3900446</p>")
    assert "Estate: A B\nCase Number: 2026ES3900446" in out


def test_body_text_unescapes_entities():
    assert "Smith & Jones" in body_text("<p>Smith &amp; Jones</p>")


def test_fetch_salvages_fast_papers_when_a_slow_one_is_still_running(monkeypatch):
    """AUDITED 2026-10-01: fetch() used to `asyncio.gather()` all three papers
    before extending self.partial, so self.partial stayed EMPTY for the whole
    run -- including the entire time the fast papers (Pickens/Laurens) had
    already finished. Verified live the same day: a real run hit the 180s
    soft timeout while the (documented, expected-slow) Gaffney Ledger was
    still going and shipped outcome=TIMEOUT, n=0, discarding 667 already-
    fetched Pickens+Laurens rows. fetch() must now bank each paper's rows
    into self.partial as ITS OWN task completes, not when the slowest does."""

    async def fake_fetch_paper(c, paper: Paper):
        if paper.host == "www.gaffneyledger.com":
            await asyncio.sleep(10)  # never resolves inside this test's budget
            return []
        e = {"estate": f"Test Decedent {paper.host}", "case_number": "2026ES3900001",
             "county": "Pickens", "date_of_death": None,
             "personal_representative": None, "pr_address": None}
        return [m._to_listing(e, f"https://{paper.host}/x", m.SCProbateNotices.slug)]

    monkeypatch.setattr(m, "_fetch_paper", fake_fetch_paper)
    scraper = m.SCProbateNotices()
    scraper.partial = []

    async def _drive():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(scraper.fetch(), timeout=1.0)

    asyncio.run(_drive())
    # The two fast papers (Pickens, Laurens) must have landed in self.partial
    # even though the slow (tolerated) Gaffney Ledger never finished.
    assert len(scraper.partial) == 2
    assert {li.source_url for li in scraper.partial} == {
        "https://www.yourpickenscounty.com/x",
        "https://www.laurenscountyadvertiser.net/x",
    }


def test_county_codes_are_the_46_sc_counties():
    """Codes map to the 46 SC counties (01-46 alphabetical), not only the footprint."""
    assert SC_COUNTY_CODE["11"] == "Cherokee"
    assert SC_COUNTY_CODE["39"] == "Pickens"
    assert SC_COUNTY_CODE["23"] == "Greenville"
    assert SC_COUNTY_CODE["46"] == "York"
    assert len(SC_COUNTY_CODE) == 46
    assert {"Anderson", "Cherokee", "Laurens", "Oconee",
            "Pickens", "Spartanburg", "Union"} <= set(SC_COUNTY_CODE.values())
