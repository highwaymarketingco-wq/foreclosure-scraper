"""Anderson County SC ACPASS deed-search (POA + COURT ORDER) extraction.

Fixtures below are trimmed excerpts of REAL markup captured live 2026-10-01
from acpass.andersoncountysc.org/deedmain.cgi, dedtypen.cgi, and
deddetail1.cgi (QryType=195 COURT ORDER and QryType=020 POA). No network
calls in these tests -- see HERMES.md section 7 for the separate live
fetch() verification run (50 real Listings, logged in the commit).

Confirms:
  - the row parser survives the real tag-soup `<font>`/`<div>` table layout
  - pagination cursor extraction, including the real page's malformed
    (missing-opening-quote) `instrnon` hidden field
  - a "finite" (no More button) result page returns no cursor
  - detail-page party/description/image extraction
  - code 195 rows mentioning HEIR classify as ESTATE_LEAD; other 195
    descriptions and all 020 rows stay UNKNOWN
  - 020's subject name is the GRANTOR (principal), not the GRANTEE (agent)
  - institutional parties (the probate court) are excluded from the subject
    name on a COURT ORDER
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc.anderson_acpass_deeds import (
    CODES,
    AndersonAcpassDeeds,
    _build_listing,
    _parse_cursor,
    _parse_detail,
    _parse_search_rows,
    _subject_names,
)

# Two COURT ORDER rows, real structure (one heir order, one not), finite
# page (no trailing "More" form -- no instrnon field at all).
COURT_ORDER_PAGE = """
<table width="100%" border="1" cellpadding="0" cellspacing="0" bordercolor="#003300">
  <tr>
    <td><div align="center"><font face="Arial, Helvetica">
        <input type="checkbox" name="instryearnbr" value="L2023239990001">
        </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr=L2023239990001">239990001</a></font></td>
    <td><div align="center">COURT ORDER</div></td>
    <td colspan="2"><div align="center"><font size="2" face="Arial, Helvetica">3/21/2023</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">19991&nbsp;&nbsp;00011
        </font></div></td>
    <td colspan="2"><div align="center"><font color="#000000" size="2" face="Arial, Helvetica">&nbsp;<strong>ORDER ESTABLISHING HEIRS
        </strong> </font> </div>
      <div align="center"></div></td>
  </tr>
  <tr>
    <td><div align="center"><font face="Arial, Helvetica">
        <input type="checkbox" name="instryearnbr" value="L2023230007259">
        </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr=L2023230007259">230007259</a></font></td>
    <td><div align="center">COURT ORDER</div></td>
    <td colspan="2"><div align="center"><font size="2" face="Arial, Helvetica">3/29/2023</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">16686&nbsp;&nbsp;00078
        </font></div></td>
    <td colspan="2"><div align="center"><font color="#000000" size="2" face="Arial, Helvetica">&nbsp;<strong>ORDER
        </strong> </font> </div>
      <div align="center"></div></td>
  </tr>
</table>
"""

# One POA row, followed by the real (malformed) "More" paging form --
# instrnon's value attribute is missing its opening quote in the live page.
POA_PAGE_WITH_CURSOR = """
<table width="100%" border="1" cellpadding="0" cellspacing="0" bordercolor="#003300">
  <tr>
    <td><div align="center"><font face="Arial, Helvetica">
        <input type="checkbox" name="instryearnbr" value="L2024249990002">
        </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr=L2024249990002">249990002</a></font></td>
    <td><div align="center">POA</div></td>
    <td colspan="2"><div align="center"><font size="2" face="Arial, Helvetica">1/02/2024</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">19992&nbsp;&nbsp;00022
        </font></div></td>
    <td colspan="2"><div align="center"><font color="#000000" size="2" face="Arial, Helvetica">&nbsp;<strong>DURABLE POWER OF ATTORNEY
        </strong> </font> </div>
      <div align="center"></div></td>
  </tr>
  <tr>
    <td height="32" colspan="8"><div align="center">
        <INPUT name="image" TYPE="image" SRC="/images/show.gif" onClick="submitFunction(2)">
        <INPUT name="image" type="image" SRC="/images/more.gif" value="LAST&gt;&gt;" onClick="submitFunction(3)">
        <input name="searchtype" type="hidden" value="L">
        <input name="searchinstr" type="hidden" value="020">
        <input name="searchbegdate" type="hidden" value="20240101">
        <input name="searchenddate" type="hidden" value="20261001">
        <input name="daten" type="hidden" value="20240109">
        <input name="instrnon" type="hidden" value=240000520">
    </div></td>
  </tr>
</table>
"""

COURT_ORDER_DETAIL = """
HISTORY DETAIL
Inst #:
2023 239990001
File
Date:
3/21/2023  16:03:50
Amount:
Type:
COURT ORDER
Book/Page:
19991   00011
Last
Modified:
4/24/2023
:
SAMPLE, CORA
GRANTOR
:
SAMPLE, CORA
GRANTEE
:
TESTER, MIA
GRANTOR
:
TESTER, MIA
GRANTEE
:
ANDERSON COUNTY PROBATE COURT
GRANTOR
:
ANDERSON COUNTY PROBATE COURT
GRANTEE
DESCRIPTION
ORDER ESTABLISHING HEIRS
<a href="/pgms/rvimain.pgm?RQSTYP=IMAGEV&RQSDTA=ZZZZ0001&DELTYP=P&HOST=acpass.andersoncountysc.org&">IMAGES</a>
View Images
Legal Disclaimer
"""

POA_DETAIL = """
HISTORY DETAIL
Inst #:
2024 249990002
File
Date:
1/02/2024  14:30:34
Amount:
Type:
POA
Book/Page:
19992   00022
Last
Modified:
1/02/2024
:
EXAMPLE, TED WILLIAM
GRANTOR
:
EXAMPLE, TERESA LANE
GRANTEE
DESCRIPTION
DURABLE POWER OF ATTORNEY
<a href="/pgms/rvimain.pgm?RQSTYP=IMAGEV&RQSDTA=ZZZZ0002&DELTYP=P&HOST=acpass.andersoncountysc.org&">IMAGES</a>
View Images
Legal Disclaimer
"""


def test_codes_are_the_two_scoped_instrument_types():
    assert CODES == {"020": "POA", "195": "COURT ORDER"}


def test_parse_search_rows_court_order():
    rows = _parse_search_rows(COURT_ORDER_PAGE)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["instr_key"] == "L2023239990001"
    assert r0["instr_no"] == "239990001"
    assert r0["type"] == "COURT ORDER"
    assert r0["file_date"] == "3/21/2023"
    assert r0["book"] == "19991"
    assert r0["page"] == "00011"
    assert r0["description"] == "ORDER ESTABLISHING HEIRS"
    assert r0["detail_url"].endswith("instryearnbr=L2023239990001")
    assert rows[1]["description"] == "ORDER"


def test_parse_search_rows_poa():
    rows = _parse_search_rows(POA_PAGE_WITH_CURSOR)
    assert len(rows) == 1
    assert rows[0]["type"] == "POA"
    assert rows[0]["description"] == "DURABLE POWER OF ATTORNEY"


def test_parse_cursor_present_despite_malformed_attribute():
    """The real page's instrnon value is missing its opening quote; the
    cursor parser must still recover a usable value for the next POST."""
    cursor = _parse_cursor(POA_PAGE_WITH_CURSOR)
    assert cursor == {
        "searchtype": "L",
        "searchinstr": "020",
        "searchbegdate": "20240101",
        "searchenddate": "20261001",
        "daten": "20240109",
        "instrnon": "240000520",
    }


def test_parse_cursor_absent_on_finite_page():
    """COURT ORDER's page in this fixture has no 'More' form -- no cursor."""
    assert _parse_cursor(COURT_ORDER_PAGE) is None


def test_parse_detail_court_order_parties_and_description():
    detail = _parse_detail(COURT_ORDER_DETAIL)
    assert detail["description"] == "ORDER ESTABLISHING HEIRS"
    roles = {(p["name"], p["role"]) for p in detail["parties"]}
    assert ("SAMPLE, CORA", "GRANTOR") in roles
    assert ("SAMPLE, CORA", "GRANTEE") in roles
    assert ("ANDERSON COUNTY PROBATE COURT", "GRANTOR") in roles
    assert detail["image_url"] == (
        "https://acpass.andersoncountysc.org/pgms/rvimain.pgm?"
        "RQSTYP=IMAGEV&RQSDTA=ZZZZ0001&DELTYP=P&HOST=acpass.andersoncountysc.org&"
    )


def test_parse_detail_poa():
    detail = _parse_detail(POA_DETAIL)
    assert detail["description"] == "DURABLE POWER OF ATTORNEY"
    assert {"name": "EXAMPLE, TED WILLIAM", "role": "GRANTOR"} in detail["parties"]
    assert {"name": "EXAMPLE, TERESA LANE", "role": "GRANTEE"} in detail["parties"]


def test_subject_names_excludes_institutional_parties():
    parties = [
        {"name": "SAMPLE, CORA", "role": "GRANTEE"},
        {"name": "ANDERSON COUNTY PROBATE COURT", "role": "GRANTEE"},
        {"name": "TESTER, MIA", "role": "GRANTOR"},
    ]
    names = _subject_names(parties, ("GRANTEE", "GRANTOR"))
    assert names == ["SAMPLE, CORA", "TESTER, MIA"]


def test_build_listing_heir_order_is_estate_lead():
    rows = _parse_search_rows(COURT_ORDER_PAGE)
    detail = _parse_detail(COURT_ORDER_DETAIL)
    li = _build_listing("counties_sc.anderson_acpass_deeds", "195", "COURT ORDER", rows[0], detail)
    assert li.listing_type == ListingType.ESTATE_LEAD
    assert li.state == "SC" and li.county == "Anderson"
    assert li.property_kind == PropertyKind.UNKNOWN
    assert li.case_number == "239990001"
    # The probate court (institutional, appears as both GRANTOR and GRANTEE)
    # must not be picked as the subject name.
    assert "PROBATE" not in (li.owner_name or "")
    assert "SAMPLE, CORA" in li.owner_name
    assert li.raw["anderson_acpass"]["type_code"] == "195"
    assert li.raw["anderson_acpass"]["image_url"]


def test_build_listing_non_heir_court_order_is_unknown():
    rows = _parse_search_rows(COURT_ORDER_PAGE)
    li = _build_listing("counties_sc.anderson_acpass_deeds", "195", "COURT ORDER", rows[1], {})
    assert li.listing_type == ListingType.UNKNOWN


def test_build_listing_poa_uses_grantor_as_subject():
    rows = _parse_search_rows(POA_PAGE_WITH_CURSOR)
    detail = _parse_detail(POA_DETAIL)
    li = _build_listing("counties_sc.anderson_acpass_deeds", "020", "POA", rows[0], detail)
    assert li.listing_type == ListingType.UNKNOWN
    # GRANTOR (the principal) is the subject, not GRANTEE (the agent).
    assert li.owner_name == "EXAMPLE, TED WILLIAM"
    assert "LAWSON" not in li.owner_name


def test_scraper_is_registered():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {c.slug for c in discover()}
    assert "counties_sc.anderson_acpass_deeds" in slugs


def test_slug_is_dateless_ok():
    """These instruments carry a FILE date, not a scheduled sale date --
    without the whitelist entry, main._active_only() drops every row."""
    from foreclosure_scraper.main import DATELESS_OK_SOURCES
    assert AndersonAcpassDeeds.slug in DATELESS_OK_SOURCES


def test_raw_key_is_in_raw_keep():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "anderson_acpass" in RAW_KEEP


# --- run shape (2026-10-08 TIMEOUT with 0 rows on the VM) -------------------
# Made-up rows and parties only; no network.

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime as _dt

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.counties_sc import anderson_acpass_deeds as _mod

_FAKE_DETAIL = ("<table><tr><td>EXAMPLE PERSON ONE</td><td>GRANTOR</td></tr>"
                "<tr><td>EXAMPLE PERSON TWO</td><td>GRANTEE</td></tr>"
                "<tr><td>DESCRIPTION</td><td>ORDER DETERMINING HEIRS</td></tr></table>")


class _FakeResp:
    status_code = 200
    text = _FAKE_DETAIL


class _FakeClient:
    async def get(self, url, **kw):
        return _FakeResp()


@asynccontextmanager
async def _fake_client(**kw):
    yield _FakeClient()


def _fake_rows(code: str, n: int) -> list[dict]:
    return [{"instr_key": f"L2026{code}{i:05d}", "instr_no": f"{code}{i:05d}", "type": CODES[code],
             "file_date": "10/01/2026", "book": "1", "page": str(i), "description": "ORDER DETERMINING HEIRS",
             "detail_url": f"https://example.invalid/deddetail1.cgi?instryearnbr=L2026{code}{i:05d}"}
            for i in range(n)]


def test_court_order_first_and_poa_reads_a_recent_window(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def fake_fetch(c, code, from_str, to_str):
        span = (_dt.strptime(to_str, "%m/%d/%Y") - _dt.strptime(from_str, "%m/%d/%Y")).days
        calls.append((code, span))
        return _fake_rows(code, 2)

    monkeypatch.setattr(_mod, "client", _fake_client)
    monkeypatch.setattr(_mod, "_fetch_type_code", fake_fetch)
    rows = asyncio.run(AndersonAcpassDeeds().fetch())
    assert [c for c, _ in calls] == ["195", "020"]
    assert calls[0][1] == 730
    assert calls[1][1] == _mod._LOOKBACK_DAYS_BY_CODE["020"] <= 60
    assert len(rows) == 4
    assert rows[0].listing_type == ListingType.ESTATE_LEAD
    assert rows[0].owner_name == "EXAMPLE PERSON TWO; EXAMPLE PERSON ONE"


def test_timeout_ships_rows_already_built(monkeypatch):
    async def fake_fetch(c, code, from_str, to_str):
        if code == "020":
            await asyncio.sleep(30)  # the slow POA sweep the soft timeout cuts
        return _fake_rows(code, 3)

    monkeypatch.setattr(_mod, "client", _fake_client)
    monkeypatch.setattr(_mod, "_fetch_type_code", fake_fetch)
    s = AndersonAcpassDeeds()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == OUTCOME_PARTIAL
    assert len(rows) == 3
    assert all(li.raw["anderson_acpass"]["type_code"] == "195" for li in rows)
