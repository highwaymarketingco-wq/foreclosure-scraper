"""A portal outage must never be reported as an empty county.

PROVEN AGAINST A LIVE OUTAGE, 2026-09-13 01:15. Every qPayBill tenant -- Union,
Barnwell, Cherokee, Oconee, Spartanburg -- answered HTTP 503 with a 123,600-byte
maintenance page. The dangerous part is that the page looks structurally valid:

    parse_grid(503 body)  -> 0 rows
    _vs(503 body)         -> still returns __VIEWSTATE / __VIEWSTATEGENERATOR / EVENTVALIDATION

_post() had no status check, so a 503 flowed straight into parse_grid and the sweep
would have logged, for all 19 counties:

    county_done  parcels=0  queries=N  errors=0

a clean bill of health for a run that collected nothing. This is the same silent shape
as the Catalis 429 that was fixed in sc_catalis_delinquent_roll -- and this sibling
scraper never got the same guard.

With the guard, the same live outage produced:

    county_done  errors=12  lost_prefixes=12  parcels=0
    county_incomplete  "this county's roll is INCOMPLETE"  prefixes=['A','B','C',...]
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (
    QPayBillUnavailable, _require_ok, parse_grid,
)


class FakeResp:
    def __init__(self, status: int, body: str = ""):
        self.status_code = status
        self.content = body.encode()
        self.text = body


#: The shape of the real 503 maintenance page: large, valid HTML, carrying ASP.NET
#: viewstate tokens, and containing no data rows.
OUTAGE_BODY = ("<html><head><title>Service Unavailable</title></head><body>"
               "<input name='__VIEWSTATE' value='abc'/>"
               "<input name='__VIEWSTATEGENERATOR' value='def'/>"
               "<input name='__EVENTVALIDATION' value='ghi'/>"
               "<p>The service is temporarily unavailable.</p></body></html>"
               + "x" * 120_000)


@pytest.mark.parametrize("status", [500, 502, 503, 504, 403, 404, 429])
def test_any_error_status_raises_rather_than_parsing(status):
    with pytest.raises(QPayBillUnavailable) as e:
        _require_ok(FakeResp(status, OUTAGE_BODY), "uniontreasurer", "A")
    msg = str(e.value)
    assert str(status) in msg
    assert "uniontreasurer" in msg
    assert "NOT an empty result" in msg, "the message must say what it is NOT"


@pytest.mark.parametrize("status", [200, 201, 204, 302])
def test_success_statuses_pass_through(status):
    _require_ok(FakeResp(status, "<html></html>"), "uniontreasurer", "A")


def test_the_outage_page_parses_to_zero_rows_which_is_why_the_guard_is_needed():
    """This is the whole danger: the body is not garbage, it is plausible. Without a
    status check there is nothing downstream that could tell it from a real empty page."""
    assert parse_grid(OUTAGE_BODY) == []


def test_the_guard_names_the_prefix_so_the_gap_is_identifiable():
    """An unreadable initial is a hole in that county's roll. It has to be nameable, so
    county_incomplete can list exactly which owners were never read."""
    with pytest.raises(QPayBillUnavailable) as e:
        _require_ok(FakeResp(503, OUTAGE_BODY), "cherokeecountysctax", "SMI")
    assert "'SMI'" in str(e.value)


def test_the_guard_reports_the_body_size():
    """A 123,600-byte 'empty result' is self-evidently not an empty result, and the size
    is what makes that obvious in a log."""
    with pytest.raises(QPayBillUnavailable) as e:
        _require_ok(FakeResp(503, OUTAGE_BODY), "x", "A")
    assert "123," in str(e.value) or "120," in str(e.value)
