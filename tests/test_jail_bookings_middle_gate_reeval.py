"""Same-county middle-name gate + per-run re-evaluation (2026-10-05).

The 2026-10-02 full-population live check (docs/validation_2026-10-02/FINDINGS.md
section 5) of all 322 board rows carrying raw['jail_booking'] found 19 of 147
middle-checkable current matches were a CONFIRMED different person (owner
"DAWKINS CHRISTOPHER A" vs inmate "Christopher Keith Dawkins") and 47 rows still
said in_custody for someone gone from the roster. What these pin:

  * a middle-name CONFLICT is never stamped; AGREES upgrades confidence to
    "middle_corroborated"; UNVERIFIED (no middle on one side) is still stamped
    "name_only_low" exactly as before
  * an existing stamp that now conflicts is cleared, along with its own
    county-jail incarceration flag -- never an NC-DAC / SC-DOC / BOP one
  * a stamped person missing from a HEALTHY roster is marked
    released_or_transferred (custody_ended() -> True, scorer drops it) and the
    record is kept; back on the roster later -> restored
  * a failed, empty, implausibly small or history-less roster NEVER marks
    anyone released (the critical safeguard), end-to-end through the real
    _load_roster + jail_roster_history sidecar
  * the per-name search lane re-checks presence but never applies absence
  * the national.jail_bookings scraper's own rows are never re-evaluated

Network is faked throughout; the sidecar is the per-test temp DB conftest sets
up. Names are placeholders except the two shapes quoted from FINDINGS.md.
"""
from __future__ import annotations

from datetime import date

import pytest

from foreclosure_scraper import enrichment_jail_bookings as jb
from foreclosure_scraper import jail_roster_history as jrh
from foreclosure_scraper.distress_score import _signals_for
from foreclosure_scraper.enrichment_jail_bookings import (
    LEFT_ROSTER_STATUS,
    RosterIndex,
    _hit_middle_verdict,
    _pick_hit,
    enrich_jail_bookings,
    match_rosters,
)
from foreclosure_scraper.models import Listing
from foreclosure_scraper.scrapers.national.jail_bookings import (
    _comma_middle,
    _parse_citizen_connect_cards,
    _parse_tyler_rows,
    _space_middle,
)
from foreclosure_scraper.signal_freshness import custody_ended

DAC_SOURCE = "NC DAC offender search"
SCDC_SOURCE = "SC DOC inmate search"
BOP_SOURCE = "BOP inmate locator"
D1 = date(2026, 10, 5)
D2 = date(2026, 10, 12)


def _li(owner, state="SC", county="Cherokee", raw_extra=None):
    raw = {"owner_mailing": {"owner": owner}}
    raw.update(raw_extra or {})
    return Listing(source="test", source_url="http://x", state=state,
                   county=f"{county} County", raw=raw)


def _hit(last, first, middle="", **extra):
    return {"last": last, "first": first, "middle": middle,
            "arrest_date": "2026-09-01", "charge": "PLACEHOLDER", **extra}


def _index(*recs, healthy=False):
    idx = RosterIndex()
    for r in recs:
        idx.add(r)
    idx.healthy = healthy
    return idx


def _own_stamp(county="Cherokee", matched="CHRISTOPHER DAWKINS", **extra):
    stamp = {"county": county, "state": "SC", "matched_name": matched,
             "release_status": "in_custody", "scheduled_release": None,
             "confidence": "name_only_low", "facility_type": "jail",
             "arrest_date": "2024-10-01"}
    stamp.update(extra)
    return stamp


def _jail_inc(county="Cherokee", matched="CHRISTOPHER DAWKINS"):
    return {"state": "SC", "source": f"{county} County jail roster",
            "matched_name": matched, "confidence": "name_only_low"}


def _alpha(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# --------------------------------------------------------------------------- #
# the verdict itself                                                          #
# --------------------------------------------------------------------------- #

def test_verdict_matches_the_findings_example_shape():
    assert _hit_middle_verdict("DAWKINS CHRISTOPHER A",
                               _hit("DAWKINS", "CHRISTOPHER", "KEITH")) == "conflict"
    assert _hit_middle_verdict("DAWKINS CHRISTOPHER A",
                               _hit("DAWKINS", "CHRISTOPHER", "ALLEN")) == "agrees"
    assert _hit_middle_verdict("DAWKINS CHRISTOPHER A",
                               _hit("DAWKINS", "CHRISTOPHER")) == "unverified"
    assert _hit_middle_verdict("DAWKINS CHRISTOPHER",
                               _hit("DAWKINS", "CHRISTOPHER", "KEITH")) == "unverified"
    # Title-case FIRST MIDDLE LAST owner (court/probate convention)
    assert _hit_middle_verdict("Richard H Russell",
                               _hit("RUSSELL", "RICHARD", "EARL")) == "conflict"


@pytest.mark.parametrize("middle", ["NMN", "NMI", "N/A", "JR", "  ", None])
def test_placeholder_or_suffix_middle_is_unverified_not_a_conflict(middle):
    assert _hit_middle_verdict("TESTCASE ALPHA B", _hit("TESTCASE", "ALPHA", middle)) == "unverified"


def test_owner_co_owner_noise_is_not_read_as_a_middle_initial():
    # ALL-CAPS GIS reads the 3rd token as the middle initial; "ETAL" is not one.
    assert _hit_middle_verdict("TESTCASE ALPHA ETAL",
                               _hit("TESTCASE", "ALPHA", "ROBERT")) == "unverified"
    assert _hit_middle_verdict("TESTCASE ALPHA ET AL",
                               _hit("TESTCASE", "ALPHA", "ROBERT")) == "unverified"


def test_hyphenated_roster_surname_still_compares_positionally():
    assert _hit_middle_verdict("SMITH-JONES, MARY A",
                               _hit("SMITH-JONES", "MARY", "BETH")) == "conflict"
    assert _hit_middle_verdict("SMITH-JONES, MARY A",
                               _hit("SMITH-JONES", "MARY", "ANN")) == "agrees"


def test_pick_hit_prefers_the_same_name_record_whose_middle_agrees():
    wrong = _hit("DAWKINS", "CHRISTOPHER", "KEITH", arrest_date="2026-09-28")
    right = _hit("DAWKINS", "CHRISTOPHER", "ALLEN", arrest_date="2026-09-10")
    hit, verdict = _pick_hit("DAWKINS CHRISTOPHER A", [wrong, right])
    assert verdict == "agrees" and hit is right
    hit, verdict = _pick_hit("DAWKINS CHRISTOPHER A", [wrong, _hit("DAWKINS", "CHRISTOPHER")])
    assert verdict == "unverified" and hit["middle"] == ""
    hit, verdict = _pick_hit("DAWKINS CHRISTOPHER A", [wrong])
    assert verdict == "conflict"


# --------------------------------------------------------------------------- #
# new matches: the gate                                                       #
# --------------------------------------------------------------------------- #

def test_conflict_is_never_stamped_and_is_counted():
    li = _li("DAWKINS CHRISTOPHER A")
    stats: dict = {}
    flagged = match_rosters([li], {("SC", "Cherokee"): _index(_hit("DAWKINS", "CHRISTOPHER", "KEITH"))},
                            today=D1, stats=stats)
    assert flagged == []
    assert "jail_booking" not in li.raw and "incarceration" not in li.raw
    assert stats["middle_conflict_rejected"] == 1


def test_agrees_is_stamped_middle_corroborated():
    li = _li("DAWKINS CHRISTOPHER A")
    stats: dict = {}
    flagged = match_rosters([li], {("SC", "Cherokee"): _index(_hit("DAWKINS", "CHRISTOPHER", "ALLEN"))},
                            today=D1, stats=stats)
    assert flagged == [li]
    jbk = li.raw["jail_booking"]
    assert jbk["confidence"] == "middle_corroborated"
    assert jbk["middle_verdict"] == "agrees"
    assert jbk["last_confirmed_on_roster"] == "2026-10-05"
    assert li.raw["incarceration"]["confidence"] == "middle_corroborated"
    assert stats["middle_corroborated"] == 1


def test_unverified_is_kept_as_name_only_low():
    """P2C-style row with no middle, and an owner with no middle: both stay
    stamped exactly as before -- the county is the second corroborating channel."""
    no_mid_roster = _li("DAWKINS CHRISTOPHER A")
    no_mid_owner = _li("TESTCASE ALPHA")
    idx = _index(_hit("DAWKINS", "CHRISTOPHER"), _hit("TESTCASE", "ALPHA", "BETA"))
    flagged = match_rosters([no_mid_roster, no_mid_owner], {("SC", "Cherokee"): idx}, today=D1)
    assert flagged == [no_mid_roster, no_mid_owner]
    for li in flagged:
        assert li.raw["jail_booking"]["confidence"] == "name_only_low"
        assert li.raw["jail_booking"]["middle_verdict"] == "unverified"
        assert li.raw["incarceration"]["source"] == "Cherokee County jail roster"


def test_two_same_name_inmates_the_agreeing_one_is_stamped():
    li = _li("DAWKINS CHRISTOPHER A")
    idx = _index(_hit("DAWKINS", "CHRISTOPHER", "KEITH", arrest_date="2026-09-28"),
                 _hit("DAWKINS", "CHRISTOPHER", "ALLEN", arrest_date="2026-09-10"))
    match_rosters([li], {("SC", "Cherokee"): idx}, today=D1)
    assert li.raw["jail_booking"]["arrest_date"] == "2026-09-10"
    assert li.raw["jail_booking"]["middle_verdict"] == "agrees"


# --------------------------------------------------------------------------- #
# existing stamps: re-evaluation                                              #
# --------------------------------------------------------------------------- #

def test_existing_conflict_is_cleared_with_its_own_jail_incarceration_flag():
    li = _li("DAWKINS CHRISTOPHER A",
             raw_extra={"jail_booking": _own_stamp(), "incarceration": _jail_inc()})
    stats: dict = {}
    flagged = match_rosters([li], {("SC", "Cherokee"): _index(_hit("DAWKINS", "CHRISTOPHER", "KEITH"))},
                            today=D1, stats=stats)
    assert flagged == []                          # cleared, and NOT re-stamped in the same pass
    assert "jail_booking" not in li.raw and "incarceration" not in li.raw
    assert stats["reeval_conflict_cleared"] == 1


@pytest.mark.parametrize("source", [DAC_SOURCE, SCDC_SOURCE, BOP_SOURCE])
def test_existing_conflict_clear_never_touches_a_non_jail_incarceration_source(source):
    other = {"state": "SC", "source": source, "matched_name": "CHRISTOPHER DAWKINS"}
    li = _li("DAWKINS CHRISTOPHER A",
             raw_extra={"jail_booking": _own_stamp(), "incarceration": dict(other)})
    match_rosters([li], {("SC", "Cherokee"): _index(_hit("DAWKINS", "CHRISTOPHER", "KEITH"))}, today=D1)
    assert "jail_booking" not in li.raw
    assert li.raw["incarceration"] == other


def test_existing_stamp_still_on_roster_is_refreshed_and_upgraded():
    li = _li("DAWKINS CHRISTOPHER A",
             raw_extra={"jail_booking": _own_stamp(), "incarceration": _jail_inc()})
    stats: dict = {}
    hit = _hit("DAWKINS", "CHRISTOPHER", "ALLEN", arrest_date="2026-10-01",
               release_status="scheduled_release 10/20/2026", scheduled_release="10/20/2026")
    match_rosters([li], {("SC", "Cherokee"): _index(hit)}, today=D1, stats=stats)
    jbk = li.raw["jail_booking"]
    assert jbk["middle_verdict"] == "agrees" and jbk["confidence"] == "middle_corroborated"
    assert jbk["release_status"] == "scheduled_release 10/20/2026"
    assert jbk["scheduled_release"] == "10/20/2026"
    assert jbk["arrest_date"] == "2026-10-01"
    assert jbk["last_confirmed_on_roster"] == "2026-10-05"
    assert li.raw["incarceration"]["confidence"] == "middle_corroborated"
    assert stats["reeval_confirmed"] == 1


def test_left_a_healthy_roster_is_marked_ended_and_kept_for_history():
    li = _li("DAWKINS CHRISTOPHER A",
             raw_extra={"jail_booking": _own_stamp(), "incarceration": _jail_inc()})
    stats: dict = {}
    idx = _index(_hit("SOMEONE", "ELSE"), healthy=True)
    match_rosters([li], {("SC", "Cherokee"): idx}, today=D1, stats=stats)
    jbk = li.raw["jail_booking"]
    assert jbk["release_status"] == LEFT_ROSTER_STATUS == "released_or_transferred"
    assert jbk["left_roster_detected_at"] == "2026-10-05"
    assert jbk["matched_name"] == "CHRISTOPHER DAWKINS"     # history kept
    assert custody_ended(jbk, D1) is True
    assert li.raw["incarceration"]["source"] == "Cherokee County jail roster"   # untouched
    assert stats["reeval_left_roster"] == 1
    # the scorer now drops the LEGAL incarceration signal
    assert "incarceration" not in [n for n, _c, _w in _signals_for(li, today=D1)]

    # a later healthy roster still without them: date of first detection is kept
    stats2: dict = {}
    match_rosters([li], {("SC", "Cherokee"): idx}, today=D2, stats=stats2)
    assert li.raw["jail_booking"]["left_roster_detected_at"] == "2026-10-05"
    assert stats2 == {"reeval_already_ended": 1}


def test_back_on_the_roster_after_being_marked_ended_is_restored():
    li = _li("DAWKINS CHRISTOPHER A", raw_extra={
        "jail_booking": _own_stamp(release_status=LEFT_ROSTER_STATUS,
                                   left_roster_detected_at="2026-09-01"),
        "incarceration": _jail_inc()})
    match_rosters([li], {("SC", "Cherokee"): _index(_hit("DAWKINS", "CHRISTOPHER", "ALLEN"))}, today=D1)
    jbk = li.raw["jail_booking"]
    assert jbk["release_status"] == "in_custody"
    assert "left_roster_detected_at" not in jbk
    assert custody_ended(jbk, D1) is False
    assert "incarceration" in [n for n, _c, _w in _signals_for(li, today=D1)]


@pytest.mark.parametrize("roster", [
    "plain_dict",          # older caller / no health info at all
    "unhealthy_index",     # RosterIndex judged not healthy by the sidecar
])
def test_unhealthy_roster_never_marks_anyone_released(roster):
    li = _li("DAWKINS CHRISTOPHER A",
             raw_extra={"jail_booking": _own_stamp(), "incarceration": _jail_inc()})
    before = dict(li.raw["jail_booking"])
    other = _hit("SOMEONE", "ELSE")
    idx = ({jb._norm_key("SOMEONE", "ELSE"): other} if roster == "plain_dict"
           else _index(other, healthy=False))
    stats: dict = {}
    match_rosters([li], {("SC", "Cherokee"): idx}, today=D1, stats=stats)
    assert li.raw["jail_booking"] == before
    assert custody_ended(li.raw["jail_booking"], D1) is False
    assert stats == {"reeval_absent_roster_unhealthy": 1}


def test_empty_roster_is_skipped_entirely():
    li = _li("DAWKINS CHRISTOPHER A", raw_extra={"jail_booking": _own_stamp()})
    before = dict(li.raw["jail_booking"])
    stats: dict = {}
    match_rosters([li], {("SC", "Cherokee"): _index(healthy=True)}, today=D1, stats=stats)
    assert li.raw["jail_booking"] == before and stats == {}


def test_national_scraper_rows_and_other_counties_are_never_reevaluated():
    national = _li("ABSENT INMATE", raw_extra={"jail_booking": {
        "county": "Cherokee", "state": "SC", "inmate_name": "ABSENT, INMATE",
        "release_status": "in_custody", "vendor": "jail_bookings_scraper"}})
    foreign = _li("DAWKINS CHRISTOPHER A",
                  raw_extra={"jail_booking": _own_stamp(county="Anderson")})
    before = [dict(national.raw["jail_booking"]), dict(foreign.raw["jail_booking"])]
    idx = _index(_hit("SOMEONE", "ELSE"), healthy=True)
    match_rosters([national, foreign], {("SC", "Cherokee"): idx}, today=D1)
    assert [national.raw["jail_booking"], foreign.raw["jail_booking"]] == before


# --------------------------------------------------------------------------- #
# end to end: the real _load_roster + sidecar health judgement                #
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _ZuercherSequence:
    """Serves the next roster in `rosters` on each Zuercher POST; a None entry
    raises (a failed fetch)."""

    def __init__(self, rosters):
        self.rosters = list(rosters)

    def factory(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, timeout=None):
        recs = self.rosters.pop(0)
        if recs is None:
            raise TimeoutError("simulated vendor timeout")
        return _Resp({"records": recs})


def _zrec(name):
    return {"name": name, "dob": None, "arrest_date": "2026-09-01T00:00:00.000Z",
            "hold_reasons": "PLACEHOLDER"}


def _fillers(n):
    return [_zrec(f"Filler{_alpha(i)}, Person") for i in range(n)]


def _install(monkeypatch, rosters):
    import curl_cffi.requests as ccr
    seq = _ZuercherSequence(rosters)
    monkeypatch.setattr(ccr, "AsyncSession", seq.factory)
    return seq


def _stamped_listing():
    return _li("DAWKINS CHRISTOPHER A",
               raw_extra={"jail_booking": _own_stamp(), "incarceration": _jail_inc()})


@pytest.mark.asyncio
async def test_e2e_healthy_history_then_absent_marks_ended(monkeypatch):
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Allen")] + _fillers(99),
                           _fillers(100)])
    li = _stamped_listing()
    r1 = await enrich_jail_bookings([li], today=D1)
    # first run: cold sidecar -> not trusted for absence, but he is present anyway
    assert r1["reeval_confirmed"] == 1 and r1["rosters_unhealthy"] == ["Cherokee"]
    r2 = await enrich_jail_bookings([li], today=D2)
    assert r2["rosters_unhealthy"] == []
    assert r2["reeval_left_roster"] == 1
    assert li.raw["jail_booking"]["release_status"] == LEFT_ROSTER_STATUS
    assert li.raw["jail_booking"]["left_roster_detected_at"] == "2026-10-12"


@pytest.mark.asyncio
@pytest.mark.parametrize("second_fetch, reason", [
    ("empty", "empty_fetch"),            # vendor returned nothing
    ("raises", "empty_fetch"),           # vendor call raised -> fetcher returns []
    ("small", "implausibly_small"),      # 25 names vs a 100-name history
    ("tiny", "below_floor"),             # 5 names
])
async def test_e2e_unhealthy_roster_does_not_mark_anyone_released(monkeypatch, second_fetch, reason):
    """THE critical safeguard: a failed, empty or truncated fetch must never
    read as "everyone missing was released"."""
    second = {"empty": [], "raises": None,
              "small": _fillers(25), "tiny": _fillers(5)}[second_fetch]
    _install(monkeypatch, [[_zrec("Dawkins, Christopher Allen")] + _fillers(99), second])
    li = _stamped_listing()
    await enrich_jail_bookings([li], today=D1)
    before = dict(li.raw["jail_booking"])
    res = await enrich_jail_bookings([li], today=D2)
    assert li.raw["jail_booking"] == before
    assert custody_ended(li.raw["jail_booking"], D2) is False
    assert res.get("reeval_left_roster", 0) == 0
    if second_fetch in ("small", "tiny"):
        assert res["rosters_unhealthy"] == ["Cherokee"]
        assert res["reeval_absent_roster_unhealthy"] == 1
        assert jrh.judge_roster_size(len(second), 100.0) == (False, reason)
    else:
        assert jrh.judge_roster_size(0, 100.0) == (False, reason)


@pytest.mark.asyncio
async def test_e2e_cold_sidecar_never_marks_released_on_its_first_fetch(monkeypatch):
    _install(monkeypatch, [_fillers(100), _fillers(100)])
    li = _stamped_listing()
    r1 = await enrich_jail_bookings([li], today=D1)
    assert r1["reeval_absent_roster_unhealthy"] == 1
    assert custody_ended(li.raw["jail_booking"], D1) is False
    # the size was recorded, so the next full fetch can be trusted
    r2 = await enrich_jail_bookings([li], today=D2)
    assert r2["reeval_left_roster"] == 1


@pytest.mark.asyncio
async def test_e2e_dry_run_records_no_roster_size(monkeypatch):
    _install(monkeypatch, [_fillers(100), _fillers(100)])
    li = _stamped_listing()
    await enrich_jail_bookings([li], today=D1, dry_run=True)
    con = jrh.connect()
    try:
        assert jrh.recent_roster_sizes(con, "SC", "Cherokee") == []
    finally:
        con.close()
    r2 = await enrich_jail_bookings([li], today=D2)       # still no trusted history
    assert r2["reeval_absent_roster_unhealthy"] == 1


# --------------------------------------------------------------------------- #
# per-name search lane (Greenville LANSA)                                     #
# --------------------------------------------------------------------------- #

def _gvl_listing():
    return _li("WATERS JIMMY S", county="Greenville", raw_extra={
        "jail_booking": _own_stamp(county="Greenville", matched="JIMMY WATERS"),
        "incarceration": _jail_inc(county="Greenville", matched="JIMMY WATERS")})


@pytest.mark.asyncio
async def test_search_lane_clears_an_existing_conflict(monkeypatch):
    async def fake_search(vendor, target, last, first):
        return [_hit("WATERS", "JIMMY", "ALLEN"), _hit("WATERS", "RICHARD", "MARION")]
    monkeypatch.setattr(jb, "_search_vendor", fake_search)
    li = _gvl_listing()
    res = await enrich_jail_bookings([li], today=D1)
    assert "jail_booking" not in li.raw and "incarceration" not in li.raw
    assert res["reeval_conflict_cleared"] == 1


@pytest.mark.asyncio
async def test_search_lane_never_reads_absence_as_released(monkeypatch):
    async def fake_search(vendor, target, last, first):
        return []                         # page-1 miss or a failed search: indistinguishable
    monkeypatch.setattr(jb, "_search_vendor", fake_search)
    li = _gvl_listing()
    before = dict(li.raw["jail_booking"])
    res = await enrich_jail_bookings([li], today=D1)
    assert li.raw["jail_booking"] == before
    assert res["reeval_absent_roster_unhealthy"] == 1


@pytest.mark.asyncio
async def test_search_lane_gates_new_matches(monkeypatch):
    async def fake_search(vendor, target, last, first):
        return [_hit("WATERS", "JIMMY", "ALLEN")]
    monkeypatch.setattr(jb, "_search_vendor", fake_search)
    conflict = _li("WATERS JIMMY S", county="Greenville")
    agree = _li("WATERS JIMMY A", county="Greenville")
    res = await enrich_jail_bookings([conflict, agree], today=D1)
    assert "jail_booking" not in conflict.raw
    assert agree.raw["jail_booking"]["confidence"] == "middle_corroborated"
    assert res["middle_conflict_rejected"] == 1 and res["matched"] == 1


# --------------------------------------------------------------------------- #
# sidecar health primitives                                                   #
# --------------------------------------------------------------------------- #

def test_judge_roster_size_policy():
    assert jrh.judge_roster_size(0, 500.0) == (False, "empty_fetch")
    assert jrh.judge_roster_size(10, 12.0) == (False, "below_floor")
    assert jrh.judge_roster_size(300, None) == (False, "no_history")
    assert jrh.judge_roster_size(200, 542.0) == (False, "implausibly_small")   # one 200-row P2C page
    assert jrh.judge_roster_size(480, 542.0) == (True, "ok")


def test_assess_uses_recent_median_and_falls_back_to_currently_listed(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    # no fetch log yet: fall back to the names currently_listed by the last diff
    jrh.diff_and_record(con, "SC", "Cherokee", "zuercher",
                        [{"last": f"FILLER{_alpha(i)}", "first": "PERSON"} for i in range(60)])
    h = jrh.assess_roster_health(con, "SC", "Cherokee", 55)
    assert h["basis"] == "currently_listed" and h["baseline"] == 60.0 and h["healthy"]
    for n in (100, 110, 5000, 105):      # one wild outlier does not move a median
        jrh.record_fetch(con, "SC", "Cherokee", "zuercher", n)
    h = jrh.assess_roster_health(con, "SC", "Cherokee", 60)
    assert h["basis"] == "recent_fetches" and h["baseline"] == 107.5
    assert h["healthy"] is False and h["reason"] == "implausibly_small"
    jrh.record_fetch(con, "SC", "Cherokee", "zuercher", 0)    # empty: never logged
    assert 0 not in jrh.recent_roster_sizes(con, "SC", "Cherokee")


# --------------------------------------------------------------------------- #
# vendor parsers now hand the middle name through                             #
# --------------------------------------------------------------------------- #

def test_comma_and_space_middle_helpers():
    assert _comma_middle("Russell, Richard Earl") == "EARL"
    assert _comma_middle("Russell, Richard") == ""
    assert _space_middle("MICHAEL LEE ABSHER") == "LEE"
    assert _space_middle("BOBBY DEAN ABEE JR") == "DEAN"
    assert _space_middle("BOBBY ABEE JR") == ""


def test_citizen_connect_and_tyler_records_carry_middle():
    card = ('<div class="card booking-card"><h5 class="mb-0">MICHAEL LEE ABSHER</h5>'
            '<span class="detail-label">Booked:</span><span class="detail-value">07/31/2026</span>')
    cc = _parse_citizen_connect_cards(card)
    assert cc[0]["last"] == "ABSHER" and cc[0]["middle"] == "LEE"
    row = ('<table><tr><td class="Name">Russell, Richard Earl</td>'
           '<td class="InCustody">Yes</td></tr></table>')
    ty = _parse_tyler_rows(row)
    assert ty[0]["last"] == "RUSSELL" and ty[0]["middle"] == "EARL"


@pytest.mark.asyncio
async def test_enricher_p2c_jqgrid_fetch_carries_middlename(monkeypatch):
    class _S:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp({})

        async def post(self, *a, **k):
            return _Resp({"rows": [{"lastname": "Testcase", "firstname": "Alpha",
                                    "middlename": "Beta"}]})
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", _S)
    recs = await jb._fetch_p2c_jqgrid("http://example.invalid/p2c")
    assert recs[0]["middle"] == "BETA"


@pytest.mark.asyncio
async def test_load_roster_blanks_placeholder_middles_for_every_consumer(monkeypatch):
    """A P2C 'NMN' must not reach match_cross_county's strict 'agrees' check
    as the initial N."""
    _install(monkeypatch, [[_zrec("Testcase, Alpha NMN"), _zrec("Testcase, Beta Carl")]])
    _key, idx = await jb._load_roster("SC", "Cherokee", "zuercher", "cherokee-so-sc")
    assert idx[jb._norm_key("TESTCASE", "ALPHA")]["middle"] == ""
    assert idx[jb._norm_key("TESTCASE", "BETA")]["middle"] == "CARL"
    assert jb._cross_county_corroborated("TESTCASE ALPHA N",
                                         idx[jb._norm_key("TESTCASE", "ALPHA")]) is False
