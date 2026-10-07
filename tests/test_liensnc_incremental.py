"""LiensNC incremental refresh and its Mac -> VM hand-off.

Every fixture here is hand-written: made-up people, streets, entry numbers and phone numbers
(555-01xx), example.com mail. No real filing, no network, and no account: the login tests
answer from an httpx.MockTransport.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import scrape_liensnc as sl  # noqa: E402

from foreclosure_scraper import liensnc_handoff as lh  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402


# ---- fixtures -----------------------------------------------------------------------------

def _row(entry: int, filed: str, *, street: str | None = None, county: str = "Testcase",
         owner: str = "Pat Placeholder", related: str = "No", pin: str | None = None,
         lot_label: bool = False) -> str:
    street = street or f"{entry % 900 + 10} Example Ln"
    prop = [f"Sample Project {entry}"]
    if lot_label:
        prop.append("Lot 4 Example Ln Subdivision")
    if pin:
        prop.append(f"PIN {pin}")
    prop += [street, "Sampleton,", "NC 28000", f"{county} County"]
    owner_cell = [owner, "99 Mailing Rd", "Othertown, NC 28001", "United States",
                  f"Phone: 555-010-{entry % 10000:04d}", f"owner{entry}@example.com"]
    return (
        '<tr class="filingRow">'
        f'<td>Appointment of Lien Agent<br>{filed}<br>Entry #: {entry}'
        f'<a href="/scr/appointment/details.html?entryNumber={entry}&printable=">view</a></td>'
        f'<td>agent{entry}</td>'
        f'<td>{"<br>".join(prop)}</td>'
        f'<td>{"<br>".join(owner_cell)}</td>'
        f'<td><a href="#">{related}</a></td><td>-</td></tr>')


def _page(rows: list[str], total_pages: int | None = None) -> str:
    head = ('<table class="table table-striped" id="filingList"><thead><tr><th>Filing</th>'
            '<th>Filed By</th><th>Project Property</th><th>Owner</th><th>Related</th>'
            '<th>Action</th></tr></thead><tbody>')
    pager = f'<div style="font-style: italic">({total_pages} pages)</div>' if total_pages else ""
    return f"<html><body>{head}{''.join(rows)}</tbody></table>{pager}</body></html>"


def _pages(spec: list[list[tuple[int, str]]]) -> dict[int, str]:
    """{page number: html} from [[(entry, filing date), ...] per page]."""
    total = len(spec)
    return {i + 1: _page([_row(e, d) for e, d in rows], total) for i, rows in enumerate(spec)}


class FakeSite:
    """get_page() over fixed pages; records every page asked for."""

    def __init__(self, pages: dict[int, str]):
        self.pages, self.asked = pages, []

    async def get_page(self, page: int, since: str, until: str) -> str:
        self.asked.append((page, since))
        return self.pages.get(page, _page([]))


def _scan(site, **kw):
    kw.setdefault("board_ids", set())
    kw.setdefault("known_cutoff", None)
    kw.setdefault("since", "09/01/2026")
    kw.setdefault("until", "10/07/2026")
    kw.setdefault("log", lambda m: None)
    return asyncio.run(sl.scan_incremental(site.get_page, **kw))


def _entries(res) -> list[int]:
    return [int(r["entry_number"]) for r in res["new"]]


# ---- the incremental stop rule ------------------------------------------------------------

def test_stops_after_n_consecutive_known_rows_and_keeps_only_new_ones():
    p1 = [(5000 - i, "10/06/2026") for i in range(50)]                         # all new
    p2 = [(4950 - i, "10/05/2026") for i in range(10)] + \
         [(4940 - i, "10/05/2026") for i in range(40)]                         # 10 new, 40 known
    p3 = [(4900 - i, "10/04/2026") for i in range(50)]                         # all known
    p4 = [(4850 - i, "10/03/2026") for i in range(50)]
    site = FakeSite(_pages([p1, p2, p3, p4]))
    known = {str(e) for e, _ in p2[10:] + p3 + p4}
    res = _scan(site, board_ids=known, stop_after_known=60, page_size=50)
    assert res["stop_reason"] == "known_run" and res["complete"]
    assert [p for p, _ in site.asked] == [1, 2, 3]          # page 4 is never requested
    assert _entries(res) == [e for e, _ in p1 + p2[:10]]
    assert res["total_pages"] == 4


def test_rows_filed_before_the_cutoff_count_as_known_without_their_id():
    p1 = [(900 - i, "10/02/2026") for i in range(30)] + \
         [(870 - i, "08/20/2026") for i in range(20)]                          # older than cutoff
    p2 = [(850 - i, "08/19/2026") for i in range(50)]
    site = FakeSite(_pages([p1, p2]))
    res = _scan(site, known_cutoff=date(2026, 8, 23), stop_after_known=40)
    assert res["stop_reason"] == "known_run"
    assert _entries(res) == [e for e, _ in p1[:30]]
    # a row filed on/after the cutoff is checked by its entry number, not its date
    site2 = FakeSite(_pages([[(77, "08/24/2026"), (76, "08/23/2026")]]))
    assert _entries(_scan(site2, known_cutoff=date(2026, 8, 23))) == [77, 76]


def test_a_new_row_restarts_the_count():
    p1 = [(100, "10/06/2026"), (99, "10/06/2026"), (98, "10/06/2026"), (97, "10/06/2026"),
          (96, "10/06/2026"), (95, "10/05/2026")]
    site = FakeSite(_pages([p1]))
    res = _scan(site, board_ids={"100", "99", "97", "96", "95"}, stop_after_known=3, page_size=6)
    assert _entries(res) == [98]
    assert res["stop_reason"] == "known_run"


def test_handed_off_rows_neither_stop_nor_restart_the_count():
    """A filing sent on an earlier cycle and not on the board yet is skipped, and the scan
    keeps walking down to the board's own frontier instead of stopping on it."""
    p1 = [(300 - i, "10/06/2026") for i in range(50)]
    p2 = [(250 - i, "10/05/2026") for i in range(50)]
    site = FakeSite(_pages([p1, p2, [(200, "10/04/2026"), (199, "10/04/2026")]]))
    neutral = {str(e) for e, _ in p1[5:] + p2}
    res = _scan(site, neutral_ids=neutral, board_ids={"200", "199"}, stop_after_known=2)
    assert _entries(res) == [300, 299, 298, 297, 296]
    assert res["stop_reason"] == "known_run" and [p for p, _ in site.asked] == [1, 2, 3]


def test_end_of_results_and_short_last_page_complete_the_scan(tmp_path):
    ck = tmp_path / "ck.json"
    site = FakeSite(_pages([[(10, "10/06/2026"), (9, "10/06/2026")]]))
    res = _scan(site, checkpoint_path=ck)
    assert res["stop_reason"] == "last_page" and res["complete"] and not ck.exists()
    empty = FakeSite({})
    assert _scan(empty)["stop_reason"] == "end_of_results"


# ---- resume -------------------------------------------------------------------------------

def test_page_cap_keeps_a_checkpoint_and_the_next_call_resumes_it(tmp_path):
    ck = tmp_path / "data" / "liensnc" / "incremental_checkpoint.json"
    spec = [[(1000 - 50 * p - i, "10/0%d/2026" % (6 - p)) for i in range(50)] for p in range(4)]
    spec.append([(700, "08/01/2026")])
    site = FakeSite(_pages(spec))
    first = _scan(site, max_pages=2, checkpoint_path=ck, since="09/20/2026",
                  known_cutoff=date(2026, 9, 1), stop_after_known=1)
    assert first["stop_reason"] == "page_cap" and not first["complete"]
    saved = json.loads(ck.read_text())
    # the full scrape's checkpoint shape, plus the window it scans
    assert saved["last_page"] == 2 and len(saved["results"]) == 100
    assert saved["since"] == "09/20/2026" and saved["known_cutoff"] == "09/01/2026"

    # next cycle: a newer frontier is passed in, but the unfinished scan wins
    second = _scan(site, max_pages=10, checkpoint_path=ck, since="10/01/2026",
                   known_cutoff=date(2026, 10, 5), stop_after_known=1)
    assert second["resumed"] and second["complete"] and not ck.exists()
    assert [p for p, _ in site.asked] == [1, 2, 3, 4, 5]     # pages 1-2 are not fetched again
    assert {s for _, s in site.asked} == {"09/20/2026"}
    assert second["new_this_call"] == 100 and len(second["new"]) == 200


def test_resumed_scan_is_not_stopped_by_rows_that_moved_down_a_page(tmp_path):
    """New filings arrive between cycles and push rows down the newest-first list: the
    resumed page repeats rows seen last time. Those are neither new nor known."""
    ck = tmp_path / "ck.json"
    p1 = [(500 - i, "10/06/2026") for i in range(50)]
    p2_before = [(450 - i, "10/05/2026") for i in range(50)]
    site = FakeSite(_pages([p1, p2_before, p2_before]))
    _scan(site, max_pages=1, checkpoint_path=ck, stop_after_known=5)
    shifted_p2 = p1[-20:] + [(450 - i, "10/05/2026") for i in range(30)]        # 20 repeats
    site.pages = _pages([p1, shifted_p2, [(420 - i, "10/05/2026") for i in range(10)]])
    res = _scan(site, checkpoint_path=ck, stop_after_known=5, board_ids=set())
    assert res["resumed"] and res["complete"]
    assert len(set(_entries(res))) == len(_entries(res)) == 90


# ---- the network layer: login failure, CAPTCHA, session loss, pacing ------------------------

class FakeClock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_login_failure_stops_at_once_with_a_clear_message_and_no_retry(tmp_path):
    calls = Counter()

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        calls[(req.method, path)] += 1
        if path.endswith("j_spring_security_check"):
            return httpx.Response(302, headers={"Location": sl.LOGIN_URL + "?error=1"})
        return httpx.Response(200, text="<html>Sign in to LiensNC</html>")

    clock = FakeClock()

    async def go():
        async with _client(handler) as c:
            await sl.fetch_incremental(
                board_ids=set(), known_cutoff=None, since="09/01/2026", until="10/07/2026",
                client=c, checkpoint_path=tmp_path / "ck.json",
                pacer=sl.Pacer(clock=clock, sleep=clock.sleep), log=lambda m: None)

    with pytest.raises(sl.LoginFailed) as exc:
        asyncio.run(go())
    msg = str(exc.value)
    assert "login failed" in msg.lower() and "not retried" in msg.lower()
    assert sl.LIENSNC_PASS not in msg                                  # never echoes the account
    if len(sl.LIENSNC_USER) >= 5:
        assert sl.LIENSNC_USER not in msg
    assert calls[("POST", "/scr/j_spring_security_check")] == 1
    assert not any(p.endswith("advancedSearch.html") for _, p in calls)
    assert not (tmp_path / "ck.json").exists()


def test_login_failure_in_a_cycle_still_hands_off_pending_rows(tmp_path):
    led = lh.Ledger(tmp_path / lh.LEDGER_NAME)
    led.add([_record(4242, "10/01/2026")], date(2026, 10, 6))
    led.save()

    async def refuse(**kw):
        raise sl.LoginFailed("LiensNC login failed: the site sent the login page back.")

    rows, report = asyncio.run(lh.run_cycle(
        state_dir=tmp_path, index=lh.BoardIndex(newest_filing=date(2026, 9, 30)),
        fetch=refuse, today=date(2026, 10, 7), log=lambda m: None))
    assert report["scan"]["stop_reason"] == "login_failed"
    assert [li.case_number for li in rows] == ["4242"]
    assert json.loads((tmp_path / lh.REPORT_NAME).read_text())["scan"]["stop_reason"] == \
        "login_failed"


def test_scraper_raises_a_clear_error_when_login_fails_and_nothing_is_pending(tmp_path,
                                                                             monkeypatch):
    from foreclosure_scraper.scrapers.counties_generic import liensnc as mod

    async def fake_cycle(**kw):
        return [], {"scan": {"stop_reason": "login_failed",
                             "error": "LiensNC login failed: the site sent the login page back."}}

    monkeypatch.setattr(lh, "run_cycle", fake_cycle)
    monkeypatch.delenv("FORECLOSURE_ROLE", raising=False)
    s = mod.LiensNCIncrementalScraper()
    out = asyncio.run(s.safe_run())
    assert out == [] and s.last_outcome == "ERROR" and "login_failed" in s.last_reason


def test_captcha_stops_the_scan_and_holds_later_cycles(tmp_path):
    clock = FakeClock()
    served = Counter()

    def handler(req: httpx.Request) -> httpx.Response:
        served[req.url.path] += 1
        if req.url.path.endswith("j_spring_security_check"):
            return httpx.Response(302, headers={"Location": "https://apps.liensnc.com/scr/"})
        if req.url.path.endswith("advancedSearch.html"):
            return httpx.Response(200, text='<div class="g-recaptcha"></div>')
        return httpx.Response(200, text="<html>ok</html>")

    async def fetch(**kw):
        async with _client(handler) as c:
            return await sl.fetch_incremental(client=c, pacer=sl.Pacer(clock=clock,
                                                                       sleep=clock.sleep), **kw)

    rows, report = asyncio.run(lh.run_cycle(
        state_dir=tmp_path, index=lh.BoardIndex(newest_filing=date(2026, 9, 30)),
        fetch=fetch, today=date(2026, 10, 7), log=lambda m: None))
    assert report["scan"]["stop_reason"] == "captcha" and rows == []
    assert served["/scr/filing/advancedSearch.html"] == 1          # stopped on the first page
    assert (tmp_path / lh.CAPTCHA_HOLD_NAME).exists()

    async def must_not_run(**kw):
        raise AssertionError("no login while a CAPTCHA hold is in place")

    _, again = asyncio.run(lh.run_cycle(
        state_dir=tmp_path, index=lh.BoardIndex(), fetch=must_not_run,
        today=date(2026, 10, 8), log=lambda m: None))
    assert again["scan"]["stop_reason"] == "captcha_hold"


def test_session_expiry_gets_one_relogin_then_stops_with_a_checkpoint(tmp_path):
    clock = FakeClock()
    logins = Counter()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("j_spring_security_check"):
            logins["post"] += 1
            return httpx.Response(302, headers={"Location": "https://apps.liensnc.com/scr/"})
        if req.url.path.endswith("advancedSearch.html"):
            page = int(req.url.params.get("currentPage"))
            if page == 1:
                return httpx.Response(200, text=_page(
                    [_row(9000 - i, "10/06/2026") for i in range(50)], 5))
            return httpx.Response(302, headers={"Location": sl.LOGIN_URL})
        return httpx.Response(200, text="<html>Sign in</html>")

    async def go():
        async with _client(handler) as c:
            return await sl.fetch_incremental(
                board_ids=set(), known_cutoff=None, since="09/01/2026", until="10/07/2026",
                client=c, checkpoint_path=tmp_path / "ck.json",
                pacer=sl.Pacer(clock=clock, sleep=clock.sleep), log=lambda m: None)

    res = asyncio.run(go())
    assert res["stop_reason"] == "session_lost" and not res["complete"]
    assert logins["post"] == 2                                    # the first login + one more
    assert len(res["new"]) == 50 and json.loads((tmp_path / "ck.json").read_text())[
        "last_page"] == 1


def test_requests_are_at_least_1_6_seconds_apart():
    clock = FakeClock()
    starts = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path != "/scr/":            # a followed redirect is part of the same request
            starts.append(clock.t)
        if req.url.path.endswith("j_spring_security_check"):
            return httpx.Response(302, headers={"Location": "https://apps.liensnc.com/scr/"})
        if req.url.path.endswith("advancedSearch.html"):
            page = int(req.url.params.get("currentPage"))
            return httpx.Response(200, text=_page(
                [_row(8000 - 50 * page - i, "10/06/2026") for i in range(50)], 3))
        return httpx.Response(200, text="<html>Sign in</html>")

    async def go():
        async with _client(handler) as c:
            return await sl.fetch_incremental(
                board_ids=set(), known_cutoff=None, since="09/01/2026", until="10/07/2026",
                client=c, checkpoint_path=None, delay=0.1,           # asks for less: floored
                pacer=sl.Pacer(0.1, clock=clock, sleep=clock.sleep), log=lambda m: None)

    res = asyncio.run(go())
    assert res["pages_fetched"] == 3 and len(starts) == 5            # GET, POST, 3 pages
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert sl.MIN_DELAY_S == 1.6 and min(gaps) >= 1.6 - 1e-9


def test_search_params_bound_the_window_and_sort_newest_first():
    p = sl.search_params("08/22/2026", "10/07/2026", 3)
    assert p["filingDateFrom"] == "08/22/2026" and p["filingDateTo"] == "10/07/2026"
    assert p["sort"] == "FILING_DATE" and p["sortDesc"] == "true" and p["currentPage"] == "3"
    assert sl.page_count('<div style="x"> (246 pages) </div>') == 246


# ---- what the board holds, and the ledger ---------------------------------------------------

def _record(entry: int, filed: str, **kw) -> dict:
    return sl.parse_results(_page([_row(entry, filed, **kw)]))[0]


def test_board_index_reads_entry_numbers_from_every_place_a_row_keeps_them():
    rows = [
        {"source": "counties_generic.liensnc", "case_number": "111",
         "source_url": "https://apps.liensnc.com/scr/appointment/details.html?entryNumber=111",
         "street_address": "10 Example Ln",
         "raw": {"liensnc": {"entry_number": "111", "filing_date": "08/26/2026"}}},
        {"source": "liensnc", "case_number": "222", "street_address": "10  example ln",
         "raw": {"liensnc": {"entry_number": "222", "filing_date": "08/20/2026"}}},
        {"source": "counties_nc.sample_vacant", "street_address": "10 Example Ln",
         "raw": {"also_seen_in": [{"source": "counties_generic.liensnc",
                                   "url": "https://x/details.html?entryNumber=333&printable="}],
                 "liensnc": {"entry_number": "444", "filing_date": "08/21/2026"}}},
        {"source": "counties_nc.sample_tax", "case_number": "555", "raw": {}},
    ]
    idx = lh.index_rows(rows)
    assert idx.entries == {"111", "222", "333", "444"}
    assert idx.newest_filing == date(2026, 8, 26)
    assert idx.liensnc_rows == 2 and idx.addr_counts["10 EXAMPLE LN"] == 2


def test_ledger_drops_landed_rows_and_tombstones_ones_that_never_land(tmp_path):
    led = lh.Ledger(tmp_path / "l.json")
    led.add([_record(1, "10/01/2026"), _record(2, "10/01/2026"), _record(3, "10/05/2026")],
            date(2026, 9, 20))
    led.entries["3"]["first_sent"] = "2026-10-05"
    st = led.prune(lh.BoardIndex(entries={"1"}, newest_filing=date(2026, 10, 6)),
                   date(2026, 10, 7), max_days=10)
    assert st == {"landed": 1, "expired": 1}
    assert led.entries["2"]["state"] == "expired" and "record" not in led.entries["2"]
    assert set(led.pending()) == {"3"} and led.ids() == {"2", "3"}


def test_cycle_hands_off_new_and_pending_rows_and_counts_landed_ones(tmp_path):
    led = lh.Ledger(tmp_path / lh.LEDGER_NAME)
    led.add([_record(10, "10/03/2026"), _record(11, "10/03/2026")], date(2026, 10, 6))
    led.save()
    seen = {}

    async def fetch(**kw):
        seen.update(kw)
        return {"new": [_record(12, "10/06/2026")], "stop_reason": "known_run",
                "complete": True, "pages_fetched": 1}

    idx = lh.BoardIndex(entries={"10"}, newest_filing=date(2026, 10, 4))
    rows, report = asyncio.run(lh.run_cycle(state_dir=tmp_path, index=idx, fetch=fetch,
                                            today=date(2026, 10, 7), log=lambda m: None))
    assert sorted(li.case_number for li in rows) == ["11", "12"]
    assert report["ledger"]["landed"] == 1 and report["ledger"]["pending"] == 2
    # the window starts a few days before the board's newest filing; older rows are known
    assert seen["since"] == "09/30/2026" and seen["known_cutoff"] == date(2026, 10, 1)
    assert seen["neutral_ids"] == {"11"}
    assert seen["checkpoint_path"] == tmp_path / lh.CHECKPOINT_NAME


def test_proof_mode_writes_nothing(tmp_path):
    async def fetch(**kw):
        assert kw["checkpoint_path"] is None and kw["neutral_ids"] == set()
        return {"new": [_record(12, "10/06/2026")], "stop_reason": "page_cap", "complete": False}

    rows, report = asyncio.run(lh.run_cycle(
        state_dir=tmp_path, index=lh.BoardIndex(newest_filing=date(2026, 8, 26)), fetch=fetch,
        proof=True, today=date(2026, 10, 7), log=lambda m: None))
    assert len(rows) == 1 and report["found"]["nc_with_county"] == 1
    assert list(tmp_path.iterdir()) == []


# ---- the hand-off record ------------------------------------------------------------------

def test_handoff_record_is_shaped_like_the_liensnc_rows_on_the_board():
    rec = _record(2700123, "10/06/2026", related="Yes", pin="9600112233", lot_label=True,
                  street="512 Example Ln")
    li = lh.to_listing(rec, now=datetime(2026, 10, 7, 6, 0))
    assert li.source == "counties_generic.liensnc"
    assert li.case_number == "2700123" and li.listing_type.value == "tax_lien"
    assert li.source_url.endswith("details.html?entryNumber=2700123&printable=")
    assert li.sale_date == datetime(2026, 10, 6) and li.state == "NC"
    assert li.street_address == "512 Example Ln"                 # not the lot label
    assert (li.city, li.zip_code, li.county) == ("Sampleton", "28000", "Testcase")
    assert li.parcel_id == "9600112233" and li.owner_name == "Pat Placeholder"
    assert li.defendant == "agent2700123"
    raw = li.raw
    assert raw["liensnc"] == rec and raw["landed_by"] == "liensnc_handoff"
    assert raw["owner_phone"]["phone"] == "(555) 010-0123"
    assert raw["owner_phone"]["source"] == "liensnc_filing" and raw["owner_phone"]["needs_dnc_scrub"]
    assert raw["owner_email"] == {"email": "owner2700123@example.com", "source": "liensnc_filing"}
    assert raw["owner_mailing"]["mailing"].startswith("99 Mailing Rd")
    assert raw["builder_distress"] == {"related_filings": True, "cluster": False,
                                       "source": "liensnc"}

    # what scripts/run_stealth_sources.py writes, and national.stealth_handoff reads back
    lead = json.loads(li.model_dump_json())
    back = Listing.model_validate(lead)
    assert back.source == li.source and back.case_number == li.case_number
    assert back.dedupe_key() == li.dedupe_key() == "parcel:NC:testcase:9600112233"


def test_handoff_row_keeps_liensnc_lead_class_and_scope():
    from foreclosure_scraper.distress_score import _is_liensnc, sale_date_is_event
    from foreclosure_scraper.main import _in_scope

    li = lh.to_listing(_record(31, "10/06/2026", county="Wake"))
    assert _is_liensnc(li) and not sale_date_is_event(li)
    assert _in_scope(li)                          # statewide NC, deny-listed county included


def test_address_cluster_and_pin_guard():
    rec = _record(41, "10/06/2026", street="7 Example Ct", pin="ehurst")
    li = lh.to_listing(rec, addr_counts=Counter({"7 EXAMPLE CT": 2}))
    assert li.raw["builder_distress"]["cluster"] is True
    assert li.parcel_id is None                   # a PIN with no digit is a word, not a parcel
    assert lh.to_listing({"entry_number": ""}) is None


def test_scraper_is_mac_only_and_off_on_the_vm(monkeypatch):
    from foreclosure_scraper.scrapers.counties_generic import liensnc as mod
    from foreclosure_scraper.source_split import needs_mac

    monkeypatch.setenv("FORECLOSURE_ROLE", "vm")
    s = mod.LiensNCIncrementalScraper()
    assert s.slug == "counties_generic.liensnc" and needs_mac(s)
    assert s.disabled and "Mac only" in s.disabled_reason
    assert asyncio.run(s.safe_run()) == [] and s.last_outcome == "DORMANT"
    monkeypatch.delenv("FORECLOSURE_ROLE")
    monkeypatch.setenv("LIENSNC_HANDOFF", "0")
    assert mod.LiensNCIncrementalScraper().disabled
    monkeypatch.delenv("LIENSNC_HANDOFF")
    assert not mod.LiensNCIncrementalScraper().disabled


def test_street_suffix_must_be_a_whole_word():
    """A suffix inside a word ('pl' in Example, 'st' in Forest, 'rd' in Hardin) no longer
    ends the address early."""
    cases = {
        "Sample Project\n512 Example Ln\nSampleton,\nNC 28000": "512 Example Ln",
        "Sample Project\n100 Forest Ridge Rd\nSampleton,\nNC 28000": "100 Forest Ridge Rd",
        "Sample Project\n45 Hardin Rd.\nSampleton,\nNC 28000": "45 Hardin Rd.",
        "Lot 2 Westover St Subdivision\n18 Westover St\nSampleton,\nNC 28000": "18 Westover St",
    }
    for text, want in cases.items():
        assert sl._extract_address(text) == want


def test_rescan_from_walks_the_whole_window_and_requeues_given_up_rows(tmp_path):
    led = lh.Ledger(tmp_path / lh.LEDGER_NAME)
    led.entries["7"] = {"state": "expired", "filing_date": "09/01/2026",
                        "first_sent": "2026-09-02", "expired_on": "2026-09-13"}
    led.save()
    seen = {}

    async def fetch(**kw):
        seen.update(kw)
        return {"new": [_record(7, "09/01/2026")], "stop_reason": "last_page", "complete": True}

    rows, report = asyncio.run(lh.run_cycle(
        state_dir=tmp_path, index=lh.BoardIndex(newest_filing=date(2026, 10, 6)), fetch=fetch,
        rescan_from=date(2026, 8, 27), today=date(2026, 10, 7), log=lambda m: None))
    assert seen["since"] == "08/26/2026" and seen["known_cutoff"] == date(2026, 8, 27)
    assert seen["stop_after_known"] >= 10 ** 9 and seen["checkpoint_path"] is None
    assert seen["neutral_ids"] == set()                 # the tombstone no longer blocks it
    assert [li.case_number for li in rows] == ["7"] and report["rescan_from"] == "2026-08-27"
