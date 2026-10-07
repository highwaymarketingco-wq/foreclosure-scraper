"""Offline tests for the GovOS/Kofile PublicSearch reader (rod/publicsearch.py).

The fixtures are hand-written replies in the shape the live socket sends (checked 2026-10-07 on
Greenville and Oconee SC); every name, book and page in them is made up."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.rod import publicsearch as ps
from foreclosure_scraper.rod import sc_chain, sc_polite
from foreclosure_scraper.rod.sc_polite import PoliteSession, RodWalled


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sc_polite.reset_walled()
    sc_polite.BUDGET.reset()
    sc_chain.clear_cache()
    monkeypatch.setattr(sc_polite, "SLEEP", lambda s: None)
    yield
    sc_polite.reset_walled()
    sc_polite.BUDGET.reset()


def ps_doc(i, day, label, code, grantors, grantees, vol, page, remarks=()):
    return {"id": i, "recordedDate": day, "docType": label, "docTypeCode": code, "book": "DE",
            "volume": vol, "page": page, "bookVolumePage": f"DE/{vol}/{page}", "instrumentNumber": f"2026{i:06d}",
            "grantor": list(grantors) + [""], "grantee": list(grantees) + [""], "remarks": list(remarks),
            "ocrText": "PRIVATE OCR TEXT", "thumbnail": "/files/x.png", "downloadLink": "/files/documents/1"}


def reply(corr, docs, total=None):
    return {"type": ps.FULFILLED, "correlationId": corr,
            "payload": {"meta": {"numRecords": len(docs) if total is None else total},
                        "data": {"byOrder": [d["id"] for d in docs], "byHash": {str(d["id"]): d for d in docs}}}}


OWNER_DOCS = [
    ps_doc(1, "3/14/2022", "DEED", "DEED", ["MARIGOLD PETRA J"], ["<em>THISTLEDOWN</em> AMOS K"], "2701", "88",
           ["Subdivision: HAZEL KNOLL", "Free Form Legal: LT 12"]),
    ps_doc(2, "3/14/2022", "MORTGAGE", "MTG", ["THISTLEDOWN AMOS K"], ["TESTBANK OF NOWHERE NA"], "5501", "12"),
    ps_doc(3, "5/1/2025", "SATISFACTION OF MORTGAGE", "SAT/MTG", ["THISTLEDOWN AMOS K"], ["TESTBANK OF NOWHERE NA"],
           "470", "33"),
]
SELLER_DOCS = [
    ps_doc(4, "8/30/2015", "QUIT-CLAIM DEED", "QCD", ["MARIGOLD OREN"], ["MARIGOLD PETRA J"], "2400", "7",
           ["Free Form Legal: LT 12 HAZEL KNOLL"]),
]


class FakeSocket:
    def __init__(self):
        self.queries = []

    def ask(self, query):
        self.queries.append(query)
        parties = json.loads(query["parties"])
        (role, items), = parties.items()
        term = items[0]["term"]
        if term == "THISTLEDOWN AMOS":
            return reply("c", OWNER_DOCS)
        if term == "MARIGOLD PETRA" and role == "grantee":
            return reply("c", SELLER_DOCS)
        return reply("c", [])

    def close(self):
        pass


def test_parse_doc_keeps_index_fields_only():
    d = ps.parse_doc(OWNER_DOCS[0], "Greenville", "SC")
    assert d.book == "2701" and d.page == "88" and d.doc_type == "DEED"
    assert d.recorded_date.year == 2022 and d.recorded_date.month == 3
    assert d.grantee == "THISTLEDOWN AMOS K"                  # <em> and '' sentinel gone
    assert d.notes == "Subdivision: HAZEL KNOLL; Free Form Legal: LT 12"
    assert "ocrText" not in json.dumps(d.raw) and "PRIVATE OCR TEXT" not in json.dumps(d.raw)
    assert d.raw["doc_type_code"] == "DEED"


def test_parse_reply_empty():
    docs, total = ps.parse_reply(reply("c", []), "Greenville", "SC")
    assert docs == [] and total == 0


def test_parse_reply_error_and_wall():
    with pytest.raises(RuntimeError):
        ps.parse_reply({"type": "@kofile/FETCH_DOCUMENTS_REJECTED/v1", "payload": {"error": "bad query"}},
                       "Greenville", "SC")
    with pytest.raises(RodWalled):
        ps.parse_reply({"type": "@kofile/ERROR", "payload": {"message": "captcha required"}}, "Greenville", "SC")


def test_build_query_roles_and_sort():
    cfg = ps.PUBLICSEARCH_COUNTIES[("SC", "greenville")]
    q = ps.build_query(cfg, "THISTLEDOWN AMOS", "grantee", None, 100, 0)
    assert json.loads(q["parties"]) == {"grantee": [{"term": "THISTLEDOWN AMOS", "types": ["grantee"]}]}
    assert q["sort"] == "desc" and q["sortBy"] == "recordedDate"
    both = ps.build_query(cfg, "X Y", "both", None, 100, 0)
    assert json.loads(both["parties"])["parties"][0]["types"] == ["grantor", "grantee"]
    assert both["recordedDateRange"].startswith("17870101,")


def test_chain_over_canned_socket():
    sock = FakeSocket()
    out = ps.chain("Greenville", "THISTLEDOWN AMOS K", socket=sock)
    assert out["platform"] == "govos_publicsearch"
    assert out["last_deed"]["book"] == "2701" and out["last_deed"]["description"].endswith("LT 12")
    assert out["prior_instruments"][0]["book"] == "2400"
    assert out["prior_instruments"][0]["type"] == "QUIT-CLAIM DEED"
    assert len(out["liens"]["deeds_of_trust"]) == 1 and len(out["liens"]["satisfactions"]) == 1
    assert out["liens"]["open_deeds_of_trust_est"] == 0
    assert out["status"] == "ok"


def test_chain_empty_register():
    class Empty(FakeSocket):
        def ask(self, query):
            return reply("c", [])
    out = ps.chain("Oconee", "THISTLEDOWN AMOS K", socket=Empty())
    assert out["last_deed"] is None and out["prior_instruments"] == [] and out["status"] == "not_found"


class _Resp:
    def __init__(self, text, status=200):
        self.status_code, self.text, self.url, self.headers = status, text, "https://greenville.sc.publicsearch.us/", {}


class _Http:
    def __init__(self, text, status=200):
        self.text, self.status, self.calls = text, status, 0
        self.cookies = {}

    def request(self, method, url, **kw):
        self.calls += 1
        return _Resp(self.text, self.status)


def test_challenge_page_marks_walled_and_stops():
    http = _Http("<html><head><title>Just a moment...</title></head></html>")
    sock = ps._Socket("greenville.sc.publicsearch.us", session=PoliteSession(session=http),
                      connect=lambda *a, **k: pytest.fail("must not open the socket past a wall"))
    out = ps.chain("Greenville", "THISTLEDOWN AMOS K", socket=sock)
    assert out["status"] == "walled" and out["reason"] == "challenge page"
    assert sc_polite.walled_reason("SC", "Greenville") == "challenge page"
    again = ps.chain("Greenville", "THISTLEDOWN AMOS K", socket=sock)
    assert again["status"] == "walled"
    assert http.calls == 1                                    # never retried


def test_error_page_is_not_a_wall():
    http = _Http("<html>500 Internal Server Error</html>", status=500)
    sock = ps._Socket("oconee.sc.publicsearch.us", session=PoliteSession(session=http),
                      connect=lambda *a, **k: pytest.fail("no socket without a token"))
    out = ps.chain("Oconee", "THISTLEDOWN AMOS K", socket=sock)
    assert out["status"] == "error" and out["reason"].startswith("fetch failed")


def test_socket_refusal_403_is_a_wall():
    class Refused(Exception):
        def __init__(self):
            self.response = type("R", (), {"status_code": 403})()
    http = _Http("<html>app</html>")
    http.cookies = {"authToken": "anon-visitor", "authToken.sig": "sig"}

    def connect(*a, **k):
        raise Refused()
    sock = ps._Socket("oconee.sc.publicsearch.us", session=PoliteSession(session=http), connect=connect)
    out = ps.chain("Oconee", "THISTLEDOWN AMOS K", socket=sock)
    assert out["status"] == "walled" and out["reason"] == "HTTP 403 on the socket"


def test_search_by_name_interface(monkeypatch):
    monkeypatch.setattr(ps, "_Socket", lambda host: FakeSocket())
    docs = asyncio.run(ps.search_by_name("SC", "Greenville", "THISTLEDOWN AMOS K", max_docs=2))
    assert len(docs) == 2 and docs[0].recorded_date >= docs[1].recorded_date
    assert asyncio.run(ps.search_by_name("SC", "Spartanburg", "THISTLEDOWN AMOS K")) == []
