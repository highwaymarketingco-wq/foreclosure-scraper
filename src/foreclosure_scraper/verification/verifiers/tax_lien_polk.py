"""tax_lien, Polk County NC: is there still a real unpaid county property-tax balance on this
specific record, read live from the county's own per-record detail page?

WHY (2026-11-18, gap_matrix verify-sweep round 25, following up round 24's scoping). Polk had
2,751 board rows typed tax_lien/tax_sale and NO verifier at all (round 23/24 confirmed: no
tax_lien_*.py module names Polk; the county's delinquent-search form itself
-- searchtaxrecord.php / searchingtaxrecord.php -- needs a Cloudflare-bot-management bypass
(nodriver, headless=False) that is this codebase's own Hermes boundary (CLAUDE.md), not a
verifier's). Round 24 live-counted the real split (read-only board_stream.iter_board_rows, no
lock needed): of Polk's 2,751 tax_lien/tax_sale rows, 996 (36.2%) carry a `detail_id` of their
own (written by scrapers/counties_nc/polk_tax.py's `_fetch_delinquent_search()` -- its own
BalanceDue>0 name-search pass against the current tax year) -- an identifier that answers a
PLAIN GET, no browser, no WAF bypass, confirmed live 2026-10-13 (that scraper's own module
docstring and tests/test_polk_tax_detail_enrichment.py's real captures). The other 1,755
(63.8%, mostly the Kania auction page's parcel-only rows, which carry a `raw.polk_tax` block
instead -- opening_bid + parcel, no detail_id at all) would need the Cloudflare-gated search
form to find a detail_id in the first place -- out of scope here, same as every other
verifier's own declared boundary in this codebase.

THE CALL (polk_tax.py's own `_fetch_detail`, live-verified 2026-10-13, module docstring there):
    GET https://cms.revize.com/revize/apps/polkcounty/taxdetail.php?id=<detail_id>
      -> HTML: Status, Total Due, Collection Status, Owner Name, Owner ID, Tax Receipt Number,
         Bill Number, Parcel Number (blank for a mobile-home-only bill), Mailing Address,
         District, Type, Description, Assessed Value, Base Amount, Charges.
Three confirmed-live "not a real record" shapes, all already rejected by the EXISTING parser
(never this verifier's own code): id=0's "No Tax Record was requested..." notice; a
negative/non-numeric/nonexistent id's literal unrendered-SQL echo; an intermittent Cloudflare
"Just a moment" challenge that slips past the fetch's own retry.

SAME PARSER, DIFFERENT TRANSPORT (the tax_lien_ustaxdata.py pattern, same session, one signal
over): this verifier calls `polk_tax._parse_detail_html` VERBATIM, unedited -- it is already
unit-tested against real captured HTML (tests/test_polk_tax_detail_enrichment.py) and there is
no reason to re-derive its field regexes here. Only the HTTP transport is rebuilt: the sweep's
Fetcher (`client.get_text(url, impersonate=True)`, the per-host-throttled, capture/replay-able
transport every other verifier here uses) in place of the scraper's own direct
`get_text_impersonate` call -- confirmed by that scraper's own module docstring that a plain GET
with a curl-cffi Chrome TLS/JA3 fingerprint is ALL this one endpoint needs (`impersonate=True`
asks the Fetcher for exactly that tier; it tries a plain fetch first and escalates on a
403/406, so this is a strict superset of what the scraper's own direct call already does, not a
weaker substitute).

NO SEARCH, NO BINDING AMBIGUITY (unlike tax_lien_itspublic / tax_lien_ptscloud / tax_lien_wake,
which must prove they found the RIGHT account among several search candidates). This verifier
never searches: `detail_id` is the row's OWN id, captured by the scraper at discovery time
directly off the search-RESULT row this exact board row came from (polk_tax.py's
`_parse_search_html`). Re-fetching that same id and reading what it says TODAY is the whole
check -- there is no second candidate to rule out. A defensive parcel-number cross-check still
guards the one way this could still go wrong (the id is stale and the county reassigned it to a
different record since): see `verify()`'s `id_mismatch` branch.

VERDICTS (mirrors tax_lien_ustaxdata.py's own rule for a vendor with no bill-history page: this
source shows what is owed on ONE record right now, not a multi-year ledger):
  confirmed    the record is still found and its own Total Due reads a real amount (> 0) today.
  stale        the record is still found and its own Total Due reads exactly $0.00: the balance
               the scraper saw has been paid (or otherwise resolved) since.
  unconfirmed  no `detail_id` on the row (out of this verifier's scope, applies() already says
               so); the fetch failed or the site was unreachable (fetch_failed, retried on the
               transient cadence); the id answered one of the three "not a real record" shapes
               above (record_not_found) or a shape whose own Total Due field could not be read
               at all despite a real record being found (no_amount_on_record -- never guessed at
               as stale); the record's own Parcel Number now names a DIFFERENT parcel than this
               row's own (id_mismatch -- see NO SEARCH, NO BINDING AMBIGUITY above).
  refuted      never: like every sibling tax_lien verifier here, this source has no payment-DATE
               field (only a resulting Total Due figure), so a bill paid before it was ever late
               cannot be told from one paid after -- there is no evidence here to refute on.

Evidence is a whitelist (public ledger): no owner names, no mailing addresses, no tax receipt /
owner id numbers. The county's own Parcel Number is published (tc._KEYS below) -- the same
choice tax_lien_itspublic.py already makes for its own AccountNumber: a county record
identifier, not a person's name.
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
SOURCE = "cms.revize.com (Polk County NC delinquent tax detail page)"
GOVERNS = tc.GOVERNS
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
#: fetch_failed only: record_not_found / id_mismatch / no_amount_on_record are about THIS
#: record's own shape, not the site's health, so they keep the normal RETRY_DAYS cadence
TRANSIENT_REASONS = ("fetch_failed",)

COUNTY = "polk"
#: only this scraper ever writes the raw['polk_tax_search']['detail_id'] block this verifier
#: reads (module docstring) -- the auction-page rows share the same `source` value but carry a
#: DIFFERENT block (raw['polk_tax'], parcel + opening_bid, no detail_id at all)
SOURCE_SLUG = "counties_nc.polk_tax"
_BLOCK_KEY = "polk_tax_search"
_NAME = __name__.rsplit(".", 1)[-1]


def _polk_tax():
    """scrapers.counties_nc.polk_tax, imported lazily on first use -- the registry imports every
    verifier module at discovery time, and that scraper's own module-level imports
    (browser_utils, nodriver) must not load in just to answer applies(). The same lazy-import
    idiom tax_lien_ustaxdata.py's own _utx() uses for enrichment_ustaxdata_tax_search."""
    from ...scrapers.counties_nc import polk_tax as m
    return m


def _block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(_BLOCK_KEY)
    return b if isinstance(b, dict) else None


def detail_id_of(row: Any) -> Optional[str]:
    """The row's own taxdetail.php?id=N identifier (polk_tax.py's own `_parse_search_html`
    writes it, module docstring), or None for a row with no such block -- the auction-page rows,
    64% of Polk's tax_lien/tax_sale total, deliberately left out of this verifier's scope (module
    docstring)."""
    v = str((_block(row) or {}).get("detail_id") or "").strip()
    return v if v.isdigit() else None


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    if str(tc.g(row, "county") or "").strip().replace(" County", "").lower() != COUNTY:
        return False
    if str(tc.g(row, "source") or "") != SOURCE_SLUG:
        return False
    if detail_id_of(row) is None:
        return False
    # own_block=True: a row carrying this scraper's own detail_id IS, by construction, this
    # verifier's own claim about the row (module docstring, NO SEARCH, NO BINDING AMBIGUITY) --
    # the same idiom tax_lien_york.py's applies() uses for its own single-source rows.
    return tc.claims_property_tax(row, True)


_KEYS = ("reason", "url", "detail_id", "status", "total_due", "parcel_number",
         "balance_under_25", "error")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION,
                 verifier=_NAME)


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    detail_id = detail_id_of(row)
    if not detail_id:
        return _res("unconfirmed", {"reason": "no_detail_id"})
    m = _polk_tax()
    url = f"{m._SEARCH_BASE}/taxdetail.php?id={detail_id}"
    ev: dict[str, Any] = {"detail_id": detail_id, "url": url}

    try:
        html = await client.get_text(url, timeout=20.0, impersonate=True)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))

    # the EXISTING, already-tested parser, unedited (module docstring, SAME PARSER, DIFFERENT
    # TRANSPORT) -- it already returns {} for every one of the three "not a real record" shapes
    # (id=0, the SQL-leak echo, a slipped-through Cloudflare challenge).
    extras = m._parse_detail_html(html)
    if not extras:
        return _res("unconfirmed", dict(ev, reason="record_not_found"))

    status = str(extras.get("status") or "").strip()
    if status:
        ev["status"] = status

    parcel = extras.get("parcel_number")
    if parcel:
        ev["parcel_number"] = parcel
        # defensive only (module docstring, NO SEARCH, NO BINDING AMBIGUITY): this id is the
        # row's own, never searched, so this should never actually fire -- but a stale id the
        # county has since reassigned to a different parcel is never confirmed over, the same
        # false-confirmed-avoidance discipline every other tax_lien verifier here keeps.
        row_parcel = str(tc.g(row, "parcel_id") or "").strip()
        if row_parcel and tc.alnum(row_parcel) and tc.alnum(str(parcel)) != tc.alnum(row_parcel):
            return _res("unconfirmed", dict(ev, reason="id_mismatch"))

    total_due = extras.get("total_due")
    if not isinstance(total_due, (int, float)):
        # a real record (owner name matched), but no readable Total Due figure at all -- never
        # seen live (both captured fixtures carry one), so this is read as "cannot tell", not
        # guessed at as paid.
        return _res("unconfirmed", dict(ev, reason="no_amount_on_record"))

    ev["total_due"] = round(float(total_due), 2)
    if total_due > 0:
        ev["balance_under_25"] = total_due < tc.DE_MINIMIS
        return _res("confirmed", ev)
    return _res("stale", dict(ev, reason="paid_since_snapshot"))
