"""scripts/compare_boards.py: compare a candidate board with the live one before it replaces it.

Every board here is made up (TEST OWNER nnn, example.test, 555-2xxx numbers). Boards are written
with the real writers (web_artifact.write_artifact into a scratch docs dir, checkpoint.save_pre_publish
into a scratch checkpoint dir) so the readers the tool uses are the production ones.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import compare_boards as CB  # noqa: E402
from foreclosure_scraper import checkpoint as CK  # noqa: E402
from foreclosure_scraper import web_artifact as WA  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402

N_A, N_B, N_C = 400, 120, 80          # three sources, 600 rows: every lens has >= LENS_MIN_ROWS


def _row(i: int, src: str, **over) -> dict:
    tier = "HOT" if i % 50 == 0 else ("WARM" if i % 2 == 0 else "COLD")
    sigs = ["tax_lien"] + (["probate"] if i % 5 == 0 else []) + (["lis_pendens"] if tier == "HOT" else [])
    d = dict(
        source=src, source_url=f"https://example.test/{src}/{i}", listing_type="tax_lien",
        state="NC" if i % 4 else "SC", county="Buncombe" if i % 4 else "Greenville",
        parcel_id=f"96{i:08d}", street_address=f"{100 + i} TEST ST", owner_name=f"TEST OWNER {i:03d}",
        assessed_value=150000 + i, living_sqft=1200,
        raw={
            "owner_phone": {"phone": f"82855520{i % 100:02d}", "source": "test"},
            "owner_email": {"best_email": f"owner{i}@example.test"},
            "owner_mailing": {"mailing": f"PO BOX {i} TESTVILLE NC 28801"},
            "tax_owed": {"balance": 1000 + i, "year": 2024, "years_delinquent": 2},
            "comps": [{"sold_price": 200000 + i, "sold_date": "2026-01-01", "match_quality": "sqft+beds"}],
            "distress_stack": {"tier": tier, "signals": sigs, "stack": len(sigs), "categories": ["tax"]},
        },
    )
    raw_over = over.pop("raw", None)
    d.update(over)
    if raw_over:
        d["raw"].update(raw_over)
    return d


def _rows() -> list[dict]:
    out = []
    for i in range(N_A):
        out.append(_row(i, "counties_nc.test_a"))
    for i in range(N_A, N_A + N_B):
        out.append(_row(i, "counties_nc.test_b"))
    for i in range(N_A + N_B, N_A + N_B + N_C):
        out.append(_row(i, "counties_sc.test_c"))
    return out


def _write_board(d: Path, rows: list[dict]) -> Path:
    WA.write_artifact([Listing.model_validate(r) for r in rows], {"notes": "fixture"}, docs_dir=d)
    return d


def _write_checkpoint(d: Path, rows: list[dict], monkeypatch, phase: str = CK.PRE_PUBLISH) -> Path:
    monkeypatch.setattr(CK, "CHECKPOINT_DIR", d)
    lis = [Listing.model_validate(r) for r in rows]
    if phase == CK.PRE_PUBLISH:
        st = SimpleNamespace(enriched=lis, enrichment_stats={"distress_stack": {"HOT": 1}}, errors=[],
                             scoring_failed=None, write_sold_pool=False, write_run_health=False,
                             export_and_email=False)
        assert CK.save_pre_publish(st, {"total": len(lis), "by_source": {}, "code_pin": "abc1234",
                                        "run_env": {"FORECLOSURE_ROD_CHAIN": "1", "GMAIL_APP_PASSWORD": "x"}})
    else:
        assert CK.save(lis, phase)
    return d


def _run(tmp: Path, base: Path, cand: Path, *extra: str) -> tuple[int, dict]:
    """compare_boards on two fixture boards. The audit checks are the repo's own unless a test names
    a --checks-dir; by default an empty one, so other areas' checks do not move these verdicts."""
    out = tmp / "cmp" / "report.json"
    if "--checks-dir" not in extra:
        (tmp / "no_checks").mkdir(exist_ok=True)
        extra = (*extra, "--checks-dir", str(tmp / "no_checks"))
    rc = CB.main(["--baseline", str(base), "--candidate", str(cand), "--out", str(out), "--no-ledger",
                  "--no-accept-file", *extra])
    return rc, json.loads(out.read_text())


@pytest.fixture(scope="module")
def base_dir(tmp_path_factory) -> Path:
    return _write_board(tmp_path_factory.mktemp("base") / "docs", _rows())


def _names(items) -> set[str]:
    return {x["name"] for x in items}


# ------------------------------------------------------------------------------------------ PASS
def test_identical_boards_pass_with_nothing_lost(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", _rows())
    rc, rep = _run(tmp_path, base_dir, cand)
    assert rc == 0 and rep["verdict"] == "PASS", (rep["blockers"], rep["notes"])
    r = rep["rows"]
    assert r["matched"] == r["baseline_total"] == r["candidate_total"] == 600
    assert r["missing_from_candidate"] == 0 and r["new_in_candidate"] == 0
    assert all(f["lost"] == 0 and f["changed"] == 0 for f in rep["fields"])
    assert rep["best_of_both"]["total"] == 0
    assert all(c["class"] == "flat" for c in rep["coverage"])
    assert rep["tiers"]["baseline"] == rep["tiers"]["candidate"]
    assert rep["publish_safety"]["candidate"]["problems"] == []


def test_a_checkpoint_candidate_reads_like_the_board_it_would_publish(tmp_path, base_dir, monkeypatch):
    ck = _write_checkpoint(tmp_path / "ckpt", _rows(), monkeypatch)
    rc, rep = _run(tmp_path, base_dir, ck)
    assert rep["candidate"]["kind"] == "checkpoint"
    assert rep["rows"]["matched"] == 600 and rep["rows"]["missing_from_candidate"] == 0
    assert all(f["lost"] == 0 and f["changed"] == 0 for f in rep["fields"]), rep["fields"]
    est = rep["publish_safety"]["candidate"]["estimate"]
    assert est["rows"] == 600 and min(est["bytes"].values()) > 0
    assert rep["verdict"] in ("PASS", "PASS_WITH_NOTES") and rc == 0, rep["blockers"]
    p = rep["process"]["candidate"]
    assert p["code_pin"] == "abc1234" and p["run_env"] == {"FORECLOSURE_ROD_CHAIN": "1"}


# ------------------------------------------------------------------------------------------ 1 rows
def test_rows_missing_by_source_and_reason_and_new_rows(tmp_path, base_dir):
    rows = _rows()
    old = (datetime.utcnow() - timedelta(days=800)).isoformat()
    cand = [r for r in rows if r["source"] != "counties_nc.test_b"]          # a source gone (120 rows)
    cand = [r for r in cand if not (r["source"] == "counties_sc.test_c" and int(r["parcel_id"][2:]) % 10 == 0)]
    cand += [_row(9000 + k, "counties_nc.test_new", raw={"owner_phone": None}) for k in range(30)]
    base_rows = [dict(r) for r in rows]
    # a terminal row (sale over a year ago) in the baseline that the candidate no longer has
    base_rows[1] = {**base_rows[1], "sale_date": old}
    cand = [r for r in cand if r["parcel_id"] != base_rows[1]["parcel_id"]]
    # a folded row: a baseline twin (no parcel, same numbered address, other source) the candidate merged
    twin = _row(3, "counties_nc.test_twin", parcel_id=None)
    base_rows.append(twin)
    base = _write_board(tmp_path / "base2", base_rows)
    candd = _write_board(tmp_path / "cand", cand)
    rc, rep = _run(tmp_path, base, candd)
    r = rep["rows"]
    assert r["missing_by_source_and_reason"]["counties_nc.test_b"] == {"source_gone_from_candidate": 120}
    assert r["missing_by_reason"]["aged_out_terminal"] == 1
    assert r["missing_by_reason"]["folded_into_another_row"] == 1
    assert r["missing_by_source_and_reason"]["counties_sc.test_c"] == {"unexplained": 8}
    assert r["new_by_source"] == {"counties_nc.test_new": 30}
    flagged = {s["source"]: s for s in r["sources_flagged"]}
    assert flagged["counties_nc.test_b"]["candidate"] == 0
    assert "counties_sc.test_c" not in flagged                     # 72 of 80 = 90%: not under the line
    assert "source:counties_nc.test_b" in _names(rep["blockers"])
    assert rc == 1 and rep["verdict"] == "HOLD"
    assert len(r["samples"]["unexplained"]) <= CB.SAMPLE_IDS


def test_an_accepted_source_drop_is_a_note(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", [r for r in _rows() if r["source"] != "counties_sc.test_c"])
    rc, rep = _run(tmp_path, base_dir, cand, "--accept-source-drop", "counties_sc.*")
    assert "source:counties_sc.test_c" in _names(rep["notes"])
    assert "source:counties_sc.test_c" not in _names(rep["blockers"])


# ------------------------------------------------------------------------------------------ 2 coverage
def test_growth_with_sparse_rows_is_dilution_not_regression(tmp_path, base_dir):
    sparse = [_row(5000 + k, "counties_nc.test_new", raw={"owner_phone": None, "owner_email": None})
              for k in range(300)]
    cand = _write_board(tmp_path / "cand", _rows() + sparse)
    rc, rep = _run(tmp_path, base_dir, cand)
    phone = next(c for c in rep["coverage"] if c["state"] == "ALL" and c["column"] == "phone")
    assert phone["count"] == [600, 600]
    assert phone["share_all"][1] < phone["share_all"][0] - 1        # 100% -> 66.7% of all rows
    assert phone["share_both"] == [100.0, 100.0]
    owner = next(c for c in rep["coverage"] if c["state"] == "ALL" and c["column"] == "owner_name")
    assert owner["class"] == "improved" or owner["class"] == "dilution"
    assert not [b for b in rep["blockers"] if b["section"] == "coverage"]
    hw = phone["share_hotwarm"]
    assert hw[1] < hw[0] - 1 and phone["class"] == "flat"           # diluted on HOT+WARM too, nothing lost


def test_a_like_for_like_loss_is_a_regression(tmp_path, base_dir):
    rows = _rows()
    for r in rows[:60]:                       # 10% of rows in both lose their phone
        r["raw"]["owner_phone"] = None
    cand = _write_board(tmp_path / "cand", rows)
    rc, rep = _run(tmp_path, base_dir, cand)
    phone = next(c for c in rep["coverage"] if c["state"] == "ALL" and c["column"] == "phone")
    assert phone["class"] == "regression" and phone["share_both"] == [100.0, 90.0]
    assert "ALL:phone" in _names(rep["blockers"])
    rc2, rep2 = _run(tmp_path, base_dir, cand, "--accept-coverage-drop", "phone", "--accept-field-loss", "phone")
    assert "ALL:phone" in _names(rep2["notes"]) and "ALL:phone" not in _names(rep2["blockers"])


# ------------------------------------------------------------------------------------------ 3 fields
def test_lost_and_changed_are_split_with_capped_samples(tmp_path, base_dir):
    rows = _rows()
    for r in rows[:40]:
        r["owner_name"] = r["owner_name"] + " JR"              # changed
    for r in rows[100:140]:
        r["raw"]["tax_owed"] = None                            # lost balance + years
    for r in rows[200:205]:
        r["raw"]["distress_stack"]["signals"] = [s for s in r["raw"]["distress_stack"]["signals"] if s != "tax_lien"]
    cand = _write_board(tmp_path / "cand", rows)
    out = tmp_path / "cmp" / "report.json"
    (tmp_path / "no_checks").mkdir()
    rc = CB.main(["--baseline", str(base_dir), "--candidate", str(cand), "--out", str(out), "--no-ledger",
                  "--checks-dir", str(tmp_path / "no_checks")])
    rep = json.loads(out.read_text())
    f = {x["field"]: x for x in rep["fields"]}
    assert f["owner_name"]["changed"] == 40 and f["owner_name"]["lost"] == 0
    assert f["tax_balance"]["lost"] == 40 and f["tax_years"]["lost"] == 40
    assert len(f["owner_name"]["sample_changed"]) == CB.SAMPLE_IDS
    assert all(s.startswith(("NC|", "SC|")) for s in f["tax_balance"]["sample_lost"])
    sig = {x["signal"]: x for x in rep["signals"]}
    assert sig["tax_lien"]["lost"] == 5
    best = [json.loads(line) for line in (tmp_path / "cmp" / "report.best_of_both.jsonl").read_text().splitlines()]
    assert sum(1 for b in best if b["field"] == "tax_balance") == 40
    assert rep["best_of_both"]["lost_good_values_by_field"]["tax_balance"] == 40
    assert "lost:tax_balance" in _names(rep["blockers"])           # 40 of 600 = 6.7% > 1%
    assert "changed:owner_name" in _names(rep["notes"])            # 40 of 600 = 6.7% > 5%
    assert "ALL:sig:tax_lien" in _names(rep["notes"])              # a signal drop is a note, never a blocker
    assert not [b for b in rep["blockers"] if b["name"].endswith("sig:tax_lien")]
    assert rc == 1


# ------------------------------------------------------------------------------------------ 4 tiers
def test_tier_transitions_and_hot_movement(tmp_path, base_dir):
    rows = _rows()
    hot = [r for r in rows if r["raw"]["distress_stack"]["tier"] == "HOT"]
    hot[0]["raw"]["distress_stack"].update(tier="WARM", signals=["tax_lien"])        # HOT -> WARM, lost lis_pendens
    rows[1]["raw"]["distress_stack"].update(tier="HOT", signals=["tax_lien", "probate"])   # COLD -> HOT
    gone = hot[1]["parcel_id"]
    rows = [r for r in rows if r["parcel_id"] != gone]                                # a HOT row leaves
    rows.append(_row(7000, "counties_nc.test_a"))                                     # new HOT row (7000 % 50 == 0)
    cand = _write_board(tmp_path / "cand", rows)
    rc, rep = _run(tmp_path, base_dir, cand)
    t = rep["tiers"]
    assert t["transitions"]["HOT->WARM"] == 1 and t["transitions"]["COLD->HOT"] == 1
    assert t["transitions"]["HOT->left"] == 1 and t["transitions"]["new->HOT"] == 1
    assert t["hot_left_tier"]["signals_lost"] == {"lis_pendens": 1, "probate": 1}
    assert t["hot_entered"]["signals_gained"] == {"probate": 1}
    assert t["hot_left_board"]["rows"] == 1


# ------------------------------------------------------------------------------------------ 5 invariants
CHECK_SRC = '''
class _C:
    name = "fixture-no-bad-owner"
    def __init__(self): self.n = 0; self.bad = 0
    def feed(self, row):
        self.n += 1
        if "BAD" in str(row.get("owner_name") or ""): self.bad += 1
    def finish(self):
        return {"name": self.name, "checked": self.n, "violations": self.bad, "max_violations": 0,
                "ok": self.bad == 0, "detail": ""}
def make_checks():
    return [_C()]
'''


def test_audit_checks_run_on_both_boards_and_a_new_breach_holds(tmp_path, base_dir):
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "fixture.py").write_text(CHECK_SRC)
    rows = _rows()
    rows[5]["owner_name"] = "BAD NAME"
    cand = _write_board(tmp_path / "cand", rows)
    rc, rep = _run(tmp_path, base_dir, cand, "--checks-dir", str(checks))
    a = {x["name"]: x for x in rep["invariants"]["audit"]}
    assert a["fixture-no-bad-owner"]["baseline_violations"] == 0
    assert a["fixture-no-bad-owner"]["candidate_violations"] == 1
    assert "audit:fixture-no-bad-owner" in _names(rep["blockers"])
    assert rep["invariants"]["selfcheck"] and all(i["candidate_ok"] for i in rep["invariants"]["selfcheck"])


def test_absent_audit_checks_are_skipped_with_a_note(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", _rows())
    rc, rep = _run(tmp_path, base_dir, cand, "--checks-dir", str(tmp_path / "none"))
    assert rep["invariants"]["audit"] is None and "skipped" in rep["invariants"]["audit_note"]
    assert rc == 0


# ------------------------------------------------------------------------------------------ 6 publish safety
def test_heir_rule_violations_hold_the_publish(tmp_path, base_dir):
    rows = _rows()
    rows[7]["raw"]["heir_candidates"] = [
        {"name": "TEST HEIR ONE", "relation": "grandchild", "source_kind": "obituary_survivor",
         "source_url": "https://example.test/o/1", "source_date": "2026-01-01", "label": "candidate"},
        {"name": "TEST HEIR TWO", "relation": "son", "source_kind": "obituary_survivor", "phone": "828-555-2999",
         "source_url": "https://example.test/o/1", "source_date": "2026-01-01", "label": "candidate"},
        {"name": "TEST HEIR THREE", "relation": "daughter", "source_kind": "obituary_survivor", "minor": True,
         "source_url": "https://example.test/o/1", "source_date": "2026-01-01", "label": "candidate"},
        {"name": "TEST HEIR FOUR", "relation": "spouse", "source_kind": "obituary_survivor",
         "source_url": "https://example.test/o/1", "source_date": "2026-01-01", "label": "candidate"},
    ]
    rows[8]["raw"]["heir_estate"] = {"owner_of_record": "TEST OWNER", "heir_names": ["TEST HEIR FIVE"]}
    cand = _write_board(tmp_path / "cand", rows)
    rc, rep = _run(tmp_path, base_dir, cand)
    v = rep["publish_safety"]["heir"]["candidate"]["violations"]
    assert v["heir_relation_not_publishable"] == 1
    assert v["heir_contact_age_or_minor_field"] == 2 and v["heir_minor"] == 1
    assert "heir_publishing_rule" in _names(rep["blockers"]) and rc == 1
    assert "heir_note:rows_with_heir_estate.heir_names" in _names(rep["notes"])
    # the report never carries the names it found
    text = (tmp_path / "cmp" / "report.json").read_text() + (tmp_path / "cmp" / "report.md").read_text()
    assert "TEST HEIR" not in text and "828-555-2999" not in text


def test_a_torn_part_set_is_a_publish_blocker(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", _rows())
    part = sorted(cand.glob("listings_part_*.json.gz"))[0]
    data = gzip.decompress(part.read_bytes())
    part.write_bytes(gzip.compress(data.replace(b"TEST OWNER 001", b"TEST OWNER 00X"), mtime=0))
    rc, rep = _run(tmp_path, base_dir, cand)
    assert rc == 1
    assert "candidate_unreadable" in _names(rep["blockers"]) or any(
        "sha256" in b["detail"] or "size" in b["detail"] for b in rep["blockers"])


def test_a_misaligned_sidecar_is_a_publish_blocker(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", _rows())
    other = _write_board(tmp_path / "other", _rows()[:10])
    (cand / "listings_detail.json.gz").write_bytes((other / "listings_detail.json.gz").read_bytes())
    rc, rep = _run(tmp_path, base_dir, cand)
    assert rc == 1 and any(b["section"] == "publish_safety" for b in rep["blockers"])


def test_an_unscored_checkpoint_is_not_publishable(tmp_path, base_dir, monkeypatch):
    rows = _rows()
    for r in rows:
        r["raw"].pop("distress_stack")
    ck = _write_checkpoint(tmp_path / "ckpt", rows, monkeypatch, phase="dot_ocr")
    rc, rep = _run(tmp_path, base_dir, ck)
    names = _names(rep["blockers"])
    assert "unscored_rows" in names
    assert any("not 'pre_publish'" in b["detail"] for b in rep["blockers"])
    assert rc == 1


# ------------------------------------------------------------------------------------------ 7 process
LOG = """==> VM run 20261008T014033  role=vm  vision=gemini  stop_before_publish=1  log=/x.log  mem=/x.mem.log
==> code at d42058b3 (pinned)
==> stealth hand-off: 2ad11c42 2026-10-07 07:31:02 -0400 (14h old)
{"scrapers": 225, "event": "orchestrator.start", "level": "info", "timestamp": "2026-10-08T01:56:31Z"}
{"count": 312565, "pruned": 3564, "event": "orchestrator.in_scope", "level": "info", "timestamp": "2026-10-08T02:32:07Z"}
{"phase": "link_validation", "leads": 389122, "seconds": 184.7, "event": "checkpoint.saved", "level": "info", "timestamp": "2026-10-08T03:00:18Z"}
{"fresh_count": 10, "aged_out_terminal": 13, "aged_out_misses": 422, "sample": [["src", "123", "1 SECRET ST", "2 SECRET ST"]], "event": "board_persist.done", "level": "info", "timestamp": "2026-10-08T03:10:00Z"}
{"dropped": 3767, "event": "orchestrator.drop_countyless_national", "level": "info", "timestamp": "2026-10-08T10:09:28Z"}
{"phase": "lrcpwa_parcel", "budget_s": 900, "event": "enrich.time_capped", "level": "warning", "timestamp": "2026-10-08T04:04:30Z"}
{"phase": "dot_ocr", "leads": 383373, "seconds": 189.2, "event": "checkpoint.saved", "level": "info", "timestamp": "2026-10-08T17:34:08Z"}
{"traceback": "1 SECRET ST", "event": "owner_mailing.failed", "level": "error", "timestamp": "2026-10-08T17:40:00Z"}
==> exit=0  elapsed=1100m  Wed Oct  8 20:00:00 UTC 2026
"""
MEMLOG = """# watching pid 1: kill at tree rss+swap > 25600 MB, or MemAvailable < 700 MB with SwapFree < 400 MB
1791424588 rss_mb=28 swap_mb=0 pss_mb=26 swappss_mb=0 avail_mb=23274 swapfree_mb=4007 procs=1
1791492934 rss_mb=23816 swap_mb=100 pss_mb=13812 swappss_mb=0 avail_mb=9833 swapfree_mb=4009 procs=2
"""


def test_process_facts_from_the_run_log_are_numbers_and_identifiers_only(tmp_path, base_dir):
    (tmp_path / "run.log").write_text(LOG)
    (tmp_path / "run.mem.log").write_text(MEMLOG)
    cand = _write_board(tmp_path / "cand", _rows())
    rc, rep = _run(tmp_path, base_dir, cand, "--candidate-log", str(tmp_path / "run.log"),
                   "--candidate-memlog", str(tmp_path / "run.mem.log"))
    p = rep["process"]["candidate"]
    assert p["code_pin"] == "d42058b3" and p["log"]["header"]["pinned"] is True
    assert p["named_filters"]["drop_countyless_national"] == 3767
    assert p["named_filters"]["merge_prior_board aged_out_misses"] == 422
    assert p["named_filters"]["in_scope (footprint)"] == 3564
    assert [x["to"] for x in p["phase_seconds"]] == ["link_validation", "dot_ocr", "end"]
    assert p["peak_mem_mb"] == 23916 and p["mem"]["kill_total_mb"] == 25600
    assert p["log"]["failed_events"] == {"owner_mailing.failed": 1}
    assert any("time cap" in x for x in rep["process"]["flags"]["candidate"])
    assert any("kill line" in x for x in rep["process"]["flags"]["candidate"])
    assert "commit pin" not in " ".join(p["not_recorded"])
    assert "SECRET" not in (tmp_path / "cmp" / "report.json").read_text()
    assert rep["process"]["baseline"]["code_pin"] is None
    assert any("commit pin" in x for x in rep["process"]["should_record"])


# ------------------------------------------------------------------------------------------ 8 verdict
def test_a_worse_candidate_holds_and_names_each_blocker(tmp_path, base_dir):
    rows = [r for r in _rows() if r["source"] != "counties_nc.test_b"]
    for r in rows[:50]:
        r["parcel_id"] = None
        r["raw"]["owner_phone"] = None
    rows[3]["raw"]["heir_candidates"] = [{"name": "TEST HEIR SIX", "relation": "niece", "source_kind": "obituary_survivor",
                                          "source_url": None, "source_date": None, "label": "candidate"}]
    cand = _write_board(tmp_path / "cand", rows)
    rc, rep = _run(tmp_path, base_dir, cand)
    names = _names(rep["blockers"])
    assert rc == 1 and rep["verdict"] == "HOLD"
    assert {"source:counties_nc.test_b", "total_rows", "lost:phone", "lost:parcel_id",
            "heir_publishing_rule"} <= names
    for b in rep["blockers"]:
        assert b["threshold"]
    md = (tmp_path / "cmp" / "report.md").read_text()
    assert "## Verdict: HOLD" in md and "Threshold:" in md
    assert rep["best_of_both"]["lost_good_values_by_field"]["phone"] == 50


def test_ledger_record_and_changelog_append_never_rewrite(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", _rows() + [_row(8000 + k, "counties_nc.test_new") for k in range(40)])
    ledger = tmp_path / "board_versions"
    ledger.mkdir()
    head = "# Board versions\n\n## 2026-10-07 board vs 2026-10-01 board\nexisting entry text\n"
    (ledger / "CHANGELOG.md").write_text(head)
    (tmp_path / "no_checks").mkdir()
    args = ["--baseline", str(base_dir), "--candidate", str(cand), "--label", "fixture run",
            "--ledger-dir", str(ledger), "--append-changelog", "--date", "2026-10-09",
            "--checks-dir", str(tmp_path / "no_checks")]
    assert CB.main([*args, "--out", str(tmp_path / "a.json")]) == 0
    assert CB.main([*args, "--out", str(tmp_path / "b.json")]) == 0
    recs = sorted(p.name for p in ledger.glob("*.json"))
    assert recs == ["2026-10-09_fixture_run.json", "2026-10-09_fixture_run_2.json"]
    rec = json.loads((ledger / recs[0]).read_text())
    assert rec["rows"]["new_in_candidate"] == 40 and rec["coverage"]["phone"]["count"] == [600, 640]
    text = (ledger / "CHANGELOG.md").read_text()
    assert text.startswith(head)
    for part in ("Improved:", "Flat:", "Looked like regressions but are dilution or rows leaving:",
                 "Real regressions:", "Defects found later:"):
        assert text.count(part) == 2
    assert "phone 600 -> 640" in text


def test_row_ref_is_a_parcel_id_or_an_opaque_hash():
    r = _row(1, "counties_nc.test_a")
    assert CB.row_ref(r) == "NC|Buncombe|9600000001"
    r2 = dict(r, parcel_id=None)
    ref = CB.row_ref(r2)
    assert ref.startswith("h:") and len(ref) == 18 and "TEST" not in ref
    assert CB.row_ref(r2) == ref


def test_a_row_that_lost_its_only_parcel_key_still_joins_on_its_fingerprint(tmp_path):
    rows = [_row(i, "counties_nc.test_a", street_address=None) for i in range(300)]
    base = _write_board(tmp_path / "base", rows)
    cand_rows = [dict(r) for r in rows]
    for r in cand_rows[:10]:
        r["parcel_id"] = None
    cand = _write_board(tmp_path / "cand", cand_rows)
    rc, rep = _run(tmp_path, base, cand)
    assert rep["rows"]["matched"] == 300 and rep["rows"]["missing_from_candidate"] == 0
    assert rep["rows"]["matched_by_key"] == {"parcel": 290, "fp": 10}
    f = {x["field"]: x for x in rep["fields"]}
    assert f["parcel_id"]["lost"] == 10


def test_from_report_writes_the_ledger_and_changelog_without_a_pass(tmp_path, base_dir):
    cand = _write_board(tmp_path / "cand", _rows())
    rc, rep = _run(tmp_path, base_dir, cand, "--label", "vm_run")
    ledger = tmp_path / "bv"
    rc2 = CB.main(["--from-report", str(tmp_path / "cmp" / "report.json"), "--ledger-dir", str(ledger),
                   "--append-changelog", "--date", "2026-10-09", "--md", str(tmp_path / "again.md")])
    assert rc2 == rc == 0
    assert (ledger / "2026-10-09_vm_run.json").is_file()
    assert "## " in (ledger / "CHANGELOG.md").read_text() and (tmp_path / "again.md").is_file()


def test_the_version_compare_audit_checks_follow_the_interface():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vc_checks", REPO / "scripts" / "audit_checks" / "version_compare.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    checks = {c.name: c for c in mod.make_checks()}
    rows = [_row(i, "counties_nc.test_a") for i in range(10)]
    rows[0]["raw"]["heir_candidates"] = [{"name": "TEST HEIR SEVEN", "relation": "nephew", "source_kind": "x",
                                          "source_url": None, "source_date": None, "label": "candidate"}]
    rows[1].update(parcel_id=None, street_address=None, case_number=None)
    for r in rows:
        for c in checks.values():
            c.feed(r)
    heir = checks["version-heir-publishing-rule"].finish()
    assert heir["violations"] == 1 and heir["max_violations"] == 0 and not heir["ok"]
    assert "TEST HEIR" not in heir["detail"]
    ident = checks["version-join-identity"].finish()
    assert ident["violations"] == 1 and ident["checked"] == 10
    for res in (heir, ident):
        assert set(res) == {"name", "checked", "violations", "max_violations", "ok", "detail"}


def test_a_fused_parcel_key_is_never_a_join_key(tmp_path):
    rows = [_row(i, "counties_nc.test_a") for i in range(300)]
    for r in rows[:6]:
        r["parcel_id"] = "9999999999"            # one placeholder parcel on six different addresses
    base = _write_board(tmp_path / "base", rows)
    cand = _write_board(tmp_path / "cand", list(reversed(rows)))
    rc, rep = _run(tmp_path, base, cand)
    assert rep["rows"]["fused_keys_not_used_for_matching"] == 1
    assert rep["rows"]["matched"] == 300
    f = {x["field"]: x for x in rep["fields"]}
    assert f["street_address"]["changed"] == 0 and f["owner_name"]["changed"] == 0
