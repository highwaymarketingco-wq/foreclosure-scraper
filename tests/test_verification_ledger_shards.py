"""verification.ledger's sharded layout (2026-10-09): docs/handoff/verification/<signal>/manifest.json
+ NNN.json, the single file read as a fallback, merge-safe writes, the git hand-off of both
layouts, the readers, and scripts/ledger_migrate.py. Every row here is made up."""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper.verification import apply as A
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


def _row(i: int, addr: str | None = None, parcel: str | None = None) -> dict:
    return {"state": "NC", "county": "Buncombe", "parcel_id": parcel or f"9{i:011d}",
            "street_address": addr or f"{i + 1} Sample Rd", "listing_type": "tax_lien"}


def _res(verdict: str, at: datetime, signal: str = "tax_lien", **ev):
    return core.result(signal, verdict, ev or {"note": "made up"}, source="s", version="v1",
                       verifier=f"{signal}_test", now=at)


def _ledger(n: int, at: datetime = T0, signal: str = "tax_lien") -> L.Ledger:
    led = L.Ledger(signal)
    for i in range(n):
        led.record(_row(i), _res("confirmed" if i % 3 else "refuted", at, signal, total=float(i)),
                   ttl_days=30, governs=("tax_lien",), now=at)
    led.last_run = {"at": core.iso_z(at), "made_up": True}
    return led


def _files(sd: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(sd.iterdir()) if p.name != L.MANIFEST_NAME}


def _same(a: dict, b: dict) -> bool:
    return json.loads(json.dumps(a)) == json.loads(json.dumps(b))


# ----------------------------------------------------------------------------- round trip
def test_shards_round_trip_with_a_manifest_that_describes_every_shard(tmp_path):
    led = _ledger(60)
    sd = led.save(tmp_path / "tax_lien", host="h", now=T0)
    assert sd == tmp_path / "tax_lien" and not (tmp_path / "tax_lien.json").exists()
    m = json.loads((sd / "manifest.json").read_text())
    assert m["kind"] == L.MANIFEST_KIND and m["version"] == L.SHARD_LAYOUT_VERSION
    assert m["signal"] == "tax_lien" and m["rows"] == 60 and m["counts"]["rows"] == 60
    assert m["buckets"] & (m["buckets"] - 1) == 0 and m["hash"] == L.HASH_RULE
    assert m["last_run"] == {"at": core.iso_z(T0), "made_up": True}
    files = _files(sd)
    assert set(files) == {s["file"] for s in m["shards"]}
    for s in m["shards"]:
        data = files[s["file"]]
        doc = json.loads(data)
        assert s["sha256"] == hashlib.sha256(data).hexdigest() and s["bytes"] == len(data)
        assert s["rows"] == len(doc["rows"]) and doc["bucket"] == s["bucket"]
        assert all(L.bucket_of(k, m["buckets"]) == s["bucket"] for k in doc["rows"])
        assert "generated_at" not in doc                # shards carry no timestamp
    back = L.Ledger.load("tax_lien", tmp_path)
    assert back.path == sd and _same(back.rows, led.rows) and back.last_run == led.last_run
    assert L.ledger_layout("tax_lien", tmp_path) == "shards"
    # each entry line is byte for byte what the single file writes for it
    single = led.save(tmp_path / "copy" / "tax_lien.json", now=T0)
    on_disk = sorted(ln for d in files.values() for ln in L.raw_row_lines(d))
    assert on_disk == sorted(L.raw_row_lines(single.read_bytes()))


def test_a_new_ledger_is_written_as_shards(tmp_path):
    led = L.Ledger.load("tax_lien", tmp_path)
    assert led.rows == {} and led.path == tmp_path / "tax_lien"
    led.record(_row(1), _res("confirmed", T0), ttl_days=30, now=T0)
    assert led.save() == tmp_path / "tax_lien"
    assert (tmp_path / "tax_lien" / "manifest.json").exists()
    assert not (tmp_path / "tax_lien.json").exists()


# ----------------------------------------------------------------------------- the old file
def test_the_single_file_is_read_as_a_fallback_and_stays_a_file_until_migrated(tmp_path):
    led = _ledger(5)
    led.save(tmp_path / "tax_lien.json", now=T0)
    back = L.Ledger.load("tax_lien", tmp_path)
    assert back.path == tmp_path / "tax_lien.json" and _same(back.rows, led.rows)
    assert L.ledger_layout("tax_lien", tmp_path) == "file"
    back.record(_row(9), _res("confirmed", T0), ttl_days=30, now=T0)
    assert back.save() == tmp_path / "tax_lien.json"          # same layout as loaded
    assert not (tmp_path / "tax_lien").exists()
    leds, bad = L.load_all(tmp_path)
    assert bad == {} and len(leds["tax_lien"].rows) == 6
    li = core_listing(_row(0))
    A.apply_verification([li], tmp_path, now=T0)
    assert li.raw["verification"][0]["verdict"] == "refuted"


def test_a_single_file_that_would_pass_the_file_limit_is_written_as_shards(tmp_path, monkeypatch):
    led = _ledger(30)
    led.save(tmp_path / "tax_lien.json", now=T0)
    back = L.Ledger.load("tax_lien", tmp_path)
    monkeypatch.setattr(L, "FILE_MAX_BYTES", 2000)
    assert back.save(now=T0) == tmp_path / "tax_lien"
    assert not (tmp_path / "tax_lien.json").exists()
    assert _same(L.Ledger.load("tax_lien", tmp_path).rows, led.rows)


def core_listing(row: dict):
    from foreclosure_scraper.models import Listing, ListingType
    return Listing(source="s", source_url="https://example.test/x", listing_type=ListingType.TAX_LIEN,
                   state=row["state"], county=row["county"], parcel_id=row["parcel_id"],
                   street_address=row["street_address"])


# ----------------------------------------------------------------------------- mixed layouts
def test_mixed_layouts_are_merged_and_the_next_save_keeps_only_the_shards(tmp_path):
    shards = L.Ledger("tax_lien")
    shards.record(_row(1), _res("confirmed", T0), ttl_days=30, now=T0)
    shards.record(_row(2), _res("confirmed", T0), ttl_days=30, now=T0)
    shards.save(tmp_path / "tax_lien", now=T0)
    t1 = T0 + timedelta(days=1)
    single = L.Ledger("tax_lien")
    single.record(_row(1), _res("refuted", t1), ttl_days=30, now=t1)       # newer answer
    single.record(_row(3), _res("confirmed", t1), ttl_days=30, now=t1)
    single.save(tmp_path / "tax_lien.json", now=t1)
    assert L.ledger_layout("tax_lien", tmp_path) == "mixed"

    led = L.Ledger.load("tax_lien", tmp_path)                      # a writer may go on
    assert led.path == tmp_path / "tax_lien" and len(led.rows) == 3
    e1 = led.find_row(_row(1))[1]
    assert e1["latest"]["verdict"] == "refuted"                    # newer checked_at wins
    assert [h["verdict"] for h in e1["history"]] == ["confirmed"]
    assert "tax_lien.json" in led.warnings
    leds, bad = L.load_all(tmp_path)
    assert len(leds["tax_lien"].rows) == 3 and bad["tax_lien.json"].startswith("read anyway:")

    led.save(now=t1)
    assert L.ledger_layout("tax_lien", tmp_path) == "shards"
    after = L.Ledger.load("tax_lien", tmp_path)
    assert {e["latest"]["verdict"] for e in after.rows.values()} == {"refuted", "confirmed"}
    assert len(after.rows) == 3 and after.warnings == {}


def test_a_writer_never_removes_a_file_it_has_not_merged(tmp_path):
    led = L.Ledger.load("tax_lien", tmp_path)
    led.record(_row(1), _res("confirmed", T0), ttl_days=30, now=T0)
    led.save(now=T0)                                           # shards
    late = L.Ledger("tax_lien")                                # an older writer, after that
    late.record(_row(7), _res("refuted", T0), ttl_days=30, now=T0)
    late.save(tmp_path / "tax_lien.json", now=T0)
    led.record(_row(2), _res("confirmed", T0), ttl_days=30, now=T0)
    led.save(now=T0)                                           # merges row 7, then removes the file
    assert not (tmp_path / "tax_lien.json").exists()
    assert len(L.Ledger.load("tax_lien", tmp_path).rows) == 3
    # an unreadable file is never removed
    (tmp_path / "tax_lien.json").write_text("{not json")
    with pytest.raises(L.LedgerUnreadable):
        led.save(now=T0)
    assert (tmp_path / "tax_lien.json").read_text() == "{not json"


# ----------------------------------------------------------------------------- two writers
def test_two_writers_merge_through_the_sweeps_save(tmp_path):
    sweep = _script("verification_sweep")
    _ledger(10).save(tmp_path / "tax_lien", now=T0)
    w1 = L.Ledger.load("tax_lien", tmp_path)
    w2 = L.Ledger.load("tax_lien", tmp_path)
    t1, t2 = T0 + timedelta(days=31), T0 + timedelta(days=32)
    w1.record(_row(1), _res("refuted", t1), ttl_days=30, now=t1)
    w1.record(_row(20), _res("confirmed", t1), ttl_days=30, now=t1)
    # tax_lien is address-scoped: one parcel, two house-numbered addresses, two writers
    w1.record(_row(40, "16 Sample Hill Dr", "900000000040"), _res("refuted", t1), ttl_days=30, now=t1)
    w2.record(_row(1), _res("confirmed", t2), ttl_days=30, now=t2)
    w2.record(_row(30), _res("confirmed", t2), ttl_days=30, now=t2)
    w2.record(_row(40, "18 Sample Hill Dr", "900000000040"), _res("confirmed", t2), ttl_days=30, now=t2)
    sweep._save(w1, "h1")
    sweep._save(w2, "h2")
    final = L.Ledger.load("tax_lien", tmp_path)
    assert len(final.rows) == 14                                   # 10 + 20 + 30 + two addresses
    e1 = final.find_row(_row(1))[1]
    assert e1["latest"]["verdict"] == "confirmed" and e1["latest"]["checked_at"] == core.iso_z(t2)
    assert "refuted" in [h["verdict"] for h in e1["history"]]
    assert final.find_row(_row(20))[1] and final.find_row(_row(30))[1]
    a16 = final.find_row(_row(40, "16 Sample Hill Dr", "900000000040"))[1]
    a18 = final.find_row(_row(40, "18 Sample Hill Dr", "900000000040"))[1]
    assert a16 is not a18
    assert (a16["latest"]["verdict"], a18["latest"]["verdict"]) == ("refuted", "confirmed")
    assert set(e1["keys"]) >= set(core.row_keys(_row(1)))                    # keys unioned


# ----------------------------------------------------------------------------- one shard per re-check
def test_a_recheck_rewrites_one_shard_and_leaves_the_others_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SHARD_TARGET_BYTES", 4096)
    led = _ledger(200)
    sd = led.save(tmp_path / "tax_lien", now=T0)
    m = json.loads((sd / "manifest.json").read_text())
    assert m["buckets"] >= 8
    before = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
              for p in sd.iterdir() if p.name != "manifest.json"}
    t1 = T0 + timedelta(days=31)
    again = L.Ledger.load("tax_lien", tmp_path)
    again.record(_row(5), _res("refuted", t1), ttl_days=30, now=t1)
    again.save(now=t1)
    key = again.find_row(_row(5))[0]
    target = L.shard_name(L.bucket_of(key, m["buckets"]))
    assert again.last_write["written"] == [target] and again.last_write["removed"] == []
    after = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
             for p in sd.iterdir() if p.name != "manifest.json"}
    changed = [n for n in before if before[n][2] != after[n][2]]
    untouched = [n for n in before if before[n][:2] == after[n][:2]]
    assert changed == [target] and len(untouched) == len(before) - 1
    m2 = json.loads((sd / "manifest.json").read_text())
    assert [s["sha256"] for s in m2["shards"] if s["file"] != target] == \
        [s["sha256"] for s in m["shards"] if s["file"] != target]
    # nothing changed: nothing but the manifest is rewritten
    same = L.Ledger.load("tax_lien", tmp_path)
    same.save(now=t1)
    assert same.last_write["written"] == []


# ----------------------------------------------------------------------------- the cap
def test_the_cap_is_8_mib_and_a_shard_that_would_pass_it_splits(tmp_path):
    assert L.SHARD_MAX_BYTES == 8 * 1024 * 1024 or os.environ.get("VERIFICATION_SHARD_MAX_BYTES")
    cap = 6000
    led = _ledger(20)
    sd = led.save(tmp_path / "tax_lien", now=T0, max_shard_bytes=cap)
    n0 = json.loads((sd / "manifest.json").read_text())["buckets"]
    for i in range(20, 120):
        led.record(_row(i), _res("confirmed", T0), ttl_days=30, now=T0)
    led.save(now=T0, max_shard_bytes=cap)
    m = json.loads((sd / "manifest.json").read_text())
    assert m["buckets"] > n0 and m["shard_max_bytes"] == cap
    assert all(s["bytes"] <= cap for s in m["shards"])
    assert all(p.stat().st_size <= cap for p in sd.iterdir() if p.name != "manifest.json")
    # a doubling splits a bucket in two: an entry stays in its bucket modulo the old count
    for s in m["shards"]:
        for k in json.loads((sd / s["file"]).read_text())["rows"]:
            assert L.bucket_of(k, m["buckets"]) % n0 == L.bucket_of(k, n0)
    assert _same(L.Ledger.load("tax_lien", tmp_path).rows, led.rows)
    # one entry bigger than the cap: its own shard, and the doubling stops
    big = L.Ledger("tax_lien")
    big.record(_row(1), _res("confirmed", T0, blob="x" * 9000), ttl_days=30, now=T0)
    big.record(_row(2), _res("confirmed", T0), ttl_days=30, now=T0)
    bd = big.save(tmp_path / "big" / "tax_lien", now=T0, max_shard_bytes=cap)
    mb = json.loads((bd / "manifest.json").read_text())
    assert sum(s["rows"] for s in mb["shards"]) == 2 and mb["buckets"] < L.MAX_BUCKETS


# ----------------------------------------------------------------------------- integrity
def _tamper(sd: Path) -> str:
    m = json.loads((sd / "manifest.json").read_text())
    name = m["shards"][0]["file"]
    p = sd / name
    text = p.read_text()
    assert '"total":' in text
    p.write_text(text.replace('"total":', '"total" :', 1))       # still valid JSON, other bytes
    return name


def test_a_manifest_hash_mismatch_is_detected(tmp_path):
    _ledger(30).save(tmp_path / "tax_lien", now=T0)
    sd = tmp_path / "tax_lien"
    name = _tamper(sd)
    with pytest.raises(L.LedgerUnreadable, match="sha256 mismatch"):
        L.Ledger.load("tax_lien", tmp_path)                     # a writer refuses it
    leds, bad = L.load_all(tmp_path)                            # the VM apply reads it, says so
    assert len(leds["tax_lien"].rows) == 30
    assert "sha256 mismatch" in bad[f"tax_lien/{name}"] and bad[f"tax_lien/{name}"].startswith("read anyway")
    assert any("sha256 differs" in i for i in L.check_layout(tmp_path)["tax_lien"]["issues"])
    # an unlisted shard is detected too
    (sd / "999.json").write_bytes((sd / name).read_bytes())
    assert "not listed" in L.load_all(tmp_path)[1]["tax_lien/999.json"]
    (sd / "999.json").unlink()
    # recover=True (the migration's re-seal) reads it; the re-written ledger is clean again
    led = L.Ledger.load("tax_lien", tmp_path, recover=True)
    led.save(sd, now=T0)
    assert L.Ledger.load("tax_lien", tmp_path).warnings == {}
    assert L.check_layout(tmp_path)["tax_lien"]["issues"] == []


def test_an_unreadable_shard_loads_the_rest_and_the_partial_ledger_refuses_to_save(tmp_path):
    _ledger(30).save(tmp_path / "tax_lien", now=T0, max_shard_bytes=2000)
    sd = tmp_path / "tax_lien"
    m = json.loads((sd / "manifest.json").read_text())
    assert len(m["shards"]) >= 2
    broken = m["shards"][0]
    (sd / broken["file"]).write_text("<<<<<<< conflict\n")
    leds, bad = L.load_all(tmp_path)
    assert len(leds["tax_lien"].rows) == 30 - broken["rows"]
    assert "not JSON" in bad[f"tax_lien/{broken['file']}"]
    with pytest.raises(L.LedgerUnreadable):
        L.Ledger.load("tax_lien", tmp_path)
    with pytest.raises(L.LedgerUnreadable, match="partly read"):
        leds["tax_lien"].save(now=T0)
    (sd / broken["file"]).unlink()                             # listed but missing
    assert "missing on disk" in L.load_all(tmp_path)[1][f"tax_lien/{broken['file']}"]


# ----------------------------------------------------------------------------- git hand-off
def _git(repo: Path, *args) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True,
                          env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    r = tmp_path / "r"
    d = r / "docs" / "handoff" / "verification"
    d.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    _git(r, "remote", "add", "origin", str(origin))
    _ledger(12).save(d / "tax_lien.json", now=T0)
    (r / "other.txt").write_text("one\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "one")
    _git(r, "push", "-q", "origin", "main")
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                 "HANDOFF_PUSH": "1", "VERIFY_GIT_RETRY_SLEEP": "0"}.items():
        monkeypatch.setenv(k, v)
    return r


def test_publish_commits_the_shards_and_the_removed_file_and_nothing_else(repo, monkeypatch):
    d = repo / "docs" / "handoff" / "verification"
    led = L.Ledger.load("tax_lien", d)
    led.record(_row(50), _res("confirmed", T0), ttl_days=30, now=T0)
    monkeypatch.setenv("VERIFICATION_LEDGER_LAYOUT", "shards")
    sd = led.save(now=T0)
    monkeypatch.delenv("VERIFICATION_LEDGER_LAYOUT")
    assert sd == d / "tax_lien" and not (d / "tax_lien.json").exists()
    (repo / "other.txt").write_text("two\n")                         # someone else's change
    (sd / ".000.json.99999.tmp").write_text("a writer's temp file")
    res, detail = L.publish_ledgers([sd], "verification hand-off: test", repo=repo)
    assert res == "pushed", detail
    names = _git(repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines()
    assert "D\tdocs/handoff/verification/tax_lien.json" in names
    assert "A\tdocs/handoff/verification/tax_lien/manifest.json" in names
    assert all("other.txt" not in n and ".tmp" not in n for n in names)
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/main")
    assert "other.txt" in _git(repo, "status", "--porcelain")          # still uncommitted
    # a later save that empties a bucket: the removed shard is committed as removed
    tracked = set(_git(repo, "ls-files", "docs/handoff/verification/tax_lien").splitlines())
    gone = sorted(t for t in tracked if t.endswith(".json") and not t.endswith("manifest.json"))[0]
    (repo / gone).unlink()
    rels = L.ledger_git_paths([sd], repo=repo)
    assert gone in rels and "docs/handoff/verification/tax_lien.json" not in rels


# ----------------------------------------------------------------------------- the readers
def test_gap_matrix_prerun_gate_and_quiet_title_read_the_shards(tmp_path):
    led = L.Ledger("jail_booking")
    led.rows["jail:x@parcel:NC:cleveland:9"] = {
        "keys": ["jail:x@parcel:NC:cleveland:9"], "row": {"state": "NC", "county": "cleveland"},
        "latest": {"verdict": "confirmed", "checked_at": core.iso_z(T0)}}
    led.save(tmp_path / "jail_booking", now=T0)
    gm = _script("gap_matrix")
    idx, counts = gm.load_ledger_index(tmp_path)
    assert idx["jail_booking"]["parcel:NC:cleveland:9"] == "confirmed"
    assert counts["jail_booking"] == {"NC|Cleveland|confirmed": 1}
    qt = _script("quiet_title_layups")
    assert qt.load("jail_booking", tmp_path).rows.keys() == led.rows.keys()
    assert qt.load("nope", tmp_path) is None

    G = _script("prerun_gate")
    r = tmp_path / "r"
    v = r / "docs" / "handoff" / "verification"
    _ledger(3).save(v / "tax_lien", now=T0)
    _ledger(2, signal="comps").save(v / "comps.json", now=T0)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "ledgers")
    profile = {"ledgers": {"dir": "docs/handoff/verification", "max_age_h": 36}}
    st, why = G.check_ledgers(r, profile, sweep_running=lambda: False)
    assert st == G.PASS and why.startswith("2 ledgers")


def test_the_audit_check_fails_a_single_file_past_the_limit_and_passes_shards(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_t_ls", REPO / "scripts" / "audit_checks" / "ledger_shards.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(L, "SHARD_MAX_BYTES", 3000)
    _ledger(30).save(tmp_path / "tax_lien.json", now=T0)
    c = mod.LedgerLayout(tmp_path)
    c.feed({})
    r = c.finish()                         # over the shard cap: advice, not a violation
    assert r["name"] == "ledger-layout" and r["ok"] and "ledger_migrate.py --apply" in r["detail"]
    monkeypatch.setattr(L, "FILE_MAX_BYTES", 5000)
    r = mod.LedgerLayout(tmp_path).finish()
    assert not r["ok"] and r["violations"] == 1 and "commit gate" in r["detail"]
    L.Ledger.load("tax_lien", tmp_path).save(tmp_path / "tax_lien", now=T0)
    (tmp_path / "tax_lien.json").unlink()
    r = mod.LedgerLayout(tmp_path).finish()
    assert r["ok"] and r["checked"] == 1 and r["violations"] == 0 and "advice" not in r["detail"]
    _tamper(tmp_path / "tax_lien")
    assert not mod.LedgerLayout(tmp_path).finish()["ok"]


# ----------------------------------------------------------------------------- the migration
def test_migrate_dry_run_apply_byte_identical_idempotent_and_locked(tmp_path, monkeypatch, capsys):
    mig = _script("ledger_migrate")
    monkeypatch.setattr(mig, "RUN_LOCK", tmp_path / "lock")
    d = tmp_path / "v"
    _ledger(80).save(d / "tax_lien.json", now=T0)
    _ledger(4, signal="comps").save(d / "comps.json", now=T0)
    original = (d / "tax_lien.json").read_bytes()

    assert mig.main(["--ledger-dir", str(d)]) == 0                       # dry run
    out = capsys.readouterr().out
    assert "byte-identical" in out and "nothing written" in out
    assert (d / "tax_lien.json").read_bytes() == original and not (d / "tax_lien").exists()

    with open(tmp_path / "lock", "a+") as fh:                           # a sweep holds the lock
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert mig.main(["--ledger-dir", str(d), "--apply"]) == 1
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert (d / "tax_lien.json").exists()

    assert mig.main(["--ledger-dir", str(d), "--apply"]) == 0
    assert not (d / "tax_lien.json").exists() and not (d / "comps.json").exists()
    on_disk = sorted(ln for p in sorted((d / "tax_lien").glob("[0-9]*.json"))
                     for ln in L.raw_row_lines(p.read_bytes()))
    assert on_disk == sorted(L.raw_row_lines(original))                  # byte for byte
    back = L.Ledger.load("tax_lien", d)
    assert back.generated_at == json.loads(original)["generated_at"]
    assert back.last_run == json.loads(original)["last_run"]
    snap = {p.name: p.read_bytes() for p in (d / "tax_lien").iterdir()}
    capsys.readouterr()
    assert mig.main(["--ledger-dir", str(d), "--apply"]) == 0              # idempotent
    assert "already sharded, clean" in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in (d / "tax_lien").iterdir()} == snap

    # a tampered shard: the dry run says so, --apply re-seals it
    _tamper(d / "tax_lien")
    assert mig.main(["--ledger-dir", str(d), "--signal", "tax_lien"]) == 1
    assert mig.main(["--ledger-dir", str(d), "--signal", "tax_lien", "--apply"]) == 0
    assert L.Ledger.load("tax_lien", d).warnings == {}
