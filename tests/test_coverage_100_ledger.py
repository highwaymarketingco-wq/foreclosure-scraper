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


# ---- FAMILIES["tax_delinquent"]: tax_lien signal -> exclude ROD-lien sources (2026-09-30) -
#
# The mirror image of the liens fix above: `tax_lien` (== listing_type, restated as a
# distress_stack signal) is the generic tax-delinquency listing type for ~25 dedicated
# scrapers, but the same three ROD sweep scrapers (nc_rod_logan, sc_rod_cott,
# sc_rod_acclaim) also stamp listing_type=="tax_lien" on a real recorded LIEN/JUDGMENT
# instrument -- not a delinquent tax parcel. None of the three names carry a
# tax_delinquent fragment, so dropping the signal-based hit for them only removes the
# false positive.


def test_rod_logan_lien_row_is_not_tax_delinquent_evidence():
    """A real nc_rod_logan LIEN/JUDGMENT recording must not count as tax_delinquent --
    it is a private lien, not a delinquent tax parcel."""
    raw = {"rod": {"doc_type": "LIEN", "grantor": "SMITH JOHN"}, "logan_rod": True}
    hits = ledger.family_hits("counties_nc.nc_rod_logan", raw, listing_type="tax_lien")
    assert "tax_delinquent" not in hits
    assert "liens" in hits          # its real family is untouched


def test_rod_cott_lien_row_is_not_tax_delinquent_evidence():
    raw = {"rod": {"doc_type": "JUDGMENT", "grantor": "DOE JANE"}, "cott_rod": True}
    hits = ledger.family_hits("counties_sc.sc_rod_cott", raw, listing_type="tax_lien")
    assert "tax_delinquent" not in hits


def test_rod_acclaim_lien_row_is_not_tax_delinquent_evidence():
    raw = {"rod": {"doc_type": "MECHANICS LIEN", "grantor": "DOE JANE"}, "acclaim_rod": True}
    hits = ledger.family_hits("counties_sc.sc_rod_acclaim", raw, listing_type="tax_lien")
    assert "tax_delinquent" not in hits


def test_dedicated_tax_delinquent_source_with_tax_lien_signal_still_counts():
    """A real dedicated tax-delinquency scraper (not a ROD source) with the
    `tax_lien` signal must still count -- the fix is source-scoped, not blind
    signal removal."""
    raw = {"distress_stack": {"signals": ["tax_lien"]}}
    hits = ledger.family_hits("counties_sc.pickens_delinquent_parcels", raw,
                               listing_type="tax_lien")
    assert "tax_delinquent" in hits


def test_greenville_hard_distress_tax_lien_row_still_counts_as_tax_delinquent():
    """greenville_hard_distress.py hardcodes listing_type=TAX_LIEN, but every row it
    emits is keyed off a real unpaid-tax spine (TOTTAX>0 AND PAIDDATE IS NULL) -- a
    genuine tax-delinquent parcel, not a ROD source, so it is untouched by the fix."""
    raw = {"distress_stack": {"signals": ["tax_lien"]}}
    hits = ledger.family_hits("counties_sc.greenville_hard_distress", raw,
                               listing_type="tax_lien")
    assert "tax_delinquent" in hits


# ---- FAMILIES["code_vacancy"]: vacant-LAND sources excluded (2026-09-30) ----------------
#
# gaston_vacant / lincoln_vacant / transylvania_vacant matched the bare "vacant" name
# fragment, but all three are vacant-LAND (unimproved lot) parcel feeds -- the opposite
# condition from code_vacancy (a STRUCTURE with an open code-enforcement / condemned /
# boarded-up case). None of the three ever sets raw['condemned'] or a code_enforcement
# block in the real scraper code.


def test_gaston_vacant_land_row_is_not_code_vacancy_evidence():
    raw = {}
    hits = ledger.family_hits("counties_nc.gaston_vacant", raw)
    assert "code_vacancy" not in hits


def test_lincoln_vacant_land_row_is_not_code_vacancy_evidence():
    raw = {}
    hits = ledger.family_hits("counties_nc.lincoln_vacant", raw)
    assert "code_vacancy" not in hits


def test_transylvania_vacant_land_row_is_not_code_vacancy_evidence():
    raw = {}
    hits = ledger.family_hits("counties_nc.transylvania_vacant", raw)
    assert "code_vacancy" not in hits


def test_gaston_vacant_row_with_a_real_code_enforcement_signal_still_counts():
    """The fix only removes the blind name-fragment match -- a genuine
    code_enforcement signal (e.g. the cross-cutting enrichment_code_enforcement.py
    city registry separately matching the same address) must still count."""
    raw = {"distress_stack": {"signals": ["code_enforcement"]}}
    hits = ledger.family_hits("counties_nc.gaston_vacant", raw)
    assert "code_vacancy" in hits


def test_spartanburg_vacant_structure_registry_still_counts_by_name():
    """spartanburg_vacant is NOT vacant land -- its "allvacant" layer carries CAMA
    specs (year_built/beds/baths) that only exist for an improved parcel, so it is
    a genuine vacant-STRUCTURE registry and keeps matching by name alone."""
    raw = {}
    hits = ledger.family_hits("counties_sc.spartanburg_vacant", raw)
    assert "code_vacancy" in hits


def test_lincoln_code_violations_unaffected_by_the_vacant_land_exclusion():
    """lincoln_code_violations (a real code-enforcement source, distinct from
    lincoln_vacant) must be untouched -- it matches its own "code_violation"
    fragment, not "vacant"."""
    raw = {}
    hits = ledger.family_hits("counties_nc.lincoln_code_violations", raw)
    assert "code_vacancy" in hits


# ---- FAMILIES["probate_estate"] / ["mortgage_foreclosure"]: hibid_real_estate (2026-09-30) -
#
# national.hibid_real_estate is a generic national real-estate AUCTION-category
# aggregator (its own docstring: "the catch-all net ... estate / distressed / land / tax
# real estate"), every row typed listing_type==AUCTION. It rode into probate_estate via
# the "estate" substring in "real_estate" and into mortgage_foreclosure via the generic
# `auction` signal, with no real evidence for either.


def test_hibid_real_estate_row_is_not_probate_estate_evidence():
    raw = {"distress_stack": {"signals": ["auction"]}}
    hits = ledger.family_hits("national.hibid_real_estate", raw, listing_type="auction")
    assert "probate_estate" not in hits


def test_hibid_real_estate_row_is_not_mortgage_foreclosure_evidence():
    raw = {"distress_stack": {"signals": ["auction"]}}
    hits = ledger.family_hits("national.hibid_real_estate", raw, listing_type="auction")
    assert "mortgage_foreclosure" not in hits


def test_dedicated_estate_sources_still_count_as_probate_estate():
    """Real estate-scoped sources must be untouched by the hibid exclusion."""
    assert "probate_estate" in ledger.family_hits("national.estate_sales", {})
    assert "probate_estate" in ledger.family_hits("counties_nc.nc_heir_estate_parcels", {})
    assert "probate_estate" in ledger.family_hits("counties_nc.nc_ecourts_estates", {})


def test_dedicated_auction_source_still_counts_as_mortgage_foreclosure():
    """A real dedicated REO/foreclosure-auction platform (not hibid) must still
    count via the generic `auction` signal -- the fix is source-scoped."""
    raw = {"distress_stack": {"signals": ["auction"]}}
    hits = ledger.family_hits("national.govdeals", raw, listing_type="auction")
    assert "mortgage_foreclosure" in hits


# ---- FAMILIES["bankruptcy"]: courtlistener_civil excluded (2026-09-30) ------------------
#
# national.courtlistener_civil is a federal CIVIL real-property/foreclosure docket
# scraper (nature-of-suit 220 Foreclosure / 230 Rent Lease & Ejectment / 240 Torts to
# Land / 290 Other Real Property), emitting listing_type=LIS_PENDENS -- never bankruptcy.
# It matched the old bare "courtlistener" fragment, which was meant for
# courtlistener_bankruptcy (already covered by the "bankruptcy" fragment substring) and
# courtlistener_adversary (a real bankruptcy-docket source, now its own fragment).


def test_courtlistener_civil_row_is_not_bankruptcy_evidence():
    raw = {}
    hits = ledger.family_hits("national.courtlistener_civil", raw, listing_type="lis_pendens")
    assert "bankruptcy" not in hits


def test_courtlistener_adversary_row_still_counts_as_bankruptcy():
    raw = {}
    hits = ledger.family_hits("national.courtlistener_adversary", raw, listing_type="lis_pendens")
    assert "bankruptcy" in hits


def test_courtlistener_bankruptcy_row_still_counts_as_bankruptcy():
    raw = {}
    hits = ledger.family_hits("national.courtlistener_bankruptcy", raw)
    assert "bankruptcy" in hits


# ---- FAMILIES["lis_pendens"]: sweep sources gated on listing_type (2026-09-30) ----------
#
# nc_ecourts_lis_pendens classifies by AOC cause of action: a divorce cause becomes
# DIVORCE_NOTICE and a tax cause becomes TAX_LIEN under the SAME slug. sc_public_index
# (the BULK civil+criminal sweep) emits UNKNOWN for its General-Sessions criminal rows
# under the same slug as its real Common-Pleas LIS_PENDENS rows. Both must require the
# row's own listing_type, not just the source name.


def test_nc_ecourts_lis_pendens_divorce_row_is_not_lis_pendens_evidence():
    raw = {}
    hits = ledger.family_hits("counties_nc.nc_ecourts_lis_pendens", raw,
                               listing_type="divorce_notice")
    assert "lis_pendens" not in hits


def test_nc_ecourts_lis_pendens_tax_row_is_not_lis_pendens_evidence():
    raw = {}
    hits = ledger.family_hits("counties_nc.nc_ecourts_lis_pendens", raw,
                               listing_type="tax_lien")
    assert "lis_pendens" not in hits


def test_nc_ecourts_lis_pendens_real_lis_pendens_row_still_counts():
    raw = {}
    hits = ledger.family_hits("counties_nc.nc_ecourts_lis_pendens", raw,
                               listing_type="lis_pendens")
    assert "lis_pendens" in hits


def test_sc_public_index_bulk_criminal_row_is_not_lis_pendens_evidence():
    """counties_sc.sc_public_index (the bulk civil+criminal sweep) must not count
    its General-Sessions criminal rows (listing_type UNKNOWN) as lis_pendens."""
    raw = {}
    hits = ledger.family_hits("counties_sc.sc_public_index", raw, listing_type="unknown")
    assert "lis_pendens" not in hits


def test_sc_public_index_bulk_civil_row_still_counts_as_lis_pendens():
    raw = {}
    hits = ledger.family_hits("counties_sc.sc_public_index", raw, listing_type="lis_pendens")
    assert "lis_pendens" in hits


def test_sc_public_index_lis_pendens_dedicated_sibling_unaffected():
    """The dedicated, single-type sc_public_index_lis_pendens sibling (CP-Foreclosure-420
    filter only) must keep matching by name alone, with no listing_type gate -- it is
    NOT in _LIS_PENDENS_SWEEP_SOURCES (its slug is a different, longer string than the
    bulk sweep's)."""
    raw = {}
    hits = ledger.family_hits("counties_sc.sc_public_index_lis_pendens", raw)
    assert "lis_pendens" in hits


def test_national_sc_public_index_dedicated_source_unaffected():
    raw = {}
    hits = ledger.family_hits("national.sc_public_index", raw)
    assert "lis_pendens" in hits


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
