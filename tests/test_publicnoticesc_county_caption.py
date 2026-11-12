"""publicnoticesc.py: 2026-10-04 final-batch extraction-completeness audit.

Re-verified the county-scope question with fresh eyes (per this batch's
instructions) rather than trusting the prior batch's quick pass. Live
sample: 150 real rows across 3 pages of the site's own "Foreclosures"
preset, checked against every row whose OWN preview text names a county via
"COUNTY OF X". 3 of 55 checked rows had county_meta (the grid's "County:"
field) disagree with the case's own caption -- e.g. real notice 649899
(The Country Chronicle): county_meta read "Richland" but the case's own
text reads "STATE OF SOUTH CAROLINA COUNTY OF FAIRFIELD IN THE COURT OF
COMMON PLEAS". None of the 3 live mismatches happened to land inside the
7-county footprint, but the mechanism is confirmed unreliable either
direction:
  - a real in-footprint case whose PUBLICATION is headquartered outside the
    footprint would be silently dropped (county_meta non-footprint) even
    though the case itself is a real footprint lead;
  - a real out-of-footprint case carried by an in-footprint publication
    would be wrongly admitted and mislabeled.
``FAIRFIELD_MISMATCH`` below is the real live text (trimmed), used to build
synthetic-but-realistic in-footprint variants of both directions.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.public_notices import publicnoticesc as M

# Real text, live-captured 2026-10-04 (notice 649899, The Country Chronicle).
FAIRFIELD_MISMATCH_TEXT = (
    "SUMMONS AND NOTICES (Non-Jury) FORECLOSURE OF REAL ESTATE MORTGAGE "
    "STATE OF SOUTH CAROLINA COUNTY OF FAIRFIELD IN THE COURT OF COMMON "
    "PLEAS C/A NO.: 2022CP2009908 U.S. Bank Trust National Association, "
    "not in its individual capacity, Plaintiff, v. JOHN DOE, Defendants."
)


def _row(notice_id: str, county_meta: str, text: str) -> dict:
    return {
        "notice_id": notice_id, "publication": "The Country Chronicle",
        "date_text": "Thursday, October 01, 2026", "published_at": None,
        "county_meta": county_meta, "city_meta": "Winnsboro", "text": text,
    }


def test_real_fairfield_mismatch_both_out_of_footprint_still_dropped():
    """The real live row: county_meta Richland (not footprint), caption
    names Fairfield (also not footprint) -- correctly dropped either way,
    proving this fix doesn't change the outcome for the real case that
    exposed it."""
    row = _row("649899", "Richland", FAIRFIELD_MISMATCH_TEXT)
    assert M._to_listing(row, "public_notices.publicnoticesc") is None


def test_case_county_re_extracts_the_real_caption_venue():
    m = M._CASE_COUNTY_RE.search(FAIRFIELD_MISMATCH_TEXT[:300])
    assert m is not None
    assert m.group(1).upper() == "FAIRFIELD"


def test_recovers_an_in_footprint_case_whose_publication_is_not():
    """Synthetic-but-realistic (same real caption shape, footprint county
    substituted for the real out-of-footprint one): county_meta says a
    NON-footprint publication county (Richland), but the case's own caption
    names a real footprint county (Spartanburg). Before this fix: dropped
    entirely (county_meta alone gated the footprint check). After: admitted
    and correctly labeled Spartanburg."""
    text = FAIRFIELD_MISMATCH_TEXT.replace("COUNTY OF FAIRFIELD", "COUNTY OF SPARTANBURG")
    row = _row("900001", "Richland", text)
    li = M._to_listing(row, "public_notices.publicnoticesc")
    assert li is not None
    assert li.county == "Spartanburg"
    assert li.raw["public_notice"]["county_source"] == "caption"
    assert li.raw["public_notice"]["publication_county"] == "Richland"


def test_excludes_an_out_of_footprint_case_whose_publication_is_not():
    """The mirror-image risk: county_meta says a footprint publication
    county (Anderson), but the case's own caption names a real
    NON-footprint county (Richland) -- before this fix: wrongly admitted
    and mislabeled Anderson. After: correctly dropped."""
    text = FAIRFIELD_MISMATCH_TEXT.replace("COUNTY OF FAIRFIELD", "COUNTY OF RICHLAND")
    row = _row("900002", "Anderson", text)
    assert M._to_listing(row, "public_notices.publicnoticesc") is None


def test_falls_back_to_county_meta_when_no_caption_county_present():
    """The common case (preview truncates before any caption, or no 'COUNTY
    OF' phrasing at all): behavior is UNCHANGED from before this fix."""
    text = "NOTICE OF SALE case no. 2026CP4209581 will sell to highest bidder..."
    row = _row("900003", "Spartanburg", text)
    li = M._to_listing(row, "public_notices.publicnoticesc")
    assert li is not None
    assert li.county == "Spartanburg"
    assert li.raw["public_notice"]["county_source"] == "publication_meta"


def test_caption_county_outside_the_300_char_caption_zone_is_ignored():
    """A 'county of' phrase that shows up deep in the body (well past the
    caption) must not override a valid, nearby county_meta -- defense in
    depth even though the preview truncates early enough in practice that
    this has not been observed live."""
    filler = "A" * 400
    text = f"NOTICE OF SALE case no. 2026CP4209581. {filler} COUNTY OF RICHLAND mentioned late."
    row = _row("900004", "Spartanburg", text)
    li = M._to_listing(row, "public_notices.publicnoticesc")
    assert li is not None
    assert li.county == "Spartanburg"
    assert li.raw["public_notice"]["county_source"] == "publication_meta"


def test_fixture_rows_still_use_caption_when_it_agrees_with_meta():
    """Regression guard against the real 4-row fixture file: Spartanburg
    (650001) and Anderson (647355) both name their own county in the
    caption/body, matching county_meta -- county_source should read
    'caption' now (an upgrade in provenance quality, not a value change)."""
    from pathlib import Path
    from foreclosure_scraper.scrapers.public_notices import _press_assoc as pa

    fixture = Path(__file__).parent / "fixtures" / "publicnoticesc_grid.html"
    rows = {r["notice_id"]: r for r in pa.parse_grid(fixture.read_text())}
    li = M._to_listing(rows["650001"], "public_notices.publicnoticesc")
    assert li.county == "Spartanburg"
    assert li.raw["public_notice"]["county_source"] == "caption"
