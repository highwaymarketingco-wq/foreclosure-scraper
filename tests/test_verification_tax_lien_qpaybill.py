"""tax_lien_qpaybill against REAL qPayBill answers captured 2026-10-06 (Williamsburg, Spartanburg,
Darlington, Laurens, Oconee, Horry, Orangeburg). tests/fixtures/verification/tax_lien_qpaybill.json.gz
keeps each page's real grid markup and values (notice, year, identification no., status, payment
date, amount); the owner/address and description cells are replaced by made-up text and the
viewstates by placeholders. No network."""
from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as q

FIX = Path(__file__).parent / "fixtures" / "verification"
FX = json.loads(gzip.decompress((FIX / "tax_lien_qpaybill.json.gz").read_bytes()))
TODAY = date(2026, 10, 6)


def served(*searches: str, extra: dict | None = None) -> ReplayFetcher:
    """A replay of each 'sub|criteria|value' search: the tenant's form, its criteria postback and
    the search, keyed exactly as the verifier posts them."""
    resp: dict = {}
    for key in searches:
        sub, crit, value = key.split("|")
        url = q.form_url(sub)
        form = FX["forms"][sub]
        crit_page = FX["criteria"][f"{sub}|{crit}"]
        resp[url] = form
        resp[form_key(url, q.criteria_data(q.viewstate(form), crit))] = crit_page
        resp[form_key(url, q.search_data(q.viewstate(crit_page), value, crit))] = FX["searches"][key]
    resp.update(extra or {})
    return ReplayFetcher(resp)


def owner_of(key: str) -> str:
    rows = q.parse_grid(FX["searches"][key])["rows"]
    return rows[0]["owner"]


def run(row, fetcher, today=TODAY):
    return asyncio.run(q.verify(row, fetcher, today=today))


def roll_row(county, ident, *, parcel=None, years=("2025",), notices=(), **kw):
    row = {"state": "SC", "county": county, "listing_type": "tax_sale",
           "source": "counties_sc.qpaybill_delinquent_roll", "parcel_id": parcel or ident,
           "raw": {"qpaybill_roll": {"identification_no": ident, "county": county,
                                     "years_unpaid": list(years),
                                     "notice_numbers": list(notices)}}}
    row.update(kw)
    return row


def names_absent(res, *names):
    blob = json.dumps(res.to_dict()).upper()
    return all(n.upper() not in blob for n in names if n)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def test_applies_only_to_sc_qpaybill_counties_with_a_property_tax_claim():
    assert q.applies(roll_row("Williamsburg", "45-338-010"))
    assert q.applies(roll_row("McCormick", "227-00-00-013.03"))          # case-insensitive map
    assert not q.applies(dict(roll_row("Williamsburg", "45-338-010"), state="NC"))
    assert not q.applies(roll_row("Greenville", "0001"))                 # not a qPayBill county
    assert not q.applies(roll_row("Buncombe", "0001", state="NC"))
    plain = {"state": "SC", "county": "Spartanburg", "parcel_id": "7-16-09-062.00", "raw": {}}
    assert q.applies(dict(plain, listing_type="tax_sale", source="counties_sc.spartanburg_delinquent_tax"))
    assert not q.applies(dict(plain, listing_type="foreclosure_sale", source="x"))
    # federal/state liens typed tax_lien are not property-tax claims...
    assert not q.applies(dict(plain, listing_type="tax_lien", source="counties_sc.sc_dew_lien_registry"))
    assert not q.applies(dict(plain, listing_type="tax_lien", source="counties_sc.sc_state_tax_lien"))
    # ...unless the row carries a property-tax claim of its own
    assert q.applies(dict(plain, listing_type="tax_lien", source="counties_sc.sc_dew_lien_registry",
                          raw={"two_year_delinquent": {"is_two_year_plus": True}}))
    assert q.applies(dict(plain, listing_type="unknown", source="x",
                          raw={"tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 2}}))
    # another county's roll block (a merge) is not this row's claim
    other = dict(plain, listing_type="foreclosure_sale", source="x",
                 raw={"qpaybill_roll": {"identification_no": "1", "county": "Kershaw"}})
    assert not q.applies(other) and q.roll_block(other) is None


def test_subjects_claim_first_board_second_cherokee_redashed():
    row = roll_row("Laurens", "022-00-00-017", parcel="022-00-00-041")
    assert q.subjects(row, "Laurens") == [("022-00-00-017", "claim"), ("022-00-00-041", "board")]
    same = roll_row("Bamberg", "0022-00-00-039.", parcel="0022-00-00-039")
    assert q.subjects(same, "Bamberg") == [("0022-00-00-039.", "claim")]
    assert q.board_parcel({"parcel_id": "0020000003000"}, "Cherokee") == "002-00-00-003.000"
    assert q.subjects({"state": "SC", "county": "Oconee", "raw": {}}, "Oconee") == []


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

def test_deadline_is_january_15_rolled_to_a_weekday():
    assert q.deadline(2025) == date(2026, 1, 15)
    assert q.deadline(2027) == date(2028, 1, 17)          # Jan 15 2028 is a Saturday
    assert not q.is_eligible(2025, date(2026, 1, 15))
    assert q.is_eligible(2025, date(2026, 1, 16))
    assert q.latest_eligible(TODAY) == 2025
    assert q.latest_eligible(date(2026, 1, 10)) == 2024


def test_grid_keeps_paid_rows_and_reads_exact_identification_numbers():
    g = q.parse_grid(FX["searches"]["williamsburgtreasurer|Map|45-338-010"])
    assert len(g["rows"]) == 25 and not g["no_match"]
    assert {r["status"] for r in g["rows"]} == {"Paid", "Unpaid"}
    mine = q.select_rows(g["rows"], "45-338-010")
    assert len(mine) == 17                                  # not the 8 rows of 45-338-010.A
    # a full page: complete for 45-338-010 (the .A rows follow it), maybe not for 45-338-010.A
    assert not q.page_capped(g["rows"], "45-338-010", True)
    assert q.page_capped(g["rows"], "45-338-010.A", True)
    nm = q.parse_grid(FX["searches"]["spartanburgcountytax|Map|9-99-99-999.99"])
    assert nm["rows"] == [] and nm["no_match"]


# ---------------------------------------------------------------------------
# verdicts on real answers
# ---------------------------------------------------------------------------

def test_confirmed_unpaid_2025_williamsburg():
    key = "williamsburgtreasurer|Map|45-338-010"
    owner = owner_of(key)
    row = roll_row("Williamsburg", "45-338-010", owner_name=owner)
    res = run(row, served(key))
    ev = res.evidence
    assert res.verdict == "confirmed" and res.verifier == "tax_lien_qpaybill"
    assert res.signal == "tax_lien" and res.source == "qpaybill.com"
    assert ev["delinquent_by_year"] == {"2025": 219.34} and ev["years_delinquent"] == 1
    assert ev["total_delinquent"] == 219.34 and ev["under_500"] and not ev["de_minimis"]
    assert ev["owner_match"] == "same" and ev["decided_on"] == "claim_ident"
    assert ev["searched"][0]["rows"] == 17
    assert names_absent(res, owner)


def test_both_parcels_delinquent_is_confirmed_on_the_claim():
    a, b = "spartanburgcountytax|Map|3-28-00-143.03", "spartanburgcountytax|Map|7-22-00-001.00"
    row = roll_row("Spartanburg", "3-28-00-143.03", parcel="7-22-00-001.00")
    res = run(row, served(a, b))
    assert res.verdict == "confirmed"
    assert res.evidence["decided_on"] == "claim_ident"
    assert res.evidence["delinquent_by_year"] == {"2025": 374.69}
    assert [s["role"] for s in res.evidence["searched"]] == ["claim", "board"]


def test_identity_conflict_when_only_the_board_parcel_owes():
    a, b = "laurenstreasurer|Map|022-00-00-017", "laurenstreasurer|Map|022-00-00-041"
    res = run(roll_row("Laurens", "022-00-00-017", parcel="022-00-00-041"), served(a, b))
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "identity_conflict"
    assert res.evidence["delinquent_parcel"] == "board"


def test_stale_claim_paid_after_the_deadline_darlington():
    a, b = "darlingtontreasurer|Map|104-00-01-121", "darlingtontreasurer|Map|067-07-03-066"
    res = run(roll_row("Darlington", "104-00-01-121", parcel="067-07-03-066"), served(a, b))
    assert res.verdict == "stale"
    first = res.evidence["bills_checked"][0]
    assert first["year"] == 2025 and first["paid_late"] is True
    assert first["paid_on"] > first["deadline"] == "2026-01-15"
    assert res.evidence["not_yet_delinquent_due"] == {"2026": 207.63}


def test_stale_account_paid_in_september_oconee():
    res = run(roll_row("Oconee", "25317", parcel=None), served("oconeesctax|Map|25317"))
    assert res.verdict == "stale"
    assert res.evidence["bills_checked"][0] == {"year": 2025, "status": "Paid",
                                                 "paid_on": "2026-09-20",
                                                 "deadline": "2026-01-15", "paid_late": True}


def test_refuted_paid_on_time_and_no_claimed_year():
    row = {"state": "SC", "county": "Spartanburg", "parcel_id": "7-16-09-062.00",
           "listing_type": "tax_sale", "source": "counties_sc.spartanburg_delinquent_tax", "raw": {}}
    res = run(row, served("spartanburgcountytax|Map|7-16-09-062.00"))
    assert res.verdict == "refuted"
    checks = res.evidence["bills_checked"]
    assert [c["year"] for c in checks] == [2025, 2024]
    assert all(c["paid_late"] is False for c in checks)
    assert res.evidence["decided_on"] == "board_parcel"


def test_other_lien_listing_is_never_suppressed():
    """A DEW lien row carrying a delinquency flag (a mixed row): the county says the property tax
    was paid on time, and that refuted answer is published as it is (the downgrade to unconfirmed
    is retired, _tax_common); the qualified GOVERNS keeps it from ending the DEW lien's own
    tax_lien signal (test_verification_tax_lien_other_lien)."""
    row = {"state": "SC", "county": "Spartanburg", "parcel_id": "7-16-09-062.00",
           "listing_type": "tax_lien", "source": "counties_sc.sc_dew_lien_registry",
           "raw": {"two_year_delinquent": {"is_two_year_plus": True, "tax_year": "2024"}}}
    assert q.applies(row)
    res = run(row, served("spartanburgcountytax|Map|7-16-09-062.00"))
    assert res.verdict == "refuted"
    assert not {"reason", "property_tax_verdict", "listing_claim_source"} & set(res.evidence)
    assert "tax_lien:property_tax" in q.GOVERNS and "tax_lien" not in q.GOVERNS


def test_receipt_fallback_horry_reads_the_claimed_bills():
    keys = ("horrycountytreasurer|Map|99800086567", "horrycountytreasurer|Receipt|386084253",
            "horrycountytreasurer|Receipt|384217243", "horrycountytreasurer|Map|39307010208")
    row = roll_row("Horry", "99800086567", parcel="39307010208", years=("2024", "2025"),
                   notices=("384217243", "386084253"), source="counties_sc.horry_delinquent_xlsx",
                   listing_type="tax_lien")
    f = served(*keys)
    res = run(row, f)
    assert res.verdict == "stale"
    assert res.evidence["decided_on"] == "claim_receipts"
    roles = [(s["role"], s.get("map_number") or s.get("receipt"), s["found"])
             for s in res.evidence["searched"]]
    assert roles == [("claim", "99800086567", False), ("claim_receipt", "386084253", True),
                     ("claim_receipt", "384217243", True), ("board", "39307010208", False)]
    # the claimed 2025 bill was paid on 2026-09-22, after its 2026-01-15 deadline
    assert res.evidence["bills_checked"] == [{"year": 2025, "status": "Paid", "paid_on": "2026-09-22",
                                              "deadline": "2026-01-15", "paid_late": True}]
    # one form + one criteria postback per criteria, then one request per search
    assert len(f.asked) == 2 + 2 + 4


def test_receipt_fallback_orangeburg_confirmed():
    keys = ("orangeburgtreasurer|Map|0970023", "orangeburgtreasurer|Receipt|007255255")
    row = roll_row("Orangeburg", "0970023", parcel=None, notices=("007255255",))
    res = run(row, served(*keys))
    assert res.verdict == "confirmed"
    assert res.evidence["decided_on"] == "claim_receipts"
    assert res.evidence["delinquent_by_year"] == {"2025": 229.68}


def test_not_on_the_portal_is_unconfirmed():
    row = {"state": "SC", "county": "Spartanburg", "parcel_id": "9-99-99-999.99",
           "listing_type": "tax_sale", "source": "x", "raw": {}}
    res = run(row, served("spartanburgcountytax|Map|9-99-99-999.99"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_not_found"


def test_parcel_record_ended_is_unconfirmed():
    row = {"state": "SC", "county": "Spartanburg", "parcel_id": "7-16-09-062.00",
           "listing_type": "tax_sale", "source": "x", "raw": {}}
    res = run(row, served("spartanburgcountytax|Map|7-16-09-062.00"), today=date(2028, 2, 1))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_record_ended"
    assert res.evidence["latest_delinquent_eligible_levy"] == 2027


def test_no_identifier_is_unconfirmed_without_a_request():
    f = ReplayFetcher({})
    res = run({"state": "SC", "county": "Lee", "listing_type": "tax_sale", "source": "x", "raw": {}}, f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_unresolvable"
    assert f.asked == []


# ---------------------------------------------------------------------------
# sessions and tenant health
# ---------------------------------------------------------------------------

def test_one_session_per_tenant_per_run():
    a, b = "spartanburgcountytax|Map|3-28-00-143.03", "spartanburgcountytax|Map|7-16-09-062.00"
    f = served(a, b)
    run(roll_row("Spartanburg", "3-28-00-143.03"), f)
    run({"state": "SC", "county": "Spartanburg", "parcel_id": "7-16-09-062.00",
         "listing_type": "tax_sale", "source": "x", "raw": {}}, f)
    url = q.form_url("spartanburgcountytax")
    assert f.asked.count(url) == 1 and len(f.asked) == 4          # form, criteria, 2 searches
    run(roll_row("Spartanburg", "3-28-00-143.03"), f)              # cached for the run
    assert len(f.asked) == 4


def test_generic_error_page_marks_the_tenant_unhealthy_for_the_run():
    url = q.form_url("williamsburgtreasurer")
    f = ReplayFetcher({url: {"status": 200, "text": "<html><body>An error occurred.</body></html>",
                             "url": "https://williamsburgtreasurer.qpaybill.com/GenericErrorPage.aspx"}})
    res = run(roll_row("Williamsburg", "45-338-010"), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "tenant_unhealthy"
    assert "generic_error_page" in res.evidence["tenant_health"]
    asked = len(f.asked)
    res2 = run(roll_row("Williamsburg", "45-221-070"), f)
    assert res2.verdict == "unconfirmed" and res2.evidence["reason"] == "tenant_unhealthy"
    assert len(f.asked) == asked                                   # no request to a dead tenant


def test_a_hanging_tenant_fails_twice_then_is_skipped():
    f = ReplayFetcher({})            # every request raises LookupError, like a timeout would
    r1 = run(roll_row("Darlington", "104-00-01-121"), f)
    r2 = run(roll_row("Darlington", "104-00-01-122"), f)
    assert r1.evidence["reason"] == r2.evidence["reason"] == "fetch_failed"
    n = len(f.asked)
    r3 = run(roll_row("Darlington", "104-00-01-123"), f)
    assert r3.verdict == "unconfirmed" and r3.evidence["reason"] == "tenant_unhealthy"
    assert len(f.asked) == n


# ---------------------------------------------------------------------------
# privacy: the ledger is public
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key,row", [
    ("williamsburgtreasurer|Map|45-338-010", roll_row("Williamsburg", "45-338-010")),
    ("oconeesctax|Map|25317", roll_row("Oconee", "25317", parcel=None)),
])
def test_evidence_is_a_whitelist_without_names(key, row):
    owner = owner_of(key)
    res = run(dict(row, owner_name=owner), served(key))
    assert set(res.evidence) <= set(q._KEYS)
    for s in res.evidence.get("searched") or []:
        assert set(s) <= set(q._SEARCHED_KEYS)
    assert names_absent(res, owner, "100 TEST RD", "TEST DESCRIPTION")
    assert q.ROW_SUMMARY_EXCLUDE == ("owner_name",)
