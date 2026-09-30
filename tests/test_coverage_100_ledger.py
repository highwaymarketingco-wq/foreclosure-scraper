"""scripts/coverage_100_ledger.py -- family_hits() matching.

A row counts toward a FAMILIES key only when its own source/scraper identity
(or a signal that ONLY that family's sources ever set) says so -- never a
generic cross-cutting stamp like raw['distressed'] that many unrelated
sources can set (enrichment_cama_condition.py / enrichment_sc_cama.py /
enrichment_owner_mailing.py all stamp it from bulk assessor "Poor" condition
data, independent of scraper identity).

Regression covered here: a pickens_delinquent_parcels (tax_delinquent) row
that picked up raw['distressed'] from assessor condition data used to count
as "code_vacancy" evidence via the distress_stack `distressed_condition`
signal, even though Pickens has no code-enforcement/vacancy scraper at all.
A real gaston_vacant row must still count.

Nothing here touches the live board -- iter_board_rows() is exercised
against a tiny synthetic fixture gzip in tmp_path, per CLAUDE.md's board
safety rules (never call load_board() / stream the real 219K-row board from
a test).
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import coverage_100_ledger as ledger  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402


def _write(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f)


# ---- direct family_hits() unit coverage -------------------------------------------------


def test_pickens_tax_cycle_distressed_flag_is_not_code_vacancy_evidence():
    """A tax-delinquency row with the generic CAMA-condition stamp must not
    count toward code_vacancy -- Pickens has no code-enforcement/vacancy
    scraper (confirmed: no scraper slug in src/foreclosure_scraper/scrapers
    matches pickens + vacant/condemn/code_violation)."""
    raw = {
        "distressed": True,                         # stamped by enrichment_cama_condition / sc_cama
        "condition_cama": {"distressed": True, "condition": "poor"},
        "distress_stack": {"signals": ["distressed_condition", "tax_lien"]},
    }
    hits = ledger.family_hits("counties_sc.pickens_delinquent_parcels", raw)
    assert "code_vacancy" not in hits
    assert "tax_delinquent" in hits            # the row's real family is untouched


def test_generic_distressed_condition_signal_alone_is_not_code_vacancy_evidence():
    """Even with no source-name hint at all, a bare `distressed_condition`
    distress_stack signal (the CAMA-condition scoring signal) must not be
    read as code_vacancy family evidence -- it is not family-specific."""
    raw = {"distress_stack": {"signals": ["distressed_condition"]}}
    hits = ledger.family_hits("some_unrelated_source", raw)
    assert "code_vacancy" not in hits


def test_gaston_vacant_row_still_counts_as_code_vacancy():
    raw = {"condemned": True, "distress_stack": {"signals": ["code_enforcement"]}}
    hits = ledger.family_hits("counties_nc.gaston_vacant", raw)
    assert "code_vacancy" in hits


def test_hendersonville_vacant_structures_signal_still_counts():
    """The one genuinely code_vacancy-scoped derived signal (only
    hendersonville_vacant_structures.py ever sets raw['vacancy'] with
    vacant/boarded_up True) must still be read as family evidence even off
    a source name that doesn't carry a fragment match."""
    raw = {"distress_stack": {"signals": ["vacant_structure"]}}
    hits = ledger.family_hits("counties_nc.hendersonville_vacant_structures", raw)
    assert "code_vacancy" in hits


def test_spartanburg_condemned_source_name_counts_without_any_signal():
    raw = {}
    hits = ledger.family_hits("counties_sc.spartanburg_condemned", raw)
    assert "code_vacancy" in hits


def test_zombie_properties_source_no_longer_counts_as_code_vacancy():
    """zombie_properties.py is a derived stalled-foreclosure signal (a stale
    lis pendens that never progressed to sale), not a code-enforcement or
    vacancy source -- it must not inflate code_vacancy coverage."""
    raw = {}
    hits = ledger.family_hits("counties_sc.zombie_properties", raw)
    assert "code_vacancy" not in hits


# ---- through the streaming board reader, on a tiny synthetic fixture --------------------


def test_through_iter_board_rows_fixture(tmp_path):
    """Same distinction, exercised through the real iter_board_rows() path the
    script uses, on a small synthetic gzip -- never the live board."""
    p = tmp_path / "board.json.gz"
    _write(p, [
        {
            "source": "counties_sc.pickens_delinquent_parcels",
            "county": "Pickens", "state": "SC",
            "raw": {"distressed": True,
                    "distress_stack": {"signals": ["distressed_condition", "tax_lien"]}},
        },
        {
            "source": "counties_nc.gaston_vacant",
            "county": "Gaston", "state": "NC",
            "raw": {"condemned": True,
                    "distress_stack": {"signals": ["code_enforcement"]}},
        },
    ])
    rows = list(iter_board_rows(p))
    hits_by_source = {r["source"]: ledger.family_hits(r["source"], r["raw"]) for r in rows}
    assert "code_vacancy" not in hits_by_source["counties_sc.pickens_delinquent_parcels"]
    assert "code_vacancy" in hits_by_source["counties_nc.gaston_vacant"]
