"""Offline tests for the Greenwood SC register reader (rod/greenwood_docsearch.py).

Fixtures are hand-written webAPI replies in the shape the county served on 2026-10-07; every name,
book and page in them is made up."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.rod import greenwood_docsearch as gw
from foreclosure_scraper.rod import sc_chain, sc_polite
from foreclosure_scraper.rod.sc_polite import PoliteSession


def det(i, typ, day, bp, frm, to, legal="", related=()):
    return {"id": i, "instrumentNumber": f"2015{i:08d}", "bookPage": bp, "volume": typ.split()[0], "documentType": typ,
            "fromNames": frm, "toNames": to, "legalDescription": legal, "recorded": day, "recordedTime": "",
            "numPages": 2, "isVerified": True, "status": "rcrd", "imagePath": "", "amount": "",
            "related": list(related), "visible": True}


def n(name, match=False):
    return {"name": name, "match": match}


def reply(details, err=""):
    return {"totRec": len(details), "deedsExist": True, "mortgagesExist": True, "platsExist": False,
            "fedLiensExist": False, "stateLiensExist": False, "errMsg": err, "names": [], "details": details}


OWNER = "Tamberlane Ivo R"
SELLER = "Quenby Mabel S"
OWNER_REPLY = reply([
    det(1, "Deed", "04/11/2015", "1450-221", [n(SELLER)], [n(OWNER, True)], "Lot 3 Sycamore Bend",
        related=[{"bookPage": "77-9", "volume": "Plat", "documentType": "Plat", "recorded": "01/02/1999"}]),
    det(2, "Mortgage", "04/11/2015", "2300-15", [n(OWNER, True)], [n("Testbank Of Nowhere Na")], "Lot 3"),
    det(3, "Satisfaction", "08/01/2022", "4100-7", [n("Testbank Of Nowhere Na")], [n(OWNER, True)], ""),
    det(4, "SC Tax Lien", "02/02/2023", "12-40", [n("SC Department Of Revenue")], [n(OWNER, True)], "Tax $900"),
    det(5, "SC Tax Satisfaction", "06/06/2023", "12-77", [n("SC Department Of Revenue")], [n(OWNER, True)], ""),
])
SELLER_REPLY = reply([
    det(6, "Deed", "09/09/1999", "800-12", [n("Sycamore Bend Llc")], [n(SELLER, True)], "Lot 3 Sycamore Bend"),
    det(7, "Deed", "04/11/2015", "1450-221", [n(SELLER, True)], [n(OWNER)], "Lot 3"),
])


class Resp:
    def __init__(self, text, status=200, url=gw.BASE):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


class FakeHttp:
    def __init__(self, shell="<html><div id=root></div></html>", api=None):
        self.shell, self.api, self.calls = shell, api, []

    def request(self, method, url, json=None, **kw):
        self.calls.append((method, url.rsplit("/", 1)[-1], json))
        if method == "GET":
            return Resp(self.shell)
        if self.api is not None:
            return Resp(self.api)
        import json as _j
        if json["txt"] == "TAMBERLANE IVO":
            return Resp(_j.dumps(OWNER_REPLY))
        if json["txt"] == "QUENBY MABEL":
            assert json["toDate"] == "04/11/2015"
            return Resp(_j.dumps(SELLER_REPLY))
        return Resp(_j.dumps(reply([])))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sc_polite.reset_walled()
    sc_polite.BUDGET.reset()
    sc_chain.clear_cache()
    monkeypatch.setattr(sc_polite, "SLEEP", lambda s: None)
    yield
    sc_polite.reset_walled()
    sc_polite.BUDGET.reset()
    sc_chain.clear_cache()


def test_parse_details():
    docs = gw.parse_details(OWNER_REPLY)
    deed = docs[0]
    assert (deed.book, deed.page, deed.doc_type) == ("1450", "221", "DEED")
    assert deed.grantor == "QUENBY MABEL S" and deed.grantee == "TAMBERLANE IVO R"
    assert deed.notes == "Lot 3 Sycamore Bend" and deed.raw["grantee_matched"] is True
    assert deed.raw["related"][0]["type"] == "Plat"
    kinds = [sc_chain.kind_of(d) for d in docs]
    assert kinds == ["deed", "mortgage", "satisfaction", "lien", "lien_release"]
    assert gw.parse_details(reply([])) == []


def test_payload_dates():
    from datetime import date
    p = gw.payload("TAMBERLANE IVO", date_to=date(2015, 4, 11))
    assert p["toDate"] == "04/11/2015" and p["fromDate"] == "" and p["isValidIP"] is False
    assert p["action"] == "getResults" and p["searchType"] == "Name"


def test_chain_end_to_end():
    http = FakeHttp()
    out = gw.chain("Greenwood", "TAMBERLANE IVO R", session=PoliteSession(session=http))
    assert out["status"] == "ok" and out["platform"] == "greenwood_docsearch"
    assert out["last_deed"]["book"] == "1450" and out["last_deed"]["description"] == "Lot 3 Sycamore Bend"
    assert out["prior_instruments"][0]["book"] == "800"        # the seller's own deed, grantee side only
    liens = out["liens"]
    assert len(liens["deeds_of_trust"]) == 1 and len(liens["satisfactions"]) == 1
    assert [x["kind"] for x in liens["other_liens"]] == ["lien_release", "lien"]
    assert liens["open_deeds_of_trust_est"] == 0


def test_register_error_message():
    out = gw.chain("Greenwood", "TAMBERLANE IVO R",
                   session=PoliteSession(session=FakeHttp(api=json.dumps(reply([], err="Error: timeout")))))
    assert out["status"] == "error" and "register error" in out["reason"]


def test_not_json_is_error():
    out = gw.chain("Greenwood", "TAMBERLANE IVO R", session=PoliteSession(session=FakeHttp(api="<xml/>")))
    assert out["status"] == "error"


def test_empty():
    out = gw.chain("Greenwood", "NOBODY ATALL Q", session=PoliteSession(session=FakeHttp()))
    assert out["status"] == "not_found"


def test_challenge_walls_and_stops():
    http = FakeHttp(shell="<html><head><title>Just a moment...</title></head></html>")
    out = gw.chain("Greenwood", "TAMBERLANE IVO R", session=PoliteSession(session=http))
    assert out["status"] == "walled"
    assert gw.chain("Greenwood", "QUENBY MABEL S", session=PoliteSession(session=http))["status"] == "walled"
    assert len(http.calls) == 1


def test_other_county():
    assert asyncio.run(gw.search_by_name("SC", "Abbeville", "X Y")) == []
    with pytest.raises(KeyError):
        gw.chain("Abbeville", "X Y")
