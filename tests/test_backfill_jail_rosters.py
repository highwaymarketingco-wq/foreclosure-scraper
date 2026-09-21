"""scripts/backfill_jail_rosters.py (build queue J-02).

The script must (1) never write the board unless --apply, (2) reach the same
matches the pipeline would (it shares enrichment_jail_bookings.match_rosters),
(3) be polite: one request at a time, spaced, a host that pushes back is left
alone, and (4) print counts only, never a roster name.

Nothing here touches a live server or the real board: HTTP is faked and the board
is a small synthetic gzip in tmp_path. Names are obvious placeholders.
"""
from __future__ import annotations

import gzip
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_jail_rosters as bjr  # noqa: E402
from foreclosure_scraper.enrichment_jail_bookings import (  # noqa: E402
    ROSTERS,
    _norm_key,
    match_rosters,
)
from foreclosure_scraper.models import Listing  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, data=None, status=200, text="", ctype="application/json"):
        self._d, self.status_code, self.text = data, status, text
        self.headers = {"content-type": ctype}

    def json(self):
        if self._d is None:
            raise ValueError("not json")
        return self._d


class _Zuercher:
    """A curl_cffi AsyncSession stand-in serving one Zuercher roster per host."""
    log: list[str] = []

    def __init__(self, hosts):
        self.hosts = hosts                       # netloc -> (status, records)

    def factory(self):
        outer = self

        class _S:
            cookies: dict = {}

            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

            async def post(self, url, json=None, timeout=None, **k):
                host = url.split("/")[2]
                outer.log.append(host)
                status, records = outer.hosts[host]
                if status != 200:
                    return _Resp(None, status, "<html>forbidden</html>", "text/html")
                return _Resp({"records": records})
        return _S


def _rec(name, dob=None):
    return {"name": name, "dob": dob, "arrest_date": "2026-09-01T00:00:00.000Z",
            "hold_reasons": ["PLACEHOLDER CHARGE"]}


def _row(county, owner, state="SC", raw_extra=None, defendant=None):
    raw = {"owner_mailing": {"owner": owner}} if owner else {}
    raw.update(raw_extra or {})
    return {"state": state, "county": county, "raw": raw, "defendant": defendant,
            "source": "test", "source_url": "http://x"}


def _write_board(path: Path, rows: list[dict]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f)
    return path


LAURENS_ROWS = [
    _row("Laurens County", "TESTCASE ALPHA"),                       # on the roster
    _row("Laurens", "TESTCASE ALPHA"),                              # same person, bare county
    _row("Laurens County", "NOBODY HERE"),                          # not on the roster
    _row("Laurens County", "TESTCASE ALPHA HOLDINGS LLC"),          # company: never eligible
    _row("Laurens County", None, defendant="PLACEHOLDER GAMMA"),    # defendant fallback, on roster
    _row("Laurens County", "TESTCASE ALPHA",
         raw_extra={"jail_booking": {"county": "Laurens"}}),        # already flagged: skipped
    _row("Oconee County", "TESTCASE ALPHA"),                        # other county: ignored here
    _row("Laurens County", "TESTCASE ALPHA", state="NC"),           # wrong state: ignored
]
LAURENS_ROSTER = [_rec("Testcase, Alpha Beta"), _rec("Placeholder, Gamma")]


# --------------------------------------------------------------------------- #
# Politeness                                                                   #
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.mark.asyncio
async def test_gate_spaces_requests_at_least_the_interval():
    c = _Clock()
    g = bjr.Gate(1.0, clock=c.now, sleep=c.sleep)
    for _ in range(4):
        await g.pace("h")
    assert g.requests == 4
    assert len(c.sleeps) == 3 and all(abs(s - 1.0) < 1e-9 for s in c.sleeps)


@pytest.mark.asyncio
async def test_gate_does_not_sleep_when_the_request_itself_was_slow():
    c = _Clock()
    g = bjr.Gate(1.0, clock=c.now, sleep=c.sleep)
    await g.pace("h")
    c.t += 5.0                                   # the request took 5s
    await g.pace("h")
    assert c.sleeps == []


@pytest.mark.parametrize("status", [401, 403, 429])
def test_gate_blocks_a_host_on_login_forbidden_or_rate_limit(status):
    g = bjr.Gate(0)
    g.judge("h", _Resp(None, status, "", "text/html"))
    assert g.blocked == {"h": f"HTTP {status}"}


@pytest.mark.parametrize("body", ["<html>Just a moment...</html>", "Attention Required! | Cloudflare",
                                  "<h1>Access Denied</h1>", "please verify you are human"])
def test_gate_blocks_a_host_that_serves_a_challenge_page(body):
    g = bjr.Gate(0)
    g.judge("h", _Resp(None, 200, body, "text/html"))
    assert "h" in g.blocked


def test_gate_does_not_block_on_ordinary_pages_or_json():
    g = bjr.Gate(0)
    g.judge("a", _Resp(None, 200, "<html>roster with a reCAPTCHA form widget</html>", "text/html"))
    g.judge("b", _Resp({"records": []}, 200, "captcha access denied", "application/json"))
    g.judge("c", object())                       # nothing inspectable
    assert g.blocked == {}


@pytest.mark.asyncio
async def test_a_blocked_host_refuses_further_requests():
    g = bjr.Gate(0)
    g.judge("h", _Resp(None, 403, "", "text/html"))
    with pytest.raises(bjr.HostBlocked):
        await g.pace("h")
    await g.pace("other")                        # other hosts are unaffected


@pytest.mark.asyncio
async def test_polite_session_wraps_every_adapter_session_and_restores(monkeypatch):
    import curl_cffi.requests as ccr
    srv = _Zuercher({"a.example": (200, []), "b.example": (200, [])})
    monkeypatch.setattr(ccr, "AsyncSession", srv.factory())
    original = ccr.AsyncSession
    c = _Clock()
    g = bjr.Gate(1.0, clock=c.now, sleep=c.sleep)
    with bjr.polite_curl_cffi(g):
        assert ccr.AsyncSession is not original
        async with ccr.AsyncSession(impersonate="chrome", verify=False) as s:
            assert s.cookies == {}               # attribute passthrough (XSRF echo needs it)
            await s.post("https://a.example/x", json={})
            await s.post("https://b.example/x", json={})
    assert ccr.AsyncSession is original
    assert g.requests == 2 and len(c.sleeps) == 1


@pytest.mark.asyncio
async def test_polite_session_stops_the_host_after_a_403(monkeypatch):
    import curl_cffi.requests as ccr
    srv = _Zuercher({"a.example": (403, [])})
    _Zuercher.log = []
    monkeypatch.setattr(ccr, "AsyncSession", srv.factory())
    g = bjr.Gate(0)
    with bjr.polite_curl_cffi(g):
        async with ccr.AsyncSession() as s:
            await s.post("https://a.example/x", json={})
            with pytest.raises(bjr.HostBlocked):
                await s.post("https://a.example/x", json={})
    assert _Zuercher.log == ["a.example"]        # the second request never left


def test_roster_host_matches_the_host_the_adapter_calls():
    got = {(s, c): bjr.roster_host(v, t) for s, c, v, t in ROSTERS}
    assert got[("SC", "Laurens")] == "laurens-911-sc.zuercherportal.com"
    assert got[("NC", "Transylvania")] == "cc.southernsoftware.com"
    assert got[("NC", "Cleveland")] == "74.218.167.200"
    assert got[("NC", "Lincoln")] == "p2c.lincolnsheriff.org"
    assert got[("NC", "Buncombe")] == "buncombecountyso.policetocitizen.com"
    assert got[("NC", "Gaston")] == "tepsweb.cityofgastonia.com"


@pytest.mark.asyncio
async def test_fetch_rosters_skips_a_host_that_already_pushed_back(monkeypatch):
    asked = []

    async def fake_load(state, county, vendor, target):
        asked.append(county)
        g.blocked["cc.southernsoftware.com"] = "HTTP 403"     # first CC roster gets 403
        return (state, county), {}

    monkeypatch.setattr(bjr, "_load_roster", fake_load)
    g = bjr.Gate(0)
    entries = [e for e in ROSTERS if e[1] in ("Polk", "Transylvania")]
    out = await bjr.fetch_rosters(entries, g)
    assert asked == ["Polk"]                                   # Transylvania not asked
    assert out[("NC", "Transylvania")] == {"index": {}, "blocked": "HTTP 403"}
    assert out[("NC", "Polk")]["blocked"] == "HTTP 403"


# --------------------------------------------------------------------------- #
# Selection and the read-only scan                                             #
# --------------------------------------------------------------------------- #
def test_select_rosters_default_is_all_and_names_are_case_insensitive():
    assert bjr.select_rosters(None) == list(ROSTERS)
    assert [e[1] for e in bjr.select_rosters("cleveland, LINCOLN")] == ["Cleveland", "Lincoln"]


def test_select_rosters_rejects_an_unknown_county():
    with pytest.raises(SystemExit) as e:
        bjr.select_rosters("Cleveland,Atlantis")
    assert "atlantis" in str(e.value)


def test_scan_counts_leads_person_owned_and_skips_flagged_and_companies():
    scan = bjr.scan_board(LAURENS_ROWS, {("SC", "Laurens")})
    s = scan[("SC", "Laurens")]
    assert s["leads"] == 6                       # Oconee row and the NC row are not Laurens SC
    assert s["eligible"] == 4                    # 2 x ALPHA + NOBODY + defendant GAMMA
    assert s["keys"][_norm_key("TESTCASE", "ALPHA")] == 2


def test_would_match_equals_what_the_pipeline_rule_flags():
    """The dry-run number and the --apply result come from one rule."""
    index = {_norm_key("TESTCASE", "ALPHA"): {"dob": None},
             _norm_key("PLACEHOLDER", "GAMMA"): {"dob": None}}
    scan = bjr.scan_board(LAURENS_ROWS, {("SC", "Laurens")})
    predicted = bjr.would_match(scan[("SC", "Laurens")], index)
    listings = [Listing(source="t", source_url="http://x", state=r["state"], county=r["county"],
                        raw=dict(r["raw"]), defendant=r["defendant"]) for r in LAURENS_ROWS]
    flagged = match_rosters(listings, {("SC", "Laurens"): index})
    assert predicted == len(flagged) == 3


# --------------------------------------------------------------------------- #
# Dry run: writes nothing, prints counts only                                  #
# --------------------------------------------------------------------------- #
@pytest.fixture
def board(tmp_path):
    return _write_board(tmp_path / "listings.json.gz", LAURENS_ROWS)


@pytest.fixture
def no_board_writes(monkeypatch):
    """Any touch of the board-writer API fails the test."""
    import foreclosure_scraper.web_artifact as wa

    def boom(*a, **k):
        raise AssertionError("dry run must not touch the board writer")
    monkeypatch.setattr(wa, "board_lock", boom)
    monkeypatch.setattr(wa, "load_board", boom)
    monkeypatch.setattr(wa, "write_artifact", boom)


def _fake_zuercher(monkeypatch, hosts):
    import curl_cffi.requests as ccr
    srv = _Zuercher(hosts)
    _Zuercher.log = []
    monkeypatch.setattr(ccr, "AsyncSession", srv.factory())
    return srv


def test_dry_run_reports_counts_and_writes_nothing(monkeypatch, board, no_board_writes, capsys):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (200, LAURENS_ROSTER)})
    rc = bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SC Laurens" in out and "zuercher" in out
    assert "DRY RUN" in out
    row = next(line for line in out.splitlines() if line.startswith("SC Laurens"))
    nums = [t.replace(",", "") for t in row.split() if t.replace(",", "").isdigit()]
    assert nums == ["6", "4", "2", "3"]          # leads, person-owned, roster, would match
    assert "leads that would be flagged: 3" in out


def test_dry_run_never_prints_a_roster_name_or_charge(monkeypatch, board, no_board_writes, capsys):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (200, LAURENS_ROSTER)})
    bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board)])
    cap = capsys.readouterr()
    text = (cap.out + cap.err).upper()
    for needle in ("TESTCASE", "ALPHA", "PLACEHOLDER", "GAMMA", "CHARGE"):
        assert needle not in text


def test_dry_run_does_not_fetch_a_roster_for_a_county_with_no_eligible_leads(
        monkeypatch, tmp_path, no_board_writes, capsys):
    b = _write_board(tmp_path / "b.json.gz", [_row("Oconee County", "TESTCASE ALPHA")])
    srv = _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (200, LAURENS_ROSTER)})
    bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(b)])
    assert _Zuercher.log == []
    assert "no eligible leads" in capsys.readouterr().out
    assert srv is not None


def test_dry_run_reports_a_blocked_host_and_stops_asking_it(
        monkeypatch, board, no_board_writes, capsys):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (403, [])})
    rc = bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BLOCKED (HTTP 403)" in out
    assert "hosts that pushed back: 1" in out
    assert _Zuercher.log == ["laurens-911-sc.zuercherportal.com"]      # exactly one request


def test_missing_board_file_is_a_clean_error(tmp_path, capsys):
    rc = bjr.main(["--counties", "Laurens", "--board", str(tmp_path / "nope.json.gz")])
    assert rc == 2 and "board file not found" in capsys.readouterr().err


def test_default_board_path_is_the_repo_gz_and_default_interval_is_polite():
    assert bjr.BOARD_GZ.name == "listings.json.gz" and bjr.BOARD_GZ.parent.name == "docs"
    assert bjr.MIN_INTERVAL >= 1.0


# --------------------------------------------------------------------------- #
# --apply: lock -> load -> match -> write                                      #
# --------------------------------------------------------------------------- #
class _Writer:
    def __init__(self, listings):
        self.listings = listings
        self.events: list = []

    def install(self, monkeypatch):
        import foreclosure_scraper.web_artifact as wa
        outer = self

        @contextmanager
        def lock(root=None, owner="", **k):
            outer.events.append(("lock", owner))
            yield
            outer.events.append(("unlock", owner))

        def load(docs_dir="docs"):
            outer.events.append(("load", str(docs_dir)))
            return outer.listings

        def write(listings, summary, docs_dir="docs"):
            outer.events.append(("write", len(listings), summary, str(docs_dir)))
            return None, None
        monkeypatch.setattr(wa, "board_lock", lock)
        monkeypatch.setattr(wa, "load_board", load)
        monkeypatch.setattr(wa, "write_artifact", write)
        return self


def _listings():
    return [Listing(source="t", source_url="http://x", state=r["state"], county=r["county"],
                    raw=dict(r["raw"]), defendant=r["defendant"]) for r in LAURENS_ROWS]


def test_apply_flags_matches_under_the_board_lock_and_writes_once(monkeypatch, board, capsys):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (200, LAURENS_ROSTER)})
    lis = _listings()
    w = _Writer(lis).install(monkeypatch)
    rc = bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board), "--apply"])
    assert rc == 0

    kinds = [e[0] for e in w.events]
    assert kinds == ["lock", "load", "write", "unlock"]        # write happens inside the lock
    assert w.events[0][1] == "backfill_jail_rosters"
    _, n, summary, docs = w.events[2]
    assert n == len(lis)
    assert "3 leads flagged" in summary["notes"]
    assert Path(docs).name == "docs"

    flagged = [li for li in lis if (li.raw or {}).get("incarceration")]
    assert len(flagged) == 3
    assert all(li.raw["incarceration"]["source"] == "Laurens County jail roster" for li in flagged)
    assert all(li.raw["jail_booking"]["confidence"] == "name_only_low" for li in flagged)
    # the company, the non-match, the other-county and other-state rows are untouched
    assert "incarceration" not in lis[2].raw and "incarceration" not in lis[3].raw
    assert "incarceration" not in lis[6].raw and "incarceration" not in lis[7].raw
    # the row that already carried a booking keeps exactly the one it had
    assert lis[5].raw["jail_booking"] == {"county": "Laurens"}
    assert "wrote board" in capsys.readouterr().out


def test_apply_with_no_roster_rows_never_loads_or_writes_the_board(monkeypatch, board, capsys):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (200, [])})
    w = _Writer(_listings()).install(monkeypatch)
    rc = bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board), "--apply"])
    assert rc == 1 and w.events == []
    assert "nothing to apply" in capsys.readouterr().out


def test_apply_with_zero_matches_does_not_rewrite_the_board(monkeypatch, board, capsys):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com":
                                 (200, [_rec("Unrelated, Person")])})
    w = _Writer(_listings()).install(monkeypatch)
    rc = bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board), "--apply"])
    assert rc == 0
    assert [e[0] for e in w.events] == ["lock", "load", "unlock"]      # no write
    assert "board not rewritten" in capsys.readouterr().out


def test_apply_a_second_time_flags_nothing_new(monkeypatch, board):
    _fake_zuercher(monkeypatch, {"laurens-911-sc.zuercherportal.com": (200, LAURENS_ROSTER)})
    lis = _listings()
    _Writer(lis).install(monkeypatch)
    bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board), "--apply"])
    snapshot = [dict(li.raw.get("jail_booking") or {}) for li in lis]
    w2 = _Writer(lis).install(monkeypatch)
    bjr.main(["--counties", "Laurens", "--interval", "0", "--board", str(board), "--apply"])
    assert [dict(li.raw.get("jail_booking") or {}) for li in lis] == snapshot
    assert [e[0] for e in w2.events] == ["lock", "load", "unlock"]
