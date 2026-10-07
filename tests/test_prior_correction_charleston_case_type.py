"""Prior correction 6: carried Charleston Public Index rows that are not leads (2026-10-07).

Made-up names and case numbers only.
"""
from __future__ import annotations

import copy

from foreclosure_scraper import enrichment_prior_correction as pc
from foreclosure_scraper.models import Listing, ListingType


class _NoCache(pc.CacheReader):
    def __init__(self):
        super().__init__(lookup=lambda c, p, s: (None, None), available=lambda c, s: False)


def _row(lane=None, status="Pending", disposed="", county="Charleston",
         source="national.sc_public_index", lt=ListingType.LIS_PENDENS, case="2025CP1000301"):
    spi = {"name": "Owner Uniform", "role": "Defendant", "case_number": case,
           "date_filed": "05/01/2025", "status": status, "date_disposed": disposed,
           "court": "SC Common Pleas", "source": "publicindex.sccourts.org"}
    if lane is not None:
        spi["lane"] = lane
    return Listing(source=source, source_url="https://publicindex.sccourts.org/", listing_type=lt,
                   state="SC", county=county, case_number=case, raw={"sc_public_index": spi})


def test_an_unlabeled_carried_row_is_withdrawn_as_unrecoverable():
    li = _row()
    a = pc.withdraw_charleston_case_type(li)
    assert a == {"action": "withdrawn", "reason": "case_type_unrecoverable"}
    assert li.listing_type == ListingType.UNKNOWN
    rec = li.raw[pc.CASE_TYPE_KEY]
    assert rec["reason"] == "case_type_unrecoverable" and rec["listing_type"] == "lis_pendens"
    assert rec["lane"] is None and rec["status"] == "Pending"


def test_other_case_types_and_closed_cases_are_withdrawn_with_their_reason():
    assert pc.withdraw_charleston_case_type(_row(lane="other"))["reason"] == "case_type_other"
    assert pc.withdraw_charleston_case_type(
        _row(lane="foreclosure", status="Disposed", disposed="08/01/2025"))["reason"] == "case_closed"
    assert pc.withdraw_charleston_case_type(_row(status="Dismissed"))["reason"] == "case_closed"
    satisfied = _row(lane="judgment", status="Satisfied", disposed="06/01/2025",
                     source="national.sc_public_index.judgment_lien", lt=ListingType.DISTRESSED)
    assert pc.withdraw_charleston_case_type(satisfied)["reason"] == "case_closed"
    assert satisfied.raw[pc.CASE_TYPE_KEY]["listing_type"] == "distressed"


def test_open_lead_lanes_are_untouched():
    for lane in ("foreclosure", "partition", "quiet_title", "lis_pendens"):
        li = _row(lane=lane)
        before = copy.deepcopy(li.model_dump())
        assert pc.withdraw_charleston_case_type(li) is None
        assert li.model_dump() == before
    entered = _row(lane="judgment", status="Judgment Entered", disposed="06/01/2025",
                   source="national.sc_public_index.judgment_lien", lt=ListingType.DISTRESSED)
    assert pc.withdraw_charleston_case_type(entered) is None
    assert entered.listing_type == ListingType.DISTRESSED


def test_other_counties_and_sources_are_not_concerned():
    assert pc.withdraw_charleston_case_type(_row(county="Spartanburg")) is None
    assert pc.withdraw_charleston_case_type(_row(source="counties_sc.sc_public_index")) is None
    assert pc.withdraw_charleston_case_type(_row(county="Charleston County")) is not None


def test_idempotent_and_reversible():
    li = _row(lane="other")
    pc.withdraw_charleston_case_type(li)
    snap = copy.deepcopy(li.model_dump())
    assert pc.withdraw_charleston_case_type(li) == {"action": "already"}
    assert li.model_dump() == snap
    # a later run re-emits the case open and labeled: the fresh type wins the merge and the
    # correction drops the audit key
    li.raw["sc_public_index"]["lane"] = "partition"
    li.listing_type = ListingType.LIS_PENDENS
    assert pc.withdraw_charleston_case_type(li) == {"action": "restored"}
    assert pc.CASE_TYPE_KEY not in li.raw and li.listing_type == ListingType.LIS_PENDENS
    # or by hand
    li2 = _row()
    pc.withdraw_charleston_case_type(li2)
    assert pc.restore_case_type_withdrawal(li2) is True
    assert li2.listing_type == ListingType.LIS_PENDENS and pc.CASE_TYPE_KEY not in li2.raw
    assert pc.restore_case_type_withdrawal(li2) is False


def test_correct_prior_rows_counts_them():
    rows = [_row(case="2025CP1000401"), _row(lane="other", case="2025CP1000402"),
            _row(lane="foreclosure", case="2025CP1000403"),
            _row(lane="foreclosure", status="Closed", case="2025CP1000404")]
    stats = pc.correct_prior_rows(rows, cache=_NoCache())
    assert stats["charleston_case_type_withdrawn"] == 3
    assert stats["charleston_case_type_detail"] == {
        "case_type_unrecoverable": 1, "case_type_other": 1, "case_closed": 1}
    assert [r.listing_type for r in rows].count(ListingType.UNKNOWN) == 3
    assert stats["rows_after"] == 4  # withdrawn rows stay on the board
