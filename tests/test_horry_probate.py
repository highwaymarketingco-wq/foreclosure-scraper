"""Horry County SC probate estates via the Spartan portal (hand-written rows).

Row keys and value shapes match the live grid answer read on 2026-10-07; every
name and case number below is made up.
"""
from __future__ import annotations

import asyncio
import json
import time

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc import horry_probate as mod

NOW = mod.datetime(2026, 10, 7)


def _row(case="2026ES2699001", name="TESTPERSON, ALEXANDRA Q", ptype="Deceased Person                         ",
         filed="09/15/2026"):
    return {"APPCODE": "26500", "CMSCASE": 999001.0, "WARANTNO": case, "CASENBR": "", "PROSCODE": "ZZZ",
            "CseFilDt": filed, "CseTypIn": "E", "PPTYSEQ": 1.0, "PPTYNAME": name,
            "PPTYLNAME": "TESTPERSON", "PPTYFNAME": "ALEXANDRA", "PROSNAME": "PLACEHOLDER, CLERK",
            "PPTYTYPE": ptype}


def _payload(rows, total):
    return {"d": json.dumps({"Error": None, "sEcho": 1, "recordsFiltered": total,
                             "recordsTotal": total, "aaData": rows})}


def test_row_becomes_a_probate_lead_for_the_decedent():
    li = mod.build_listing(_row(), now=NOW)
    assert li.listing_type == ListingType.PROBATE_NOTICE
    assert (li.state, li.county, li.case_number) == ("SC", "Horry", "2026ES2699001")
    assert li.owner_name == "TESTPERSON, ALEXANDRA Q"
    p = li.raw["probate"]
    assert p["filing_date"] == "2026-09-15" and p["party_type"] == "Deceased Person"
    assert "PROSNAME" not in repr(li.raw) and "PLACEHOLDER, CLERK" not in repr(li.raw)


def test_non_decedent_and_unnamed_rows_are_dropped():
    assert mod.build_listing(_row(ptype="Petitioner"), now=NOW) is None
    assert mod.build_listing(_row(name=""), now=NOW) is None


def test_search_params_match_the_grid_request():
    p = mod.search_params(2026, 500)
    assert p["CaseNumber"] == "2026ES26" and p["AgencyId"] == "26500"
    assert (p["iDisplayStart"], p["iDisplayLength"]) == ("500", "500")


def test_decode_handles_the_asmx_wrapper_and_junk():
    assert mod.decode(_payload([_row()], 1))["recordsTotal"] == 1
    assert mod.decode({"d": "not json"}) == {} and mod.decode([]) == {}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._p, self.status_code = payload, status_code

    def json(self):
        return self._p


class _Http:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if url == mod.PAGE_URL:
            return _Resp({})
        return self.pages.pop(0) if self.pages else _Resp(_payload([], 0))


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_pages_by_offset_dedupes_and_applies_the_lookback(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    monkeypatch.setattr(mod, "_PAUSE_S", 0)
    this_year = [_Resp(_payload([_row("2026ES2699001"), _row("2026ES2699002")], 3)),
                 _Resp(_payload([_row("2026ES2699002"), _row("2026ES2699003", filed="01/02/2024")], 3))]
    last_year = [_Resp(_payload([_row("2025ES2699004", filed="12/01/2025")], 1))]
    http = _Http(this_year + last_year)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    s = mod.HorryProbate()
    rows = asyncio.run(s.fetch())
    assert sorted(li.case_number for li in rows) == ["2025ES2699004", "2026ES2699001", "2026ES2699002"]
    data_calls = [c for c in http.calls if c[0] == mod.DATA_URL]
    assert [c[1]["CaseNumber"] for c in data_calls] == ["2026ES26", "2026ES26", "2025ES26"]


def test_future_filing_date_typo_is_blanked():
    li = mod.build_listing(_row(filed="06/01/3025"), now=NOW)
    assert li.raw["probate"]["filing_date"] is None


# --- per-case detail page (CaseDetailPage.aspx) -----------------------------
#
# Real trimmed captures, read live 2026-10-13 (source-completeness audit
# Pattern D) via plain httpx against scportal.hostedbyspartan.com -- names
# and case numbers are real public-record probate filings already indexed by
# the county's own search page.

# Case 2026ES2600001: decedent address blank ("&nbsp;"), one Personal
# Representative on the case.
_DETAIL_HTML_WITH_REP_NO_ADDRESS = """
<table><caption><h2>Primary Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th><th scope="col">Date of Death</th><th scope="col">Address</th>
</tr><tr class="gridItemNrm">
<td>Grainger, John Kevin</td><td>Deceased Person                         </td><td>7/9/2024</td><td>&nbsp;</td>
</tr></table>
<table><caption><h2>Case Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th>
</tr><tr class="gridItemNrm">
<td>Grainger, John Kevin</td><td>Deceased Person                         </td>
</tr><tr class="gridItemAlt">
<td>Grainger, Connor</td><td>Personal Representative                 </td>
</tr></table>
<h2>Scheduled Events</h2>
"""

# Case 2026ES2600002: decedent address blank, only an AFFIANT on the case
# (small-estate affidavit, no Personal Representative appointed) -- neither
# field should be extracted.
_DETAIL_HTML_NO_ADDRESS_NO_REP = """
<table><caption><h2>Primary Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th><th scope="col">Date of Death</th><th scope="col">Address</th>
</tr><tr class="gridItemNrm">
<td>Johnson, Lori Lynn</td><td>Deceased Person                         </td><td>1/1/2024</td><td>&nbsp;</td>
</tr></table>
<table><caption><h2>Case Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th>
</tr><tr class="gridItemNrm">
<td>Johnson, Lori Lynn</td><td>Deceased Person                         </td>
</tr><tr class="gridItemAlt">
<td>Johnson, Scott</td><td>AFFIANT                                 </td>
</tr></table>
<h2>Scheduled Events</h2>
"""

# Case 2025ES2600828: decedent address populated (real out-of-state example),
# Applicant + Attorney on the case but no Personal Representative yet.
_DETAIL_HTML_WITH_ADDRESS_NO_REP = """
<table><caption><h2>Primary Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th><th scope="col">Date of Death</th><th scope="col">Address</th>
</tr><tr class="gridItemNrm">
<td>Skory, Meriann Sue</td><td>Deceased Person                         </td><td>11/13/2008</td><td>18604 Stony Point Strongsville, OH 44136     </td>
</tr></table>
<table><caption><h2>Case Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th>
</tr><tr class="gridItemNrm">
<td>Skory, Meriann Sue</td><td>Deceased Person                         </td>
</tr><tr class="gridItemAlt">
<td>Skory, John Edward</td><td>Applicant                               </td>
</tr><tr class="gridItemNrm">
<td>Wilson, John Leonard</td><td>Attorney                                </td>
</tr></table>
<h2>Scheduled Events</h2>
"""

# Synthetic (not yet seen in the samples pulled live 2026-10-13, but
# "Co-Personal Representative" is a confirmed-live party TYPE value) --
# checks the substring match covers the "Co-" variant and that multiple
# representatives on one case are all captured.
_DETAIL_HTML_CO_REPS_SYNTHETIC = """
<table><caption><h2>Primary Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th><th scope="col">Date of Death</th><th scope="col">Address</th>
</tr><tr class="gridItemNrm">
<td>Example, Decedent</td><td>Deceased Person                         </td><td>1/1/2026</td><td>&nbsp;</td>
</tr></table>
<table><caption><h2>Case Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th>
</tr><tr class="gridItemNrm">
<td>Example, Decedent</td><td>Deceased Person                         </td>
</tr><tr class="gridItemAlt">
<td>Example, Co-Rep One</td><td>Co-Personal Representative              </td>
</tr><tr class="gridItemNrm">
<td>Example, Co-Rep Two</td><td>Co-Personal Representative              </td>
</tr></table>
<h2>Scheduled Events</h2>
"""


def test_detail_url_builds_from_the_grids_own_template():
    url = mod.detail_url("26500", 160275.0, 1.0)
    assert url == (mod.DETAIL_URL + "?AgencyId=26500&CaseId=160275&PartySeq=1")


def test_detail_url_returns_none_when_a_key_is_missing():
    assert mod.detail_url(None, 1, 1) is None
    assert mod.detail_url("26500", None, 1) is None
    assert mod.detail_url("26500", 1, None) is None
    assert mod.detail_url("26500", "not-a-number", 1) is None


def test_parse_detail_html_extracts_the_personal_representative():
    extras = mod._parse_detail_html(_DETAIL_HTML_WITH_REP_NO_ADDRESS)
    assert extras == {"personal_representatives": [{"name": "Grainger, Connor",
                                                      "role": "Personal Representative"}]}


def test_parse_detail_html_extracts_the_decedent_address():
    extras = mod._parse_detail_html(_DETAIL_HTML_WITH_ADDRESS_NO_REP)
    assert extras["decedent_address"] == "18604 Stony Point Strongsville, OH 44136"
    assert extras["mail_state"] == "OH"
    assert "personal_representatives" not in extras


def test_parse_detail_html_empty_when_neither_field_is_populated():
    """An AFFIANT-only small-estate case with a blank address cell must not
    fabricate either field."""
    assert mod._parse_detail_html(_DETAIL_HTML_NO_ADDRESS_NO_REP) == {}


def test_parse_detail_html_captures_multiple_co_representatives():
    extras = mod._parse_detail_html(_DETAIL_HTML_CO_REPS_SYNTHETIC)
    assert extras["personal_representatives"] == [
        {"name": "Example, Co-Rep One", "role": "Co-Personal Representative"},
        {"name": "Example, Co-Rep Two", "role": "Co-Personal Representative"},
    ]
    assert "decedent_address" not in extras


def test_parse_detail_html_handles_garbage_and_empty_input():
    assert mod._parse_detail_html("") == {}
    assert mod._parse_detail_html(None) == {}
    assert mod._parse_detail_html("<html>not a case detail page at all</html>") == {}


class _DetailResp:
    def __init__(self, text="", status_code=200):
        self.text, self.status_code = text, status_code


def test_fetch_detail_page_returns_empty_dict_on_non_200(monkeypatch):
    class _Http:
        async def get(self, url, headers=None):
            return _DetailResp(_DETAIL_HTML_WITH_REP_NO_ADDRESS, status_code=403)

    extras = asyncio.run(mod._fetch_detail_page(_Http(), "26500", 1, 1))
    assert extras == {}


def test_fetch_detail_page_returns_empty_dict_on_network_failure():
    class _Http:
        async def get(self, url, headers=None):
            raise RuntimeError("connection reset")

    extras = asyncio.run(mod._fetch_detail_page(_Http(), "26500", 1, 1))
    assert extras == {}


def test_fetch_detail_page_returns_empty_dict_when_url_cannot_be_built():
    extras = asyncio.run(mod._fetch_detail_page(object(), None, None, None))
    assert extras == {}


def test_fetch_detail_page_never_raises_even_on_parser_bug(monkeypatch):
    class _Http:
        async def get(self, url, headers=None):
            return _DetailResp(_DETAIL_HTML_WITH_REP_NO_ADDRESS)

    def _boom(html):
        raise ValueError("parser exploded")

    monkeypatch.setattr(mod, "_parse_detail_html", _boom)
    extras = asyncio.run(mod._fetch_detail_page(_Http(), "26500", 1, 1))
    assert extras == {}


def test_fetch_detail_page_parses_a_real_200(monkeypatch):
    class _Http:
        async def get(self, url, headers=None):
            assert url == mod.DETAIL_URL + "?AgencyId=26500&CaseId=160275&PartySeq=1"
            return _DetailResp(_DETAIL_HTML_WITH_REP_NO_ADDRESS)

    extras = asyncio.run(mod._fetch_detail_page(_Http(), "26500", 160275.0, 1.0))
    assert extras["personal_representatives"][0]["name"] == "Grainger, Connor"


def _probate_listing(**raw_probate_overrides) -> "mod.Listing":
    from datetime import datetime, timezone

    from foreclosure_scraper.models import Listing

    raw_probate = {"decedent": "Grainger, John Kevin", "case_number": "2026ES2600001",
                   "filing_date": "2025-12-30", "court": "Horry County Probate Court",
                   "party_type": "Deceased Person", "case_type": "E",
                   "detail_keys": {"agency": "26500", "case_id": 160275.0, "party_seq": 1.0},
                   "source": "horry_spartan_portal"}
    raw_probate.update(raw_probate_overrides)
    return Listing(
        source=mod.HorryProbate.slug, source_url=mod.PAGE_URL,
        listing_type=mod.ListingType.PROBATE_NOTICE, property_kind=mod.PropertyKind.UNKNOWN,
        state="SC", county="Horry", case_number="2026ES2600001",
        owner_name="Grainger, John Kevin",
        description="Horry County SC estate 2026ES2600001 opened 2025-12-30 for Grainger, John Kevin (deceased)",
        first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
        raw={"probate": raw_probate},
    )


def test_apply_detail_noop_on_empty_extras():
    li = _probate_listing()
    before = li.model_copy(deep=True)
    mod._apply_detail(li, {})
    assert li == before


def test_apply_detail_fills_owner_mailing_from_decedent_address():
    li = _probate_listing()
    extras = mod._parse_detail_html(_DETAIL_HTML_WITH_ADDRESS_NO_REP)
    mod._apply_detail(li, extras)
    om = li.raw["owner_mailing"]
    assert om["owner"] == "Grainger, John Kevin"          # li.owner_name, not the detail page's own name
    assert om["mailing"] == "18604 Stony Point Strongsville, OH 44136"
    assert om["situs"] is None
    assert om["mail_state"] == "OH"
    assert om["absentee"] is False
    assert om["out_of_state"] is True                      # OH != SC
    assert om["source"] == "horry_probate_detail"


def test_apply_detail_out_of_state_false_when_mail_state_is_sc():
    li = _probate_listing()
    extras = {"decedent_address": "123 Main St, Myrtle Beach, SC 29577", "mail_state": "SC"}
    mod._apply_detail(li, extras)
    assert li.raw["owner_mailing"]["out_of_state"] is False


def test_apply_detail_adds_personal_representatives_under_the_probate_block():
    li = _probate_listing()
    extras = mod._parse_detail_html(_DETAIL_HTML_WITH_REP_NO_ADDRESS)
    mod._apply_detail(li, extras)
    assert li.raw["probate"]["personal_representatives"] == [
        {"name": "Grainger, Connor", "role": "Personal Representative"}
    ]
    # the existing probate block's other fields are untouched
    assert li.raw["probate"]["decedent"] == "Grainger, John Kevin"
    assert "owner_mailing" not in li.raw


def test_apply_detail_sets_both_fields_when_both_are_present():
    li = _probate_listing()
    extras = {"decedent_address": "1 Elm St, Conway, SC 29526", "mail_state": "SC",
              "personal_representatives": [{"name": "Grainger, Connor", "role": "Personal Representative"}]}
    mod._apply_detail(li, extras)
    assert "owner_mailing" in li.raw and "personal_representatives" in li.raw["probate"]


# --- detail-fetch volume cap / time budget (HorryProbate._enrich_with_detail_pages) --

class _DetailHttp:
    """Fake session: PAGE_URL/DATA_URL answer empty so the list-fetch loop
    ends immediately; any CaseDetailPage.aspx URL is counted and answered
    with a fixed real-shaped detail page."""

    def __init__(self, detail_html=_DETAIL_HTML_WITH_REP_NO_ADDRESS):
        self.detail_html = detail_html
        self.detail_calls: list[str] = []

    async def get(self, url, params=None, headers=None):
        if url == mod.PAGE_URL:
            return _Resp({})
        if url == mod.DATA_URL:
            return _Resp(_payload([], 0))
        self.detail_calls.append(url)
        return _DetailResp(self.detail_html)


def _rows(n: int, start_case: int = 500000) -> list[dict]:
    return [_row(f"2026ES26{start_case + i:05d}") for i in range(n)]


def test_enrich_with_detail_pages_honours_the_fetch_cap(monkeypatch):
    monkeypatch.setattr(mod, "_DETAIL_PAUSE_S", 0)
    monkeypatch.setattr(mod, "DETAIL_FETCH_CAP", 2)
    now = mod.datetime(2026, 10, 13)
    listings = [mod.build_listing(r, now=now) for r in _rows(5)]
    http = _DetailHttp()
    s = mod.HorryProbate()
    asyncio.run(s._enrich_with_detail_pages(http, listings, fetch_start=time.monotonic()))
    assert len(http.detail_calls) == 2, "the cap must bound how many detail pages get fetched"
    assert len(listings) == 5, "the cap must never drop a listing, only limit enrichment"
    enriched = [li for li in listings if "personal_representatives" in li.raw.get("probate", {})]
    assert len(enriched) == 2


def test_enrich_with_detail_pages_honours_the_time_budget(monkeypatch):
    monkeypatch.setattr(mod, "_DETAIL_PAUSE_S", 0)
    now = mod.datetime(2026, 10, 13)
    listings = [mod.build_listing(r, now=now) for r in _rows(3)]
    http = _DetailHttp()
    s = mod.HorryProbate()
    s.timeout_s = 180.0
    # fetch_start far enough in the past that the budget is already spent.
    stale_start = time.monotonic() - 10_000
    asyncio.run(s._enrich_with_detail_pages(http, listings, fetch_start=stale_start))
    assert http.detail_calls == []
    assert len(listings) == 3, "an exhausted budget must still ship every listing"


def test_enrich_with_detail_pages_skips_rows_without_detail_keys(monkeypatch):
    monkeypatch.setattr(mod, "_DETAIL_PAUSE_S", 0)
    now = mod.datetime(2026, 10, 13)
    li = mod.build_listing(_row("2026ES2699999"), now=now)
    li.raw["probate"]["detail_keys"] = {"agency": None, "case_id": None, "party_seq": None}
    http = _DetailHttp()
    s = mod.HorryProbate()
    asyncio.run(s._enrich_with_detail_pages(http, [li], fetch_start=time.monotonic()))
    assert http.detail_calls == []


def test_enrich_with_detail_pages_never_drops_a_listing_on_fetch_error(monkeypatch):
    monkeypatch.setattr(mod, "_DETAIL_PAUSE_S", 0)

    async def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(mod, "_fetch_detail_page", _boom)
    now = mod.datetime(2026, 10, 13)
    listings = [mod.build_listing(r, now=now) for r in _rows(2)]
    s = mod.HorryProbate()
    asyncio.run(s._enrich_with_detail_pages(_DetailHttp(), listings, fetch_start=time.monotonic()))
    assert len(listings) == 2


def test_fetch_banks_partial_before_the_detail_pass_and_returns_enriched_rows(monkeypatch):
    """Integration: HorryProbate.fetch() must bank self.partial with every
    list-grid row before running detail enrichment, and the returned rows
    must carry whatever the (capped) detail pass filled in."""
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    monkeypatch.setattr(mod, "_PAUSE_S", 0)
    monkeypatch.setattr(mod, "_DETAIL_PAUSE_S", 0)
    pages = [_Resp(_payload([_row("2026ES2699001")], 1)), _Resp(_payload([], 0))]
    detail_calls: list[str] = []

    async def _get(url, params=None, headers=None):
        if url == mod.PAGE_URL:
            return _Resp({})
        if url == mod.DATA_URL:
            return pages.pop(0) if pages else _Resp(_payload([], 0))
        detail_calls.append(url)
        return _DetailResp(_DETAIL_HTML_WITH_REP_NO_ADDRESS)

    http = _DetailHttp()
    http.get = _get
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))

    s = mod.HorryProbate()
    rows = asyncio.run(s.fetch())
    assert [li.case_number for li in rows] == ["2026ES2699001"]
    assert len(s.partial) == 1
    assert len(detail_calls) == 1
    assert rows[0].raw["probate"]["personal_representatives"] == [
        {"name": "Grainger, Connor", "role": "Personal Representative"}
    ]
