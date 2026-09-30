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


# ---- FAMILIES["liens"]: recorded_debt -> source+listing_type (2026-09-30 fix) -----------
#
# recorded_debt (distress_score.py) fires off ANY real raw['tax_owed']['balance'] or
# countable raw['amount_owed'] -- a real-debt signal, not a lien-registry-specific one.
# Real lien evidence comes from the three ROD "sweep" scrapers (nc_rod_logan,
# sc_rod_cott, sc_rod_acclaim), each of which discovers ALL recent distress
# recordings for its county/vendor (lis pendens, foreclosure deeds, probate, liens)
# and classifies every row's own instrument code via its own `_classify()`. Only a
# row that source classified as a LIEN (LIEN/JUDGMENT/MECH/EXECUTION code) is
# stamped listing_type=="tax_lien" by that source. The fix requires BOTH: the row's
# source is one of the three ROD scrapers AND its own listing_type says tax_lien --
# not a bare recorded_debt flag, and not "any row from a ROD source."


def test_rod_logan_lien_row_counts_as_liens():
    """A real nc_rod_logan LIEN/JUDGMENT recording (_classify() -> TAX_LIEN) must
    count toward the liens family via source+listing_type, with no recorded_debt
    signal present at all (these ROD scrapers never populate tax_owed/amount_owed)."""
    raw = {"rod": {"doc_type": "LIEN", "grantor": "SMITH JOHN"}, "logan_rod": True}
    hits = ledger.family_hits("counties_nc.nc_rod_logan", raw, listing_type="tax_lien")
    assert "liens" in hits


def test_rod_logan_lis_pendens_row_from_same_source_does_not_count_as_liens():
    """The SAME nc_rod_logan scraper also emits LIS_PENDENS (FCL/S-TR/etc.) and
    FORECLOSURE_SALE (TR-D/SHF-D/etc.) rows off the same sweep -- those must not
    count as liens just because they share a source with real lien rows."""
    raw = {"rod": {"doc_type": "FCL", "grantor": "SMITH JOHN"}, "logan_rod": True}
    hits = ledger.family_hits("counties_nc.nc_rod_logan", raw, listing_type="lis_pendens")
    assert "liens" not in hits


def test_rod_cott_probate_row_from_same_source_does_not_count_as_liens():
    """sc_rod_cott also sweeps probate (deed of distribution / death) recordings --
    those must not count as liens either."""
    raw = {"rod": {"doc_type": "DOD", "grantor": "JONES MARY"},
           "cott_rod": True, "relationship_signal": {"kind": "probate", "keyword": "DOD"}}
    hits = ledger.family_hits("counties_sc.sc_rod_cott", raw, listing_type="probate_notice")
    assert "liens" not in hits


def test_rod_acclaim_lien_row_counts_as_liens():
    raw = {"rod": {"doc_type": "MECHANICS LIEN", "grantor": "DOE JANE"}, "acclaim_rod": True}
    hits = ledger.family_hits("counties_sc.sc_rod_acclaim", raw, listing_type="tax_lien")
    assert "liens" in hits


def test_tax_delinquent_row_with_real_balance_is_not_liens_evidence():
    """The false-positive class recorded_debt caused: a plain tax-delinquency row
    (Pickens parcel scraper, not a ROD scraper) with a real recorded_debt signal
    (an actual raw['tax_owed']['balance']) must NOT count as liens -- a real tax
    balance on a delinquent PARCEL is not a recorded LIEN instrument. It also
    happens to carry listing_type=="tax_lien" (ListingType.TAX_LIEN is the generic
    tax-delinquency listing type), which is exactly why listing_type alone --
    without the ROD source-identity check -- would still be wrong."""
    raw = {"tax_owed": {"balance": 4200.00},
           "distress_stack": {"signals": ["recorded_debt", "tax_lien"]}}
    hits = ledger.family_hits("counties_sc.pickens_delinquent_parcels", raw,
                               listing_type="tax_lien")
    assert "liens" not in hits
    assert "tax_delinquent" in hits


def test_mortgage_foreclosure_row_with_countable_judgment_is_not_liens_evidence():
    """A foreclosure-sale source with a real countable amount_owed (judgment
    amount) also used to fire recorded_debt -- must not count as liens either."""
    raw = {"amount_owed": {"value": 185000.0, "is_actual_debt": True},
           "distress_stack": {"signals": ["recorded_debt", "foreclosure_sale"]}}
    hits = ledger.family_hits("counties_nc.hutchens_foreclosure_sale", raw,
                               listing_type="foreclosure_sale")
    assert "liens" not in hits
    assert "mortgage_foreclosure" in hits


def test_dedicated_lien_registry_source_still_counts_via_name_fragment():
    """A genuinely lien-specific source (SC DEW Lien Registry) still counts via
    the "lien" name fragment -- untouched by dropping recorded_debt."""
    raw = {}
    hits = ledger.family_hits("counties_sc.sc_dew_lien_registry", raw)
    assert "liens" in hits


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
