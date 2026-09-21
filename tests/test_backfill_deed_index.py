"""scripts/backfill_deed_index.py: dry run by default, one wall stops one host,
and the board is only loaded and written when it can change.

Nothing here touches the real board, the real sidecar or the network. The board
functions the script imports are replaced with recorders that FAIL the test when a
path that must not use them does; the sweep is replaced with a fake.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_deed_index as bd  # noqa: E402

from foreclosure_scraper import deed_index  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows as REAL_ITER_BOARD_ROWS  # noqa: E402
from foreclosure_scraper.deed_index import DeedInstrument, Party  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402
from foreclosure_scraper.rod import cchs  # noqa: E402
from foreclosure_scraper.rod import inst_class as ic  # noqa: E402


class Guards:
    """Records calls to the functions a dry run must never reach."""

    def __init__(self):
        self.calls: list[str] = []
        self.sweeps: list[str] = []
        self.written: list[tuple] = []


@pytest.fixture
def forbidden(monkeypatch):
    """Every board and network entry point raises. Tests that may use one re-patch it."""
    g = Guards()

    def boom(name):
        def f(*a, **k):
            g.calls.append(name)
            raise AssertionError(f"{name} must not be called here")
        return f

    async def no_sweep(*a, **k):
        g.calls.append("sweep_loss_instruments")
        raise AssertionError("sweep_loss_instruments must not be called here")

    monkeypatch.setattr(bd, "load_board", boom("load_board"))
    monkeypatch.setattr(bd, "board_lock", boom("board_lock"))
    monkeypatch.setattr(bd, "write_artifact", boom("write_artifact"))
    monkeypatch.setattr(bd, "iter_board_rows", boom("iter_board_rows"))
    monkeypatch.setattr(cchs, "sweep_loss_instruments", no_sweep)
    return g


def _instrument(names=("DOE JOHN Q",), county="Burke", page="101", parcel="9-1000001",
                date="2024-05-01") -> DeedInstrument:
    parties = [Party("PLACEHOLDER TRUSTEE SERVICES PLLC", kind="F")] + [Party(n, kind="I") for n in names]
    kind, losers = deed_index.derive_loss(ic.TRUSTEE_DEED, parties, "8123/456")
    return DeedInstrument(
        county=county, state="NC", source="cchs_classic", inst_code="TR/D", inst_class=ic.TRUSTEE_DEED,
        recorded_date=date, book="9001", page=page, instrument_no=f"2024{page}", parcel_id=parcel,
        grantors=[p.name for p in parties], grantor_parties=parties, grantees=["EXAMPLE MORTGAGE HOLDINGS LLC"],
        description="8123/456", loss_kind=kind, loser_names=losers)


def _result(county, instruments=(), walled=None, problems=()):
    return cchs.SweepResult("NC", county, instruments=list(instruments), kinds=("TR/D", "COM/D", "SHF/D"),
                            kinds_source="dictionary", requests=5, windows=1 if instruments else 0,
                            rows=len(instruments) * 3, walled=walled, problems=list(problems))


def _fake_sweeper(monkeypatch, per_county: dict, guards: Guards):
    async def fake(state, county, start, end):
        guards.sweeps.append(county)
        return per_county.get(county) or _result(county)

    monkeypatch.setattr(cchs, "sweep_loss_instruments", fake)


def _write_board(docs: Path, rows: list[dict]) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    with gzip.open(docs / "listings.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rows, f)


def _listing(owner, county="Burke", parcel="P2", raw=None) -> Listing:
    return Listing(source="s", source_url=f"https://example.com/{owner}-{parcel}",
                   listing_type=ListingType.TAX_LIEN, state="NC", county=county,
                   owner_name=owner, parcel_id=parcel, raw=raw or {})


def _args(tmp_path, *extra):
    return ["--db", str(tmp_path / "d.db"), "--docs", str(tmp_path / "docs"), *extra]


# --- dry run -------------------------------------------------------------------------
def test_default_is_a_dry_run_that_touches_no_network_no_board_and_writes_nothing(
        forbidden, tmp_path, capsys):
    assert bd.main(_args(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Burke" in out and "Lincoln" in out and "not built yet" in out
    assert forbidden.calls == []
    assert not (tmp_path / "d.db").exists() and not (tmp_path / "docs").exists()


def test_dry_run_prints_the_plan_per_host(forbidden, tmp_path, capsys):
    bd.main(_args(tmp_path, "--from-year", "2024", "--to-year", "2025"))
    out = capsys.readouterr().out
    assert re.search(r"Burke\s+host us5\s+~7 requests", out)     # 3 bootstrap + 2 per year x 2 years
    assert re.search(r"Lincoln\s+host us4", out)
    assert "hosts touched: us4, us5" in out


def test_dry_run_shows_sidecar_coverage_without_modifying_the_file(forbidden, tmp_path, capsys):
    con = deed_index.connect(tmp_path / "d.db")
    deed_index.upsert(con, [_instrument()])
    con.close()
    before = (tmp_path / "d.db").read_bytes()
    bd.main(_args(tmp_path))
    out = capsys.readouterr().out
    assert "1 instruments" in out and "Burke" in out and "1 name a loser" in out
    assert (tmp_path / "d.db").read_bytes() == before
    assert forbidden.calls == []


def test_preview_board_streams_the_board_and_never_loads_it(forbidden, tmp_path, monkeypatch, capsys):
    """--preview-board is the only board contact a dry run has, and it is board_stream."""
    con = deed_index.connect(tmp_path / "d.db")
    deed_index.upsert(con, [_instrument()])
    con.close()
    _write_board(tmp_path / "docs", [
        {"owner_name": "DOE JOHN Q", "county": "Burke", "state": "NC"},
        {"owner_name": "SOMEONE ELSE", "county": "Burke", "state": "NC"}])
    monkeypatch.setattr(bd, "iter_board_rows", REAL_ITER_BOARD_ROWS)
    assert bd.main(_args(tmp_path, "--preview-board")) == 0
    assert "'candidate_rows': 1" in capsys.readouterr().out
    assert forbidden.calls == []                          # load_board / board_lock / write_artifact untouched


def test_apply_and_sweep_only_cannot_be_combined(forbidden, tmp_path):
    with pytest.raises(SystemExit):
        bd.main(_args(tmp_path, "--apply", "--sweep-only"))


# --- sweep only -------------------------------------------------------------------------
def test_sweep_only_fills_the_sidecar_and_never_opens_the_board(forbidden, tmp_path, monkeypatch, capsys):
    _fake_sweeper(monkeypatch, {"Burke": _result("Burke", [_instrument(), _instrument(page="102")])}, forbidden)
    assert bd.main(_args(tmp_path, "--sweep-only")) == 0
    out = capsys.readouterr().out
    assert "2 instruments" in out and "board not touched" in out
    assert forbidden.sweeps == ["Burke", "Cleveland", "Henderson", "Lincoln"]
    assert [r["page"] for r in deed_index.load_loss_rows(tmp_path / "d.db")] == ["101", "102"]
    assert "load_board" not in forbidden.calls and "iter_board_rows" not in forbidden.calls


def test_one_wall_stops_that_host_skips_its_other_counties_and_exits_2(forbidden, tmp_path, monkeypatch, capsys):
    """Burke and Cleveland share us5; Henderson and Lincoln share us4."""
    _fake_sweeper(monkeypatch, {
        "Burke": _result("Burke", walled="us5.courthousecomputersystems.com search 2010-01-01..2010-12-31: HTTP 403"),
        "Henderson": _result("Henderson", walled="us4.courthousecomputersystems.com search 2010-01-01..2010-12-31: HTTP 403"),
    }, forbidden)
    assert bd.main(_args(tmp_path, "--sweep-only")) == 2
    out = capsys.readouterr().out
    assert forbidden.sweeps == ["Burke", "Henderson"]        # Cleveland and Lincoln never asked
    assert "WALL" in out and "not retried" in out
    assert "Cleveland" in out and "host us5 already walled" in out
    assert "Lincoln" in out and "host us4 already walled" in out


def test_a_shape_problem_or_a_capped_window_also_exits_2(forbidden, tmp_path, monkeypatch, capsys):
    _fake_sweeper(monkeypatch, {"Burke": _result("Burke", [_instrument()],
                                                 problems=["2024-01-01..2024-12-31: search reply has no <recordcount>"])},
                  forbidden)
    assert bd.main(_args(tmp_path, "--sweep-only", "--counties", "Burke")) == 2
    assert "PROBLEM: 2024-01-01..2024-12-31" in capsys.readouterr().out


def test_a_county_on_another_platform_is_skipped_not_swept(forbidden, tmp_path, monkeypatch, capsys):
    _fake_sweeper(monkeypatch, {}, forbidden)
    assert bd.main(_args(tmp_path, "--sweep-only", "--counties", "Buncombe,Burke")) == 0
    assert forbidden.sweeps == ["Burke"]
    assert "Buncombe" in capsys.readouterr().out


def test_the_sweep_refreshes_losers_so_a_standing_officer_is_dropped(forbidden, tmp_path, monkeypatch, capsys):
    docs = []
    for n in range(1, 21):
        parties = [Party("ROE RICHARD T", kind="I"), Party(f"TAXPAYER{n:02d} PERSON", kind="I")]
        kind, losers = deed_index.derive_loss(ic.COMMISSIONER_DEED, parties, "TAX FORECLOSURE")
        docs.append(DeedInstrument(
            county="Burke", state="NC", source="cchs_classic", inst_code="COM/D",
            inst_class=ic.COMMISSIONER_DEED, recorded_date="2024-01-01", book="9001", page=str(n),
            instrument_no=f"2024{n:05d}", grantors=[p.name for p in parties], grantor_parties=parties,
            description="TAX FORECLOSURE", loss_kind=kind, loser_names=losers))
    _fake_sweeper(monkeypatch, {"Burke": _result("Burke", docs)}, forbidden)
    bd.main(_args(tmp_path, "--sweep-only", "--counties", "Burke"))
    assert "Burke, NC" in capsys.readouterr().out
    assert all("ROE RICHARD T" not in r["loser_names"] for r in deed_index.load_loss_rows(tmp_path / "d.db"))


# --- apply -------------------------------------------------------------------------------
def _allow_board(monkeypatch, guards: Guards, listings: list[Listing]):
    """apply's board path, against synthetic Listings."""
    monkeypatch.setattr(bd, "iter_board_rows", REAL_ITER_BOARD_ROWS)
    monkeypatch.setattr(bd, "board_lock", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(bd, "load_board", lambda docs: (guards.calls.append("load_board"), listings)[1])

    def write(rows, summary, docs_dir=None):
        guards.written.append((rows, summary, docs_dir))

    monkeypatch.setattr(bd, "write_artifact", write)


def test_apply_sweeps_previews_then_joins_and_writes_once(forbidden, tmp_path, monkeypatch, capsys):
    current = _listing("DOE JOHN Q", parcel="P2")
    bystander = _listing("SOMEONE ELSE", parcel="P3")
    _write_board(tmp_path / "docs", [{"owner_name": "DOE JOHN Q", "county": "Burke", "state": "NC"},
                                     {"owner_name": "SOMEONE ELSE", "county": "Burke", "state": "NC"}])
    _fake_sweeper(monkeypatch, {"Burke": _result("Burke", [_instrument()])}, forbidden)
    _allow_board(monkeypatch, forbidden, [current, bystander])
    assert bd.main(_args(tmp_path, "--apply")) == 0
    out = capsys.readouterr().out
    assert "'candidate_rows': 1" in out and "'tagged_rows': 1" in out and "'written': True" in out
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 1
    assert current.raw["deed_index"][0]["book"] == "9001"
    assert "repeat_tax_loss" not in bystander.raw
    (rows, summary, docs_dir), = forbidden.written
    assert rows == [current, bystander] and summary == {"backfill_deed_index": 1}
    assert forbidden.sweeps == ["Burke", "Cleveland", "Henderson", "Lincoln"]
    assert forbidden.calls.count("load_board") == 1


def test_apply_never_loads_the_board_when_no_owner_can_match(forbidden, tmp_path, monkeypatch, capsys):
    _write_board(tmp_path / "docs", [{"owner_name": "SOMEONE ELSE", "county": "Burke", "state": "NC"}])
    _fake_sweeper(monkeypatch, {"Burke": _result("Burke", [_instrument()])}, forbidden)
    _allow_board(monkeypatch, forbidden, [])
    assert bd.main(_args(tmp_path, "--apply")) == 0
    assert "board not loaded, nothing written" in capsys.readouterr().out
    assert "load_board" not in forbidden.calls and forbidden.written == []


def test_apply_never_touches_the_board_when_the_sweep_found_nothing(forbidden, tmp_path, monkeypatch, capsys):
    """Both hosts walled: an empty sidecar. Exit 2, and not even the stream is opened."""
    _fake_sweeper(monkeypatch, {
        "Burke": _result("Burke", walled="us5 HTTP 403"),
        "Henderson": _result("Henderson", walled="us4 HTTP 403")}, forbidden)
    _allow_board(monkeypatch, forbidden, [])
    monkeypatch.setattr(bd, "iter_board_rows", lambda *a, **k: pytest.fail("board stream opened"))
    assert bd.main(_args(tmp_path, "--apply")) == 2
    assert "nothing to join: board not touched" in capsys.readouterr().out
    assert "load_board" not in forbidden.calls and forbidden.written == []


def test_apply_does_not_republish_the_board_when_the_guard_excludes_every_match(
        forbidden, tmp_path, monkeypatch, capsys):
    """The stream preview counts the name; the self-match guard then finds it is the
    parcel he lost (vendor key 9-1000001 is board key 91000001). Nothing changed, so
    the board is loaded but not written."""
    same_parcel = _listing("DOE JOHN Q", parcel="91000001")
    _write_board(tmp_path / "docs", [{"owner_name": "DOE JOHN Q", "county": "Burke", "state": "NC"}])
    _fake_sweeper(monkeypatch, {"Burke": _result("Burke", [_instrument(parcel="9-1000001")])}, forbidden)
    _allow_board(monkeypatch, forbidden, [same_parcel])
    assert bd.main(_args(tmp_path, "--apply")) == 0
    assert "'written': False" in capsys.readouterr().out
    assert forbidden.written == [] and "repeat_tax_loss" not in same_parcel.raw


def test_apply_no_sweep_joins_from_the_sidecar_as_it_is(forbidden, tmp_path, monkeypatch, capsys):
    con = deed_index.connect(tmp_path / "d.db")
    deed_index.upsert(con, [_instrument()])
    con.close()
    current = _listing("DOE JOHN Q")
    _write_board(tmp_path / "docs", [{"owner_name": "DOE JOHN Q", "county": "Burke", "state": "NC"}])
    _allow_board(monkeypatch, forbidden, [current])
    assert bd.main(_args(tmp_path, "--apply", "--no-sweep")) == 0
    assert forbidden.sweeps == [] and len(forbidden.written) == 1


def test_the_board_lock_wraps_the_whole_load_join_write_span(forbidden, tmp_path, monkeypatch):
    events = []

    @contextlib.contextmanager
    def lock(*a, **k):
        events.append(("lock", k.get("owner")))
        yield
        events.append("unlock")

    con = deed_index.connect(tmp_path / "d.db")
    deed_index.upsert(con, [_instrument()])
    con.close()
    current = _listing("DOE JOHN Q")
    _write_board(tmp_path / "docs", [{"owner_name": "DOE JOHN Q", "county": "Burke", "state": "NC"}])
    _allow_board(monkeypatch, forbidden, [current])
    monkeypatch.setattr(bd, "board_lock", lock)
    monkeypatch.setattr(bd, "load_board", lambda docs: (events.append("load"), [current])[1])
    monkeypatch.setattr(bd, "write_artifact", lambda *a, **k: events.append("write"))
    bd.main(_args(tmp_path, "--apply", "--no-sweep"))
    assert events == [("lock", "backfill_deed_index"), "load", "write", "unlock"]


def test_build_plan_estimates_requests_and_marks_other_platforms():
    plan = {p["county"]: p for p in bd.build_plan(["Burke", "Buncombe"], 2010, 2026)}
    assert plan["Burke"]["est_requests"] == 3 + 2 * 17 and plan["Burke"]["host"] == "us5"
    assert plan["Buncombe"]["host"] is None and plan["Buncombe"]["est_requests"] == 0
