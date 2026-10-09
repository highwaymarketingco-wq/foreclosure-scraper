"""tax_lien_florence v1: the treasurer's tax inquiry (year files and the delinquent list).

Synthetic: made-up owners (TESTOWNER ...), made-up parcels, notice numbers and streets, the shape of
the county's real pages (read live 2026-10-09). No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_florence as f

TODAY = date(2026, 10, 9)
MBP = ("00777", "12", "345")
KEY = "00777 12 345"


def bill_tr(year, *, mbp=KEY, red=False, paid=None, total=600.0, label="Total Paid", msg="",
            owner="TESTOWNER ALPHA", typ="Real", seq=1):
    bg = ' bgcolor="#ffa0a0"' if red else " "
    paid_s = paid.strftime("%m/%d/%y") if paid else "--/--/--"
    notice = f"{year % 100:02d}{seq:06d}"
    return f"""<tr>
<td{bg}><center><font color=blue>
<table cellpadding=3 border=1 bordercolor=gray>
<tr><td bgcolor=#3030a0>
<a href=tax-del.cgi?step=3&key={notice}>{notice}</a>
</td></tr></table>
{mbp}</td>
<td{bg}><font color=blue>{typ}<br>220</td>
<td{bg}><font color=blue size=-1>{owner}<br>TEST LOT</td>
<td{bg}><font color=blue size=-1>1 TEST BILLING RD<br><font color=blue>TESTVILLE SC</td>
<td{bg}><font color=blue>            <br>  <br>{msg}</td>
<td align=right{bg} valign=top><font color=blue>      760<br>  26.86<br> 175.00<br>   0.00<hr><font color=brown>{label}</font></td>
<td align=right{bg} valign=top><font color=blue>   0.00<br> 426.18<br> 426.18<br><br><hr><font color=brown size=+1> {total:.2f}</td>
<td{bg} valign=top><font color=blue>09/13/{(year) % 100:02d}<br>{paid_s}<br>--/--/--<br>--/--/--</td>
</tr>
"""


def page(trs):
    if not trs:
        return "<html>Tax Records Inquiry ... No match found for your search</html>"
    return ("<html><table cellpadding=3 border=1><th><font color=brown>Notice #<br>MBP</th>"
            + "".join(trs) + "</table><hr><table><tr><td>Red Entries Are Delinquent Taxes</td></tr></table></html>")


class FakeSite:
    """year files keyed by (file, mbp key); the delinquent list keyed by mbp key."""

    def __init__(self, years=None, dels=None, fail=0):
        self.years, self.dels, self.fail, self.asked = years or {}, dels or {}, fail, []

    async def get_text(self, url, **_):
        self.asked.append(url)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("HTTP 503")
        from urllib.parse import parse_qs, urlsplit
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}
        key = f"{q['map']} {q['block']} {q['parcel']}"
        if "tax-del.cgi" in url:
            return page(self.dels.get(key, []))
        return page(self.years.get((q["file"], key), []))


def sale_row(**kw):
    r = {"state": "SC", "county": "Florence", "listing_type": "tax_sale",
         "source": "counties_sc.florence_delinquent_tax", "parcel_id": "777-12-345",
         "owner_name": "TESTOWNER ALPHA",
         "raw": {f.ROLL_KEY: {"tms": "777-12-345", "taxpayer": "TESTOWNER ALPHA"},
                 "tax_owed": {"balance": 650.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def run(row, site):
    return asyncio.run(f.verify(row, site, today=TODAY))


def test_contract_and_parcel_forms():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(f)
    assert (v.signal, v.version) == ("tax_lien", "v1") and v.governs == tc.GOVERNS
    assert f.mbp("777-12-345") == MBP and f.mbp("00777-12-345") == MBP and f.mbp("77-12-345") == ("00077", "12", "345")
    assert f.mbp("") is None and f.mbp("00000-00-000") is None
    assert f.applies(sale_row()) and not f.applies(sale_row(county="Darlington"))


def test_a_red_unpaid_bill_confirms():
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, red=True, label="Total Due", total=2464.07)],
                           ("rpcpubp2", KEY): [bill_tr(2024, paid=date(2024, 12, 1))]})
    r = run(sale_row(), site)
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 2464.07} and r.evidence["decided_on"] == "claim_tms"
    # three reads: the two year files and the delinquent list
    assert len(site.asked) == 3 and any("tax-del.cgi" in u for u in site.asked)


def test_a_bill_on_the_delinquent_list_was_paid_late():
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, paid=date(2026, 9, 11), msg="SW FEE PAID 260911")]},
                    dels={KEY: [bill_tr(2023, paid=date(2024, 8, 5), msg="S SCHEDULED FOR TAX SALE"),
                                bill_tr(2024, paid=date(2025, 8, 17), msg="S SCHEDULED FOR TAX SALE")]})
    r = run(sale_row(), site)
    assert r.verdict == "stale", r.evidence
    assert r.evidence["late_levy_years"] == [2023, 2024, 2025] and r.evidence["chronic_claim"] == "confirmed"
    assert "tax_lien_chronic" not in f.governs_for(r.to_dict())
    assert "scheduled_for_tax_sale" in r.evidence["flags"]


def test_paid_by_the_deadline_is_refuted():
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, paid=date(2025, 12, 30))],
                           ("rpcpubp2", KEY): [bill_tr(2024, paid=date(2024, 11, 2))]})
    r = run(sale_row(), site)
    assert r.verdict == "refuted", r.evidence
    assert r.evidence["current_claim_basis"] == "claimed_years_on_time"


def test_not_found_and_failures():
    assert run(sale_row(), FakeSite()).evidence["reason"] == "parcel_not_found"
    site = FakeSite(fail=9)
    assert run(sale_row(), site).evidence["reason"] == "fetch_failed"
    run(sale_row(), site)
    run(sale_row(), site)
    assert run(sale_row(), site).evidence["reason"] == "portal_unhealthy"


def test_the_year_files_moved_on():
    """When the roll moves (the 'current' file now holds another levy), the file the answer points
    at is read once more."""
    site = FakeSite(years={("rpcpubf", KEY): [bill_tr(2025, red=True, label="Total Due", total=900.0)],
                           ("rpcpubp1", KEY): [bill_tr(2024, paid=date(2024, 12, 1))]})
    r = asyncio.run(f.verify(sale_row(), site, today=date(2026, 9, 20)))   # assumes current = 2026
    assert r.verdict == "confirmed" and r.evidence["delinquent_by_year"] == {"2025": 900.0}, r.evidence


def test_claim_and_board_disagree():
    other = ("00888", "12", "345")
    row = sale_row(parcel_id="888-12-345")
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, red=True, label="Total Due")],
                           ("rpcpubp1", " ".join(other)): [bill_tr(2025, mbp=" ".join(other), paid=date(2025, 11, 1))]})
    r = run(row, site)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "identity_conflict")


def test_personal_property_and_other_parcels_are_not_read():
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, typ="Pers", red=True, label="Total Due"),
                                               bill_tr(2025, mbp="00777 12 346", red=True, label="Total Due")]})
    assert run(sale_row(), site).evidence["reason"] == "parcel_not_found"


def test_public_evidence_names_nobody():
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, red=True, label="Total Due")]})
    blob = json.dumps(run(sale_row(), site).to_dict())
    assert "TESTOWNER" not in blob and "TEST BILLING" not in blob and "25000001" not in blob


def test_the_gate_sees_a_check_of_the_rows_own_parcel():
    from foreclosure_scraper.tax_binding import verified_checks_row
    site = FakeSite(years={("rpcpubp1", KEY): [bill_tr(2025, red=True, label="Total Due")]})
    r = run(sale_row(), site)
    assert r.evidence["tax_parcel"] == "00777-12-345" and verified_checks_row(sale_row(), r.evidence)
