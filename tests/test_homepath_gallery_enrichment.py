"""national.fannie_homepath + national.homepath_json: photo-gallery + agent-
contact enrichment, added 2026-10-13 (source-completeness audit, Pattern B).

Both scrapers' search-result JSON teaser (`_to_listing`) only ever carries
ONE photo (`primHiResImageUrl`) and no agent contact. Live-confirmed
2026-10-13 (plain httpx, no login/CAPTCHA/impersonation needed) against
Fannie Mae HomePath's own per-property detail endpoint
(``GET /cfl/property-inventory/property/{uuid}`` -- the SAME open JSON-XHR
endpoint ``enrichment_homepath_uuid.py`` already calls for uuid-liveness
checks): 3 real current NC/SC REO rows carried 30, 15 and 15 `propertyPics`
gallery images plus a real `brokerCompanies[].contacts[]` agent name/phone/
email, none of which either scraper captured.

Fixtures below mirror that real, live-confirmed response shape (trimmed to
the fields `_parse_gallery_and_agent` reads) rather than inventing a shape.

Both modules' fix is a line-for-line duplicate of the same small
`_parse_gallery_and_agent` / `_enrich_galleries` pair (see each module's own
comment on why: explicit sibling-independence, same precedent the modules
already set for the search-phase `_to_listing` duplication) -- so this file
covers both, module by module, rather than forcing a shared parametrization
that would imply a coupling the production code deliberately avoids.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.national import fannie_homepath as hp
from foreclosure_scraper.scrapers.national import homepath_json as hj


def _detail_payload(*, primary_url: str, extra_photos: int, agent: dict | None = None) -> dict:
    """A `/cfl/property-inventory/property/{uuid}` response, trimmed to the
    fields `_parse_gallery_and_agent` reads -- mirrors the real live shape
    (propertyPics[0] is always the same image as the search teaser's
    primHiResImageUrl, sequence 0, primary=True; see module docstring)."""
    pics = [{"fileId": None, "fileName": None, "imageUrl": primary_url,
             "sequence": 0, "primary": True}]
    for i in range(extra_photos):
        pics.append({
            "fileId": f"file-{i}",
            "fileName": f"REOImage_{i}.jpg",
            "imageUrl": f"https://homepath.fanniemae.com/images/f{i}/REOImage_{i}.jpg",
            "sequence": i + 1,
            "primary": False,
        })
    out: dict = {"propertyPics": pics}
    if agent is not None:
        out["brokerCompanies"] = [{
            "vendorUuid": "broker-1",
            "name": "Test Realty",
            "contacts": [{
                "contactUuid": "contact-1",
                "fullName": agent.get("name"),
                "phoneNumber": agent.get("phone"),
                "email": agent.get("email"),
            }],
        }]
    return out


class _FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Records every GET by uuid; `responses` maps uuid -> _FakeResp or an
    Exception instance to raise."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, url, headers=None, follow_redirects=True):
        uuid = url.rsplit("/", 1)[-1]
        self.calls.append(uuid)
        resp = self._responses.get(uuid)
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            return _FakeResp(status_code=404)
        return resp


def _listing_with_uuid(m, uuid: str, primary_url: str) -> Listing:
    """A Listing shaped exactly like each module's own `_to_listing` output:
    namespaced raw dict with property_uuid, plus the single teaser photo
    already in raw["images"]["real"]."""
    ns = "fannie_homepath" if m is hp else "homepath_json"
    return Listing(
        source=m.FannieHomePath.slug if m is hp else m.HomePathJSON.slug,
        source_url=f"https://homepath.fanniemae.com/property/{uuid}",
        listing_type=ListingType.REO,
        state="NC",
        street_address="1 Test St",
        case_number=f"fannie-{uuid}",
        raw={ns: {"property_uuid": uuid}, "images": {"real": [primary_url]}},
    )


# ---------------------------------------------------------------------------
# _parse_gallery_and_agent -- pure parsing, run against both modules.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("m", [hp, hj])
def test_parse_gallery_dedupes_and_caps(m):
    primary = "https://homepath.fanniemae.com/images/p/primary.jpg"
    # 12 real extra photos (exceeds MAX_GALLERY_PHOTOS=8) plus the primary
    # repeated once more later in the list, as the live API's own feed
    # structure does for sequence 0.
    data = _detail_payload(primary_url=primary, extra_photos=12)
    data["propertyPics"].append({"imageUrl": primary, "sequence": 99, "primary": False})

    photos, agent = m._parse_gallery_and_agent(data)

    assert photos[0] == primary
    assert len(photos) == len(set(photos)), "duplicate imageUrl must be deduped"
    assert len(photos) <= m.MAX_GALLERY_PHOTOS
    assert agent == {}


@pytest.mark.parametrize("m", [hp, hj])
def test_parse_gallery_extracts_agent_contact(m):
    data = _detail_payload(
        primary_url="https://homepath.fanniemae.com/images/p/primary.jpg",
        extra_photos=2,
        agent={"name": "JANE DOE", "phone": "8035550142", "email": "JANE@EXAMPLE.COM"},
    )

    photos, agent = m._parse_gallery_and_agent(data)

    assert len(photos) == 3
    assert agent == {"name": "JANE DOE", "phone": "8035550142", "email": "JANE@EXAMPLE.COM"}


@pytest.mark.parametrize("m", [hp, hj])
def test_parse_gallery_handles_missing_fields_without_crashing(m):
    photos, agent = m._parse_gallery_and_agent({})
    assert photos == []
    assert agent == {}

    # Malformed entries (not dicts) must be skipped, not raise.
    photos, agent = m._parse_gallery_and_agent(
        {"propertyPics": ["not-a-dict", None, 42], "brokerCompanies": ["not-a-dict"]}
    )
    assert photos == []
    assert agent == {}


@pytest.mark.parametrize("m", [hp, hj])
def test_parse_gallery_skips_contact_with_no_usable_field(m):
    """A contact dict present but with every field blank must not produce a
    truthy-but-empty agent dict."""
    data = {
        "propertyPics": [],
        "brokerCompanies": [{"contacts": [{"fullName": None, "phoneNumber": None, "email": None}]}],
    }
    photos, agent = m._parse_gallery_and_agent(data)
    assert agent == {}


# ---------------------------------------------------------------------------
# _enrich_galleries -- mutates Listing.raw in place via a fake async client.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_merges_gallery_and_agent_into_raw(m):
    primary = "https://homepath.fanniemae.com/images/p/primary.jpg"
    li = _listing_with_uuid(m, "uuid-1", primary)
    ns = li.raw and next(k for k in li.raw if k != "images")
    payload = _detail_payload(
        primary_url=primary, extra_photos=5,
        agent={"name": "JOHN ROE", "phone": "9195550198", "email": "JOHN@EXAMPLE.COM"},
    )
    client = _FakeClient({"uuid-1": _FakeResp(200, payload)})

    asyncio.run(m._enrich_galleries(client, [li], deadline=time.monotonic() + 30))

    real = li.raw["images"]["real"]
    assert real[0] == primary
    assert len(real) == 6  # primary + 5 new, no dupes
    assert len(real) == len(set(real))
    assert li.raw[ns]["agent"] == {
        "name": "JOHN ROE", "phone": "9195550198", "email": "JOHN@EXAMPLE.COM",
    }
    assert client.calls == ["uuid-1"]


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_caps_merged_total_at_max_gallery_photos(m):
    primary = "https://homepath.fanniemae.com/images/p/primary.jpg"
    li = _listing_with_uuid(m, "uuid-1", primary)
    payload = _detail_payload(primary_url=primary, extra_photos=29)  # real-world: 30 total
    client = _FakeClient({"uuid-1": _FakeResp(200, payload)})

    asyncio.run(m._enrich_galleries(client, [li], deadline=time.monotonic() + 30))

    assert len(li.raw["images"]["real"]) == m.MAX_GALLERY_PHOTOS


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_skips_listing_with_no_resolvable_uuid(m):
    li = Listing(
        source=m.FannieHomePath.slug if m is hp else m.HomePathJSON.slug,
        source_url="https://homepath.fanniemae.com/property/unknown",
        listing_type=ListingType.REO,
        state="NC",
        street_address="1 Test St",
        case_number="fannie-unknown",
        raw={"images": {"real": ["https://x/img.jpg"]}},
    )
    client = _FakeClient({})

    asyncio.run(m._enrich_galleries(client, [li], deadline=time.monotonic() + 30))

    assert client.calls == [], "a listing with no namespaced property_uuid must never trigger a fetch"
    assert li.raw["images"]["real"] == ["https://x/img.jpg"], "untouched"


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_continues_past_a_failed_fetch(m):
    primary1 = "https://homepath.fanniemae.com/images/a/1.jpg"
    primary2 = "https://homepath.fanniemae.com/images/b/1.jpg"
    li_fail = _listing_with_uuid(m, "uuid-fail", primary1)
    li_ok = _listing_with_uuid(m, "uuid-ok", primary2)
    payload_ok = _detail_payload(primary_url=primary2, extra_photos=3)
    client = _FakeClient({
        "uuid-fail": RuntimeError("connection reset"),
        "uuid-ok": _FakeResp(200, payload_ok),
    })

    asyncio.run(m._enrich_galleries(client, [li_fail, li_ok], deadline=time.monotonic() + 30))

    assert li_fail.raw["images"]["real"] == [primary1], "failed fetch must leave the row untouched"
    assert len(li_ok.raw["images"]["real"]) == 4, "a later row's success must not be blocked by an earlier failure"


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_skips_non_200_response(m):
    primary = "https://homepath.fanniemae.com/images/p/primary.jpg"
    li = _listing_with_uuid(m, "uuid-404", primary)
    client = _FakeClient({"uuid-404": _FakeResp(404, {})})

    asyncio.run(m._enrich_galleries(client, [li], deadline=time.monotonic() + 30))

    assert li.raw["images"]["real"] == [primary]


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_skips_unparseable_json(m):
    primary = "https://homepath.fanniemae.com/images/p/primary.jpg"
    li = _listing_with_uuid(m, "uuid-bad-json", primary)

    class _BadJsonResp:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    client = _FakeClient({"uuid-bad-json": _BadJsonResp()})

    asyncio.run(m._enrich_galleries(client, [li], deadline=time.monotonic() + 30))

    assert li.raw["images"]["real"] == [primary]


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_stops_at_an_already_passed_deadline(m):
    primary = "https://homepath.fanniemae.com/images/p/primary.jpg"
    li = _listing_with_uuid(m, "uuid-1", primary)
    payload = _detail_payload(primary_url=primary, extra_photos=5)
    client = _FakeClient({"uuid-1": _FakeResp(200, payload)})

    asyncio.run(m._enrich_galleries(client, [li], deadline=time.monotonic() - 1))

    assert client.calls == [], "a deadline already in the past must stop before the first fetch"
    assert li.raw["images"]["real"] == [primary]


@pytest.mark.parametrize("m", [hp, hj])
def test_enrich_galleries_partial_budget_still_enriches_earlier_rows(m):
    """A deadline that runs out partway through must still have enriched
    whatever rows it reached before cutoff -- mirrors freddie_homesteps.py's
    own budget-cutoff contract (ship what's done, skip the rest, never
    raise)."""
    primary1 = "https://homepath.fanniemae.com/images/a/1.jpg"
    primary2 = "https://homepath.fanniemae.com/images/b/1.jpg"
    li1 = _listing_with_uuid(m, "uuid-1", primary1)
    li2 = _listing_with_uuid(m, "uuid-2", primary2)
    payload1 = _detail_payload(primary_url=primary1, extra_photos=4)
    # deadline passes the instant _enrich_galleries checks it for the SECOND
    # row: give it a tiny positive budget and make the fake client sleep past it.
    deadline = time.monotonic() + 0.05

    class _SlowFakeClient(_FakeClient):
        async def get(self, url, headers=None, follow_redirects=True):
            await asyncio.sleep(0.1)
            return await super().get(url, headers=headers, follow_redirects=follow_redirects)

    client = _SlowFakeClient({"uuid-1": _FakeResp(200, payload1)})

    asyncio.run(m._enrich_galleries(client, [li1, li2], deadline=deadline))

    assert len(li1.raw["images"]["real"]) == 5, "the first row started before the deadline and must finish"
    assert li2.raw["images"]["real"] == [primary2], "the second row must be skipped once the deadline has passed"
