"""enrichment_catawba_multiyear_tax: Catawba County NC multi-year delinquent-tax history, read
live via verification/verifiers/tax_lien_itspublic.py's own live-proven session/search/parse
chain, reused verbatim (not re-implemented). Bill fixtures below use the exact dict shape
tax_lien_itspublic.search() (via parse_rows()) produces: year/bill/owner/ids/situs/original/
balance/in_tax_foreclosure.

The build_block() fixtures mirror real shapes live-read against the real portal 2026-10-20 (see
the module's own docstring): PIN 374117104352 (paid current, correctly yields nothing) and PIN
375005098228 (2024 + 2025 both unpaid and matured -- a genuine, minimum-qualifying multi-year
delinquency).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_itspublic as its
from foreclosure_scraper import enrichment_catawba_multiyear_tax as mod
from foreclosure_scraper.enrichment_catawba_multiyear_tax import (
    build_block, enrich_with_catawba_multiyear_tax, _fetch,
)

TODAY = date(2026, 10, 20)
PORTAL = its.PORTALS["Catawba"]
PIN = "375005098228"


def bill(year, reid, pin, situs, original, balance, *, acres="0.300 AC", foreclosure=False):
    """One ITSPublic-shaped bill dict, the same keys tax_lien_itspublic.parse_rows() emits.
    `acres=None` reproduces Catawba's own real_without_units quirk (bills before levy 2025
    print no acreage at all -- real_without_units still counts them as real property)."""
    pin16 = f"{pin}0000"
    ids = [reid, pin16, pin]  # pin_pad auto-adds the unpadded PIN (parse_description)
    return {"year": year, "bill": str(reid).lstrip("0") or "0", "owner": "TESTOWNER ALPHA",
            "ids": ids, "situs": situs, "original": original, "balance": balance,
            "in_tax_foreclosure": foreclosure}


def _li(parcel=PIN, county="Catawba", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.nc_county_pdf_delinquent_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# build_block -- pure, using the live-shaped dollar figures from recon
# ---------------------------------------------------------------------------

def test_real_shaped_two_matured_years_qualifies():
    """Real board PIN 375005098228, live-verified 2026-10-20: 2026 current ($242.67, not yet
    due), 2025 ($266.90) and 2024 ($291.74) both unpaid and matured, 2023/2022/2021 paid."""
    bills = [
        bill(2026, "0901674", PIN, "1 TEST DR", 242.67, 242.67),
        bill(2025, "0901674", PIN, "1 TEST DR", 242.67, 266.90),
        bill(2024, "2907636", PIN, "1 TEST DR", 245.22, 291.74),
        bill(2023, "2907636", PIN, "1 TEST DR", 245.22, 0.0),
        bill(2022, "2907636", PIN, "1 TEST DR", 85.86, 0.0),
    ]
    block = build_block(PIN, bills, today=TODAY)
    assert block is not None
    assert block["years"] == [2024, 2025, 2026]
    assert block["matured_years"] == [2024, 2025]
    assert block["years_delinquent"] == 2
    assert block["total_due"] == round(242.67 + 266.90 + 291.74, 2)
    assert block["matured_owed"] == round(266.90 + 291.74, 2)
    assert block["current_levy_year"] == 2026 and block["in_current_levy"] is True
    assert block["amount_basis"] == "annual_bill"
    assert block["parcel_key"] == PIN
    assert "taxbill.catawbacountync.gov" in block["source_url"]


def test_paid_current_parcel_does_not_qualify():
    """Real board PIN 374117104352 (the exact example tax_lien_itspublic.py's own docstring
    uses), live-verified 2026-10-20: every year paid except the current, not-yet-due bill."""
    pin = "374117104352"
    bills = [bill(2026, "0027012", pin, "2 TEST DR", 5505.07, 5505.07)]
    for y, reid, orig in ((2025, "0027012", 5505.07), (2024, "1682933", 5505.07),
                          (2023, "1682933", 5505.07), (2022, "1682933", 2973.71)):
        bills.append(bill(y, reid, pin, "2 TEST DR", orig, 0.0))
    assert build_block(pin, bills, today=TODAY) is None


def test_single_unpaid_year_fails_gate():
    bills = [bill(2026, "0000001", PIN, "3 TEST DR", 100.0, 100.0)]
    assert build_block(PIN, bills, today=TODAY) is None


def test_two_unpaid_years_both_current_does_not_qualify():
    """Current-year-only bills (no levy past its delinquent date) must not read as repeat
    delinquency -- same guard as Wake's/Randolph's/Gaston's own enrichments."""
    bills = [bill(2026, "0000002", PIN, "4 TEST DR", 50.0, 50.0),
            bill(2027, "0000002", PIN, "4 TEST DR", 60.0, 60.0)]
    assert build_block(PIN, bills, today=TODAY) is None


def test_paid_years_never_surface_as_unpaid():
    bills = [bill(2025, "0000003", PIN, "5 TEST DR", 30.0, 0.0),
            bill(2024, "0000003", PIN, "5 TEST DR", 30.0, 30.0),
            bill(2023, "0000003", PIN, "5 TEST DR", 32.0, 32.0)]
    block = build_block(PIN, bills, today=TODAY)
    assert block["years"] == [2023, 2024]
    assert 2025 not in block["years"]


def test_ignores_bills_for_a_different_parcel():
    """A search answers only the submitted AlternateParcelIdentifier already, but build_block's
    own id-match is a belt-and-suspenders check, same discipline as tax_lien_itspublic.bills_of()
    / enrichment_randolph_multiyear_tax's own parcel guard."""
    other = bill(2023, "0000005", "999999999999", "9 OTHER ST", 999.0, 999.0)
    bills = [bill(2024, "0000004", PIN, "6 TEST DR", 30.0, 30.0),
            bill(2023, "0000004", PIN, "6 TEST DR", 32.0, 32.0), other]
    block = build_block(PIN, bills, today=TODAY)
    assert block["years"] == [2023, 2024]
    assert block["total_due"] == 62.0  # the other parcel's $999 never counted


def test_duplicate_year_keeps_larger_not_sum():
    bills = [bill(2024, "0000006", PIN, "7 TEST DR", 10.0, 10.0),
            bill(2024, "0000006", PIN, "7 TEST DR", 40.0, 40.0),
            bill(2023, "0000006", PIN, "7 TEST DR", 5.0, 5.0)]
    block = build_block(PIN, bills, today=TODAY)
    assert block["per_year"]["2024"] == 40.0
    assert block["total_due"] == 45.0


def test_real_without_units_bill_still_counts_as_qualifying_history():
    """Catawba's own quirk (Portal.real_without_units, live-confirmed 2026-10-20): bills before
    levy 2025 print no acreage at all. tax_lien_itspublic.parse_rows() already resolves this
    before build_block ever sees the bill -- this fixture proves build_block doesn't need its
    own acreage logic, only the already-parsed `ids`/`balance`/`year` shape."""
    bills = [bill(2026, "0000007", PIN, "8 TEST DR", 20.0, 20.0, acres=None),
            bill(2025, "0000007", PIN, "8 TEST DR", 18.0, 18.0, acres=None),
            bill(2024, "0000007", PIN, "8 TEST DR", 17.0, 0.0, acres=None)]
    block = build_block(PIN, bills, today=TODAY)
    assert block["years"] == [2025, 2026]
    assert block["matured_years"] == [2025]


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_enrich_eligible_only_catawba_nc_with_parcel():
    eligible = _li()
    wrong_county = _li(county="Wake")
    wrong_state = _li(state="SC", county="Catawba")
    no_parcel = _li(parcel="")
    already = _li(raw={"_catawba_mydt_checked": "insufficient_history"})
    rows = [eligible, wrong_county, wrong_state, no_parcel, already]
    targets = [li for li in rows if mod._eligible(li)]
    assert targets == [eligible]


# ---------------------------------------------------------------------------
# _fetch / enrich_with_catawba_multiyear_tax -- the live session/search chain, faked
# ---------------------------------------------------------------------------

class FakeITSPublic:
    """A Catawba-shaped ITSPublic portal in memory: full_model (every .search-value field
    required), session kept server-side, same shape as the real vendor and as
    tests/test_verification_tax_lien_itspublic.py's own FakePortal. No network."""

    def __init__(self, bills):
        self.bills = bills
        self.model = None

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, **_):
        return FormResponse(200, url, "<html>Tax Bill Search</html>")

    async def post_form(self, url, data, **_):
        if url.endswith("/GetSearchTablePartial/"):
            self.model = dict(data)
            return FormResponse(200, url, '<script>PopulateTable("PayTaxBills", \'\');</script>')
        if url.endswith("/GetSearchTableData"):
            rows = [self._row(b) for b in self._match()]
            return FormResponse(200, url, json.dumps({"total": 1, "numRecords": len(rows), "rows": rows}))
        return FormResponse(404, url, "")

    def _match(self):
        want = (self.model or {}).get("AlternateParcelIdentifier")
        if not want:
            return []
        return [b for b in self.bills if tc.alnum(want) in {tc.alnum(i) for i in b["ids"]}]

    @staticmethod
    def _row(b):
        parts = list(b["ids"])
        if b["situs"]:
            parts.append(b["situs"])
        desc = "<br/>".join(parts)
        action = "<button title='Add to Cart'>Pay</button>"
        return {"id": f"{b['year']}/{b['bill']}",
                "cell": [str(b["year"]), b["bill"], "900000001", b["owner"], desc,
                        f"{b['original']:,.2f}", f"{b['balance']:,.2f}", action]}


def test_fetch_ok_path_reuses_tax_lien_itspublic_verbatim():
    bills = [bill(2024, "0000008", PIN, "9 TEST DR", 30.0, 30.0),
            bill(2023, "0000008", PIN, "9 TEST DR", 32.0, 32.0)]
    f = FakeITSPublic(bills)
    got, status = run(_fetch(f, PIN))
    assert status == "ok"
    assert {b["year"] for b in got} == {2023, 2024}


def test_fetch_no_bills():
    f = FakeITSPublic([])
    got, status = run(_fetch(f, PIN))
    assert (got, status) == (None, "no_bills")


def test_enrich_end_to_end_qualifies_and_stamps_block():
    bills = [bill(2026, "0000009", PIN, "10 TEST DR", 100.0, 100.0),
            bill(2025, "0000009", PIN, "10 TEST DR", 50.0, 50.0),
            bill(2024, "0000009", PIN, "10 TEST DR", 52.0, 52.0)]
    li = _li()
    f = FakeITSPublic(bills)
    stats = run(enrich_with_catawba_multiyear_tax([li], client=f))
    assert stats["eligible"] == 1 and stats["qualified"] == 1
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025, 2026]
    assert li.raw["multi_year_delinquent_tax"]["matured_years"] == [2024, 2025]


def test_enrich_insufficient_history_stamps_checked_sentinel_not_block():
    bills = [bill(2026, "0000010", PIN, "11 TEST DR", 100.0, 100.0)]
    li = _li()
    f = FakeITSPublic(bills)
    stats = run(enrich_with_catawba_multiyear_tax([li], client=f))
    assert stats["qualified"] == 0 and stats["insufficient_history"] == 1
    assert "multi_year_delinquent_tax" not in li.raw
    assert li.raw["_catawba_mydt_checked"] == "insufficient_history"


def test_enrich_no_bills_stamps_checked_sentinel():
    li = _li()
    f = FakeITSPublic([])
    stats = run(enrich_with_catawba_multiyear_tax([li], client=f))
    assert stats["no_bills"] == 1
    assert li.raw["_catawba_mydt_checked"] == "no_bills"


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"years": [1999], "manual": True}
    li = _li(raw={"multi_year_delinquent_tax": sentinel})
    f = FakeITSPublic([])
    stats = run(enrich_with_catawba_multiyear_tax([li], client=f))
    assert stats["eligible"] == 0
    assert li.raw["multi_year_delinquent_tax"] is sentinel
