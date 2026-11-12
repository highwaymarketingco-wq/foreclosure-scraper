"""obituary_lookup: lead-driven Echovita / Find a Grave name searches. Made-up names, hand-written
markup modelled on the live pages (2026-10-07). No network."""
from __future__ import annotations

import asyncio

from foreclosure_scraper import obituary_lookup as ol
from foreclosure_scraper.enrichment_obituary_match import match_rows
from foreclosure_scraper.heirs_store import LookupLog, ObituaryStore
from foreclosure_scraper.quiet_title.fetch import Walled

FAG_USA = '<a href="/cemetery-browse/USA/North-Carolina?id=state_29">NC</a><a href="/cemetery-browse/USA/South-Carolina?id=state_43">SC</a>'
FAG_NC = '<a href="/cemetery-browse/USA/North-Carolina/Buncombe-County?id=county_1661">Buncombe</a>'
FAG_SC = '<a href="/cemetery-browse/USA/South-Carolina/Oconee-County?id=county_2349">Oconee</a>'
FAG_SEARCH = """<!-- Memorial search result list begins -->
<div class="memorial-item px-2 row" id="sr-111"><a href="/memorial/111/orvel-q-tandry">
<h2 class="name-grave d-flex"><i class="pe-2 text-break">Orvel Quimby Tandry</i></h2>
<b class="birthDeathDates fw-light">2 Mar 1942 &ndash; 28 Sep 2026</b></a>
<div class="memorial-item---cemet"><form action="/cemetery/1/x"><button>Pine Cemetery</button></form>
<p class="addr-cemet mb-1">Weaverville, Buncombe County, North Carolina, USA</p></div></div>
<div class="memorial-item px-2 row" id="sr-222"><a href="/memorial/222/orvel-b-tandry">
<h2 class="name-grave d-flex"><i class="pe-2 text-break">Orvel Baxter Tandry</i></h2>
<b class="birthDeathDates fw-light">1901 &ndash; 1970</b></a>
<div class="memorial-item---cemet"><p class="addr-cemet mb-1">Arden, Buncombe County, North Carolina, USA</p></div></div>
<!-- Memorial search result list ends -->"""
FAG_MEMORIAL = """<span itemprop="birthDate">2 Mar 1942</span><span itemprop="deathDate">28 Sep 2026</span>
<p itemprop="description">Orvel was a carpenter. He is survived by his wife, Lunetta Brask Tandry, and a son,
Corwin Tandry.</p><div id="family-grid"><b id="parentsLabel" class="label-relation">Parents</b>
<ul class="member-family"><li><h3 itemprop="name">Amos Tandry</h3><span itemprop="deathDate">1980</span></li></ul></div>"""
ECHO_SEARCH = """<a class="text-name-obit-in-list text-color-default" href="/us/obituaries/nc/weaverville/orvel-tandry-1" title="Read the obituary of Orvel Q. Tandry">x</a>
<p><a class="text-primary" title="Obituaries - Weaverville, North Carolina" href="/us/obituaries/nc/weaverville">W</a></p>
<p><span class="my-auto">1942 - 2026</span><span class=" ml-1">(84 years old)</span></p></div>"""
ECHO_OBIT = """<script type="application/ld+json">{"@type":"Person","name":"Orvel Q. Tandry","birthDate":"1942-03-02",
"deathDate":"2026-09-28"}</script><div id="obituary" class="ObituaryDescText"><h1>Orvel Q. Tandry</h1>
<p>He is survived by his wife of 61 years, Lunetta Brask Tandry; and a daughter, Wynnie Tandry Holcomb.</p></div>"""


class Fake:
    def __init__(self, walled_hosts=()):
        self.calls = []
        self.walled_hosts = walled_hosts
        self.walled = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None, content_rx=None):
        self.calls.append((url, params))
        for h in self.walled_hosts:
            if h in url:
                raise Walled(url, "HTTP 429")
        if url.endswith("/cemetery-browse/USA?id=country_4"):
            return FAG_USA
        if "North-Carolina?id=" in url:
            return FAG_NC
        if "South-Carolina?id=" in url:
            return FAG_SC
        if url.endswith("/memorial/search"):
            return FAG_SEARCH
        if "/memorial/111/" in url:
            return FAG_MEMORIAL
        if "echovita.com/us/obituaries/nc/" in url and "?q=" in url:
            return ECHO_SEARCH if "weaverville" in url or "asheville" in url else "<html></html>"
        if "orvel-tandry-1" in url:
            return ECHO_OBIT
        return "<html></html>"


def _lead(owner="TANDRY ORVEL QUIMBY HEIRS"):
    return {"source": "counties_nc.buncombe_tax", "source_url": "https://county.test/p/1", "listing_type": "tax_lien",
            "owner_name": owner, "county": "Buncombe", "state": "NC", "city": "Weaverville", "parcel_id": "1", "raw": {}}


def test_parsers():
    cards = ol.parse_fag_search(FAG_SEARCH)
    assert [c["name"] for c in cards] == ["Orvel Quimby Tandry", "Orvel Baxter Tandry"]
    assert "Buncombe County" in cards[0]["cemetery_place"]
    m = ol.parse_fag_memorial(FAG_MEMORIAL)
    assert m["death_date"] == "28 Sep 2026" and "Corwin" in m["bio"]
    assert m["family"] == [{"relation": "parents", "name": "Amos Tandry", "death_date": "1980"}]


def test_lookup_finds_matches_and_never_repeats(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    store = ObituaryStore(tmp_path).load()
    lg = LookupLog(tmp_path).load()
    lead, alive = _lead(), _lead("TANDRY ORVEL QUIMBY")          # the second has no death signal
    fake = Fake()
    st = asyncio.run(ol.lookup_leads([lead, alive], limit=5, store=store, log_store=lg, fetcher_factory=lambda: fake))
    assert st["leads_searched"] == 1                              # only the dead-owner lead is searched
    urls = {r["url"] for r in store.values()}
    assert "https://www.findagrave.com/memorial/111/orvel-q-tandry" in urls
    assert "https://www.findagrave.com/memorial/222/orvel-b-tandry" not in urls   # middle name differs
    assert "https://www.echovita.com/us/obituaries/nc/weaverville/orvel-tandry-1" in urls
    fag = store.records["https://www.findagrave.com/memorial/111/orvel-q-tandry"]
    assert [s["name"] for s in fag["survivors"]] == ["Lunetta Brask Tandry", "Corwin Tandry"]
    assert fag["family_memorials"] == 1 and "family" not in fag  # dead relatives: counted only
    search = [p for u, p in fake.calls if u.endswith("/memorial/search")][0]
    assert search["locationId"] == "county_1661" and search["middlename"] == "Quimby"
    # both records are the same death (same full name and death date): one attached match
    match_rows([lead], store.values())
    assert lead["raw"]["obituary_match"]["status"] == "attached"
    # a second run within the TTL does not search again
    fake2 = Fake()
    st2 = asyncio.run(ol.lookup_leads([_lead()], limit=5, store=store, log_store=LookupLog(tmp_path).load(),
                                      fetcher_factory=lambda: fake2))
    assert st2["skipped_recent"] == 1 and st2["leads_searched"] == 0


def test_a_walled_source_stops_and_the_other_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    store = ObituaryStore(tmp_path).load()
    fake = Fake(walled_hosts=("echovita.com",))
    st = asyncio.run(ol.lookup_leads([_lead(), _lead("TANDRY ORVEL Q HEIRS")], limit=5, store=store,
                                     log_store=LookupLog(tmp_path).load(), fetcher_factory=lambda: fake))
    assert st["walled"] == {"echovita": "HTTP 429"}
    echo_calls = [u for u, _ in fake.calls if "echovita" in u]
    assert len(echo_calls) == 1                                    # never asked again after the wall
    assert any("findagrave" in r["url"] for r in store.values())
