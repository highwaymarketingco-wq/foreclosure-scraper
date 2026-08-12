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


# --- pick-list cap ---------------------------------------------------------
# Haywood returned EXACTLY 1000 parties for a 21-day window and 385 for a
# 3-day one. 1000 is a cap, not a count, and a capped window silently drops
# filings — for a foreclosure-start feed that means missing the leads the
# source exists to find.

def test_split_halves_a_window():
    assert lookup._split("08/01/2026", "08/11/2026") == [
        ("08/01/2026", "08/06/2026"), ("08/07/2026", "08/11/2026")]


def test_split_refuses_to_go_below_one_day():
    assert lookup._split("08/01/2026", "08/01/2026") == []


def test_split_halves_are_contiguous_and_do_not_overlap():
    from datetime import datetime
    (a1, b1), (a2, b2) = lookup._split("01/01/2026", "01/31/2026")
    d = lambda s: datetime.strptime(s, "%m/%d/%Y")  # noqa: E731
    assert d(a1) == d("01/01/2026") and d(b2) == d("01/31/2026")
    assert (d(a2) - d(b1)).days == 1, "a day would be skipped between halves"


class _FakeResp:
    def __init__(self, text):
        self.status_code, self.text = 200, text


class _FakeSession:
    """Serves a capped pick list for any window wider than 3 days, and a small
    one below that — the shape Haywood actually exhibits."""

    def __init__(self, seen):
        self.seen = seen

    def get(self, url, params=None, headers=None, timeout=None):
        p = dict(params or {})
        if p.get("show_pick_list") == "1":
            from datetime import datetime
            a = datetime.strptime(p["start_date"], "%m/%d/%Y")
            b = datetime.strptime(p["end_date"], "%m/%d/%Y")
            self.seen.append((p["start_date"], p["end_date"]))
            n = lookup.PICK_LIST_CAP if (b - a).days > 3 else 2
            ids = "".join(f'<input name="entityID[]" value="{i}"/>'
                          for i in range(n))
            return _FakeResp('<input type="hidden" name="searchType" '
                             f'value="name"/>{ids}')
        # document fetch — one parseable row, padded past the 4000-byte floor
        row = ("<tr><td>19860911 08/01/2026</td><td>RB 1 1</td><td>S/T</td>"
               "<td></td><td>GRANTOR</td><td>DOE JANE</td><td>BANK</td></tr>")
        return _FakeResp(row + "<!--" + "x" * 4200 + "-->")


def test_capped_window_is_split_until_it_fits(monkeypatch):
    """A capped window must be halved and both halves read, never returned."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(lookup, "_session", lambda host: _FakeSession(seen))
    monkeypatch.setattr(lookup, "_throttle", lambda host: None)

    rows = lookup.bulk_by_date("haywood", "NC", "08/01/2026", "08/29/2026")

    assert seen[0] == ("08/01/2026", "08/29/2026"), "should try the full window"
    assert len(seen) > 1, "capped window was returned instead of being split"
    # every window finally read must be small enough to be under the cap
    from datetime import datetime
    d = lambda s: datetime.strptime(s, "%m/%d/%Y")  # noqa: E731
    assert any((d(b) - d(a)).days <= 3 for a, b in seen)
    assert rows, "splitting produced no rows at all"


def test_uncapped_window_is_not_split(monkeypatch):
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(lookup, "_session", lambda host: _FakeSession(seen))
    monkeypatch.setattr(lookup, "_throttle", lambda host: None)

    lookup.bulk_by_date("haywood", "NC", "08/01/2026", "08/03/2026")
    assert seen == [("08/01/2026", "08/03/2026")]
