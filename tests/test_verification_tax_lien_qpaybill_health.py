"""tax_lien_qpaybill v5 (2026-10-08): tenant health, the criteria a tenant offers, Horry's PIN
search, a confirmed answer bound to the row's address, and the framework pieces that keep a
source outage from costing a week (ledger.is_due's transient retry, the sweep's deferral, one
pacing slot for all qPayBill tenants).

What the 2026-10-08 sweep hit: Horry's form offers no Property Address search, and posting one
answers GenericErrorPage.aspx, which v4 took as a dead tenant (843 Horry rows unconfirmed); and
one minute of vendor-wide 503s / error pages at 18:34-18:35 UTC killed every other tenant for the
rest of the run. Every page here is hand-written in the portal's markup with made-up owners,
addresses and map numbers. No network."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import fetch as F
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.registry import discover, from_module
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as q

TODAY = date(2026, 10, 8)
FULL = (("Receipt", "Notice Number"), ("Map", "Map Number"), ("Name", "Owner Name"),
        ("DOR", "Tax ID"), ("Address", "Property Address"))
HORRY = (("Receipt", "Notice Number"), ("Map", "Map Number"), ("Name", "Owner Name"),
         ("PIN", "PIN"), ("DOR", "Tax ID"))
DECAL = FULL + (("PIN", "Decal Number"),)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    slept: list[float] = []

    async def fake(seconds):
        slept.append(float(seconds))
    monkeypatch.setattr(q, "_sleep", fake)
    return slept


def page(rows=(), options=FULL, no_match=False):
    """A portal page: the viewstate, the Search By list and the grid.
    rows: (notice, owner, address, year, ident, status, paid mm/dd/yy or '', amount)."""
    opts = "".join(f'<option value="{v}">{lbl}</option>' for v, lbl in options)
    body = "".join(
        f'<tr class="gvrow"><td>{n}</td><td>{own}<br />{addr}</td><td>{y}</td><td>TEST DESCRIPTION</td>'
        f'<td>{ident}</td><td>RealEstate</td><td>{st}</td><td>{paid or "        "}</td>'
        f'<td>{amt}</td></tr>' for n, own, addr, y, ident, st, paid, amt in rows)
    if no_match:
        body = '<tr><td colspan="11">No records matched the search criteria provided.</td></tr>'
    return ('<html><body><form><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS" />'
            f'<select name="ctl00$MainContent$ddlCriteriaList" id="x">{opts}</select>'
            f'<table class="gridview" id="ctl00_MainContent_gvSearchResults">{body}</table>'
            '</form></body></html>')


def served(sub, searches: dict, options=FULL) -> ReplayFetcher:
    """The tenant's form, a postback per criteria and the searches {(criteria, value): page}."""
    url = q.form_url(sub)
    form = page(options=options)
    resp = {url: form}
    for crit, _ in options:
        resp[form_key(url, q.criteria_data(q.viewstate(form), crit))] = form
    for (crit, value), html in searches.items():
        resp[form_key(url, q.search_data(q.viewstate(form), value, crit))] = html
    return ReplayFetcher(resp)


def run(row, fetcher, today=TODAY):
    return asyncio.run(q.verify(row, fetcher, today=today))


def roll_row(county, ident, *, parcel=None, street=None, owner="TESTOWNER PAT", **kw):
    row = {"state": "SC", "county": county, "listing_type": "tax_sale",
           "source": "counties_sc.qpaybill_delinquent_roll", "parcel_id": parcel or ident,
           "street_address": street, "owner_name": owner,
           "raw": {"qpaybill_roll": {"identification_no": ident, "county": county,
                                     "years_unpaid": ["2025"], "notice_numbers": []}}}
    row.update(kw)
    return row


OWED = lambda ident, addr="100 TEST RD", n="000000001": [            # noqa: E731
    (n, "TESTOWNER PAT", addr, 2025, ident, "Unpaid", "", "$812.40"),
    ("000000002", "TESTOWNER PAT", addr, 2024, ident, "Unpaid", "", "$790.10"),
    ("000000003", "TESTOWNER PAT", addr, 2023, ident, "Paid", "01/10/24", "$700.00")]
ON_TIME = lambda ident, addr="100 TEST RD", n="000000011": [         # noqa: E731
    (n, "TESTOWNER PAT", addr, 2025, ident, "Paid", "01/09/26", "$812.40"),
    ("000000012", "TESTOWNER PAT", addr, 2024, ident, "Paid", "01/08/25", "$790.10")]


def tenant(f, county, sub):
    return q._tenant(f, county, sub)


# ---------------------------------------------------------------------------
# the circuit breaker
# ---------------------------------------------------------------------------

def _outage(sub, status=503, headers=None):
    url = q.form_url(sub)
    return ReplayFetcher({url: {"status": status, "text": "<html>Service Unavailable</html>",
                                "headers": headers or {}}})


def test_a_vendor_minute_of_503s_opens_the_circuit_then_a_half_open_probe_recovers(_no_real_sleep):
    sub = "darlingtontreasurer"
    f = _outage(sub)
    r1 = run(roll_row("Darlington", "900-00-00-001"), f)
    assert r1.verdict == "unconfirmed" and r1.evidence["reason"] == "fetch_failed"
    assert r1.evidence["http_status"] == 503 and r1.evidence["tenant_failure"] == "http_503"
    assert _no_real_sleep == [q.RETRY_BACKOFF_S]                  # one retry, after a pause
    r2 = run(roll_row("Darlington", "900-00-00-002"), f)
    assert r2.evidence["reason"] == "tenant_unhealthy"
    assert r2.evidence["tenant_state"] == "open" and r2.evidence["http_status"] == 503
    assert 55 <= r2.evidence["retry_in_s"] <= q.COOLDOWN_BASE_S
    asked = len(f.asked)
    r3 = run(roll_row("Darlington", "900-00-00-003"), f)
    assert r3.evidence["reason"] == "tenant_unhealthy" and len(f.asked) == asked
    # the vendor is back: once the cooldown has passed, ONE search is let through and closes it
    ok = served(sub, {("Map", "900-00-00-004"): page(OWED("900-00-00-004"))})
    f.responses = ok.responses
    t = tenant(f, "Darlington", sub)
    t.open_until = time.monotonic() - 1
    r4 = run(roll_row("Darlington", "900-00-00-004", street="100 TEST RD"), f)
    assert r4.verdict == "confirmed" and r4.evidence["total_delinquent"] == 1602.5
    assert t.failures == 0 and t.open_until == 0.0 and not t.half_open and t.trips == 0


def test_a_failed_half_open_probe_reopens_with_a_doubled_cooldown():
    sub = "darlingtontreasurer"
    f = _outage(sub)
    for i in range(2):
        run(roll_row("Darlington", f"900-00-00-01{i}"), f)
    t = tenant(f, "Darlington", sub)
    assert t.trips == 1
    t.open_until = time.monotonic() - 1                    # the cooldown has passed
    n = len(f.asked)
    r = run(roll_row("Darlington", "900-00-00-019"), f)
    assert r.evidence["reason"] == "tenant_unhealthy" and r.evidence["tenant_state"] == "open"
    assert len(f.asked) == n + 1                           # one probe, no retry
    assert t.trips == 2 and 110 <= r.evidence["retry_in_s"] <= 2 * q.COOLDOWN_BASE_S


def test_a_cooldown_about_to_end_is_waited_out_not_reported(_no_real_sleep):
    sub = "laurenstreasurer"
    f = served(sub, {("Map", "900-00-00-021"): page(OWED("900-00-00-021"))})
    t = tenant(f, "Laurens", sub)
    t.open_until = time.monotonic() + 5
    t.last = q.Health("http_503", 503)
    r = run(roll_row("Laurens", "900-00-00-021", street="100 TEST RD"), f)
    assert r.verdict == "confirmed"
    assert _no_real_sleep and 0 < _no_real_sleep[0] <= q.MAX_INLINE_WAIT_S


def test_retry_after_is_honoured_up_to_its_cap(_no_real_sleep):
    sub = "uniontreasurer"
    f = _outage(sub, 429, {"Retry-After": "30"})
    r = run(roll_row("Union", "900-00-00-031"), f)
    assert r.evidence["http_status"] == 429 and _no_real_sleep == [30.0]
    _no_real_sleep.clear()
    f2 = _outage(sub, 503, {"Retry-After": "600"})
    run(roll_row("Union", "900-00-00-032"), f2)
    assert _no_real_sleep == [q.RETRY_AFTER_CAP_S]


def test_a_403_is_a_wall_for_the_run_and_never_retried(_no_real_sleep):
    sub = "colleton"
    f = _outage(sub, 403)
    r = run(roll_row("Colleton", "900-00-00-041.000"), f)
    assert r.evidence["reason"] == "tenant_unhealthy" and r.evidence["tenant_state"] == "blocked"
    assert r.evidence["http_status"] == 403 and r.evidence.get("retry_in_s") is None
    assert len(f.asked) == 1 and _no_real_sleep == []
    tenant(f, "Colleton", sub).open_until = 0.0
    run(roll_row("Colleton", "900-00-00-042.000"), f)
    assert len(f.asked) == 1


def test_the_portals_own_offline_notice_opens_the_circuit_for_long():
    """Abbeville 2026-10-08 (its tenant now MOVED to PayStar; the same page on another tenant
    here): the form redirects to Info.aspx, 'Sorry the site is currently off line.' (a 200
    page): not retried, the circuit opens for OFFLINE_COOLDOWN_S at once."""
    sub = "allendaletreasurer"
    url = q.form_url(sub)
    f = ReplayFetcher({url: {"status": 200, "url": f"https://{sub}.qpaybill.com/Info.aspx",
                             "text": '<html><input name="__VIEWSTATE" value="x" />Info Page '
                                     'Sorry the site is currently off line.</html>'}})
    r = run(roll_row("Allendale", "900-00-00-051"), f)
    assert r.evidence["reason"] == "tenant_unhealthy"
    assert r.evidence["tenant_failure"] == "portal_offline" and r.evidence["http_status"] == 200
    assert r.evidence["retry_in_s"] > q.COOLDOWN_MAX_S
    assert len(f.asked) == 1


def test_abbeville_left_qpaybill():
    assert "abbeville" not in q.tenants() and "abbeville" in q.MOVED
    assert not q.applies(roll_row("Abbeville", "900-00-00-052"))
    assert q.applies(roll_row("Allendale", "900-00-00-052"))


def test_health_answers_are_transient_for_the_ledger_and_the_sweep():
    v = from_module(q)
    assert set(v.transient_reasons) == {"tenant_unhealthy", "fetch_failed", "address_search_failed"}
    now = datetime(2026, 10, 8, 18, 35, tzinfo=timezone.utc)
    down = core.result("tax_lien", "unconfirmed", {"reason": "tenant_unhealthy"},
                       version=q.VERSION, verifier="tax_lien_qpaybill", now=now)
    other = core.result("tax_lien", "unconfirmed", {"reason": "parcel_not_found"},
                        version=q.VERSION, verifier="tax_lien_qpaybill", now=now)
    assert v.is_transient(down.to_dict()) and not v.is_transient(other.to_dict())
    led = L.Ledger("tax_lien")
    e1 = led.record({"state": "SC", "county": "Horry", "parcel_id": "90000000001"}, down)
    e2 = led.record({"state": "SC", "county": "Horry", "parcel_id": "90000000002"}, other)
    later = now + timedelta(hours=7)
    assert L.is_due(e1, v, later) == (True, "retry_transient")
    assert L.is_due(e1, v, now + timedelta(hours=5)) == (False, "retry_transient")
    assert L.is_due(e2, v, later) == (False, "retry")            # 7 days for a real answer


# ---------------------------------------------------------------------------
# the criteria a tenant offers; Horry's PIN search
# ---------------------------------------------------------------------------

def test_horry_pin_is_searched_by_pin_and_no_address_search_is_ever_posted():
    sub = "horrycountytreasurer"
    pin1, pin2 = "90011122233", "90011122244"
    f = served(sub, {("Map", pin1): page(no_match=True, options=HORRY),
                     ("PIN", pin1): page(ON_TIME(pin1, addr=""), options=HORRY),
                     ("PIN", pin2): page(OWED(pin2, addr=""), options=HORRY)}, options=HORRY)
    r1 = run(roll_row("Horry", pin1, street="100 TEST RD"), f)
    # the first row learns the form: Map finds nothing, then PIN; no Address search exists
    assert [(s["searched_by"], s["found"]) for s in r1.evidence["searched"]] == \
        [("Map", False), ("PIN", True)]
    assert r1.verdict == "refuted" and r1.evidence["address_binding"] == "no_address_search"
    url = q.form_url(sub)
    assert form_key(url, q.criteria_data(q.viewstate(page(options=HORRY)), "Address")) not in f.asked
    assert tenant(f, "Horry", sub).offered["PIN"] == "PIN"
    # the next all-digit number goes to PIN first
    r2 = run(roll_row("Horry", pin2, street="100 TEST RD"), f)
    assert r2.verdict == "confirmed"
    assert [s["searched_by"] for s in r2.evidence["searched"]] == ["PIN"]


def test_no_address_search_with_a_conflicting_bill_address_is_unconfirmed():
    sub = "horrycountytreasurer"
    pin = "90011122255"
    f = served(sub, {("PIN", pin): page(ON_TIME(pin, addr="300 OTHER LN"), options=HORRY),
                     ("Map", pin): page(no_match=True, options=HORRY)}, options=HORRY)
    r = run(roll_row("Horry", pin, street="100 TEST RD"), f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "address_search_unavailable"


def test_a_pin_labelled_decal_number_is_never_used():
    sub = "lexingtoncountytreasurer"
    f = served(sub, {("Map", "9001122"): page(ON_TIME("9001122"), options=DECAL)}, options=DECAL)
    run(roll_row("Lexington", "9001122", street="100 TEST RD"), f)
    t = tenant(f, "Lexington", sub)
    assert not q.pin_search_offered(t) and t.offered["PIN"] == "Decal Number"
    url = q.form_url(sub)
    assert form_key(url, q.criteria_data(q.viewstate(page(options=DECAL)), "PIN")) not in f.asked


def test_offered_criteria_parser():
    assert q.offered_criteria(page(options=HORRY)) == dict(HORRY)
    assert q.offered_criteria("<html>no form</html>") == {}


# ---------------------------------------------------------------------------
# a confirmed answer is bound to the row's address (never a neighbor's bills)
# ---------------------------------------------------------------------------

def test_confirmed_on_a_neighbors_house_number_needs_the_address_search():
    """The account searched owes, but its bills name 104 TEST RD while the row is 100 TEST RD,
    and no account carries 100 TEST RD: unconfirmed address_not_found, not confirmed."""
    sub = "spartanburgcountytax"
    ident = "9-00-00-061.00"
    f = served(sub, {("Map", ident): page(OWED(ident, addr="104 TEST RD")),
                     ("Address", "100 TEST"): page(no_match=True)})
    r = run(roll_row("Spartanburg", ident, street="100 Test Road"), f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "address_not_found"
    assert r.evidence["bound_because"] == "other_number_same_street"


def test_confirmed_neighbor_follows_the_rows_own_account_with_owner_proof():
    """The row's own address is on another account whose owner is the row's owner, while the
    searched account's owner is someone else: the address's own account decides (paid on time ->
    refuted), never the neighbor's balance."""
    sub = "spartanburgcountytax"
    ident, own = "9-00-00-062.00", "9-00-00-063.00"
    neighbor = [(n, "OTHERPERSON LEE", "104 TEST RD", y, ident, st, pd, amt)
                for n, _o, _a, y, _i, st, pd, amt in OWED(ident)]
    f = served(sub, {("Map", ident): page(neighbor),
                     ("Address", "100 TEST"): page(ON_TIME(own, addr="100 TEST RD", n="000000021"))})
    r = run(roll_row("Spartanburg", ident, street="100 TEST RD", owner="TESTOWNER PAT"), f)
    assert r.evidence["decided_on"] == "address_search"
    assert r.evidence["followed_because"] == "owner_follows_address"
    assert r.verdict == "refuted" and r.evidence["total_delinquent"] == 0.0


def test_confirmed_with_the_rows_own_address_on_the_bill_is_not_rebound():
    sub = "spartanburgcountytax"
    ident = "9-00-00-064.00"
    f = served(sub, {("Map", ident): page(OWED(ident, addr="100 TEST RD"))})
    r = run(roll_row("Spartanburg", ident, street="100 Test Road"), f)
    assert r.verdict == "confirmed" and "bound_because" not in r.evidence
    assert len(f.asked) == 3                                   # form, criteria, one search


def test_evidence_stays_a_whitelist_without_names():
    sub = "darlingtontreasurer"
    f = _outage(sub)
    r = run(roll_row("Darlington", "900-00-00-071"), f)
    assert set(r.evidence) <= set(q._KEYS)
    assert "TESTOWNER" not in json.dumps(r.to_dict())


# ---------------------------------------------------------------------------
# pacing: one slot for every qPayBill tenant, 2 s by default
# ---------------------------------------------------------------------------

def test_qpaybill_tenants_share_one_pacing_slot():
    assert F.pace_key("horrycountytreasurer.qpaybill.com") == "qpaybill.com"
    assert F.pace_key("spartanburgcountytax.qpaybill.com") == "qpaybill.com"
    assert F.pace_key("tax.buncombenc.gov") == "tax.buncombenc.gov"
    assert F.DEFAULT_MIN_INTERVAL_S >= 2.0


def test_shared_slot_spaces_requests_across_tenants(monkeypatch):
    monkeypatch.delenv("VERIFY_HOST_MIN_INTERVAL_S", raising=False)
    f = F.Fetcher(min_interval_s=0.2)

    async def go():
        t0 = time.monotonic()
        await f._pace("a.qpaybill.com")
        await f._pace("b.qpaybill.com")
        await f._pace("c.qpaybill.com")
        return time.monotonic() - t0
    assert asyncio.run(go()) >= 0.39
    assert F.Fetcher().min_interval_s == 2.0


def test_replayed_form_response_carries_retry_after():
    f = ReplayFetcher({"https://x.qpaybill.com/a": {"status": 503, "text": "", "headers": {"Retry-After": "7"}}})

    async def go():
        async with f.form_session() as s:
            return await s.get("https://x.qpaybill.com/a")
    r = asyncio.run(go())
    assert r.status == 503 and r.headers == {"retry-after": "7"}


def test_registry_loads_v5_with_its_transient_reasons():
    v = next(v for v in discover() if v.name == "tax_lien_qpaybill")
    assert v.version == "v5" and "tenant_unhealthy" in v.transient_reasons
    assert v.transient_retry_days == 0.25


# ---------------------------------------------------------------------------
# the sweep: an answer about source health is re-checked at the end of the run
# ---------------------------------------------------------------------------

def _load_sweep():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "scripts" / "verification_sweep.py"
    spec = importlib.util.spec_from_file_location("verification_sweep_t", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sweep_defers_health_answers_and_records_the_recheck(tmp_path, monkeypatch):
    from foreclosure_scraper.verification.registry import Verifier
    sw = _load_sweep()
    calls: list[str] = []

    async def verify(row, client):
        calls.append(row["parcel_id"])
        first = calls.count(row["parcel_id"]) == 1
        if row["parcel_id"] == "900-00-00-081" and first:      # the vendor's bad minute
            return core.result("tax_lien", "unconfirmed", {"reason": "tenant_unhealthy",
                                                           "http_status": 503},
                               version="v9", verifier="fake_q")
        return core.result("tax_lien", "confirmed", {"total_delinquent": 600.0},
                           version="v9", verifier="fake_q")
    v = Verifier(name="fake_q", signal="tax_lien", version="v9", ttl_days=30,
                 applies=lambda r: True, verify=verify, transient_reasons=("tenant_unhealthy",))
    rows = [{"state": "SC", "county": "Union", "parcel_id": p, "street_address": f"{i} TEST RD"}
            for i, p in enumerate(("900-00-00-081", "900-00-00-082"), start=1)]
    plan = {"tax_lien": [((3, 0, 0.0, i), f"parcel:SC:union:{r['parcel_id']}", r, v)
                         for i, r in enumerate(rows)]}
    led = L.Ledger("tax_lien", path=tmp_path / "tax_lien.json")
    paused: list[float] = []

    async def fake_sleep(s):
        paused.append(s)
    monkeypatch.setattr(sw.asyncio, "sleep", fake_sleep)
    tally = asyncio.run(sw.run_checks(plan, {"tax_lien": led}, None, budget_s=600, save_every=50,
                                      row_timeout_s=30, host="test", defer_wait_s=120))
    assert calls == ["900-00-00-081", "900-00-00-082", "900-00-00-081"]
    assert paused == [120]
    t = tally["tax_lien"]
    assert t["deferred"] == 1 and t["rechecked_after_deferral"] == 1
    assert t["confirmed"] == 2 and t["checked"] == 2 and "unconfirmed" not in t
    assert led.counts()["confirmed"] == 2
