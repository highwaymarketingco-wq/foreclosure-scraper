"""tax_lien, Pasquotank County NC: does the county's own annual NCGS 105-369 delinquent-tax
advertisement STILL list this exact parcel with a real balance due, read live today from the SAME
public PDF the row's own claim was built from?

WHY (2026-11-18, gap_matrix built-not-verified sweep). gap_matrix flagged Pasquotank NC
tax_aging_surfaced as "built-not-verified": 1,804 rows carry a real raw.tax_aging_surfaced claim
(enrichment_pasquotank_delinquent_tax.py's own raw['pasquotank_tax_lien'] feeds it through the
generic enrichment_tax_aging.py reader -- see that producer's own module docstring) but NO
verifier anywhere names Pasquotank: confirmed by grepping every tax_lien_*.py verifier here before
writing this one. The producer's own module docstring already tried every other candidate on the
county's site (payonline/gis-office/delinquent-taxes/tax-sales) and settled on this ONE source,
live-re-verified again tonight (2026-11-18): the SAME PDF_URL answers a plain GET, 1,852 real rows
parsed with the SAME parser this module reuses unedited.

THE CALL (enrichment_pasquotank_delinquent_tax.py, SAME PARSER, DIFFERENT TRANSPORT -- the
tax_lien_polk.py idiom: a producer's already-tested parser, reused verbatim, over a fresh fetch):
    GET https://www.pasquotankcountync.org/s/DTax2026-edmn.pdf
      -> a 3-page, text-extractable PDF (pdfplumber), one dot-leader row per real-estate account:
         "OWNER NAME.......PARCEL.......$AMOUNT". parse_pdf_text() (the producer's own function,
         called here unedited) turns the whole document into {owner, parcel, amount} rows.

ONE FETCH SERVES THE WHOLE COUNTY, same as the producer itself: this is one annual advertisement
covering every delinquent account, not a per-parcel lookup. Fetched ONCE per process (an
asyncio.Lock-guarded, unbounded-TTL module cache: a sweep process is short-lived and the document
itself changes at most once a year, so there is no reason to re-fetch it a second time within one
run) and reused for every candidate row.

NO NAME MATCHING AT VERIFY TIME, UNLIKE THE PRODUCER. The producer must match a board row to a PDF
account by OWNER NAME (no address or parcel-id crosswalk exists in the document at discovery time
-- see that module's own "MATCH METHOD" section). This verifier does not need to: by the time a row
reaches here it already carries the PDF's OWN parcel string in raw.pasquotank_tax_lien.parcel,
captured at discovery. Re-parsing the current PDF and looking up that EXACT parcel (summed across
every dot-leader row that names it, in case a split real-estate + supplemental bill shares one
account -- the producer's own documented shape) is a strictly more precise check than redoing the
owner-name match: no second candidate to rule out, the same "NO SEARCH, NO BINDING AMBIGUITY"
discipline tax_lien_polk.py already holds itself to for its own per-record id.

VERDICTS:
  confirmed    the parcel is still on the current live PDF with a real (>0) summed balance.
  stale        never actually reachable: the producer's own _money() helper requires amount > 0 to
               ever emit a row at all, so a parcel whose balance now reads $0 does not appear as a
               zero row in the parsed output -- it simply stops appearing, the SAME shape as
               "parcel_not_in_current_roll" below. Kept only for the same structural reason
               tax_lien_polk.py keeps its own unreachable "refuted: never" branch: a future change
               to the producer's own money-parsing floor would not silently mis-verdict here.
  refuted      never: like every sibling tax_lien verifier here, this source has no payment-DATE
               field, only a resulting balance, so a bill paid before it was ever late cannot be
               told from one paid after -- there is no evidence here to refute on.
  unconfirmed  no usable parcel on the row (no_block / no_parcel); the fetch or PDF parse failed
               (fetch_failed, retried on the transient cadence); the parcel no longer appears
               anywhere on the current roll (parcel_not_in_current_roll) -- genuinely ambiguous on
               a once-a-year static advertisement: it could mean paid since, or simply that this
               year's advertisement has not yet listed it (the annual cycle restarts rows), so this
               is never guessed at as a positive "stale" signal, the same conservative bar
               tax_lien_polk.py's own "record_not_found" (by id) holds for an unfindable record.
  wall         never: the document is a public, no-login PDF (confirmed live 2026-11-18).

Evidence is a whitelist (public ledger): the county's own parcel id (the same choice every sibling
tax_lien verifier makes for its own identifier) and the two balances; no owner name.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30          # one annual advertisement; re-checking faster than this learns nothing new
RETRY_DAYS = 14
SOURCE = "pasquotankcountync.org (NCGS 105-369 delinquent tax advertisement PDF)"
GOVERNS = tc.GOVERNS
priority = tc.flag_priority     # the "2+ years and $500" rows first within a tier
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed",)

COUNTY = "pasquotank"
_BLOCK_KEY = "pasquotank_tax_lien"
#: only enrichment_pasquotank_delinquent_tax.py ever writes this block (its own module docstring);
#: the row's own top-level `source` is whatever ORIGINAL scraper first saw the row (this is an
#: enrichment pass merged onto an existing row by owner name, module docstring's "MATCH METHOD"),
#: so applies() keys off the raw block's own `source` sub-field, never row['source'].
_PRODUCER_SLUG = "enrichment_pasquotank_delinquent_tax"
_NAME = __name__.rsplit(".", 1)[-1]

_CACHE: dict[str, Any] = {"totals": None, "pdf_rows": None}
_LOCK = asyncio.Lock()


def _enr():
    """The producer module, imported lazily on first use -- the registry imports every verifier
    module at discovery time, and the producer's own module-level imports (pdfplumber, httpx) are
    cheap here but this still keeps the same lazy idiom tax_lien_polk.py's own _polk_tax() uses."""
    from ... import enrichment_pasquotank_delinquent_tax as m
    return m


def _block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(_BLOCK_KEY)
    return b if isinstance(b, dict) and str(b.get("source") or "") == _PRODUCER_SLUG else None


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    if str(tc.g(row, "county") or "").replace(" County", "").strip().lower() != COUNTY:
        return False
    b = _block(row)
    if not b or not str(b.get("parcel") or "").strip():
        return False
    return tc.claims_property_tax(row, True)


async def _parcel_totals(client: Any) -> dict[str, float]:
    """parcel (whitespace-stripped, exactly as parse_pdf_text() emits it) -> its current summed
    balance, parsed fresh from the SAME PDF the producer reads -- fetched and parsed once per
    process, never once per row (module docstring: one document serves the whole county)."""
    if _CACHE["totals"] is not None:
        return _CACHE["totals"]
    async with _LOCK:
        if _CACHE["totals"] is not None:
            return _CACHE["totals"]
        from ...http_client import get_bytes      # lazy: the network stack only when fetching
        m = _enr()
        pdf_bytes = await get_bytes(m.PDF_URL, timeout=30.0)
        rows = m.parse_pdf_text(m._extract_text(pdf_bytes))
        totals: dict[str, float] = {}
        for r in rows:
            totals[r["parcel"]] = round(totals.get(r["parcel"], 0.0) + r["amount"], 2)
        _CACHE["totals"] = totals
        _CACHE["pdf_rows"] = len(rows)
        return totals


def _find(parcel: str, totals: dict[str, float]) -> Optional[float]:
    if parcel in totals:
        return totals[parcel]
    target = tc.alnum(parcel)
    if not target:
        return None
    # defensive fallback only (mirrors tax_lien_polk.py's own parcel cross-check): a parcel whose
    # punctuation the county's own formatting has shifted slightly between PDF editions still
    # matches by its letters/digits alone.
    for k, v in totals.items():
        if tc.alnum(k) == target:
            return v
    return None


_KEYS = ("reason", "url", "parcel", "amount_at_discovery", "amount_today", "pdf_rows", "error")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION,
                 verifier=_NAME)


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    b = _block(row)
    if not b:
        return _res("unconfirmed", {"reason": "no_block"})
    parcel = str(b.get("parcel") or "").strip()
    if not parcel:
        return _res("unconfirmed", {"reason": "no_parcel"})
    ev: dict[str, Any] = {"parcel": parcel, "url": _enr().PDF_URL,
                          "amount_at_discovery": b.get("balance")}
    try:
        totals = await _parcel_totals(client)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["pdf_rows"] = _CACHE.get("pdf_rows")
    amount = _find(parcel, totals)
    if amount is None:
        return _res("unconfirmed", dict(ev, reason="parcel_not_in_current_roll"))
    ev["amount_today"] = amount
    if amount > 0:
        return _res("confirmed", ev)
    # unreachable in practice (module docstring's VERDICTS: stale) -- parse_pdf_text()'s own
    # _money() never lets an amount <= 0 become a row in the first place.
    return _res("stale", dict(ev, reason="paid_since_snapshot"))
