"""tax_lien_perquimans: the county tax search against the newspaper list's rows (made-up pages)."""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import tax_lien_perquimans as V

MAP = "9-X999-0001-ZZ"
URL = V.SEARCH_URL.format(q=MAP)


def _block(account, owner, due, parts, map_str=MAP):
    types = "PTax|PDMV|HTax|HDMV|HMFee|WTax|WDMV|WMFee|HDept|CDFee|PDFee|CPerry|Gates"
    amounts = "|".join(f"{parts.get(t, 0):.2f}" for t in types.split("|"))
    return f"""
<TR><TD ALIGN=RIGHT>Tax Account Number</TD><TD ALIGN=LEFT>{account}</TD><TD ALIGN=CENTER COLSPAN=2>Taxes Due Break Down</TD></TR>
<TR><TD ALIGN=RIGHT VALIGN=TOP>Owner</TD><TD VALIGN=TOP>
   {map_str}<BR>
   {owner},<BR>
   1 EXAMPLE MAILING ST<BR>
   NOWHERE, NC 27900<BR>
   <CENTER><FONT SIZE=+1><B>Taxes Due ${due:,.2f}</B></FONT><BR>
   <INPUT TYPE='hidden' NAME='cde-PaymType-1' VALUE='{types}'>
   <INPUT TYPE='hidden' NAME='cde-PaymAmou-2' VALUE='{amounts}'>
   </CENTER></TD></TR>"""


def _page(*blocks):
    return "<HTML><BODY><B>Search Results.</B>" + "".join(blocks) + "</BODY></HTML>"


def _row(owner="EXAMPLE, ELLA & HUSBAND", **kw):
    r = {"state": "NC", "county": "Perquimans", "parcel_id": MAP, "owner_name": owner,
         "listing_type": "tax_lien", "source": "counties_nc.albemarle_observer_tax_lists",
         "raw": {"albemarle_observer_tax_list": {"county": "Perquimans", "parcel": MAP, "owner": owner,
                                                 "post_date": "2026-06-11", "list_year": 2025,
                                                 "total_due": 100.0}}}
    r.update(kw)
    return r


def _run(row, page):
    f = ReplayFetcher({URL: page} if page is not None else {})
    return asyncio.run(V.verify(row, f, today=date(2026, 10, 9))), f


def test_registered_with_the_shared_tax_lien_contract():
    v = {x.name: x for x in registry.discover()}["tax_lien_perquimans"]
    assert v.signal == "tax_lien" and v.governs and not v.wall


def test_applies_only_to_perquimans_newspaper_rows():
    assert V.applies(_row())
    assert not V.applies(_row(county="Chowan", raw={}))
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(listing_type="lis_pendens", raw={}))


def test_parse_accounts_splits_property_tax_from_vehicle_tax_and_fees():
    page = _page(_block("111", "EXAMPLE, ELLA & HUSBAND", 130.0, {"PTax": 100.0, "PDMV": 20.0, "HMFee": 10.0}))
    a = V.parse_accounts(page)
    assert len(a) == 1 and a[0]["account"] == "111" and a[0]["map"] == MAP
    assert a[0]["due"] == 130.0 and a[0]["property_due"] == 100.0 and a[0]["other_due"] == 30.0
    assert a[0]["owner"] == "EXAMPLE, ELLA & HUSBAND"


def test_confirmed_when_the_rows_owner_still_owes_property_tax():
    page = _page(_block("111", "EXAMPLE, ELLA & HUSBAND", 130.0, {"PTax": 100.0, "HTax": 30.0}),
                 _block("222", "OTHER, PERSON", 500.0, {"PTax": 500.0}))
    r, f = _run(_row(), page)
    assert r.verdict == "confirmed" and f.asked == [URL]
    assert r.evidence["property_tax_due"] == 130.0 and r.evidence["accounts_on_map"] == 2
    assert r.evidence["accounts_matched"] == 1 and r.evidence["owner_match"] == "same"
    assert "EXAMPLE" not in str(r.evidence) and "MAILING" not in str(r.evidence)     # public ledger


def test_stale_when_the_account_the_list_named_shows_nothing_due():
    r, _ = _run(_row(), _page(_block("111", "EXAMPLE, ELLA & HUSBAND", 0.0, {})))
    assert r.verdict == "stale" and r.evidence["reason"] == "paid_since_list"


def test_only_vehicle_tax_or_fees_due_is_not_a_property_tax_claim():
    r, _ = _run(_row(), _page(_block("111", "EXAMPLE, ELLA & HUSBAND", 20.0, {"PDMV": 20.0})))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_property_tax_part"


def test_a_different_owner_on_the_map_is_unconfirmed_never_stale():
    r, _ = _run(_row(), _page(_block("333", "NEWCOMER, NORA", 0.0, {})))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "owner_differs"


def test_map_missing_and_fetch_failure_are_unconfirmed():
    r, _ = _run(_row(), "<HTML><BODY>No records</BODY></HTML>")
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "map_not_on_site"
    r, _ = _run(_row(), None)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"
    assert "fetch_failed" in V.TRANSIENT_REASONS
    r, f = _run(_row(parcel_id=None, raw={}), "x")
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_unresolvable" and f.asked == []


def test_one_search_per_map_per_run():
    page = _page(_block("111", "EXAMPLE, ELLA & HUSBAND", 130.0, {"PTax": 130.0}))
    f = ReplayFetcher({URL: page})

    async def both():
        a = await V.verify(_row(), f, today=date(2026, 10, 9))
        b = await V.verify(_row(owner="EXAMPLE, ELLA & HUSBAND"), f, today=date(2026, 10, 9))
        return a, b
    a, b = asyncio.run(both())
    assert a.verdict == b.verdict == "confirmed" and f.asked == [URL]
