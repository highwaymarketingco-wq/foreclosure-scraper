"""tax_lien_devnet v1 (Gaston on DEVNET wEdge: GIS PIN -> PID, the parcel page's payment history).

Synthetic: made-up PINs, PIDs, streets and amounts, the shape of the real pages (read live
2026-10-09). No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_devnet as dn

TODAY = date(2026, 10, 9)
PIN = "3500-00-0001"
PID = "900001"


def parcel_page(history, *, pid=PID, situs="12 TEST MAIN AVE GASTONIA NC 28052"):
    rows = "".join(
        f'<tr class="text-center"><td>{y}</td><td>${due:,.2f}</td><td>${paid:,.2f}</td>'
        f'<td>${due - paid:,.2f}</td><td>{d.strftime("%-m/%-d/%Y") if d else ""}</td></tr>'
        for y, due, paid, d in history)
    return (f'<div class="md:flex"><div class="inner-label md:w-5/12">Parcel Number</div>'
            f'<div class="md:w-7/12">{pid}</div></div>'
            f'<div class="md:flex"><div class="inner-label md:w-5/12">Physical Address</div>'
            f'<div class="md:w-7/12">{situs}</div></div>'
            f'<div id="PaymentHistory1" class="panel"><table><thead><tr><th>Tax Year</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            f'<div id="Billing1"><table><tr><th>Paid By</th><td>TESTPAYER NAME</td></tr></table></div>')


def history(**over):
    out = [(2026, 1000.0, 0.0, None),
           (2025, 1000.0, over.get("paid2025", 1000.0), over.get("d2025", date(2025, 12, 20))),
           (2024, 1000.0, 1000.0, over.get("d2024", date(2024, 12, 20)))]
    out += [(y, 900.0, 900.0, date(y, 11, 1)) for y in range(2023, 2018, -1)]
    return out


class FakeSite:
    def __init__(self, page, *, gis=None, fail=0):
        self.page, self.fail, self.asked = page, fail, []
        self.gis = gis if gis is not None else {"features": [{"attributes": {"PIN": PIN, "PID": PID,
                                                                              "PHYSSTRADD": "12 TEST MAIN AVE"}}]}

    async def get_json(self, url, **_):
        self.asked.append(url)
        return self.gis

    async def get_text(self, url, **_):
        self.asked.append(url)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("HTTP 503")
        return self.page


def row(**kw):
    r = {"state": "NC", "county": "Gaston", "listing_type": "code_violation", "source": "counties_nc.gaston_vacant",
         "parcel_id": PIN, "street_address": "12 TEST MAIN AVE", "owner_name": "TESTOWNER ALPHA",
         "raw": {"tax_owed": {"balance": 1000.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def run(r, site):
    return asyncio.run(dn.verify(r, site, today=TODAY))


def test_contract_and_pins():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(dn)
    assert (v.signal, v.version) == ("tax_lien", "v1") and v.governs == tc.GOVERNS
    assert dn.pin_of("3500000001") == PIN and dn.pin_of(PIN) == PIN and dn.pin_of("") is None
    assert dn.applies(row()) and not dn.applies(row(county="Lincoln"))


def test_unpaid_late_levy_confirms():
    r = run(row(), FakeSite(parcel_page(history(paid2025=0.0, d2025=None))))
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 1000.0}
    assert r.evidence["not_yet_delinquent_due"] == {"2026": 1000.0} and r.evidence["address_binding"] == "bill_address"


def test_paid_late_is_stale_and_on_time_refuted():
    r = run(row(), FakeSite(parcel_page(history(d2025=date(2026, 1, 15)))))
    assert r.verdict == "stale" and r.evidence["current_claim_basis"] == "claimed_year_paid_late", r.evidence
    r = run(row(), FakeSite(parcel_page(history())))
    assert r.verdict == "refuted" and r.evidence["chronic_claim"] == "not_confirmed", r.evidence
    assert r.evidence["note"].startswith("only the current levy")


def test_another_house_number_never_gives_a_harmful_answer():
    r = run(row(street_address="14 TEST MAIN AVE"), FakeSite(parcel_page(history())))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_parcel_mismatch")


def test_exempt_not_found_and_failures():
    assert run(row(), FakeSite(parcel_page([]))).evidence["reason"] == "no_bills_exempt_or_not_billed"
    assert run(row(), FakeSite(parcel_page(history()), gis={"features": []})).evidence["reason"] == "parcel_not_found"
    assert run(row(parcel_id=""), FakeSite("")).evidence["reason"] == "parcel_unresolvable"
    r = run(row(), FakeSite(parcel_page(history()), fail=2))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "fetch_failed")


def test_public_evidence_names_nobody_and_skips_the_payer():
    blob = json.dumps(run(row(), FakeSite(parcel_page(history(paid2025=0.0, d2025=None)))).to_dict())
    assert "TESTOWNER" not in blob and "TESTPAYER" not in blob and "TEST MAIN" not in blob
