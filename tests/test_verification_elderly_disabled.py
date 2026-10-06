"""elderly_disabled (Buncombe NC) against the live sweep's OWN responses (2026-10-06): the county
parcel layer's JSON, tax.buncombenc.gov parcel and bill pages, and the NCSBE voter search results,
names pseudonymized (first letter kept), voter ids / zips replaced
(tests/fixtures/verification/elderly_disabled_cases.json.gz). No network."""
from __future__ import annotations

import asyncio
import gzip
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from foreclosure_scraper import enrichment_nc_voter_lookup as V
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import elderly_disabled as e

FIX = Path(__file__).parent / "fixtures" / "verification" / "elderly_disabled_cases.json.gz"


@lru_cache(maxsize=1)
def fixture() -> dict:
    return json.loads(gzip.decompress(FIX.read_bytes()))


def case(name: str) -> dict:
    return fixture()["cases"][name]


class Replay(ReplayFetcher):
    """ReplayFetcher plus the recorded voter searches, keyed LAST|FIRST."""

    def __init__(self, responses: dict, voter: dict | None = None) -> None:
        super().__init__(responses)
        self.voter = dict(voter or {})
        self.voter_asked: list[tuple[str, str, str]] = []

    async def voter_search(self, first: str, last: str, county: str) -> dict:
        self.voter_asked.append((first, last, county))
        key = f"{last.upper()}|{first.upper()}"
        if key not in self.voter:
            raise LookupError(f"no recorded voter search for {key}")
        return self.voter[key]


def run(row: dict, client) -> core.VerificationResult:
    return asyncio.run(e.verify(row, client))


def replay(c: dict) -> Replay:
    return Replay(c["responses"], c["voter"])


def _row(**kw) -> dict:
    base = {"state": "NC", "county": "Buncombe", "listing_type": "elderly_disabled",
            "parcel_id": "0605880879", "owner_name": "OXAMI CEROLA", "city": "Fairview",
            "source": "counties_nc.buncombe_elderly",
            "raw": {"gis_exempt": {"code": "ELD", "tag": "elderly_exemption"},
                    "life_events": ["elderly_exemption"]}}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# the contract and the claim
# ---------------------------------------------------------------------------

def test_registered_with_governs_ttl():
    v = {x.name: x for x in discover()}["elderly_disabled"]
    assert v.signal == "elderly_disabled" and v.version == "v2"
    assert v.governs == ("elderly_disabled", "senior_exemption")
    assert v.ttl_days == 60 and v.retry_days == 7 and not v.wall


def test_governs_are_the_scorer_names_the_claim_feeds():
    from foreclosure_scraper import distress_score
    assert distress_score._LISTING_TYPE_SIGNAL["elderly_disabled"][0] == "LIFE_EVENT"
    assert distress_score.SIGNAL_CATEGORY["senior_exemption"] == "LIFE_EVENT"


def test_layer_url_is_the_scrapers_layer():
    from foreclosure_scraper.scrapers.counties_nc.buncombe_elderly import QUERY_URL
    assert e.LAYER_URL == QUERY_URL
    assert e.layer_url("pin", "0605880879").startswith(QUERY_URL + "?where=pin%3D%270605880879%27")


@pytest.mark.parametrize("pid,q", [
    ("0605880879", ("pin", "0605880879")),                 # the scraper's own 10-digit form
    ("0605-88-0879", ("pin", "0605880879")),
    ("060588087900000", ("pinnum", "060588087900000")),    # a full PIN (tax sources)
    ("9648-62-3059-C0401", ("pinnum", "9648623059C0401")),  # a condominium unit
    ("96865408261234", None), ("12345", None), (None, None),
])
def test_layer_query(pid, q):
    assert e.layer_query({"parcel_id": pid}) == q


def test_claimed_codes_from_every_carrier():
    assert e.claimed_codes(_row()) == ["ELD"]
    assert e.claimed_codes(_row(raw={"tax_relief": {"kind": "disabled"}})) == ["DIS"]
    assert e.claimed_codes(_row(raw={"life_events": ["trust", "disabled_veteran_exemption"]})) == ["VET"]
    assert e.claimed_codes(_row(raw={"gis_exempt": {"code": "BLD"}, "life_events": ["elderly_exemption"]})) == ["BLD", "ELD"]
    assert e.claimed_codes(_row(raw={"tax_relief": {"kind": "use_value_deferral"},
                                     "life_events": ["life_estate", "estate_probate"]})) == []


def test_applies_buncombe_nc_claim_rows_only():
    assert e.applies(_row())
    assert e.applies(_row(listing_type="tax_lien"))                      # claim via gis_exempt
    assert e.applies(_row(raw={}, listing_type="elderly_disabled"))     # claim via listing type
    assert not e.applies(_row(listing_type="tax_lien", raw={"life_events": ["trust"]}))
    assert not e.applies(_row(county="Henderson"))                       # no proven endpoint
    assert not e.applies(_row(state="SC"))
    assert not e.applies({"raw": None})


# ---------------------------------------------------------------------------
# pure rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("real,exempt,shape", [
    (52600, 26300, "elderly_disabled_half"),      # live: half the appraised value
    (208300, 45000, "veteran_45000"),              # live: the disabled-veteran $45,000
    (40000, 25000, "elderly_disabled_25000"),      # the $25,000 floor
    (18000, 18000, "full_value"),                  # a residence worth less than the exclusion
    (300000, 1234, "other"),
    (300000, 0, None),
    (300000, None, None),
])
def test_relief_shape(real, exempt, shape):
    assert e.relief_shape(real, exempt) == shape


def test_parse_layer_and_errors():
    [a] = e.parse_layer({"features": [{"attributes": {"pinnum": "1", "owner": " X Y ", "Exempt": "eld ",
                                                      "TaxYear": "26", "UpdateDate": "20261001",
                                                      "DeedDate": "19690918", "AppraisedValue": "52600"}}]})
    assert a["code"] == "ELD" and a["tax_year"] == 2026 and a["updated"] == "2026-10-01"
    assert a["deed_date"] == "1969-09-18" and a["owner"] == "X Y" and a["appraised"] == 52600
    assert e.parse_layer({"features": []}) == []
    for bad in ({"error": {"code": 400}}, {"nope": 1}, ["x"]):
        with pytest.raises(ValueError):
            e.parse_layer(bad)


def test_owner_state_transfer_and_household():
    lay = {"owner": "OXAMI CEROLA;OXAMI PATALI", "deed_date": "1969-09-18"}
    s = e.owner_state({"owner_name": "OXAMI CEROLA", "first_seen": "2026-07-01T00:00:00"}, lay)
    assert s == {"owner_match": "same", "transferred_since": False, "owner_changed": False}
    s = e.owner_state({"owner_name": "OXAMI CEROLA L", "first_seen": "2026-07-01"},
                      {"owner": "OXAMI MIKALO", "deed_date": "2026-08-15"})
    assert s["owner_match"] == "partial" and s["transferred_since"] and s["owner_changed"]
    s = e.owner_state({"owner_name": "OXAMI CEROLA L", "first_seen": "2026-07-01"},
                      {"owner": "OXAMI MIKALO", "deed_date": "2001-01-01"})
    assert not s["owner_changed"]                     # a shared surname, no deed since
    s = e.owner_state({"owner_name": "BIRATU CAMOSE", "first_seen": "2026-07-01"},
                      {"owner": "2020 BUILDERS LLC", "deed_date": "2001-01-01"})
    assert s["owner_changed"]


def test_scraped_from_layer_needs_the_same_pin():
    url = e.LAYER_URL + "?where=pin%3D%270605880879%27&outFields=*&f=html"
    assert e.scraped_from_layer(_row(source_url=url), "060588087900000")
    assert not e.scraped_from_layer(_row(source_url=url), "060588087800000")
    assert not e.scraped_from_layer(_row(source_url=url, source="counties_nc.buncombe_delinquent_tax"),
                                    "060588087900000")


# ---------------------------------------------------------------------------
# voter status: status and counts only
# ---------------------------------------------------------------------------

def _v(name, status, csz="ASHEVILLE, NC 28000"):
    return {"FullName": name, "StatusDesc": status, "ResAddressCSZ": csz,
            "VoterRegNum": "900000000", "NCID": "ZZ1", "CountyName": "BUNCOMBE"}


def test_classify_voters_rules():
    one = [_v("OXAMI, CEROLA LEE", "ACTIVE")]
    assert e.classify_voters(one, "OXAMI", "CEROLA", "", None) == {"same_name": 1, "by": [], "status": "active"}
    assert e.classify_voters([_v("OXAMI, CEROLA", "INACTIVE")], "OXAMI", "CEROLA", "", None)["status"] == "inactive"
    assert e.classify_voters([], "OXAMI", "CEROLA", "", None)["status"] == "not_found"
    # another person who only starts with the same letters is not a same-name record
    assert e.classify_voters([_v("OXAMIS, CEROLAN", "ACTIVE")], "OXAMI", "CEROLA", "", None)["status"] == "not_found"
    two = [_v("OXAMI, CEROLA A", "ACTIVE"), _v("OXAMI, CEROLA B", "ACTIVE", "WEAVERVILLE, NC 28000")]
    r = e.classify_voters(two, "OXAMI", "CEROLA", "", None)
    assert r["status"] == "ambiguous" and r["matches"] == 2
    r = e.classify_voters(two, "OXAMI", "CEROLA", "", "Weaverville")
    assert r["status"] == "active" and r["by"] == ["city"]
    r = e.classify_voters(two, "OXAMI", "CEROLA", "B", None)
    assert r["status"] == "active" and r["by"] == ["middle"] and r["middle_excluded"] == 1
    # registered records decide first; none registered -> removed (removed records carry no address)
    rem = [_v("OXAMI, CEROLA", "REMOVED", ""), _v("OXAMI, CEROLA Q", "DENIED", "")]
    r = e.classify_voters(rem, "OXAMI", "CEROLA", "", None)
    assert r["status"] == "removed" and r["matches"] == 2
    assert e.classify_voters(rem + one, "OXAMI", "CEROLA", "", None)["status"] == "active"
    # a middle-initial conflict removes the only registered record: the owner is the removed one
    r = e.classify_voters([_v("OXAMI, CEROLA Z", "ACTIVE"), _v("OXAMI, CEROLA L", "REMOVED", "")],
                          "OXAMI", "CEROLA", "L", None)
    assert r["status"] == "removed" and r["middle_excluded"] == 1


def test_classify_voters_keeps_nothing_personal():
    rows = [_v("OXAMI, CEROLA LEE", "ACTIVE"), _v("OXAMI, CEROLA MAE", "REMOVED", "")]
    blob = json.dumps(e.classify_voters(rows, "OXAMI", "CEROLA", "", "Asheville"))
    for bad in ("OXAMI", "CEROLA", "LEE", "ASHEVILLE", "900000000", "ZZ1", "28000"):
        assert bad not in blob.upper()


@pytest.mark.parametrize("owner,status,reason", [
    ("OXAMI FAMILY TRUST", "skipped", "trust_owner"),
    ("ACME HOLDINGS LLC", "skipped", "entity_owner"),
    ("OXAMI CEROLA ESTATE", "skipped", "estate_owner"),
    ("COUNTY OF BUNCOMBE", "skipped", "government_owner"),
    (None, "skipped", "no_owner"),
    ("OXAMI", "skipped", "name_unsplittable"),
])
def test_voter_skips_non_people(owner, status, reason):
    r = asyncio.run(e.voter_status(_row(owner_name=owner), Replay({})))
    assert r == {"status": status, "reason": reason}


def test_voter_never_goes_live_without_a_live_fetcher():
    assert asyncio.run(e.voter_status(_row(), ReplayFetcher({}))) == {"status": "not_checked",
                                                                      "reason": "no_voter_client"}


def test_voter_search_failure_is_an_error_status_not_a_verdict_change():
    class Bad(Replay):
        async def voter_search(self, *a):
            return {"ok": False, "error": "ConnectTimeout: vt.ncsbe.gov", "rows": []}
    assert asyncio.run(e.voter_status(_row(), Bad({}))) == {"status": "error", "error": "ConnectTimeout"}


def test_nc_voter_search_replays_the_real_flow():
    """nc_voter_search against the captured form page and a captured (pseudonymized) result set:
    the token is posted back, both status filters are sent, pace runs before every request."""
    form = fixture()["voter_form"]
    rows = next(v for c in fixture()["cases"].values() for v in c["voter"].values() if v["rows"])
    posted: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/RegLkup/":
            return httpx.Response(200, text=form)
        if req.method == "POST":
            posted.append({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
            return httpx.Response(302, headers={"Location": "/RegLkup/SearchResults"})
        if req.url.params.get("handler") == "LoadResults":
            return httpx.Response(200, json={"Data": rows["rows"], "Total": rows["total"]})
        return httpx.Response(200, text="<html></html>")

    paced = []

    async def pace():
        paced.append(1)

    res = asyncio.run(V.nc_voter_search("Cerola", "Oxami", "BUNCOMBE", include_removed=True,
                                        pace=pace, transport=httpx.MockTransport(handler)))
    assert res["ok"] and res["rows"] == rows["rows"] and res["total"] == rows["total"]
    p = posted[0]
    assert p["VoterSearchFilter.IsRegistered"] == "true" and p["VoterSearchFilter.IsRemovedOrDenied"] == "true"
    assert p["VoterSearchFilter.SelectedCountyId"] == "11" and p["__RequestVerificationToken"]
    assert len(paced) == 3


def test_nc_voter_search_never_raises():
    def boom(req):
        raise httpx.ConnectError("down")
    res = asyncio.run(V.nc_voter_search("A", "B", transport=httpx.MockTransport(boom)))
    assert res["ok"] is False and res["error"].startswith("ConnectError")


# ---------------------------------------------------------------------------
# the live verdicts, reproduced exactly from the sweep's own responses
# ---------------------------------------------------------------------------

def _cases():
    return sorted(fixture()["cases"])


@pytest.mark.parametrize("name", _cases())
def test_live_verdicts_reproduce(name):
    c = case(name)
    res = run(c["row"], replay(c))
    exp = c["expected"]
    assert res.verdict == exp["verdict"]
    assert res.evidence.get("basis") == exp["basis"]
    assert res.evidence.get("reason") == exp["reason"]
    assert (res.evidence.get("voter") or {}).get("status") == exp["voter_status"]
    assert res.verifier == "elderly_disabled" and res.verifier_version == "v2"


@pytest.mark.parametrize("name", _cases())
def test_evidence_is_minimal(name):
    """No owner name (county's or board's), no voter id, address or other person in evidence."""
    c = case(name)
    res = run(c["row"], replay(c))
    from foreclosure_scraper.name_normalize import core_tokens
    blob = json.dumps(res.evidence).upper()
    for t in core_tokens(c["row"].get("owner_name")):       # person-name tokens, no LLC / TRUST
        if len(t) > 2 and t not in {"REVOCABLE", "LIVING", "FAMILY"}:
            assert t not in blob, t
    for k in ("VoterRegNum", "NCID", "ResAddressCSZ", "FullName", "28000", "owner_county", "owner_board"):
        assert k.upper() not in blob
    assert set(res.evidence.get("voter") or {}) <= {"status", "same_name", "by", "matches",
                                                    "middle_excluded", "reason", "error"}


def test_confirmed_reads_only_the_layer():
    c = case("confirmed_eld")
    f = replay(c)
    res = run(c["row"], f)
    assert res.verdict == "confirmed" and res.evidence["county_code"] == "ELD"
    assert res.evidence["exemption_type"] == "elderly" and res.evidence["tax_year"] == 2026
    assert [u for u in f.asked if "tax.buncombenc.gov" in u] == []
    assert len(f.voter_asked) == 1 and f.voter_asked[0][2] == "BUNCOMBE"


def test_refuted_merged_claim_checked_two_bills():
    c = case("refuted_merged_claim")
    f = replay(c)
    res = run(c["row"], f)
    assert res.verdict == "refuted" and res.evidence["basis"] == "never_on_record"
    assert res.evidence["county_code"] is None
    assert [b["exempt_value"] for b in res.evidence["bills_checked"]] == [0.0, 0.0]
    assert "buncombe_elderly" in str(c["row"]["raw"].get("also_seen_in"))    # the claim came by a merge
    assert not e.scraped_from_layer(c["row"], res.evidence["pinnum"])


def test_condo_units_under_one_pin_never_decide():
    """A board row with the building's 10-digit pin: 202 parcels come back (the 00000 common area
    and the units). The owner's own unit still carries VET, but every unit's row shares the ledger
    key, so the answer is unconfirmed and nothing else is fetched (live 2026-10-06; v1 read the
    common-area parcel and called this stale)."""
    c = case("unconfirmed_condo_units")
    f = replay(c)
    res = run(c["row"], f)
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "pin_shared_by_units"
    assert ev["parcels_under_pin"] == 202 and ev["coded_parcels_under_pin"] == 13
    assert ev["owner_unit_code"] == "VET" and ev["owner_unit"].startswith("9658735582C")
    assert len(f.asked) == 1 and f.voter_asked == []


def test_stale_relief_billed_this_year_but_gone_from_the_layer():
    c = case("stale_billed_this_year")
    res = run(c["row"], replay(c))
    ev = res.evidence
    assert res.verdict == "stale" and ev["basis"] == "relief_removed" and ev["county_code"] is None
    assert ev["bills_checked"][0]["year"] == 2026 and ev["bills_checked"][0]["shape"] == "elderly_disabled_half"
    assert ev["layer_showed_it_on"] and e.scraped_from_layer(c["row"], ev["pinnum"])


def test_stale_relief_removed_from_the_2026_bill():
    c = case("stale_relief_removed")
    ev = run(c["row"], replay(c)).evidence
    assert [b["year"] for b in ev["bills_checked"]] == [2026, 2025]
    assert ev["bills_checked"][0]["exempt_value"] == 0.0 and ev["bills_checked"][1]["exempt_value"] > 0


def test_same_page_without_the_code_is_stale_for_the_scrapers_own_row():
    """The confirmed parcel's layer answer with the code blanked, and its own scraper row: the
    relief was on the record (the scraper read it there by this PIN) and is not now -> stale;
    the same answer for a row that only carries the claim by a merge, bills unrecorded ->
    unconfirmed (never refuted without every bill read)."""
    c = case("confirmed_eld")
    resp = {}
    for u, b in c["responses"].items():
        d = json.loads(b)
        d["features"][0]["attributes"]["Exempt"] = ""
        resp[u] = json.dumps(d)
    pin = e.layer_query(c["row"])[1]
    row = dict(c["row"], source_url=e.LAYER_URL + f"?where=pin%3D%27{pin[:10]}%27&outFields=*&f=html")
    res = run(row, Replay(resp, c["voter"]))
    assert res.verdict == "stale" and res.evidence["basis"] == "relief_removed"
    assert res.evidence["bills_checked"] == []          # the tax site was asked, nothing recorded
    res = run(dict(row, source="counties_generic.arcgis_distress.buncombe_unpaid_bills"),
              Replay(resp, c["voter"]))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "bills_unreadable"


def test_layer_code_present_new_owner_never_suppresses():
    c = case("confirmed_eld")
    row = dict(c["row"], owner_name="BIRATU CAMOSE")
    res = run(row, replay(c))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "owner_differs_relief_present"
    assert res.evidence["owner_match"] == "different"


def test_type_change_inside_the_set_is_still_confirmed():
    c = case("confirmed_eld")
    row = json.loads(json.dumps(c["row"]))
    row["raw"]["gis_exempt"] = {"code": "VET", "tag": "disabled_veteran_exemption"}
    row["raw"]["life_events"] = ["disabled_veteran_exemption"]
    res = run(row, replay(c))
    assert res.verdict == "confirmed" and res.evidence["type_changed"] is True


def test_refuted_page_with_one_bill_unrecorded_is_unconfirmed():
    c = case("refuted_merged_claim")
    resp = dict(c["responses"])
    last_bill = [u for u in resp if "/Bill/Details/" in u][-1]
    del resp[last_bill]
    res = run(c["row"], Replay(resp, c["voter"]))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "bills_unreadable"


def test_billing_that_ended_cannot_say_never():
    """The same pages read as if it were 2030: the newest bill (2026) no longer reaches last year,
    so the record cannot speak for the board's lifetime -> unconfirmed, never refuted."""
    from datetime import date
    c = case("refuted_merged_claim")
    res = asyncio.run(e.verify(c["row"], replay(c), today=date(2030, 1, 1)))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_record_ended"


def test_exempt_value_unexplained_is_unconfirmed():
    c = case("refuted_merged_claim")
    resp = {u: (b.replace("<th>Exempt Value:</th>\n                        <td class=\"text-end\">$0.00</td>",
                          "<th>Exempt Value:</th>\n                        <td class=\"text-end\">$1,234.00</td>")
                if "/Bill/Details/" in u else b) for u, b in c["responses"].items()}
    assert any("$1,234.00" in b for b in resp.values())
    res = run(c["row"], Replay(resp, c["voter"]))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "exempt_value_unexplained"


# ---------------------------------------------------------------------------
# unconfirmed paths
# ---------------------------------------------------------------------------

def test_unresolvable_parcel_fetches_nothing():
    f = Replay({})
    res = run(_row(parcel_id="12345"), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_unresolvable"
    assert f.asked == [] and f.voter_asked == []


def test_layer_unreadable():
    f = Replay({})
    res = run(_row(), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "layer_unreadable"
    assert f.voter_asked == []


def test_layer_error_payload():
    url = e.layer_url("pin", "0605880879")
    res = run(_row(), Replay({url: json.dumps({"error": {"code": 400, "message": "bad"}})}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "layer_unreadable"


def test_pin_not_in_layer():
    url = e.layer_url("pin", "0605880879")
    res = run(_row(), Replay({url: json.dumps({"features": []})}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_not_in_county_layer"


# ---------------------------------------------------------------------------
# what a verdict does to the score
# ---------------------------------------------------------------------------

def _rec(verdict: str) -> dict:
    return {"signal": "elderly_disabled", "verdict": verdict, "checked_at": core.iso_z(core.utc_now()),
            "expires_at": core.iso_z(core.utc_now().replace(year=core.utc_now().year + 1)),
            "governs": list(e.GOVERNS), "verifier": "elderly_disabled"}


@pytest.mark.parametrize("verdict,kept", [("confirmed", True), ("unconfirmed", True),
                                          ("refuted", False), ("stale", False)])
def test_scoring_reads_the_verdict(verdict, kept):
    from foreclosure_scraper.distress_score import _signals_for
    from foreclosure_scraper.enrichment_lead_signals import _facet_signals
    from foreclosure_scraper.models import Listing, ListingType
    li = Listing(source="counties_nc.buncombe_elderly", source_url="https://x",
                 listing_type=ListingType.ELDERLY_DISABLED, state="NC", county="Buncombe",
                 parcel_id="0605880879", street_address="863 X RD",
                 raw={"tax_relief": {"kind": "elderly"}, "gis_exempt": {"code": "ELD"},
                      "life_events": ["elderly_exemption"], "verification": [_rec(verdict)]})
    names = {n for n, _c, _w in _signals_for(li, today=core.utc_now().date())}
    assert ("elderly_disabled" in names) is kept and ("senior_exemption" in names) is kept
    assert ("senior_exemption" in _facet_signals(li)) is kept
