"""enrich_divorce_no_subsequent_deed: cross-references a DIVORCE_NOTICE row's plaintiff/
defendant against raw['resolved_from_name'] (already written by
enrichment_resolve_name_to_property.py) to flag ex-spouses still jointly titled on the
same GIS/tax-roll owner cell post-judgment -- i.e. no deed ever moved the property to one
of them alone. See enrichment_divorce_no_subsequent_deed.py's module docstring for the
live-verified design (Buncombe 25CV001998-100, Greene v. Greene) and the two guards this
file exercises directly: the same-person caption artifact, and the ambiguous-multi-parcel
candidate path. Every parcel, owner, case number and address here is made up.

This file closes the one real gap found while investigating the (stale) gap_matrix claim
that this signal was 'sourced but not built': the enrichment and its main.py wiring already
existed (commit afae350, 2026-11-10 14:01), and test_gap_matrix.py already covers the
SPECS/checked_columns side, but no test exercised enrich_divorce_no_subsequent_deed's own
true/false branches directly."""
from __future__ import annotations

from foreclosure_scraper.enrichment_divorce_no_subsequent_deed import (
    enrich_divorce_no_subsequent_deed,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from datetime import datetime

NOW = datetime(2026, 11, 10)


def _li(raw=None, state="NC", plaintiff="GREENE KENNETH", defendant="GREENE YVONNE",
        listing_type=ListingType.DIVORCE_NOTICE, case_number="25CV001998-100",
        county="Buncombe", parcel_id=None):
    return Listing(source="s", source_url="https://x.invalid/1", listing_type=listing_type,
                    property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                    parcel_id=parcel_id, plaintiff=plaintiff, defendant=defendant,
                    case_number=case_number, first_seen=NOW, last_seen=NOW, raw=raw or {})


def test_both_spouses_on_same_owner_cell_is_tagged_high_confidence():
    """The one real live hit documented in the module: both ex-spouses still clear
    match_owner, exactly, against distinct segments of the same owner cell."""
    li = _li(raw={
        "resolved_from_name": {"matched_owner": "GREENE KENNETH;GREENE YVONNE",
                                "confidence": "ambiguous_multi_parcel"},
        "nc_ecourts": {"ordered_date_iso": "2026-07-12", "civilJudgmentStatus": "Active"},
    })
    stats = enrich_divorce_no_subsequent_deed([li])
    sig = li.raw["divorce_no_subsequent_deed"]
    assert sig["confidence"] == "high"
    assert sig["plaintiff_match"] == "exact"
    assert sig["defendant_match"] == "exact"
    assert sig["matched_owner"] == "GREENE KENNETH;GREENE YVONNE"
    assert sig["decree_date"] == "2026-07-12"
    assert sig["decree_date_kind"] == "judgment_ordered"
    assert sig["judgment_confirmed"] is True
    assert stats["tagged"] == 1


def test_resolved_to_single_owner_is_not_tagged():
    """Property moved to one ex-spouse alone (or to a third party) -- the owner cell no
    longer carries both names, so this is exactly the negative the signal must NOT fire on."""
    li = _li(raw={"resolved_from_name": {"matched_owner": "GREENE YVONNE",
                                          "confidence": "strong"}})
    stats = enrich_divorce_no_subsequent_deed([li])
    assert "divorce_no_subsequent_deed" not in li.raw
    assert stats["resolved_no_joint_owner"] == 1
    assert stats["tagged"] == 0


def test_sc_row_is_skipped_even_with_a_joint_owner_cell():
    """NC-only by design (SC family court is access-restricted) -- the state gate must win
    even when the rest of the row would otherwise qualify."""
    li = _li(state="SC", raw={
        "resolved_from_name": {"matched_owner": "GREENE KENNETH;GREENE YVONNE"},
    })
    stats = enrich_divorce_no_subsequent_deed([li])
    assert "divorce_no_subsequent_deed" not in li.raw
    assert stats["sc_skipped"] == 1
    assert stats["tagged"] == 0


def test_no_resolver_block_yet_is_not_tagged():
    """The name->property resolver is a shared, budget-capped backlog; most divorce_notice
    rows have not been through it yet and must not be treated as a negative result."""
    li = _li(raw={})
    stats = enrich_divorce_no_subsequent_deed([li])
    assert "divorce_no_subsequent_deed" not in li.raw
    assert stats["no_resolution_yet"] == 1


def test_same_person_captioned_as_both_parties_is_guarded():
    """Live-documented false-positive: a caption-parsing artifact upstream names the same
    person as plaintiff and defendant ('STECHER, REESE E' v. 'Stecher, Reese Edward'), which
    would trivially match a single-name owner cell against 'both spouses' without this guard."""
    li = _li(plaintiff="STECHER, REESE E", defendant="Stecher, Reese Edward",
             raw={"resolved_from_name": {"matched_owner": "STECHER REESE E"}})
    stats = enrich_divorce_no_subsequent_deed([li])
    assert "divorce_no_subsequent_deed" not in li.raw
    assert stats["same_person_artifact"] == 1
    assert stats["tagged"] == 0


def test_ambiguous_multi_parcel_candidate_owner_is_checked():
    """The case the module's docstring calls out as the one that actually matters: the
    resolver found 2+ parcels and stopped short of committing matched_owner, but each
    candidate still carries its own owner-cell text -- that must be checked too."""
    li = _li(raw={"resolved_from_name": {
        "confidence": "ambiguous_multi_parcel",
        "candidates": [
            {"parcel_id": "071081525000000", "owner": "SOMEONE ELSE"},
            {"parcel_id": "071081539300000", "owner": "GREENE KENNETH;GREENE YVONNE"},
        ],
    }})
    stats = enrich_divorce_no_subsequent_deed([li])
    sig = li.raw["divorce_no_subsequent_deed"]
    assert sig["matched_owner"] == "GREENE KENNETH;GREENE YVONNE"
    assert sig["candidate_parcel_ids"] == ["071081525000000", "071081539300000"]
    assert stats["tagged"] == 1


def test_medium_confidence_when_one_side_is_only_a_strong_match():
    """'strong' (not 'exact') on either side must still tag the row -- it is real evidence --
    but at reduced confidence, per the module's own high/medium split. A real middle name on
    the plaintiff's caption that the GIS owner cell lacks is enough to drop exact-token-set
    equality to the positional 'strong' rule (verified directly against name_normalize.
    match_owner before writing this case: 'KENNETH MICHAEL GREENE' vs 'GREENE KENNETH' ->
    'strong', not 'exact')."""
    li = _li(plaintiff="KENNETH MICHAEL GREENE", defendant="GREENE YVONNE",
              raw={"resolved_from_name": {"matched_owner": "GREENE KENNETH;GREENE YVONNE"}})
    stats = enrich_divorce_no_subsequent_deed([li])
    sig = li.raw["divorce_no_subsequent_deed"]
    assert sig["plaintiff_match"] == "strong"
    assert sig["defendant_match"] == "exact"
    assert sig["confidence"] == "medium"
    assert stats["tagged"] == 1


def test_non_divorce_notice_listing_type_is_ignored():
    """Only DIVORCE_NOTICE rows carry plaintiff/defendant in the sense this join needs --
    every other listing type must be skipped before any stat beyond the loop itself."""
    li = _li(listing_type=ListingType.TAX_LIEN,
              raw={"resolved_from_name": {"matched_owner": "GREENE KENNETH;GREENE YVONNE"}})
    stats = enrich_divorce_no_subsequent_deed([li])
    assert "divorce_no_subsequent_deed" not in li.raw
    assert stats["divorce_notice_rows"] == 0


def test_missing_defendant_is_skipped_without_crashing():
    """A DIVORCE_NOTICE row that never got a second party name (caption parse miss, not an
    error in this module) must not raise and must not be tagged."""
    li = _li(defendant=None,
              raw={"resolved_from_name": {"matched_owner": "GREENE KENNETH;GREENE YVONNE"}})
    stats = enrich_divorce_no_subsequent_deed([li])
    assert "divorce_no_subsequent_deed" not in li.raw
    assert stats["divorce_notice_rows"] == 1
    assert stats["tagged"] == 0


def test_decree_date_falls_back_to_filing_when_no_judgment():
    """A pending SmartSearch filing (nc_ecourts_divorce.py) is weaker evidence than a granted
    judgment, but is still the best date available when no judgment block exists."""
    li = _li(raw={
        "resolved_from_name": {"matched_owner": "GREENE KENNETH;GREENE YVONNE"},
        "nc_ecourts_divorce": {"filed_date_iso": "2026-03-01"},
    })
    enrich_divorce_no_subsequent_deed([li])
    sig = li.raw["divorce_no_subsequent_deed"]
    assert sig["decree_date"] == "2026-03-01"
    assert sig["decree_date_kind"] == "filing_date"
    assert sig["judgment_confirmed"] is False
