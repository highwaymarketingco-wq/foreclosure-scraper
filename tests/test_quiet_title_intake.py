"""quiet_title.intake + render with a FAKE county adapter (no network), and the PoliteFetcher.
Every name, PIN and amount here is made up."""
from datetime import date, datetime, timezone

import pytest

from foreclosure_scraper.quiet_title.adapters.base import CountyAdapter
from foreclosure_scraper.quiet_title.fetch import PoliteFetcher, Walled
from foreclosure_scraper.quiet_title.intake import (chain_grantor, desc_marks, is_conveyance, later_summary,
                                                    run_intake, shared_marks, tax_rows)
from foreclosure_scraper.quiet_title.model import (DeathEntry, DeathSearch, Instrument, IntakeResult, NameSearch,
                                                   Parcel, RecordCheck, TaxBill, TaxStatus, TaxTransaction)
from foreclosure_scraper.quiet_title.render import render_html

PIN = "000011112222333"


def inst(date_, idx, kind, grantors, grantees, desc, bp, matched=None, side=None):
    book, page = bp.split("/")
    y = int(date_[-4:])
    iso = f"{date_[6:]}-{date_[:2]}-{date_[3:5]}" if "*" not in date_ else None
    return Instrument(date=date_, date_iso=iso, year=y, index_code=idx, kind=kind, grantors=grantors,
                      grantees=grantees, matched=matched or [], matched_side=side, description=desc,
                      book=book, page=page, pages=2)


def bill(y, due, txs, detail=True):
    return TaxBill(bill=f"0000000001-{y}-{y}-0000-00", tax_year=y, levy_year=y, regular=True,
                   owner="ANNA MARIE TESTER (HEIRS)", amount_due=due, amount_due_text=f"${due:,.2f}",
                   transactions=txs, detail_read=detail, exhibit="E3" if detail else None)


class FakeAdapter(CountyAdapter):
    state, county = "NC", "Testshire"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.searches = []

    def parcel(self, pin):
        ex = self.new_exhibit("parcel", "fake layer", "https://example.invalid/layer")
        return Parcel(pin=pin, found=True, exhibit=ex.key, owner="ANNA MARIE TESTER (HEIRS)", care_of="JOHN SAMPLE",
                      mailing="12 EXAMPLE RIDGE RD, NOWHERE NC 28000", situs="EXAMPLE RIDGE RD",
                      situs_note="no house number", deed_book="123", deed_page="45", deed_date="1979-03-04",
                      deed_instrument="DEE", field_names=["pinnum", "owner"], acreage=1.5, tax_value=10000.0)

    def parcels_at_mailing_number(self, parcel):
        return [], "The mailing address is on a different road; not checked."

    def tax(self, parcel, today):
        bill_line = lambda d, amt: TaxTransaction("BILL", d, "", amt, 0.0, 0.0, 0.0, amt)  # noqa: E731
        bills = [bill(2026, 80.0, [bill_line("7/25/2026", 80.0)]),
                 bill(2025, 100.0, [bill_line("7/26/2025", 100.0)]),
                 bill(2024, 90.0, [bill_line("7/27/2024", 90.0)]),
                 bill(2023, 0.0, [bill_line("7/29/2023", 85.0),
                                  TaxTransaction("PAYMENT", "2/1/2024", "9", -85.0, 0.0, 0.0, 0.0, -85.0)]),
                 bill(2022, 0.0, [], detail=False)]
        return TaxStatus(exhibit="E3", parcel_status="Active", bills=bills, current_year=2026,
                         completed_years=[2025, 2024, 2023], interest_rule="Interest begins January 6.")

    def deed_at(self, book, page, label=None):
        ex = self.new_exhibit("book/page", "fake register", "https://example.invalid/bp")
        rows = [inst("03/04/1979", "DEE", "PRE 95 DEEDS", ["SAMPLE, ROY W"], ["TESTER, ANNA MARIE"],
                  "[W/DEED ] 1.5 ACRES EXAMPLE TWP", "123/45"),
                inst("07/31/1989", "DTR", "DEED OF TRUST", ["OTHER, PAT"], ["LENDER, TR"], "[D/T ] LOT 5", "123/45")]
        for r in rows:
            r.exhibit = ex.key
        return rows, "https://example.invalid/bp?bk=123&pg=45"

    def deed_detail(self, inst):
        return None

    def name_search(self, purpose, person, *, side="both", date_from="", date_thru=""):
        self.searches.append((purpose, getattr(person, "last", person), side, date_thru))
        ex = self.new_exhibit(purpose, "fake register", "https://example.invalid/name", method="POST")
        ns = NameSearch(purpose=purpose, last=getattr(person, "last", str(person)),
                        first=getattr(person, "first", ""), side=side, date_thru=date_thru, exhibit=ex.key)
        if "owner of record" in purpose:
            ns.rows = [inst("03/04/1979", "DEE", "PRE 95 DEEDS", ["SAMPLE, ROY W"], ["TESTER, ANNA MARIE"],
                         "[W/DEED ] 1.5 ACRES EXAMPLE TWP", "123/45", ["TESTER, ANNA MARIE"], "grantee"),
                       inst("**/**/1990", "DTH", "", ["TESTER, ANNA MARIE"], ["TESTER, JOHN"], "", "70/1",
                         ["TESTER, ANNA MARIE"], "grantor"),
                       inst("05/05/1985", "DEE", "PRE 95 DEEDS", ["TESTER, ANNA J"], ["BUYER, BOB"], "[W/DEED ] LOT 2",
                         "200/2", ["TESTER, ANNA J"], "grantor")]
        elif person.last == "SAMPLE":
            ns.rows = [inst("01/02/1965", "DEE", "", ["UTILITY CO"], ["SAMPLE, ROY W"], "EASEMENT", "900/1",
                         ["SAMPLE, ROY W"], "grantee"),
                       inst("06/07/1960", "DEE", "", ["ELDER, MAE B/ DECD", "ELDER, JOHN", "ELDER, SUE", "ELDER, TOM"],
                         ["SAMPLE, ROY W"], "EXAMPLE TWP 2 TRACTS", "800/8", ["SAMPLE, ROY W"], "grantee"),
                       inst("03/03/1950", "DEE", "", ["FAR, AWAY"], ["SAMPLE, ROY"], "EXAMPLE TWP", "700/7",
                         ["SAMPLE, ROY"], "grantee")]
        ns.total, ns.shown = len(ns.rows), len(ns.rows)
        return ns

    def death_search(self, person, reading):
        ds = DeathSearch(person=person.indexed(), reading=reading, last=person.last, first=person.first,
                         valid_from="1/1/1913", valid_thru="10/1/2026", total=3)
        ds.entries = [DeathEntry(1990, "**/**/1990", "70 / 1", ["TESTER, ANNA MARIE"], ["TESTER, JOHN"], "decedent",
                                 "candidate"),
                      DeathEntry(1960, "**/**/1960", "40 / 1", ["TESTER, ANNA JOY"], ["SAMPLE, ROY"], "decedent",
                                 "candidate"),
                      DeathEntry(1970, "**/**/1970", "50 / 1", ["TESTER, BABY"], ["TESTER, ANNA MARIE"], "parent",
                                 "parent_only")]
        return ds

    def static_records(self):
        return [RecordCheck("Probate files", "walled", "court portal CAPTCHA", "not known")]

    def how_to(self, result):
        return [("Tax bills", ["Open the county tax site."])]

    def sources(self):
        return [("fake register", "https://example.invalid", "free")]


@pytest.fixture()
def done(tmp_path):
    res = IntakeResult(county="Testshire", state="NC", pin=PIN,
                       started=datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc))
    ad = FakeAdapter(PoliteFetcher(tmp_path), res, "20261007")
    run_intake(ad, PIN, date(2026, 10, 7))
    return res, ad


def test_vesting_is_the_entry_with_the_county_deed_date(done):
    res, _ = done
    assert res.vesting is res.deed_rows[0]
    assert "matches the county's deed date" in res.vesting_note


def test_chain_skips_easements_takes_latest_deed_and_follows_the_decedent(done):
    res, ad = done
    assert [c.book_page for c in res.chain] == ["800 / 8"]
    tie = res.chain[0].tie
    assert "the full name agrees" in tie and "EXAMPLE TWP" in tie and "1 other deed" in tie
    # step 2 follows the grantor the index marks deceased, not the first of four
    assert ad.searches[-1][1] == "ELDER" and ad.searches[-1][2] == "grantee"
    assert "No earlier deed into ELDER, MAE B" in res.chain_note


def test_owner_search_drops_vital_records_and_conflicting_names(done):
    res, _ = done
    ns = res.after_vesting[0]
    assert [r.book_page for r in ns.rows] == ["123 / 45"]
    assert "1 rows dropped" in ns.purpose and "1 birth, marriage or death" in ns.purpose


def test_later_summary_counts_only_entries_after_the_cited_deed(done):
    res, _ = done
    assert later_summary(res).startswith("none found")
    res.after_vesting[0].rows.append(inst("05/03/2023", "CRP", "SUBSTITUTE TRUSTEE", ["TESTER, ANNA MARIE"],
                                          ["SAMPLE TRUSTEES LLC"], "", "6000/1"))
    res.after_vesting[0].rows.append(inst("01/02/2006", "CRP", "DEED OF TRUST", ["TESTER, ANNA MARIE"],
                                          ["LENDER INC"], "[D/T ]", "4000/1"))
    s = later_summary(res)
    assert s.startswith("2 entries") and "1 substitution of trustee" in s and "1 deed of trust" in s
    assert "latest filed 05/03/2023" in s


def test_owner_read_from_register_and_deaths_classified(done):
    res, _ = done
    assert res.owner_people[0]["person"].indexed() == "TESTER, ANNA MARIE"
    assert "register's index" in res.owner_people[0]["reading"]
    fits = [e.fit for e in res.death_searches[0].entries]
    assert fits == ["fit", "candidate", "parent_only"]
    obs = res.death_searches[0].entries[1].observations
    assert any("before the 1979 deed" in o for o in obs)


def test_tax_rows_three_completed_years_current_apart():
    ad_res = IntakeResult(county="T", state="NC", pin=PIN, started=datetime(2026, 10, 7, tzinfo=timezone.utc))
    ts = FakeAdapter(None, ad_res, "x").tax(None, date(2026, 10, 7))
    tr = tax_rows(ts, date(2026, 10, 7), "NC")
    assert [r["year"] for r in tr["rows"]] == [2025, 2024, 2023]
    assert tr["unpaid_years"] == [2025, 2024] and tr["unpaid_total"] == 190.0
    assert tr["current"]["year"] == 2026 and tr["current"]["due"] == 80.0
    assert "(after interest began)" in tr["rows"][2]["payments"]
    assert [b.levy_year for b in tr["older"]] == [2022] and tr["older_open"] == []


def test_sheet_says_what_it_does_and_does_not_establish(done):
    res, _ = done
    h = render_html(res)
    assert "Legal description: needs the deed image" in h
    assert "Current year, not yet late" in h
    assert "Fits the full name" in h and "Confirmed in part" in h
    assert "No title search was run" in h
    assert "Probate files" in h and "walled" in h
    assert "EDT" in h and "UTC" in h
    assert any(r.record.startswith("Register of Deeds deaths index") for r in res.records)


def test_conveyance_and_description_rules():
    assert is_conveyance(inst("01/01/1980", "DEE", "PRE 95 DEEDS", [], [], "[W/DEED ] LOT 1", "1/1"))
    assert not is_conveyance(inst("01/01/1980", "DEE", "PRE 95 DEEDS", [], [], "[P O A ]", "1/1"))
    assert not is_conveyance(inst("01/01/1980", "DTR", "DEED OF TRUST", [], [], "[D/T ]", "1/1"))
    assert not is_conveyance(inst("01/01/1960", "DEE", "", [], [], "ORDER & FINAL JUDGMT", "1/1"))
    assert is_conveyance(inst("01/01/2001", "CRP", "DEED", [], [], "LOT 3", "1/1"))
    assert not is_conveyance(inst("01/01/2001", "CRP", "DEED OF TRUST SATISFACTION", [], [], "", "1/1"))
    assert "1.5 ACRES" in desc_marks("[W/DEED ] 1.5 ACRES EXAMPLE TWP")
    assert shared_marks("[D/T] EXAMPLE CRK TWP", "EXAMPLE CREEK TWP 2 TRACTS") == ["EXAMPLE CREEK TWP"]
    many = inst("01/01/1970", "DEE", "", ["A, B", "C, D", "E, F", "G, H"], [], "", "1/1")
    assert chain_grantor(many)[0] is None and "4 grantors" in chain_grantor(many)[1]


class _Resp:
    def __init__(self, status, text, url):
        self.status_code, self.text, self.url, self.content = status, text, url, text.encode()


class _Session:
    def __init__(self, pages):
        self.pages = pages

    def request(self, method, url, params=None, data=None, timeout=None):
        status, text = self.pages[url]
        return _Resp(status, text, url)


def test_polite_fetcher_spaces_requests_per_host_and_stops_at_walls(tmp_path):
    t = [100.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 2))
        t[0] += s

    pages = {"https://a.example/1": (200, "ok"), "https://a.example/2": (200, "ok"),
             "https://b.example/1": (200, "ok"), "https://a.example/3": (200, "<title>Just a moment...</title>")}
    f = PoliteFetcher(tmp_path, session_factory=lambda: _Session(pages), sleep=sleep, clock=lambda: t[0])
    f.get("https://a.example/1")
    f.get("https://b.example/1")
    f.get("https://a.example/2")
    assert slept == [1.6]
    with pytest.raises(Walled) as w:
        f.get("https://a.example/3")
    assert w.value.reason == "challenge page"
    assert (tmp_path / "fetchlog.jsonl").read_text().count("\n") == 4
    assert f.save("x.html", "<p>saved</p>") == "x.html" and (tmp_path / "exhibits" / "x.html").exists()
