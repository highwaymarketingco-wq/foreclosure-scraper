"""Prior correction 6: carried Charleston Public Index rows that are positively not leads.

Only a stored lane of 'other', or a stored status recording a dismissal, withdrawal,
discontinuance or satisfaction, withdraws a row (2026-10-07). Made-up names and numbers only.
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


def test_a_stored_other_lane_is_withdrawn():
    li = _row(lane="other")
    assert pc.withdraw_charleston_case_type(li) == {"action": "withdrawn", "reason": "case_type_other"}
    assert li.listing_type == ListingType.UNKNOWN
    rec = li.raw[pc.CASE_TYPE_KEY]
    assert rec["reason"] == "case_type_other" and rec["listing_type"] == "lis_pendens"


def test_dismissed_withdrawn_discontinued_or_satisfied_is_withdrawn():
    for status in ("Dismissed", "Withdrawn", "Discontinued", "Satisfied"):
        li = _row(status=status, disposed="03/01/2026")
        assert pc.withdraw_charleston_case_type(li)["reason"] == "case_dismissed_or_satisfied", status
    j = _row(lane="judgment", status="Satisfied", source="national.sc_public_index.judgment_lien",
             lt=ListingType.DISTRESSED)
    assert pc.withdraw_charleston_case_type(j)["reason"] == "case_dismissed_or_satisfied"
    assert j.raw[pc.CASE_TYPE_KEY]["listing_type"] == "distressed"


def test_unlabeled_or_live_rows_are_left_alone():
    # the 557 open-but-unlabeled kind, a judgment-entered foreclosure, a settled case
    # (not in the rule: it ages out if the scraper stops emitting it), an open lead
    for li in (_row(), _row(status="Pending/ADR"), _row(status="Judgment", disposed="08/01/2026"),
               _row(lane="foreclosure", status="Disposed", disposed="08/01/2026"),
               _row(status="Settled", disposed="02/01/2026"), _row(lane="partition"),
               _row(lane="judgment", status="Judgment Entered", disposed="06/01/2025",
                    source="national.sc_public_index.judgment_lien", lt=ListingType.DISTRESSED)):
        before = copy.deepcopy(li.model_dump())
        assert pc.withdraw_charleston_case_type(li) is None
        assert li.model_dump() == before


def test_other_counties_and_sources_are_not_concerned():
    assert pc.withdraw_charleston_case_type(_row(lane="other", county="Spartanburg")) is None
    assert pc.withdraw_charleston_case_type(_row(lane="other", source="counties_sc.sc_public_index")) is None
    assert pc.withdraw_charleston_case_type(_row(lane="other", county="Charleston County")) is not None


def test_idempotent_and_reversible():
    li = _row(lane="other")
    pc.withdraw_charleston_case_type(li)
    snap = copy.deepcopy(li.model_dump())
    assert pc.withdraw_charleston_case_type(li) == {"action": "already"}
    assert li.model_dump() == snap
    # a later copy re-emitted as a live partition: fresh type kept, audit key dropped
    li.raw["sc_public_index"]["lane"] = "partition"
    li.listing_type = ListingType.LIS_PENDENS
    assert pc.withdraw_charleston_case_type(li) == {"action": "restored"}
    assert pc.CASE_TYPE_KEY not in li.raw and li.listing_type == ListingType.LIS_PENDENS
    # a row whose stored status no longer meets the rule gets its recorded type back
    li2 = _row(status="Dismissed")
    pc.withdraw_charleston_case_type(li2)
    li2.raw["sc_public_index"]["status"] = "Reopened"
    assert pc.withdraw_charleston_case_type(li2) == {"action": "restored"}
    assert li2.listing_type == ListingType.LIS_PENDENS and pc.CASE_TYPE_KEY not in li2.raw
    # or by hand
    li3 = _row(lane="other")
    pc.withdraw_charleston_case_type(li3)
    assert pc.restore_case_type_withdrawal(li3) is True
    assert li3.listing_type == ListingType.LIS_PENDENS and pc.CASE_TYPE_KEY not in li3.raw
    assert pc.restore_case_type_withdrawal(li3) is False


def test_correct_prior_rows_counts_them():
    rows = [_row(case="2025CP1000401"), _row(lane="other", case="2025CP1000402"),
            _row(lane="foreclosure", case="2025CP1000403"),
            _row(status="Dismissed", case="2025CP1000404")]
    stats = pc.correct_prior_rows(rows, cache=_NoCache())
    assert stats["charleston_case_type_withdrawn"] == 2
    assert stats["charleston_case_type_detail"] == {"case_type_other": 1, "case_dismissed_or_satisfied": 1}
    assert [r.listing_type for r in rows].count(ListingType.UNKNOWN) == 2
    assert stats["rows_after"] == 4  # withdrawn rows stay on the board
