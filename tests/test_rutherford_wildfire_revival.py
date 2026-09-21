"""Revival tests for the Rutherford Sturgis/Avalon Wildfire scraper (2026-09-21).

Offline. A tiny in-memory fake of the Avalon API stands in for the CDN: it mints a
SearchToken on page 1, demands it on later pages (401 otherwise), pages 20 at a time per
tax-year facet, and answers HTTP 200 with an HTML "Data Only" page unless the request
carries ``Accept: application/json``, which is the silent-success trap found live on
2026-09-21.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.counties_nc import rutherford_wildfire_tax as m

FIX = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# fake API
# --------------------------------------------------------------------------- #

def _bill(parcel: str, year: int, due: float, kind: str = "REI", n: int = 0,
          situs: str = "12 OAK ST FOREST CITY NC 28043") -> dict:
    return {
        "AbstractType": kind, "ParcelNumber": parcel if kind == "REI" else "",
        "BillYear": year, "Bill": f"{parcel or 'P'}{n:04d}-{year}", "IDHash": f"h-{parcel}-{year}-{kind}-{n}",
        "BillType": "REG", "Description": "LOT 1 PL 1-1", "Acres": None,
        "OwnerName1": f"OWNER {parcel}", "OwnerName2": "", "OwnerName3": "",
        "OwnerAddress": {"Line1": "1 MAIN", "City": "FOREST CITY", "State": "NC", "Zip": "28043"},
        "SitusAddress": {"Line1": situs},
        "FlagsString": "DLQ,ADVERTISED",
        "Flags": [{"Description": "DELINQUENT"}, {"Description": "ADVERTISED"}],
        "Values": {"AmountDue": due, "OriginalAmountDue": due - 5.0, "RealValue": 100000.0},
    }


class FakeResp:
    def __init__(self, status=200, body=None, text=None, ctype="application/json; charset=utf-8",
                 headers=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.headers = {"content-type": ctype, **(headers or {})}

    def json(self):
        return json.loads(self.text)


class FakeApi:
    """years -> list of bills. Records every request for assertions."""

    def __init__(self, by_year: dict[int, list[dict]]):
        self.by_year = by_year
        self.calls: list[dict] = []
        self.tokens: set[str] = set()
        self.script: list = []          # queued FakeResp overrides, consumed first

    async def post(self, url, content=None, headers=None):
        body = json.loads(content)
        self.calls.append({"skip": body["skip"], "headers": dict(headers or {}),
                           "years": sorted(body["facets"]["Years"])})
        if self.script:
            return self.script.pop(0)
        if "json" not in (headers or {}).get("Accept", ""):
            return FakeResp(200, text="<html><title>Avalon :: Data Only</title></html>",
                            ctype="text/html")
        yrs = [int(y) for y in body["facets"]["Years"]]
        rows = [b for y in yrs for b in self.by_year.get(y, [])]
        tok = (headers or {}).get("SearchToken")
        if body["skip"] > 0 and tok not in self.tokens:
            return FakeResp(401, text="")
        if body["skip"] == 0:
            tok = f"tok{len(self.tokens)}"
            self.tokens.add(tok)
        page = rows[body["skip"]: body["skip"] + 20]
        return FakeResp(200, {"SearchToken": tok, "TotalRecords": len(rows), "Records": page,
                              "Facets": {}})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(m, "BILLS_PATH", tmp_path / "bills.jsonl")
    monkeypatch.setattr(m, "EXTRA_DELAY_S", 0.0)
    monkeypatch.delenv("ROBOTS_STRICT", raising=False)
    monkeypatch.setattr(m, "_delinquent_years", lambda today=None: [2025, 2024])

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(m.asyncio, "sleep", no_sleep)

    async def no_shell(*a, **k):
        return "<html></html>"
    monkeypatch.setattr(m, "get_text", no_shell)
    return tmp_path


def _install(monkeypatch, api: FakeApi):
    @asynccontextmanager
    async def fake_client(**kw):
        yield api
    monkeypatch.setattr(m, "client", fake_client)


def _run(scraper=None):
    s = scraper or m.RutherfordWildfireDelinquent()
    return s, asyncio.run(s.safe_run())


def _api(n_parcels=30):
    """30 real parcels: every one owes TY2025, the first 10 also owe TY2024; plus
    personal-property bills that must never become leads."""
    y25 = [_bill(f"{1000 + i}", 2025, 100.0 + i) for i in range(n_parcels)]
    y25 += [_bill("", 2025, 9.0, kind="IND", n=i) for i in range(15)]
    y24 = [_bill(f"{1000 + i}", 2024, 50.0) for i in range(10)]
    y24 += [_bill("", 2024, 4.0, kind="BUS", n=i) for i in range(6)]
    return FakeApi({2025: y25, 2024: y24})


# --------------------------------------------------------------------------- #
# the silent-success trap and the wall rules
# --------------------------------------------------------------------------- #

def test_every_post_asks_for_json(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    _run()
    assert api.calls
    assert all("application/json" in c["headers"]["Accept"] for c in api.calls)


def test_html_data_only_page_is_an_error_not_an_empty_result(env, monkeypatch):
    """The exact live failure: HTTP 200 + text/html. Must raise, never return []."""
    api = _api()
    api.script = [FakeResp(200, text="<html><title>Avalon :: Data Only</title></html>",
                           ctype="text/html")]
    _install(monkeypatch, api)
    with pytest.raises(m.WildfireNotJson) as ei:
        asyncio.run(_one_page(api))
    assert "Data Only" in str(ei.value)


async def _one_page(api):
    return await m._post_page(api, "u", {"skip": 0, "facets": m._facets([2025])}, None)


def test_challenge_page_is_a_wall(env, monkeypatch):
    api = _api()
    api.script = [FakeResp(200, text="<html>Please complete the CAPTCHA</html>", ctype="text/html")]
    with pytest.raises(m.WildfireWall):
        asyncio.run(_one_page(api))


def test_403_aborts_the_whole_sweep_and_reports_blocked(env, monkeypatch):
    api = _api()
    api.script = [FakeResp(403, text="forbidden", ctype="text/html")]
    _install(monkeypatch, api)
    s, out = _run()
    assert out == []
    assert s.last_outcome == "BLOCKED"
    assert len(api.calls) == 1            # no probing around a wall


def test_403_after_progress_still_ships_what_was_collected(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    real_post = api.post
    state = {"n": 0}

    async def flaky(url, content=None, headers=None):
        state["n"] += 1
        if state["n"] == 3:               # page 1 ok, page 2 ok, page 3 blocked
            return FakeResp(403, text="forbidden", ctype="text/html")
        return await real_post(url, content=content, headers=headers)
    api.post = flaky
    s, out = _run()
    assert s.last_outcome == "OK"
    assert len(out) > 0                   # the 40 bills before the wall became leads


def test_429_honours_retry_after_then_succeeds(env, monkeypatch):
    api = _api()
    api.script = [FakeResp(429, text="slow down", headers={"retry-after": "7"})]
    _install(monkeypatch, api)
    waits = []

    async def rec_sleep(sec):
        waits.append(sec)
    monkeypatch.setattr(m.asyncio, "sleep", rec_sleep)
    s, out = _run()
    assert 7.0 in waits
    assert len(out) == 30


def test_retry_after_is_capped_and_parses_http_dates():
    class H(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    assert m._retry_after_s(H({"retry-after": "9999"}), 1.0) == m.RETRY_AFTER_CAP_S
    assert m._retry_after_s(H({}), 12.0) == 12.0
    assert m._retry_after_s(H({"retry-after": "not a date"}), 5.0) == 5.0


def test_persistent_429_gives_up_after_max_attempts(env, monkeypatch):
    api = _api()
    api.script = [FakeResp(429, text="x")] * m.MAX_ATTEMPTS
    with pytest.raises(RuntimeError):
        asyncio.run(_one_page(api))
    assert len(api.calls) == m.MAX_ATTEMPTS


def test_rejected_token_is_reminted(env, monkeypatch):
    api = _api(n_parcels=60)              # 75 bills in TY2025 = 4 pages
    _install(monkeypatch, api)
    real_post = api.post
    n = {"i": 0}

    async def drop_token_once(url, content=None, headers=None):
        n["i"] += 1
        if n["i"] == 3:                    # 3rd request would be page 2: reject its token
            return FakeResp(401, text="")
        return await real_post(url, content=content, headers=headers)
    api.post = drop_token_once
    s, out = _run()
    assert len(out) == 60


# --------------------------------------------------------------------------- #
# robots flag: off by default, ROBOTS_STRICT=1 restores the fail-closed gate
# --------------------------------------------------------------------------- #

def test_robots_preflight_is_off_by_default(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    called = []

    async def boom(*a, **k):
        called.append(1)
        return True
    monkeypatch.setattr(m, "_robots_blocks", boom)
    s, out = _run()
    assert not called
    assert len(out) == 30


def test_robots_strict_flag_restores_the_fail_closed_gate(env, monkeypatch):
    monkeypatch.setenv("ROBOTS_STRICT", "1")
    api = _api()
    _install(monkeypatch, api)

    async def blocked(*a, **k):
        return True
    monkeypatch.setattr(m, "_robots_blocks", blocked)
    s, out = _run()
    assert out == []
    assert api.calls == []                # not one API request while the flag is on


def test_robots_code_path_is_still_there():
    assert m._path_disallowed("User-agent: *\nDisallow: /\n", "/data/x") is True


# --------------------------------------------------------------------------- #
# paging, resume, cache
# --------------------------------------------------------------------------- #

def test_paging_is_sequential_20_at_a_time_and_echoes_the_token(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    _run()
    ty25 = [c for c in api.calls if c["years"] == ["2025"]]
    assert [c["skip"] for c in ty25] == [0, 20, 40]          # 45 bills -> 3 pages
    assert "SearchToken" not in ty25[0]["headers"]
    assert all(c["headers"].get("SearchToken") for c in ty25[1:])


def test_one_lead_per_parcel_with_per_year_detail(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    s, out = _run()
    assert len(out) == 30                                     # 30 parcels, not 40 bills
    by = {li.parcel_id: li for li in out}
    two_year = by["1003"]
    r = two_year.raw["rutherford_wildfire"]
    assert r["tax_years"] == [2025, 2024]
    assert r["amount_by_year"] == {"2025": 103.0, "2024": 50.0}
    assert [d["year"] for d in r["years_detail"]] == [2025, 2024]
    assert two_year.judgment_amount == 153.0
    assert two_year.listing_type.value == "tax_lien"
    assert r["oldest_delinquent_year"] == 2024
    assert by["1020"].raw["rutherford_wildfire"]["tax_years"] == [2025]


def test_personal_property_never_becomes_a_lead(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    s, out = _run()
    assert all(li.parcel_id for li in out)
    bills = m._load_bills()
    assert {b["AbstractType"] for b in bills} == {"REI"}     # only real estate is even stored


def test_interrupted_sweep_resumes_at_the_recorded_skip(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    s = m.RutherfordWildfireDelinquent()
    s.max_pages_total = 2                                     # stop after 2 pages of TY2025
    _, first = _run(s)
    st = json.loads(m.STATE_PATH.read_text())
    assert st["years"]["2025"]["next_skip"] == 40 and not st["years"]["2025"]["done"]
    assert st["complete"] is False
    assert len(api.calls) == 2                                # exactly the 2 budgeted pages

    api2 = _api()
    _install(monkeypatch, api2)
    _, out = _run()                                           # unlimited second run
    ty25_skips = [c["skip"] for c in api2.calls if c["years"] == ["2025"]]
    assert ty25_skips[:2] == [0, 40]                          # re-mint page 0, then resume at 40
    assert 20 not in ty25_skips                               # pages 0-1 were NOT re-fetched
    assert len(out) == 30                                     # nothing lost, nothing doubled
    assert json.loads(m.STATE_PATH.read_text())["complete"] is True


def test_complete_recent_sweep_is_served_from_cache_with_zero_requests(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    _run()
    api2 = _api()
    _install(monkeypatch, api2)
    _, out = _run()
    assert api2.calls == []
    assert len(out) == 30


def test_stale_state_is_ignored_and_restarted(env, monkeypatch):
    api = _api()
    _install(monkeypatch, api)
    _run()
    st = json.loads(m.STATE_PATH.read_text())
    st["updated_at"] -= 3600 * (m.RESUME_MAX_AGE_H + 1)
    m.STATE_PATH.write_text(json.dumps(st))
    api2 = _api()
    _install(monkeypatch, api2)
    _, out = _run()
    assert api2.calls                                         # re-swept
    assert len(out) == 30                                     # and the bills file was reset, no doubling


def test_replayed_page_never_double_counts_an_amount(env):
    recs = [_bill("77", 2025, 100.0), _bill("77", 2025, 100.0)]   # same IDHash twice
    out = m._records_to_listings(recs, "u")
    assert len(out) == 1 and out[0].judgment_amount == 100.0


def test_year_shortfall_is_logged(env, monkeypatch):
    api = _api()
    real_post = api.post

    async def lie(url, content=None, headers=None):
        r = await real_post(url, content=content, headers=headers)
        if r.status_code == 200:
            p = json.loads(r.text)
            p["TotalRecords"] = 1000                          # server claims far more than it serves
            p["Records"] = p["Records"][:5]
            return FakeResp(200, p)
        return r
    api.post = lie
    _install(monkeypatch, api)
    seen = []
    monkeypatch.setattr(m.log, "warning", lambda ev, **kw: seen.append(ev))
    _run()
    assert "rutherford_wildfire.year_short" in seen


def test_apply_row_limit_caps_pages():
    s = m.RutherfordWildfireDelinquent()
    s.apply_row_limit(200)
    assert s.max_pages_total == 34                            # ceil(200 / 6)
    s.apply_row_limit(1)
    assert s.max_pages_total == 1


# --------------------------------------------------------------------------- #
# situs handling on the real recorded payload
# --------------------------------------------------------------------------- #

def test_house_number_zero_is_a_vacant_lot_not_an_address():
    payload = json.loads((FIX / "rutherford_wildfire_records_page1.json").read_text())
    out = {li.parcel_id: li for li in m._records_to_listings(payload["Records"], "u")}
    glen = out["1638529"]                                     # "0 GLEN RIDGE TRL LAKE LURE NC 28746"
    assert glen.street_address is None
    assert glen.raw["rutherford_wildfire"]["situs_vacant_lot"] is True
    assert glen.raw["rutherford_wildfire"]["situs_raw"].startswith("0 GLEN RIDGE")
    assert out["232588"].street_address == "307 PEARTREE DR"
    assert out["232588"].raw["rutherford_wildfire"]["situs_vacant_lot"] is False


def test_chimney_rock_village_city_is_split():
    rec = _bill("5", 2025, 10.0, situs="390 MAIN ST CHIMNEY ROCK VILLAGE NC 28720")
    li = m._records_to_listings([rec], "u")[0]
    assert (li.street_address, li.city, li.zip_code) == ("390 MAIN ST", "Chimney Rock Village", "28720")


def test_rows_survive_the_orchestrator_filters():
    """Not just parseable: they must pass the SAME scope + dateless gates main applies."""
    from foreclosure_scraper.main import _active_only, _in_scope
    li = m._records_to_listings([_bill("9", 2025, 10.0)], "u")[0]
    assert _in_scope(li) and _active_only(li, 180)
