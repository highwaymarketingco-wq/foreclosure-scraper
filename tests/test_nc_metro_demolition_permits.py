"""NC metro demolition permits (Mecklenburg, Greensboro, Durham, Cary).

Date-coverage audit fix, 2026-10-14 (docs/date_coverage_audit_2026-10-14.md, target #1):
`FORECLOSURE_DEMOLITION_DAYS` used to default to 730 and was baked into every feed's
WHERE clause as a hard floor, discarding a demolition permit the moment it turned two
years old even though every one of these feeds is a full, date-agnostic history (live-
verified 2026-10-14: Greensboro alone goes back to 1997-08-04, 3,023 rows all-time vs.
148 inside the old 730-day window -- a 95% exclusion rate). The fix drops the date floor
by default (`since=None`); `FORECLOSURE_DEMOLITION_DAYS` still narrows it when an operator
explicitly wants a sample run.

Live-verifying Mecklenburg also found a SEPARATE, unrelated break: the `AccelaAllPermits`
FeatureServer this file pointed at since 2026-10-07 now 404s outright (the county migrated
to a `BuildingPermits` service with a different field schema entirely), and the county's
own classification of "this is a demolition permit" changed shape at the same migration --
`worktype='Demolish'` is a legacy tag used only through 2017-03-09; every demolition since
is identifiable only by `permitdesc LIKE '%Demolish/Move Off%'`. Both fixes are verified
together below since they ship in the same commit. The fixture rows are real attribute
dicts (trimmed to the fields this module reads) pulled live from each service on
2026-10-14, not invented.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import httpx
import pytest

import foreclosure_scraper.scrapers.counties_nc.nc_metro_demolition_permits as m

MECK_URL = ("https://meckgis.mecklenburgcountync.gov/server/rest/services/"
            "BuildingPermits/FeatureServer/0")
GSO_URL = ("https://gis.greensboro-nc.gov/arcgis/rest/services/OpenGateCity/"
           "OpenData_HRES_DS/MapServer/2")
DURHAM_URL = ("https://webgis2.durhamnc.gov/server/rest/services/PublicServices/"
              "Inspections/MapServer/10")
CARY_URL = "https://data.townofcary.org/api/explore/v2.1/catalog/datasets/permit-applications/records"

MECK_FEED = next(f for f in m.FEEDS if f.name == "mecklenburg")
GSO_FEED = next(f for f in m.FEEDS if f.name == "greensboro")
DURHAM_FEED = next(f for f in m.FEEDS if f.name == "durham")
CARY_FEED = next(f for f in m.FEEDS if f.name == "cary")


# --------------------------------------------------------------------------- arcgis_where / cary_where

def test_mecklenburg_where_ors_the_legacy_tag_and_the_current_phrase_with_no_date_floor_by_default():
    where = m.arcgis_where(MECK_FEED, None)
    assert where == "(worktype='Demolish' OR permitdesc LIKE '%Demolish/Move Off%')"
    assert "DATE" not in where


def test_mecklenburg_where_adds_a_date_floor_only_when_since_is_given():
    since = datetime(2024, 10, 14, tzinfo=timezone.utc)
    where = m.arcgis_where(MECK_FEED, since)
    assert where == ("(worktype='Demolish' OR permitdesc LIKE '%Demolish/Move Off%') "
                     "AND issuedate >= DATE '2024-10-14'")


def test_greensboro_and_durham_where_drop_the_date_floor_by_default():
    assert m.arcgis_where(GSO_FEED, None) == "ApplicationType LIKE 'Total Demolish%'"
    assert m.arcgis_where(DURHAM_FEED, None) == "1=1"


def test_greensboro_and_durham_where_keep_the_old_shape_when_since_is_given():
    since = datetime(2024, 10, 14, tzinfo=timezone.utc)
    assert m.arcgis_where(GSO_FEED, since) == (
        "ApplicationType LIKE 'Total Demolish%' AND IssuedDate >= DATE '2024-10-14'")
    assert m.arcgis_where(DURHAM_FEED, since) == "ISSUE_DATE >= DATE '2024-10-14'"


def test_cary_where_drops_and_keeps_the_date_floor_the_same_way():
    assert m.cary_where(None) == (
        'permittypedesc in ("BLDG - DEMOLISH - SNGL FAM HOME (B645)","BLDG NON RES DEMOLITION (B649)")')
    since = datetime(2024, 10, 14, tzinfo=timezone.utc)
    assert m.cary_where(since).endswith("and applieddate >= date'2024-10-14'")


# --------------------------------------------------------------------------- _get fallback chain

def test_get_falls_back_through_a_tuple_when_the_first_field_is_blank():
    """Mecklenburg's post-migration rows carry an empty `worktype` -- `_get` must fall
    through to `permitdesc` instead of reporting no type at all."""
    legacy_row = {"worktype": "Demolish", "permitdesc": "TOTAL DEMO -"}
    current_row = {"worktype": "", "permitdesc": "DEMO HOUSE Demolish/Move Off. SF Dwelling Detached."}
    assert m._get(legacy_row, MECK_FEED, "type") == "Demolish"
    assert m._get(current_row, MECK_FEED, "type") == \
        "DEMO HOUSE Demolish/Move Off. SF Dwelling Detached."


def test_get_returns_none_when_every_candidate_in_the_chain_is_blank():
    assert m._get({"worktype": "", "permitdesc": ""}, MECK_FEED, "type") is None


# --------------------------------------------------------------------------- real-shaped fixture rows
#
# Real attribute dicts (trimmed to the fields this module reads), live 2026-10-14:
#   MECK_LEGACY_1991  meckgis BuildingPermits/0, worktype='Demolish' exact match, the OLDEST
#                      shape this feed carries -- 1991-04-11, 35 years before today.
#   MECK_CURRENT_2025 same service, worktype blank (the legacy tag stopped being used after
#                      2017-03), only identifiable via permitdesc's 'Demolish/Move Off' phrase.
#   GSO_1997 / GSO_2026   gis.greensboro-nc.gov BI_Permits, the measured oldest (1997-08-04)
#                      and a current (2026-09-24) row.
#   DURHAM_2007 / DURHAM_2026  webgis2.durhamnc.gov Demolition Permits, measured oldest
#                      (2007-10-25) and a current (2026-10-08) row.

MECK_LEGACY_1991 = {
    "permitnum": "B0012345", "permitdesc": "TOTAL DEMO -", "worktype": "Demolish",
    "permitstat": "Complete", "issuedate": 671342400000,            # 1991-04-11
    "projadd": "323 DELBURG ST", "parcelnum": "00327318", "taxjuris": "DAVIDSON",
    "zipcode": "28036", "ownname": "JCB URBAN CO INC", "owncity": "CHARLOTTE",
    "ownstate": "NC", "ownzipcode": 28204,
}
MECK_CURRENT_2025 = {
    "permitnum": "B4779880",
    "permitdesc": ("M. Brinkerhoff - Facilitator - 02.24.25 Sent to UnitsDEMO HOUSE AND "
                   "BUILDINGS Demolish/Move Off. SF Dwelling Detached."),
    "worktype": "", "permitstat": "Issued", "issuedate": 1741194000000,   # 2025-03-05
    "projadd": "1799  JAMESTON DR", "parcelnum": "12345678", "taxjuris": "CHARLOTTE",
    "zipcode": "28215", "ownname": "ROE JANE", "owncity": "CHARLOTTE",
    "ownstate": "NC", "ownzipcode": 28215,
}
GSO_1997 = {
    "PermitNum": "OLD000001", "ApplicationType": "Total Demolish", "CurrentStatus": "Complete",
    "IssuedDate": 870652800000,                                      # 1997-08-04
    "FullAddress": "100 OLD MILL RD", "OwnerName": "DOE JOHN",
    "OwnerMailAddress": "100 OLD MILL RD", "OwnerMailCity": "GREENSBORO",
    "OwnerMailState": "NC", "OwnerMailZip": "27401",
}
GSO_2026 = {
    "PermitNum": "DEM260924", "ApplicationType": "Total Demolish", "CurrentStatus": "Issued",
    "IssuedDate": 1790250360000,                                     # 2026-09-24
    "FullAddress": "200 NEW ST", "OwnerName": "ROE SAM",
    "OwnerMailAddress": "200 NEW ST", "OwnerMailCity": "GREENSBORO",
    "OwnerMailState": "NC", "OwnerMailZip": "27403",
}
DURHAM_2007 = {
    "PermitNum": "DUR2007A", "PID": "123456", "PIN15": "1234567890",
    "ISSUE_DATE": 1193326203000,                                     # 2007-10-25
    "TYPE": "Demolition", "PmtStatus": "Complete",
}
DURHAM_2026 = {
    "PermitNum": "DUR2026A", "PID": "654321", "PIN15": "9876543210",
    "ISSUE_DATE": 1791475231000,                                     # 2026-10-08
    "TYPE": "Demolition", "PmtStatus": "Issued",
}
CARY_2019 = {
    "permitnum": "20-00002279", "applieddate": "2019-09-10", "issuedate": None,
    "statuscurrent": "CLOSED (CL)", "originaladdress1": "3700 TEN TEN RD",
    "originalcity": "APEX", "originalzip": "27539", "pin": "761303237",
    "permittypedesc": "BLDG - DEMOLISH - SNGL FAM HOME (B645)",
    "ownername": "WARREN ALLEN", "owneraddress1": "3700 TEN TEN RD", "ownerzip": "27539",
}
CARY_2026 = {
    "permitnum": "26-00001000", "applieddate": "2026-09-01", "issuedate": "2026-09-05",
    "statuscurrent": "ISSUED", "originaladdress1": "50 CHAPEL HILL RD",
    "originalcity": "CARY", "originalzip": "27511", "pin": "761399999",
    "permittypedesc": "BLDG - DEMOLISH - SNGL FAM HOME (B645)",
    "ownername": "ROE ANN", "owneraddress1": "50 CHAPEL HILL RD", "ownerzip": "27511",
}


def test_mecklenburg_legacy_1991_row_becomes_a_listing_with_its_real_type_tag():
    [g] = m.group_permits(MECK_FEED, [MECK_LEGACY_1991])
    li = m.to_listing(g)
    assert li.parcel_id == "00327318" and li.street_address == "323 DELBURG ST"
    assert li.raw["demolition_permit"]["permits"][0]["date"] == "1991-04-11"
    assert li.raw["demolition_permit"]["permits"][0]["type"] == "Demolish"
    # new schema has no owner-mailing street field: city/state/zip only.
    assert li.raw["owner_mailing"]["mailing"] == "CHARLOTTE NC 28204"


def test_mecklenburg_current_2025_row_is_only_identifiable_via_permitdesc_and_still_becomes_a_listing():
    """The row the OLD `type_of_work='Demolition'` filter (and a blank `worktype`) would
    both have missed -- this is exactly the row the migration broke and the fix restores."""
    [g] = m.group_permits(MECK_FEED, [MECK_CURRENT_2025])
    li = m.to_listing(g)
    assert li.parcel_id == "12345678"
    assert "Demolish/Move Off" in li.raw["demolition_permit"]["permits"][0]["type"]
    assert li.raw["demolition_permit"]["permits"][0]["date"] == "2025-03-05"


@pytest.mark.parametrize("feed,old_row,new_row,old_date", [
    (GSO_FEED, GSO_1997, GSO_2026, "1997-08-04"),
    (DURHAM_FEED, DURHAM_2007, DURHAM_2026, "2007-10-25"),
])
def test_an_old_row_far_outside_the_old_730_day_window_still_becomes_a_listing(feed, old_row, new_row, old_date):
    """`group_permits`/`to_listing` apply no date logic of their own -- whatever rows the
    fetch returns all become listings. This is the behavior `since=None` now relies on:
    a permit decades old is never dropped once it is in the row set."""
    [old_g] = m.group_permits(feed, [old_row])
    old_li = m.to_listing(old_g)
    assert old_li.raw["demolition_permit"]["latest_date"] == old_date
    [new_g] = m.group_permits(feed, [new_row])
    new_li = m.to_listing(new_g)
    assert new_li.raw["demolition_permit"]["latest_date"] != old_date


# --------------------------------------------------------------------------- full fetch() integration
#
# A mock transport that actually HONORS the WHERE clause's date floor (extracting the
# literal `DATE '...'`/`date'...'` the code constructs) so this is a real end-to-end
# regression for the bug: the old row must be ABSENT when a date floor is requested, and
# PRESENT when none is (the default, post-fix, behavior).

_ARCGIS_DATE_RE = re.compile(r"date\s*'(\d{4}-\d{2}-\d{2})'", re.I)


def _where_from(request: httpx.Request) -> str:
    if request.method == "GET":
        return request.url.params.get("where", "")
    body = urllib.parse.parse_qsl(request.content.decode())
    return dict(body).get("where", "")


def _cutoff(where: str) -> str | None:
    mo = _ARCGIS_DATE_RE.search(where)
    return mo.group(1) if mo else None


def _ms(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _arcgis_handler(rows: list[dict], date_field: str):
    def handler(request: httpx.Request) -> httpx.Response:
        where = _where_from(request)
        cutoff = _cutoff(where)
        kept = rows if cutoff is None else [r for r in rows if (r.get(date_field) or 0) >= _ms(cutoff)]
        return httpx.Response(200, json={"objectIdFieldName": "OBJECTID",
                                         "features": [{"attributes": r} for r in kept],
                                         "exceededTransferLimit": False})
    return handler


def _combined_transport():
    meck = _arcgis_handler([MECK_LEGACY_1991, MECK_CURRENT_2025], "issuedate")
    gso = _arcgis_handler([GSO_1997, GSO_2026], "IssuedDate")
    durham = _arcgis_handler([DURHAM_2007, DURHAM_2026], "ISSUE_DATE")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if MECK_URL in url:
            return meck(request)
        if GSO_URL in url:
            return gso(request)
        if DURHAM_URL in url:
            return durham(request)
        if CARY_URL in url:
            where = request.url.params.get("where", "")
            cutoff_mo = re.search(r"date'(\d{4}-\d{2}-\d{2})'", where)
            rows = [CARY_2019, CARY_2026]
            if cutoff_mo:
                rows = [r for r in rows if r["applieddate"] >= cutoff_mo.group(1)]
            return httpx.Response(200, json={"results": rows, "total_count": len(rows)})
        return httpx.Response(404, json={"error": f"no route for {url}"})
    return httpx.MockTransport(handler)


@pytest.fixture
def _patched_client(monkeypatch):
    transport = _combined_transport()
    monkeypatch.setattr(m, "client",
                        lambda timeout=60.0: httpx.AsyncClient(transport=transport))


def test_fetch_with_no_date_floor_includes_decades_old_permits(_patched_client, monkeypatch):
    """The actual fix: with FORECLOSURE_DEMOLITION_DAYS unset (the new default), every
    feed's full all-time history comes back, including the oldest row on each feed."""
    monkeypatch.delenv("FORECLOSURE_DEMOLITION_DAYS", raising=False)
    out = asyncio.run(m.NCMetroDemolitionPermits().fetch())
    by_feed = {li.raw["demolition_permit"]["feed"]: [] for li in out}
    for li in out:
        by_feed[li.raw["demolition_permit"]["feed"]].append(li.raw["demolition_permit"]["latest_date"])
    assert "1991-04-11" in by_feed["mecklenburg"] and "2025-03-05" in by_feed["mecklenburg"]
    assert "1997-08-04" in by_feed["greensboro"] and "2026-09-24" in by_feed["greensboro"]
    assert "2007-10-25" in by_feed["durham"] and "2026-10-08" in by_feed["durham"]
    assert "2019-09-10" in by_feed["cary"] and "2026-09-01" in by_feed["cary"]
    assert len(out) == 8          # 2 rows x 4 feeds, nothing filtered


def test_fetch_with_an_explicit_days_window_still_drops_the_old_rows(_patched_client, monkeypatch):
    """`FORECLOSURE_DEMOLITION_DAYS` still works for an operator who wants the OLD, narrower
    behavior on purpose -- proving the knob survived the fix, just with a different default."""
    monkeypatch.setenv("FORECLOSURE_DEMOLITION_DAYS", "730")
    out = asyncio.run(m.NCMetroDemolitionPermits().fetch())
    dates = {li.raw["demolition_permit"]["latest_date"] for li in out}
    assert "1991-04-11" not in dates and "1997-08-04" not in dates
    assert "2007-10-25" not in dates and "2019-09-10" not in dates
    assert len(out) == 4          # only the 4 "current" rows survive the 730-day floor
