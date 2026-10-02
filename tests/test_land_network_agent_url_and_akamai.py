"""The Land.com-network scrapers (national.landwatch, national.landandfarm,
national.landsofamerica): 2026-10-01 national/reo per-source extraction audit.

1. All three share identical JSON-LD offers.offeredBy shape. Confirmed live:
   offeredBy never carries a telephone field anymore (not blank -- absent),
   but DOES carry a profile url (e.g. landwatch.com/profile/billy-may/332405)
   that none of the three captured. Zero-cost fix (already in the fetched
   JSON-LD): keep it in raw.*.agent_profile_url as a free, clickable path to
   the agent's own contact info when agent_phone comes back empty.

2. national.landsofamerica is confirmed live to be walled differently from
   its two siblings: land.com (not landwatch.com/landandfarm.com) serves a
   real Akamai Sensor interactive-challenge page, deterministically, on
   every county tested. The challenge page is ~2.6KB -- under the pre-
   existing `len(html) < 5000` generic short-page cutoff, which ran BEFORE
   the module's own _is_akamai_challenge() check and so always fired first,
   silently swallowing the walled response with no log signal at all. Fixed
   the ordering (challenge check first) and disabled the scraper (confirmed
   deterministic wall, not a fingerprint-only gate -- compliant to walk
   away from, not to push through).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import landandfarm as landandfarm_mod
from foreclosure_scraper.scrapers.national import landsofamerica as loa_mod
from foreclosure_scraper.scrapers.national import landwatch as landwatch_mod

_OFFERED_BY = {
    "@type": "Person",
    "name": "Billy May",
    "url": "https://www.landwatch.com/profile/billy-may/332405",
    "worksFor": {"@type": "Organization", "name": "KW Altamont Property Group"},
}


def _item(url: str) -> dict:
    return {
        "url": url,
        "name": "125 acres, 59 Pisgah Mountain Trail, Candler, NC 28715",
        "description": "125 acres recreational property",
        "contentLocation": {
            "address": {
                "streetAddress": "59 Pisgah Mountain Trail",
                "addressLocality": "Candler",
                "addressRegion": "NC",
                "postalCode": "28715",
            }
        },
        "offers": {"price": "1895000", "offeredBy": dict(_OFFERED_BY)},
        "image": "https://assets.example.com/1.jpg",
    }


def test_landwatch_captures_agent_profile_url_with_no_phone():
    li = landwatch_mod._parse_item(
        _item("https://www.landwatch.com/x/pid/1"), "national.landwatch"
    )
    assert li is not None
    raw = li.raw["landwatch"]
    assert raw["agent_phone"] is None
    assert raw["agent_profile_url"] == "https://www.landwatch.com/profile/billy-may/332405"


def test_landandfarm_captures_agent_profile_url_with_no_phone():
    li = landandfarm_mod._parse_item(
        _item("https://www.landandfarm.com/property/x-1"), "national.landandfarm"
    )
    assert li is not None
    raw = li.raw["landandfarm"]
    assert raw["agent_phone"] is None
    assert raw["agent_profile_url"] == "https://www.landwatch.com/profile/billy-may/332405"


def test_landsofamerica_captures_agent_profile_url_with_no_phone():
    li = loa_mod._parse_item(
        _item("https://www.land.com/x/pid/1"), "national.landsofamerica"
    )
    assert li is not None
    raw = li.raw["landsofamerica"]
    assert raw["agent_phone"] is None
    assert raw["agent_profile_url"] == "https://www.landwatch.com/profile/billy-may/332405"


# A trimmed but real capture of land.com's Akamai Sensor challenge page,
# 2026-10-01 -- well under 5000 bytes.
_AKAMAI_CHALLENGE_HTML = """
<html><head></head><body><script type="text/javascript" src="/w0fpPz/challenge?t=1"></script>
<div id="sec-if-cpt-container" role="main" style="display: none">
    <div class="behavioral-content">
        <div class="scf-akamai-logo-sec-abc">
            <div class="scf-akamai-logo-msg"><p class="scf-akamai-protected-by">Powered and protected by</p></div>
        </div>
    </div>
</div>
</body></html>
"""


def test_akamai_challenge_is_detected_as_such():
    assert loa_mod._is_akamai_challenge(_AKAMAI_CHALLENGE_HTML) is True


def test_fetch_county_logs_akamai_challenge_not_a_silent_generic_zero(monkeypatch):
    """Regression guard for the bug found 2026-10-01: the old code checked
    `len(html) < 5000` BEFORE _is_akamai_challenge(), and the real challenge
    page is ~2.6KB, so that generic short-page break always fired first and
    _is_akamai_challenge() was unreachable for the single most common
    failure shape. Confirms the reordering: a short challenge page must now
    be attributed to the challenge, not silently dropped."""
    class _FakeResult:
        body = _AKAMAI_CHALLENGE_HTML.encode("utf-8")

    class _FakeStealthyFetcher:
        @staticmethod
        async def async_fetch(*a, **kw):
            return _FakeResult()

    import sys
    import types

    fake_module = types.ModuleType("scrapling.fetchers")
    fake_module.StealthyFetcher = _FakeStealthyFetcher
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fake_module)

    logged = []
    monkeypatch.setattr(
        loa_mod.log, "warning",
        lambda event, **kw: logged.append((event, kw)),
    )

    out = asyncio.run(
        loa_mod._fetch_county("buncombe", "NC",
                              "https://www.land.com/buncombe-County-NC/all-land/",
                              "national.landsofamerica")
    )

    assert out == []
    assert any(event == "landsofamerica.akamai_challenge" for event, _ in logged), (
        f"expected an akamai_challenge warning, got log events: {[e for e, _ in logged]}")


def test_landsofamerica_disabled_and_dormant():
    assert loa_mod.LandsOfAmerica.disabled is True
    assert loa_mod.LandsOfAmerica.disabled_reason

    scraper = loa_mod.LandsOfAmerica()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()


def test_siblings_remain_active():
    """landwatch and landandfarm are NOT walled (confirmed live) and must
    stay enabled -- this is a targeted disable of landsofamerica only."""
    assert landwatch_mod.LandWatch.disabled is False
    assert landandfarm_mod.LandAndFarm.disabled is False
