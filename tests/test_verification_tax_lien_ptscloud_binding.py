"""tax_lien_ptscloud v4 (2026-10-07): `confirmed` binds to the ROW'S OWN parcel and owner.

The live re-check for the lawyer package found 15 of the 54 confirmed PTS Cloud verdicts carried a
bill owner different from the row's owner and 4 only a partial one. The cause: the roll block of one
parcel had been merged into four unrelated Henderson rows (UST incident sites, code-violation
cases), and `confirmed` was the first parcel searched owing anything: no address binding, no owner
test (those guarded stale / refuted only). Each test below fails on v3.

Everything here is synthetic: made-up owners (TESTOWNER...), made-up streets (TEST ...), the shape of
the real SimpleBillSearch / GetbillDetails answers. No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from urllib.parse import quote

import pytest

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import tax_lien_ptscloud as p

TODAY = date(2026, 10, 7)
UST = "counties_generic.state_contamination.nc_ust_incidents"


def bill(parcel, year, due, status, addr, owner, *, owner2=None, bid=None):
    return {"id": bid or f"{parcel}{year}", "billNumber": f"{parcel}-{year}", "taxYear": str(year),
            "parcelId": parcel, "billParentType": "Real Property", "billType": "REG",
            "billStatus": status, "originalBillAmount": due, "amountDue": due if status == "UNPAID" else 0,
            "flags": [], "propertyAddress1": addr, "ownerName1": owner, "ownerName2": owner2,
            "additionalOwners": []}


def search(query, results, tenant="Henderson"):
    url = p.SEARCH_URL.format(q=quote(query, safe=""), tenant=quote(tenant))
    return url, json.dumps({"totalCount": len(results), "filteredCount": len(results), "results": results})


def detail(bill_id, paid_on, tenant="Henderson", begin="2026-01-07"):
    url = p.DETAIL_URL.format(bill_id=quote(bill_id), tenant=quote(tenant))
    body = {"statusType": "PAID", "interestBeginDate": f"{begin}T00:00:00",
            "lastPaymentDate": f"{paid_on}T00:00:00", "interestPaid": 0,
            "transactions": [{"transactionType": "PAYMENT",
                              "transactionCreationDate": f"{paid_on}T10:00:00"}]}
    return url, json.dumps(body)


def served(*pairs):
    return ReplayFetcher(dict(pairs))


def run(row, fetcher):
    return asyncio.run(p.verify(row, fetcher, today=TODAY))


def merged_row(**kw):
    """A UST-incident row with another parcel's roll block merged in (the live Henderson shape)."""
    r = {"state": "NC", "county": "Henderson", "listing_type": "tax_lien", "source": UST,
         "parcel_id": "9000000001", "street_address": "20 TEST MORGAN RD", "owner_name": "TESTOWNER VFD",
         "raw": {p.ROLL_KEY: {"tenant": "Henderson", "parcel": "100579", "tax_year": "2025",
                              "bill_number": None}}}
    r.update(kw)
    return r


def neighbour_bills():
    """Parcel 100579: a different property (another street), another owner, 2025 unpaid."""
    return search("100579", [bill("100579", 2025, 281.42, "UNPAID", "210 TEST KING ST", "BANKS, TESTSAM"),
                             bill("100579", 2024, 270.0, "PAID", "210 TEST KING ST", "BANKS, TESTSAM")])


def own_parcel_bills(owner="TESTOWNER VFD"):
    """Parcel 9935013: the row's own address, 2024 and 2025 paid, the 2026 bill open (not late yet)."""
    return search("20 TEST MORGAN", [
        bill("9935013", 2026, 270.0, "UNPAID", "20 TEST MORGAN RD", owner),
        bill("9935013", 2025, 260.0, "PAID", "20 TEST MORGAN RD", owner, bid="25"),
        bill("9935013", 2024, 250.0, "PAID", "20 TEST MORGAN RD", owner, bid="24")])


def own_parcel_by_number(owner="TESTOWNER VFD"):
    url, body = own_parcel_bills(owner)
    return search("9935013", json.loads(body)["results"])


# ---------------------------------------------------------------------------
# a roll block merged into another source's row is not the row's parcel
# ---------------------------------------------------------------------------

def test_version_is_v4():
    assert p.VERSION == "v4"


def test_a_merged_neighbour_block_does_not_confirm_a_row_at_another_address():
    """20 L M Morgan Rd shape: the neighbour parcel owes $281.42, the row's own parcel (found by the
    row's address) is paid. v3 confirmed the neighbour's balance."""
    f = served(neighbour_bills(), own_parcel_bills(), own_parcel_by_number(),
               detail("25", "2025-11-20"), detail("24", "2024-11-20"))
    r = run(merged_row(), f)
    assert r.verdict == "refuted", r.evidence                     # the row's own parcel is paid
    ev = r.evidence
    assert ev["tax_parcel"] == "9935013" and ev["followed_from_parcel"] == "100579"
    assert ev["followed_because"] == "owner_follows_address"
    assert ev["address_relation"] == "match" or ev["address_binding"] == "followed"
    assert not ev.get("delinquent_by_year")                       # the neighbour's $281.42 is not the row's


def test_the_address_parcel_is_not_followed_without_proof_the_block_is_wrong():
    """Same shape, but the owner on the address parcel is not the row's either: which account is
    the row's cannot be told (account_choice): unconfirmed, never confirmed on the neighbour."""
    f = served(neighbour_bills(), own_parcel_bills(owner="SOMEBODY, ELSE"), own_parcel_by_number("SOMEBODY, ELSE"))
    r = run(merged_row(), f)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    assert r.evidence["address_pins"] == ["9935013"]


def test_a_mailing_address_is_not_a_property_address():
    """38 Macedonia Rd shape: the address search matches a parcel whose MAILING address is the
    row's, its own (property) address is elsewhere. Nothing carries the row's address: v3 confirmed
    the merged neighbour's balance, v4 says address_not_found."""
    mailing_hit = search("38 TEST MACEDONIA", [
        bill("777", 2025, 150.0, "PAID", "2014 TEST PACE MOUNTAIN RD", "TESTOWNER MAILER")])
    f = served(neighbour_bills(), mailing_hit)
    r = run(merged_row(street_address="38 TEST MACEDONIA RD", owner_name="TESTOWNER MAILER"), f)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")
    assert r.evidence["address_relation"] == "conflict" and r.evidence["address_matches"] == 0


def test_only_the_parcels_current_address_counts_not_an_old_bills_mailing_address():
    """The live 38 Macedonia Rd shape: parcel 777's OLD bills carry the owner's mailing address
    (the row's address) in the property-address field, its newest bills the real one. The address
    search answers with only the old bills whose text matched; the parcel's own bills show its
    current address, so the row is not bound to it (v3 and the first v4 draft bound it)."""
    old_mailing = [bill("777", y, 150.0, "PAID", "38 TEST MACEDONIA RD", "TESTOWNER MAILER") for y in (2018, 2019)]
    whole = old_mailing + [bill("777", y, 150.0, "PAID", "2014 TEST PACE MOUNTAIN RD", "TESTOWNER MAILER")
                           for y in (2025, 2026)]
    f = served(neighbour_bills(), search("38 TEST MACEDONIA", old_mailing), search("777", whole))
    r = run(merged_row(street_address="38 TEST MACEDONIA RD", owner_name="TESTOWNER MAILER"), f)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")
    assert r.evidence["address_matches"] == 0
    assert search("777", whole)[0] in f.asked                       # its own bills were read


def test_a_parcel_whose_current_address_is_the_rows_is_bound_through_its_own_bills():
    only_new = [bill("778", y, 150.0, "PAID", "38 TEST MACEDONIA RD", "TESTOWNER VFD") for y in (2025, 2026)]
    f = served(neighbour_bills(), search("38 TEST MACEDONIA", only_new), search("778", only_new),
               detail("778", "2025-11-01"))
    r = run(merged_row(street_address="38 TEST MACEDONIA RD"), f)
    assert r.evidence.get("followed_from_parcel") == "100579" and r.evidence["tax_parcel"] == "778"


def test_addresses_and_candidates_read_the_right_year():
    raw = [bill("1", 2019, 1.0, "PAID", "9 OLD MAIL ST", "X"), bill("1", 2025, 1.0, "PAID", "5 NEW ST", "X"),
           bill("1", 2025, 2.0, "UNPAID", "5 NEW ST", "X")]
    assert p._addresses(p.bills_of({"results": raw}, "1")) == ["5 NEW ST"] and p._addresses([]) == []
    payload = {"results": [bill("1", 2019, 1.0, "PAID", "9 OLD MAIL ST", "X"),
                           bill("2", 2024, 1.0, "PAID", "7 OTHER ST", "Y")]}
    assert p._candidates(payload, "9 OLD MAIL ST") == {"1": "9 OLD MAIL ST"}    # any year: a candidate only
    assert p._candidates(payload, "1 NOWHERE ST") == {}


def test_an_exact_parcel_number_binds_confirmed_whatever_address_the_county_printed():
    """Guilford / Pitt / old Madison bills print the owner's mailing address as the property
    address. The roll's own row (the number is exact) stays confirmed; the conflict is recorded.
    (v3 had no binding; a first v4 draft vetoed these on the address.)"""
    row = {"state": "NC", "county": "Henderson", "listing_type": "tax_lien", "source": p.ROLL_SLUG,
           "parcel_id": "700001", "street_address": "5 TEST OAK ST", "owner_name": "TESTOWNER ALPHA",
           "raw": {p.ROLL_KEY: {"tenant": "Henderson", "parcel": "700001", "tax_year": "2025"}}}
    r = run(row, served(owed("TESTOWNER ALPHA", addr="223 TEST MAILING ST")))
    assert r.verdict == "confirmed" and r.evidence["address_relation"] == "conflict"
    assert r.evidence["address_binding"] == "parcel_number" and r.evidence["tax_parcel_row_own"] is True


def test_an_exact_number_with_an_unusable_county_address_is_not_followed_away_when_it_owes():
    """Madison: the PIN-keyed record holds the old unpaid bill and prints no usable address; another
    parcel carries the row's address and is paid. The unpaid bill on the row's own PIN stands
    (following the address would have made it `stale`, a suppressing verdict, on a real balance)."""
    row = {"state": "NC", "county": "Henderson", "listing_type": "tax_lien", "source": p.ROLL_SLUG,
           "parcel_id": "700001", "street_address": "5 TEST OAK ST", "owner_name": "TESTOWNER ALPHA",
           "raw": {p.ROLL_KEY: {"tenant": "Henderson", "parcel": "700001", "tax_year": "2013"}}}
    pin_record = search("700001", [bill("700001", 2013, 196.31, "UNPAID", "0 NO ADDRESS ASSIGNED", "TESTOWNER ALPHA")])
    elsewhere = search("5 TEST OAK", [bill("19757", 2025, 300.0, "PAID", "5 TEST OAK ST", "TESTOWNER ALPHA")])
    r = run(row, served(pin_record, elsewhere))
    assert r.verdict == "confirmed" and r.evidence["tax_parcel"] == "700001"
    assert r.evidence["total_delinquent"] == 196.31 and "followed_from_parcel" not in r.evidence


def test_a_merged_block_with_no_address_and_no_number_the_row_carries_is_unbound():
    """Nothing ties the merged block to the row: no address to compare, the row's parcel_id is not
    the block's parcel. v3 confirmed it; the same block on the roll's OWN row still confirms."""
    unbound = merged_row(street_address=None, owner_name=None)
    r = run(unbound, served(neighbour_bills()))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "roll_block_unbound")
    assert r.evidence["tax_parcel_row_own"] is False

    roll_own = merged_row(street_address=None, owner_name=None, source=p.ROLL_SLUG)
    ok = run(roll_own, served(neighbour_bills()))
    assert ok.verdict == "confirmed" and ok.evidence["tax_parcel_row_own"] is True


def test_a_merged_block_whose_parcel_has_no_usable_address_is_unbound_too():
    nothing = search("100579", [bill("100579", 2025, 90.0, "UNPAID", "0 NO ADDRESS ASSIGNED", "BANKS, TESTSAM")])
    miss = search("20 TEST MORGAN", [])
    r = run(merged_row(), served(nothing, miss))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "roll_block_unbound")


def test_the_same_block_is_the_rows_when_the_row_carries_that_parcel_number():
    """A land-records REID that equals the block's parcel is a number the row itself carries."""
    row = merged_row(street_address=None, owner_name=None)
    row["raw"]["lrcpwa"] = {"reid": "100579"}
    r = run(row, served(neighbour_bills()))
    assert r.verdict == "confirmed" and r.evidence["tax_parcel_row_own"] is True
    assert r.evidence.get("owner_match") is None                  # no owner on the row: nothing contradicts


def test_a_bills_address_that_equals_the_rows_binds_a_merged_block():
    row = merged_row(street_address="210 TEST KING ST", owner_name="BANKS, TESTSAM")
    r = run(row, served(neighbour_bills()))
    assert r.verdict == "confirmed" and r.evidence["address_binding"] == "bill_address"
    assert r.evidence["tax_parcel_row_own"] is False and r.evidence["owner_match"] == "same"


# ---------------------------------------------------------------------------
# the owner on the bills
# ---------------------------------------------------------------------------

def board_row(owner, **kw):
    r = {"state": "NC", "county": "Henderson", "listing_type": "tax_lien", "source": "counties_nc.testsrc",
         "parcel_id": "700001", "street_address": "5 TEST OAK ST", "owner_name": owner, "raw": {}}
    r.update(kw)
    return r


def owed(owner, owner2=None, addr="5 TEST OAK ST"):
    return search("700001", [bill("700001", 2025, 300.0, "UNPAID", addr, owner, owner2=owner2)])


def test_a_differing_owner_with_an_exact_parcel_number_stays_confirmed_and_says_why():
    r = run(board_row("TESTOWNER ALPHA"), served(owed("OMEGA, BETA")))
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "different"
    assert r.evidence["owner_corroborated_by"] == "pin_exact"
    assert r.evidence["tax_parcel_row_own"] is True


def test_a_differing_owner_without_corroboration_is_unconfirmed():
    """The parcel number a resolver attached is a guess, not corroboration (v3: confirmed)."""
    row = board_row("TESTOWNER ALPHA", raw={"parcel_from_address": {"source": "parcel_cache_situs_address"}})
    r = run(row, served(owed("OMEGA, BETA")))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "bill_owner_differs")
    assert r.evidence["owner_match"] == "different" and "owner_corroborated_by" not in r.evidence


def test_a_partial_owner_without_corroboration_is_unconfirmed():
    row = board_row("TESTOWNER ALPHA", raw={"parcel_from_geo": {"source": "ptscloud_pts_to_pin"}})
    r = run(row, served(owed("TESTOWNER, OMEGA")))              # shares only the surname
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "bill_owner_partial")
    assert r.evidence["owner_match"] == "partial"


@pytest.mark.parametrize("row_owner,bill_owner", [
    ("Testowner, Alpha Marie", "TESTOWNER ALPHA M"),              # surname-first vs surname-first caps
    ("Alpha M Testowner", "TESTOWNER ALPHA MARIE ET AL"),         # natural order, Title Case, ET AL
    ("TESTOWNER ALPHA JR", "Alpha Testowner"),                    # suffix ignored, case ignored
    ("TESTOWNER ALPHA", "TESTOWNER ALPHA & TESTOWNER BETA"),      # one of two owners
])
def test_the_same_owner_in_another_notation_confirms_even_without_corroboration(row_owner, bill_owner):
    row = board_row(row_owner, raw={"parcel_from_address": {"source": "parcel_cache_situs_address"}})
    r = run(row, served(owed(bill_owner)))
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "same"
    assert "owner_corroborated_by" not in r.evidence


def test_the_owner_on_the_unpaid_bill_counts_when_the_parcel_was_sold_since():
    """The latest (2026) bill names the new owner; the unpaid 2025 bill the row's owner."""
    res = [bill("700001", 2026, 310.0, "UNPAID", "5 TEST OAK ST", "NEWFOLK, SALLY"),
           bill("700001", 2025, 300.0, "UNPAID", "5 TEST OAK ST", "TESTOWNER ALPHA"),
           bill("700001", 2024, 290.0, "PAID", "5 TEST OAK ST", "TESTOWNER ALPHA")]
    row = board_row("TESTOWNER ALPHA", raw={"parcel_from_address": {"source": "parcel_cache_situs_address"}})
    r = run(row, served(search("700001", res)))
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "same"


def test_a_row_without_an_owner_is_not_contradicted():
    r = run(board_row(None, raw={"parcel_from_address": {"x": 1}}), served(owed("OMEGA, BETA")))
    assert r.verdict == "confirmed" and r.evidence.get("owner_match") is None


def test_the_address_parcel_confirms_only_with_an_agreeing_owner():
    """The merged block's parcel is not the row's; the row's own address parcel owes, but its owner
    is not the row's: bill_owner_differs (the board owner matches neither, so account_choice would
    not follow; with the owner on the address parcel the follow happens and it confirms)."""
    owed_own = search("20 TEST MORGAN", [bill("9935013", 2025, 260.0, "UNPAID", "20 TEST MORGAN RD", "TESTOWNER VFD")])
    f = served(neighbour_bills(), owed_own, search("9935013", json.loads(owed_own[1])["results"]))
    r = run(merged_row(), f)
    assert r.verdict == "confirmed"
    assert r.evidence["tax_parcel"] == "9935013" and r.evidence["total_delinquent"] == 260.0
    assert r.evidence["owner_match"] == "same" and r.evidence["followed_from_parcel"] == "100579"


# ---------------------------------------------------------------------------
# the row's own numbers (pure)
# ---------------------------------------------------------------------------

def blk(parcel="100579", **kw):
    return {"tenant": "Henderson", "parcel": parcel, "tax_year": "2025", **kw}


def test_row_parcel_ids_roll_own_row():
    row = {"county": "Henderson", "source": p.ROLL_SLUG, "parcel_id": "9595642133",
           "raw": {p.ROLL_KEY: blk("100579", parcel_raw="0"), "lrcpwa": {"reid": "55"}}}
    own, exact = p.row_parcel_ids(row, "Henderson", row["raw"][p.ROLL_KEY])
    assert own == exact == frozenset({"9595642133", "55", "100579"})


def test_row_parcel_ids_a_merged_block_is_not_the_rows():
    row = {"county": "Henderson", "source": UST, "parcel_id": "9595642133", "raw": {p.ROLL_KEY: blk()}}
    own, exact = p.row_parcel_ids(row, "Henderson", row["raw"][p.ROLL_KEY])
    assert own == exact == frozenset({"9595642133"})


def test_row_parcel_ids_a_moved_roll_row_and_a_resolver_corroborate_nothing():
    moved = {"county": "Hyde", "source": p.ROLL_SLUG, "parcel_id": "9500189104",
             "raw": {p.ROLL_KEY: dict(blk("78006"), tenant="Pitt")}}
    own, exact = p.row_parcel_ids(moved, "Pitt", moved["raw"][p.ROLL_KEY])
    assert own == frozenset({"9500189104", "78006"}) and exact == frozenset({"9500189104"})
    guessed = {"county": "Henderson", "source": UST, "parcel_id": "42",
               "raw": {"parcel_from_geo": {"source": "ptscloud_pts_to_pin"}, "lrcpwa": {"reid": "43"}}}
    own, exact = p.row_parcel_ids(guessed, "Henderson", None)
    assert own == frozenset({"42", "43"}) and exact == frozenset()
    placeholder = {"county": "Henderson", "source": UST, "parcel_id": "0000", "raw": {}}
    assert p.row_parcel_ids(placeholder, "Henderson", None) == (frozenset(), frozenset())


# ---------------------------------------------------------------------------
# an unconfirmed answer suppresses nothing
# ---------------------------------------------------------------------------

def test_the_new_unconfirmed_reasons_never_suppress_the_signal():
    assert "unconfirmed" not in core.SUPPRESSING and "confirmed" not in core.SUPPRESSING
    row = board_row("TESTOWNER ALPHA", raw={"parcel_from_address": {"x": 1}})
    r = run(row, served(owed("OMEGA, BETA")))
    assert r.verdict not in core.SUPPRESSING
    assert p.governs_for(r.to_dict())            # the verifier's GOVERNS are unchanged (stale / refuted only)
    assert "tax_lien:property_tax" in p.GOVERNS
