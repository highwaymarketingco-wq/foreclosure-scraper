"""court_wall, NC + SC: court and notice claims whose primary source code may not read. Labelled
`wall` with the walls_register card that tells the owner what to do by hand; never fetched.

WHY A LABEL. The court_signals audit (2026-10-09) asked that every lead called because of a court
or notice event be rechecked at its primary source before it is called. For these claims the
primary source is behind a CAPTCHA or a bot check (docs/walls_register.json, kind A); a verifier
that fetched would have to get around it, which this project never does. A `wall` record on the
row says so where the lead is read, and the card id names the manual lane:

  card sc_publicindex   SC lis pendens / foreclosure / judgment claims from the SC Judicial
                        Public Index (counties_sc.sc_public_index, sc_public_index_lis_pendens,
                        national.sc_public_index) outside Charleston (Charleston's own copy of the
                        index is open; no verifier reads it yet, so its rows carry no label).
  card nc_est           NC estate claims from estate notices (notice to creditors: the estate
                        file itself is an NC eCourts Smart Search record).
  card brock_scott_waf  Brock & Scott trustee-sale rows (foreclosure_sale, every NC/SC county it
                        files in). foreclosure_sale_list.py's own docstring already names Brock &
                        Scott as "NOT read (walls, recorded in docs/walls_register.json): ...
                        answers 'Forbidden' to a plain client; its scraper falls back to a stealth
                        browser" -- a verifier never takes that fallback, so these rows carried no
                        verdict at all (not even a wall) until this card. Confirmed live in the
                        scraper's own code (law_firms/brock_scott.py _page(): "Site now returns
                        'Forbidden' (9 bytes) to plain httpx. Fall back to StealthyFetcher which
                        passes the WAF check."): a Cloudflare-style bot check, kind A by this
                        register's own definition. Added 2026-11-18, gap_matrix built-not-verified
                        sweep; board_stream audit found 51 rows across 16 counties (NC Gaston,
                        Burke, Buncombe, Brunswick, Henderson, Onslow, Lincoln, Mitchell,
                        Rutherford, Cleveland, McDowell; SC Spartanburg, Anderson, Oconee, Laurens,
                        Pickens), none carrying any prior verification dict. No walls_register.json
                        card added alongside this one (that file's generator requires several
                        operational fields -- what to pull, how it is saved, which existing app
                        ingests the save -- this round found no such ingestion lane for this firm's
                        page format and declined to invent one; a future round can add the full
                        manual-lane card once that lane is real).
  card nc_sp            NC power-of-sale foreclosure claims built from a notice of sale (the SP
                        file: hearing, sale, report of sale, upset bids). Also covers a notice
                        nc_notices_counties.py classified raw.public_notice.kind == "foreclosure"
                        but then remapped to listing_type lis_pendens (its own deliberate
                        _FLIP_FOOTPRINT_NAMES rule: FORECLOSURE_SALE's flip semantics don't leak
                        outside the flip footprint) -- added 2026-11-18, gap_matrix
                        built-not-verified sweep, same bug class as sc_notice_body below: card_of()
                        checked only lt == "foreclosure_sale" before this, so a county outside the
                        flip footprint (e.g. Dare, 20 rows) got no verdict at all even though its
                        rows are the identical "NOTICE OF FORECLOSURE SALE ... FILE NO. 26SP..."
                        text behind the identical eCourts picture-CAPTCHA. Confirmed live
                        2026-11-18 across every NC county this remap touches (board_stream audit:
                        81 rows, 13 counties -- Dare 20, Brunswick 14, New Hanover 13, Onslow 12,
                        Carteret 4, Haywood 4, Lincoln 3, Rutherford 3, Gaston 2, Burke 2, McDowell
                        2, Buncombe 1, Cleveland 1 -- every one carries raw.public_notice.kind ==
                        "foreclosure" and a real 26SP/25SP case number, not a lis-pendens-only
                        filing).
  card sc_notice_body   SC foreclosure AND probate-notice claims from scpublicnotices.com notice
                        bodies (lt_probate_notice added 2026-11-18, gap_matrix built-not-verified
                        sweep: counties_sc.sc_public_notices.py's own code confirms every row,
                        whatever category it came from -- Foreclosures, Tax Sales, "Notice to
                        Creditors", "Probate Notices" -- carries the identical
                        source_url=Details.aspx?ID=... and the same text_truncated=True marker;
                        card_of() checked only lt == "foreclosure_sale" before this, so a
                        probate_notice row from the exact same walled source carried no verdict at
                        all. Confirmed live 2026-11-18 (6 real Colleton "Notice to Creditors" rows,
                        category 30 -- e.g. Details.aspx?ID=640383): a plain httpx GET on the
                        row's own source_url still answers the identical Cloudflare Turnstile +
                        ReCaptcha "challenge" interstitial the producer's own module docstring
                        already documented for this host -- nothing category-specific about the
                        wall, Greenwood/Newberry/Sumter/Barnwell's rows share the same source_url
                        shape and text_truncated=True marker).
The human-assisted checker (scripts/verify_lead_human_assisted.py, card nc_verify) writes the
verdict a person reads into the human lane's own ledgers; this label never displaces one.

VERDICT: always `wall`, GOVERNS nothing (a wall changes no score). TTL 365: relabelled yearly or
when the wall changes.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core import VerificationResult, result

SIGNAL = "court_wall"
VERSION = "v1"
TTL_DAYS = 365
SOURCE = "walls_register.json (kind A walls)"
GOVERNS: tuple[str, ...] = ()
WALL = True
#: the ledger is public; a notice row's street_address can hold notice text with names
ROW_SUMMARY_EXCLUDE = ("owner_name", "street_address")

SC_INDEX_SOURCES = frozenset({"counties_sc.sc_public_index", "counties_sc.sc_public_index_lis_pendens",
                              "national.sc_public_index", "national.sc_public_index.judgment_lien"})
NC_ESTATE_NOTICE_SOURCES = frozenset({"counties.column_legal_notices",
                                      "public_notices.nc_notices_counties", "public_notices.ncnotices"})
NC_SP_NOTICE_SOURCES = frozenset({"public_notices.nc_notices_counties", "public_notices.ncnotices",
                                  "counties.column_legal_notices"})
SC_NOTICE_SOURCES = frozenset({"counties_sc.sc_public_notices"})
#: foreclosure_sale_list.py's own FIRMS registry never includes this one (its docstring: "NOT
#: read ... answers 'Forbidden' to a plain client; its scraper falls back to a stealth browser").
BROCKSCOTT_SOURCES = frozenset({"law_firms.brock_scott"})
#: the claim types a trustee sale list (or this wall standing in for one) can govern -- same
#: universe as foreclosure_sale_list.GOVERNS, kept as a local literal so this module never
#: imports a sibling verifier just for one tuple.
_SALE_LIST_TYPES = frozenset({"foreclosure_sale", "upset_bid", "court_sale", "tax_sale"})

_NAME = __name__.rsplit(".", 1)[-1]


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _val(v: Any) -> Any:
    return getattr(v, "value", v)


def card_of(row: Any) -> Optional[str]:
    """The walls_register card that covers the row's court claim, or None."""
    st = str(_get(row, "state") or "").strip().upper()
    src = str(_get(row, "source") or "")
    lt = str(_val(_get(row, "listing_type")) or "")
    raw = _get(row, "raw") if isinstance(_get(row, "raw"), dict) else {}
    co = str(_get(row, "county") or "").strip().lower()
    if st == "SC" and src in SC_INDEX_SOURCES and co != "charleston" and \
            lt in ("lis_pendens", "foreclosure_sale", "distressed"):
        return "sc_publicindex"
    if st == "SC" and src in SC_NOTICE_SOURCES and lt in ("foreclosure_sale", "probate_notice"):
        return "sc_notice_body"
    if st == "NC" and src in NC_SP_NOTICE_SOURCES and (
            lt == "foreclosure_sale"
            or (lt == "lis_pendens" and (raw.get("public_notice") or {}).get("kind") == "foreclosure")):
        return "nc_sp"
    if st == "NC" and src in NC_ESTATE_NOTICE_SOURCES and (
            lt in ("probate_notice", "estate_lead") or isinstance(raw.get("probate"), dict)):
        return "nc_est"
    if st in ("NC", "SC") and src in BROCKSCOTT_SOURCES and lt in _SALE_LIST_TYPES:
        return "brock_scott_waf"
    return None


def applies(row: dict) -> bool:
    return card_of(row) is not None


_WHY = {
    "sc_publicindex": "SC Judicial Public Index: the site's edge refuses scripts (bot check)",
    "sc_notice_body": "scpublicnotices.com notice body: Cloudflare check and a CAPTCHA",
    "nc_sp": "NC eCourts special proceeding file: picture CAPTCHA before every search",
    "brock_scott_waf": "brockandscott.com foreclosure sale list: plain fetch gets HTTP 'Forbidden'"
                       " (Cloudflare-style WAF); the scraper's own stealth-browser fallback is"
                       " never used by a verifier",
    "nc_est": "NC eCourts estate file: picture CAPTCHA before every search",
}


async def verify(row: dict, client=None) -> VerificationResult:
    card = card_of(row)
    return result(SIGNAL, "wall", {"reason": _WHY.get(card or "", "walled source"), "card": card,
                                   "manual": "docs/OWNER_MANUAL_LANES.md (generated from "
                                             "docs/walls_register.json, card " + str(card) + ")"},
                  source=SOURCE, version=VERSION, verifier=_NAME)
