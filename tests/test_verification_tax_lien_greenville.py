"""tax_lien_greenville v1 and the shared SC bill rules (_sc_bills).

Synthetic: made-up owners (TESTOWNER ...), made-up map numbers, the shape of the county's real
RealTaxesResults page (read live 2026-10-09). No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification.verifiers import _sc_bills as sb
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_greenville as g

TODAY = date(2026, 10, 9)
MAP = "0999000100100"


def bill_tr(year, *, owner="TESTOWNER ALPHA", m=MAP, paid=None, d=False, base=1000.0, balance=None,
            status=""):
    paid_txt = paid.strftime("%m/%d/%Y") if paid else ""
    bal = f"${balance:.2f}" if balance else ""
    return f"""
    <tr><td valign="top" align="left"><span style="font-weight: bold;"> {owner} </span>
      <div><a href='https://www.greenvillecounty.org/appsas400/RealProperty/Details.aspx?MapNumber={m}&TaxYear={year}&Receipt=1&Item=77'>
        {year} 000000001 77 001</a>&nbsp;<a href="#">View Tax Notice</a></div>
      <div style="color: Red;"> {status} </div></td>
    <td valign="top" align="left" class="MobileHide"><div> {m} </div><div> </div></td>
    <td align="left" class="MobileHide"><div> &nbsp; </div><div> 500&nbsp; </div><div> </td>
    <td valign="top" style="text-align: center;" class="MobileHide"><div> &nbsp; </div><div> {"D" if d else ""}&nbsp; </div></td>
    <td valign="top" align="right" class="MobileHide"><div> 5880 </div><div> {paid_txt} </div></td>
    <td valign="top" align="right"><div> ${base:.2f} </div><div> ${0 if balance else base:.2f} </div></td>
    <td style="text-align: center; vertical-align: middle; color: Red;"><div><span style="font-weight: bold;"> {bal} </span></div></td>
    </tr>"""


def page(trs):
    return (f'<html><span id="ctl00_bodyContent_lbl_Count">{len(trs)}</span><table><thead><tr><th>x</th></tr>'
            f'</thead><tbody>{"".join(trs)}</tbody></table></html>')


class FakeSite:
    def __init__(self, pages, *, fail=0):
        self.pages, self.fail, self.asked = pages, fail, []

    async def get_text(self, url, **_):
        self.asked.append(url)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("HTTP 503")
        for m, p in self.pages.items():
            if f"Criteria={m}" in url:
                return p
        return page([])


def history(m=MAP, **over):
    """2019-2024 paid on time; the 2025 bill as `over` says."""
    trs = [bill_tr(2025, m=m, paid=over.get("p2025"), d=over.get("d2025", False), balance=over.get("b2025"))]
    for y in range(2024, 2018, -1):
        trs.append(bill_tr(y, m=m, paid=over.get(f"p{y}", date(y, 12, 1)), d=over.get(f"d{y}", False)))
    return page(trs)


def roster_row(**kw):
    r = {"state": "SC", "county": "Greenville", "listing_type": "tax_sale",
         "source": "counties_sc.greenville_delinquent_tax", "parcel_id": MAP,
         "street_address": "1 TEST ST", "owner_name": "TESTOWNER ALPHA",
         "raw": {g.ROLL_KEY: {"map_number": MAP, "amount_due": 1100.0},
                 "tax_owed": {"balance": 1100.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def run(row, site):
    return asyncio.run(g.verify(row, site, today=TODAY))


def test_contract():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(g)
    assert (v.signal, v.version, v.ttl_days) == ("tax_lien", "v1", 30.0)
    assert v.governs == tc.GOVERNS and v.priority_fn is tc.flag_priority


def test_applies():
    assert g.applies(roster_row())
    assert not g.applies(roster_row(county="Spartanburg"))
    assert not g.applies(roster_row(state="NC"))
    assert not g.applies({"state": "SC", "county": "Greenville", "listing_type": "code_violation",
                          "source": "x", "raw": {}})
    # a state-revenue lien row is not a county property-tax claim
    assert not g.applies({"state": "SC", "county": "Greenville", "listing_type": "tax_lien",
                          "source": "counties_sc.sc_state_tax_lien", "raw": {}})


def test_confirmed_with_the_balance_of_the_late_levy():
    r = run(roster_row(), FakeSite({MAP: history(b2025=1426.02, d2025=True)}))
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 1426.02}
    assert r.evidence["decided_on"] == "claim_map" and r.evidence["owner_match"] == "same"


def test_stale_when_the_claimed_levy_was_paid_late():
    r = run(roster_row(), FakeSite({MAP: history(p2025=date(2026, 9, 28), d2025=True)}))
    assert r.verdict == "stale", r.evidence
    assert r.evidence["current_claim_basis"] == "claimed_year_paid_late"
    assert r.evidence["late_levy_years"] == [2025] and r.evidence["chronic_claim"] == "not_confirmed"


def test_late_without_the_d_mark_is_judged_by_the_date():
    # paid 2026-03-08: after January 15 plus the postmark grace, before the county's mid-March mark
    r = run(roster_row(), FakeSite({MAP: history(p2025=date(2026, 3, 8))}))
    assert r.verdict == "stale", r.evidence


def test_a_receipt_inside_the_postmark_grace_is_undecided():
    r = run(roster_row(), FakeSite({MAP: history(p2025=date(2026, 1, 20))}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "paid_near_deadline"), r.evidence


def test_refuted_when_paid_on_time():
    r = run(roster_row(), FakeSite({MAP: history(p2025=date(2025, 12, 20))}))
    assert r.verdict == "refuted", r.evidence
    assert r.evidence["current_claim_basis"] == "claimed_years_on_time"
    assert g.governs_for(r.to_dict()) == tc.GOVERNS


def test_a_chronic_late_payer_keeps_the_chronic_signal():
    r = run(roster_row(), FakeSite({MAP: history(p2025=date(2026, 5, 1), d2025=True, d2024=True,
                                                 p2024=date(2025, 6, 1), d2023=True, p2023=date(2024, 7, 1))}))
    assert r.verdict == "stale" and r.evidence["chronic_claim"] == "confirmed"
    assert "tax_lien_chronic" not in g.governs_for(r.to_dict())


def test_not_found_and_failures_are_unconfirmed():
    r = run(roster_row(), FakeSite({}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_not_found")
    site = FakeSite({MAP: history()}, fail=5)
    assert run(roster_row(), site).evidence["reason"] == "fetch_failed"
    assert run(roster_row(), site).evidence["reason"] == "fetch_failed"
    assert run(roster_row(), site).evidence["reason"] == "fetch_failed"
    assert run(roster_row(), site).evidence["reason"] == "portal_unhealthy"


def test_claim_and_board_parcels_that_disagree_are_an_identity_conflict():
    other = "0888000100100"
    row = roster_row(parcel_id=other)
    r = run(row, FakeSite({MAP: history(b2025=900.0, d2025=True), other: history(other, p2025=date(2025, 12, 1))}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "identity_conflict")
    assert r.evidence["delinquent_parcel"] == "claim"


def test_a_resolver_parcel_needs_the_owner():
    row = {"state": "SC", "county": "Greenville", "listing_type": "code_violation", "source": "x",
           "parcel_id": MAP, "owner_name": "SOMEONE ELSE ENTIRELY",
           "raw": {"parcel_from_address": True, "tax_owed": {"balance": 50.0, "kind": "delinquent_tax"}}}
    r = run(row, FakeSite({MAP: history(b2025=900.0, d2025=True)}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_resolved_unbound")


def test_record_ended_and_tax_sale():
    ended = page([bill_tr(2023, paid=date(2023, 12, 1))])
    r = run(roster_row(), FakeSite({MAP: ended}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_record_ended")
    sold = page([bill_tr(2025, balance=800.0, d=True, status="TAX SALE"), bill_tr(2024, paid=date(2024, 12, 1))])
    r = run(roster_row(), FakeSite({MAP: sold}))
    assert r.verdict == "confirmed" and r.evidence["reason"] == "sold_at_tax_sale"


def test_the_public_evidence_names_nobody():
    r = run(roster_row(), FakeSite({MAP: history(b2025=1426.02, d2025=True)}))
    assert "TESTOWNER" not in json.dumps(r.to_dict())


def test_sc_deadline_rolls_a_weekend():
    assert sb.deadline(2025) == date(2026, 1, 15)          # a Thursday
    assert sb.deadline(2022) == date(2023, 1, 16)          # Jan 15, 2023 was a Sunday
    assert sb.latest_eligible(TODAY) == 2025 and sb.latest_eligible(date(2026, 1, 10)) == 2024


def test_the_gate_sees_a_check_of_the_rows_own_parcel():
    """call_ready's tax_fact counts a confirmed check only when tax_binding.verified_checks_row
    finds the checked parcel among the row's ids: every new SC verifier names it (tax_parcel)."""
    from foreclosure_scraper.tax_binding import verified_checks_row
    r = run(roster_row(), FakeSite({MAP: history(b2025=900.0, d2025=True)}))
    assert r.evidence["tax_parcel"] == MAP and verified_checks_row(roster_row(), r.evidence)
    other = roster_row(parcel_id="0888000100100")
    r = run(other, FakeSite({MAP: history(b2025=900.0, d2025=True)}))
    assert r.verdict == "confirmed" and not verified_checks_row(other, r.evidence)   # the claim's parcel, not the row's
