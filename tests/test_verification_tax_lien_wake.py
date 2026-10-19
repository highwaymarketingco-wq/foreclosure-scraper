"""tax_lien_wake: services.wake.gov's own bill-history search, read via a bridged REID.

The BILLS_* fixtures below are genuine markup, trimmed -- captured live 2026-10-18 from
https://services.wake.gov/ptax/main/billing/acctsummary.aspx?search=re&yrs=2&prev=re&id=<reid>
for 3 real Wake board-shaped parcels (tax_lien_wake module docstring: PIN 1713252770 / REID
0047895, PIN 0765045120 / REID 0210739, PIN 1797953869 / REID 0167151). Every dollar figure,
year and flag in the assertions below is read straight off that live page, not invented.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.verifiers import tax_lien_wake as V

TODAY = date(2026, 10, 18)

PIN = "1713252770"
REID = "0047895"
BRIDGE_URL = V._bridge_url(PIN)
BILLS_URL = V.BILLS_URL.format(reid=REID)


def _bill_row(account: str, flag: str, amount: str, due_date: str) -> str:
    return (
        f'<TD class="medFont"><A title="Go To Billing Statement" '
        f'HREF="javascript:__doPostBack(\'ctlAcctSumm\', \'x\')">{account}</A></TD></TR>'
        f'<TR><TD class="billFlag">{flag}</TD></TR></TABLE></TD>'
        f'<TD width="33%"><TABLE><TR><TD width="50%"><span class="medFontBold">Current Due: '
        f'</span></TD><TD width="30%" align="right" class="medFontBold">${amount}</TD>'
        f'<TD class="medFont" width="25%"></TD></TR>'
        f'<TR><TD width="50%" class="medfont">Due Date:</TD>'
        f'<TD width="30%" align="right" class="medFont">{due_date}</TD>'
        f'<TD width="20%"></TD></TR></TABLE></TD></TR>'
    )


def _bills_page(*rows: str) -> str:
    return "<HTML><BODY><TABLE>" + "".join(rows) + "</TABLE></BODY></HTML>"


#: real shape (tax_lien_wake docstring): 5 open-year bills, 4 Delinquent.
REAL_BILLS_0047895 = _bills_page(
    _bill_row("0000047895-2026-2026-000000", "Collection Proceeding Active<br>",
             "1,634.31", "09/01/2026"),
    _bill_row("0000047895-2025-2025-000000",
             "Delinquent<br>Collection Proceeding Active<br>", "1,710.10", "09/01/2025"),
    _bill_row("0000047895-2024-2024-000000",
             "Delinquent<br>Collection Proceeding Active<br>", "1,849.35", "09/01/2024"),
    _bill_row("0000047895-2023-2023-000000",
             "Delinquent<br>Collection Proceeding Active<br>", "3,099.35", "09/01/2023"),
    _bill_row("0000047895-2022-2022-000000",
             "Delinquent<br>Collection Proceeding Active<br>", "1,885.73", "09/01/2022"),
)

#: real shape: ordinary current parcel, 2024/2025 paid, 2026 due but not yet late.
REAL_BILLS_0210739 = _bills_page(
    _bill_row("0000210739-2024-2024-000000", "", "0.00", "09/01/2024"),
    _bill_row("0000210739-2026-2026-000000", "", "5,600.17", "09/01/2026"),
    _bill_row("0000210739-2025-2025-000000", "", "0.00", "09/01/2025"),
)

#: real shape: present-use farm, "002000" rollback-tracking rows alongside the ordinary bill.
REAL_BILLS_0167151 = _bills_page(
    _bill_row("0000167151-2026-2026-002000", "Subject to Rollback", "0.00", "09/01/2026"),
    _bill_row("0000167151-2026-2026-000000", "", "197.79", "09/01/2026"),
    _bill_row("0000167151-2025-2025-002000", "Subject to Rollback", "0.00", "09/01/2025"),
    _bill_row("0000167151-2025-2025-000000", "", "0.00", "09/01/2025"),
)


def _bridge_json(reid=REID) -> str:
    return json.dumps({"features": [{"attributes": {"altparno": reid}}]})


class FakeSite:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.asked: list[str] = []

    async def get_text(self, url, **_):
        self.asked.append(url)
        if url not in self.pages:
            raise RuntimeError(f"unexpected url {url}")
        return self.pages[url]


def _row(parcel_id=PIN, county="Wake", state="NC", **kw) -> dict:
    r = {"state": state, "county": county, "parcel_id": parcel_id, "owner_name": "EXAMPLE OWNER",
        "listing_type": "distressed", "source": "counties_generic.nc_onemap",
        "raw": {"tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 2,
                                       "tax_year": 2024}}}
    r.update(kw)
    return r


def run(coro):
    return asyncio.run(coro)


def test_registered_with_the_shared_tax_lien_contract():
    v = {x.name: x for x in registry.discover()}["tax_lien_wake"]
    assert v.signal == "tax_lien" and v.governs and not v.wall


def test_applies_only_to_wake_rows_with_a_tax_claim():
    assert V.applies(_row())
    assert not V.applies(_row(county="Durham", raw={}))
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(raw={}))   # no tax_claim at all


# ---------------------------------------------------------------------------
# reid_of / parse_bills: pure
# ---------------------------------------------------------------------------

def test_reid_of_recognizes_a_short_reid_not_a_long_pin():
    assert V.reid_of("0047895") == "0047895"
    assert V.reid_of("47895") == "0047895"
    assert V.reid_of(PIN) is None


def test_parse_bills_reads_the_real_delinquent_shape():
    bills = V.parse_bills(REAL_BILLS_0047895)
    assert [b["year"] for b in bills] == [2026, 2025, 2024, 2023, 2022]
    assert bills[1]["amount_due"] == 1710.10 and "Delinquent" in bills[1]["flag"]
    assert bills[0]["amount_due"] == 1634.31 and "Delinquent" not in bills[0]["flag"]
    assert all(b["suffix"] == "000000" for b in bills)


def test_parse_bills_separates_rollback_tracking_rows_by_suffix():
    bills = V.parse_bills(REAL_BILLS_0167151)
    suffixes = {(b["year"], b["suffix"]) for b in bills}
    assert (2026, "002000") in suffixes and (2026, "000000") in suffixes
    rollback_row = next(b for b in bills if b["suffix"] == "002000" and b["year"] == 2026)
    assert rollback_row["flag"] == "Subject to Rollback"


# ---------------------------------------------------------------------------
# bridge_pin_to_reid / resolve_reid
# ---------------------------------------------------------------------------

def test_bridge_pin_to_reid_reads_altparno():
    site = FakeSite({BRIDGE_URL: _bridge_json()})
    assert run(V.bridge_pin_to_reid(site, PIN)) == REID
    assert site.asked == [BRIDGE_URL]


def test_bridge_pin_to_reid_no_match_is_none():
    site = FakeSite({BRIDGE_URL: json.dumps({"features": []})})
    assert run(V.bridge_pin_to_reid(site, PIN)) is None


def test_resolve_reid_skips_the_bridge_for_an_already_short_id():
    site = FakeSite({})
    assert run(V.resolve_reid(site, REID)) == REID
    assert site.asked == []


# ---------------------------------------------------------------------------
# verify: end to end
# ---------------------------------------------------------------------------

def test_confirmed_on_the_real_multi_year_delinquent_parcel():
    site = FakeSite({BRIDGE_URL: _bridge_json(), BILLS_URL: REAL_BILLS_0047895})
    r = run(V.verify(_row(), site, today=TODAY))
    assert r.verdict == "confirmed"
    assert r.evidence["reid"] == REID and r.evidence["years_delinquent"] == 4
    assert r.evidence["total_delinquent"] == 8544.53
    assert "owner" not in str(r.evidence).lower()   # public ledger


def test_unconfirmed_when_only_the_current_not_yet_due_bill_owes():
    site = FakeSite({BRIDGE_URL: _bridge_json(reid="0210739"),
                     V.BILLS_URL.format(reid="0210739"): REAL_BILLS_0210739})
    r = run(V.verify(_row(raw={}), site, today=TODAY))
    assert r.verdict == "unconfirmed"
    assert r.evidence.get("not_yet_delinquent_due") == {"2026": 5600.17}


def test_the_present_use_rollback_tracking_row_is_never_double_counted():
    """A '002000' row must never be read as a second tax bill for the same year (module
    docstring) -- only the ordinary '000000' bill decides the verdict."""
    site = FakeSite({BRIDGE_URL: _bridge_json(reid="0167151"),
                     V.BILLS_URL.format(reid="0167151"): REAL_BILLS_0167151})
    r = run(V.verify(_row(raw={"two_year_delinquent": {"is_two_year_plus": True,
                                                       "tax_year": 2025}}), site, today=TODAY))
    # 2025's ordinary bill is $0.00 (paid) and the claimed year 2025 resolves to it -- stale,
    # never confirmed off the 002000 "Subject to Rollback" row's own $0.00.
    assert r.verdict == "stale"
    assert r.evidence["resolved_claimed_years"] == [2025]


def test_bridge_failure_is_unconfirmed_not_raised():
    site = FakeSite({BRIDGE_URL: json.dumps({"features": []})})
    r = run(V.verify(_row(), site, today=TODAY))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "bridge_failed"


def test_no_parcel_is_unconfirmed_with_no_network_at_all():
    site = FakeSite({})
    r = run(V.verify(_row(parcel_id=None), site, today=TODAY))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_parcel"
    assert site.asked == []
