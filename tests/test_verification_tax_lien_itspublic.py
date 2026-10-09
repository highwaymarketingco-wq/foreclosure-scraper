"""tax_lien_itspublic v1: the BT / ITS "ITSPublic" tax-bill portals (Onslow, Graham).

Everything here is synthetic: made-up owners (TESTOWNER ...), made-up parcels and streets (TEST ...),
the shape of the real portal answers (live-read 2026-10-08). The portal keeps the search in the
session (the table POST carries no search terms), so a small in-memory portal stands in for it.
No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_itspublic as p

TODAY = date(2026, 10, 8)
ONSLOW = p.PORTALS["Onslow"].base
GRAHAM = p.PORTALS["Graham"].base


def bill(year, number, ids, situs, *, owner="TESTOWNER ALPHA", account="900000001", balance=0.0,
         original=1000.0, paid_on=None, acres="0.500 AC", foreclosure=False):
    return {"year": year, "bill": str(number), "ids": list(ids), "situs": situs, "owner": owner,
            "account": account, "balance": balance, "original": original, "paid_on": paid_on,
            "acres": acres, "foreclosure": foreclosure}


class FakePortal:
    """An ITSPublic portal in memory: the search model is kept per session, like the real one."""

    def __init__(self, base, bills, *, fail_tables=0):
        self.base, self.bills = base, bills
        self.model = None
        self.asked = []
        self.fail_tables = fail_tables

    # the client side the verifier uses -------------------------------------------------
    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, **_):
        self.asked.append(("GET", url))
        return FormResponse(200, url, "<html>Tax Bill Search</html>")

    async def post_form(self, url, data, **_):
        self.asked.append(("POST", url, dict(data)))
        if url.endswith("/GetSearchTablePartial/"):
            self.model = dict(data)
            return FormResponse(200, url, '<script>PopulateTable("PayTaxBills", \'\');</script>')
        if url.endswith("/GetSearchTableData"):
            if self.fail_tables:
                self.fail_tables -= 1
                return FormResponse(500, url, "<html>Server Error</html>")
            rows = [self._row(b) for b in self._match()]
            return FormResponse(200, url, json.dumps({"total": 1, "numRecords": len(rows), "rows": rows}))
        if url.endswith("/ViewTaxBill"):
            b = next(b for b in self.bills if str(b["year"]) == data["taxYear"] and b["bill"] == data["billNumber"]
                     and self._match_one(b))
            return FormResponse(200, url, self._view(b))
        return FormResponse(404, url, "")

    # the server side -------------------------------------------------------------------
    def _match_one(self, b):
        return b in self._match() if self.model else True

    def _match(self):
        m = self.model or {}
        # the parcel id is the description's first id, the alternate (map) number its second
        for f, i in (("ParcelNumber", 0), ("AlternateParcelIdentifier", 1)):
            if m.get(f):
                return [b for b in self.bills if len(b["ids"]) > i and tc.alnum(b["ids"][i]) == tc.alnum(m[f])]
        if m.get("AccountNumber"):
            return [b for b in self.bills if b["account"] == m["AccountNumber"]]
        if m.get("FormattedPropertyAddress"):
            return [b for b in self.bills if b["situs"].upper().startswith(m["FormattedPropertyAddress"].upper())]
        return []

    @staticmethod
    def _row(b):
        desc = "<br/>".join([*b["ids"], b["situs"], b["acres"]])
        action = ("<div>This property is currently in Tax Foreclosure. Contact the tax office</div>"
                  if b["foreclosure"] else "<button title='Add to Cart'>Pay</button>")
        return {"id": f"{b['year']}/{b['bill']}",
                "cell": [str(b["year"]), b["bill"], b["account"], b["owner"], desc,
                         f"{b['original']:,.2f}", f"{b['balance']:,.2f}", action]}

    @staticmethod
    def _view(b):
        def li(k, v):
            return (f'<li><div class="indiv info-row-label">{k} :</div> '
                    f'<div class="indiv info-row-text" style=\'text-align: right\'>{v}</div></li>')
        paid = b["paid_on"].strftime("%m/%d/%Y") if b["paid_on"] else ""
        return "<ol>" + "".join([li("Year-Bill Number", f"{b['year']}-{b['bill']}"),
                                 li("Parcel Id", b["ids"][0]),
                                 li("Current Balance", f"{b['balance']:,.2f}"),
                                 li("Original Levy", f"{b['original']:,.2f}"),
                                 li("Last Payment Date", paid)]) + "</ol>"


def run(row, portal):
    return asyncio.run(p.verify(row, portal, today=TODAY))


def onslow_roll_row(**kw):
    r = {"state": "NC", "county": "Onslow", "listing_type": "tax_lien", "source": p.ROLL_SLUG,
         "parcel_id": "1316-90", "street_address": "105 TEST FOX LN", "owner_name": "TESTOWNER ALPHA",
         "first_seen": "2026-10-06T18:00:00",
         "raw": {p.ROLL_KEY: {"county": "Onslow", "portal": ONSLOW, "parcel": "1316-90",
                              "account": "900000001", "years": [2024, 2025]},
                 "tax_owed": {"balance": 2400.0, "year": 2025, "source": p.ROLL_SLUG},
                 "two_year_delinquent": {"is_two_year_plus": True, "years": 2}}}
    r.update(kw)
    return r


def onslow_bills(**over):
    """Parcel id 009001 / map number 1316-90 at 105 TEST FOX LN; 2026 open (not late yet)."""
    situs = "105 TEST FOX LN HUBERT NC 28539-0000"
    out = [bill(2026, 9001, ["009001", "1316-90"], situs, balance=1100.0),
           bill(2025, 9001, ["009001", "1316-90"], situs, balance=over.get("b2025", 1180.0),
                paid_on=over.get("p2025")),
           bill(2024, 9001, ["009001", "1316-90"], situs, balance=over.get("b2024", 1220.0),
                paid_on=over.get("p2024")),
           bill(2023, 8123, ["009001", "1316-90"], situs, paid_on=over.get("p2023", date(2023, 11, 2))),
           bill(2022, 8122, ["009001", "1316-90"], situs, paid_on=over.get("p2022", date(2022, 12, 1))),
           bill(2021, 8121, ["009001", "1316-90"], situs, paid_on=date(2021, 10, 1)),
           bill(2020, 8120, ["009001", "1316-90"], situs, paid_on=date(2020, 10, 1)),
           bill(2019, 8119, ["009001", "1316-90"], situs, paid_on=date(2019, 10, 1))]
    return out


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def test_contract_and_version():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(p)
    assert (v.signal, v.version, v.ttl_days) == ("tax_lien", "v1", 30.0)
    assert v.governs == tc.GOVERNS


def test_applies_to_the_configured_counties_only():
    assert p.applies(onslow_roll_row())
    assert p.applies(onslow_roll_row(county="Graham", raw={"two_year_delinquent": {"is_two_year_plus": True}}))
    assert not p.applies(onslow_roll_row(county="Gates"))              # portal answers no records
    assert not p.applies(onslow_roll_row(state="SC"))
    # a PTS Cloud roll row geocoded into Onslow is tax_lien_ptscloud's (another county's parcel)
    assert not p.applies(onslow_roll_row(source="counties_nc.nc_ptscloud_delinquent_tax"))
    # no tax claim at all
    assert not p.applies({"state": "NC", "county": "Onslow", "listing_type": "foreclosure",
                          "source": "x", "parcel_id": "1", "raw": {}})


def test_description_and_situs_parsing():
    d = p.parse_description("001278<br/>1316-39<br />105 TEST FOX LN HUBERT NC 28539-4513<br />0.840 AC")
    assert d == {"ids": ["001278", "1316-39"], "situs": "105 TEST FOX LN HUBERT NC 28539-4513", "real": True}
    assert p.parse_description("569300060017LH<br/><br />2441 TEST FONTANA RD<br />0.000 UT")["ids"] == ["569300060017LH"]
    assert not p.parse_description("001278<br/><br />105 TEST FOX LN HUBERT NC 28539")["real"]   # no acreage
    cities = p.PORTALS["Onslow"].cities
    assert p.situs_street("105 TEST FOX LN HUBERT NC 28539-4513", cities) == "105 TEST FOX LN"
    assert p.situs_street("1534 TEST TAPOCO RD") == "1534 TEST TAPOCO RD"
    assert p.situs_street("22 TEST MAIN ST NEWTOWN NC 28540") == "22 TEST MAIN ST"


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------

def test_confirmed_on_the_rows_own_map_number():
    portal = FakePortal(ONSLOW, onslow_bills())
    r = run(onslow_roll_row(), portal)
    assert r.verdict == "confirmed", r.evidence
    ev = r.evidence
    assert ev["delinquent_by_year"] == {"2025": 1180.0, "2024": 1220.0}
    assert ev["total_delinquent"] == 2400.0 and ev["years_delinquent"] == 2
    assert ev["tax_parcel"] == "1316-90" and ev["address_binding"] == "parcel_number"
    assert ev["searched"][0]["by"] == "AlternateParcelIdentifier"        # Onslow's board parcel field
    assert "2026" not in ev["delinquent_by_year"]                         # not late until 2027-01-06


def test_stale_when_the_claimed_year_was_paid_late():
    portal = FakePortal(ONSLOW, onslow_bills(b2025=0.0, p2025=date(2026, 9, 28),
                                             b2024=0.0, p2024=date(2024, 12, 20)))
    r = run(onslow_roll_row(), portal)
    assert r.verdict == "stale", r.evidence
    assert r.evidence["current_claim_basis"] == "claimed_year_paid_late"
    assert r.evidence["late_levy_years"] == [2025]
    assert r.evidence["address_binding"] == "bill_address"


def test_refuted_when_everything_was_paid_on_time():
    portal = FakePortal(ONSLOW, onslow_bills(b2025=0.0, p2025=date(2025, 12, 1),
                                             b2024=0.0, p2024=date(2024, 12, 20)))
    r = run(onslow_roll_row(), portal)
    assert r.verdict == "refuted", r.evidence
    assert r.evidence["current_claim_basis"] == "claimed_years_on_time"
    assert r.evidence["chronic_claim"] == "not_confirmed" and r.evidence["history_complete"] is True
    assert p.governs_for(r.to_dict()) == tc.GOVERNS


def test_a_chronic_late_payer_keeps_tax_lien_chronic():
    portal = FakePortal(ONSLOW, onslow_bills(b2025=0.0, p2025=date(2026, 3, 1), b2024=0.0,
                                             p2024=date(2025, 2, 1), p2023=date(2024, 4, 1)))
    r = run(onslow_roll_row(), portal)
    assert r.verdict == "stale" and r.evidence["chronic_claim"] == "confirmed"
    assert "tax_lien_chronic" not in p.governs_for(r.to_dict())


def test_the_current_levy_alone_is_not_delinquent():
    bills = onslow_bills(b2025=0.0, p2025=date(2025, 11, 1), b2024=0.0, p2024=date(2024, 11, 1))
    r = run(onslow_roll_row(), FakePortal(ONSLOW, bills))
    assert r.verdict == "refuted"
    assert r.evidence["not_yet_delinquent_due"] == {"2026": 1100.0}


def test_parcel_not_found_is_unconfirmed():
    r = run(onslow_roll_row(), FakePortal(ONSLOW, []))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_not_found")


def test_an_account_search_never_binds_another_parcel_of_the_account():
    """A roll row with no board parcel: its map number search finds nothing (the county printed
    another spelling), the account search returns the account's two parcels, the OTHER one owing.
    Only bills carrying one of the row's own numbers count: none here, so unconfirmed, never the
    other parcel's balance."""
    other = [bill(2025, 7001, ["007001", "1400-12"], "9 TEST OTHER RD HUBERT NC 28539", balance=900.0),
             bill(2024, 7001, ["007001", "1400-12"], "9 TEST OTHER RD HUBERT NC 28539", balance=950.0)]
    mine = onslow_bills()
    for b in mine:
        b["ids"] = ["009001", "1316-090"]
    row = onslow_roll_row(parcel_id=None)
    portal = FakePortal(ONSLOW, other + mine)
    r = run(row, portal)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_not_found"), r.evidence
    assert [x["by"] for x in r.evidence["searched"]] == ["AlternateParcelIdentifier", "AccountNumber"]
    assert not r.evidence.get("delinquent_by_year")


def test_an_account_search_reads_the_rows_own_parcel():
    other = [bill(2025, 7001, ["007001", "1400-12"], "9 TEST OTHER RD HUBERT NC 28539", balance=900.0)]
    mine = onslow_bills(b2025=0.0, p2025=date(2025, 12, 1), b2024=0.0, p2024=date(2024, 12, 1))
    for b in mine:
        b["ids"] = ["1316-90"]                            # this bill prints only the map number
    row = onslow_roll_row(parcel_id=None)
    r = run(row, FakePortal(ONSLOW, other + mine))
    assert r.verdict == "refuted", r.evidence
    assert r.evidence["tax_parcel_from"] == "roll_account" and not r.evidence["delinquent_by_year"]


def test_never_confirmed_on_a_neighbours_bills():
    """A lien-agent row (its parcel was attached by a resolver) points at the NEIGHBOUR's parcel,
    which owes; the parcel that carries the row's address is paid on time. The verdict is about
    the row's own property: never `confirmed` on the neighbour's balance."""
    neighbour = [bill(2025, 5001, ["005001", "1316-91"], "107 TEST FOX LN HUBERT NC 28539",
                      owner="TESTOWNER BRAVO", account="900000002", balance=800.0),
                 bill(2024, 5001, ["005001", "1316-91"], "107 TEST FOX LN HUBERT NC 28539",
                      owner="TESTOWNER BRAVO", account="900000002", balance=820.0)]
    own = onslow_bills(b2025=0.0, p2025=date(2025, 12, 1), b2024=0.0, p2024=date(2024, 12, 1))
    row = {"state": "NC", "county": "Onslow", "listing_type": "tax_lien", "source": "liensnc",
           "parcel_id": "1316-91", "street_address": "105 TEST FOX LN", "owner_name": "TESTOWNER ALPHA",
           "raw": {"liensnc": {"pin": ""}, "two_year_delinquent": {"is_two_year_plus": True}}}
    r = run(row, FakePortal(ONSLOW, neighbour + own))
    assert r.verdict == "refuted", r.evidence
    assert r.evidence["followed_from_parcel"] == "1316-91"
    assert r.evidence["tax_parcel"] == "009001" and r.evidence["followed_because"] == "parcel_resolved"
    assert not r.evidence.get("delinquent_by_year")


def test_a_resolver_parcel_with_another_owner_is_not_confirmed():
    """The bills are at the row's address, but the parcel came from a resolver and the owner on
    the bills is someone else: unconfirmed, not confirmed."""
    bills = onslow_bills()
    for b in bills:
        b["owner"] = "SOMEBODY ELSE"
    row = onslow_roll_row(source="counties_generic.state_contamination.nc_ust_incidents",
                          raw={"parcel_from_address": True, "two_year_delinquent": {"is_two_year_plus": True}})
    r = run(row, FakePortal(ONSLOW, bills))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "bill_owner_differs")


def test_graham_searches_the_parcel_number_field():
    situs = "1534 TEST TAPOCO RD"
    bills = [bill(2026, 197, ["565100020099", "1130299"], situs, balance=550.0),
             bill(2025, 191, ["565100020099", "1130299"], situs, balance=548.12),
             bill(2024, 192, ["565100020099", "1130299"], situs, balance=594.71)]
    row = {"state": "NC", "county": "Graham", "listing_type": "tax_lien", "source": p.ROLL_SLUG,
           "parcel_id": "565100020099", "street_address": "1534 TEST TAPOCO RD",
           "owner_name": "TESTOWNER ALPHA",
           "raw": {p.ROLL_KEY: {"county": "Graham", "parcel": "565100020099", "account": "1",
                                "years": [2024, 2025]}}}
    portal = FakePortal(GRAHAM, bills)
    r = run(row, portal)
    assert r.verdict == "confirmed" and r.evidence["total_delinquent"] == 1142.83
    partial = [a for a in portal.asked if a[0] == "POST" and a[1].endswith("GetSearchTablePartial/")]
    assert partial[0][2]["ParcelNumber"] == "565100020099"


def test_a_failing_portal_is_unconfirmed_and_then_skipped():
    portal = FakePortal(ONSLOW, onslow_bills(), fail_tables=5)
    r1 = run(onslow_roll_row(), portal)
    assert (r1.verdict, r1.evidence["reason"]) == ("unconfirmed", "fetch_failed")
    r2 = run(onslow_roll_row(parcel_id="1316-92"), portal)
    assert r2.verdict == "unconfirmed" and r2.evidence["reason"] in ("fetch_failed", "portal_unhealthy")
    r3 = run(onslow_roll_row(parcel_id="1316-93"), portal)
    assert (r3.verdict, r3.evidence["reason"]) == ("unconfirmed", "portal_unhealthy")


def test_the_public_evidence_names_nobody():
    r = run(onslow_roll_row(), FakePortal(ONSLOW, onslow_bills()))
    blob = json.dumps(r.to_dict())
    assert "TESTOWNER" not in blob and "900000001" not in blob     # no owner, no account number


# ---------------------------------------------------------------------------
# 2026-10-09: Transylvania and Catawba (newer build: the full search model)
# ---------------------------------------------------------------------------

TRANSY = p.PORTALS["Transylvania"].base
CATAWBA = p.PORTALS["Catawba"].base
_FULL = ("OwnerLastName", "OwnerFirstName", "ParcelNumber", "ParcelSearch", "TaxYear", "BillNumber",
         "UnpaidBillsOnly", "FormattedPropertyAddress", "SortBy")


class FullModelPortal(FakePortal):
    """The newer build: a partial posted without every .search-value field answers an empty body
    and the table then fails (HTTP 500), as Transylvania did on 2026-10-09."""

    def __init__(self, base, bills, *, required=_FULL, map_ref=None, pin_pad=""):
        super().__init__(base, bills)
        self.required, self.map_ref, self.pin_pad = required, map_ref, pin_pad

    async def post_form(self, url, data, **kw):
        if url.endswith("/GetSearchTablePartial/") and not all(f in data for f in self.required):
            self.asked.append(("POST", url, dict(data)))
            self.model = None
            return FormResponse(200, url, "")
        if url.endswith("/GetSearchTableData") and self.model is None:
            return FormResponse(500, url, "<title>Object reference not set to an instance</title>")
        return await super().post_form(url, data, **kw)

    def _match(self):
        m = self.model or {}
        if self.pin_pad and m.get("AlternateParcelIdentifier"):
            v = tc.alnum(m["AlternateParcelIdentifier"])
            return [b for b in self.bills if len(b["ids"]) > 1 and tc.alnum(b["ids"][1]) == v + self.pin_pad]
        return super()._match()

    def _row(self, b):
        r = FakePortal._row(b)
        if self.map_ref:      # Transylvania: parcel, map reference, situs, acreage
            r["cell"][4] = "<br/>".join([*b["ids"], self.map_ref, b["situs"], b["acres"]])
        if b.get("no_units"):  # Catawba before levy 2025: no acreage part
            r["cell"][4] = "<br/>".join([*b["ids"], b["situs"], ""])
        return r


def transy_bills(**over):
    situs = "12 TEST BAYNARD RD"
    pid = "8500000001000"
    return [bill(2026, 26001, [pid], situs, balance=400.0),
            bill(2025, 15001, [pid], situs, balance=over.get("b2025", 436.06), paid_on=over.get("p2025")),
            bill(2024, 14001, [pid], situs, paid_on=over.get("p2024", date(2024, 9, 1))),
            bill(2023, 13001, [pid], situs, paid_on=date(2023, 9, 1)),
            bill(2022, 12001, [pid], situs, paid_on=date(2022, 9, 1)),
            bill(2021, 11001, [pid], situs, paid_on=date(2021, 9, 1)),
            bill(2020, 10001, [pid], situs, paid_on=date(2020, 9, 1)),
            bill(2019, 9001, [pid], situs, paid_on=date(2019, 9, 1))]


def transy_roll_row(**kw):
    r = {"state": "NC", "county": "Transylvania", "listing_type": "tax_lien",
         "source": "counties_nc.transylvania_delinquent_tax", "parcel_id": "Escrow :",
         "street_address": "12 TEST BAYNARD RD", "owner_name": "TESTOWNER ALPHA",
         "first_seen": "2026-10-04T12:00:00",
         "raw": {"transylvania_tax": {"tax_year": "2025", "bill_number": "15001",
                                      "account_number": "900000001", "parcel": "8500000001000",
                                      "balance_owed": 436.06},
                 "tax_owed": {"balance": 436.06, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def test_transylvania_posts_the_full_model_and_reads_the_situs_past_the_map_reference():
    portal = FullModelPortal(TRANSY, transy_bills(), map_ref="T999 00001   01 MS.07")
    r = run(transy_roll_row(), portal)
    assert r.verdict == "confirmed", r.evidence
    ev = r.evidence
    assert ev["delinquent_by_year"] == {"2025": 436.06}
    assert ev["searched"][0] == {"by": "ParcelNumber", "from": "roll_block", "bills": 8}
    assert ev["tax_parcel"] == "8500000001000"
    partial = [a for a in portal.asked if a[0] == "POST" and a[1].endswith("GetSearchTablePartial/")]
    assert all(f in partial[0][2] for f in _FULL) and partial[0][2]["ParcelNumber"] == "8500000001000"
    tables = [a for a in portal.asked if a[0] == "POST" and a[1].endswith("GetSearchTableData")]
    assert tables[0][2].get("PostData") == ""
    d = p.parse_description("8500000001000<br/>T999 00001   01 MS.07<br />12 TEST BAYNARD RD<br />4.420 AC",
                            p.PORTALS["Transylvania"])
    assert d["situs"] == "12 TEST BAYNARD RD" and d["ids"] == ["8500000001000"] and d["real"]


def test_transylvania_escrow_placeholder_is_no_parcel_and_a_dashed_pin_is_searched_bare():
    row = transy_roll_row(parcel_id="Escrow :")
    assert p.searches(row, p.PORTALS["Transylvania"])[0] == ("ParcelNumber", "8500000001000", "roll_block")
    row = transy_roll_row(parcel_id="8500-00-0001-000", source="counties_generic.x", raw={
        "tax_owed": {"balance": 436.06, "year": 2025, "kind": "delinquent_tax"}})
    assert p.applies(row)                                        # the gate's claim: a tax_owed balance
    assert p.searches(row, p.PORTALS["Transylvania"]) == [("ParcelNumber", "8500000001000", "board_parcel")]
    r = run(row, FullModelPortal(TRANSY, transy_bills(), map_ref="T999 00001   01 MS.07"))
    assert r.verdict == "confirmed" and r.evidence["address_binding"] == "parcel_number"


def test_transylvania_stale_when_the_claimed_year_was_paid_late():
    bills = transy_bills(b2025=0.0, p2025=date(2026, 9, 30))
    r = run(transy_roll_row(), FullModelPortal(TRANSY, bills, map_ref="T999 00001   01 MS.07"))
    assert r.verdict == "stale", r.evidence
    assert r.evidence["late_levy_years"] == [2025] and r.evidence["address_binding"] == "bill_address"


def test_the_old_minimal_model_fails_on_the_newer_build():
    """What the verifier would get without Portal.full_model: unconfirmed, never a verdict."""
    old = p.Portal("Transylvania", TRANSY, "ParcelNumber", rolls=p.PORTALS["Transylvania"].rolls)
    assert set(p.search_model(old, "ParcelNumber", "1")) == {"PageSize", "ParcelNumber", "UnpaidBillsOnly",
                                                             "ParcelSearch"}
    assert set(p.search_model(p.PORTALS["Transylvania"], "ParcelNumber", "1")) >= set(_FULL) | {"AccountNumber"}
    cat = p.search_model(p.PORTALS["Catawba"], "AlternateParcelIdentifier", "374100000001")
    assert "AccountNumber" not in cat and cat["AlternateParcelIdentifier"] == "374100000001"


def catawba_bills(**over):
    ids = ["0027012", "3741000000010000"]
    situs = "20 TEST 19TH ST NEWTON NC 28658"
    out = [bill(2026, 27012, ids, situs, balance=0.0, paid_on=date(2026, 9, 1)),
           bill(2025, 27012, ids, situs, balance=over.get("b2025", 0.0), paid_on=over.get("p2025", date(2026, 3, 2)))]
    for y in range(2024, 2018, -1):
        b = bill(y, 1600000 + y, ids, "20 TEST 19TH ST", paid_on=date(y, 11, 20))
        b["no_units"] = True
        out.append(b)
    pp = bill(2024, 1810313, ["Personal Property"], "20 TEST 19TH ST", balance=99.0)
    out.append(pp)
    return out


def catawba_pdf_row(**kw):
    r = {"state": "NC", "county": "Catawba", "listing_type": "tax_lien",
         "source": "counties_nc.nc_county_pdf_delinquent_tax", "parcel_id": "",
         "street_address": None, "owner_name": "TESTOWNER ALPHA", "first_seen": "2026-08-01T12:00:00",
         "raw": {"nc_county_pdf_delinquent_tax": {"county": "Catawba", "county_id": "27012",
                                                  "id_is_parcel": False, "principal_tax_due": 4000.0,
                                                  "tax_year": 2025},
                 "tax_owed": {"balance": 4000.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def test_catawba_pdf_id_is_the_reid_and_older_bills_without_acreage_are_read():
    portal = FullModelPortal(CATAWBA, catawba_bills(), required=_FULL + ("AlternateParcelIdentifier",),
                             pin_pad="0000")
    r = run(catawba_pdf_row(), portal)
    assert r.verdict == "stale", r.evidence            # claimed 2025, paid 2026-03-02 (after Jan 6)
    ev = r.evidence
    assert ev["searched"][0] == {"by": "ParcelNumber", "from": "roll_block", "bills": 8}
    assert ev["tax_parcel"] == "0027012" and ev["address_binding"] == "no_row_address"
    assert ev["late_levy_years"] == [2025] and ev["history_complete"] is True
    assert ev["chronic_claim"] == "not_confirmed"
    d = p.parse_description("Personal Property<br />20 TEST 19TH ST<br />", p.PORTALS["Catawba"])
    assert not d["real"]


def test_catawba_board_pin_finds_the_padded_pin_and_confirms():
    portal = FullModelPortal(CATAWBA, catawba_bills(b2025=1500.0, p2025=None),
                             required=_FULL + ("AlternateParcelIdentifier",), pin_pad="0000")
    row = {"state": "NC", "county": "Catawba", "listing_type": "code_violation", "source": "counties_generic.x",
           "parcel_id": "374100000001", "street_address": "20 TEST 19TH ST", "owner_name": "TESTOWNER ALPHA",
           "raw": {"tax_owed": {"balance": 1500.0, "year": 2025, "kind": "delinquent_tax"}}}
    r = run(row, portal)
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["searched"][0]["by"] == "AlternateParcelIdentifier"
    assert r.evidence["delinquent_by_year"] == {"2025": 1500.0}
    assert r.evidence["tax_parcel"] == "374100000001"


def test_a_merged_pdf_block_is_not_the_rows_own_number():
    """A Catawba row of another source carrying the advertisement block of some parcel: the block's
    REID is never searched or treated as exact (it is a claim about the block's parcel)."""
    row = catawba_pdf_row(source="counties_generic.state_contamination.nc_ust_incidents",
                          parcel_id="374100000001")
    assert p.applies(row)
    assert p.searches(row, p.PORTALS["Catawba"]) == [("AlternateParcelIdentifier", "374100000001", "board_parcel")]
    own, exact = p.row_parcel_ids(row)
    assert "0027012" not in own and "374100000001" in exact


def test_a_tax_owed_balance_of_another_lien_is_not_a_property_tax_claim():
    row = {"state": "NC", "county": "Catawba", "listing_type": "tax_lien", "source": "liensnc",
           "parcel_id": "374100000001", "raw": {"tax_owed": {"balance": 900.0, "kind": "delinquent_tax"}}}
    assert not tc.tax_owed_claim(row)
    row2 = dict(row, listing_type="foreclosure", source="x")
    assert tc.tax_owed_claim(row2)
    row3 = dict(row2, raw={"tax_owed": {"balance": 0, "kind": "delinquent_tax"}})
    assert not tc.tax_owed_claim(row3)
    row4 = dict(row2, raw={"tax_owed": {"balance": 50.0, "kind": "judgment"}})
    assert not tc.tax_owed_claim(row4)


def test_a_roll_row_whose_account_holds_only_personal_property_says_so():
    """Transylvania's roll lists business personal-property bills with parcel "Escrow :": the
    account search answers only Personal Property bills, never a parcel to judge."""
    pp = bill(2025, 100416, ["Personal Property"], "", account="202510041600", balance=50.0)
    portal = FullModelPortal(TRANSY, [pp], map_ref="T999 00001   01 MS.07")
    row = transy_roll_row(raw={"transylvania_tax": {"tax_year": "2025", "bill_number": "100416",
                                                    "account_number": "202510041600", "parcel": "Escrow :"},
                               "tax_owed": {"balance": 50.0, "year": 2025, "kind": "delinquent_tax"}})
    r = run(row, portal)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "personal_property_only"), r.evidence


# ---------------------------------------------------------------------------
# 2026-10-09: Brunswick (the older ITSNet build: another cell order, the situs in its own cell)
# ---------------------------------------------------------------------------

BRUNSWICK = p.PORTALS["Brunswick"].base


class ItsNetPortal(FakePortal):
    @staticmethod
    def _row(b):
        desc = "<br/>".join(b["ids"]) if b["ids"] else None
        return {"id": f"{b['year']}/{b['bill']}",
                "cell": [str(b["year"]), b["bill"], b["account"], b["owner"], f"{b['original']:,.2f}",
                         f"{b['balance']:,.2f}", "", desc, f"{b['situs']} TESTVILLE 28000 COUNTY"]}


def test_brunswick_reads_the_itsnet_cell_order():
    situs = "1017 TEST ANDOVER PL SE"
    bills = [bill(2026, 26001, ["201TT022", "204700000001"], situs, balance=900.0),
             bill(2025, 25001, ["201TT022", "204700000001"], situs, balance=986.82),
             bill(2024, 24001, ["201TT022", "204700000001"], situs, balance=120.0),
             bill(2011, 11001, [], situs, balance=0.0)]                   # no description: dropped
    row = {"state": "NC", "county": "Brunswick", "listing_type": "tax_sale", "source": "counties_nc.x",
           "parcel_id": "201TT022", "street_address": "1017 TEST ANDOVER PL SE", "owner_name": "TESTOWNER ALPHA",
           "raw": {"tax_owed": {"balance": 1106.82, "year": 2025, "kind": "delinquent_tax"}}}
    r = run(row, ItsNetPortal(BRUNSWICK, bills))
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 986.82, "2024": 120.0}
    assert r.evidence["address_relation"] == "match"       # "... SE TESTVILLE 28000 COUNTY" cut to the street
    rows = p.parse_rows({"rows": [ItsNetPortal._row(b) for b in bills]}, p.PORTALS["Brunswick"])
    assert [b["year"] for b in rows] == [2026, 2025, 2024] and rows[0]["situs"] == "1017 TEST ANDOVER PL SE TESTVILLE 28000"


# ---------------------------------------------------------------------------------------------
# top-80 check group (2026-10-09): six counties of the vendor's newer build
# ---------------------------------------------------------------------------------------------

def test_the_newer_build_counties_are_configured_with_the_full_model():
    for c in ("anson", "granville", "harnett", "yadkin", "alleghany", "scotland"):
        port = p._BY_COUNTY[c]
        assert port.full_model and port.parcel_field == "ParcelNumber" and port.real_without_units
    assert p._BY_COUNTY["alleghany"].cells == p.ITSNET_CELLS and p._BY_COUNTY["anson"].cells == p.CELLS
    assert not p._BY_COUNTY["granville"].account_search
    assert "AlternateParcelIdentifier" in p._BY_COUNTY["granville"].model_fields
    for c in ("caswell", "jones", "person"):                  # no parcel id to bind a row to
        assert c not in p._BY_COUNTY


def test_alleghany_layout_parcel_and_alternate_in_the_description_situs_in_the_address_cell():
    payload = {"rows": [
        {"id": "2025/3896", "cell": ["2025", "3896", "83774", "EXAMPLE HOLDINGS LLC", "2,737.83", "86.21", "",
                                     "3033811534<br/>", "147 SAMPLE RD"]},
        {"id": "2025/17739", "cell": ["2025", "17739", "83903", "EXAMPLE NURSERY", "17.52", "19.06", "",
                                      "Personal Property", "5734 SAMPLE HWY"]}]}
    bills = p.parse_rows(payload, p._BY_COUNTY["alleghany"])
    assert len(bills) == 1
    assert bills[0]["ids"] == ["3033811534"] and bills[0]["situs"] == "147 SAMPLE RD" and bills[0]["balance"] == 86.21


def test_anson_layout_a_parcel_only_description_is_real_property_without_units():
    payload = {"rows": [
        {"id": "2025/201268", "cell": ["2025", "201268", "7561", "EXAMPLE LLC", "742600527368<br/><br /><br />",
                                       "392.85", "392.85", "<button>+</button>"]},
        {"id": "2025/7604", "cell": ["2025", "7604", "7580", "EXAMPLE JOE", "Personal Property<br />1 SAMPLE RD",
                                     "14.41", "15.67", "<button>+</button>"]}]}
    bills = p.parse_rows(payload, p._BY_COUNTY["anson"])
    assert [b["ids"] for b in bills] == [["742600527368"]] and bills[0]["balance"] == 392.85
