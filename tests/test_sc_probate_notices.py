"""Parser tests for SC Notice-to-Creditors probate notices.

Every fixture below is trimmed from a page that was actually fetched on
2026-08-06, including the field-layout differences between the three papers and
the two junk values that sit exactly where a representative's name sits.
"""
from foreclosure_scraper.scrapers.counties_sc.sc_probate_notices import (
    SC_COUNTY_CODE, body_text, parse_estates,
)

HEADER = (
    "NOTICE TO CREDITORS\nOF ESTATES\n"
    "All persons having claims against the following estates MUST file their "
    "claims on Form #371ES with the Probate Court.\n"
)

PICKENS = HEADER + (
    "Estate: Angela Lyn Allen\n"
    "Date of Death: 5/30/2026\n"
    "Case Number: 2026ES3900446\n"
    "Personal Representative:\n"
    "Frances E. Allen\n"
    "Address: 117 Roslyn Dr., \n"
    "Clemson, SC 29631\n"
    "July 22, 29, Aug. 5\n"
)

CHEROKEE = HEADER + (
    "Estate: Linda Fowler Harris\n"
    "Death: 06/19/2026\n"
    "Case# 2026ES1100303\n"
    "PR: Nicole Easler\n"
    "115 Riveredge Dr.\n"
    "Moore, SC 29369\n"
    "Published: July 29, August 5 & 12, 2026\n"
)

LAURENS = HEADER + (
    "ESTATE OF: Lee Edward Brouillette Jr. \n"
    "Date of Death: May 10, 2026\n"
    "Case Number: 2026ES3000274\n"
    "Personal Representative: Teresa Fulmer Brouillette\n"
    "Address: 192 Burton Road, Laurens, SC 29360\n"
    "July22,29Aug5\n"
)


def _one(text):
    rows = parse_estates(text)
    assert len(rows) == 1, rows
    return rows[0]


def test_pickens_dialect_name_on_following_line():
    r = _one(PICKENS)
    assert r["estate"] == "Angela Lyn Allen"
    assert r["case_number"] == "2026ES3900446"
    assert r["county"] == "Pickens"
    assert r["date_of_death"] == "5/30/2026"
    assert r["personal_representative"] == "Frances E. Allen"
    # The city line lives BELOW the "Address:" line and must be joined onto it.
    assert r["pr_address"] == "117 Roslyn Dr., Clemson, SC 29631"


def test_cherokee_dialect_short_labels_and_unlabelled_address():
    r = _one(CHEROKEE)
    assert r["estate"] == "Linda Fowler Harris"
    assert r["county"] == "Cherokee"
    assert r["date_of_death"] == "06/19/2026"
    assert r["personal_representative"] == "Nicole Easler"
    # No "Address:" label at all on this paper.
    assert r["pr_address"] == "115 Riveredge Dr., Moore, SC 29369"


def test_laurens_dialect_estate_of_and_spelled_out_date():
    r = _one(LAURENS)
    assert r["estate"] == "Lee Edward Brouillette Jr."
    assert r["county"] == "Laurens"
    assert r["date_of_death"] == "May 10, 2026"
    assert r["personal_representative"] == "Teresa Fulmer Brouillette"


def test_county_comes_from_the_case_number_not_the_paper():
    """A Spartanburg estate printed in the Cherokee paper files as Spartanburg."""
    r = _one(CHEROKEE.replace("2026ES1100303", "2026ES4200999"))
    assert r["county"] == "Spartanburg"


def test_out_of_footprint_case_number_is_dropped():
    # 23 = Greenville, adjacent but outside the 18-county footprint.
    assert parse_estates(CHEROKEE.replace("2026ES1100303", "2026ES2300999")) == []


def test_body_without_the_literal_phrase_yields_nothing():
    """WP search is fuzzy: a story can match the query without being a notice."""
    story = ("A personal representative of the family said the personal art "
             "collection sold. Estate: Someone Real\nCase Number: 2026ES3900001\n")
    assert parse_estates(story) == []


def test_missing_case_number_yields_nothing():
    assert parse_estates(PICKENS.replace("Case Number: 2026ES3900446", "")) == []


def test_case_number_tail_echoed_in_the_name_is_trimmed():
    """'Estate: Ethel J. Hamrick 276' beside case ...100276 — real published text."""
    r = _one(CHEROKEE.replace("Estate: Linda Fowler Harris",
                              "Estate: Ethel J. Hamrick 276")
                     .replace("2026ES1100303", "2026ES1100276"))
    assert r["estate"] == "Ethel J. Hamrick"


def test_a_number_that_is_not_the_case_tail_is_kept():
    r = _one(CHEROKEE.replace("Estate: Linda Fowler Harris",
                              "Estate: Linda Fowler Harris 2nd"))
    assert r["estate"] == "Linda Fowler Harris 2nd"


def test_publication_date_run_is_not_read_as_a_representative():
    r = _one(LAURENS.replace("Personal Representative: Teresa Fulmer Brouillette",
                             "Personal Representative:\nFeb11,18,25"))
    assert r["personal_representative"] is None


def test_po_box_is_an_address_not_a_representative_name():
    r = _one(PICKENS.replace("Frances E. Allen\nAddress: 117 Roslyn Dr., \n"
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


def test_footprint_codes_only():
    """Codes must map to real SC counties in the 18-county footprint."""
    assert SC_COUNTY_CODE["11"] == "Cherokee"
    assert SC_COUNTY_CODE["39"] == "Pickens"
    assert set(SC_COUNTY_CODE.values()) == {
        "Anderson", "Cherokee", "Laurens", "Oconee",
        "Pickens", "Spartanburg", "Union"}
