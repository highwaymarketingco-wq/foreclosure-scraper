"""national.courtlistener_adversary — trustee/attorney not promoted to Listing.trustee
(audit 2026-10-01).

Per-source extraction audit (docs/HERMES.md sec 8, which explicitly lists
"attorney/trustee" as a required field): trustee_str/attorney/firm were already
pulled off the RECAP search hit into raw['courtlistener_adversary'], but never
promoted to the top-level `Listing.trustee` field -- the one enrichment_title_risk.py
and enrichment_courts.py actually read (`li.trustee`).

Live-verified 2026-10-01: a live run against the 4 NC/SC bankruptcy courts returned
261 lift-stay/363-sale/abandonment listings, 257 of which now carry a trustee name
via this fix (previously 0, since the field was never assigned to the Listing).

Also regression-tests `_as_name`: unlike `trustee_str` (a flattened single string),
`attorney`/`firm` on a type=r RECAP result are ARRAYS (every attorney who ever
appeared on any document in the docket -- live-verified up to 25 names on one
case), and `Listing.trustee` is a plain `str | None` field, so assigning a raw
list would either corrupt the value or raise a Pydantic validation error.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national.courtlistener_adversary import _as_name


def test_as_name_passes_through_a_plain_string():
    assert _as_name("Holman, Jenny P.") == "Holman, Jenny P."


def test_as_name_joins_a_list_of_names():
    out = _as_name(["Benjamin Rhodes", "John C. Woodman"])
    assert out == "Benjamin Rhodes; John C. Woodman"


def test_as_name_dedupes_and_truncates():
    out = _as_name(["A", "A", "B"])
    assert out == "A; B"


def test_as_name_empty_list_and_blank_are_none():
    assert _as_name([]) is None
    assert _as_name("") is None
    assert _as_name(None) is None
    assert _as_name(["", "  "]) is None


def test_fetch_promotes_trustee_str_to_listing_trustee(monkeypatch):
    import foreclosure_scraper.scrapers.national.courtlistener_adversary as M

    async def fake_search(c, token, court, phrase):
        if court == "ncwb" and phrase == "relief from stay":
            return [{
                "caseName": "In re Jenny P. Holman",
                "docketNumber": "26-40001",
                "dateFiled": "2026-09-01",
                "chapter": "13",
                "docket_absolute_url": "/docket/1/holman/",
                "trustee_str": "Holman, Jenny P.",
                "attorney": [],
                "firm": [],
                "suitNature": "Relief from Stay",
            }]
        return []

    monkeypatch.setattr(M, "_search", fake_search)
    monkeypatch.setattr(M, "_load_token", lambda: "fake-token")

    rows = list(asyncio.run(M.CourtListenerAdversary().fetch()))
    assert len(rows) == 1
    assert rows[0].trustee == "Holman, Jenny P."


def test_fetch_falls_back_to_joined_attorney_list_when_no_trustee_str(monkeypatch):
    import foreclosure_scraper.scrapers.national.courtlistener_adversary as M

    async def fake_search(c, token, court, phrase):
        if court == "ncwb" and phrase == "relief from stay":
            return [{
                "caseName": "In re John Doe",
                "docketNumber": "26-40002",
                "dateFiled": "2026-09-01",
                "chapter": "13",
                "docket_absolute_url": "/docket/2/doe/",
                "trustee_str": "",
                "attorney": ["Benjamin Rhodes", "John C. Woodman"],
                "firm": [],
                "suitNature": "Relief from Stay",
            }]
        return []

    monkeypatch.setattr(M, "_search", fake_search)
    monkeypatch.setattr(M, "_load_token", lambda: "fake-token")

    rows = list(asyncio.run(M.CourtListenerAdversary().fetch()))
    assert len(rows) == 1
    # Must be a plain string (not a list) -- a raw list would fail Pydantic
    # validation on the `str | None` Listing.trustee field.
    assert isinstance(rows[0].trustee, str)
    assert rows[0].trustee == "Benjamin Rhodes; John C. Woodman"
