"""County-published owner-phone enricher — parcel keying, phone hygiene, privacy guard,
paging, the bridged second county, and the non-clobber contract.

Fully offline: the ArcGIS calls are served from saved fixtures through an httpx
MockTransport that honors the real request shape (POST body, orderByFields, resultOffset /
resultRecordCount, exceededTransferLimit), so the paging + IN-chunk logic is exercised for
real rather than stubbed out.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from foreclosure_scraper import enrichment_county_phone as cp
from foreclosure_scraper.models import Listing

_REAL_CLIENT = httpx.AsyncClient          # captured before any monkeypatching
FIX = Path(__file__).parent / "fixtures"
BUNCOMBE = json.loads((FIX / "buncombe_accela_owner_phone.json").read_text())
LINCOLN = json.loads((FIX / "lincoln_taxpayer_phone.json").read_text())

BUN_SPEC = cp.COUNTY_PHONE_SOURCES["NC:Buncombe"]
LIN_SPEC = cp.COUNTY_PHONE_SOURCES["NC:Lincoln"]
BUN_ROWS = [f["attributes"] for f in BUNCOMBE["features"]]


def _listing(**kw) -> Listing:
    base = dict(source="test", source_url="https://example.org/case/1", state="NC",
                county="Buncombe", street_address="1 Test St", city="Asheville")
    base.update(kw)
    return Listing(**base)


# ---------------------------------------------------------------- phone hygiene
@pytest.mark.parametrize("digits", [
    "8286289884", "7042749014", "8287830905",
])
def test_valid_nanp_accepts_real_numbers(digits):
    assert cp._valid_nanp(digits)


@pytest.mark.parametrize("digits", [
    "9999999999",   # county placeholder (live: Lincoln 999/999/9999)
    "0000000000",
    "1111111111",
    "1234567",      # too short
    "8289112345",   # N11 area code
    "8282111234",   # N11 exchange
    "1286289884",   # NPA starts with 1
    "8285550100",   # fictional 555-01xx range
])
def test_valid_nanp_rejects_junk(digits):
    assert not cp._valid_nanp(digits)


def test_clean_digits_strips_country_code_and_formatting():
    assert cp._clean_digits("1 (828) 628-9884") == "8286289884"
    assert cp._clean_digits(None) == ""


# ---------------------------------------------------------------- parcel keying
def test_key_variants_bridges_the_two_buncombe_parcel_forms():
    # Board carries both the bare 10-digit PIN and the Accela 15-digit card form.
    assert cp._key_variants("9713706531") == ["9713706531", "971370653100000"]
    assert cp._key_variants("971370653100000") == ["971370653100000", "9713706531"]
    assert cp._key_variants("06-05-026837-00000")[0] == "060502683700000"


def test_key_variants_rejects_useless_keys():
    assert cp._key_variants("") == []
    assert cp._key_variants("12") == []


def test_key_variants_does_not_strip_a_nonzero_card_suffix():
    # '...00001' is a real sub-card, not padding — must not collapse to the base.
    assert cp._key_variants("868587595400001") == ["868587595400001"]


# ---------------------------------------------------------------- privacy guard
def test_lincoln_config_never_requests_ssn_fields():
    """Lincoln's public taxpayer layer exposes TCSSN1/TCSSN2. The config must enumerate
    outFields and must not name them."""
    for spec in (LIN_SPEC, LIN_SPEC["bridge"]):
        fields = spec["out_fields"]
        assert "*" not in fields
        assert not [f for f in fields if "SSN" in f.upper()]


def test_out_fields_drops_sensitive_fields_even_if_a_config_asks():
    out = cp._out_fields({"out_fields": ["TCTXID", "TCSSN1", "TCSSN2", "TCDLC1", "TCNAM1"]})
    assert out == "TCTXID,TCNAM1"


def test_out_fields_refuses_wildcard():
    with pytest.raises(ValueError):
        cp._out_fields({"out_fields": ["*"]})
    with pytest.raises(ValueError):
        cp._out_fields({"out_fields": []})


def test_no_source_config_uses_a_wildcard():
    for spec in cp.COUNTY_PHONE_SOURCES.values():
        assert "*" not in spec["out_fields"]
        cp._out_fields(spec)  # must not raise


# ---------------------------------------------------------------- index build
def test_index_keys_exact_parcel_and_unambiguous_base():
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    # exact 15-digit key
    assert idx["060502683700000"]["phones"] == ["8286289884"]
    # unambiguous 10-digit base derived from it
    assert idx["0605026837"]["phones"] == ["8286289884"]
    assert idx["0605026837"]["_base_match"] is True


def test_index_skips_ambiguous_base_keys():
    """Two cards under one base with different phones — the base form must NOT resolve,
    or a 10-digit board parcel_id would get a coin-flip owner."""
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    assert "868587595400001" in idx and "868587595400002" in idx
    assert "8685875954" not in idx


def test_index_drops_placeholder_phone_rows_entirely():
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    assert "964809813900000" not in idx     # 999-999-9999 / 000-000-0000 only


def test_index_honors_the_active_owner_status_filter():
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    assert "060505914100000" not in idx     # OwnerStatus 'X'


def test_index_keeps_second_number_and_mailing_and_as_of():
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    rec = idx["971370653100000"]
    assert rec["phones"] == ["8282755283", "7042749014"]
    assert rec["mailing"] == "389 SUGAR HOLLOW RD FAIRVIEW NC 28730"
    assert rec["as_of"] == "2026-07-30"


def test_split_integer_phone_columns_are_zero_padded():
    """Lincoln stores area/exchange/line in three integer columns; TCPHON=905 is the
    4-digit line '0905', not a 3-digit number."""
    rows = [f["attributes"] for f in LINCOLN["taxpayer"]["features"]]
    idx = cp._index_rows(rows, LIN_SPEC)
    assert idx["0195049"]["phones"] == ["8287830905", "7042749014"]
    assert idx["0309770"]["phones"] == ["8014873801"]
    assert "0000001" not in idx     # 999/999/9999 placeholder


# ---------------------------------------------------------------- record shape
def test_record_carries_the_compliance_and_consumer_fields():
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    li = _listing(owner_name="DAVID MANLY", parcel_id="060502683700000")
    rec = cp._record(idx["060502683700000"], BUN_SPEC, li, "2026-08-03")
    # shape the dashboard + enrichment_line_type already consume
    assert rec["phone"] == "(828) 628-9884"
    assert rec["source"] == "buncombe_accela"
    assert rec["line_type"] == "unknown"
    # DNC/TCPA hygiene: county-published, never consented
    assert rec["needs_dnc_scrub"] is True
    assert rec["county_published"] is True
    assert rec["consent"] == "none"
    assert rec["confidence"] == "high" and rec["match"] == "parcel_id"
    assert rec["fetched"] == "2026-08-03" and rec["as_of"] == "2026-07-30"
    assert rec["owner_name_match"] is True


def test_base_match_is_downgraded_to_medium_confidence():
    idx = cp._index_rows(BUN_ROWS, BUN_SPEC)
    li = _listing(owner_name="DAVID MANLY", parcel_id="0605026837")
    rec = cp._record(idx["0605026837"], BUN_SPEC, li, "2026-08-03")
    assert rec["confidence"] == "medium" and rec["match"] == "parcel_id_base"


# ---------------------------------------------------------------- non-clobber
def test_attach_fills_an_empty_slot():
    li = _listing(parcel_id="060502683700000")
    counts = {"filled": 0, "alternates": 0, "confirmed_existing": 0}
    cp._attach(li, {"phone": "(828) 628-9884", "source": "buncombe_accela"}, counts)
    assert li.raw["owner_phone"]["source"] == "buncombe_accela"
    assert counts["filled"] == 1


def test_attach_never_overwrites_an_existing_voter_phone():
    li = _listing(parcel_id="060502683700000")
    li.raw = {"owner_phone": {"phone": "(828) 279-5724", "source": "ncsbe_voter",
                              "line_type": "wireless", "tcpa_class": "manual_only"}}
    counts = {"filled": 0, "alternates": 0, "confirmed_existing": 0}
    payload = cp._record(cp._index_rows(BUN_ROWS, BUN_SPEC)["060502683700000"],
                         BUN_SPEC, li, "2026-08-03")
    cp._attach(li, payload, counts)
    op = li.raw["owner_phone"]
    assert op["phone"] == "(828) 279-5724" and op["source"] == "ncsbe_voter"
    assert op["line_type"] == "wireless"          # line_type classification survives
    assert counts["filled"] == 0 and counts["alternates"] == 1
    alt = op["alternates"][0]
    assert alt["phone"] == "(828) 628-9884"
    assert alt["county_published"] is True and alt["consent"] == "none"
    assert alt["needs_dnc_scrub"] is True


def test_attach_records_agreement_as_corroboration_not_a_duplicate():
    li = _listing(parcel_id="060502683700000")
    li.raw = {"owner_phone": {"phone": "(828) 628-9884", "source": "ncsbe_voter"}}
    counts = {"filled": 0, "alternates": 0, "confirmed_existing": 0}
    cp._attach(li, {"phone": "(828) 628-9884", "source": "buncombe_accela"}, counts)
    assert counts["confirmed_existing"] == 1 and counts["alternates"] == 0
    assert li.raw["owner_phone"]["corroborated_by"] == ["buncombe_accela"]


def test_attach_is_idempotent_for_alternates():
    li = _listing(parcel_id="060502683700000")
    li.raw = {"owner_phone": {"phone": "(828) 279-5724", "source": "ncsbe_voter"}}
    counts = {"filled": 0, "alternates": 0, "confirmed_existing": 0}
    payload = {"phone": "(828) 628-9884", "source": "buncombe_accela", "match": "parcel_id",
               "confidence": "high", "county_published": True, "consent": "none",
               "needs_dnc_scrub": True, "fetched": "2026-08-03", "county_owner": None,
               "county_mailing": None}
    cp._attach(li, payload, counts)
    cp._attach(li, payload, counts)
    assert len(li.raw["owner_phone"]["alternates"]) == 1


# ---------------------------------------------------------------- transport / e2e
def _features(rows: list[dict]) -> list[dict]:
    return [{"attributes": r} for r in rows]


def _handler(request: httpx.Request) -> httpx.Response:
    """Serve the fixtures with real ArcGIS paging semantics."""
    body = parse_qs(request.content.decode())
    one = {k: v[0] for k, v in body.items()}
    host, path = request.url.host, request.url.path

    if "buncombenc" in host:
        # Layers with no OID reject paging without an explicit sort.
        assert one.get("orderByFields"), "paging without orderByFields would repeat page 1"
        rows = [r for r in BUN_ROWS if r.get("Phone")]
        offset = int(one.get("resultOffset", 0))
        count = int(one.get("resultRecordCount", 1000))
        page = rows[offset:offset + count]
        return httpx.Response(200, json={"features": _features(page),
                                         "exceededTransferLimit": offset + count < len(rows)})

    key_field = "PIN" if path.endswith("/1/query") else "TCTXID"
    table = LINCOLN["bridge"] if key_field == "PIN" else LINCOLN["taxpayer"]
    where = one.get("where", "")
    rows = [f["attributes"] for f in table["features"]
            if f"'{f['attributes'][key_field]}'" in where]
    return httpx.Response(200, json={"features": _features(rows),
                                     "exceededTransferLimit": False})


@pytest.fixture()
def offline(monkeypatch, tmp_path):
    """No network, no shared on-disk cache."""
    monkeypatch.setattr(cp, "_CACHE_DIR", tmp_path / "county_phone")

    def _factory(*_a, **_kw):
        return _REAL_CLIENT(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(cp.httpx, "AsyncClient", _factory)
    return tmp_path


@pytest.mark.asyncio
async def test_end_to_end_buncombe_pages_and_fills(offline):
    listings = [
        _listing(owner_name="DAVID MANLY", parcel_id="060502683700000"),
        _listing(owner_name="WILLIAM GALYEAN", parcel_id="9713706531"),   # base-form id
        _listing(owner_name="NOBODY", parcel_id="1111111111"),            # no county record
        _listing(owner_name="NO PARCEL"),                                 # not a target
        _listing(owner_name="OTHER COUNTY", county="Watauga", parcel_id="060502683700000"),
    ]
    stats = await cp.enrich_county_phone(listings)
    bun = stats["by_source"]["buncombe_accela"]
    assert bun["targets"] == 3 and bun["matched"] == 2
    assert stats["filled"] == 2

    assert listings[0].raw["owner_phone"]["phone"] == "(828) 628-9884"
    second = listings[1].raw["owner_phone"]
    assert second["phone"] == "(828) 275-5283"
    assert second["alt_phones"] == ["(704) 274-9014"]
    assert second["confidence"] == "medium"        # matched via the 10-digit base form
    assert not isinstance(listings[2].raw, dict) or "owner_phone" not in (listings[2].raw or {})
    assert not (listings[4].raw or {}).get("owner_phone")   # unconfigured county untouched


@pytest.mark.asyncio
async def test_end_to_end_lincoln_bridges_parcel_to_taxpayer(offline):
    listings = [
        _listing(county="Lincoln", owner_name="FEDERAL NATIONAL MORTGAGE",
                 parcel_id="3633246157"),
        _listing(county="Lincoln", owner_name="MORETZ AUSTIN", parcel_id="3602373054"),
        _listing(county="Lincoln", owner_name="PLACEHOLDER", parcel_id="3625271987"),
    ]
    stats = await cp.enrich_county_phone(listings)
    lin = stats["by_source"]["lincoln_taxpayer"]
    assert lin["targets"] == 3 and lin["matched"] == 2

    first = listings[0].raw["owner_phone"]
    assert first["phone"] == "(801) 487-3801"
    assert first["match"] == "parcel_id+ownerid"
    assert first["county_mailing"] == "PO BOX 650043 DALLAS TX 75265-0043"
    assert first["county_published"] is True and first["consent"] == "none"
    # Falls back to COOWNERID when OWNERID is blank.
    assert listings[1].raw["owner_phone"]["phone"] == "(828) 783-0905"
    # Taxpayer row exists but holds only a placeholder number -> no phone attached.
    assert not (listings[2].raw or {}).get("owner_phone")


@pytest.mark.asyncio
async def test_bulk_index_is_cached_between_runs(offline, monkeypatch):
    await cp.enrich_county_phone([_listing(parcel_id="060502683700000")])
    cache = offline / "county_phone" / "buncombe_accela.json"
    assert cache.exists()
    payload = json.loads(cache.read_text())
    assert "060502683700000" in payload["index"]

    calls: list[str] = []
    real = cp._fetch_bulk

    async def _spy(http, spec):
        calls.append(spec["source"])
        return await real(http, spec)

    monkeypatch.setattr(cp, "_fetch_bulk", _spy)
    li = _listing(parcel_id="060502683700000")
    await cp.enrich_county_phone([li])
    assert calls == []                                  # served from cache
    assert li.raw["owner_phone"]["phone"] == "(828) 628-9884"


@pytest.mark.asyncio
async def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_COUNTY_PHONE", "0")
    assert "skipped" in await cp.enrich_county_phone([_listing(parcel_id="060502683700000")])


@pytest.mark.asyncio
async def test_arcgis_200_with_error_body_is_not_silently_empty(monkeypatch, tmp_path):
    """ArcGIS answers bad requests with HTTP 200 + {"error": ...}. Treating that as an empty
    result set is how a source dies silently — it must raise."""
    monkeypatch.setattr(cp, "_CACHE_DIR", tmp_path / "county_phone")

    def _bad(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 400, "message": "Pagination request requires either orderBy field"}})

    monkeypatch.setattr(cp.httpx, "AsyncClient",
                        lambda *a, **k: _REAL_CLIENT(transport=httpx.MockTransport(_bad)))
    with pytest.raises(RuntimeError, match="arcgis error 400"):
        async with _REAL_CLIENT(transport=httpx.MockTransport(_bad)) as http:
            await cp._query(http, "https://example.org/x/MapServer/6", {"where": "1=1"})

    # …and a failing source degrades the run instead of killing it.
    li = _listing(parcel_id="060502683700000")
    stats = await cp.enrich_county_phone([li])
    assert "error" in stats["by_source"]["buncombe_accela"]
    assert stats["filled"] == 0
