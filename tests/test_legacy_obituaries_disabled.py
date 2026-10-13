"""national.legacy_obituaries: re-enabled 2026-10-13.

The scraper was disabled 2026-09-15 because the old search params
(`term=`, `countryId=1`, `stateId={state.lower()}`) were confirmed to not
scope results at all. Driving legacy.com's real search UI found the actual
params: `country`/`state`/`city`, all taking human-readable full names
(e.g. `?country=United+States&state=North+Carolina&city=Asheville`). Live
verification of all 19 `_CITIES` entries with the corrected params found
the fix overwhelmingly correct but not perfect (legacy.com's own facet has
a small real leak rate), so `_fetch_city` also does its own server-side
check per row -- see module docstring for the full live-verification
writeup. These tests exercise that logic without hitting the network:
real-shaped captures for the parsing path, synthetic-but-realistic cases
for the verify/drop logic specifically.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national import legacy_obituaries as m

# Real capture (2026-10-13, legacy.com/obituaries/search?country=United+States
# &state=North+Carolina&city=Asheville), trimmed of the Tailwind class soup
# but otherwise the real name/year/bio/publisher text and the real detail
# href -- the top real result for a correctly-scoped NC search.
ASHEVILLE_GOOD = """
<article data-testid="result-card-0">
  <a aria-label="View obituary details for Cheryl Francine Robinson (Morgan)"
     href="https://www.legacy.com/person/cheryl-francine-robinson-(morgan)-62643283">
    <div>Cheryl Francine Robinson (Morgan)</div>
    <span>1949 - 2026</span>
    <p>Cheryl Francine Morgan Robinson, 77, of Asheville, North Carolina, went
    home to be with her Lord and Savior on Thursday, October 8, 2026, leaving
    behind a beautiful legacy of faith, compassion, and unconditional love.</p>
  </a>
  <div>
    <a href="https://www.legacy.com/us/obituaries/828newsnow/name/cheryl-robinson-obituary?id=62738254">
      <span>828 News Now</span>
    </a>
  </div>
</article>
"""


def _page(*articles: str) -> str:
    return "<html><body>" + "\n".join(articles) + "</body></html>"


def test_enabled_now():
    assert m.LegacyObituariesScraper.disabled is False


def test_real_params_sent_are_the_verified_ones(monkeypatch):
    """The real finding: country/state take full names, not abbreviations
    or numeric IDs, and the city goes in a separate `city` param."""
    calls = []

    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        calls.append(url)
        return _page(ASHEVILLE_GOOD)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    asyncio.run(m.LegacyObituariesScraper()._fetch_city("Asheville", "NC"))
    assert len(calls) == 1
    assert "country=United+States" in calls[0]
    assert "state=North+Carolina" in calls[0]
    assert "city=Asheville" in calls[0]
    # Regression guard: the exact broken params from the old garbage-emitter
    # bug must never reappear.
    for dead_param in ("term=", "countryId=", "stateId=", "dateFrom="):
        assert dead_param not in calls[0]


def test_real_params_use_full_state_name_for_sc_too(monkeypatch):
    calls = []

    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        calls.append(url)
        return _page(ASHEVILLE_GOOD)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    asyncio.run(m.LegacyObituariesScraper()._fetch_city("Spartanburg", "SC"))
    assert "state=South+Carolina" in calls[0]
    assert "city=Spartanburg" in calls[0]


def test_parses_real_captured_result_and_marks_it_verified(monkeypatch):
    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        return _page(ASHEVILLE_GOOD)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    result = asyncio.run(m.LegacyObituariesScraper()._fetch_city("Asheville", "NC"))
    assert len(result) == 1
    row = result[0]
    assert row.city == "Asheville"
    assert row.state == "NC"
    assert row.owner_name  # _NAME_RE matched something real
    assert row.raw["legacy"]["verified"] is True
    assert row.raw["legacy"]["search_params"] == {
        "country": "United States", "state": "North Carolina", "city": "Asheville",
    }


def test_drops_row_that_explicitly_names_a_different_state(monkeypatch):
    """The real failure mode found live: legacy.com's own city/state facet
    occasionally lets through a result for a different state entirely. A
    row whose own text names a DIFFERENT state (and never mentions ours)
    must be rejected, not emitted as a North-Carolina-tagged lead."""
    wrong_state_row = """
    <article>
      <a aria-label="View obituary details for John Allen Peterson"
         href="https://www.legacy.com/person/john-allen-peterson-1">
        <div>John Allen Peterson</div>
        <span>1950 - 2026</span>
        <p>John Allen Peterson of Culpeper, Virginia, passed away peacefully
        at his home surrounded by family.</p>
      </a>
    </article>
    """

    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        return _page(wrong_state_row)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    result = asyncio.run(m.LegacyObituariesScraper()._fetch_city("Hendersonville", "NC"))
    assert result == []


def test_keeps_ambiguous_row_with_no_location_cue_but_flags_unverified(monkeypatch):
    """legacy.com's own preview snippets are short and often don't repeat
    the city/state at all -- that's not evidence of a wrong-state leak, so
    these rows are kept (the project's existing county cross-reference gate
    is the final arbiter) but tagged verified=False rather than silently
    treated the same as a confirmed match."""
    ambiguous_row = """
    <article>
      <a aria-label="View obituary details for Mary Ellen Carter"
         href="https://www.legacy.com/person/mary-ellen-carter-1">
        <div>Mary Ellen Carter</div>
        <span>1945 - 2026</span>
        <p>Mary Ellen Carter passed away peacefully on Tuesday surrounded by
        her loving family after a long illness. She will be remembered for
        her warmth, her generosity, and her devotion to her children and
        grandchildren. A celebration of her life will be held at a later
        date, details to be announced by the family in the coming days.</p>
      </a>
    </article>
    """  # padded past _fetch_city's own len(html) < 500 short-response guard

    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        return _page(ambiguous_row)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    result = asyncio.run(m.LegacyObituariesScraper()._fetch_city("Asheville", "NC"))
    assert len(result) == 1
    assert result[0].raw["legacy"]["verified"] is False


def test_fetch_iterates_cities_and_feeds_partial(monkeypatch):
    """fetch() must actually run now (not the old hardcoded `return []`),
    and -- per BaseScraper's partial-results convention -- append to
    self.partial as it goes so a mid-run timeout still ships collected rows."""
    monkeypatch.setattr(m, "_CITIES", [("Asheville", "NC"), ("Spartanburg", "SC")])

    calls = []

    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        calls.append(url)
        return _page(ASHEVILLE_GOOD)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    scraper = m.LegacyObituariesScraper()
    result = asyncio.run(scraper.fetch())
    result = list(result)
    assert len(calls) == 2
    assert len(result) == 2
    assert len(scraper.partial) == 2


def test_a_fetch_failure_on_one_city_does_not_drop_the_others(monkeypatch):
    monkeypatch.setattr(m, "_CITIES", [("Asheville", "NC"), ("Spartanburg", "SC")])

    async def fake_get_text_impersonate(url, *, timeout=30.0, **kw):
        if "Spartanburg" in url:
            raise RuntimeError("simulated network failure")
        return _page(ASHEVILLE_GOOD)

    monkeypatch.setattr(m, "get_text_impersonate", fake_get_text_impersonate)

    result = list(asyncio.run(m.LegacyObituariesScraper().fetch()))
    assert len(result) == 1
    assert result[0].city == "Asheville"
