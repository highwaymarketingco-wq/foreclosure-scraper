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
  card nc_sp            NC power-of-sale foreclosure claims built from a notice of sale (the SP
                        file: hearing, sale, report of sale, upset bids).
  card sc_notice_body   SC foreclosure claims from scpublicnotices.com notice bodies.
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
    if st == "SC" and src in SC_NOTICE_SOURCES and lt == "foreclosure_sale":
        return "sc_notice_body"
    if st == "NC" and src in NC_SP_NOTICE_SOURCES and lt == "foreclosure_sale":
        return "nc_sp"
    if st == "NC" and src in NC_ESTATE_NOTICE_SOURCES and (
            lt in ("probate_notice", "estate_lead") or isinstance(raw.get("probate"), dict)):
        return "nc_est"
    return None


def applies(row: dict) -> bool:
    return card_of(row) is not None


_WHY = {
    "sc_publicindex": "SC Judicial Public Index: the site's edge refuses scripts (bot check)",
    "sc_notice_body": "scpublicnotices.com notice body: Cloudflare check and a CAPTCHA",
    "nc_sp": "NC eCourts special proceeding file: picture CAPTCHA before every search",
    "nc_est": "NC eCourts estate file: picture CAPTCHA before every search",
}


async def verify(row: dict, client=None) -> VerificationResult:
    card = card_of(row)
    return result(SIGNAL, "wall", {"reason": _WHY.get(card or "", "walled source"), "card": card,
                                   "manual": "docs/OWNER_MANUAL_LANES.md (generated from "
                                             "docs/walls_register.json, card " + str(card) + ")"},
                  source=SOURCE, version=VERSION, verifier=_NAME)
