"""qPayBill detail pages, STAGED (owner decision 2026-10-07): on by default, at most
QPAYBILL_ROLL_DETAIL_MAX parcels per run (default 2,000), HOT then WARM then COLD (the board's
raw.distress_stack.tier), largest balance first, never a parcel whose board row already
carries the detail (resumable, idempotent), one request at a time per county host, paced.
Made-up idents and hrefs; no network, no real board."""
from __future__ import annotations

import asyncio

import foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll as q


def _r(ident, amount, receipt=None):
    return {"ident": ident, "amount": amount,
            "detail_href": f"TaxesDetailsType4.aspx?receiptNo={receipt or ident}&recID=1"}


def test_defaults_are_on_and_capped_at_2000():
    """Read off the module source: reloading the module here would swap its exception
    classes under every other test (the conftest switches the pass off for fetch() tests)."""
    from pathlib import Path
    src = Path(q.__file__).read_text()
    assert 'os.getenv("QPAYBILL_ROLL_DETAIL_MAX", "2000")' in src
    assert 'os.getenv("QPAYBILL_ROLL_DETAIL", "1") not in ("0", "false", "False")' in src
    assert 'os.getenv("QPAYBILL_ROLL_DETAIL_PACE_S", "1.6")' in src


def test_targets_go_hot_warm_cold_then_balance_and_skip_detailed_parcels():
    rows = {"Aiken": [_r("A1", 50.0), _r("A2", 9000.0), _r("A3", 10.0), _r("A4", 70.0)],
            "Barnwell": [_r("B1", 20.0), _r("B2", 5.0)]}
    plan = {("Aiken", "A1"): {"tier": "HOT", "has_detail": False},
            ("Aiken", "A2"): {"tier": "COLD", "has_detail": False},
            ("Aiken", "A3"): {"tier": "WARM", "has_detail": False},
            ("Aiken", "A4"): {"tier": "HOT", "has_detail": True},       # already done: skip
            ("Barnwell", "B1"): {"tier": "WARM", "has_detail": False}}
    order = [r["ident"] for _c, r in q.ordered_detail_targets(rows, {}, plan, cap=10)]
    # HOT, WARM (larger balance first), COLD, then no tier; the detailed parcel is skipped
    assert order == ["A1", "B1", "A3", "A2", "B2"]
    grouped = q.stage_detail_targets(rows, {}, plan, cap=10)
    assert [r["ident"] for r in grouped["Aiken"]] == ["A1", "A3", "A2"]


def test_the_cap_takes_the_highest_priority_parcels_only():
    rows = {"Aiken": [_r("A1", 1.0), _r("A2", 2.0), _r("A3", 3.0)]}
    plan = {("Aiken", "A1"): {"tier": "HOT", "has_detail": False}}
    t = q.stage_detail_targets(rows, {}, plan, cap=2)
    assert [r["ident"] for r in t["Aiken"]] == ["A1", "A3"]   # HOT first, then $3 over $2


def test_one_row_per_parcel_and_only_parcels_that_survived_the_filter():
    rows = {"Aiken": [_r("A1", 5.0, "r1"), _r("A1", 50.0, "r2"), _r("A9", 99.0)]}
    t = q.stage_detail_targets(rows, {"Aiken": {"A1"}}, {}, cap=10)
    assert [(r["ident"], r["amount"]) for r in t["Aiken"]] == [("A1", 50.0)]


def test_board_plan_reads_tier_and_existing_detail(monkeypatch):
    rows = [
        {"source": "counties_sc.qpaybill_delinquent_roll", "county": "Aiken",
         "raw": {"qpaybill_roll": {"identification_no": "A1", "county": "Aiken",
                                    "detail": {"appraised_value": 1.0}},
                 "distress_stack": {"tier": "WARM"}}},
        {"source": "counties_sc.qpaybill_delinquent_roll", "county": "Aiken",
         "raw": {"qpaybill_roll": {"identification_no": "A2", "county": "Aiken"},
                 "distress_stack": {"tier": "HOT"}}},
        {"source": "other.source", "raw": {}},
    ]
    import foreclosure_scraper.board_stream as bs
    monkeypatch.setattr(bs, "iter_board_rows", lambda path=None: iter(rows))
    plan = q.board_detail_plan("unused")
    assert plan == {("Aiken", "A1"): {"tier": "WARM", "has_detail": True},
                    ("Aiken", "A2"): {"tier": "HOT", "has_detail": False}}


def test_an_unreadable_board_gives_an_empty_plan(monkeypatch):
    import foreclosure_scraper.board_stream as bs

    def boom(path=None):
        raise FileNotFoundError(path)
    monkeypatch.setattr(bs, "iter_board_rows", boom)
    assert q.board_detail_plan("missing") == {}


class _Resp:
    def __init__(self, text):
        self.text = text


class _SeqClient:
    def __init__(self):
        self.inflight = 0
        self.max_inflight = 0
        self.urls = []

    async def get(self, url):
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        self.urls.append(url)
        await asyncio.sleep(0)
        self.inflight -= 1
        return _Resp("Notice # 1\\nBalance Due: $10.00\\nTotal Appraisal: $5,000\\n")


def test_detail_requests_are_one_at_a_time_and_paced(monkeypatch):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        sleeps.append(s)
        await real_sleep(0)
    monkeypatch.setattr(q.asyncio, "sleep", fake_sleep)
    c = _SeqClient()
    hrefs = [_r(f"A{i}", 1.0)["detail_href"] for i in range(3)]
    got = asyncio.run(q.fetch_details_paced(c, "sample", hrefs, {}, pace_s=1.6))
    assert c.max_inflight == 1 and len(c.urls) == 3
    assert [s for s in sleeps if s == 1.6] == [1.6, 1.6]
    assert set(got) == {"A0", "A1", "A2"}
