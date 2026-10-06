"""tax_lien_ptscloud against REAL NC PTS Cloud (bcpwa.ncptscloud.com) answers captured during the
2026-10-06 live sweep (Henderson, Hyde, Pitt, Forsyth, Madison, Orange, Beaufort).
tests/fixtures/verification/tax_lien_ptscloud.json.gz is {url: body}, trimmed to the fields the
verifier reads, owner names replaced by made-up ones, mailing addresses dropped. No network."""
from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import tax_lien_ptscloud as p

FIX = Path(__file__).parent / "fixtures" / "verification"
FX = json.loads(gzip.decompress((FIX / "tax_lien_ptscloud.json.gz").read_bytes()))
TODAY = date(2026, 10, 6)


def search_url(parcel: str, tenant: str) -> str:
    return p.SEARCH_URL.format(q=quote(parcel, safe=""), tenant=quote(tenant))


def detail_url(bill_id: str, tenant: str) -> str:
    return p.DETAIL_URL.format(bill_id=bill_id, tenant=tenant)


def served(**extra) -> ReplayFetcher:
    return ReplayFetcher({**FX, **extra})


def run(row, fetcher, today=TODAY):
    return asyncio.run(p.verify(row, fetcher, today=today))


def owner_in(url: str) -> str:
    return json.loads(FX[url])["results"][0]["ownerName1"]


def roll_row(county, tenant, parcel, *, year="2025", bill=None, board_parcel=None, **kw):
    row = {"state": "NC", "county": county, "listing_type": "tax_lien",
           "source": p.ROLL_SLUG, "parcel_id": board_parcel,
           "raw": {p.ROLL_KEY: {"tenant": tenant, "parcel": parcel, "tax_year": year,
                                "bill_number": bill}}}
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def test_applies_to_covered_nc_tenants_never_buncombe_or_sc():
    assert p.applies(roll_row("Henderson", "Henderson", "106725"))
    assert not p.applies(roll_row("Buncombe", "Henderson", "106725"))        # Buncombe's rows
    assert not p.applies(dict(roll_row("Henderson", "Henderson", "106725"), state="SC"))
    # a non-covered NC county (no bill search on the cluster)
    assert not p.applies({"state": "NC", "county": "Rutherford", "listing_type": "tax_lien",
                          "source": "counties_nc.rutherford_tax", "parcel_id": "1646174", "raw": {}})
    # the roll's own row geocoded into another county: still the roll's claim, its tenant answers
    geo = roll_row("Cleveland", "Madison", "6183")
    assert p.applies(geo) and p.tenant_of(geo) == ("Madison", geo["raw"][p.ROLL_KEY])
    # a roll block merged into another source's row in another county is not trusted
    merged = dict(roll_row("Catawba", "Guilford", "20531"), source="counties_nc.nc_county_pdf_delinquent_tax")
    assert p.tenant_of(merged) == (None, None) and not p.applies(merged)
    # federal / NCDOR / lien-agent rows typed tax_lien are not property-tax claims
    base = {"state": "NC", "county": "Forsyth", "listing_type": "tax_lien", "parcel_id": "6833-46-8791.000", "raw": {}}
    for src in ("counties_nc.nc_ecourts_lis_pendens", "nc_ecourts_judgments", "liensnc",
                "counties_generic.liensnc"):
        assert not p.applies(dict(base, source=src))
    assert p.applies(dict(base, source="law_firms.zacchaeus", listing_type="tax_sale"))
    assert p.applies(dict(base, source="liensnc",
                          raw={"two_year_delinquent": {"is_two_year_plus": True}}))


def test_parcel_candidates_order_and_placeholders():
    row = roll_row("Henderson", "Henderson", "106725", board_parcel="9569787829",
                   raw={p.ROLL_KEY: {"tenant": "Henderson", "parcel": "106725", "parcel_raw": "0"},
                        "lrcpwa": {"reid": "106725"}})
    t, blk = p.tenant_of(row)
    assert p.parcel_candidates(row, t, blk) == [("106725", "roll_block"),
                                                ("9569787829", "board_parcel")]
    assert p.parcel_candidates({"county": "Pitt", "parcel_id": None, "raw": {}}, "Pitt", None) == []


def test_delinquency_starts_january_6():
    assert p.delinquent_from(2025) == date(2026, 1, 6)
    assert not p.is_eligible(2025, date(2026, 1, 5)) and p.is_eligible(2025, date(2026, 1, 6))
    assert p.latest_eligible(TODAY) == 2025


# ---------------------------------------------------------------------------
# verdicts on real answers
# ---------------------------------------------------------------------------

def test_confirmed_henderson_2001_balance_with_county_flags():
    url = search_url("106725", "Henderson")
    owner = owner_in(url)
    row = roll_row("Henderson", "Henderson", "106725", year="2001",
                   bill="0000104428-2001-2001-0000-00", board_parcel="9569787829", owner_name=owner)
    f = served()
    res = run(row, f)
    ev = res.evidence
    assert res.verdict == "confirmed" and res.signal == "tax_lien"
    assert res.verifier == "tax_lien_ptscloud" and res.source == "bcpwa.ncptscloud.com"
    assert ev["delinquent_by_year"] == {"2001": 277.79} and ev["total_delinquent"] == 277.79
    assert ev["flags"] == ["DLQ", "UNDER RESEARCH"]
    assert ev["not_yet_delinquent_due"] == {"2026": 901.19}
    assert ev["tax_parcel"] == "106725" and ev["tax_parcel_from"] == "roll_block"
    # the query also matched bill 0000106725 of another parcel: only parcelId 106725 is read
    assert ev["searched"] == [{"parcel": "106725", "from": "roll_block", "bills": 34}]
    assert ev["results_total"] == 35
    assert ev["owner_match"] == "same" and owner.upper() not in json.dumps(res.to_dict()).upper()
    assert f.asked == [url]


def test_confirmed_many_years_forsyth():
    res = run(roll_row("Forsyth", "Forsyth", "6826-81-5289.000", year="2006"), served())
    assert res.verdict == "confirmed"
    assert sorted(res.evidence["delinquent_by_year"]) == ["2001", "2002", "2003", "2004", "2005", "2006"]
    assert res.evidence["total_delinquent"] == 5878.52 and not res.evidence["under_500"]


def test_confirmed_de_minimis_on_a_roll_row_geocoded_elsewhere():
    row = roll_row("Hyde", "Pitt", "78006", board_parcel="9500189104")
    res = run(row, served())
    assert res.verdict == "confirmed"
    assert res.evidence["total_delinquent"] == 12.64 and res.evidence["de_minimis"] is True
    assert res.evidence["claim_county_differs"] is True and res.evidence["tenant"] == "Pitt"


def test_stale_hyde_2021_paid_after_interest_began():
    row = roll_row("Hyde", "Hyde", "15796", year="2021", bill="0000169265-2021-2021-0000-00")
    res = run(row, served())
    assert res.verdict == "stale"
    c = res.evidence["bills_checked"][0]
    assert c["year"] == 2021 and c["paid_late"] is True
    assert c["paid_on"] == "2026-10-05" and c["paid_on"] >= c["interest_begin"]
    assert c["url"] == detail_url("309316", "Hyde")
    assert c["page_url"] == "https://bcpwa.ncptscloud.com/hyde/bill-detail/309316"


def test_refuted_orange_paid_before_interest():
    row = {"state": "NC", "county": "Orange", "parcel_id": "9857427149", "listing_type": "tax_lien",
           "source": "test", "raw": {"two_year_delinquent": {"is_two_year_plus": True, "tax_year": "2024"}}}
    f = served()
    res = run(row, f)
    assert res.verdict == "refuted"
    checks = res.evidence["bills_checked"]
    assert [c["year"] for c in checks] == [2024, 2025]
    assert all(c["paid_late"] is False and c["paid_on"] < c["interest_begin"] for c in checks)
    assert res.evidence["note"].startswith("only the current levy")
    assert len(f.asked) == 3                         # one search, two bill pages


def test_other_lien_listing_is_never_suppressed():
    """A lien-agent row carrying a delinquency flag on the same parcel: a stale property-tax
    answer would also remove that row's own tax_lien listing signal, so it is not published."""
    row = {"state": "NC", "county": "Hyde", "parcel_id": "9501107720", "listing_type": "tax_lien",
           "source": "liensnc", "raw": {"lrcpwa": {"reid": "15796"},
                                        "two_year_delinquent": {"is_two_year_plus": True, "tax_year": "2021"}}}
    res = run(row, served())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "other_lien_listing"
    assert res.evidence["property_tax_verdict"] == "stale"
    assert res.evidence["tax_parcel_from"] == "lrcpwa_reid"


def test_falls_back_to_the_next_parcel_number():
    empty = FX[search_url("5686016641", "Beaufort")]                 # a real "nothing found"
    row = roll_row("Henderson", "Henderson", "9569787829", year="2001",
                   raw={p.ROLL_KEY: {"tenant": "Henderson", "parcel": "9569787829"},
                        "lrcpwa": {"reid": "106725"}})
    res = run(row, served(**{search_url("9569787829", "Henderson"): empty}))
    assert res.verdict == "confirmed"
    assert [s["from"] for s in res.evidence["searched"]] == ["roll_block", "lrcpwa_reid"]
    assert res.evidence["tax_parcel"] == "106725"


def test_not_found_is_unconfirmed():
    row = {"state": "NC", "county": "Beaufort", "parcel_id": "5686016641", "listing_type": "tax_sale",
           "source": "x", "raw": {}}
    res = run(row, served())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_not_found"


def test_parcel_record_ended_is_unconfirmed():
    """A parcel whose billing stops before the latest delinquent-eligible levy (a retired PIN):
    the real Hyde answer cut to its bills of 2023 and earlier, all paid."""
    url = search_url("15796", "Hyde")
    body = json.loads(FX[url])
    body["results"] = [r for r in body["results"] if int(r["taxYear"]) <= 2023]
    res = run(roll_row("Hyde", "Hyde", "15796", year="2021"), served(**{url: json.dumps(body)}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_record_ended"
    assert res.evidence["latest_delinquent_eligible_levy"] == 2025
    assert res.evidence["latest_levy_year"] == 2023


def test_unreadable_bill_page_is_unconfirmed():
    row = roll_row("Hyde", "Hyde", "15796", year="2021", bill="0000169265-2021-2021-0000-00")
    res = run(row, served(**{detail_url("309316", "Hyde"): "<html>maintenance</html>"}))
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] in ("bill_details_unreadable",)


def test_a_failing_tenant_is_skipped_for_the_rest_of_the_run():
    f = ReplayFetcher({})                               # every request fails
    r1 = run(roll_row("Pitt", "Pitt", "1"), f)
    r2 = run(roll_row("Pitt", "Pitt", "2"), f)
    assert r1.evidence["reason"] == r2.evidence["reason"] == "fetch_failed"
    n = len(f.asked)
    r3 = run(roll_row("Pitt", "Pitt", "3"), f)
    assert r3.verdict == "unconfirmed" and r3.evidence["reason"] == "tenant_unhealthy"
    assert len(f.asked) == n
    # another tenant is unaffected
    r4 = run(roll_row("Madison", "Madison", "6183", board_parcel=None), served())
    assert r4.verdict == "confirmed"


def test_searches_are_cached_for_the_run():
    f = served()
    run(roll_row("Madison", "Madison", "6183"), f)
    run(roll_row("Cleveland", "Madison", "6183"), f)
    assert f.asked == [search_url("6183", "Madison")]


@pytest.mark.parametrize("row", [
    roll_row("Henderson", "Henderson", "106725", year="2001"),
    roll_row("Hyde", "Hyde", "15796", year="2021"),
])
def test_evidence_is_a_whitelist_without_names(row):
    res = run(dict(row, owner_name="TESTOWNER01, PAT"), served())
    assert set(res.evidence) <= set(p._KEYS)
    blob = json.dumps(res.to_dict()).upper()
    for url, body in FX.items():
        for r in (json.loads(body).get("results") or []):
            for k in ("ownerName1", "ownerName2"):
                if r.get(k):
                    assert r[k].upper() not in blob
    assert p.ROW_SUMMARY_EXCLUDE == ("owner_name",)
