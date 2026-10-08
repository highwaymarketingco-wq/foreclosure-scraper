"""scripts/audit_checks/pipeline.py: the pipeline invariants (audit 2026-10-09, pipeline_gate).

Made-up rows only. Each test builds the defect the check exists for and a clean twin."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("audit_checks_pipeline",
                                               REPO / "scripts" / "audit_checks" / "pipeline.py")
P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P)


def _run(check, rows):
    for r in rows:
        check.feed(r)
    return check.finish()


def test_interface_shape():
    for c in P.make_checks():
        res = c.finish()
        assert set(res) >= {"name", "checked", "violations", "max_violations", "ok", "detail"}
        assert res["name"].startswith("pipeline-") and res["name"] == res["name"].lower()


def test_verified_source_matches_tax_binding():
    from foreclosure_scraper.tax_binding import VERIFIED_SOURCE
    assert P.VERIFIED_SOURCE == VERIFIED_SOURCE


def test_equity_ratios_match_the_equity_engine():
    """The check restates enrichment_equity's assessed-value ratios; pin them to the code."""
    import inspect
    from foreclosure_scraper import enrichment_equity
    src = inspect.getsource(enrichment_equity._payoff)
    assert "assessed_value) * 0.70" in src and "assessed_value) * 0.60" in src


def test_row_scored():
    rows = [{"parcel_id": "1", "raw": {"distress_stack": {"tier": "WARM"}}},
            {"parcel_id": "2", "raw": {}},
            {"parcel_id": "3", "raw": {"distress_stack": {"tier": "COLD", "score_error": "x"}}},
            {"parcel_id": "4", "raw": {"distress_stack": {"tier": "LUKEWARM"}}},
            {"parcel_id": "5", "raw": {"sold_confirmed": True}}]          # unscored by design
    res = _run(P.RowScored(), rows)
    assert (res["checked"], res["violations"], res["ok"]) == (4, 3, False)


def test_row_valued():
    res = _run(P.RowValued(), [{"raw": {"calc": {}, "grade": {}}}, {"raw": {"calc": {}}}, {"raw": {}}])
    assert (res["checked"], res["violations"]) == (3, 2)


def _eq_row(av, aged, payoff, src="assessed_value_estimate", ao=None):
    raw = {"equity": {"payoff_estimate": payoff, "payoff_source": src}}
    if aged:
        raw["tax_aging_high"] = True
    if ao is not None:
        raw["amount_owed"] = ao
    return {"parcel_id": "P1", "county": "Polk", "assessed_value": av, "raw": raw}


def test_equity_tax_inputs_catches_a_late_tax_aging_change():
    """restore_verified_tax sets tax_aging_high after enrich_equity used the 0.60 ratio."""
    ok = _eq_row(100_000, False, 60_000)
    late = _eq_row(100_000, True, 60_000)            # equity used 0.60, the row now says aged
    ok_aged = _eq_row(100_000, True, 70_000)
    res = _run(P.EquityTaxInputs(), [ok, late, ok_aged])
    assert (res["checked"], res["violations"]) == (3, 1)
    assert "aging ratio flipped" in res["detail"]


def test_equity_tax_inputs_amount_owed_payoff():
    good = _eq_row(0, False, 12_300, src="amount_owed:tax_owed", ao={"source": "tax_owed", "value": 12_345})
    gone = _eq_row(0, False, 12_300, src="amount_owed:tax_owed")
    moved = _eq_row(0, False, 12_300, src="amount_owed:tax_owed", ao={"source": "tax_owed", "value": 2_000})
    resrc = _eq_row(0, False, 12_300, src="amount_owed:tax_owed", ao={"source": "judgment", "value": 12_300})
    res = _run(P.EquityTaxInputs(), [good, gone, moved, resrc])
    assert (res["checked"], res["violations"]) == (4, 3)


def test_equity_withheld_or_absent_is_not_checked():
    res = _run(P.EquityTaxInputs(), [{"raw": {"equity": {"withheld": True}}}, {"raw": {}}])
    assert res["checked"] == 0 and res["ok"]


def test_tax_check_binding():
    v = P.VERIFIED_SOURCE
    rows = [
        {"raw": {"tax_county_check": {"verdict": "confirmed"}, "tax_owed": {"source": v}}},
        {"raw": {"tax_county_check": {"verdict": "confirmed"}, "tax_owed": {"source": "buncombe"}}},
        {"raw": {"tax_county_check": {"verdict": "stale"}}},
        {"raw": {"tax_county_check": {"verdict": "refuted"}, "tax_owed": {"source": "buncombe"}}},
        {"raw": {"tax_county_check": {"verdict": "stale"}, "tax_owed": {"source": v}}},   # balance the site still shows
        {"raw": {"tax_owed": {"source": "buncombe"}}},                                     # no check: not judged
    ]
    res = _run(P.TaxCheckBinding(), rows)
    assert (res["checked"], res["violations"]) == (5, 2)


def test_countyless_national():
    rows = [{"source": "national.courtlistener_bankruptcy", "county": ""},
            {"source": "reo.vrm", "county": None},
            {"source": "national.courtlistener_bankruptcy", "county": "Polk"},
            {"source": "counties_nc.polk_tax", "county": ""}]
    res = _run(P.CountylessNational(), rows)
    assert (res["checked"], res["violations"]) == (3, 2)


def test_raw_keep():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    k = next(iter(RAW_KEEP))
    res = _run(P.RawKeep(), [{"raw": {k: 1}}, {"raw": {k: 1, "zz_unpublished_key": 1}}])
    assert (res["checked"], res["violations"]) == (2, 1) and "zz_unpublished_key" in res["detail"]


def test_seen_order():
    rows = [{"first_seen": "2026-10-01T00:00:00", "last_seen": "2026-10-02T00:00:00"},
            {"first_seen": "2026-10-03T00:00:00", "last_seen": "2026-10-02T00:00:00"},
            {"first_seen": "junk", "last_seen": "2026-10-02"}]
    res = _run(P.SeenOrder(), rows)
    assert (res["checked"], res["violations"]) == (2, 1)


def test_run_health_counts_beside_a_published_board(tmp_path):
    import json
    (tmp_path / "run_health.json").write_text(json.dumps({"sources": [
        {"source": "a", "count": 0, "status": "OK (3058)"},          # the 10/7 defect
        {"source": "b", "count": 12, "status": "OK (12)"},
        {"source": "c", "count": 0, "status": "DORMANT - seasonal"}]}))
    c = P.RunHealthCounts()
    c.set_source("board", tmp_path)
    res = c.finish()
    assert (res["checked"], res["violations"], res["ok"]) == (2, 1, False)


def test_run_health_counts_beside_a_checkpoint(tmp_path):
    import json
    state = {"publish": {"write_run_health": True},
             "summary": {"by_source": {}, "source_status": {"a": "OK (5)", "b": "EMPTY (verified)"}}}
    (tmp_path / "resume_state.json").write_text(json.dumps(state))
    c = P.RunHealthCounts()
    c.set_source("checkpoint", tmp_path)
    assert c.finish()["violations"] == 1
    state["summary"]["by_source"] = {"a": 5}
    (tmp_path / "resume_state.json").write_text(json.dumps(state))
    c = P.RunHealthCounts()
    c.set_source("checkpoint", tmp_path)
    assert c.finish()["ok"]
    state["publish"]["write_run_health"] = False                    # a resume writes none: not judged
    state["summary"]["by_source"] = {}
    (tmp_path / "resume_state.json").write_text(json.dumps(state))
    c = P.RunHealthCounts()
    c.set_source("checkpoint", tmp_path)
    res = c.finish()
    assert res["checked"] == 0 and res["ok"]


def test_run_health_counts_without_a_source_is_quiet():
    res = P.RunHealthCounts().finish()
    assert res["ok"] and "nothing to judge" in res["detail"]


def test_combo_matches_tax():
    rows = [{"raw": {"bankruptcy_tax_combo": {"tax_owed_balance": 900.0}, "tax_owed": {"balance": 900}}},
            {"raw": {"bankruptcy_tax_combo": {"tax_owed_balance": 900.0}}},
            {"raw": {"bankruptcy_tax_combo": {"tax_owed_balance": 900.0}, "tax_owed": {"balance": 450}}},
            {"raw": {"tax_owed": {"balance": 1}}}]
    res = _run(P.ComboMatchesTax(), rows)
    assert (res["checked"], res["violations"]) == (3, 2)


def test_grade_equity_current():
    def row(pct, notes, under=False, withheld=False):
        eq = {"pct": pct, "is_underwater": under}
        if withheld:
            eq = {"withheld": True}
        return {"raw": {"equity": eq, "grade": {"rationale": notes}}}
    rows = [row(0.98, ["tax sale — buyer takes subject to other liens; high real equity (98%)"]),
            row(0.992, ["tax sale; high real equity (100%)"]),          # graded off another equity
            row(0.995, ["tax sale — buyer takes subject to other liens"]),  # graded before equity
            row(-0.2, ["underwater — real equity -20% (after payoff + liens)"], under=True),
            row(0.2, ["fine"]),
            row(None, ["high real equity (50%)"], withheld=True)]       # note, no published equity
    res = _run(P.GradeEquityCurrent(), rows)
    assert (res["checked"], res["violations"]) == (6, 3)


def test_tenure_from_sale():
    c = P.TenureFromSale()
    now = c.now
    rows = [{"raw": {"cama": {"last_sale_date": f"{now - 10}-05-01"}, "tenure": {"years_held": 10}}},
            {"raw": {"cama": {"last_sale_date": f"{now - 10}-05-01"}}},                  # sc_cama after tenure
            {"raw": {"gis": {"last_sale": {"date": f"{now - 3}-01-01"}}, "tenure": {"years_held": 12}}},
            {"raw": {}}]
    res = _run(c, rows)
    assert (res["checked"], res["violations"]) == (3, 2)
    assert P.TenureFromSale.DETAIL_KEYS == ("cama",)
