"""counties_nc.asheville_str_permits — extraction completeness + signal check.

The ArcGIS layer's `record_comments` field (the city's own case notes) was
never captured, even though live data (2026-10-01) shows it is load-bearing:
a handful of "Revoked" rows are for a homestay that was never actually
issued/inspected -- no STR income was ever earned, so flagging them as a
lost-income distress signal would be fabricating one. Fixtures below are
verbatim `attributes` shapes captured live against
gis.ashevillenc.gov/.../HomestayPermitsView/MapServer/5.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from foreclosure_scraper.scrapers.counties_nc import asheville_str_permits as m


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


REVOKED_REAL_INCOME_LOSS = {
    "record_id": "17-03939", "record_name": "BRATTER, MELISSA",
    "address": "16 POND ST, ARDEN, NC 28704", "parcel_number": "6379", "apn": "6379",
    "record_status": "Expired", "record_status_date": 1637730000000,
    "date_opened": 1493870400000, "business_name": None, "license_number": "206177",
    "balance_due": 0.0,
    "record_comments": "HOMESTAY APPLICATION;[NEXT COMMENT]Permit expired. "
                        "Applicant failed to renew for 2020, though they were "
                        "sent a reminder.",
}

REVOKED_NEVER_ISSUED = {
    "record_id": "18-04537", "record_name": "CHURCH, CHRIS",
    "address": "202 ALPINE RIDGE DR, ASHEVILLE, NC 28803", "parcel_number": "279595",
    "apn": "279595", "record_status": "Revoked", "record_status_date": 1578286800000,
    "date_opened": 1528862400000, "business_name": None, "license_number": "98191",
    "balance_due": 0.0,
    "record_comments": "HOMESTAY APPLICATION FOR CHRIS CHURCH;[NEXT COMMENT]"
                        "Revoked 01.06.2020. Homestay never inspected, so "
                        "permit was never actually issued.",
}

WITH_BALANCE_DUE = {
    "record_id": "20-00001", "record_name": "NICHOLS, JANET",
    "address": "1 MAIN ST, ASHEVILLE, NC 28803", "parcel_number": "99999", "apn": "99999",
    "record_status": "Revoked", "record_status_date": 1620000000000,
    "date_opened": 1500000000000, "business_name": None, "license_number": "400001",
    "balance_due": 208.0,
    "record_comments": "RENEWAL FOR HOMESTAY PERMIT.  BALANCE DUE, LEFT V/M FOR "
                        "JANET ON 5/23;[NEXT COMMENT]Revoked. Applicant failed "
                        "to move forward with the renewal process.",
}


def _fetch(rows):
    @asynccontextmanager
    async def fake_client(*a, **kw):
        class _C:
            async def get(self, url, params=None):
                return _FakeResp({"features": [{"attributes": r} for r in rows]})
        yield _C()

    async def run():
        import foreclosure_scraper.scrapers.counties_nc.asheville_str_permits as mod
        orig = mod.client
        mod.client = fake_client
        try:
            return list(await mod.AshevilleSTRPermits().fetch())
        finally:
            mod.client = orig
    return asyncio.run(run())


def test_never_issued_permit_is_excluded_not_a_real_income_loss():
    out = _fetch([REVOKED_NEVER_ISSUED])
    assert out == []


def test_real_lapsed_permit_is_kept_with_comments_wired():
    out = _fetch([REVOKED_REAL_INCOME_LOSS])
    assert len(out) == 1
    li = out[0]
    assert li.case_number == "17-03939"
    sig = li.raw["str_permit_lapsed"]
    assert "failed to renew" in sig["comments"].lower()
    assert sig["license_number"] == "206177"
    assert sig["status_date_iso"] == "2021-11-24"
    assert sig["date_opened_iso"] == "2017-05-04"
    assert "balance_due" not in sig  # zero balance omitted, not a false 0


def test_nonzero_balance_due_is_captured():
    out = _fetch([WITH_BALANCE_DUE])
    assert len(out) == 1
    assert out[0].raw["str_permit_lapsed"]["balance_due"] == 208.0


def test_mixed_batch_drops_only_the_never_issued_row():
    out = _fetch([REVOKED_REAL_INCOME_LOSS, REVOKED_NEVER_ISSUED, WITH_BALANCE_DUE])
    case_numbers = {li.case_number for li in out}
    assert case_numbers == {"17-03939", "20-00001"}
