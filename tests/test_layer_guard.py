"""LayerHarvest — the guard that turns a partial harvest into a hard failure.

WHY THESE TESTS EXIST:
    Two live sources were shipping fewer leads than they should because a
    single layer in a declared set died and the loop did ``except: continue``:

      * counties_sc.pickens_delinquent_parcels emitted 1,977 instead of 2,161
        (one of 8 GIS services retired). expected_min_count=1500 did not catch
        the 184-lead hole.
      * enrichment_helene_damage stamped 476 on one run and 521 on two others.

    A short return is indistinguishable from real-world shrinkage, which is the
    same reason the upset-bid outage hid for months. So the contract under test
    is: a declared layer that does not come back RAISES.

The failure bodies are SAVED FIXTURES captured verbatim from the live Pickens
GIS org, including the detail that matters most — a retired ArcGIS service
answers **HTTP 200** with an error object and no "features" key.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from foreclosure_scraper.arcgis_webmap import ArcGisError
from foreclosure_scraper.layer_guard import (
    LayerHarvest,
    PartialHarvest,
    arcgis_error,
    raise_for_arcgis_error,
)

from tests._arcgis_fakes import FakeHttp, FakeResponse

FIX = Path(__file__).parent / "fixtures"
RETIRED = json.loads((FIX / "arcgis_retired_service_error.json").read_text())
BAD_FIELDS = json.loads((FIX / "arcgis_bad_outfields_error.json").read_text())


async def _rows(n: int) -> list[int]:
    return list(range(n))


async def _boom(msg: str = "Invalid URL") -> list[int]:
    raise ArcGisError(msg)


# --------------------------------------------------------------------------
# The core contract
# --------------------------------------------------------------------------

def test_all_layers_alive_does_not_raise():
    async def go():
        g = LayerHarvest("src", ["a", "b", "c"])
        with g:
            for name in ("a", "b", "c"):
                assert await g.harvest(name, lambda: _rows(5)) == [0, 1, 2, 3, 4]
        return g

    g = asyncio.run(go())
    assert (g.live, g.declared, g.rows) == (3, 3, 15)


def test_one_dead_layer_raises_instead_of_returning_a_short_harvest():
    """The Pickens shape: 7 of 8 layers fine, the 8th retired."""
    async def go():
        g = LayerHarvest("counties_sc.pickens_delinquent_parcels",
                         [f"layer{i}" for i in range(8)], attempts=1)
        with g:
            for i in range(8):
                await g.harvest(
                    f"layer{i}",
                    (lambda: _boom()) if i == 7 else (lambda: _rows(400)))

    with pytest.raises(PartialHarvest) as ei:
        asyncio.run(go())
    msg = str(ei.value)
    # Names the source, the survivor count, AND the specific dead layer.
    assert "lost layer7" in msg
    assert "7/8 declared layers alive" in msg
    assert "Invalid URL" in msg
    # The rows it DID collect are named in the message precisely so nobody
    # mistakes the failure for "the source found nothing".
    assert "2800 rows discarded" in msg


def test_never_attempted_layer_is_caught_by_the_context_manager():
    """An early break/return out of the harvest loop is itself a silent loss."""
    async def go():
        g = LayerHarvest("src", ["a", "b", "c"])
        with g:
            for name in ("a", "b", "c"):
                await g.harvest(name, lambda: _rows(3))
                if name == "a":
                    break  # the shape that skips two layers with no error at all

    with pytest.raises(PartialHarvest) as ei:
        asyncio.run(go())
    assert "never attempted [b, c]" in str(ei.value)


def test_row_floor_catches_a_layer_that_answers_but_empties_out():
    async def go():
        g = LayerHarvest("src", {"a": 100})
        with g:
            await g.harvest("a", lambda: _rows(2))

    with pytest.raises(PartialHarvest) as ei:
        asyncio.run(go())
    assert "short [a returned 2 rows (floor 100)]" in str(ei.value)


def test_in_flight_exception_is_not_masked_by_the_guard():
    """A real error inside the block must surface as itself, not as a
    PartialHarvest raised from __exit__."""
    async def go():
        g = LayerHarvest("src", ["a", "b"])
        with g:
            await g.harvest("a", lambda: _rows(1))
            raise KeyError("the actual bug")

    with pytest.raises(KeyError):
        asyncio.run(go())


def test_tolerate_makes_a_known_dead_layer_an_explicit_exemption():
    async def go():
        g = LayerHarvest("src", ["a", "retired"], tolerate=["retired"], attempts=1)
        with g:
            await g.harvest("a", lambda: _rows(9))
            assert await g.harvest("retired", lambda: _boom()) == []
        return g

    g = asyncio.run(go())          # does not raise
    assert g.stats()["failed"] == ["retired"]


def test_undeclared_layer_is_a_wiring_bug():
    async def go():
        g = LayerHarvest("src", ["a"])
        await g.harvest("typo", lambda: _rows(1))

    with pytest.raises(ValueError, match="never declared"):
        asyncio.run(go())


def test_duplicate_declared_names_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        LayerHarvest("src", ["a", "a"])


def test_tolerate_must_name_a_declared_layer():
    with pytest.raises(ValueError, match="not declared layers"):
        LayerHarvest("src", ["a"], tolerate=["b"])


# --------------------------------------------------------------------------
# Retry: a transient blip must not be as fatal as a retired service
# --------------------------------------------------------------------------

def test_transient_failure_is_retried_then_counts_as_alive():
    """http_client is built with retries=0, so without this a one-off ReadError
    would fail the whole source. Observed live on spartanburg_assessments."""
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ArcGisError("ReadError")
        return [1, 2, 3]

    async def go():
        g = LayerHarvest("src", ["a"], attempts=2, retry_delay_s=0)
        with g:
            assert await g.harvest("a", flaky) == [1, 2, 3]
        return g

    g = asyncio.run(go())
    assert calls["n"] == 2 and g.live == 1


def test_persistent_failure_still_raises_after_exhausting_attempts():
    calls = {"n": 0}

    async def always_dead():
        calls["n"] += 1
        raise ArcGisError("Invalid URL")

    async def go():
        g = LayerHarvest("src", ["a"], attempts=3, retry_delay_s=0)
        with g:
            await g.harvest("a", always_dead)

    with pytest.raises(PartialHarvest):
        asyncio.run(go())
    assert calls["n"] == 3


def test_bare_coroutine_cannot_silently_skip_its_retries():
    async def go():
        g = LayerHarvest("src", ["a"], attempts=3)
        co = _rows(1)
        try:
            await g.harvest("a", co, attempts=2)   # not callable -> cannot retry
        finally:
            co.close()

    with pytest.raises(ValueError, match="zero-arg callable"):
        asyncio.run(go())


# --------------------------------------------------------------------------
# HTTP 200 + error body must never read as zero rows
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload,needle", [
    (RETIRED, "Invalid URL"),
    (BAD_FIELDS, "'outFields' parameter is invalid"),
])
def test_arcgis_error_body_detected(payload, needle):
    msg = arcgis_error(payload)
    assert msg and needle in msg
    with pytest.raises(ArcGisError):
        raise_for_arcgis_error("https://example/query", payload)


def test_clean_empty_payload_is_not_an_error():
    assert arcgis_error({"features": [], "exceededTransferLimit": False}) is None
    raise_for_arcgis_error("https://example/query", {"features": []})  # no raise


def test_query_features_raises_on_the_saved_retired_service_body():
    """The paginator is the central place this is handled; assert it against the
    real captured body rather than a hand-written stub."""
    from foreclosure_scraper import arcgis_webmap as agw

    http = FakeHttp(routes={"dqnt_2026": FakeResponse(RETIRED)})
    with pytest.raises(ArcGisError, match="Invalid URL"):
        asyncio.run(agw.query_features(
            http, "https://x/dqnt_2026/FeatureServer/0", out_fields="FID"))


# --------------------------------------------------------------------------
# End-to-end: the two sources the guard was applied to
#
# These drive the REAL fetch()/enrich() code paths against a fake transport in
# which exactly one declared layer is retired, serving the saved 200+error-body
# fixture. Before the guard both sources returned a plausible short harvest.
# --------------------------------------------------------------------------

import contextlib  # noqa: E402

from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _fake_client(http):
    @contextlib.asynccontextmanager
    async def _c(*a, **kw):
        yield http
    return _c


def _pickens_feature(pin: str, layer) -> dict:
    """One feature shaped for whichever column names that roll year uses."""
    attrs = {layer.pin: pin}
    if layer.owner:
        attrs[layer.owner] = "DOE, JANE"
    if layer.amount:
        attrs[layer.amount] = 1234.56
    if layer.situs:
        attrs[layer.situs] = "100 MAIN ST"
    return {"attributes": attrs, "geometry": {"rings": [[[-82.7, 34.9], [-82.7, 34.9]]]}}


def _pickens_routes(dead_service: str | None) -> dict:
    from foreclosure_scraper.scrapers.counties_sc import pickens_delinquent_parcels as pk

    routes = {}
    for i, layer in enumerate(pk.LAYERS):
        if layer.service == dead_service:
            routes[f"/{layer.service}/"] = RETIRED
            continue
        routes[f"/{layer.service}/"] = {
            "features": [_pickens_feature(f"4054-15-54-{3000 + i * 10 + j:04d}", layer)
                         for j in range(5)],
            "exceededTransferLimit": False,
        }
    return routes


def test_pickens_all_layers_alive_emits_every_parcel(monkeypatch):
    from foreclosure_scraper.scrapers.counties_sc import pickens_delinquent_parcels as pk

    http = FakeHttp(routes=_pickens_routes(None))
    monkeypatch.setattr(pk, "client", _fake_client(http))
    s = pk.PickensDelinquentParcels()
    out = asyncio.run(s.safe_run())
    assert s.last_outcome == "OK"
    assert len(out) == 5 * len(pk.LAYERS)          # 8 layers x 5 distinct PINs


def test_pickens_one_retired_service_fails_the_run_instead_of_shrinking_it(monkeypatch):
    """THE REGRESSION: this used to return 7/8 of the parcels and report OK.

    The retired service answers HTTP 200 with an error body (saved fixture), so
    there is no status code anywhere to notice — only the guard catches it.
    """
    from foreclosure_scraper.scrapers.counties_sc import pickens_delinquent_parcels as pk

    http = FakeHttp(routes=_pickens_routes("dqnt_2024"))
    monkeypatch.setattr(pk, "client", _fake_client(http))
    s = pk.PickensDelinquentParcels()
    out = asyncio.run(s.safe_run())

    # safe_run classifies the raise; the partial rows are NOT shipped.
    assert out == []
    assert s.last_outcome == "ERROR"
    # last_reason is truncated to 160 chars for the run report, so the dead
    # layer name has to survive that cut — that is the whole point of it.
    assert len(s.last_reason) <= 200
    assert "partial harvest" in s.last_reason
    assert "dqnt_2024" in s.last_reason
    assert "7/8 declared layers alive" in s.last_reason


def _helene_listing(parcel: str) -> Listing:
    return Listing(
        source="test", source_url="https://example/x",
        listing_type=ListingType.UNKNOWN,
        state="NC", county="Buncombe", parcel_id=parcel,
        street_address="100 MAIN ST",
    )


def test_helene_dead_layer_raises_instead_of_stamping_fewer_leads(monkeypatch):
    """THE REGRESSION: 476 stamps on one run, 521 on two others."""
    from foreclosure_scraper import enrichment_helene_damage as hd

    routes = {
        "NC_BuncombeCnty_PPDR": {"features": [
            {"attributes": {"pin": "9648123456", "Address": "100 MAIN ST",
                            "What_Service_are_you_Requesting": "Debris Removal",
                            "Was_this_Property_Residential_o": "Yes"}}],
            "exceededTransferLimit": False},
        # The placard layer is the one that dies, mid-harvest, with a 200.
        "HeleneCombinedDamageAssessmentResults": RETIRED,
        "Accela/MapServer/7": {"features": [
            {"attributes": {"pin": "9648123456", "DamageType": "DESTROYED"}}],
            "exceededTransferLimit": False},
    }
    monkeypatch.setattr(hd, "client", _fake_client(FakeHttp(routes=routes)))

    lis = [_helene_listing("9648123456")]
    with pytest.raises(PartialHarvest) as ei:
        asyncio.run(hd.enrich_with_helene_damage(lis))
    assert "buncombe_placards" in str(ei.value)
    # Nothing half-built leaks out onto the leads.
    assert "storm_damage" not in (lis[0].raw or {})


def test_helene_all_layers_alive_still_stamps(monkeypatch):
    from foreclosure_scraper import enrichment_helene_damage as hd

    routes = {
        "NC_BuncombeCnty_PPDR": {"features": [
            {"attributes": {"pin": "9648123456", "Address": "100 MAIN ST",
                            "What_Service_are_you_Requesting": "Demolition",
                            "Was_this_Property_Residential_o": "Yes"}}],
            "exceededTransferLimit": False},
        "HeleneCombinedDamageAssessmentResults": {"features": [
            {"attributes": {"pinnum": "9648123456", "structure_address": "100 MAIN ST",
                            "posting": "red", "primary_occupancy_type": "Residential",
                            "substantial_damage_determinatio": "yes"}}],
            "exceededTransferLimit": False},
        "Accela/MapServer/7": {"features": [
            {"attributes": {"pin": "9648123456", "DamageType": "DESTROYED"}}],
            "exceededTransferLimit": False},
    }
    monkeypatch.setattr(hd, "client", _fake_client(FakeHttp(routes=routes)))

    lis = [_helene_listing("9648123456")]
    stats = asyncio.run(hd.enrich_with_helene_damage(lis))
    assert stats["matched"] == 1
    assert lis[0].raw["storm_damage"]["damage_level"]


def test_helene_never_widens_outfields_to_star(monkeypatch):
    """The placard layer carries building_contact_info (owner phone + email).
    Routing through query_features must not have relaxed the enumerated-field
    rule, and the contact column must never be requested."""
    from foreclosure_scraper import enrichment_helene_damage as hd

    http = FakeHttp(routes={
        "NC_BuncombeCnty_PPDR": {"features": [], "exceededTransferLimit": False},
        "HeleneCombinedDamageAssessmentResults": {"features": [], "exceededTransferLimit": False},
        "Accela/MapServer/7": {"features": [], "exceededTransferLimit": False},
    })
    monkeypatch.setattr(hd, "client", _fake_client(http))
    asyncio.run(hd.enrich_with_helene_damage([_helene_listing("9648123456")]))

    assert http.calls, "no request was made"
    for _verb, _url, params in http.calls:
        fields = params.get("outFields", "")
        assert fields and fields != "*"
        assert "contact" not in fields.lower()
