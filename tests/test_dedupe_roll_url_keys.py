"""dedupe() must not fuse the rows of one county roll that share nothing but the roll's URL
(audit 2026-10-09, area regressions).

THE DEFECT. A row with no parcel id, no address and no case number is keyed by its source URL, and
a county roll's URL is the source_url of every row of the roll. A published row whose short id
validation nulled carries parcel_id None and the id only in raw['parcel_id_nulled'] or the source's
own raw block, so the short-source-parcel rule never saw it, and URL evidence merged two unnumbered
rows with no parcel. In the gated d42058b3 run Rutherford's roll was blocked from the VM, carryover
replayed its 5,109 published rows, and dedupe() fused the 580 that had no situs into ONE row; aged
PTS Cloud rows of five counties that share one URL fused across counties in the second dedupe.
Replayed on the 10/7 board's 25,578 URL-only rows (as aged copies) the old rule left 6,881 rows; the
fixed one merges only exact repeats of one record (216).

Fixtures are invented (owners, ids, URLs).
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper import dedupe as D
from foreclosure_scraper.models import Listing, ListingType

T = datetime(2026, 10, 8, 2, 0)
ROLL = "https://example.invalid/roll/TR-452.xlsx"
PORTAL = "https://example.invalid/ptscloud/"


def roll_row(short_id, owner, *, county="Rutherford", url=ROLL, source="counties_nc.rutherford_tax",
             nulled=False, aged=False, **kw) -> Listing:
    raw = {"rutherford_tax": {"parcel": short_id, "taxpayer": owner}} if not nulled else {
        "parcel_id_nulled": {"value": short_id, "reason": "too_short"}}
    if aged:
        raw["pulled_sale"] = {"consecutive_misses": 1, "presumed_withdrawn": True}
    base = dict(source=source, source_url=url, listing_type=ListingType.TAX_LIEN, state="NC",
                county=county, parcel_id=None, street_address=None, owner_name=owner, raw=raw,
                first_seen=T, last_seen=T)
    base.update(kw)
    return Listing(**base)


def test_replayed_roll_rows_with_nulled_ids_stay_apart():
    rows = [roll_row("426770", "OWNER A"), roll_row("514474", "OWNER B"), roll_row("230682", "OWNER C")]
    assert len({li.dedupe_key() for li in rows}) == 1          # one URL key for all three
    out = D.dedupe(rows)
    assert len(out) == 3
    assert sorted(li.owner_name for li in out) == ["OWNER A", "OWNER B", "OWNER C"]


def test_nulled_id_from_parcel_id_nulled_counts_too():
    rows = [roll_row("700001", "OWNER A", nulled=True, source="counties_nc.nc_ptscloud_delinquent_tax",
                     url=PORTAL, county="Madison"),
            roll_row("700002", "OWNER A", nulled=True, source="counties_nc.nc_ptscloud_delinquent_tax",
                     url=PORTAL, county="Madison")]
    # same owner, same county, same URL: two accounts of one roll are still two rows
    assert len(D.dedupe(rows)) == 2


def test_aged_rows_of_two_counties_sharing_a_portal_url_stay_apart():
    a = roll_row("25261", "OWNER A", nulled=True, source="counties_nc.nc_ptscloud_delinquent_tax",
                 url=PORTAL, county="Madison", aged=True)
    b = roll_row("25261", "OWNER A", nulled=True, source="counties_nc.nc_ptscloud_delinquent_tax",
                 url=PORTAL, county="Beaufort", aged=True)
    assert len(D.dedupe([a, b])) == 2


def test_the_same_record_twice_still_merges():
    a = roll_row("426770", "OWNER A", city="Forest City", zip_code="28043")
    b = roll_row("426770", "Owner  A", city="Forest City", zip_code="28043")
    out = D.dedupe([a, b])
    assert len(out) == 1


def test_rows_with_no_owner_and_no_id_never_merge_on_a_url():
    a = Listing(source="counties_generic.arcgis_distress.cleanup", source_url="https://example.invalid/",
                listing_type=ListingType.DISTRESSED, state="SC", county="Spartanburg", city="Chesnee",
                zip_code="29323", first_seen=T, last_seen=T)
    b = a.model_copy(deep=True)
    assert len(D.dedupe([a, b])) == 2


def test_identity_reads_the_nulled_short_id():
    li = roll_row("426770", "OWNER A")
    ident = D.identity(li)
    assert ident.sp and next(iter(ident.sp))[1] == "counties_nc.rutherford_tax"
    other = roll_row("514474", "OWNER B")
    assert D.different_source_parcels(ident, D.identity(other))
    # a row that carries its parcel id is unchanged: the nulled lookup is only a fallback
    assert D.nulled_source_parcel("1624538", li.raw, li.source) is None


def test_numbered_rows_of_one_address_with_two_nulled_ids_stay_apart():
    a = roll_row("430941", "OWNER A", street_address="173 E MAIN ST", zip_code="28043")
    b = roll_row("425109", "OWNER B", street_address="173 E MAIN ST", zip_code="28043")
    assert len(D.dedupe([a, b])) == 2


def test_url_key_conflict_reads_dicts_and_listings():
    a = {"county": "Madison", "owner_name": "OWNER A"}
    assert D.url_key_conflict(a, {"county": "Beaufort", "owner_name": "OWNER A"}) == "url_county"
    assert D.url_key_conflict(a, roll_row("1", "OWNER B", county="Madison")) == "url_owner"
    assert D.url_key_conflict(a, {"county": "madison", "owner_name": "owner a"}) is None
    assert D.url_key_conflict(a, {"county": "Madison", "owner_name": None}) is None
