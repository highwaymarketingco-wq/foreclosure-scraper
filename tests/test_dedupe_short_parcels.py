"""dedupe() must not merge two entries of ONE source's roll that carry different parcel ids, even
when the ids are too short to count as valid parcels (2026-10-06).

THE DEFECT LEFT AFTER dedupe.identity_conflict (240b8de9). Replayed on the fresh four-source
scrape (spartanburg_vacant, spartanburg_condemned, buncombe_delinquent_tax, rutherford_tax;
16,932 records) the identity rule leaves no output row with two valid parcels or two real house
numbers (the old rule left 755), but 21 rutherford_tax pairs were still merged: the same real house
number (or '146 WALDO LN' twice) and an address that scores >= 92, with two different parcel ids,
different tax bills, different amounts and (19 of 21) different taxpayers. Rutherford's roll mixes
6-digit and 7-digit ids; an id under placeholder_twins.MIN_PARCEL_LEN (7) is not a valid parcel
(validation.py nulls it as not unique), so identity_conflict saw no parcel on that side and nothing
else refused the merge.

THE RULE (dedupe.different_source_parcels). A short id cannot prove two rows are the SAME property,
but two different ids published by ONE source, in one county, are two entries of that source's
roll. Both rows must carry such an id from the same source (an id a resolver attached, an
over-shared one, one repeated character, a recorded-document pattern or one under
MIN_SOURCE_PARCEL_LEN characters never counts). Ids from two DIFFERENT sources are two id systems
and still do not conflict.

Every pair in REAL_PAIRS is a real row pair from that scrape (parcel ids, situs and zip as the
county published them); owner names are replaced.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper import dedupe as D
from foreclosure_scraper.board_dedupe_stream import find_dedupe_merge_groups
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import write_artifact

T = datetime(2026, 10, 5, 20, 5)
RUTHERFORD_URL = ("https://www.rutherfordcountync.gov/TR-452%20Delinquent%20Bills%20Report%20w%20"
                  "Parcel%20Id.xlsx")


def row(parcel, addr, zip_code="28043", owner=None, source="counties_nc.rutherford_tax",
        county="Rutherford", **kw) -> Listing:
    base = dict(source=source, source_url=RUTHERFORD_URL, listing_type=ListingType.TAX_LIEN,
                state="NC", county=county, zip_code=zip_code, parcel_id=parcel,
                street_address=addr, owner_name=owner, first_seen=T, last_seen=T)
    base.update(kw)
    return Listing(**base)


def parcels(out) -> list:
    return sorted(li.parcel_id or "" for li in out)


# (parcel, situs, zip) x 2: one source, two bills, two parcels. Eight of the 21 pairs have a
# different street name on one side ('173 E MAIN ST' / '173 N MAIN ST'), the rest the same situs.
REAL_PAIRS = [
    (("430941", "173 E MAIN ST", "28043"), ("1624538", "173 N MAIN ST", "28139")),
    (("1601271", "197 OLD CHURCH ST", "28114"), ("425109", "197 N CHURCH ST", "28043")),
    (("915784", "139 INGLE HILL ST", "28114"), ("1637150", "139 INGLE HILL ST", "28114")),
    (("1200978", "215 APT A N MAIN ST", "28139"), ("222032", "215 MAIN ST", "28720")),
    (("1626363", "146 WALDO LN", "28018"), ("320042", "146 WALDO LN", "28018")),
    (("1628211", "217 JORDON TRL", "28018"), ("713143", "217 JORDON TRL", "28018")),
    (("809786", "1083 US 64/74A HWY", "28139"), ("1627671", "1083 US 64/74A HWY", "28139")),
    (("1622263", "147 SHASTA LN", "28114"), ("908154", "147 SHASTA LN", "28114")),
    (("1201667", "163 N MAIN ST", "28139"), ("915945", "163 N MAIN ST", "28114")),
    (("425428", "219 E MAIN ST", "28043"), ("330069", "219 MAIN ST", "28040")),
    (("329127", "183 LEDFORD RD", "28040"), ("1619686", "183 LEDFORD RD", "28040")),
    (("914669", "150 POWELL RD", "28043"), ("1622391", "150 HOWELL RD", "28746")),
    (("1631681", "540 MAIN ST", "28040"), ("327689", "540 MAIN ST", "28040")),
    (("421048", "207 E TRADE ST", "28043"), ("422617", "207 E TRADE ST", "28043")),
    (("916080", "132 BRANCH ST", "28114"), ("1209030", "132 BRANCH ST", "28139")),
    (("911936", "5040 US 221S HWY", "28043"), ("1647414", "5040 US 221S HWY", "28043")),
    (("605674", "583 ROPER LOOP RD", "28139"), ("1650397", "583 ROPER LOOP RD", "28139")),
    (("915579", "132 MCCROW RD", "28076"), ("911297", "132 MCCROW RD", "28114")),
    (("431595", "190 E MAIN ST", "28043"), ("1652699", "190 S MAIN ST", "28018")),
    (("329150", "1021 OLD HOLLIS RD", "28040"), ("1628637", "1021 HOLLIS RD", "28018")),
    (("323133", "667 WEBB RD", "28040"), ("317482", "667 WEBB RD", "28043")),
]


def _pair(pair):
    return [row(p, a, z, owner=f"OWNER {n}") for n, (p, a, z) in zip("AB", pair)]


@pytest.mark.parametrize("reverse", [False, True], ids=["in-order", "reversed"])
@pytest.mark.parametrize("pair", REAL_PAIRS, ids=[p[0][1] for p in REAL_PAIRS])
def test_real_rutherford_pairs_with_different_parcels_stay_two_rows(pair, reverse):
    rows = _pair(pair)
    out = D.dedupe(rows[::-1] if reverse else rows)
    assert len(out) == 2
    assert parcels(out) == sorted([pair[0][0], pair[1][0]])
    for li in out:                                  # each row still shows its own property
        src = next(r for r in rows if r.parcel_id == li.parcel_id)
        assert (li.street_address, li.owner_name) == (src.street_address, src.owner_name)


def test_all_21_real_pairs_together_keep_42_rows():
    rows = [r for pair in REAL_PAIRS for r in _pair(pair)]
    assert len(D.dedupe(rows)) == 42


# ---------------------------------------------------------------- what still merges
def test_the_same_short_parcel_spelled_two_ways_still_merges():
    a = row("320042", "146 WALDO LN", "28018")
    b = row("320042", "146 Waldo Lane", "28018")
    c = row("32-0042", "146 WALDO LN", "28018")
    assert len(D.dedupe([a, b])) == 1               # pass 1 key, address spelling differs
    assert len(D.dedupe([a, c])) == 1               # parcel formatting variant


def test_a_short_parcel_row_and_a_parcel_less_copy_of_the_same_house_still_merge():
    a = row("320042", "146 WALDO LN", "28018")
    b = row(None, "146 WALDO LN", "28018", source="counties_nc.rutherford_wildfire_tax")
    assert len(D.dedupe([a, b])) == 1


def test_different_ids_from_two_different_sources_are_two_id_systems_not_two_properties():
    """Catawba-style: a tax-account number from one source, a parcel number from another."""
    a = row("320042", "146 WALDO LN", "28018")
    b = row("1626363", "146 WALDO LN", "28018", source="counties_nc.rutherford_wildfire_tax")
    out = D.dedupe([a, b])
    assert len(out) == 1


def test_a_resolver_attached_id_is_no_evidence():
    a = row("320042", "146 WALDO LN", "28018")
    b = row("1626363", "146 WALDO LN", "28018", raw={"parcel_from_address": {"source": "gis"}})
    assert len(D.dedupe([a, b])) == 1


def test_ids_under_the_floor_are_no_evidence():
    a = row("123", "146 WALDO LN", "28018")
    b = row("456", "146 WALDO LN", "28018")
    assert len(D.dedupe([a, b])) == 1
    assert D.source_parcel("NC", "Rutherford", "123", {}, "s") == frozenset()
    assert D.source_parcel("NC", "Rutherford", "1234", {}, "s")


@pytest.mark.parametrize("pid,raw,source,overshared", [
    ("0000000", {}, "s", frozenset()),                           # one repeated character
    ("B123P456", {}, "s", frozenset()),                          # recorded-document pattern
    ("pinehurst", {}, "s", frozenset()),                         # digitless
    ("320042", {"parcel_from_geo": {"lat": 1}}, "s", frozenset()),   # a resolver's
    ("320042", {}, None, frozenset()),                           # no source
    ("320042", {}, "s", frozenset({"NC|rutherford|320042"})),    # over-shared
])
def test_source_parcel_ignores(pid, raw, source, overshared):
    assert D.source_parcel("NC", "Rutherford", pid, raw, source, overshared) == frozenset()


def test_source_parcel_and_conflict_shape():
    a = D.identity_of("NC", "Rutherford", "320042", "146 WALDO LN", {}, source="s1")
    b = D.identity_of("NC", "Rutherford", "1626363", "146 WALDO LN", {}, source="s1")
    c = D.identity_of("NC", "Rutherfordton", "1626363", "146 WALDO LN", {}, source="s1")
    d = D.identity_of("NC", "Rutherford", "1626363", "146 WALDO LN", {}, source="s2")
    e = D.identity_of("NC", "Polk", "1626363", "146 WALDO LN", {}, source="s1")
    assert a.pk is None and b.pk is not None            # 6 chars is not a valid parcel
    assert D.identity_conflict(a, b) == "parcel"
    assert D.identity_conflict(a, c) == "parcel"        # one county written two ways
    assert D.identity_conflict(a, d) is None            # another source's id
    assert D.identity_conflict(a, e) is None            # another county
    assert D.identity_conflict(b, c) is None            # same parcel, county spelled two ways


# ---------------------------------------------------------------- groups, passes, streaming
def test_a_merged_group_remembers_every_source_id_it_took_in():
    """A (source s1, id X) merges with B (source s2, another id) on the address; C (s1, id Y) must
    then not join that group, in pass 2 or through union-find in pass 3, in any order."""
    def rows():
        return {
            "A": row("320042", "146 WALDO LN", "28018", raw={"_m": {"A": 1}}),
            "B": row("1626363", "146 WALDO LN", "28018", source="counties_nc.rutherford_wildfire_tax",
                     raw={"_m": {"B": 1}}),
            "C": row("713143", "146 WALDO LN", "28018", raw={"_m": {"C": 1}}),
        }
    for order in ("ABC", "CBA", "BAC", "ACB", "BCA", "CAB"):
        r = rows()
        out = D.dedupe([r[k] for k in order])
        members = sorted("".join(sorted(x.raw["_m"])) for x in out)
        assert len(out) == 2 and "AC" not in members and not any(
            m == "ABC" for m in members), (order, members)


def test_pass_three_signatures_refuse_it_too():
    """No zip and no overlap in pass 2's blocks: only the ('s', street, county, state) signature
    can join them, and it must refuse the same way."""
    a = row("320042", "146 WALDO LANE", None)
    b = row("1626363", "146 WALDO LN", None)
    assert len(D.dedupe([a, b])) == 2
    c = row("320042", "146 WALDO LN", None)
    assert len(D.dedupe([a, c])) == 1


def test_streamed_finder_refuses_the_same_pair(tmp_path):
    """board_dedupe_stream builds light Listings; they carry source and parcel_id, so the streamed
    finder agrees with dedupe()."""
    rows = _pair(REAL_PAIRS[4]) + [row("320042", "146 Waldo Lane", "28018", owner="OWNER C",
                                       source="counties_nc.rutherford_wildfire_tax")]
    write_artifact(rows, {"notes": "seed"}, docs_dir=tmp_path)
    real = D.dedupe([li.model_copy(deep=True) for li in rows])
    groups, stats = find_dedupe_merge_groups(tmp_path)
    assert stats["skipped"] == 0
    assert len(real) == 2
    assert len(groups) == 1 and len(groups[0]) == 2     # the wildfire row joins one of the two
