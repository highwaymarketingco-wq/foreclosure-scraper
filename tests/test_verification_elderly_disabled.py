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


def _address_response(c: dict, responses: dict | None = None) -> dict:
    """What the layer's situs-column query for the case row's address answers, built from the
    case's own recorded layer record: the board's parcel IS the one carrying the row's address
    (v4 asks; the 2026-10-06 sweep that recorded these cases did not). A case whose layer answer
    has no parcel gets an empty answer."""
    row = c["row"]
    url = e.address_layer_url(row.get("street_address"))
    if not url:
        return {}
    q = e.layer_query(row)
    responses = c["responses"] if responses is None else responses
    feats = json.loads(responses[e.layer_url(*q)]).get("features", []) if q else []
    if len(feats) != 1:
        return {url: json.dumps({"features": []})}
    number, _, rest = str(row["street_address"]).strip().partition(" ")
    attrs = dict(feats[0]["attributes"], HouseNumber=number, NumberSuffix="", direction="",
                 streetname=rest, StreetType="", PostDirection="")
    return {url: json.dumps({"features": [{"attributes": attrs}]})}


def _older_bills(c: dict) -> dict:
    """The look-back window's older bills (v4 reads every bill since 2022 before it says
    "never"; the sweep read the two newest): each unrecorded bill of the case's parcel page that
    falls in the window, served as a copy of the newest recorded bill of the parcel (the refuted
    cases' recorded bills carry no exclusion) with its own levy year."""
    import re
    from foreclosure_scraper.verification.verifiers.tax_lien_buncombe import parse_parcel_page
    out = {}
    recorded = [u for u in c["responses"] if "/Bill/Details/" in u]
    for u, body in c["responses"].items():
        if "/Parcel/Details/" not in u or not recorded:
            continue
        for b in parse_parcel_page(body)["bills"]:
            burl = "https://tax.buncombenc.gov/Bill/Details/" + b["bill"]
            if burl in c["responses"] or b["year"] < 2022:
                continue
            text = c["responses"][recorded[0]]
            out[burl] = re.sub(r"(<th>Levy Year</th>\s*<td>)\d{4}", lambda m: m.group(1) + str(b["year"]),
                               text)
    return out


def with_address(c: dict, resp: dict) -> Replay:
    """A Replay of `resp` (a case's responses, edited by a test) that also answers the address
    query as the case's board parcel carrying the row's address (see _address_response)."""
    return Replay({**resp, **_address_response(c, resp)}, c["voter"])


def replay(c: dict) -> Replay:
    extra = _address_response(c)
    if c["expected"]["verdict"] == "refuted":
        extra.update(_older_bills(c))
    return Replay({**c["responses"], **extra}, c["voter"])


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
    assert v.signal == "elderly_disabled" and v.version == "v5"
    assert v.governs == ("elderly_disabled", "senior_exemption")
    assert v.ttl_days == 60 and v.retry_days == 7 and not v.wall


def test_owner_name_stays_out_of_the_public_ledger(tmp_path):
    from foreclosure_scraper.verification.ledger import Ledger
    assert e.ROW_SUMMARY_EXCLUDE == ("owner_name",)
    c = case("confirmed_eld")
    led = Ledger.load("elderly_disabled", tmp_path)
    led.record(c["row"], run(c["row"], replay(c)), ttl_days=e.TTL_DAYS, governs=e.GOVERNS)
    assert any("owner_name" in x["row"] for x in led.rows.values())   # what record() writes
    assert e.migrate_ledger(led) == 1 and e.migrate_ledger(led) == 0
    assert not any("owner_name" in x["row"] for x in led.rows.values())
    assert [x["latest"]["verdict"] for x in led.rows.values()] == ["confirmed"]


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


#: what v3 changed on the live cases (the fixture's `expected` is what v2 answered): the one
#: stale that the county's own bill contradicted
V3_CHANGED = {"stale_billed_this_year": {"verdict": "confirmed", "basis": "exemption_on_latest_bill",
                                         "reason": None, "voter_status": "not_found"},
              # v5 (owner decision 2026-10-06): the exclusion gone from the newest bill with the SAME
              # owner keeps scoring: unconfirmed, not stale (11 Cardinal Cove Rd)
              "stale_relief_removed": {"verdict": "unconfirmed", "basis": None,
                                       "reason": "relief_removed_same_owner", "voter_status": "not_found"}}


#: 82 Black Bear Trl: its parcel page lists 2026 and 2025 bills in legal collection ("See Legal",
#: no numeric Amount Due) above the paid 2024 / 2023 ones. tax_lien_buncombe's parse_parcel_page
#: (the page parser this verifier shares) dropped such cards until its v4, so the newest bills it
#: returned were 2024 and 2023 and the answer was parcel_record_ended; with them kept the newest
#: two are the legal-collection bills, whose Bill Details pages the sweep never captured:
#: bills_unreadable. Either way unconfirmed, never decisive.
SHARED_PARSER_REASONS = {"unconfirmed_record_ended": {"parcel_record_ended", "bills_unreadable"}}


@pytest.mark.parametrize("name", _cases())
def test_live_verdicts_reproduce(name):
    c = case(name)
    res = run(c["row"], replay(c))
    exp = V3_CHANGED.get(name, c["expected"])
    assert res.verdict == exp["verdict"]
    assert res.evidence.get("basis") == exp["basis"]
    assert res.evidence.get("reason") in SHARED_PARSER_REASONS.get(name, {exp["reason"]})
    assert (res.evidence.get("voter") or {}).get("status") == exp["voter_status"]
    assert res.verifier == "elderly_disabled" and res.verifier_version == "v5"


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
    # v4 reads every bill of the look-back window before it says "never" (2022 to 2026)
    assert [b["year"] for b in res.evidence["bills_checked"]] == [2026, 2025, 2024, 2023, 2022]
    assert [b["exempt_value"] for b in res.evidence["bills_checked"]] == [0.0] * 5
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


def test_the_newest_bill_still_excludes_so_a_blank_layer_flag_is_not_stale():
    """1406 Hardscrabble Rd (the live case, pseudonymized): the layer's Exempt flag is blank, but
    the 2026 bill (8/15/2026, paid) excludes 103,900 = half of 207,800, the owners are unchanged on
    every bill, and the scraper's own row read the code on 2026-08-16. v2 called this stale
    (relief_removed) through `from_layer` and an `any()` over the two bills, against its own
    bills_checked; the newest bill decides: confirmed."""
    c = case("stale_billed_this_year")
    res = run(c["row"], replay(c))
    ev = res.evidence
    assert res.verdict == "confirmed" and ev["basis"] == "exemption_on_latest_bill"
    assert ev["county_code"] is None and ev["layer_flag_blank"] is True
    assert ev["bills_checked"][0]["year"] == 2026 and ev["bills_checked"][0]["exempt_value"] == 103900.0
    assert ev["bills_checked"][0]["shape"] == "elderly_disabled_half" == ev["latest_bill_shape"]
    assert ev["layer_showed_it_on"] and e.scraped_from_layer(c["row"], ev["pinnum"])   # v2's trigger
    assert ev["exempt_value_by_year"] == {"2026": 103900.0, "2025": 101800.0}
    assert ev["owner_unchanged_since"] == 2020 and ev["owner_match"] == "same"


def _with_bill_exempt(c: dict, year: int, exempt: str) -> Replay:
    """The case's responses with the Exempt Value of one levy year's bill replaced."""
    import re
    resp = {}
    for u, b in c["responses"].items():
        if f"-{year}-{year}-" in u and "/Bill/Details/" in u:
            b = re.sub(r"(<th>Exempt Value:</th>\s*<td[^>]*>)\s*[^<]*?\s*(</td>)",
                       lambda m: m.group(1) + exempt + m.group(2), b)
            assert exempt in b
        resp[u] = b
    return with_address(c, resp)


def test_a_newest_bill_without_the_exclusion_keeps_scoring_for_the_same_owner():
    """The 1406 pages with the 2026 bill's exclusion removed: the newest bill is what says the
    relief is gone; with the owner unchanged the person may still be elderly, so v5 answers
    unconfirmed (the signal keeps scoring), not stale."""
    c = case("stale_billed_this_year")
    res = run(c["row"], _with_bill_exempt(c, 2026, "$0.00"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "relief_removed_same_owner"
    assert res.evidence["exempt_value_by_year"] == {"2026": 0.0, "2025": 101800.0}


def test_an_unreadable_newest_bill_cannot_say_the_relief_is_gone():
    """The layer's blank flag is not proof (1406 had one over a bill that still excluded half the
    value), so with the 2026 bill unrecorded neither the older bill nor the scraper's own earlier
    read of the layer makes a stale: unconfirmed, retried in a week."""
    c = case("stale_billed_this_year")
    resp = {u: b for u, b in c["responses"].items() if "-2026-2026-" not in u}
    res = run(c["row"], with_address(c, resp))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "bills_unreadable"
    assert [b.get("error") for b in res.evidence["bills_checked"]][0] == "LookupError"


def test_an_unexplained_newest_exclusion_confirms_only_the_scrapers_own_row():
    """118,350 of 258,700 is no relief formula ('other'): on the scraper's own row of the parcel
    (it read ELD there) the newest bill's exclusion still confirms; on a claim merged in from
    elsewhere it stays unexplained."""
    c = case("stale_relief_removed")
    res = run(c["row"], _with_bill_exempt(c, 2026, "$118,350.00"))
    assert res.verdict == "confirmed" and res.evidence["basis"] == "exemption_on_latest_bill"
    assert res.evidence["latest_bill_shape"] == "other"
    merged = dict(c["row"], source="counties_generic.arcgis_distress.buncombe_unpaid_bills")
    res = run(merged, _with_bill_exempt(c, 2026, "$118,350.00"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "exempt_value_unexplained"


def test_a_new_owner_with_the_exclusion_on_the_newest_bill_is_still_stale_owner_changed():
    """The newest bill cannot show a NEW owner's relief (the exclusion is personal): an owner
    change since the board saw the row stays the v2 answer."""
    c = case("stale_billed_this_year")
    row = dict(c["row"], owner_name="BIRATU CAMOSE")
    res = run(row, replay(c))
    assert res.verdict == "stale" and res.evidence["basis"] == "owner_changed"


def test_owner_unchanged_since_is_the_run_of_bills_naming_the_newest_owner():
    bills = [{"year": 2026, "owner": "ROE JANE (LE)"}, {"year": 2025, "owner": "roe, jane (le)"},
             {"year": 2024, "owner": "ROE JANE (LE)"},
             {"year": 2023, "owner": "ROE JANE (LE) DOE JOHN (LE)"}, {"year": 2022, "owner": "ROE JANE (LE)"}]
    assert e.owner_unchanged_since(bills) == 2024          # a second owner on 2023 ends the run
    assert e.owner_unchanged_since(bills[:3]) == 2024
    assert e.owner_unchanged_since([{"year": 2026, "owner": None}, {"year": 2025, "owner": "A B"}]) is None
    assert e.owner_unchanged_since([]) is None
    assert e.owner_unchanged_since([{"year": 2026, "owner": "A B"}, {"year": 2025, "owner": None}]) == 2026


def test_stale_relief_removed_from_the_2026_bill():
    c = case("stale_relief_removed")
    ev = run(c["row"], replay(c)).evidence
    assert [b["year"] for b in ev["bills_checked"]] == [2026, 2025]
    assert ev["bills_checked"][0]["exempt_value"] == 0.0 and ev["bills_checked"][1]["exempt_value"] > 0


def test_a_same_owner_removal_keeps_scoring_and_shows_what_decides_it():
    """11 Cardinal Cove Rd (parcel situs 7): 118,350 excluded on the 2025 bill, 0 on 2026, the
    same life-estate owner on every bill since 2021 and no deed since 2010. The owner decided
    (2026-10-06) that such a lead keeps scoring: unconfirmed (relief_removed_same_owner), not
    stale; the evidence carries what the decision rests on."""
    c = case("stale_relief_removed")
    res = run(c["row"], replay(c))
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "relief_removed_same_owner"
    assert ev["exempt_value_by_year"] == {"2026": 0.0, "2025": 118350.0}
    assert ev["owner_unchanged_since"] == 2021 and ev["owner_match"] == "same"
    assert "transferred_since" not in ev and "deed_date" not in ev       # no deed since the board saw it
    blob = json.dumps(ev).upper()
    assert "REMIMU" not in blob and "WEMA" not in blob                    # the year only, never the name


def test_same_page_without_the_code_cannot_be_stale_with_the_bills_unrecorded():
    """The confirmed parcel's layer answer with the code blanked, and its own scraper row: with the
    tax site answering nothing the bills cannot say the relief is gone (v2 called this stale from
    the layer's blank flag alone, a flag that is blank over a still-excluding bill on 1406
    Hardscrabble Rd) -> unconfirmed; a row that only carries the claim by a merge, same."""
    c = case("confirmed_eld")
    resp = {}
    for u, b in c["responses"].items():
        d = json.loads(b)
        d["features"][0]["attributes"]["Exempt"] = ""
        resp[u] = json.dumps(d)
    pin = e.layer_query(c["row"])[1]
    row = dict(c["row"], source_url=e.LAYER_URL + f"?where=pin%3D%27{pin[:10]}%27&outFields=*&f=html")
    res = run(row, with_address(dict(c, row=row), resp))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "bills_unreadable"
    assert res.evidence["bills_checked"] == []          # the tax site was asked, nothing recorded
    res = run(dict(row, source="counties_generic.arcgis_distress.buncombe_unpaid_bills"),
              with_address(dict(c, row=row), resp))
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
    res = run(c["row"], with_address(c, resp))
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
    res = run(c["row"], with_address(c, resp))
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


# ---------------------------------------------------------------------------
# v4: the parcel that carries the row's ADDRESS, the lien-bill parcel, the bill look-back
#
# Built from the real shapes the 2026-10-06 live re-check of the 34 refuted entries found wrong
# (PINs and street addresses are public record; every owner is invented). The county layer's
# answers are in its JSON shape; the tax site's pages are generated in the markup of the real
# ones (the pieces tax_lien_buncombe.parse_parcel_page / parse_bill_values read).
# ---------------------------------------------------------------------------

from datetime import date as _date  # noqa: E402

TODAY = _date(2026, 10, 6)
TAX = "https://tax.buncombenc.gov"


def run_at(row: dict, client) -> core.VerificationResult:
    return asyncio.run(e.verify(row, client, today=TODAY))


def _feat(pinnum: str, owner: str, code: str = "", situs: tuple | None = None,
          deed: str = "20100101") -> dict:
    """One parcel of the county layer. situs = (house number, street name, street type)."""
    a = {"pinnum": pinnum, "pin": pinnum[:10], "owner": owner, "Exempt": code, "TaxYear": "26",
         "UpdateDate": "20261004", "DeedDate": deed, "AppraisedValue": "180100", "Class": "100"}
    if situs:
        a.update(HouseNumber=situs[0], NumberSuffix="", direction="", streetname=situs[1],
                 StreetType=situs[2], PostDirection="")
    return {"attributes": a}


def _layer_ans(*feats: dict) -> str:
    return json.dumps({"features": list(feats)})


def _bill_html(year: int, real: float, exempt: float) -> str:
    cell = lambda v: f'<td class="text-end">${v:,.2f}</td>'          # noqa: E731
    return (f"<table><tr><th>Levy Year</th><td>{year}</td></tr></table><table>"
            f"<tr><th>Real Value:</th>{cell(real)}</tr><tr><th>Deferred Value:</th>{cell(0)}</tr>"
            f"<tr><th>Exempt Value:</th>{cell(exempt)}</tr><tr><th>Total Value:</th>"
            f"{cell(real - exempt)}</tr></table>")


def _parcel_html(pinnum: str, situs: str, acct: str, years: dict) -> str:
    """years: {levy year: (owner, real value, exempt value)}, the parcel page's bill cards."""
    cards = "".join(
        f'<div class="card history-card shadow-sm"><div class="card-header"><h3 class="h6 mb-0">'
        f'<a href="/Bill/Details/{acct}-{y}-{y}-0000-00">{acct}-{y}-{y}-0000-00</a></h3></div>'
        f'<div class="card-body"><div class="row"><div class="col-6">'
        f'<small class="text-muted d-block">Owner</small><div class="fw-semibold"> {o}</div></div>'
        f'<div class="col-6 text-end"><small class="text-muted d-block">Value</small>'
        f'<div class="fw-semibold">${r:,.0f}</div></div></div><div class="row mt-2"><div class="col-6">'
        f'<small class="text-muted d-block">PIN</small><div>{pinnum}</div></div>'
        f'<div class="col-6 text-end"><small class="text-muted d-block">Amount Due</small>'
        f'<div class="fw-semibold">$0.00</div></div></div></div></div>'
        for y, (o, r, _x) in sorted(years.items(), reverse=True))
    return f'<h1 class="card-title h2 mb-2">{situs}, ASHEVILLE NC 28803</h1>{cards}'


def _tax_pages(pinnum: str, situs: str, acct: str, years: dict) -> dict:
    out = {f"{TAX}/Parcel/Details/{pinnum}": _parcel_html(pinnum, situs, acct, years)}
    for y, (_o, real, exempt) in years.items():
        out[f"{TAX}/Bill/Details/{acct}-{y}-{y}-0000-00"] = _bill_html(y, real, exempt)
    return out


def _years(owner: str, exempt: dict, real: float = 180100.0, first: int = 2022,
           last: int = 2026) -> dict:
    return {y: (owner, real, exempt.get(y, 0.0)) for y in range(first, last + 1)}


class Scripted(Replay):
    """Replay plus a scripted answer for the layer's situs-column (address) query, which is the
    one query v4 adds and v3 never made: any layer URL asking for HouseNumber."""

    def __init__(self, responses: dict, address: str | None = None) -> None:
        super().__init__(responses, {})
        self.address = address

    async def get_text(self, url: str, **kw):
        if self.address is not None and "HouseNumber" in url and url not in self.responses:
            self.asked.append(url)
            return self.address
        return await super().get_text(url, **kw)


def _lien_row(**kw) -> dict:
    base = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien",
            "source": "counties_generic.arcgis_distress.buncombe_unpaid_bills",
            "first_seen": "2026-07-01T02:57:14.922879", "last_seen": "2026-09-22T15:43:13",
            "raw": {"gis_exempt": {"code": "ELD", "tag": "elderly_exemption"},
                    "life_events": ["elderly_exemption"],
                    "also_seen_in": [{"source": e.ELDERLY_SOURCE,
                                      "url": e.LAYER_URL + "?where=pin%3D%27x%27&outFields=*&f=html"}]}}
    base.update(kw)
    return base


def _ad(pin: str, last: str, first: str) -> dict:
    return {"layer": "buncombe_unpaid_bills", "pin": pin, "owner1_last_name": last,
            "owner1_first_name": first}


# 9648690092 / 31 MLK Jr Dr: the lien bill is for 14 MLK Jr Dr (ELD nowhere on its record); the row's
# street address is the lien owner's mailing address, 31 MLK Jr Dr = parcel 9648695364, which
# carries ELD today with the lien owner among its owners (exempt value 105,150 on every bill).
MLK_BOARD = "964869009200000"
MLK_ADDR = "964869536400000"


def _mlk() -> tuple[dict, Scripted]:
    row = _lien_row(parcel_id="9648-69-0092-00000", street_address="31 MARTIN LUTHER KING JR DR",
                    owner_name="QUILLOW HESTER",
                    raw={**_lien_row()["raw"], "arcgis_distress": _ad("9648-69-0092-00000",
                                                                      "QUILLOW", "HESTER")})
    resp = {e.layer_url("pinnum", MLK_BOARD): _layer_ans(_feat(MLK_BOARD, "QUILLOW HESTER")),
            **_tax_pages(MLK_BOARD, "14 MARTIN LUTHER KING JR DR", "0000716927",
                         _years("QUILLOW HESTER", {}))}
    addr = _layer_ans(
        _feat(MLK_ADDR, "QUILLOW HESTER;QUILLOW ORVAL", "ELD", ("31", "MARTIN LUTHER KING JR", "DR")),
        _feat("964869530100000", "TOLLIVER ABNER", "", ("33", "MARTIN LUTHER KING JR", "DR")))
    return row, Scripted(resp, addr)


def test_the_exclusion_on_the_parcel_that_carries_the_address_confirms_the_claim():
    """v3 judged only the lien bill's parcel (14 MLK Jr Dr: no exclusion on any bill) and said
    refuted; the row's address is parcel 9648695364, ELD today, and its owner list names the lien
    owner: the claim is true for this row."""
    row, f = _mlk()
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "confirmed" and ev["basis"] == "exemption_on_address_parcel"
    assert ev["address_parcel_basis"] == "exemption_on_record" and ev["county_code"] == "ELD"
    assert ev["address_pin"] == MLK_ADDR == ev["pinnum"] and ev["board_pin"] == MLK_BOARD
    assert ev["address_binding"] == "layer_situs" and ev["owner_match"] == "same"
    assert [p["role"] for p in ev["parcels"]] == ["address", "board"]
    assert [u for u in f.asked if "tax.buncombenc.gov" in u] == []      # a relief code needs no bills
    asked = [u for u in f.asked if "HouseNumber" in u]
    assert len(asked) == 1 and "HouseNumber+IN+%28%2731%27" in asked[0] and "LUTHER" in asked[0]


def test_a_neighbours_exclusion_is_not_followed_to():
    """The same layer answer without the 31 MLK record: only 33 MLK Jr Dr (ELD) comes back. A
    different house number is never followed to: nothing carries the row's address, the board's
    parcel is judged alone and has no exclusion on any bill since 2022."""
    row, f = _mlk()
    f.address = _layer_ans(_feat("964869530100000", "TOLLIVER ABNER", "ELD",
                                 ("33", "MARTIN LUTHER KING JR", "DR")))
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "refuted" and ev["basis"] == "never_on_record"
    assert ev["address_binding"] == "none_found" and ev["pinnum"] == MLK_BOARD
    assert "address_pin" not in ev
    assert [b["year"] for b in ev["bills_checked"]] == [2026, 2025, 2024, 2023, 2022]


def test_an_address_the_layer_cannot_read_is_never_a_refuted():
    row, f = _mlk()
    f.address = None            # the address query raises LookupError (not recorded)
    res = run_at(row, f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "address_parcel_unreadable"
    assert res.evidence["address_binding"] == "unreadable"


def test_the_tax_sites_address_search_is_the_fallback_for_the_layers_situs_columns():
    row, f = _mlk()
    f.address = _layer_ans()                                   # the layer's situs columns: nothing
    pin15 = "9648695364" + "00000"
    surl = e.SEARCH_URL.format(q="31+MARTIN+LUTHER+KING+JR")
    f.responses[surl] = (
        '<div class="search-results"><h6 class="card-subtitle mb-2">' + pin15 + '</h6>'
        '<a href="/Parcel/Details/' + pin15 + '"><h4 class="card-title">31 MARTIN LUTHER KING JR DR</h4></a>'
        '<h6 class="card-subtitle mb-2">964869530100000</h6>'
        '<a href="/Parcel/Details/964869530100000"><h4 class="card-title">33 MARTIN LUTHER KING JR DR</h4></a></div>')
    f.responses[e.layer_url("pinnum", pin15)] = _layer_ans(
        _feat(pin15, "QUILLOW HESTER;QUILLOW ORVAL", "ELD"))
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "confirmed" and ev["basis"] == "exemption_on_address_parcel"
    assert ev["address_binding"] == "site_search" and ev["address_pin"] == pin15


# 9730717960 / 87 Elkwood Ave: the board's parcel_id is the unrelated '99999 Elkwood Ave' parcel;
# the lien bill (and the row's address) is 9730729200, ELD today under the lien bill's owner.
ELK_BOARD = "973071796000000"
ELK_ADDR = "973072920000000"


def _elkwood() -> tuple[dict, Scripted]:
    row = _lien_row(parcel_id="9730-71-7960-00000", street_address="87 ELKWOOD AVE",
                    owner_name="PRYDE MARCELLE",
                    raw={**_lien_row()["raw"], "arcgis_distress": _ad("9730-72-9200-00000",
                                                                      "PRYDE", "MARCELLE"),
                         "owner_mailing": {"owner": "PRYDE MARCELLE", "source": "county_tax_roll",
                                           "parcel_id": "9730-72-9200-00000"}})
    resp = {e.layer_url("pinnum", ELK_BOARD): _layer_ans(
                _feat(ELK_BOARD, "ROADSIDE PARTNERS LLC", "", ("99999", "ELKWOOD", "AVE"), "19200424")),
            **_tax_pages(ELK_BOARD, "99999 ELKWOOD AVE", "0000611870",
                         _years("ROADSIDE PARTNERS LLC", {}, real=21000.0))}
    return row, Scripted(resp, _layer_ans(_feat(ELK_ADDR, "PRYDE MARCELLE", "ELD",
                                                ("87", "ELKWOOD", "AVE"), "20090814")))


def test_a_lien_row_filed_under_a_road_parcel_is_judged_on_the_parcel_of_its_address():
    row, f = _elkwood()
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "confirmed" and ev["basis"] == "exemption_on_address_parcel"
    assert ev["address_pin"] == ELK_ADDR and ev["board_pin"] == ELK_BOARD
    assert ev["exemption_type"] == "elderly" and ev["owner_match"] == "same"
    assert "lien_pin" not in ev                      # the lien bill's parcel IS the address parcel


def test_the_lien_bills_own_parcel_is_judged_when_nothing_carries_the_address():
    """The address is on no parcel of the layer; the lien bill's parcel (a third PIN, ELD today,
    the lien owner's) confirms by itself."""
    row, f = _elkwood()
    f.address = _layer_ans()
    f.responses[e.layer_url("pinnum", ELK_ADDR)] = _layer_ans(
        _feat(ELK_ADDR, "PRYDE MARCELLE", "ELD", ("87", "ELKWOOD", "AVE")))
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "confirmed" and ev["basis"] == "exemption_on_lien_parcel"
    assert ev["lien_pin"] == ELK_ADDR and ev["board_pin"] == ELK_BOARD
    assert ev["address_binding"] == "none_found"


@pytest.mark.parametrize("value", [400000.0, 37100.0])
def test_a_lien_parcel_with_another_exemption_is_not_this_relief(value):
    """A church parcel (layer code EXO, the whole value excluded) under another owner is a third
    parcel the lien bill names: its exclusion is explained by its own code, so the claim stays
    refuted (the live case was RIVERVIEW CHURCH RD). A parcel worth only 37,100 is excluded whole
    too, which is the shape of the elderly exclusion on a residence worth under 45,000: the layer's
    EXO code is what says it is not (the first recheck of v4 confirmed this row on that shape)."""
    row = _lien_row(parcel_id="9639-18-3184-00000", street_address=None, owner_name="WINTERBY ODELL",
                    raw={**_lien_row()["raw"], "arcgis_distress": _ad("9639-18-3999-00000",
                                                                      "WINTERBY", "ODELL")})
    board, lien = "963918318400000", "963918399900000"
    resp = {e.layer_url("pinnum", board): _layer_ans(_feat(board, "WINTERBY ODELL")),
            e.layer_url("pinnum", lien): _layer_ans(_feat(lien, "WINTERBY ODELL", "EXO")),
            **_tax_pages(board, "RIVERVIEW CHURCH RD", "0000600001", _years("WINTERBY ODELL", {})),
            **_tax_pages(lien, "RIVERVIEW CHURCH RD", "0000600002",
                         _years("WINTERBY ODELL", dict.fromkeys(range(2022, 2027), value), real=value))}
    res = run_at(row, Scripted(resp))
    ev = res.evidence
    assert res.verdict == "refuted" and ev["basis"] == "never_on_record"
    assert ev["address_binding"] == "no_row_address"
    assert [p["status"] for p in ev["parcels"]] == ["refuted", "refuted"]
    assert [p["role"] for p in ev["parcels"]] == ["board", "lien_bill"]
    assert ev["parcels"][1]["county_code"] == "EXO"


# 9686053926 / 29 Ravenwood Dr: the lien bill's parcel (the board's) lost its exclusion after the
# 2024 levy (half of 180,100 on the 2022 to 2024 bills, 0 on 2025 and 2026, the owner unchanged);
# the parcel at 29 Ravenwood Dr (9674172509) carries ELD today under ANOTHER owner.
RAV_BOARD = "968605392600000"
RAV_ADDR = "967417250900000"


def _ravenwood(relief: dict | None = None, owner_by_year=None) -> tuple[dict, Scripted]:
    relief = {2022: 90050.0, 2023: 90050.0, 2024: 90050.0} if relief is None else relief
    row = _lien_row(parcel_id="9686-05-3926-00000", street_address="29 RAVENWOOD DR",
                    owner_name="FENWICK DORIAN",
                    source="counties_generic.arcgis_distress.buncombe_unpaid_bills_2024",
                    raw={**_lien_row()["raw"], "arcgis_distress": _ad("9686-05-3926-00000",
                                                                      "FENWICK", "DORIAN")})
    years = _years("FENWICK DORIAN", relief)
    if owner_by_year:
        years = {y: (owner_by_year(y), r, x) for y, (_o, r, x) in years.items()}
    resp = {e.layer_url("pinnum", RAV_BOARD): _layer_ans(_feat(RAV_BOARD, "FENWICK DORIAN")),
            **_tax_pages(RAV_BOARD, "3 EASTCREST DR", "0000667232", years)}
    addr = _layer_ans(_feat(RAV_ADDR, "TESTOR ALDEN", "ELD", ("29", "RAVENWOOD", "DR")))
    return row, Scripted(resp, addr)


def test_a_relief_that_ended_after_2024_is_not_refuted_and_keeps_scoring():
    """v3 read the two newest bills (2026, 2025: no exclusion) and said refuted; the 2022 to 2024
    bills excluded half the value under the same owner. The neighbour at the row's address having
    ELD under someone else neither confirms nor hides that. v5: the relief was this owner's, so
    the answer is unconfirmed (relief_removed_same_owner), which keeps the signal scoring."""
    row, f = _ravenwood()
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "relief_removed_same_owner"
    assert ev["relief_years"] == [2024, 2023, 2022] and ev["owner_unchanged_since"] == 2022
    assert ev["exempt_value_by_year"] == {"2026": 0.0, "2025": 0.0, "2024": 90050.0,
                                          "2023": 90050.0, "2022": 90050.0}
    assert ev["pinnum"] == RAV_BOARD and ev["address_pin"] == RAV_ADDR and ev["board_pin"] == RAV_BOARD
    roles = {p["role"]: p for p in ev["parcels"]}
    assert roles["address"]["status"] == "neutral" and roles["board"]["status"] == "unconfirmed"
    assert roles["address"]["reason"] == "address_parcel_other_owner" and roles["address"]["county_code"] == "ELD"
    assert "TESTOR" not in json.dumps(ev).upper() and "FENWICK" not in json.dumps(ev).upper()


def test_the_window_starts_in_2022_and_a_relief_before_it_is_not_looked_for():
    row, f = _ravenwood(relief={2022: 90050.0})
    assert run_at(row, f).verdict == "unconfirmed"                 # the edge of the window (same owner)
    row, f = _ravenwood(relief={})
    f.responses.update(_tax_pages(RAV_BOARD, "3 EASTCREST DR", "0000667232",
                                  {y: ("FENWICK DORIAN", 180100.0, 90050.0 if y == 2021 else 0.0)
                                   for y in range(2021, 2027)}))
    res = run_at(row, f)                                            # a 2021 bill is outside it
    assert res.verdict == "refuted"
    assert [b["year"] for b in res.evidence["bills_checked"]] == [2026, 2025, 2024, 2023, 2022]


def test_a_relief_only_on_the_bills_of_an_earlier_owner_is_stale_and_says_so():
    row, f = _ravenwood(owner_by_year=lambda y: "FENWICK DORIAN" if y >= 2025 else "BRACKETT NOLA")
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "stale" and ev["basis"] == "owner_changed"
    assert ev["relief_under_earlier_owner"] is True and ev["owner_unchanged_since"] == 2025


def test_the_older_bills_are_read_only_when_the_newest_two_say_never():
    """A relief on the newest bill (or its removal, shown by the scraper's own earlier read) is
    decided from two bills as in v3; only "never" reads the rest of the window."""
    row, f = _ravenwood(relief={2026: 90050.0, 2025: 90050.0})
    res = run_at(row, f)
    assert res.verdict == "confirmed" and res.evidence["basis"] == "exemption_on_latest_bill"
    assert [b["year"] for b in res.evidence["bills_checked"]] == [2026, 2025]
    row, f = _ravenwood(relief={})
    res = run_at(row, f)
    assert res.verdict == "refuted" and len(res.evidence["bills_checked"]) == 5


def test_a_bill_of_the_window_that_cannot_be_read_blocks_a_refuted():
    row, f = _ravenwood(relief={})
    del f.responses[f"{TAX}/Bill/Details/0000667232-2023-2023-0000-00"]
    res = run_at(row, f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "bills_unreadable"


def test_an_unreadable_parcel_blocks_a_stale_that_another_parcel_gave():
    """The address parcel could not be read (it may show the relief today): the board parcel's
    stale does not stand alone."""
    row, f = _ravenwood()
    f.address = None
    res = run_at(row, f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "address_parcel_unreadable"


def test_the_row_owner_must_be_among_the_address_parcels_owners():
    """ELD on the address parcel under an owner who is not the row's (or the lien owner's) never
    confirms; a partial match (a shared surname) is not enough off the board's own parcel."""
    row, f = _mlk()
    f.address = _layer_ans(_feat(MLK_ADDR, "QUILLOW CALDER;TOLLIVER ABNER", "ELD",
                                 ("31", "MARTIN LUTHER KING JR", "DR")))
    res = run_at(row, f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "owner_differs_relief_present"
    assert res.evidence["owner_match"] == "partial"
    row["raw"]["arcgis_distress"] = _ad("9648-69-0092-00000", "QUILLOW", "CALDER")
    row["owner_name"] = "STRANGER PERSON"
    assert run_at(row, f).verdict == "confirmed"                  # the lien bill's owner is among them


def test_another_persons_parcel_at_the_rows_address_neither_confirms_nor_blocks_a_refuted():
    """The row's address is a stranger's home (the taxpayer's old mailing address) with ELD under
    its own owner; the lien bill's parcel never had a relief. The stranger's exclusion is nobody's
    claim here: refuted, with the neutral parcel named in the evidence (v3 refuted this too, by not
    looking at the address at all)."""
    row, f = _ravenwood(relief={})
    res = run_at(row, f)
    ev = res.evidence
    assert res.verdict == "refuted" and ev["basis"] == "never_on_record"
    assert {p["role"]: p["status"] for p in ev["parcels"]} == {"address": "neutral", "board": "refuted"}
    assert ev["address_pin"] == RAV_ADDR and ev["pinnum"] == RAV_BOARD
    assert not [u for u in f.asked if RAV_ADDR[:10] in u and "tax.buncombenc.gov" in u]   # not read


def test_a_whole_value_exclusion_above_45000_is_not_this_relief():
    assert e.relief_shape(18000, 18000) == "full_value"
    assert e.relief_shape(45000, 45000) == "full_value"
    assert e.relief_shape(400000, 400000) == "other"           # a church: layer code EXO


def test_lien_pin_and_owner_candidates_read_the_lien_block_not_the_mailing_guess():
    row = _lien_row(raw={"arcgis_distress": _ad("9730-72-9200-00000", "PRYDE", "MARCELLE"),
                         "owner_mailing": {"owner": "X Y", "source": "county_gis",
                                           "parcel_id": "9674172509"}}, owner_name="PRYDE M")
    assert e.lien_pin_query(row) == ("pinnum", "973072920000000")
    assert e.owner_candidates(row) == ["PRYDE M", "PRYDE MARCELLE"]    # county_gis mailing: not the lien's
    assert e.lien_pin_query({"raw": {}}) is None
    row["raw"]["owner_mailing"]["source"] = "county_tax_roll"
    assert e.owner_candidates(row)[-1] == "PRYDE MARCELLE" and "X Y" in e.owner_candidates(row)


def test_address_layer_url_asks_for_the_house_number_and_one_street_word():
    u = e.address_layer_url("31 MARTIN LUTHER KING JR DR")
    assert "HouseNumber+IN+%28%2731%27%2C%2700031%27%29" in u and "LIKE+%27%25LUTHER%25%27" in u
    assert "outFields=" in u and "HouseNumber%2CNumberSuffix" in u
    assert e.address_layer_url("OLD TRULL RD") is None and e.address_layer_url("99999 ELKWOOD AVE") is None
    assert e.address_layer_url(None) is None


# ---------------------------------------------------------------------------
# the county layer answers an error payload now and then: retried before a parcel is unreadable
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_layer_retry_wait(monkeypatch):
    monkeypatch.setattr(e, "LAYER_RETRY_WAIT_S", 0.0)


class FlakyLayer(Scripted):
    """Answers the first `fail` layer queries of each URL with the HTTP 200 error payload the
    county's ArcGIS server returned in the 2026-10-06 recheck ({"error": {"code": 500}})."""

    def __init__(self, responses: dict, fail: int, address: str | None = None) -> None:
        super().__init__(responses, address)
        self.fail, self.calls = fail, {}

    async def get_text(self, url: str, **kw):
        if "MapServer/1/query" in url:
            self.calls[url] = self.calls.get(url, 0) + 1
            if self.calls[url] <= self.fail:
                self.asked.append(url)
                return json.dumps({"error": {"code": 500, "message": "Error performing query operation",
                                             "details": []}})
        return await super().get_text(url, **kw)


def test_a_layer_error_payload_is_retried_before_a_parcel_is_unreadable():
    c = case("confirmed_eld")
    f = FlakyLayer(c["responses"], fail=2)
    res = run(c["row"], f)
    assert res.verdict == "confirmed" and res.evidence["county_code"] == "ELD"
    assert list(f.calls.values()) == [3]                   # two error payloads, then the record


def test_a_layer_that_keeps_failing_is_unreadable_after_three_tries():
    c = case("confirmed_eld")
    f = FlakyLayer(c["responses"], fail=99)
    res = run(c["row"], f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "layer_unreadable"
    assert list(f.calls.values()) == [e.LAYER_TRIES] and "layer error" in res.evidence["error"]


def test_the_address_and_lien_queries_are_retried_too():
    row, f0 = _mlk()
    f = FlakyLayer(f0.responses, fail=1, address=f0.address)
    res = run_at(row, f)
    assert res.verdict == "confirmed" and res.evidence["basis"] == "exemption_on_address_parcel"
    assert len(f.calls) == 2 and all(n == 2 for n in f.calls.values())      # board + address, 1 retry each
    row, f0 = _ravenwood()
    row["raw"]["arcgis_distress"]["pin"] = "9686-05-4000-00000"                # a third PIN: the lien's
    lien_url = e.layer_url("pinnum", "968605400000000")
    f0.responses[lien_url] = _layer_ans(_feat("968605400000000", "FENWICK DORIAN"))
    f0.responses.update(_tax_pages("968605400000000", "9 LIENSIDE LN", "0000667233",
                                   _years("FENWICK DORIAN", {})))
    f = FlakyLayer(f0.responses, fail=2, address=f0.address)
    res = run_at(row, f)
    assert res.verdict == "unconfirmed" and f.calls[lien_url] == 3
    assert "lien_bill" in {p["role"] for p in res.evidence["parcels"]}


def test_an_unrecorded_url_is_never_retried():
    f = Replay({})
    res = run(_row(), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "layer_unreadable"
    assert len(f.asked) == 1
