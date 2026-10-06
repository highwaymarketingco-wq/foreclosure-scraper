"""The jail_booking verifier (verification/verifiers/jail_booking.py).

What these pin:
  * applies(): only this pipeline's own same-county stamps that still claim custody;
  * the verdicts, through the REAL enrichment_jail_bookings._load_roster + RosterIndex +
    jail_roster_history health judge (vendor HTTP faked at the curl_cffi layer, like the jail
    module's own tests): confirmed (middle agrees), refuted (middle conflicts), stale (absent
    from a HEALTHY roster), and every unconfirmed path, above all that a failed, empty,
    truncated or history-less roster NEVER yields stale;
  * one roster fetch per county per sweep run, whatever the number of rows;
  * the verifier records roster sizes in its OWN history file, never the pipeline's sidecar;
  * parity with the run's own re-evaluation (_reevaluate_stamp) on the same roster;
  * scoring: a refuted/stale verdict ("incarceration:jail") ends a JAIL-sourced incarceration
    flag only; a NC DAC / SC DOC / BOP flag on the same row is never touched.
Names are placeholders except the FINDINGS.md section 5 shape (owner "DAWKINS CHRISTOPHER A" vs
inmate "Christopher Keith Dawkins").
"""
from __future__ import annotations

import asyncio
import copy
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper import enrichment_jail_bookings as jb
from foreclosure_scraper import jail_roster_history as jrh
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.apply import apply_verification
from foreclosure_scraper.verification.ledger import Ledger
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import jail_booking as v

TODAY = date(2026, 10, 6)
DAC = "NC DAC offender search"
SCDC = "SC DOC inmate search"
BOP = "BOP inmate locator"


@pytest.fixture(autouse=True)
def _own_history(monkeypatch, tmp_path):
    """The verifier's history file in a temp dir (the pipeline's sidecar is already isolated
    by conftest), and no roster cache carried between tests."""
    monkeypatch.setenv("VERIFY_JAIL_HISTORY_DB", str(tmp_path / "verifier_history.db"))
    v._RUNS.clear()


# --------------------------------------------------------------------------- #
# rows                                                                        #
# --------------------------------------------------------------------------- #

def _stamp(county="Cherokee", state="SC", matched="CHRISTOPHER DAWKINS", **extra):
    s = {"county": county, "state": state, "matched_name": matched,
         "release_status": "in_custody", "scheduled_release": None,
         "confidence": "name_only_low", "facility_type": "jail", "arrest_date": "2026-09-01"}
    s.update(extra)
    return s


def _jail_inc(county="Cherokee", matched="CHRISTOPHER DAWKINS"):
    return {"state": "SC", "source": f"{county} County jail roster", "matched_name": matched,
            "confidence": "name_only_low"}


def _row(owner="DAWKINS CHRISTOPHER A", county="Cherokee", state="SC", stamp=None, inc=None,
         **kw):
    raw = {"owner_mailing": {"owner": owner},
           "jail_booking": stamp if stamp is not None else _stamp(county, state),
           "incarceration": inc if inc is not None else _jail_inc(county)}
    row = {"state": state, "county": county, "parcel_id": kw.pop("parcel_id", "1234567890"),
           "street_address": kw.pop("street_address", "12 PLACEHOLDER RD"), "raw": raw,
           "source": "counties_sc.placeholder"}
    row.update(kw)
    return row


def test_applies_only_to_the_pipelines_own_same_county_stamps_that_claim_custody():
    assert v.applies(_row())
    assert v.applies(_row(stamp=_stamp(confidence="middle_corroborated")))
    # the national.jail_bookings scraper's inmate-as-lead rows
    assert not v.applies(_row(stamp={"county": "Cherokee", "state": "SC",
                                     "vendor": "jail_bookings_scraper",
                                     "release_status": "in_custody"}))
    # a stamp for another county than the row's own
    assert not v.applies(_row(stamp=_stamp(county="Anderson")))
    # custody already ended on the board
    assert not v.applies(_row(stamp=_stamp(release_status=jb.LEFT_ROSTER_STATUS)))
    assert not v.applies(_row(stamp=_stamp(scheduled_release="2026-01-01")))
    # no stamp, the cross-county tier, another state
    r = _row()
    del r["raw"]["jail_booking"]
    assert not v.applies(r)
    r["raw"]["jail_booking_new"] = _stamp(confidence="middle_corroborated_cross_county")
    assert not v.applies(r)
    assert not v.applies(_row(state="GA"))


def test_registered_with_the_jail_only_governance():
    reg = {x.name: x for x in discover()}["jail_booking"]
    assert (reg.signal, reg.governs, reg.ttl_days, reg.retry_days) == (
        "jail_booking", ("incarceration:jail",), 3.0, 1.0)
    assert "incarceration" not in reg.governs        # never the bare name: prison flags stay


# --------------------------------------------------------------------------- #
# a Zuercher roster through the real fetcher, _load_roster and health judge    #
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, data):
        self._d = data
        self.text = ""

    def json(self):
        return self._d


class _Zuercher:
    """Serves the next roster on each Zuercher POST (None = the vendor times out) and counts
    the POSTs per subdomain."""

    def __init__(self, rosters):
        self.rosters = list(rosters)
        self.posts: Counter = Counter()

    def factory(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, timeout=None, **_):
        self.posts[url.split("//")[1].split(".")[0]] += 1
        recs = self.rosters.pop(0) if len(self.rosters) > 1 else self.rosters[0]
        if recs is None:
            raise TimeoutError("simulated vendor timeout")
        return _Resp({"records": recs})


def _zrec(name, charge="PLACEHOLDER CHARGE"):
    return {"name": name, "dob": None, "arrest_date": "2026-09-01T00:00:00.000Z",
            "hold_reasons": charge}


def _alpha(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _fillers(n):
    return [_zrec(f"Filler{_alpha(i)}, Person Middle") for i in range(n)]


def _install(monkeypatch, rosters):
    import curl_cffi.requests as ccr
    z = _Zuercher(rosters)
    monkeypatch.setattr(ccr, "AsyncSession", z.factory)
    return z


def _seed_history(state="SC", county="Cherokee", sizes=(100,)):
    con = jrh.connect(v.history_db())
    try:
        for i, n in enumerate(sizes):
            jrh.record_fetch(con, state, county, "zuercher", n,
                             now=datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(hours=i))
    finally:
        con.close()


class _Client:
    """The sweep's Fetcher stand-in: only the counters the verifier bumps."""

    def __init__(self):
        self.requests: Counter = Counter()
        self.errors: Counter = Counter()


def run(row, client):
    return asyncio.run(v.verify(row, client, today=TODAY))


def test_confirmed_when_the_inmate_middle_agrees(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Allen", "ASSAULT")] + _fillers(99)])
    res = run(_row(), _Client())
    assert res.verdict == "confirmed"
    ev = res.evidence
    assert ev["middle_verdict"] == "agrees" and ev["on_roster"] is True
    assert ev["inmate"] == {"first": "CHRISTOPHER", "middle": "ALLEN", "last": "DAWKINS",
                            "arrest_date": "2026-09-01T00:00:00.000Z", "charge": "ASSAULT"}
    assert ev["roster_size"] == 100 and ev["roster_healthy"] is True
    assert ev["roster_host"] == "cherokee-so-sc.zuercherportal.com" and ev["vendor"] == "zuercher"
    assert ev["fetched_at"].endswith("Z") and res.source == "cherokee-so-sc.zuercherportal.com"
    assert res.verifier == "jail_booking" and res.verifier_version == v.VERSION


def test_refuted_when_every_same_name_inmate_has_a_conflicting_middle(monkeypatch):
    """FINDINGS.md section 5's example: owner DAWKINS CHRISTOPHER A, inmate Christopher Keith."""
    _seed_history()
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Keith")] + _fillers(99)])
    res = run(_row(), _Client())
    assert res.verdict == "refuted"
    assert res.evidence["middle_verdict"] == "conflict"
    assert res.evidence["conflicting_middles"] == ["KEITH"]
    assert res.evidence["owner_middle_initial"] == "A"


def test_two_same_name_inmates_the_agreeing_one_confirms(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Keith"),
                            _zrec("Dawkins, Christopher Allen")] + _fillers(98)])
    res = run(_row(), _Client())
    assert res.verdict == "confirmed" and res.evidence["same_name_on_roster"] == 2
    assert res.evidence["inmate"]["middle"] == "ALLEN"


@pytest.mark.parametrize("roster_name, missing_on", [
    ("Dawkins, Christopher", "roster"),               # the vendor printed no middle
    ("Dawkins, Christopher NMN", "roster"),           # a placeholder is no middle
])
def test_on_the_roster_without_a_middle_to_compare_is_unconfirmed(monkeypatch, roster_name,
                                                                  missing_on):
    _seed_history()
    _install(monkeypatch, [[_zrec(roster_name)] + _fillers(99)])
    res = run(_row(), _Client())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "middle_unverifiable"
    assert res.evidence["on_roster"] is True and res.evidence["middle_missing_on"] == missing_on


def test_owner_without_a_middle_is_unconfirmed(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Keith")] + _fillers(99)])
    res = run(_row(owner="DAWKINS CHRISTOPHER"), _Client())
    assert res.verdict == "unconfirmed" and res.evidence["middle_missing_on"] == "owner"


def test_stale_when_absent_from_a_healthy_roster(monkeypatch):
    _seed_history(sizes=(100, 104, 98))
    _install(monkeypatch, [_fillers(101)])
    res = run(_row(), _Client())
    assert res.verdict == "stale"
    assert res.evidence["on_roster"] is False and res.evidence["roster_healthy"] is True
    assert res.evidence["roster_health_reason"] == "ok" and res.evidence["roster_baseline"] == 100


@pytest.mark.parametrize("today_roster, reason, health", [
    ([], "roster_unavailable", "empty_fetch"),            # vendor returned nothing
    (None, "roster_unavailable", "empty_fetch"),          # vendor timed out
    (_fillers(25), "roster_unhealthy", "implausibly_small"),   # 25 names vs a 100 history
    (_fillers(5), "roster_unhealthy", "below_floor"),
])
def test_never_stale_from_an_unhealthy_roster(monkeypatch, today_roster, reason, health):
    """THE safeguard: a failed, empty or truncated fetch is never read as 'released'."""
    _seed_history()
    _install(monkeypatch, [today_roster])
    res = run(_row(), _Client())
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == reason and res.evidence["roster_health_reason"] == health


def test_never_stale_without_history_and_the_fetch_is_recorded_for_next_time(monkeypatch):
    _install(monkeypatch, [_fillers(100)])
    first = run(_row(), _Client())
    assert first.verdict == "unconfirmed" and first.evidence["reason"] == "roster_unhealthy"
    assert first.evidence["roster_health_reason"] == "no_history"
    v._RUNS.clear()                                      # the next sweep run
    assert run(_row(), _Client()).verdict == "stale"


def test_owner_no_longer_the_matched_person_is_never_decisive(monkeypatch):
    """On the 2026-10-06 board, 91 Anderson court-case rows share one city-owned parcel: the
    roster answers for the matched person, not for the property's owner."""
    _seed_history()
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Allen")] + _fillers(99)])
    on = run(_row(owner="CHEROKEE COUNTY"), _Client())
    assert on.verdict == "unconfirmed" and on.evidence["reason"] == "owner_no_longer_matches"
    assert on.evidence["on_roster"] is True and "inmate" not in on.evidence
    v._RUNS.clear()
    _install(monkeypatch, [_fillers(100)])
    off = run(_row(owner="SMITH JOHN Q"), _Client())     # absent from a HEALTHY roster
    assert off.verdict == "unconfirmed" and off.evidence["on_roster"] is False


def test_counties_without_a_bulk_roster_are_unconfirmed_without_a_fetch(monkeypatch):
    z = _install(monkeypatch, [_fillers(100)])
    gvl = _row(owner="WATERS JIMMY S", county="Greenville",
               stamp=_stamp(county="Greenville", matched="JIMMY WATERS"))
    res = run(gvl, _Client())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "per_name_search_vendor"
    assert res.evidence["vendor"] == "lansa"
    other = _row(owner="DOE JANE Q", county="Pickens",
                 stamp=_stamp(county="Pickens", matched="JANE DOE"))
    assert run(other, _Client()).evidence["reason"] == "no_roster_for_county"
    assert sum(z.posts.values()) == 0


# --------------------------------------------------------------------------- #
# one fetch per county per sweep run; the verifier's own history file          #
# --------------------------------------------------------------------------- #

def test_one_roster_fetch_per_county_per_run(monkeypatch):
    _seed_history()
    z = _install(monkeypatch, [[_zrec("Dawkins, Christopher Allen")] + _fillers(99)])
    client = _Client()
    rows = [_row(), _row(owner="FILLERA PERSON M", stamp=_stamp(matched="PERSON FILLERA")),
            _row(owner="NOBODY SOME X", stamp=_stamp(matched="SOME NOBODY"))]

    async def sweep():
        out = [await v.verify(r, client) for r in rows]
        # concurrent callers share the in-flight load too
        out += await asyncio.gather(*(v.verify(r, client) for r in rows))
        return out

    verdicts = [r.verdict for r in asyncio.run(sweep())]
    assert verdicts == ["confirmed", "confirmed", "stale"] * 2
    assert z.posts == Counter({"cherokee-so-sc": 1})
    assert client.requests == Counter({"roster:cherokee-so-sc.zuercherportal.com": 1})
    # a new sweep run (a new client) fetches again
    asyncio.run(v.verify(rows[0], _Client()))
    assert z.posts == Counter({"cherokee-so-sc": 2})


def test_a_failed_roster_is_counted_as_an_error_and_not_refetched_per_row(monkeypatch):
    _seed_history()
    z = _install(monkeypatch, [None])
    client = _Client()

    async def sweep():
        return [await v.verify(_row(), client) for _ in range(3)]

    assert {r.evidence["reason"] for r in asyncio.run(sweep())} == {"roster_unavailable"}
    assert z.posts == Counter({"cherokee-so-sc": 1})
    assert client.errors == Counter({"roster:cherokee-so-sc.zuercherportal.com": 1})


def test_the_pipeline_sidecar_is_never_written(monkeypatch):
    _install(monkeypatch, [_fillers(100)])
    run(_row(), _Client())
    con = jrh.connect()                                  # the pipeline's (conftest temp) file
    try:
        assert jrh.recent_roster_sizes(con, "SC", "Cherokee") == []
        assert jrh.listed_count(con, "SC", "Cherokee") == 0
    finally:
        con.close()
    con = jrh.connect(v.history_db())
    try:
        assert jrh.recent_roster_sizes(con, "SC", "Cherokee") == [100]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# parity with the run's own re-evaluation                                     #
# --------------------------------------------------------------------------- #

_REEVAL_TO_VERDICT = {"conflict_cleared": {"refuted"}, "left_roster": {"stale"},
                      "absent_unchecked": {"unconfirmed"},
                      "confirmed": {"confirmed", "unconfirmed"}}


@pytest.mark.parametrize("roster, healthy", [
    ([_zrec("Dawkins, Christopher Allen")] + _fillers(99), True),
    ([_zrec("Dawkins, Christopher Keith")] + _fillers(99), True),
    ([_zrec("Dawkins, Christopher")] + _fillers(99), True),
    (_fillers(100), True),
    (_fillers(100), False),
])
def test_verdict_agrees_with_reevaluate_stamp_on_the_same_roster(monkeypatch, roster, healthy):
    if healthy:
        _seed_history()
    _install(monkeypatch, [roster])
    row = _row()
    client = _Client()                    # held: the per-run cache is keyed weakly by it
    res = run(row, client)
    idx = v._RUNS[client][("SC", "Cherokee")].index
    li = Listing(source="t", source_url="http://x", state="SC", county="Cherokee",
                 raw=copy.deepcopy(row["raw"]))
    outcome = jb._reevaluate_stamp(li, idx, jb._name_parts(jb._owner_of(li)),
                                   roster_complete=bool(idx.healthy), today=TODAY)
    assert res.verdict in _REEVAL_TO_VERDICT[outcome]
    if outcome == "confirmed":     # the run keeps both; the verifier decides only on 'agrees'
        assert (res.verdict == "confirmed") == (li.raw["jail_booking"]["middle_verdict"] == "agrees")


# --------------------------------------------------------------------------- #
# scoring: jail-sourced flags only                                            #
# --------------------------------------------------------------------------- #

def _vrec(verdict, *, expires_in_days=2):
    checked = datetime(2026, 10, 6, 3, tzinfo=timezone.utc)
    return {"signal": "jail_booking", "verdict": verdict, "evidence": {},
            "source": "cherokee-so-sc.zuercherportal.com", "checked_at": core.iso_z(checked),
            "verifier_version": "v1", "verifier": "jail_booking",
            "expires_at": core.iso_z(checked + timedelta(days=expires_in_days)),
            "governs": list(v.GOVERNS)}


def _listing(inc_source="Cherokee County jail roster", verification=None, jail=True,
             parcel="1234567890", address="12 PLACEHOLDER RD"):
    raw = {"owner_mailing": {"owner": "DAWKINS CHRISTOPHER A"}}
    if jail:
        raw["jail_booking"] = _stamp()
    if inc_source is not None:
        raw["incarceration"] = {"state": "SC", "source": inc_source,
                                "matched_name": "CHRISTOPHER DAWKINS"}
    elif jail:
        raw["incarceration"] = {"state": "SC", "matched_name": "CHRISTOPHER DAWKINS"}  # legacy
    if verification is not None:
        raw["verification"] = verification
    return Listing(source="counties_sc.placeholder", source_url="http://x", state="SC",
                   county="Cherokee", parcel_id=parcel, street_address=address, raw=raw)


def _scored(li):
    return {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
@pytest.mark.parametrize("src", ["Cherokee County jail roster", None])
def test_refuted_or_stale_ends_a_jail_sourced_flag(verdict, src):
    li = _listing(src, [_vrec(verdict)])
    assert "incarceration" in _scored(_listing(src))
    assert "incarceration" not in _scored(li)
    assert "incarceration" not in _facet_signals(li, TODAY)


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
@pytest.mark.parametrize("src", [DAC, SCDC, BOP])
def test_a_prison_sourced_flag_is_never_touched(verdict, src):
    """The jail -> prison move: the county roster says gone (stale), the state lane found him."""
    li = _listing(src, [_vrec(verdict)])
    assert "incarceration" in _scored(li)
    assert "incarceration" in _facet_signals(li, TODAY)
    assert _scored(li) == _scored(_listing(src))


@pytest.mark.parametrize("verdict, expires", [("confirmed", 2), ("unconfirmed", 2),
                                              ("stale", -1), ("refuted", -1)])
def test_confirmed_unconfirmed_or_expired_change_nothing(verdict, expires):
    li = _listing(verification=[_vrec(verdict, expires_in_days=expires)])
    assert _scored(li) == _scored(_listing())
    assert "incarceration" in _facet_signals(li, TODAY)


def test_badge_and_suppressed_names():
    li = _listing(verification=[_vrec("stale")])
    assert core.verdict_badges(li.raw, datetime(2026, 10, 6, 12, tzinfo=timezone.utc)) == {
        "jail_booking": "stale"}
    assert core.suppressed_scorer_signals(li.raw, TODAY) == {"incarceration:jail"}


def test_apply_then_score_end_to_end(tmp_path):
    """Ledger -> apply_verification -> _signals_for: a stale jail verdict ends the jail flag;
    the same verdict on a row whose flag is now prison-sourced leaves it scored."""
    led = Ledger("jail_booking", path=tmp_path / "jail_booking.json")
    jail_row = _listing()
    prison_row = _listing(DAC, parcel="2222222222", address="34 PLACEHOLDER RD")
    control = _listing(parcel="3333333333", address="56 PLACEHOLDER RD")
    stale = core.result("jail_booking", "stale", {"on_roster": False}, source="x",
                        version="v1", verifier="jail_booking",
                        now=datetime(2026, 10, 6, 3, tzinfo=timezone.utc))
    for li in (jail_row, prison_row):
        led.record(li, stale, ttl_days=v.TTL_DAYS, governs=v.GOVERNS)
    led.save()
    counts = apply_verification([jail_row, prison_row, control], directory=tmp_path,
                                now=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    assert counts["records"] == 2 and counts["suppressing"] == 2
    assert "incarceration" not in _scored(jail_row)
    assert "incarceration" in _scored(prison_row)
    assert "verification" not in control.raw and "incarceration" in _scored(control)


# --------------------------------------------------------------------------- #
# REAL responses: the 2026-10-06 live sweep's own roster bodies                #
# --------------------------------------------------------------------------- #
# tests/fixtures/verification/jail_roster_<county>.json.gz: every request the real vendor
# fetchers made for that county during the sweep (Buncombe = P2C CentralSquare: the XSRF app
# GET + three 200-row pages; Cherokee = Zuercher; Lincoln = P2C jqGrid), as served, with every
# person-name token pseudonymized consistently (first letter kept, so each middle-name
# agree/conflict is what it was live; suffixes, placeholders and entity words untouched) and
# DOB / mugshots / image ids / warrant and docket numbers / marks / addresses removed.
# jail_booking_cases.json: the 34 sweep rows of those counties (owner and matched names through
# the same pseudonym map) with the verdict the live sweep gave each.

import gzip  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "verification"
CASES = json.loads((FIX / "jail_booking_cases.json").read_text())
# the warm-up fetch sizes recorded in the verifier's history 6 minutes before the sweep
# (Cherokee's warm-up timed out, so the sweep judged it with no history, as here)
WARMUP = {("NC", "Buncombe"): 509, ("NC", "Lincoln"): 154}


def _recorded(county):
    return json.loads(gzip.decompress((FIX / f"jail_roster_{county.lower()}.json.gz").read_bytes()))


class _RecordedResp:
    def __init__(self, rec):
        self.status_code = rec["status"]
        self.text = rec["text"]

    def json(self):
        return json.loads(self.text)


class _Recorded:
    """curl_cffi.AsyncSession stand-in that replays the captured requests per host, in order,
    and fails loudly on any request the real fetcher did not make live."""

    def __init__(self, counties, *, truncate_after=None):
        self.queues: dict[str, list] = {}
        for co in counties:
            recs = _recorded(co)
            if truncate_after is not None and co in truncate_after:
                n = truncate_after[co]
                empty = dict(recs[n], text=json.dumps({"Inmates": [], "Total": 0}))
                recs = recs[:n] + [empty]
            for rec in recs:
                self.queues.setdefault(rec["url"].split("/")[2], []).append(rec)
        self.served: Counter = Counter()

    def factory(self, *a, **k):
        outer = self

        class _S:
            def __init__(self):
                self.cookies: dict = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def _next(self, method, url):
                host = url.split("/")[2]
                rec = outer.queues[host].pop(0)
                assert (rec["method"], rec["url"]) == (method, url)
                self.cookies.update(rec["cookies"])
                outer.served[host] += 1
                return _RecordedResp(rec)

            async def get(self, url, **_):
                return self._next("GET", url)

            async def post(self, url, **_):
                return self._next("POST", url)

        return _S()


def _install_recorded(monkeypatch, counties, **kw):
    import curl_cffi.requests as ccr
    rec = _Recorded(counties, **kw)
    monkeypatch.setattr(ccr, "AsyncSession", rec.factory)
    return rec


def _seed_warmup():
    con = jrh.connect(v.history_db())
    try:
        for (st, co), n in WARMUP.items():
            jrh.record_fetch(con, st, co, "warmup", n,
                             now=datetime(2026, 10, 6, 4, 43, tzinfo=timezone.utc))
    finally:
        con.close()


def test_the_real_cases_cover_every_verdict():
    assert Counter(c["expect"]["verdict"] for c in CASES) == Counter(
        {"confirmed": 18, "refuted": 7, "unconfirmed": 7, "stale": 2})
    for c in CASES:
        assert v.applies(c["row"]), c["name"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_real_roster_reproduces_the_live_verdict(monkeypatch, case):
    _seed_warmup()
    _install_recorded(monkeypatch, [case["row"]["county"]])
    res = run(case["row"], _Client())
    exp = case["expect"]
    assert (res.verdict, res.evidence.get("reason"), res.evidence.get("middle_verdict"),
            res.evidence.get("on_roster")) == (exp["verdict"], exp["reason"],
                                               exp["middle_verdict"], exp["on_roster"])
    if exp["verdict"] in ("confirmed", "refuted"):
        assert res.evidence["inmate"]["last"] and res.evidence["inmate"]["first"]
        assert "dob" not in res.evidence["inmate"]


def test_real_rosters_one_load_per_county_for_every_case(monkeypatch):
    _seed_warmup()
    rec = _install_recorded(monkeypatch, ["Buncombe", "Cherokee", "Lincoln"])
    client = _Client()

    async def sweep():
        return [await v.verify(c["row"], client) for c in CASES]

    got = [r.verdict for r in asyncio.run(sweep())]
    assert got == [c["expect"]["verdict"] for c in CASES]
    # exactly the live sweep's requests: P2C's app GET + 3 pages, one Zuercher POST,
    # jqGrid's session GET + one POST; nothing per row
    assert rec.served == Counter({"buncombecountyso.policetocitizen.com": 4,
                                  "cherokee-so-sc.zuercherportal.com": 1,
                                  "p2c.lincolnsheriff.org": 2})
    assert all(not q for q in rec.queues.values())
    sizes = {k[1]: r.size for k, r in v._RUNS[client].items()}
    assert sizes == {"Buncombe": 509, "Cherokee": 288, "Lincoln": 154}


def test_real_buncombe_roster_cut_after_one_page_is_never_stale(monkeypatch):
    """The same live roster, cut to its first 200-row page (a vendor hiccup mid-paging): 199
    names against a 509 history is implausibly small, so the two people the full roster shows
    gone come out unconfirmed, never stale; presence still decides the others."""
    _seed_warmup()
    _install_recorded(monkeypatch, ["Buncombe"], truncate_after={"Buncombe": 2})
    client = _Client()
    bun = [c for c in CASES if c["row"]["county"] == "Buncombe"]

    async def sweep():
        return [await v.verify(c["row"], client) for c in bun]

    res = asyncio.run(sweep())
    roster = v._RUNS[client][("NC", "Buncombe")]
    # 199: the page holds 200 records, one without a name (the full roster: Total 510, 509 named)
    assert roster.size == 199 and roster.health["reason"] == "implausibly_small"
    assert "stale" not in {r.verdict for r in res}
    for c, r in zip(bun, res):
        if c["expect"]["verdict"] == "stale":
            assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "roster_unhealthy")


def test_real_roster_with_no_history_is_never_stale(monkeypatch):
    """The machine's first sweep: the same full Buncombe roster, no recorded history."""
    _install_recorded(monkeypatch, ["Buncombe"])
    stale = [c for c in CASES if c["expect"]["verdict"] == "stale"]
    res = run(stale[0]["row"], _Client())
    assert (res.verdict, res.evidence["reason"], res.evidence["roster_health_reason"]) == (
        "unconfirmed", "roster_unhealthy", "no_history")
