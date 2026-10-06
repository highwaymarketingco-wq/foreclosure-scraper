"""scripts/verification_recheck.py: re-verify named ledger entries (by latest verdict, or by key)
and report what changed, on a scratch board and a scratch ledger. No network (a fake verifier),
the board is never written, only the ledger file is."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.registry import Verifier

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _load_script():
    spec = importlib.util.spec_from_file_location("verification_recheck",
                                                  REPO / "scripts" / "verification_recheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(pid, tier="WARM", county="Buncombe", addr=None, owner="SECRET PERSON"):
    return {"source": "s", "source_url": "https://x/roll.pdf", "listing_type": "tax_lien", "state": "NC",
            "county": county, "parcel_id": pid, "street_address": addr or f"{pid[-3:]} Main St",
            "owner_name": owner, "raw": {"distress_stack": {"tier": tier}}}


ROWS = [_row("1000000001", "COLD"), _row("1000000002", "WARM"), _row("1000000003", "HOT"),
        _row("1000000003", "COLD", addr="Other Name Rd"),            # same parcel, worse tier
        _row("1000000004", "WARM"), _row("1000000005", "HOT")]


@pytest.fixture
def board(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(ROWS).encode()))
    return docs


def _verifier(calls, answers, *, version="v4", name="fake_tax"):
    async def verify(row, client):
        calls.append(row["parcel_id"])
        verdict, reason = answers.get(row["parcel_id"], ("confirmed", None))
        return core.result("tax_lien", verdict, {"reason": reason} if reason else {}, source="fake",
                           version=version, verifier=name)
    return Verifier(name=name, signal="tax_lien", version=version, ttl_days=30,
                    applies=lambda r: r.get("listing_type") == "tax_lien", verify=verify,
                    governs=("tax_lien",))


def _ledger_with(tmp_path, verdicts, *, version="v3", name="fake_tax"):
    """A tax_lien ledger on disk: {parcel: old verdict} for the rows of ROWS."""
    ldir = tmp_path / "ledger"
    led = L.Ledger("tax_lien", path=L.ledger_path("tax_lien", ldir))
    by_pid = {r["parcel_id"]: r for r in ROWS}
    for pid, verdict in verdicts.items():
        led.record(by_pid[pid], core.result("tax_lien", verdict, {}, version=version, verifier=name,
                                            now=NOW - timedelta(days=2)), ttl_days=30, now=NOW)
    led.save(now=NOW)
    return ldir


def _wire(rc, monkeypatch, tmp_path, verifier):
    monkeypatch.setattr(rc, "discover", lambda: [verifier])
    monkeypatch.setattr(rc, "RUN_LOCK", tmp_path / "recheck.lock")
    monkeypatch.setenv("HANDOFF_PUSH", "0")


def _args(board, ldir, *extra):
    return ["--signal", "tax_lien", "--docs", str(board), "--ledger-dir", str(ldir), *extra]


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def test_default_selection_is_the_stale_and_refuted_entries(tmp_path):
    rc = _load_script()
    ldir = _ledger_with(tmp_path, {"1000000001": "stale", "1000000002": "refuted",
                                   "1000000003": "confirmed", "1000000004": "unconfirmed"})
    led = L.Ledger.load("tax_lien", ldir)
    chosen, missing = rc.select_entries(led, verdicts={"stale", "refuted"}, keys=None, cap=-1)
    assert sorted(chosen) == ["parcel:NC:buncombe:1000000001", "parcel:NC:buncombe:1000000002"]
    assert missing == []
    capped, _ = rc.select_entries(led, verdicts={"stale", "refuted"}, keys=None, cap=1)
    assert list(capped) == ["parcel:NC:buncombe:1000000001"]
    only_stale, _ = rc.select_entries(led, verdicts={"stale"}, keys=None, cap=-1)
    assert list(only_stale) == ["parcel:NC:buncombe:1000000001"]


def test_a_keys_file_names_entries_by_any_key_and_reports_the_unknown(tmp_path):
    rc = _load_script()
    ldir = _ledger_with(tmp_path, {"1000000001": "stale", "1000000003": "confirmed"})
    kf = tmp_path / "keys.txt"
    kf.write_text("# keys to recheck\n\nparcel:NC:buncombe:1000000003   # confirmed one\n"
                  "addr:NC:buncombe:001 main st\nparcel:NC:buncombe:9999999999\n")
    keys = rc.read_keys(kf)
    assert keys == ["parcel:NC:buncombe:1000000003", "addr:NC:buncombe:001 main st",
                    "parcel:NC:buncombe:9999999999"]
    led = L.Ledger.load("tax_lien", ldir)
    chosen, missing = rc.select_entries(led, verdicts=None, keys=keys, cap=-1)
    assert sorted(chosen) == ["parcel:NC:buncombe:1000000001", "parcel:NC:buncombe:1000000003"]
    assert missing == ["parcel:NC:buncombe:9999999999"]
    narrowed, _ = rc.select_entries(led, verdicts={"stale"}, keys=keys, cap=-1)
    assert list(narrowed) == ["parcel:NC:buncombe:1000000001"]


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def test_dry_run_finds_the_rows_and_fetches_nothing_and_writes_nothing(board, tmp_path, monkeypatch, capsys):
    rc = _load_script()
    calls: list = []
    ldir = _ledger_with(tmp_path, {"1000000001": "stale", "1000000002": "refuted"})
    _wire(rc, monkeypatch, tmp_path, _verifier(calls, {}))
    before = (ldir / "tax_lien.json").read_bytes()
    assert rc.main(_args(board, ldir, "--dry-run")) == 0
    assert calls == [] and (ldir / "tax_lien.json").read_bytes() == before
    out = capsys.readouterr().out
    assert "2 of 2 entries have a board row" in out and "dry run" in out


def test_end_to_end_rechecks_only_the_selected_entries_and_reports_counts_without_names(
        board, tmp_path, monkeypatch, capsys):
    rc = _load_script()
    calls: list = []
    ldir = _ledger_with(tmp_path, {"1000000001": "stale", "1000000002": "refuted",
                                   "1000000003": "confirmed", "1000000004": "stale"})
    answers = {"1000000001": ("confirmed", None),                       # stale   -> confirmed
               "1000000002": ("unconfirmed", "address_parcel_mismatch"),  # refuted -> unconfirmed
               "1000000004": ("stale", None)}                           # stale   -> stale
    _wire(rc, monkeypatch, tmp_path, _verifier(calls, answers))
    board_hash = hashlib.sha256((board / "listings.json.gz").read_bytes()).hexdigest()
    passes = []
    real = rc.iter_board_rows
    monkeypatch.setattr(rc, "iter_board_rows", lambda *a, **k: (passes.append(1), real(*a, **k))[1])

    assert rc.main(_args(board, ldir, "--save-every", "1")) == 0
    assert hashlib.sha256((board / "listings.json.gz").read_bytes()).hexdigest() == board_hash
    assert len(passes) == 1                                  # ONE read-only board pass
    assert sorted(calls) == ["1000000001", "1000000002", "1000000004"]   # the confirmed one untouched
    led = L.Ledger.load("tax_lien", ldir)
    v = {k.rsplit(":", 1)[-1]: e["latest"]["verdict"] for k, e in led.rows.items()}
    assert v == {"1000000001": "confirmed", "1000000002": "unconfirmed",
                 "1000000003": "confirmed", "1000000004": "stale"}
    assert led.rows["parcel:NC:buncombe:1000000002"]["latest"]["verifier_version"] == "v4"
    assert led.last_run["recheck"] is True and led.last_run["result"]["checked"] == 3
    out = capsys.readouterr().out
    assert "selected 3" in out and "on the board 3" in out and "rechecked 3" in out
    assert "changed 2 of 3" in out
    assert "stale       -> confirmed" in out and "refuted     -> unconfirmed" in out
    assert "stale       -> stale" in out and "(unchanged)" in out
    assert "unconfirmed reasons: address_parcel_mismatch 1" in out
    assert "SECRET" not in out and "PERSON" not in out       # counts, no names


def test_the_better_ranked_row_of_a_property_is_the_one_rechecked(board, tmp_path, monkeypatch):
    rc = _load_script()
    seen: list = []

    async def verify(row, client):
        seen.append(row["raw"]["distress_stack"]["tier"])
        return core.result("tax_lien", "confirmed", {}, source="fake", version="v4", verifier="fake_tax")
    v = Verifier(name="fake_tax", signal="tax_lien", version="v4", ttl_days=30,
                 applies=lambda r: True, verify=verify, governs=("tax_lien",))
    ldir = _ledger_with(tmp_path, {"1000000003": "stale"})
    _wire(rc, monkeypatch, tmp_path, v)
    assert rc.main(_args(board, ldir)) == 0
    assert seen == ["HOT"]                                   # two board rows, one check


def test_an_entry_with_no_board_row_is_counted_not_rechecked(board, tmp_path, monkeypatch, capsys):
    rc = _load_script()
    calls: list = []
    ghost = _row("1000000099")
    ldir = tmp_path / "ledger"
    led = L.Ledger("tax_lien", path=L.ledger_path("tax_lien", ldir))
    led.record(ghost, core.result("tax_lien", "stale", {}, version="v3", verifier="fake_tax",
                                  now=NOW - timedelta(days=2)), ttl_days=30, now=NOW)
    led.record(ROWS[1], core.result("tax_lien", "stale", {}, version="v3", verifier="fake_tax",
                                    now=NOW - timedelta(days=2)), ttl_days=30, now=NOW)
    led.save(now=NOW)
    _wire(rc, monkeypatch, tmp_path, _verifier(calls, {"1000000002": ("refuted", None)}))
    assert rc.main(_args(board, ldir)) == 0
    assert calls == ["1000000002"]
    out = capsys.readouterr().out
    assert "selected 2" in out and "on the board 1 | not on the board 1" in out
    still = L.Ledger.load("tax_lien", ldir).rows["parcel:NC:buncombe:1000000099"]
    assert still["latest"]["verdict"] == "stale"             # untouched, never dropped


def test_a_case_scoped_entry_is_found_by_its_case_key(tmp_path, monkeypatch):
    rc = _load_script()
    seen: list = []
    cid = core.case_id("jail", "NC", "Buncombe", "x")
    ledger_keys = lambda row: core.scoped_keys(core.row_keys(row), cid)      # noqa: E731

    async def verify(row, client):
        seen.append(row["parcel_id"])
        return core.result("tax_lien", "confirmed", {}, source="fake", version="v2", verifier="fake_case")

    v = Verifier(name="fake_case", signal="tax_lien", version="v2", ttl_days=3, applies=lambda r: True,
                 verify=verify, identity="case", case_identity=lambda row: cid)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(ROWS).encode()))
    ldir = tmp_path / "ledger"
    led = L.Ledger("tax_lien", path=L.ledger_path("tax_lien", ldir))
    led.record(ROWS[1], core.result("tax_lien", "stale", {}, version="v1", verifier="fake_case",
                                    now=NOW - timedelta(days=2)), ttl_days=3, now=NOW,
               keys=ledger_keys(ROWS[1]))
    led.save(now=NOW)
    kf = tmp_path / "k.txt"
    kf.write_text(f"{cid}@parcel:NC:buncombe:1000000002\n")
    _wire(rc, monkeypatch, tmp_path, v)
    assert rc.main(_args(docs, ldir, "--keys-file", str(kf))) == 0
    assert seen == ["1000000002"]
    assert L.Ledger.load("tax_lien", ldir).counts()["confirmed"] == 1


def test_an_unreadable_ledger_is_never_overwritten(board, tmp_path, monkeypatch):
    rc = _load_script()
    ldir = tmp_path / "ledger"
    ldir.mkdir()
    (ldir / "tax_lien.json").write_text("not a ledger")
    _wire(rc, monkeypatch, tmp_path, _verifier([], {}))
    assert rc.main(_args(board, ldir)) == 1
    assert (ldir / "tax_lien.json").read_text() == "not a ledger"


def test_report_lines():
    rc = _load_script()
    lines = rc.report("tax_lien", 5, 1, 4, {"a": "stale", "b": "stale", "c": "refuted", "d": "stale"},
                      {"a": ("refuted", None), "b": ("stale", None), "c": ("unconfirmed", "pin_inactive"),
                       "d": ("unconfirmed", "pin_inactive")}, 1)
    text = "\n".join(lines)
    assert "selected 5 (1 listed key(s) match no entry)" in text and "not on the board 1" in text
    assert "changed 3 of 4" in text and "unconfirmed reasons: pin_inactive 2" in text
