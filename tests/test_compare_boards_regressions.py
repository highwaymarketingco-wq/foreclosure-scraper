"""scripts/compare_boards.py after the regressions audit (2026-10-09): a row whose primary source changed
is attribution, not loss; a short id that became a PIN between two boards is still one row.

The gated d42058b3 comparison held the publish on buncombe_delinquent_tax (1,182 -> 827),
multi_year_delinquent_tax (1,115 -> 436), kania (177 -> 150) and sc_catalis (63 -> 53) with 0 or 1
rows missing: every row was on the candidate under another merge base. It also reported 1,818 Lincoln
rows missing and 1,009 rows as having lost their comps that were all on the candidate under the PIN
(the fingerprint join paired different vacant lots of one owner on one road). Rows are invented."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import compare_boards as CB  # noqa: E402
from foreclosure_scraper import web_artifact as WA  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402


def _row(i: int, src: str, **over) -> dict:
    d = dict(source=src, source_url=f"https://example.test/{src}/{i}", listing_type="tax_lien", state="NC",
             county="Buncombe", parcel_id=f"96{i:08d}", street_address=f"{100 + i} TEST ST",
             owner_name=f"TEST OWNER {i:03d}",
             raw={"tax_owed": {"balance": 1000 + i, "year": 2025, "years_delinquent": 1},
                  "distress_stack": {"tier": "COLD", "signals": ["tax_lien"]}})
    raw = over.pop("raw", None)
    d.update(over)
    if raw:
        d["raw"].update(raw)
    return d


def _board(d: Path, rows: list[dict]) -> Path:
    WA.write_artifact([Listing.model_validate(r) for r in rows], {"notes": "fixture"}, docs_dir=d)
    return d


def _run(tmp: Path, base: Path, cand: Path) -> tuple[int, dict]:
    out = tmp / "cmp" / "report.json"
    (tmp / "no_checks").mkdir(parents=True, exist_ok=True)
    rc = CB.main(["--baseline", str(base), "--candidate", str(cand), "--out", str(out), "--no-ledger", "--no-accept-file",
                  "--checks-dir", str(tmp / "no_checks")])
    return rc, json.loads(out.read_text())


def test_a_source_whose_rows_moved_under_another_merge_base_is_not_lost(tmp_path):
    live = [_row(i, "counties_nc.test_roll") for i in range(120)] + [_row(500 + i, "counties_nc.other")
                                                                      for i in range(200)]
    cand = [dict(r) for r in live]
    for r in cand[:60]:                                   # half the roll now sits under another base
        r["source"] = "counties_nc.other"
    rc, rep = _run(tmp_path, _board(tmp_path / "base", live), _board(tmp_path / "cand", cand))
    names = {b["name"] for b in rep["blockers"]}
    assert "source:counties_nc.test_roll" not in names
    note = next(n for n in rep["notes"] if n["name"] == "relabeled:counties_nc.test_roll")
    assert "120 -> 60 rows under this primary source, but 120 of its rows" in note["detail"]
    assert rep["rows"]["missing_from_candidate"] == 0


def test_a_source_that_really_lost_rows_is_still_held(tmp_path):
    live = [_row(i, "counties_nc.test_roll") for i in range(120)]
    cand = [dict(r) for r in live[:90]]
    for r in cand[:30]:
        r["source"] = "counties_nc.other"                 # relabels do not hide a real loss
    rc, rep = _run(tmp_path, _board(tmp_path / "base", live), _board(tmp_path / "cand", cand))
    flagged = {s["source"]: s for s in rep["rows"]["sources_flagged"]}
    assert flagged["counties_nc.test_roll"]["held"] == 90 and flagged["counties_nc.test_roll"]["relabeled"] == 30
    assert rc == 1 and "source:counties_nc.test_roll" in {b["name"] for b in rep["blockers"]}


def test_a_short_id_that_became_a_pin_joins_on_the_source_id(tmp_path):
    def lot(i, pin):
        # an unnumbered vacant lot of one owner on one road: no address key, one fingerprint for all
        return _row(i, "counties_nc.lincoln_vacant", county="Lincoln", parcel_id=pin, street_address="TEST RD",
                    owner_name="TEST OWNER", source_url="https://example.test/lincoln", listing_type="distressed",
                    raw={"lincoln_vacant": {"PARCELID": f"{10000 + i}", "PIN": f"36{i:08d}"},
                         "comps": [{"sold_price": 50000 + i, "sold_date": "2026-01-01"}]})
    live = [lot(i, None) for i in range(150)]                                  # short id nulled: no parcel
    cand = [lot(i, f"36{i:08d}") for i in reversed(range(150))]                # the PIN now, another order
    rc, rep = _run(tmp_path, _board(tmp_path / "base", live), _board(tmp_path / "cand", cand))
    r = rep["rows"]
    assert r["matched"] == 150 and r["missing_from_candidate"] == 0
    assert r["matched_by_key"] == {"sid": 150}
    f = {x["field"]: x for x in rep["fields"]}
    assert f["comps"]["lost"] == 0 and f["comps"]["changed"] == 0          # each lot met its own row


def test_source_id_keys_are_county_qualified_and_skip_weak_ids():
    row = {"state": "NC", "county": "Madison",
           "raw": {"nc_ptscloud_delinquent_tax": {"parcel": "25261"}, "parcel_id_nulled": {"value": "25261"}}}
    assert CB.source_id_keys(row) == ["sid:NC:madison:25261"]
    assert CB.source_id_keys({**row, "county": None}) == []
    assert CB.source_id_keys({"state": "NC", "county": "Polk", "raw": {"parcel_id_nulled": {"value": "000"}}}) == []
    assert CB.join_keys(row)[0] == "sid:NC:madison:25261" and CB.join_keys(row)[-1].startswith("fp:")


def test_hot_warm_growth_without_the_value_is_not_a_regression_but_a_loss_on_rows_in_both_is(tmp_path):
    def hot(i, comps=True, tier="WARM"):
        raw = {"distress_stack": {"tier": tier, "signals": ["tax_lien"]}}
        if comps:
            raw["comps"] = [{"sold_price": 90000 + i, "sold_date": "2026-01-01"}]
        return _row(i, "counties_nc.test_roll", raw=raw)
    live = [hot(i) for i in range(300)] + [_row(1000 + i, "counties_nc.cold") for i in range(300)]
    # 300 COLD rows promoted to WARM without comps: the all-HOT+WARM share halves, nothing is lost
    grown = [hot(i) for i in range(300)] + [hot(1000 + i, comps=False) for i in range(300)]
    rc, rep = _run(tmp_path / "a", _board(tmp_path / "base", live), _board(tmp_path / "cand", grown))
    assert not any(b["name"].endswith(":comps") for b in rep["blockers"]), rep["blockers"]
    cov = next(r for r in rep["coverage"] if r["state"] == "ALL" and r["column"] == "comps")
    assert cov["count_hotwarm_both"] == [300, 300]
    # 30 of the rows HOT+WARM on both boards lose their comps: a regression on that lens
    lost = [hot(i, comps=i >= 30) for i in range(300)] + [_row(1000 + i, "counties_nc.cold") for i in range(300)]
    rc, rep = _run(tmp_path / "b", _board(tmp_path / "base2", live), _board(tmp_path / "cand2", lost))
    assert "ALL:comps" in {b["name"] for b in rep["blockers"]}


def test_an_accepted_drop_file_accepts_within_its_bound_only(tmp_path):
    live = [_row(i, "counties_nc.test_roll") for i in range(300)]
    cand = [dict(r, raw={**r["raw"], "tax_owed": None}) if i < 30 else r for i, r in enumerate(live)]
    base, cd = _board(tmp_path / "base", live), _board(tmp_path / "cand", cand)

    def run(entries, sub):
        f = tmp_path / f"{sub}.json"
        f.write_text(json.dumps({"entries": entries}))
        out = tmp_path / sub / "r.json"
        (tmp_path / "no_checks").mkdir(parents=True, exist_ok=True)
        CB.main(["--baseline", str(base), "--candidate", str(cd), "--out", str(out), "--no-ledger",
                 "--checks-dir", str(tmp_path / "no_checks"), "--accept-file", str(f)])
        rep = json.loads(out.read_text())
        return {b["name"] for b in rep["blockers"]}, {n["name"]: n for n in rep["notes"]}
    entry = {"kind": "field", "name": "tax_balance", "reason": "scrubbed copies (test)"}
    blockers, notes = run([{**entry, "max_loss": 40}], "ok")
    assert "lost:tax_balance" not in blockers and "scrubbed copies" in notes["lost:tax_balance"]["why_not_blocking"]
    blockers, _ = run([{**entry, "max_loss": 10}], "over")                 # 30 lost > the bound
    assert "lost:tax_balance" in blockers
    blockers, _ = run([{"kind": "field", "name": "tax_balance", "max_loss": 40}], "noreason")
    assert "lost:tax_balance" in blockers                                  # no reason, no acceptance
