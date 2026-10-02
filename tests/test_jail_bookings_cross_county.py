"""Dirty Deeds Tier B #36 — standing re-query + cross-county re-identification.

The synthesis's exact framing: "rosters are wired; what is missing is a
standing re-query... a fugitive heir was lost for months, then a saved search
re-fired on a NEW booking in a DIFFERENT county, and that closed the deal."

What these pin end-to-end (through enrich_jail_bookings, i.e. what a real
pipeline run does):
  * a first-time same-county match carries facility_type="jail",
    is_new_booking=True and a first_detected_at timestamp
  * a SECOND run of the identical roster leaves an already-matched listing
    untouched (match_rosters' existing skip-once-matched rule — unchanged)
  * a listing whose OWN property county has NO roster coverage still gets
    flagged when its owner's name is new to a DIFFERENT covered county's
    roster this run — raw['jail_booking_new'], not raw['jail_booking'] or
    raw['incarceration'] (must not move an existing distress_score count)
  * the SAME cross-county pairing does not re-fire on a later run once the
    sidecar no longer considers it new
  * an entity-owned listing (LLC) is never flagged by either lane
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_jail_bookings import enrich_jail_bookings
from foreclosure_scraper.models import Listing


class _FakeZuercherSession:
    """Serves one Zuercher-shaped roster per zuercherportal.com host."""

    def __init__(self, hosts: dict):
        self.hosts = hosts          # {"cherokee-so-sc": [rec, ...], ...}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, timeout=None):
        subdomain = url.split("//", 1)[1].split(".zuercherportal.com")[0]
        return _Resp({"records": self.hosts.get(subdomain, [])})


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def _rec(last_first: str, arrest="2026-09-01T00:00:00.000Z", charge="TRESPASSING"):
    return {"name": last_first, "dob": None, "arrest_date": arrest,
            "hold_reasons": [charge]}


def _patch_zuercher(monkeypatch, hosts: dict):
    import curl_cffi.requests as ccr
    fake = _FakeZuercherSession(hosts)
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    return fake


def _li(state, county, owner):
    return Listing(source="test", source_url="http://x", state=state,
                   county=county, raw={"owner_mailing": {"owner": owner}})


@pytest.mark.asyncio
async def test_first_match_carries_facility_type_and_new_booking_metadata(monkeypatch):
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Adams, Bruce Edward")]})
    li = _li("SC", "Cherokee", "ADAMS BRUCE")
    await enrich_jail_bookings([li])
    jbk = li.raw["jail_booking"]
    assert jbk["facility_type"] == "jail"
    assert jbk["is_new_booking"] is True
    assert jbk["first_detected_at"]          # a real timestamp, not None


@pytest.mark.asyncio
async def test_rerunning_the_same_roster_does_not_touch_an_already_matched_listing(monkeypatch):
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Adams, Bruce Edward")]})
    li = _li("SC", "Cherokee", "ADAMS BRUCE")
    await enrich_jail_bookings([li])
    first_pass = dict(li.raw["jail_booking"])
    await enrich_jail_bookings([li])          # match_rosters' own skip-once-set rule
    assert li.raw["jail_booking"] == first_pass


@pytest.mark.asyncio
async def test_cross_county_flags_an_owner_whose_property_county_has_no_roster(monkeypatch):
    # Spartanburg SC has NO roster entry at all (its portal is offline — see
    # ROSTERS' own docstring); a property sitting there whose owner turns up
    # booked in Cherokee must still be caught. A second listing whose OWN
    # county IS Cherokee is what makes the pipeline fetch Cherokee's roster in
    # the first place (bulk_needed is driven by listing counties). The owner's
    # middle name ("ANNE") must agree with the booking's — fixed 2026-10-02,
    # see enrichment_jail_bookings.py's "CROSS-COUNTY NAME-ONLY FANOUT" —
    # or this match is no longer stamped at all (see the rejection tests below).
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Fugitive, Heir Anne")]})
    home = _li("SC", "Spartanburg", "FUGITIVE HEIR ANNE")   # property county: no roster
    trigger = _li("SC", "Cherokee", "NOBODY MATCHES HERE")  # forces Cherokee's roster fetch
    res = await enrich_jail_bookings([home, trigger])
    assert res["cross_county"] == 1
    jn = home.raw["jail_booking_new"]
    assert jn["county"] == "Cherokee"
    assert jn["home_county"] == "Spartanburg"
    assert jn["cross_county"] is True
    assert jn["confidence"] == "middle_corroborated_cross_county"
    assert jn["middle_verdict"] == "agrees"
    assert jn["facility_type"] == "jail"
    assert jn["first_detected_at"]
    # must NOT touch the same-county / scored keys
    assert "jail_booking" not in home.raw
    assert "incarceration" not in home.raw
    assert "jail_booking_new" not in trigger.raw


@pytest.mark.asyncio
async def test_cross_county_rejects_a_common_name_with_no_middle_corroboration(monkeypatch):
    """The actual 2026-10-02 incident, reproduced: an exact first+last match
    with NO other corroborating field (no middle name on the owner side) must
    NOT be stamped — this is what fanned one common booked name out to 12,337
    unrelated board rows in the real run. Same fixture as the accept-case test
    above, minus the owner's middle name, is the whole difference."""
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Fugitive, Heir Anne")]})
    home = _li("SC", "Spartanburg", "FUGITIVE HEIR")         # no middle name at all
    trigger = _li("SC", "Cherokee", "NOBODY MATCHES HERE")
    res = await enrich_jail_bookings([home, trigger])
    assert res["cross_county"] == 0
    assert "jail_booking_new" not in home.raw


@pytest.mark.asyncio
async def test_cross_county_rejects_a_conflicting_middle_name(monkeypatch):
    """Same first+last, but the owner's middle name provably disagrees with the
    booking's — a different person who happens to share a common name, same
    class of false positive name_normalize.party_middle_conflict exists to
    catch for the SC-divorce match (41% of comparable hits, audit 2026-09-21)."""
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Fugitive, Heir Anne")]})
    home = _li("SC", "Spartanburg", "FUGITIVE HEIR ZOE")     # middle initial Z != A
    trigger = _li("SC", "Cherokee", "NOBODY MATCHES HERE")
    res = await enrich_jail_bookings([home, trigger])
    assert res["cross_county"] == 0
    assert "jail_booking_new" not in home.raw


@pytest.mark.asyncio
async def test_a_booking_in_its_own_property_county_is_never_also_flagged_cross_county(monkeypatch):
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Local, Person Andrew")]})
    li = _li("SC", "Cherokee", "LOCAL PERSON")
    res = await enrich_jail_bookings([li])
    assert res["matched"] == 1
    assert res["cross_county"] == 0
    assert "jail_booking_new" not in li.raw


@pytest.mark.asyncio
async def test_cross_county_pairing_does_not_refire_once_no_longer_new(monkeypatch):
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Fugitive, Heir Anne")]})
    home = _li("SC", "Spartanburg", "FUGITIVE HEIR ANNE")   # middle agrees — see accept-case test
    trigger = _li("SC", "Cherokee", "NOBODY MATCHES HERE")
    res1 = await enrich_jail_bookings([home, trigger])
    assert res1["cross_county"] == 1
    first = dict(home.raw["jail_booking_new"])

    # A later run re-fetches the SAME roster contents, so jail_roster_history
    # now reports is_new_booking=False for this name — the pairing already
    # fired once and must not fire again on a fresh listing (match_cross_county's
    # own already-flagged guard only covers the SAME run/listing).
    home2 = _li("SC", "Spartanburg", "FUGITIVE HEIR ANNE")
    trigger2 = _li("SC", "Cherokee", "NOBODY MATCHES HERE")
    res2 = await enrich_jail_bookings([home2, trigger2])
    assert res2["cross_county"] == 0
    assert "jail_booking_new" not in home2.raw
    # the original flag on the first listing is untouched by the second run
    assert home.raw["jail_booking_new"] == first


@pytest.mark.asyncio
async def test_entity_owned_listing_is_never_flagged_by_either_lane(monkeypatch):
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Holdings, Acme LLC")]})
    li = _li("SC", "Spartanburg", "ACME HOLDINGS LLC")
    trigger = _li("SC", "Cherokee", "NOBODY MATCHES HERE")
    res = await enrich_jail_bookings([li, trigger])
    assert res["matched"] == 0
    assert res.get("cross_county", 0) == 0
    assert "jail_booking" not in li.raw
    assert "jail_booking_new" not in li.raw


# ---- dry_run -- 2026-09-29 fix -------------------------------------------
#
# scripts/run_pending_signal_enrichers.py --dry-run found 590 genuine
# jail_booking_new cross-county matches (real fresh jail roster data); the
# REAL (non-dry-run) apply pass ~35 minutes later found 0 new matches for the
# same counties, because the dry run's own roster fetch had already been
# diffed-and-recorded into jail_roster_history.db as "seen." These pin the
# fix end-to-end through enrich_jail_bookings, mirroring
# test_jail_roster_history.py's lower-level sidecar coverage of the same fix.

@pytest.mark.asyncio
async def test_dry_run_does_not_persist_to_the_sidecar(monkeypatch):
    from foreclosure_scraper import jail_roster_history as jrh
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Adams, Bruce Edward")]})
    li = _li("SC", "Cherokee", "ADAMS BRUCE")
    await enrich_jail_bookings([li], dry_run=True)
    # conftest's autouse _isolate_jail_roster_history fixture redirects
    # DB_PATH to a throwaway per-test file -- this reads that same file.
    con = jrh.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    finally:
        con.close()


@pytest.mark.asyncio
async def test_dry_run_still_computes_and_reports_is_new_booking(monkeypatch):
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Adams, Bruce Edward")]})
    li = _li("SC", "Cherokee", "ADAMS BRUCE")
    res = await enrich_jail_bookings([li], dry_run=True)
    assert res["matched"] == 1
    jbk = li.raw["jail_booking"]
    # accurate report even though nothing was persisted -- this is what makes
    # a dry run's own printed "590 new matches" count trustworthy
    assert jbk["is_new_booking"] is True
    assert jbk["first_detected_at"]


@pytest.mark.asyncio
async def test_real_run_after_a_dry_run_still_detects_the_same_new_booking(monkeypatch):
    """The exact 2026-09-29 regression, end to end: a --dry-run pass over a
    roster must not cause the REAL pass minutes later to see the same
    booking as already-seen (0 new matches)."""
    _patch_zuercher(monkeypatch, {"cherokee-so-sc": [_rec("Adams, Bruce Edward")]})

    dry_listing = _li("SC", "Cherokee", "ADAMS BRUCE")
    dry_res = await enrich_jail_bookings([dry_listing], dry_run=True)
    assert dry_res["matched"] == 1
    assert dry_listing.raw["jail_booking"]["is_new_booking"] is True

    # A separate listing stands in for "the real apply pass ~35 minutes
    # later" against the same roster/name -- this time for real.
    real_listing = _li("SC", "Cherokee", "ADAMS BRUCE")
    real_res = await enrich_jail_bookings([real_listing], dry_run=False)
    assert real_res["matched"] == 1
    assert real_listing.raw["jail_booking"]["is_new_booking"] is True

    # and the real run genuinely DID persist -- a second real run now
    # correctly sees the name as no longer new (normal idempotence, unbroken
    # by the fix).
    third_listing = _li("SC", "Cherokee", "ADAMS BRUCE")
    third_res = await enrich_jail_bookings([third_listing], dry_run=False)
    assert third_res["matched"] == 1
    assert third_listing.raw["jail_booking"]["is_new_booking"] is False
