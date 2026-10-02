"""reo.usda_rd: 2026-10-01 national/reo per-source extraction audit.

The results table's Photo cell (column 0) carries a real listing thumbnail
(<img src="https://www.resales.usda.gov.../SFH_INTRANET/....png">) that was
never captured, despite the table already being in hand (no extra request,
plain httpx -- not a stealth-browser detail-page cost like
national.crexi_multifamily). Confirmed live against a real SC result row.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from foreclosure_scraper.scrapers.reo import usda_rd as m

# A trimmed but real row, captured live 2026-10-01 against
# resales.usda.gov's SFH search for SC / Lexington county.
_REAL_TABLE_HTML = """
<table id="propertySummariesTable"><tbody>
<tr>
    <td>
        <a href="/resales/public/SFHPropertyDetail?id=7619&amp;listingType=Foreclosure">
            <img src="https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-1.png" height="60" width="80">
        </a>
        <br>
        <a href="/resales/public/SFHPropertyDetail?id=7619&amp;listingType=Foreclosure"><span>Details</span></a>
    </td>
    <td>Foreclosure</td>
    <td>341 Crestwood Arch<br><a href="https://maps.google.com/x">Map</a></td>
    <td>Lexington</td>
    <td>South Carolina</td>
    <td>Lexington</td>
    <td>29073</td>
    <td>$166,191</td>
    <td>3</td>
    <td>2</td>
    <td>1260</td>
</tr>
</tbody></table>
"""


def _row():
    return HTMLParser(_REAL_TABLE_HTML).css_first("#propertySummariesTable tbody tr")


def test_search_county_captures_photo_from_the_table_already_in_hand(monkeypatch):
    import asyncio

    class _FakeResp:
        status_code = 200
        text = _REAL_TABLE_HTML

    class _FakeClient:
        async def post(self, *a, **kw):
            return _FakeResp()

    out = asyncio.run(m._search_county(_FakeClient(), "SC", "SFH", "063"))
    assert len(out) == 1
    li = out[0]
    assert li.street_address == "341 Crestwood Arch"
    assert li.raw["images"] == {
        "real": ["https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-1.png"]
    }


def test_row_without_img_leaves_images_empty():
    html = _REAL_TABLE_HTML.replace(
        '<img src="https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-1.png" height="60" width="80">',
        "",
    )

    async def _run():
        class _FakeResp:
            status_code = 200
            text = html

        class _FakeClient:
            async def post(self, *a, **kw):
                return _FakeResp()

        return await m._search_county(_FakeClient(), "SC", "SFH", "063")

    import asyncio
    out = asyncio.run(_run())
    assert len(out) == 1
    assert "images" not in out[0].raw or out[0].raw["images"] == {}
