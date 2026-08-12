"""The two register-of-deeds platforms must not be confused for each other.

Every bug these guard against returned HTTP 200 while being wrong, which is why
they are asserted rather than left to a live probe.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import enrichment_rod_lookup as lookup
from foreclosure_scraper import enrichment_rod_name_index as name_index


def test_the_two_platforms_share_no_counties():
    """The nine counties dropped from LOOKUP_HOSTS run the OTHER platform.

    Listing a county in both means one of the two readers is pointed at a host
    that 404s for it, and a 404 here reads as 'county has no records'.
    """
    overlap = set(lookup.LOOKUP_HOSTS) & set(name_index.NAME_INDEX_HOSTS)
    assert not overlap, f"county claimed by both readers: {sorted(overlap)}"


def test_lookup_hosts_are_only_the_verified_three():
    """Nine counties were removed because they 404 on content.php. Re-adding one
    without verifying a browse returns rows silently empties that county."""
    assert set(lookup.LOOKUP_HOSTS) == {
        ("clay", "NC"), ("haywood", "NC"), ("yancey", "NC")}


def test_every_lookup_host_records_how_its_state_was_confirmed():
    """hendersondeeds.com is Kentucky and wilsondeeds.com is Tennessee. A host
    added by name pattern alone must not reach LOOKUP_HOSTS again."""
    for key in lookup.LOOKUP_HOSTS:
        assert key in lookup.VERIFIED_AGAINST, f"{key} has no state evidence"
        assert lookup.VERIFIED_AGAINST[key].strip()


def test_bulk_by_date_refuses_counties_that_ignore_the_window(monkeypatch):
    """Five of the eight return the head of the whole index for any window. If
    bulk_by_date ran there it would publish years-old filings as this week's."""
    def explode(*a, **k):  # a refused county must not open a session at all
        raise AssertionError("session opened for a date-ignoring county")
    monkeypatch.setattr(name_index, "_session", explode)

    for county in ("abbeville", "berkeley", "colleton", "dorchester", "florence"):
        assert name_index.bulk_by_date(county, "SC", "08/01/2026", "08/12/2026") == []
    # York is undetermined, not proven working — it must be refused too.
    assert name_index.bulk_by_date("york", "SC", "08/01/2026", "08/12/2026") == []


def test_date_filter_covers_every_host():
    """A host with no measured DATE_FILTER entry would fall through .get() to
    None and be refused, which is safe but silent. Force the pairing instead."""
    assert set(name_index.DATE_FILTER) == set(name_index.NAME_INDEX_HOSTS)


@pytest.mark.parametrize("doc_type,expected", [
    ("LIS PENDENS", True),
    ("NOTICE OF SEIZURE", True),
    ("NOT OF LEVY", True),
    ("FEDERAL TAX LIEN", True),
    ("JUDGEMENT", True),          # spelled this way in Florence's own list
    ("MECHANICS LIEN", True),
    ("DEED", False),
    ("MORTGAGE", False),          # new debt is not distress
    ("MARRIAGE LICENSE", False),
])
def test_distress_classification(doc_type, expected):
    assert bool(name_index.DISTRESS_TYPE_RE.search(doc_type)) is expected


def test_rows_ignores_the_repeating_header():
    """NameDisplay repeats the column header between date groups. Parsing by
    position would emit those as documents."""
    html = """
    <tr><td>Date</td><td>Code-Book-Page</td><td>Type</td><td>Description</td>
        <td>Amount</td><td>One Reverse Party</td></tr>
    <tr><td>08/10/2026</td><td>RECORD BOOK-5057-427</td><td>SATISFACTIO</td>
        <td>PD:FORECLOSURE BK 4589</td><td></td><td>MORTGAGE ELECTRONIC RE</td></tr>
    <tr><td>Date</td><td>Code-Book-Page</td><td>Type</td><td>Description</td>
        <td>Amount</td><td>One Reverse Party</td></tr>
    <tr><td>08/11/2026</td><td>RECORD BOOK-5058-273</td><td>DEED</td>
        <td>PD:LT 65 LITCHFIELD</td><td></td><td>PURDY FRANK RUSSELL IV</td></tr>
    """
    rows = name_index._rows(html)
    assert len(rows) == 2
    assert [r["doc_type"] for r in rows] == ["SATISFACTIO", "DEED"]
    # distress is caught via the DESCRIPTION here, not the type
    assert rows[0]["is_distress"] is True
    assert rows[1]["is_distress"] is False


def test_unknown_county_returns_empty_not_raises():
    assert name_index.lookup_name("buncombe", "NC", "SMITH") == []
    assert lookup.lookup_name("buncombe", "NC", "SMITH") == []
