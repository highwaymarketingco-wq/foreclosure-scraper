"""tax_lien, ustaxdata.com tenants (NC): is there a real delinquent property-tax balance on this
parcel today?

A tax_lien adapter beside tax_lien_buncombe (the reference) and tax_lien_perquimans: same
SIGNAL, same GOVERNS, same verdict meanings, one tax_lien ledger. No existing verifier read
ustaxdata.com at all before this (confirmed by grepping every tax_lien_*.py's own vendor
hostname -- see project_verify_layer_survey_2026-11-16.md, Finding 2 -- tax_aging_surfaced's
Rockingham cell, 24 rows, was one of 7 counties that cell flagged `built-not-verified`).

GENERIC OVER THE LIVE REGISTRY, NOT A HARDCODED COUNTY (the code_enforcement_adl.py fix-shape):
applies()/verify() read enrichment_ustaxdata_tax_search.py's own TENANTS (direct parcel-number
search: currently Robeson) and NAME_SEARCH_TENANTS (owner-name search, address-confirmed:
currently Alexander, Rockingham) dicts every call, so a future tenant that module adds is
covered here for free, with no edit to this file.

REUSES enrichment_ustaxdata_tax_search.py's OWN pure parsing/query-building functions verbatim,
unedited: search_url, search_url_by_name, parse_results, _confirm_by_address, bill_detail_url,
parse_bill_detail. Only the HTTP transport is rebuilt (`client.get_text`, the sweep's Fetcher/
ReplayFetcher, in place of that module's own httpx client) -- confirmed live 2026-11-16 that no
session/cookie is needed for either the search page or the bill-detail page (a plain GET on
each, the same shape that module's own enrich_ustaxdata() already uses).

THE SUMMARY TABLE HAS NO DOLLAR AMOUNT (enrichment module's own finding, repeated here because
it drives this verifier's own two-hop shape): a year's real balance lives one click deeper, on
taxbill.cfm. This verifier only fetches that detail page for years the summary itself marks
unpaid/partial (at most MAX_DETAIL_FETCHES, newest first -- parse_results() already orders
newest-first), never the whole history of a parcel that is current.

LIVE-CONFIRMED 2026-11-16 (tests/fixtures/verification/tax_lien_ustaxdata.json.gz, captured
through the real Fetcher against the real site):
  Rockingham, 3 real board rows (WEBSTER RICHARD heirs/1090 K Fork Rd, HALL ELMA WATKINS
  estate/1398 Anglin Mill Rd, DILLARD S ARTHUR heirs/1535 Price Rd): name search + address
  confirms exactly one account each, every one carries a real 2025/2026 unpaid balance that
  matches the board's own cached raw['ustaxdata_delinquent_tax'] almost to the cent -> confirmed.
  Robeson parcel 021903073 (the enrichment module's own 2026-10-16 example, re-fetched live
  today): still 13/13 bills paid -> stale, were this row's own claim ever to name it.
  Robeson, a made-up parcel number: 0 records -> unconfirmed, parcel_not_found.

VERDICTS (mirrors tax_lien_perquimans's own rule: this vendor shows what is owed now, not what
the board's own aging/list snapshot held):
  confirmed    a matched account's unpaid/partial year's own taxbill.cfm shows a real amount
               still owed (> 0) today. Evidence: the amount due, the years checked.
  stale        the matched account carries bill history (so the search did find it) but no
               unpaid/partial year at all, or every unpaid/partial year's own detail page reads
               $0.00 now: the delinquency the board named has been paid since.
  unconfirmed  no usable search key (TENANTS: no parcel_id on the row; NAME_SEARCH_TENANTS: no
               owner_name, or an owner_name but no street_address to confirm an account with) /
               the county isn't a tenant of either registry / the search answered zero records
               (parcel_not_found) / NAME_SEARCH_TENANTS found bills but no single account
               address-matches (ambiguous_account) / every unpaid/partial detail page it tried
               came back with no readable "TOTAL" figure, e.g. Alexander's own known taxbill.cfm
               outage (detail_unreadable) / the site did not answer (fetch_failed, retried in
               RETRY_DAYS).
  refuted      never: same rule as every sibling tax_lien verifier here.

Evidence is a whitelist (public ledger): no owner names, no mailing lines. The vendor's own
account number is published (bills_matched's `account`) -- it is the vendor's own search
result identifying a tax account, not a person's name, the same choice tax_lien_itspublic.py's
evidence already makes for AccountNumber.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 7
SOURCE = "ustaxdata.com (NC county tax-bill search)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "detail_unreadable")

#: at most this many unpaid/partial years' own taxbill.cfm fetched per row, newest first (module
#: doc, THE SUMMARY TABLE HAS NO DOLLAR AMOUNT) -- bounds the per-row network cost the same way
#: _tax_common.MAX_HISTORY_BILLS bounds Buncombe/PTS Cloud's own bill-history reads
MAX_DETAIL_FETCHES = 6

_NAME = __name__.rsplit(".", 1)[-1]
_BLOCK_KEY = "ustaxdata_delinquent_tax"


def _utx():
    """enrichment_ustaxdata_tax_search.py, imported on first use (the registry imports every
    verifier; the full enrichment stack must not load in just to answer applies())."""
    from ... import enrichment_ustaxdata_tax_search as m
    return m


def _block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(_BLOCK_KEY)
    return b if isinstance(b, dict) else None


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    m = _utx()
    key = m._county_key(tc.g(row, "county"))
    if key not in m._TENANTS_CI and key not in m._NAME_SEARCH_TENANTS_CI:
        return False
    return tc.claims_property_tax(row, _block(row) is not None)


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


_KEYS = ("reason", "url", "county", "account", "bills_on_account", "years_checked",
         "amount_due", "checked_on", "error")


async def _fetch_detail(client: Any, county: str, bill: dict, ev: dict) -> Optional[float]:
    """The real amount still owed on one unpaid/partial bill, or None when the detail page
    carried no readable figure (Alexander's own known outage; parse_bill_detail degrades to {}
    rather than guessing, module doc)."""
    m = _utx()
    url = m.bill_detail_url(county, bill.get("account"), bill.get("bill_no"), bill.get("year"))
    if not url:
        return None
    try:
        html = await client.get_text(url, timeout=30)
    except Exception:  # noqa: BLE001 - one unreadable year never fails the whole row
        return None
    return m.parse_bill_detail(html).get("amount_owed")


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    m = _utx()
    county = tc.g(row, "county")
    key = m._county_key(county)
    ev: dict[str, Any] = {"county": county, "checked_on": today.isoformat()}

    if key in m._TENANTS_CI:
        parcel = str(tc.g(row, "parcel_id") or "").strip()
        if not parcel:
            return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
        url = m.search_url(county, parcel)
        ev["url"] = url
        try:
            bills = m.parse_results(await client.get_text(url, timeout=30))
        except Exception as exc:  # noqa: BLE001 - every outcome is an answer
            return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                            error=f"{type(exc).__name__}: {str(exc)[:120]}"))
        if not bills:
            return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
        account = bills[0].get("account")
        mine = [b for b in bills if b.get("account") == account] if account else bills
    elif key in m._NAME_SEARCH_TENANTS_CI:
        owner = tc.g(row, "owner_name")
        addr = tc.g(row, "street_address")
        if not owner:
            return _res("unconfirmed", dict(ev, reason="owner_unresolvable"))
        url = m.search_url_by_name(county, owner)
        if not url:
            return _res("unconfirmed", dict(ev, reason="owner_unresolvable"))
        ev["url"] = url
        try:
            bills = m.parse_results(await client.get_text(url, timeout=30))
        except Exception as exc:  # noqa: BLE001 - every outcome is an answer
            return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                            error=f"{type(exc).__name__}: {str(exc)[:120]}"))
        if not bills:
            return _res("unconfirmed", dict(ev, reason="owner_not_found"))
        if not addr:
            return _res("unconfirmed", dict(ev, reason="ambiguous_account"))
        account = m._confirm_by_address(bills, addr)
        if not account:
            return _res("unconfirmed", dict(ev, reason="ambiguous_account"))
        mine = [b for b in bills if b.get("account") == account]
    else:  # pragma: no cover - applies() already gates this; defensive only
        return _res("unconfirmed", dict(ev, reason="not_a_tenant"))

    ev["account"] = account
    ev["bills_on_account"] = len(mine)
    if not mine:
        return _res("unconfirmed", dict(ev, reason="account_empty"))
    unpaid = [b for b in mine if b.get("status") in ("unpaid", "partial")][:MAX_DETAIL_FETCHES]
    if not unpaid:
        return _res("stale", dict(ev, reason="paid_since_snapshot",
                                  note="the vendor shows every year on this account paid today"))
    ev["years_checked"] = [b.get("year") for b in unpaid]
    total = 0.0
    any_readable = False
    for b in unpaid:
        amt = await _fetch_detail(client, county, b, ev)
        if amt is None:
            continue
        any_readable = True
        total = round(total + amt, 2)
    if not any_readable:
        return _res("unconfirmed", dict(ev, reason="detail_unreadable"))
    ev["amount_due"] = total
    if total > 0:
        return _res("confirmed", ev)
    return _res("stale", dict(ev, reason="paid_since_snapshot",
                              note="every unpaid/partial year's own bill page now reads $0.00"))
