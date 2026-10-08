"""Window-searched court lanes: a known open Charleston case stays on the board until it is disposed
(a foreclosure disposed by judgment stays for the judgment-entered window) or idle for 12 months;
the 60-day filed-date window limits how far back a run searches, not how long a case stays (owner
decision 2026-10-09). Made-up cases, names and addresses."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.board_persist import open_case_hold, merge_prior_board

from tests.test_board_persist import _li, _write_board

NOW = datetime(2026, 10, 9)


def _case(street="10 Sample St", county="Charleston", source="national.sc_public_index", **spi):
    block = {"case_number": "2026CP1000001", "date_filed": "05/20/2026", "status": "Pending",
             "date_disposed": ""}
    block.update(spi)
    raw = {"sc_public_index": block,
           "pulled_sale": {"consecutive_misses": 4, "presumed_withdrawn": True}}
    return _li(street_address=street, zip_code="29401", state="SC", county=county, source=source,
               auction_status="presumed_withdrawn", raw=raw, first_seen=datetime(2026, 6, 1))


def _rec(li):
    return li.model_dump(mode="json")


def test_the_hold_rule():
    assert open_case_hold(_rec(_case()), NOW)                                       # open, filed in May
    assert open_case_hold(_rec(_case(source="national.sc_public_index.judgment_lien")), NOW)
    assert not open_case_hold(_rec(_case(date_filed="03/01/2025")), NOW)            # idle over a year
    assert not open_case_hold(_rec(_case(date_disposed="09/01/2026")), NOW)         # disposed
    assert not open_case_hold(_rec(_case(status="Dismissed")), NOW)
    assert not open_case_hold(_rec(_case(lane="other")), NOW)                       # not a lead lane
    assert not open_case_hold(_rec(_case(county="Hampton")), NOW)                   # Charleston only
    assert not open_case_hold(_rec(_case(source="counties_sc.sc_public_index")), NOW)


def test_a_judgment_entered_foreclosure_stays_for_its_window():
    li = _case(date_disposed="08/01/2026")
    li.raw["foreclosure_judgment_entered"] = True
    assert open_case_hold(_rec(li), NOW)
    li.raw["sc_public_index"]["date_disposed"] = "08/01/2025"
    assert not open_case_hold(_rec(li), NOW)


def test_recent_docket_activity_keeps_an_old_case():
    li = _case(date_filed="01/05/2024")
    li.raw["docket_last_event_date"] = "2026-08-30"
    assert open_case_hold(_rec(li), NOW)


def test_merge_holds_an_open_case_and_ages_the_others(tmp_path):
    prior = [_case(street="10 Sample St"),
             _case(street="12 Sample St", date_disposed="09/01/2026"),
             _case(street="14 Sample St", date_filed="02/02/2024")]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    held = by["10 Sample St"]
    assert "pulled_sale" not in (held.raw or {}) and held.auction_status is None
    assert "12 Sample St" not in by and "14 Sample St" not in by          # 5th miss: aged out
    assert stats["prior_only_kept_open_case"] == 1 and stats["aged_out_misses"] == 2
