"""lien_registry_wall, NC + SC: lien claims on the board whose primary source no code may read.
Labelled `wall` with the walls_register.json card that tells the owner what to do by hand; never
fetched.

WHY A LABEL (top-80 build list 2026-10-09, item 74 lt_tax_lien: 72 county cells). On the
2026-10-07 board 54,000 rows are typed tax_lien by sources whose claim is NOT a county
property-tax delinquency (verification/verifiers/_tax_common.NON_PROPERTY_TAX_SOURCES: the county
tax verifiers never take them), so the cube's tax_lien verification layer counted them as hit rows
nobody could verify. Each of these has a reason no verifier may fetch:

  counties_generic.liensnc, liensnc   45,093 rows (2026-10-07). Every row is a LiensNC "Appointment
        of Lien Agent": a construction project's lien agent, not a lien and not a tax claim. The
        registry (apps.liensnc.com) is behind the owner's own login; no verification code signs in.
        Card liensnc_login. (The listing type is the scraper's choice; the scorer is not touched.)
  counties_sc.sc_dew_lien_registry    8,288 rows. SC DEW's registry search service answers a plain
        request "Invalid Security Key" (read live 2026-10-09 with the key the scraper carries): it
        accepts its key only from the rendered page, which the scraper reaches with the stealth
        browser (existing code, not extended). Card sc_lien_registries.
  counties_sc.sc_state_tax_lien   319 rows. The SCDOR top-delinquent grid is a rendered page read
        in the stealth browser. Card sc_lien_registries.
  counties_nc.rutherford_tax, counties_nc.rutherford_wildfire_tax   8,544 rows. Rutherford's tax
        bill search and its data host answer HTTP 403 to the cloud address (and show a CAPTCHA to
        a browser): card avalon_tax. The county's only free list, the TR-452 workbook the first
        source reads, has been the "as of 2026-02-01" file since February (the link carries the
        2026-02-01 stamp, read 2026-10-09): re-reading it would repeat the scrape, not check it.

VERDICT: always `wall`, GOVERNS nothing (a wall changes no score). TTL 365: relabelled yearly or
when the wall changes. The human-assisted checker never displaces a verdict a person wrote.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core import VerificationResult, result

SIGNAL = "lien_registry_wall"
VERSION = "v1"
TTL_DAYS = 365
SOURCE = "walls_register.json (kind A walls)"
GOVERNS: tuple[str, ...] = ()
WALL = True
#: the ledger is public; a lien row can hold a debtor's name or an owner mailing address
ROW_SUMMARY_EXCLUDE = ("owner_name", "street_address")

LIENSNC_SOURCES = frozenset({"counties_generic.liensnc", "liensnc"})
SC_REGISTRY_SOURCES = frozenset({"counties_sc.sc_dew_lien_registry", "counties_sc.sc_state_tax_lien"})
RUTHERFORD_SOURCES = frozenset({"counties_nc.rutherford_tax", "counties_nc.rutherford_wildfire_tax"})
TAX_TYPES = frozenset({"tax_lien", "tax_sale"})

_NAME = __name__.rsplit(".", 1)[-1]

_WHY = {
    "liensnc_login": "LiensNC appointments of a lien agent: the registry is behind the owner's own login "
                     "(and the filing is a construction-project notice, not a tax lien)",
    "sc_lien_registries": "SC DEW / SCDOR lien registries: the search service accepts its key only from "
                          "the rendered page (plain request: Invalid Security Key)",
    "avalon_tax": "Rutherford County tax bill search: data host 403 to the cloud address, CAPTCHA in a "
                  "browser; the county's free list is a frozen 2026-02-01 file",
}


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _val(v: Any) -> Any:
    return getattr(v, "value", v)


def card_of(row: Any) -> Optional[str]:
    """The walls_register card that covers the row's lien claim, or None."""
    src = str(_get(row, "source") or "")
    lt = str(_val(_get(row, "listing_type")) or "")
    if lt not in TAX_TYPES:
        return None
    if src in LIENSNC_SOURCES:
        return "liensnc_login"
    if src in SC_REGISTRY_SOURCES:
        return "sc_lien_registries"
    if src in RUTHERFORD_SOURCES:
        return "avalon_tax"
    return None


def applies(row: dict) -> bool:
    return card_of(row) is not None


async def verify(row: dict, client=None) -> VerificationResult:
    card = card_of(row)
    return result(SIGNAL, "wall", {"reason": _WHY.get(card or "", "walled source"), "card": card,
                                   "manual": "docs/OWNER_MANUAL_LANES.md (generated from "
                                             "docs/walls_register.json, card " + str(card) + ")"},
                  source=SOURCE, version=VERSION, verifier=_NAME)
