"""tax_lien verifiers v5 / v3 / v3 (2026-10-06): the defects the independent live re-check of the 51
`refuted` ledger entries found (49 Buncombe, 2 Union SC), each pinned on a REAL shape and each
failing on the pre-fix code (tax_lien_buncombe v4, tax_lien_ptscloud v2, tax_lien_qpaybill v2, a
ledger that gave one entry to every row of a parcel).

Fixture tests/fixtures/verification/tax_lien_history_shapes.json.gz: compact, name-free shapes of
the live tax.buncombenc.gov pages of the real cases (captured 2026-10-06): per parcel its situs,
and per bill the number, the amount due, the card's value and the Transactions rows (type, date,
tax, late fee, interest, cost); plus the address searches. The helpers below rebuild the site's
markup from them; owners are made-up placeholders chosen to reproduce the owner CATEGORY the
live run measured (same / different).

DEFECTS (numbers as in the task):
  1 Sibling rows on one ledger key (Rabbit Hill 16 / 18, Pole Creasman 586 / 756, a hotel parcel
    shared by a UST row and a lien-agent row): a verdict is about the parcel AND address of the
    row it was verified for.
  2 Following the address away from a county-supplied PIN (2614 Old Fort Rd, 16 Rabbit Hill Dr).
  3 Chronic late payers refuted: two claims judged apart, late_levy_years in the evidence,
    per-record governs, stale when the claimed year (or a bill delinquent at first_seen) was late.
  4 Union SC / PTS Cloud: the address account and the row's own account disagree.
  5 No parcel carries the address: address_not_found, never an invented binding.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
import importlib.util
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import apply as A
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as tb

REPO = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
SHAPES = json.loads(gzip.decompress((FIX / "tax_lien_history_shapes.json.gz").read_bytes()))
PARCELS, SEARCHES = SHAPES["parcels"], SHAPES["searches"]

SAME, OTHER = "JO EXAMPLE", "PAT SAMPLE"        # made-up owners: the category is what is measured


# ===========================================================================
# the site's markup, rebuilt from the captured shapes
# ===========================================================================

def _card(bill, amount_due, legal, value, owner, pin):
    badge = '<span class="badge bg-warning">See Legal</span>' if legal else ""
    amt = ('<div class="text-danger fw-semibold">See Legal</div>' if legal
           else f'<div class="fw-semibold">${amount_due:,.2f}</div>')
    return f'''<div class="col-12"><div class="card history-card shadow-sm">
<div class="card-header bg-light"><div class="d-flex justify-content-between align-items-center">
<h3 class="h6 mb-0"><a href="/Bill/Details/{bill}">{bill}</a></h3>{badge}</div></div>
<div class="card-body"><div class="row"><div class="col-6"><small class="text-muted d-block">Owner</small>
<div class="fw-semibold"> {owner}</div></div><div class="col-6 text-end">
<small class="text-muted d-block">Value</small><div class="fw-semibold">${value:,.0f}</div></div></div>
<div class="row mt-2"><div class="col-6"><small class="text-muted d-block">PIN</small><div>{pin}</div></div>
<div class="col-6 text-end"><small class="text-muted d-block">Amount Due</small>{amt}</div></div></div></div></div>'''


def parcel_page(pin, owner=SAME, shape=None):
    s = shape or PARCELS[pin]
    banner = ('<div class="alert alert-warning"><strong>You are viewing an inactive parcel.</strong></div>'
              if s["inactive"] else "")
    cards = "".join(_card(b["bill"], b["amount_due"] or 0.0, b["see_legal"], b["value"] or s["value"] or 0,
                          owner, pin) for b in s["bills"])
    return (f'<html><body>{banner}<h1 class="card-title h2 mb-2">{s["situs"]}</h1>'
            f'<div class="d-block d-md-none"><div class="row g-3">{cards}</div></div></body></html>')


def bill_page(rows):
    def money(v):
        return f"(${abs(v):,.2f})" if v < 0 else f"${v:,.2f}"
    trs = "".join(f"<tr><td>{t}</td><td>{d}</td><td></td><td>{money(a)}</td><td>{money(b)}</td>"
                  f"<td>{money(c)}</td><td>{money(e)}</td><td>{money(a + b + c + e)}</td></tr>"
                  for t, d, a, b, c, e in rows)
    return (f'<html><body><section class="transactions my-4"><table><thead><tr><th>Type</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></section></body></html>')


def search_page(found):
    if not found:
        return ('<html><body><div class="alert alert-warning"> Sorry, we didn\'t find any results. '
                'Try removing words from your search and checking spelling. </div></body></html>')
    cards = "".join(f'<div class="col"><div class="card shadow mb-3"><div class="card-body">'
                    f'<h6 class="card-subtitle mb-1">\n  {pin}\n</h6>'
                    f'<a href="/Parcel/Details/{pin}?Query=x"><h4 class="card-title text-uppercase">{a}</h4></a>'
                    f'</div></div></div>' for pin, a in found)
    return f'<html><body><div class="search-results row">{cards}</div></body></html>'


def pages(pins, owners=None, searches=(), shape_override=None):
    """{url: page} for these parcels (their parcel page and every captured bill page) and these
    address searches (keys of SEARCHES)."""
    out = {}
    for pin in pins:
        s = (shape_override or {}).get(pin) or PARCELS[pin]
        out[f"{tb.BASE}/Parcel/Details/{pin}"] = parcel_page(pin, (owners or {}).get(pin, SAME), s)
        for b in s["bills"]:
            if b["tx"] is not None:
                out[f"{tb.BASE}/Bill/Details/{b['bill']}"] = bill_page(b["tx"])
    for q in searches:
        out[f"{tb.BASE}/Search/Results?QueryType=Address&Query={quote_plus(q)}"] = search_page(SEARCHES[q])
    return out


def brow(parcel, addr, *, owner=SAME, claimed=(2025,), first_seen="2026-09-15T14:56:18", **kw):
    r = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien", "parcel_id": parcel,
         "street_address": addr, "source": "counties_generic.arcgis_distress.buncombe_unpaid_bills",
         "owner_name": owner, "first_seen": first_seen, "raw": {}}
    if claimed:
        r["raw"]["tax_owed"] = {"balance": 171.74, "kind": "delinquent_tax", "year": max(claimed)}
    r.update(kw)
    return r


def run(row, pages_, today=TODAY):
    f = ReplayFetcher(pages_)
    return asyncio.run(tb.verify(row, f, today=today)), f


def _result_dict(res):
    return res.to_dict()


# ===========================================================================
# 5. no parcel carries the address
# ===========================================================================

def test_the_county_empty_search_answer_is_readable_and_empty():
    """"Sorry, we didn't find any results" has no search-results container: v4 read it as an
    unreadable page (address_search_unreadable)."""
    assert tb.parse_search_results(search_page([])) == []
    assert tb.parse_search_results("<html><body>an error page</body></html>") is None
    assert tb.parse_search_results(search_page([("975469477200000", "7 ISLAND IN THE SKY TRL")])) == [
        {"pin": "975469477200000", "address": "7 ISLAND IN THE SKY TRL"}]


def test_600_glen_bridge_rd_no_parcel_carries_it_the_ledger_pin_is_620_glenn_bridge_rd():
    row = brow("964308731700000", "600 Glen Bridge rd.", source="liensnc", claimed=())
    r, f = run(row, pages(["964308731700000"], searches=["600 GLEN BRIDGE"]))
    assert PARCELS["964308731700000"]["situs"].startswith("620 GLENN BRIDGE RD")
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")
    assert r.evidence["address_relation"] == "conflict" and r.evidence["address_matches"] == 0
    assert any("Query=600+GLEN+BRIDGE" in u for u in f.asked)


def test_79_lincolnshire_loop_a_wrong_parcel_with_a_value_ratio_of_1878():
    row = brow("964589970700000", "79 Lincolnshire Loop", source="liensnc", claimed=(),
               market_value=147661300.0, tax_value=4866700.0)
    r, _ = run(row, pages(["964589970700000"], searches=["79 LINCOLNSHIRE"]))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")
    assert r.evidence["value_ratio_board_to_county"] > 1000


@pytest.mark.parametrize("near", [
    [("975478328400000", "78 ISLAND IN THE SKY TRL, WEAVERVILLE NC 28787")],       # another number
    [("111111111100000", "600 GLEN BRIDGE CT, ARDEN NC 28704")],                    # another suffix
    [("111111111100000", "600 GLENN BRIDGE RD, ARDEN NC 28704"),                    # one letter off
     ("222222222200000", "6000 GLEN BRIDGE RD, ARDEN NC 28704")],                   # one digit on
])
def test_the_address_search_never_binds_from_a_fuzzy_street_match(near):
    """The follow path needs the house number AND the street name tokens to be equal
    (_tax_common.address_relation): a near miss is another property."""
    row = brow("964308731700000", "600 Glen Bridge Rd", source="liensnc", claimed=())
    pg = pages(["964308731700000"])
    pg[f"{tb.BASE}/Search/Results?QueryType=Address&Query=600+GLEN+BRIDGE"] = search_page(near)
    r, f = run(row, pg)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")
    assert r.evidence["address_matches"] == 0
    assert not any("/Parcel/Details/111111111100000" in u for u in f.asked)     # nothing followed


@pytest.mark.parametrize("row_addr,county_addr,rel", [
    ("5 All Souls Crescent", "5 ALL SOULS CRES, ASHEVILLE NC 28803", "match"),       # the county's spelling
    ("161 Azalea Rd", "161 AZALEA RD E, ASHEVILLE NC 28805", "match"),               # the filing left the direction off
    ("161 Azalea Rd W", "161 AZALEA RD E", "conflict"),                              # two directions are two streets
    ("100 Main St Ext", "100 MAIN ST", "conflict"),                                  # an extension is not the street
    ("2614 OLD FORT RD", "2610 OLD FORT RD", "conflict"),                            # another number
    ("600 Glen Bridge rd.", "620 GLENN BRIDGE RD, ARDEN NC 28704", "conflict"),
    ("2614 Old Fort Rd", "OLD FORT RD", "unknown"),                                  # no number: no claim
])
def test_address_relation_rules_behind_the_binding(row_addr, county_addr, rel):
    assert tc.address_relation(row_addr, county_addr) == rel
    assert tc.address_query("5 All Souls Crescent") == "5 ALL SOULS"


@pytest.mark.parametrize("addr,parcel,pins,search", [
    ("5 All Souls Crescent", "9647792712", ["964779271200000"], "5 ALL SOULS"),
    ("161 Azalea Rd", "9668746687", ["966874668700000"], "161 AZALEA"),
])
def test_a_suffix_spelling_or_a_missing_direction_is_not_an_address_conflict(addr, parcel, pins, search):
    """v4 read "5 ALL SOULS CRES" against "5 All Souls Crescent" and "161 AZALEA RD E" against
    "161 Azalea Rd" as conflicts, searched the county for an address it spells otherwise, found
    nothing and answered address_not_found for parcels that carry the row's address."""
    row = brow(parcel, addr, source="liensnc", claimed=())
    row["raw"]["liensnc"] = {"entry_number": "1", "pin": ""}
    r, f = run(row, pages(pins))
    assert r.verdict == "refuted" and r.evidence["address_relation"] == "match"
    assert r.evidence["address_binding"] == "page_address"
    assert not any("/Search/" in u for u in f.asked)


def test_a_lien_filing_names_no_parcel_so_the_address_parcel_decides_10_rocky_point_circle():
    """A liensnc row's parcel id was attached by something else (the filing's own PIN is empty):
    the row's PIN (57 Cliffview Dr) is a guess, the parcel that carries 10 Rocky Point Cir decides."""
    row = brow("9677032513", "10 Rocky Point Circle", source="liensnc", claimed=(), owner=OTHER)
    row["raw"]["liensnc"] = {"entry_number": "1", "pin": ""}
    assert tc.parcel_resolved(row)
    r, _ = run(row, pages(["967703251300000", "967703238600000"], searches=["10 ROCKY"]))
    assert r.verdict == "refuted" and r.evidence["followed_because"] == "parcel_resolved"
    assert r.evidence["pin"] == "967703238600000" and r.evidence["followed_from_pin"] == "967703251300000"
    row["raw"]["liensnc"]["pin"] = "9677032513"            # the filer typed the PIN: it is the source's
    assert not tc.parcel_resolved(row)
    amb, _ = run(row, pages(["967703251300000", "967703238600000"], searches=["10 ROCKY"]))
    assert (amb.verdict, amb.evidence["reason"]) == ("unconfirmed", "ambiguous_account")


# ===========================================================================
# 2. following the address to a neighbor
# ===========================================================================

OLD_FORT = ["064644125600000", "064644107900000"]
RABBIT = ["969602780300000", "969602665700000"]


def _board_values(mv, tv):
    return {"market_value": mv, "tax_value": tv}


def test_2614_old_fort_rd_is_judged_on_its_own_pin_not_the_neighbors_parcel():
    """The row's PIN 0646-44-1256 is 2610 Old Fort Rd (county situs); the unpaid-bills layer row
    carries the owner's address 2614. The address search finds ANOTHER parcel that carries 2614
    exactly, whose bills were all paid on time: v4 followed it and said refuted. The row's own
    PIN paid its claimed 2025 bill on 2026-09-29 and every levy 2019-2025 late: stale. The row's
    board value (21,200) is its own PIN's county value, not the 2614 parcel's (100,800)."""
    row = brow("0646441256", "2614 OLD FORT RD", **_board_values(25900.0, 21200.0))
    r, f = run(row, pages(OLD_FORT, searches=["2614 OLD FORT"]))
    ev = r.evidence
    assert r.verdict == "stale", ev
    assert ev["pin"] == "064644125600000" and "followed_from_pin" not in ev
    assert ev["address_relation"] == "conflict"
    assert ev["address_binding"] == "own_parcel_value_identity"
    assert ev["address_account_pin"] == "064644107900000"
    assert ev["current_claim_basis"] == "claimed_year_paid_late"
    assert ev["late_levy_years"] == [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    assert ev["late_payment_dates"]["2025"] == ["2026-09-29"]
    assert any("Parcel/Details/064644107900000" in u for u in f.asked)        # looked at, not decided on


def test_16_rabbit_hill_dr_is_judged_on_its_own_pin_not_the_neighbors_parcel():
    """PIN 9696-02-7803 is 18 Rabbit Hill Dr; the row says 16. The parcel that carries 16 paid
    its 2025 bill on time; the row's own PIN paid 2025 on 2026-09-23, eight days after the board
    first saw the row (2026-09-15): the claim WAS true."""
    row = brow("9696027803", "16 RABBIT HILL DR", claimed=(2026,), **_board_values(45700.0, 35400.0))
    r, _ = run(row, pages(RABBIT, searches=["16 RABBIT HILL"]))
    ev = r.evidence
    assert r.verdict == "stale", ev
    assert ev["pin"] == "969602780300000" and ev["address_binding"] == "own_parcel_value_identity"
    assert ev["late_levy_years"] == [2021, 2023, 2024, 2025]
    assert ev["late_payment_dates"]["2025"] == ["2026-09-23"]
    assert ev["current_claim_basis"] == "latest_year_paid_late"


@pytest.mark.parametrize("addr,parcel,pins,search,claimed,values", [
    ("2614 OLD FORT RD", "0646441256", OLD_FORT, "2614 OLD FORT", (2025,), (25900.0, 21200.0)),
    ("16 RABBIT HILL DR", "9696027803", RABBIT, "16 RABBIT HILL", (2026,), (45700.0, 35400.0)),
])
def test_without_proof_which_account_is_the_rows_the_answer_is_ambiguous_never_refuted(
        addr, parcel, pins, search, claimed, values):
    """The same rows with no board value to tell the PIN's record apart: the verifier cannot say
    whether the row is the PIN with a stray address or the address with a stray PIN."""
    row = brow(parcel, addr, claimed=claimed)                # no value on the row
    r, _ = run(row, pages(pins, searches=[search]))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    assert r.evidence["address_pins"] and r.evidence["address_relation"] == "conflict"


def test_the_address_parcel_decides_when_a_resolver_attached_the_rows_parcel():
    row = brow("0646441256", "2614 OLD FORT RD")
    row["raw"]["parcel_from_address"] = {"source": "parcel_cache_situs_address"}
    r, _ = run(row, pages(OLD_FORT, searches=["2614 OLD FORT"]))
    ev = r.evidence
    assert r.verdict == "refuted", ev
    assert ev["pin"] == "064644107900000" and ev["followed_from_pin"] == "064644125600000"
    assert ev["address_binding"] == "followed" and ev["followed_because"] == "parcel_resolved"


def test_the_address_parcel_decides_when_the_board_owner_is_its_owner_and_not_the_pins():
    row = brow("0646441256", "2614 OLD FORT RD", owner=SAME)
    r, _ = run(row, pages(OLD_FORT, owners={"064644125600000": OTHER, "064644107900000": SAME},
                          searches=["2614 OLD FORT"]))
    assert r.verdict == "refuted" and r.evidence["followed_because"] == "owner_follows_address"
    both_same, _ = run(row, pages(OLD_FORT, owners={"064644125600000": SAME, "064644107900000": SAME},
                                  searches=["2614 OLD FORT"]))
    assert both_same.evidence["reason"] == "ambiguous_account"      # one owner for both: no proof


def test_a_retired_pin_is_followed_to_the_parcel_that_carries_the_address():
    """7 Island in the Sky Trl: the PIN is inactive (the county retired it), and the search also
    lists 78 Island in the Sky Trl, which is not the address."""
    row = brow("9754697396", "7 ISLAND IN THE SKY TRL", owner=OTHER, claimed=(), source="liensnc",
               raw={"two_year_delinquent": {"is_two_year_plus": True, "tax_year": 2025}})
    r, _ = run(row, pages(["975469739600000", "975469477200000"], searches=["7 ISLAND IN THE SKY"]))
    ev = r.evidence
    assert r.verdict == "refuted" and ev["followed_because"] == "portal_retired"
    assert ev["pin"] == "975469477200000" and ev["followed_from_pin"] == "975469739600000"


def test_a_pin_that_names_no_usable_address_contradicts_nothing():
    """A county placeholder situs ("99999 EAST ST") on the row's PIN: the one parcel that carries
    the row's address decides, as before (44 Skyland Cir, v4)."""
    shape = copy.deepcopy(PARCELS["064644125600000"])
    shape["situs"] = "99999 EAST ST"
    row = brow("0646441256", "2614 OLD FORT RD")
    pg = pages(["064644125600000", "064644107900000"], searches=["2614 OLD FORT"],
               shape_override={"064644125600000": shape})
    r, _ = run(row, pg)
    assert r.verdict == "refuted" and r.evidence["followed_because"] == "pin_names_no_usable_address"
    assert r.evidence["pin"] == "064644107900000"


# ===========================================================================
# 1. sibling rows on one ledger key
# ===========================================================================

def _lrow(parcel, addr, **kw):
    r = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien", "parcel_id": parcel,
         "street_address": addr, "source": "counties_generic.arcgis_distress.buncombe_unpaid_bills"}
    r.update(kw)
    return r


R16 = _lrow("9696-02-7803-00000", "16 RABBIT HILL DR")
R18 = _lrow("9696-02-7803-00000", "18 RABBIT HILL DR", source="counties.multi_year_delinquent_tax")
K16, K18 = "parcel:NC:buncombe:9696027803", "addr:NC:buncombe:18 rabbit hill dr"


def _res(verdict, version="v5", **ev):
    return core.result("tax_lien", verdict, ev, source="tax.buncombenc.gov", version=version,
                       verifier="tax_lien_buncombe", now=NOW)


def test_two_rows_of_one_parcel_with_different_addresses_get_their_own_entries():
    led = L.Ledger("tax_lien")
    e16 = led.record(R16, _res("refuted"), ttl_days=30, governs=tb.GOVERNS, now=NOW)
    assert led.find_row(R16)[1] is e16
    assert led.find_row(R18) == (None, None)             # v4: the sibling's entry, whole
    e18 = led.record(R18, _res("stale"), ttl_days=30, governs=tb.GOVERNS, now=NOW)
    assert e18 is not e16 and len(led.rows) == 2
    assert e16["latest"]["verdict"] == "refuted" and e16["row"]["street_address"] == "16 RABBIT HILL DR"
    assert e18["latest"]["verdict"] == "stale" and set(led.rows) == {K16, K18}
    # each row finds its own entry, however the keys are ordered
    assert led.find_row(R16)[0] == K16 and led.find_row(R18)[0] == K18
    # a re-check of either updates its own entry only
    led.record(R16, _res("stale"), ttl_days=30, governs=tb.GOVERNS, now=NOW + timedelta(days=1))
    assert led.rows[K16]["latest"]["verdict"] == "stale" and led.rows[K16]["checks"] == 2
    assert led.rows[K18]["checks"] == 1


def test_a_row_with_no_house_number_never_conflicts_and_one_numbered_row_is_unchanged():
    led = L.Ledger("tax_lien")
    led.record(R16, _res("refuted"), ttl_days=30, now=NOW)
    bare = _lrow("9696-02-7803-00000", "RABBIT HILL DR")
    assert led.find_row(bare)[0] == K16                     # no address to compare: the parcel's entry
    same = _lrow("9696-02-7803-00000", "16 Rabbit Hill Drive, Fairview NC")
    assert led.find_row(same)[0] == K16                     # one address spelled another way
    other_signal = L.Ledger("jail_booking")                 # only tax_lien is address-scoped
    other_signal.record(R16, core.result("jail_booking", "refuted", {}, version="v1", verifier="x", now=NOW),
                        ttl_days=30, now=NOW)
    assert other_signal.find_row(R18)[0] == K16


def test_a_row_with_no_address_on_a_parcel_two_entries_claim_keeps_one_entry_of_its_own():
    """Once two entries claim the parcel key, a row with no house number cannot pick one: its
    answer goes to ONE fallback entry (not one new entry per run, and never over either row's)."""
    led = L.Ledger("tax_lien")
    led.record(R16, _res("refuted"), ttl_days=30, now=NOW)
    led.record(R18, _res("stale"), ttl_days=30, now=NOW)
    bare = _lrow("9696-02-7803-00000", "RABBIT HILL DR")
    assert led.find_row(bare) == (None, None)
    e = led.record(bare, _res("confirmed"), ttl_days=30, now=NOW)
    assert len(led.rows) == 3 and e["latest"]["verdict"] == "confirmed"
    assert led.rows[K16]["latest"]["verdict"] == "refuted" and led.rows[K18]["latest"]["verdict"] == "stale"
    assert led.find_row(bare)[1] is e
    led.record(bare, _res("stale"), ttl_days=30, now=NOW + timedelta(days=1))
    assert len(led.rows) == 3 and e["checks"] == 2
    assert led.find_row(R16)[0] == K16 and led.find_row(R18)[0] == K18    # the numbered rows never see it


def test_merging_the_copy_on_disk_never_joins_two_addresses_of_one_key():
    """_save merges the file on disk back into the run's copy: an entry under the same key but
    verified for another address of the parcel is another row's entry, kept beside it."""
    mem, disk = L.Ledger("tax_lien"), L.Ledger("tax_lien")
    mem.record(R16, _res("refuted"), ttl_days=30, now=NOW)
    disk.record(R18, _res("stale"), ttl_days=30, now=NOW + timedelta(hours=1))      # keyed by the parcel too
    assert list(disk.rows) == [K16]
    mem.merge_from(disk)
    assert len(mem.rows) == 2
    assert mem.rows[K16]["latest"]["verdict"] == "refuted"
    other = next(e for k, e in mem.rows.items() if k != K16)
    assert other["latest"]["verdict"] == "stale" and other["row"]["street_address"] == "18 RABBIT HILL DR"
    assert mem.find_row(R16)[1]["latest"]["verdict"] == "refuted"
    assert mem.find_row(R18)[1]["latest"]["verdict"] == "stale"
    mem.merge_from(disk)                                   # merging again changes nothing
    assert len(mem.rows) == 2


def test_a_shared_lien_case_key_never_joins_two_parcels_pole_creasman_586_and_756():
    """Two parcels, one lien-agent filing (case key) and one copied county roll block. Different
    parcels are different entries (find's parcel guard); two rows with NO parcel and different
    addresses on one filing were the leak: the case key matched the sibling's entry."""
    r586 = _lrow("9626-31-8147-00000", "586 POLE CREASMAN RD", case_number="2627893")
    r756 = _lrow("9625385860", "756 Pole Creasman Rd.", case_number="2627893")
    led = L.Ledger("tax_lien")
    led.record(r756, _res("refuted"), ttl_days=30, now=NOW)
    assert led.find_row(r586) == (None, None)
    e586 = led.record(r586, _res("confirmed"), ttl_days=30, now=NOW)
    assert e586["latest"]["verdict"] == "confirmed"
    assert led.rows["parcel:NC:buncombe:9625385860"]["latest"]["verdict"] == "refuted"
    # the same filing on two rows that carry no parcel
    n1 = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien", "street_address": "660 Glen Bridge Rd",
          "case_number": "2640610"}
    n2 = dict(n1, street_address="662 Glen Bridge Rd")
    led2 = L.Ledger("tax_lien")
    led2.record(n1, _res("refuted"), ttl_days=30, now=NOW)
    assert led2.find_row(n2) == (None, None)
    led2.record(n2, _res("confirmed"), ttl_days=30, now=NOW)
    assert sorted(e["latest"]["verdict"] for e in led2.rows.values()) == ["confirmed", "refuted"]


def test_the_verdict_for_756_is_about_756s_own_parcel_and_586_is_confirmed_on_its_own():
    """Row 756 (parcel 9625385860, county situs 756 Pole Creasman Rd) carries the county roll block
    of parcel 962631814700000 (586): its own parcel is clean, and the verdict says so, with
    claim_pin_differs. Row 586's own PIN still owes its 2017, 2019 and 2022 bills."""
    claim = {"multi_year_delinquent_tax": {"parcel_key": "962631814700000", "years": [2017, 2019, 2022, 2026]}}
    r756 = brow("9625385860", "756 Pole Creasman Rd.", source="counties_generic.liensnc", claimed=(2026,),
                owner=OTHER, raw=claim)
    r586 = brow("9626318147", "586 POLE CREASMAN RD", source="counties.multi_year_delinquent_tax",
                claimed=(2026,), raw=copy.deepcopy(claim))
    pg = pages(["962538586000000", "962631814700000"])
    v756, _ = run(r756, pg)
    assert v756.verdict == "refuted" and v756.evidence["pin"] == "962538586000000"
    assert v756.evidence["claim_pin_differs"] and v756.evidence["claim_pins"] == ["962631814700000"]
    assert v756.evidence["address_relation"] == "match"
    v586, _ = run(r586, pg)
    assert v586.verdict == "confirmed" and v586.evidence["pin"] == "962631814700000"
    assert v586.evidence["delinquent_by_year"] == {"2022": 72.8, "2019": 29.02, "2017": 193.96}
    assert "claim_pin_differs" not in v586.evidence


def _listing(row, **kw):
    r = dict(row)
    raw = r.pop("raw", {})
    return Listing(source=r.pop("source"), source_url="https://x/y", listing_type=ListingType.TAX_LIEN,
                   state="NC", county="Buncombe", parcel_id=r.get("parcel_id"),
                   street_address=r.get("street_address"), raw=dict(raw), **kw)


def _entry_for(row, res, governs=tb.GOVERNS):
    led = L.Ledger("tax_lien")
    led.record(row, res, ttl_days=30, governs=governs, now=NOW)
    return led


def test_apply_attaches_an_entry_to_the_row_it_was_verified_for_only(tmp_path):
    """v4 attached the 16 Rabbit Hill Dr verdict to the 18 Rabbit Hill Dr row too (one parcel key)
    and the 79 Lincolnshire Loop verdict to the 1617 Hendersonville Rd row (one hotel parcel)."""
    led = _entry_for(R16, _res("refuted"))
    led.save(tmp_path / "tax_lien.json", now=NOW)
    a, b = _listing(R16), _listing(R18)
    A.apply_verification([a, b], tmp_path, now=NOW)
    assert [r["verdict"] for r in a.raw["verification"]] == ["refuted"]
    assert "verification" not in b.raw
    # a UST row on the parcel a wrong resolver also gave a liensnc row
    lin = _lrow("964589970700000", "79 Lincolnshire Loop", source="liensnc")
    ust = _lrow("964589970700000", "1617 HENDERSONVILLE RD", source="counties_generic.state_contamination.nc_ust_incidents")
    _entry_for(lin, _res("refuted")).save(tmp_path / "tax_lien.json", now=NOW)
    la, ub = _listing(lin), _listing(ust)
    A.apply_verification([la, ub], tmp_path, now=NOW)
    assert "verification" in la.raw and "verification" not in ub.raw


def _sweep():
    spec = importlib.util.spec_from_file_location("verification_sweep", REPO / "scripts" / "verification_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _board(tmp_path, rows):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(rows).encode()))
    return docs / "listings.json.gz"


def _registry_verifier():
    return next(v for v in discover() if v.name == "tax_lien_buncombe")


def test_the_sweep_queues_both_rows_of_a_parcel_that_carry_different_addresses(tmp_path):
    sw = _sweep()
    rows = [dict(R16, raw={}, owner_name=None, first_seen="2026-09-15"),
            dict(R18, raw={"two_year_delinquent": {"is_two_year_plus": True, "tax_year": 2025}}, first_seen="2026-09-15")]
    path = _board(tmp_path, rows)
    v = _registry_verifier()
    plan, why = sw.select(path, [v], {"tax_lien": L.Ledger("tax_lien")}, county="Buncombe", cap=10, now=NOW)
    assert sorted(r["street_address"] for _p, _k, r, _v in plan["tax_lien"]) == [
        "16 RABBIT HILL DR", "18 RABBIT HILL DR"]                       # v4: one of them
    # the same row twice (one address) and a row with no number still ride on one check
    rows2 = [rows[0], dict(rows[0]), dict(rows[0], street_address="RABBIT HILL DR")]
    plan2, why2 = sw.select(_board(tmp_path, rows2), [v], {"tax_lien": L.Ledger("tax_lien")},
                            county="Buncombe", cap=10, now=NOW)
    assert len(plan2["tax_lien"]) == 1 and why2["tax_lien"]["same_property_queued"] == 2


def test_the_sweeps_answer_for_each_address_lands_on_its_own_entry(tmp_path):
    sw = _sweep()
    v = _registry_verifier()
    led = L.Ledger("tax_lien", path=tmp_path / "tax_lien.json")
    pg = pages(RABBIT + ["962538586000000"], searches=["16 RABBIT HILL"])
    f = ReplayFetcher(pg)
    rows = [brow("9696027803", "16 RABBIT HILL DR", claimed=(2026,), **_board_values(45700.0, 35400.0)),
            brow("9696027803", "18 RABBIT HILL DR", claimed=(2026,), **_board_values(45700.0, 35400.0))]
    plan = {"tax_lien": [((0.0, 0, 0.0, i), v.ledger_keys(r)[0], r, v) for i, r in enumerate(rows)]}
    asyncio.run(sw.run_checks(plan, {"tax_lien": led}, f, budget_s=60, save_every=1, row_timeout_s=30, host="t"))
    assert len(led.rows) == 2
    by_addr = {e["row"]["street_address"]: e for e in led.rows.values()}
    assert set(by_addr) == {"16 RABBIT HILL DR", "18 RABBIT HILL DR"}
    assert {e["latest"]["verdict"] for e in by_addr.values()} == {"stale"}
    assert by_addr["16 RABBIT HILL DR"]["latest"]["evidence"]["address_binding"] == "own_parcel_value_identity"
    assert by_addr["18 RABBIT HILL DR"]["latest"]["evidence"]["address_binding"] == "page_address"
    # the per-record governs the sweep stored: the chronic claim is confirmed (4 late levy years)
    assert "tax_lien_chronic" not in by_addr["18 RABBIT HILL DR"]["governs"]


# ===========================================================================
# 3. chronic late payers: two claims, judged apart
# ===========================================================================

#: the five-plus-late-levy-year shapes of the 2026-10-06 live re-check: (board address, board parcel,
#: pins the verifier reads, searches, claimed years, expected late levy years, followed pin)
FIVE_PLUS = [
    ("120 LAKEY GAP ACRES", "061883221800000", ["061883221800000"], [], (2025,), [2020, 2021, 2022, 2023, 2024]),
    ("5 VALLEYWOOD CT", "965532706500000", ["965532706500000"], [], (2025,), [2019, 2020, 2021, 2022, 2023]),
    ("ENTHOFFER ST", "071040271700000", ["071040271700000"], [], (2025,), [2019, 2020, 2021, 2022, 2023, 2024]),
    ("55 E PONDERS WAY", "973466507800000", ["973466507800000"], [], (2025,), [2019, 2020, 2021, 2022, 2023, 2024]),
    ("17 SERENITY CREEK DR", "869929999900000", ["869929999900000"], [], (2025,), [2019, 2020, 2021, 2022, 2023, 2024]),
    ("78 OLD LEICESTER HWY", "972081974800000", ["972081974800000"], [], (2025,), [2020, 2021, 2022, 2023, 2024]),
    ("550 OLD NEWFOUND RD", "879093638500000", ["879093638500000"], [], (2025,), [2020, 2021, 2022, 2023, 2024]),
    ("18 SUNRIDGE RD", "962993177600000", ["962993177600000"], [], (2025,), [2020, 2021, 2022, 2023, 2024]),
    ("68 PINEY VIEW EST", "879351393600000", ["879351393600000", "879351560300000"], ["68 PINEY VIEW EST"],
     (2025,), [2019, 2020, 2021, 2022, 2023, 2024]),                # inactive PIN, followed
    ("7 ISLAND IN THE SKY TRL", "975469739600000", ["975469739600000", "975469477200000"],
     ["7 ISLAND IN THE SKY"], (), [2019, 2020, 2021, 2022, 2023]),  # inactive PIN, followed
]


def _five_plus_row(addr, pin, claimed):
    row = brow(pin[:10], addr, claimed=claimed, source="liensnc")
    if not claimed:
        row["raw"]["two_year_delinquent"] = {"is_two_year_plus": True, "tax_year": 2025}
    return row


@pytest.mark.parametrize("addr,pin,pins,searches,claimed,late", FIVE_PLUS)
def test_a_chronic_late_payer_is_refuted_for_the_current_claim_and_keeps_tax_lien_chronic(
        addr, pin, pins, searches, claimed, late):
    """Paid up today, claimed year paid on time, five or six late levy years behind it. v4 read the
    latest bill only: refuted, and the verdict's governs took tax_lien_chronic away too."""
    r, _ = run(_five_plus_row(addr, pin, claimed), pages(pins, searches=searches))
    ev = r.evidence
    assert r.verdict == "refuted", ev
    assert ev["late_levy_years"] == late and len(late) >= 5
    assert ev["chronic_claim"] == "confirmed" and ev["history_complete"] is True
    assert ev["current_claim_basis"] in ("claimed_years_on_time", "latest_year_on_time")
    for y in late:                                    # the late payment date of every late year
        dates = ev["late_payment_dates"][str(y)]
        assert dates and all(d >= f"{y + 1}-01-06" for d in dates)
    gov = tb.governs_for(r.to_dict())
    assert "tax_lien_chronic" not in gov
    assert set(gov) == set(tb.GOVERNS) - {"tax_lien_chronic"}


def test_the_current_claim_alone_when_the_history_has_fewer_than_three_late_years():
    r, _ = run(brow("9625385860", "756 Pole Creasman Rd.", claimed=(2026,), owner=OTHER),
               pages(["962538586000000"]))
    assert r.verdict == "refuted" and r.evidence["late_levy_years"] == []
    assert r.evidence["chronic_claim"] == "not_confirmed"
    assert tb.governs_for(r.to_dict()) == tb.GOVERNS        # a refuted claim takes the chronic one too


def test_two_late_years_are_not_chronic_and_three_are():
    assert tc.CHRONIC_MIN_LATE_YEARS == 3                   # the scorer's pickens `len(cycles) >= 3`
    assert tc.history_claims([2022, 2023], True) == "not_confirmed"
    assert tc.history_claims([2021, 2022, 2023], True) == "confirmed"
    assert tc.history_claims([2022, 2023], False) == "unknown"
    base = {"evidence": {}}
    assert tc.governs_for(base) == tc.GOVERNS and tc.governs_for({}) == tc.GOVERNS
    assert "tax_lien_chronic" not in tc.governs_for({"evidence": {"chronic_claim": "unknown"}})


def test_a_claimed_year_that_was_itself_paid_late_is_stale_not_refuted():
    r, _ = run(brow("0646441256", "2610 Old Fort Rd", claimed=(2025,)), pages(["064644125600000"]))
    assert r.verdict == "stale" and r.evidence["current_claim_basis"] == "claimed_year_paid_late"
    assert r.evidence["address_binding"] == "page_address"
    assert r.evidence["bills_checked"][0]["paid_on"] == "2026-09-29"


def _shape_with(bills_tx, situs="1 EXAMPLE RD", value=90050):
    """A parcel shape: bills_tx = {levy year: [(type, 'm/d/Y', tax, late, interest, cost), ...]}."""
    bills = []
    for y in sorted(bills_tx, reverse=True):
        due = 0.0
        bills.append({"bill": f"0000000001-{y}-{y}-0000-00", "amount_due": due, "see_legal": False,
                      "value": value, "tx": bills_tx[y]})
    return {"situs": situs, "value": value, "inactive": False, "bills": bills}


def _on_time(y, amount=500.0):
    return [("BILL", f"7/26/{y}", amount, 0, 0, 0), ("PAYMENT", f"11/19/{y}", -amount, 0, 0, 0)]


def _late(y, when, amount=500.0, interest=20.0):
    d = date.fromisoformat(when)
    return [("BILL", f"7/26/{y}", amount, 0, 0, 0), ("BILL", f"1/6/{y + 1}", 0, 0, interest, 0),
            ("PAYMENT", f"{d.month}/{d.day}/{d.year}", -(amount + interest), 0, -interest, 0)]


def test_a_bill_that_was_already_delinquent_when_the_board_saw_the_row_and_paid_since_is_stale():
    """The board first saw the row 2026-09-15 and no year is claimed: the 2023 bill was delinquent
    that day (since January 2024) and was paid on 2026-09-20, after it. refuted when that payment
    came before the board saw the row, or when the bill was not delinquent yet that day."""
    shape = _shape_with({2025: _on_time(2025), 2024: _on_time(2024), 2023: _late(2023, "2026-09-20"),
                         2022: _on_time(2022)})
    pg = {f"{tb.BASE}/Parcel/Details/000000000000000": parcel_page("000000000000000", SAME, shape)}
    for b in shape["bills"]:
        pg[f"{tb.BASE}/Bill/Details/{b['bill']}"] = bill_page(b["tx"])
    row = brow("0000000000", "1 EXAMPLE RD", claimed=())
    r, _ = run(row, pg)
    assert r.verdict == "stale" and r.evidence["current_claim_basis"] == "paid_late_after_first_seen"
    assert r.evidence["late_levy_years"] == [2023]
    assert r.evidence["late_payment_dates"] == {"2023": ["2026-09-20"]}
    after, _ = run(dict(row, first_seen="2026-09-21T00:00:00"), pg)
    assert after.verdict == "refuted" and after.evidence["current_claim_basis"] == "latest_year_on_time"
    early, _ = run(dict(row, first_seen="2023-11-01T00:00:00"), pg)
    assert early.verdict == "refuted"          # not delinquent yet that day: nothing was open


def test_the_governs_a_sweep_stores_and_apply_attaches_follow_the_record(tmp_path):
    """A chronic claim confirmed by the history: the stored `governs` and the record the apply step
    attaches leave tax_lien_chronic out, so the scorer keeps it (and still ends the current claim)."""
    sw = _sweep()
    v = _registry_verifier()
    row = _five_plus_row("55 E PONDERS WAY", "973466507800000", (2025,))
    led = L.Ledger("tax_lien", path=tmp_path / "tax_lien.json")
    plan = {"tax_lien": [((0.0, 0, 0.0, 0), v.ledger_keys(row)[0], row, v)]}
    asyncio.run(sw.run_checks(plan, {"tax_lien": led}, ReplayFetcher(pages(["973466507800000"])),
                              budget_s=60, save_every=1, row_timeout_s=30, host="t"))
    entry = next(iter(led.rows.values()))
    assert entry["latest"]["verdict"] == "refuted"
    assert "tax_lien_chronic" not in entry["governs"] and "recorded_debt:tax" in entry["governs"]
    li = _listing(row)
    li.raw["pickens_delinquent"] = {"chronic": True, "cycle_count": 3, "county": "Pickens"}
    li.raw["tax_owed"] = {"balance": 171.74, "kind": "delinquent_tax", "year": 2025}
    names = lambda x: {n for n, _c, _w in ds._signals_for(x, today=TODAY)}      # noqa: E731
    assert "tax_lien_chronic" in names(li)
    A.apply_verification([li], tmp_path, now=NOW)
    assert li.raw["verification"][0]["verdict"] == "refuted"
    assert "tax_lien_chronic" not in li.raw["verification"][0]["governs"]
    assert "tax_lien_chronic" in names(li) and "recorded_debt" not in names(li)
    # an entry whose history was read in full and is not chronic still ends it
    row2 = brow("9625385860", "756 Pole Creasman Rd.", claimed=(2026,), owner=OTHER)
    led2 = L.Ledger("tax_lien", path=tmp_path / "tax_lien.json")
    plan2 = {"tax_lien": [((0.0, 0, 0.0, 0), v.ledger_keys(row2)[0], row2, v)]}
    asyncio.run(sw.run_checks(plan2, {"tax_lien": led2}, ReplayFetcher(pages(["962538586000000"])),
                              budget_s=60, save_every=1, row_timeout_s=30, host="t"))
    li2 = _listing(row2)
    li2.raw["pickens_delinquent"] = {"chronic": True, "cycle_count": 3, "county": "Pickens"}
    A.apply_verification([li2], tmp_path, now=NOW)
    assert "tax_lien_chronic" not in names(li2)


# ===========================================================================
# the recheck tool re-judges entries whose row no verifier covers any more
# ===========================================================================

def test_the_recheck_tool_can_rejudge_an_entry_whose_row_is_no_longer_covered(tmp_path):
    spec = importlib.util.spec_from_file_location("verification_recheck", REPO / "scripts" / "verification_recheck.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    lien = _lrow("9643087317", "600 Glen Bridge rd.", source="liensnc")      # a lien-agent filing only
    path = _board(tmp_path, [lien])
    v = _registry_verifier()
    assert not v.applies(lien)                                               # no longer covered since v3
    led = L.Ledger("tax_lien")
    led.record(lien, _res("refuted", version="v3"), ttl_days=30, now=NOW)
    wanted = {"tax_lien": set(led.rows)}
    plain = rc.find_rows(path, [v], {"tax_lien": led}, wanted)
    assert plain["tax_lien"] == {}
    found = rc.find_rows(path, [v], {"tax_lien": led}, wanted, include_uncovered=True)
    (rank, row, vv), = found["tax_lien"].values()
    assert vv is v and row["street_address"] == "600 Glen Bridge rd."


# ===========================================================================
# 4. Union SC (qPayBill) and PTS Cloud: the address account and the row's own account disagree
# ===========================================================================

from tests.test_verification_tax_lien_recheck_defects import (  # noqa: E402
    PTS, UNION_2383, prow, prun, qrow, qrun, qserved)
from foreclosure_scraper.verification.verifiers import tax_lien_ptscloud as tp  # noqa: E402
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as tq  # noqa: E402

UNION_844 = ["uniontreasurer|Map|072-00-00-052 000", "uniontreasurer|Address|844 RICE"]


@pytest.mark.parametrize("pages_,row", [
    (UNION_2383, lambda: qrow("Union", "036-00-00-066 000", "027-00-00-008 000", addr="2383 Jonesville Hwy",
                              owner_name="OUTSIDER PERSON")),
    (UNION_844, lambda: qrow("Union", "072-00-00-052 000", "072-00-00-052 000", addr="844 RICE AVE EXT",
                             owner_name="OUTSIDER PERSON")),
])
def test_the_two_union_rows_are_ambiguous_with_an_owner_that_matches_neither_account(pages_, row):
    r = qrun(row(), qserved(*pages_))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    assert r.evidence["owner_match"] == "different" and r.evidence["address_owner_match"] == "different"
    assert not {"bills_checked", "late_levy_years"} & set(r.evidence)       # nothing was judged


def test_the_address_account_decides_when_the_board_owner_is_its_owner_and_not_the_claims():
    """Proof: the board owner is the address account's owner (TESTOWNER...) and not the claim
    account's (made different here), so the claim account is the wrong one: the address account
    decides as it did in v2 (844 Rice Avenue Ext paid on time: refuted)."""
    row = qrow("Union", "072-00-00-052 000", "072-00-00-052 000", addr="844 RICE AVE EXT",
               owner_name="TESTOWNER01 PAT")
    both_same = qrun(row, qserved(*UNION_844))
    assert both_same.evidence["reason"] == "ambiguous_account"     # the board owner is both accounts' owner
    f2 = qserved(*UNION_844)                                       # the claim account's grid: other owners
    for k, v in list(f2.responses.items()):
        if "RICE AVE EXT" in str(v) and "844 RICE" not in str(v):
            f2.responses[k] = re.sub(r"TESTOWNER\d\d PAT", "ELSEWHERE ZED", str(v))
    r = qrun(row, f2)
    assert r.verdict == "refuted" and r.evidence["decided_on"] == "address_search"
    assert r.evidence["followed_because"] == "owner_follows_address"


def test_the_address_account_decides_when_a_resolver_attached_the_boards_parcel():
    row = qrow("Union", "072-00-00-052 000", "072-00-00-052 000", addr="844 RICE AVE EXT")
    del row["raw"]["qpaybill_roll"]                              # no claim account: the board's parcel
    row["raw"]["parcel_from_address"] = {"source": "parcel_cache_situs_address"}
    r = qrun(row, qserved(*UNION_844))
    assert r.verdict == "refuted" and r.evidence["followed_because"] == "parcel_resolved"


def _pts_parcel(parcel, addr, owner):
    payload = json.loads(PTS[tp.SEARCH_URL.format(q="106171", tenant="Henderson")])
    res = []
    for b in payload["results"]:
        b = dict(b, parcelId=parcel, propertyAddress=f"{addr} HENDERSONVILLE NC 28792", propertyAddress1=addr,
                 ownerName1=owner)
        res.append(b)
    return tp.SEARCH_URL.format(q=parcel, tenant="Henderson"), json.dumps(dict(payload, results=res))


def test_pts_the_rows_own_parcel_on_the_same_street_is_ambiguous_without_proof():
    """The roll's parcel is 809 Robinson Ter (the same street, another number); the address search
    names the parcel that carries 807 Robinson Ter. Nothing proves the roll's parcel is wrong."""
    url, body = _pts_parcel("555555", "809 ROBINSON TER", "OTHERFOLK, SAM")
    row = prow("555555", "807 ROBINSON TERRACE", owner_name="NOBODY, RANDOM")
    r, f = prun(row, {url: body})
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    assert r.evidence["address_relation"] == "conflict" and r.evidence["address_pins"] == ["106171"]
    assert r.evidence["address_owner_match"] == "different" and r.evidence["owner_match"] == "different"
    assert "bills_checked" not in r.evidence


def test_pts_the_address_parcel_decides_with_the_owner_as_proof():
    url, body = _pts_parcel("555555", "809 ROBINSON TER", "OTHERFOLK, SAM")
    row = prow("555555", "807 ROBINSON TERRACE", owner_name="TESTOWNER, PAT")
    r, _ = prun(row, {url: body})
    assert r.verdict == "stale" and r.evidence["followed_from_parcel"] == "555555"
    assert r.evidence["tax_parcel"] == "106171" and r.evidence["followed_because"] == "owner_follows_address"
    same_url, same_body = _pts_parcel("555555", "809 ROBINSON TER", "TESTOWNER, PAT")
    r2, _ = prun(row, {same_url: same_body})
    assert r2.evidence["reason"] == "ambiguous_account"            # the same owner for both


def test_pts_no_parcel_carries_the_address_is_address_not_found():
    url, body = _pts_parcel("555555", "809 ROBINSON TER", "OTHERFOLK, SAM")
    r, _ = prun(prow("555555", "810 ROBINSON TERRACE"), {url: body})
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")


def test_pts_a_failed_history_read_never_takes_the_tenant_out_of_the_run():
    """The bill history reads old bills the county may have purged: a failed read there must not
    count against the tenant's health (two failures end the county's rows for the run)."""
    run_ = tp._run
    f = ReplayFetcher({})
    for i in range(4):
        with pytest.raises(LookupError):
            asyncio.run(tp._get_json(f, f"https://bcpwa.ncptscloud.com/api/GetbillDetails?BillId={i}", "Henderson",
                                     health=False))
    assert not run_(f)["dead"]
    for i in range(2):
        with pytest.raises(LookupError):
            asyncio.run(tp._get_json(f, f"https://bcpwa.ncptscloud.com/api/x?{i}", "Henderson"))
    assert "Henderson" in run_(f)["dead"]


# ===========================================================================
# the qPayBill payment history, per year, from the grid
# ===========================================================================

def test_qpaybill_records_the_late_years_and_their_dates_and_keeps_the_chronic_claim_unknown_when_partial():
    f = qserved("uniontreasurer|Map|046-00-00-029 000")
    r = qrun(qrow("Union", "046-00-00-029 000", "046-00-00-029 000", addr="2383 JONESVILLE HWY"), f)
    ev = r.evidence
    assert r.verdict == "refuted" and ev["late_levy_years"] == [] and ev["chronic_claim"] == "not_confirmed"
    assert ev["history_complete"] is True and ev["current_claim_basis"] == "claimed_years_on_time"
    late = qrun(qrow("Union", "036-00-00-066 000", "036-00-00-066 000", addr="329 JONESVILLE LOCKHART HWY"),
                qserved("uniontreasurer|Map|036-00-00-066 000"))
    assert late.verdict == "stale" and late.evidence["late_levy_years"] == [2024, 2025]
    assert late.evidence["late_payment_dates"] == {"2024": ["2025-07-15"], "2025": ["2026-09-29"]}
    assert late.evidence["current_claim_basis"] == "claimed_year_paid_late"
    assert late.evidence["chronic_claim"] == "not_confirmed"       # two late levy years: not chronic
    assert tq.governs_for(late.to_dict()) == tq.GOVERNS
