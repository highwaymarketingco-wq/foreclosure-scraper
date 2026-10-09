"""publicnoticesc_estates: SC estate-notice grid previews. Made-up names; grid markup in the shape
_press_assoc.parse_grid reads (the live portal's nested-table rows)."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.public_notices import publicnoticesc_estates as est


def _row(nid: str, text: str, county: str = "Jasper") -> str:
    return (f'<table class="nested"><tr><td><input onclick="location.href=\'Details.aspx?SID=abc&ID={nid}\'"></td>'
            f'<td><div class="left"><strong>Test Gazette</strong><br>Thursday, October 1, 2026</div>'
            f'<div class="right" style="display:none">City: Ridgeland<br>County: {county}</div></td></tr>'
            f'<tr><td colspan="3">{text}... click \'view\' to open the full text.</td></tr></table>')


PAGE = ("<html><input type='hidden' name='__VIEWSTATE' value='v'/>"
        + _row("1", "STATE OF SOUTH CAROLINA COUNTY OF: JASPER IN THE MATTER OF: ORVEL QUIMBY TANDRY (DECEASED) IN THE "
                    "PROBATE COURT NOTICE TO CREDITORS CASE NUMBER: 2026-ES-27-09906 *NOTICE TO CREDITORS OF ESTATES All")
        + _row("2", "NOTICE TO CREDITORS OF ESTATES All persons having claims against the following estates MUST file")
        + _row("3", "NOTICE TO CREDITORS Estate: Vera Juno Samplecrisp Date of Death: 06/19/2026 Case Number: 2026ES4209923 "
                    "Personal Representative: Walter Samplecrisp", county="Spartanburg")
        + "</html>")


def test_parse_preview():
    a = est.parse_preview("STATE OF SOUTH CAROLINA COUNTY OF: JASPER IN THE MATTER OF: ORVEL QUIMBY TANDRY (DECEASED) "
                          "IN THE PROBATE COURT NOTICE TO CREDITORS CASE NUMBER: 2026-ES-27-09906")
    assert a == {"estate": "Orvel Quimby Tandry", "case_number": "2026ES2709906", "county": "Jasper"}
    b = est.parse_preview("NOTICE TO CREDITORS Estate: Vera Juno Samplecrisp Date of Death: 06/19/2026 Case Number: "
                          "2026ES4209923 Personal Representative: Walter Samplecrisp")
    assert b["county"] == "Spartanburg" and b["personal_representative"] == "Walter Samplecrisp"
    assert est.parse_preview("NOTICE TO CREDITORS OF ESTATES All persons having claims against") is None
    assert est.SC_COUNTY_CODES["27"] == "Jasper" and est.SC_COUNTY_CODES["39"] == "Pickens"
    assert est.SC_COUNTY_CODES["46"] == "York" and est.SC_COUNTY_CODES["04"] == "Anderson"


class Fake:
    def __init__(self):
        self.posts = []
        self.walled = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get_with_url(self, url):
        return "<html><input type='hidden' name='__VIEWSTATE' value='v'/></html>", "https://www.scpublicnotices.com/(S(x))/Search.aspx"

    async def post(self, url, data):
        self.posts.append(dict(data))
        return PAGE


def test_end_to_end(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(est, "PoliteFetcher", lambda: fake)
    s = est.PublicNoticeSCEstates()
    rows = asyncio.run(s.fetch())
    assert sorted((r.owner_name, r.county) for r in rows) == [("Orvel Quimby Tandry", "Jasper"),
                                                               ("Vera Juno Samplecrisp", "Spartanburg")]
    r = next(x for x in rows if x.county == "Jasper")
    assert r.raw["sc_probate_notice"]["case_number"] == "2026ES2709906"
    assert r.source_url.endswith("Details.aspx?ID=1")
    assert "preview_text" not in r.raw["public_notice"]
    presets = {p.get("ctl00$ContentPlaceHolder1$as1$ddlPopularSearches") for p in fake.posts}
    assert {"30", "23"} <= presets
    assert s.last_stats["Notice to Creditors"]["named"] == 2
