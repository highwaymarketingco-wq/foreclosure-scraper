"""Offline tests for the Gaston ROD lien-existence enricher (parser + classifier).

Uses a captured-shape DevExpress grid fixture so CI never hits the network.
"""
import pytest

from foreclosure_scraper import enrichment_gaston_rod as GR
from foreclosure_scraper.enrichment_gaston_rod import (
    parse_rows, classify, _body, _name_parts, _wall_reason, GastonWall,
    _seed, search_instruments, enrich_gaston_rod,
)

SAMPLE = """
<tr id="gridTrad_DXDataRow0" class="dxgvDataRow dx_grid_row">
<td class="dx_grid_cell Cell_Date dxgv" style="font-size:12pt;">01/02/2020</td>
<td class="dx_grid_cell Cell_Kind dxgv" style="font-size:12pt;">D/T</td>
<td class="dx_grid_cell Cell_Grantor dxgv" style="font-size:12pt;">COLONIAL OAKS APARTMENTS</td>
<td class="dx_grid_cell Cell_Grantee dxgv" style="font-size:12pt;">BANK OF AMERICA</td>
<td title="[ MTG ]" class="dx_grid_cell Cell_Description dxgv">[ MTG ]</td>
<td class="dx_grid_cell Cell_DocNo dxgv"><span class='pointer' onclick='x'>0001234567</span></td>
<td class="dx_grid_cell Cell_Book dxgv">5012</td>
<td class="dx_grid_cell Cell_Page dxgv">221</td>
</tr>
<tr id="gridTrad_DXDataRow1" class="dxgvDataRow dx_grid_row">
<td class="dx_grid_cell Cell_Date dxgv">03/04/2019</td>
<td class="dx_grid_cell Cell_Kind dxgv">DEED</td>
<td class="dx_grid_cell Cell_Grantor dxgv">SMITH JOHN</td>
<td class="dx_grid_cell Cell_Grantee dxgv">COLONIAL OAKS APARTMENTS</td>
<td class="dx_grid_cell Cell_Description dxgv">[ WD ]</td>
<td class="dx_grid_cell Cell_DocNo dxgv"><span>0001234500</span></td>
<td class="dx_grid_cell Cell_Book dxgv">4900</td>
<td class="dx_grid_cell Cell_Page dxgv">10</td>
</tr>
"""


def test_parse_rows():
    rows = parse_rows(SAMPLE)
    assert len(rows) == 2
    assert rows[0]["kind"] == "D/T"
    assert rows[0]["grantor"] == "COLONIAL OAKS APARTMENTS"
    assert rows[0]["grantee"] == "BANK OF AMERICA"
    assert rows[0]["book"] == "5012" and rows[0]["page"] == "221"
    assert rows[1]["kind"] == "DEED"


def test_classify_mortgage():
    c = classify(parse_rows(SAMPLE))
    assert c["instrument_count"] == 2
    assert c["has_mortgage"] is True          # D/T => deed of trust
    assert c["kinds"].get("D/T") == 1
    assert c["has_adverse_lien"] is False


def test_classify_adverse():
    c = classify([{"kind": "JUDG", "description": "TAX LIEN"}])
    assert c["has_adverse_lien"] is True
    assert "JUDG" in c["adverse_types"]


def test_parse_empty():
    assert parse_rows("") == []
    assert parse_rows("<html>Object reference not set</html>") == []


def test_name_parts():
    assert _name_parts("SMITH, JOHN") == ("SMITH", "JOHN")
    assert _name_parts("COLONIAL OAKS APARTMENTS") == ("COLONIAL OAKS APARTMENTS", "")


def test_body_encodes_name():
    b = _body("SMITH", "JOHN")
    assert "MultiNameLast%5B%5D=SMITH" in b
    assert "MultiNameGiven%5B%5D=JOHN" in b
    assert "MatchType=beginswith" in b
    assert "DXScript" not in b   # robust: no app-version tokens


def test_wall_reason_flags_a_block_status():
    assert _wall_reason(403, "") == "HTTP 403"
    assert _wall_reason(503, "") == "HTTP 503"
    assert _wall_reason(200, "") is None


def test_wall_reason_flags_a_cloudflare_challenge_page_even_on_200():
    assert _wall_reason(200, "<title>Just a moment...</title>") == "challenge, CAPTCHA or login page"
    assert _wall_reason(200, "<title>Attention Required! | Cloudflare</title>") is not None


class _FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    """A minimal stand-in for curl_cffi's AsyncSession: queued (status, text) replies."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        status, text = self._replies.pop(0)
        return _FakeResp(status, text)

    async def post(self, url, **kw):
        self.calls += 1
        status, text = self._replies.pop(0)
        return _FakeResp(status, text)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_seed_raises_gaston_wall_on_a_403_instead_of_reporting_success():
    s = _FakeSession([(403, "<title>Attention Required! | Cloudflare</title>"), (200, "")])
    with pytest.raises(GastonWall):
        await _seed(s)


@pytest.mark.asyncio
async def test_seed_returns_true_on_two_clean_gets():
    s = _FakeSession([(200, "ok"), (200, "ok")])
    assert await _seed(s) is True


@pytest.mark.asyncio
async def test_search_instruments_raises_gaston_wall_on_a_challenge_mid_run():
    s = _FakeSession([(403, "<title>Just a moment...</title>")])
    with pytest.raises(GastonWall):
        await search_instruments(s, "SMITH")


@pytest.mark.asyncio
async def test_search_instruments_still_treats_a_genuine_empty_result_as_no_rows():
    s = _FakeSession([(200, "<html>Object reference not set</html>")])
    assert await search_instruments(s, "SMITH") == []


@pytest.mark.asyncio
async def test_enrich_gaston_rod_stops_immediately_on_a_walled_seed(monkeypatch):
    from types import SimpleNamespace

    class _WalledSession(_FakeSession):
        async def get(self, url, **kw):
            self.calls += 1
            raise GastonWall("seed GET /: HTTP 403")

    monkeypatch.setattr(GR, "AsyncSession", lambda **kw: _WalledSession([]))
    monkeypatch.setenv("FORECLOSURE_GASTON_ROD", "1")
    li = SimpleNamespace(state="NC", county="Gaston", owner_name="SMITH, JOHN", raw={})
    stats = await enrich_gaston_rod([li])
    assert stats["error"] == "walled"
    assert "HTTP 403" in stats["wall_reason"]
    assert stats["searched"] == 0   # never attempted a single lookup once the seed was walled


@pytest.mark.asyncio
async def test_enrich_gaston_rod_stops_after_the_first_walled_lookup_not_the_whole_queue(monkeypatch):
    from types import SimpleNamespace

    class _SeedOkThenWalledSession:
        def __init__(self, **kw):
            self.gets = 0
            self.posts = 0

        async def get(self, url, **kw):
            self.gets += 1
            return _FakeResp(200, "ok")

        async def post(self, url, **kw):
            self.posts += 1
            return _FakeResp(403, "<title>Attention Required! | Cloudflare</title>")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(GR, "AsyncSession", _SeedOkThenWalledSession)
    monkeypatch.setenv("FORECLOSURE_GASTON_ROD", "1")
    targets = [SimpleNamespace(state="NC", county="Gaston", owner_name=f"SMITH, J{i}", raw={})
               for i in range(5)]
    stats = await enrich_gaston_rod(targets)
    assert stats["error"] == "walled"
    assert stats["searched"] == 0   # the wall hit on the very first lookup
    assert stats["targets"] == 5    # but the queue itself was never trimmed
