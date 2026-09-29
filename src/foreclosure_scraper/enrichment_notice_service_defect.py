"""Assessor owner-name search used as a notice-defect weapon (Dirty Deeds Tier B
#30, docs/dirty_deeds_synthesis_2026-09-10.md): "If a tax-foreclosure defendant
was served by publication or alternative service, and that same name resolves
to a mailing or situs address in the same county's assessor, service was
defective. That is leverage to pull a pending sale and buy the deed pre-sale,
and a cloud on any issued tax deed. Both halves of the data are already held;
only the join is missing."

THE JOIN, AS ACTUALLY BUILDABLE (found live, not assumed)
    Half A -- the service-method signal -- already exists in captured notice
    text, but only on ONE source: public_notices.nc_notices_counties (the
    ncnotices.com county-scoped scraper). Its OWN classifier
    (`_PUBLICATION_SERVICE_RE` in that module) already detects "NOTICE OF
    SERVICE OF PROCESS BY PUBLICATION" language and uses it internally to pick
    a ListingType (LIS_PENDENS vs TAX_LIEN) -- but never stamps the fact "this
    defendant was served by publication" anywhere a downstream join could read
    it. This module re-derives that same signal from the row's own
    `description` (the scraper's own text[:400] excerpt, which reliably
    contains the notice's opening caption where this phrase always sits) and,
    when still present, `raw['public_notice']['preview_text']` -- confirmed
    live 2026-09-29 that the board's merge/dedup step frequently DROPS the
    `public_notice` raw block (it is not RAW_KEEP'd) while `description`
    survives, so `description` is the durable read.

    Half B -- the assessor owner-name resolution -- is the NAME -> PROPERTY
    resolver this board already runs for every name-indexed lead
    (enrichment_resolve_name_to_property.py, raw['resolved_from_name']) and
    the situs-based owner+mailing enricher (enrichment_owner_mailing.py,
    raw['owner_mailing']). Both are ALREADY a live "does this name resolve to
    a real address in this county's GIS/tax roll" answer -- exactly what the
    synthesis calls "an assessor owner-name search" -- and this module reads
    them rather than re-implementing a third name-to-parcel resolver.

    This module is the JOIN ONLY: for a row where (a) the plaintiff is a
    government entity (a tax-foreclosure caption, "COUNTY OF X" / "CITY OF X"
    / ...), (b) the notice text says the defendant was served by publication
    or alternative/substituted service, and (c) the defendant is a real named
    party (not "unknown heirs" -- a county genuinely not knowing an heir's
    identity is not a locatability defect), it looks for a resolved address
    for that SAME name in the SAME county two ways:
      1. On the row itself: raw['owner_mailing']['mailing'], a plain
         Listing.street_address (often merged in from a sibling notice for
         the same case via the board's cross-source dedup -- see LIVE
         VERIFICATION), or a favorable raw['resolved_from_name'].
      2. Board-wide: any OTHER listing in the same (state, county) whose
         owner_name/defendant clears name_normalize.match_owner against this
         defendant AND itself carries a resolved address. Built once as a
         county index over the whole `enriched` list passed in, so the O(n)
         cost is one extra pass, not a nested scan.
    No network. Additive only, same contract as every enricher in this
    family.

LIVE VERIFICATION 2026-09-29 (board_stream.iter_board_rows, read-only, no
load_board -- scratch probe scripts, not committed):
  * Board-wide, only 3 sources ever carry "service by publication" /
    "alternative service" / "substitute(d) service" language at all:
    public_notices.nc_notices_counties (9 rows, all NC, all with a
    government-entity plaintiff -- genuinely tax-foreclosure shaped),
    public_notices.ncnotices (1 row, a DIVORCE_NOTICE -- out of scope, no
    government plaintiff), and counties_sc.sc_public_notices (1 row, an SC
    PROBATE_NOTICE motion for service by publication -- an estate case, not a
    tax foreclosure, and SC's own tax-sale process is administrative with no
    lawsuit or service event at all -- see SC NOTE below).
  * Of the 9 NC tax-foreclosure-shaped rows: 2 name a generic, non-individual
    party ("Any unknown HEIRS", "THE UNKNOWN HEIRS OF BERKLEY R...") and are
    correctly excluded by the real-party-name guard. Of the remaining 7 real
    individual defendants (Buncombe x6, Craven x1), 2 already carry a REAL
    resolved address for that exact defendant in the exact suing county:
      - JAMES DAYTON PLEMMONS, Buncombe 26CV002591-100, COUNTY OF BUNCOMBE
        plaintiff -- raw['owner_mailing']['mailing'] =
        "103 W STATE ST BLACK MTN NC 28711" (his own tax mailing address on
        file with the SAME county that told the court he could not be
        located).
      - MERANDA L. McCONNELL, Buncombe 26CV003558-100, COUNTY OF BUNCOMBE
        plaintiff -- raw['owner_mailing']['mailing'] =
        "54 PUNKIN ST LEICESTER NC 28748", matching her own situs address.
    A THIRD row (the same JAMES DAYTON PLEMMONS case, a second board row for
    the same case_number with no address of its own -- the board's dedup
    merged the notice text and the GIS mailing hit onto two different rows
    instead of one) is caught ONLY by the board-wide cross-reference, not by
    reading its own raw -- confirming the board-wide half of this join earns
    its cost and is not redundant with the same-row read.
  * The remaining 4 (DAVID EARL WISE, MILLAD MOORAEI, RONALD A. MAXWELL,
    MICHAEL CARLAND RODGERS) have no resolved address anywhere on the board
    today -- correctly left untagged; a future name-resolver or owner-mailing
    pass over the same rows can only ever add matches here, never remove
    this module's need to check.

SC NOTE (per docs/dirty_deeds_synthesis_2026-09-10.md: "SC runs an
administrative delinquent-tax sale, which means no lawsuit, no docket, no
plaintiff's attorney signature block, no return-of-service event, no party
list, and no order of sale") -- confirmed independently here: a full-board
scan found ZERO SC rows, of any listing_type, carrying publication/
alternative-service language tied to a tax sale or tax lien. SC's one hit is
a probate estate motion, a different legal posture entirely (and PROBATE_
NOTICE rows are explicitly out of scope for this module -- a decedent's
unresolved estate is not the same due-process claim as a living defendant's
locatability). This module hard-gates on state == "NC"; the state check is
explicit even though the plaintiff-shape and party-name guards would already
exclude SC's admin tax-sale rows, same defense-in-depth style as
enrichment_divorce_no_subsequent_deed.py.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

import structlog

from .mailing_shape import mailing_of
from .models import Listing
from .name_normalize import is_entity, match_owner

log = structlog.get_logger()

# "NOTICE OF SERVICE OF PROCESS BY PUBLICATION" is the exact NC caption; the
# other two phrasings cover alternative wording seen in the same notice family
# (a court order for substituted/alternative service after publication fails
# too, or is used instead of it).
_PUBLICATION_SERVICE_RE = re.compile(
    r"service\s+by\s+publication|"
    r"notice\s+of\s+service\s+of\s+process\s+by\s+publication|"
    r"alternative\s+service|"
    r"substitut(?:ed|e)\s+service",
    re.I,
)

# A government body suing as the tax-foreclosure plaintiff -- "COUNTY OF X",
# "CITY OF X, a Body Politic and Corporate", "TOWN OF X" ... Mirrors the same
# entity shape column_legal_notices._TAX_PLAINTIFF and nc_notices_counties.
# _PLAINTIFF_RE both key on, but this reads the already-parsed Listing.plaintiff
# field instead of re-scanning body text.
_GOV_PLAINTIFF_RE = re.compile(r"^(?:COUNTY|CITY|TOWN|VILLAGE)\s+OF\s", re.I)

# A caption naming an unidentified class of defendant, not a real located
# person -- the county not knowing WHO an heir is is not a claim that a real,
# named person was undiscoverable. Excluded so every tagged row makes a
# concrete, checkable claim about one real name.
_GENERIC_PARTY_RE = re.compile(
    r"unknown\s+heirs?|heirs?\s+of\s+[a-z]|any\s+(?:and\s+all\s+)?unknown|"
    r"all\s+unknown|unknown\s+owner|unknown\s+spouse|unknown\s+defendant|"
    r"\bjohn\s+doe\b|\bjane\s+doe\b",
    re.I,
)

#: resolved_from_name confidences that mean the name-search backend actually
#: FOUND this person on a real parcel (exact/strong = committed to one parcel;
#: ambiguous_multi_parcel = found on 2+, still a real hit on the name).
_FAVORABLE_RESOLVER_CONFIDENCE = {"exact", "strong", "ambiguous_multi_parcel"}


def _notice_text(li: Listing) -> str:
    """Every text field this row might carry the notice body in. `description`
    is the durable one (see module docstring); the raw blocks are read too in
    case a fresher, not-yet-merged row still has them."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    parts = [li.description or ""]
    pn = raw.get("public_notice")
    if isinstance(pn, dict) and pn.get("preview_text"):
        parts.append(str(pn["preview_text"]))
    col = raw.get("column")
    if isinstance(col, dict) and col.get("snippet"):
        parts.append(str(col["snippet"]))
    return " ".join(p for p in parts if p)


def _is_publication_service(li: Listing) -> bool:
    return bool(_PUBLICATION_SERVICE_RE.search(_notice_text(li)))


def _is_tax_foreclosure_plaintiff(li: Listing) -> bool:
    return bool(_GOV_PLAINTIFF_RE.search((li.plaintiff or "").strip()))


def _real_party_name(li: Listing) -> Optional[str]:
    """The defendant's name, or None when it names no real located individual."""
    name = (li.defendant or li.owner_name or "").strip()
    if len(name) < 4:
        return None
    if _GENERIC_PARTY_RE.search(name):
        return None
    if is_entity(name):
        return None
    return name


def _own_row_evidence(li: Listing) -> Optional[dict]:
    """Address evidence already resolved ON THIS ROW by an enricher that already
    ran an assessor/GIS owner-name or owner-address lookup for exactly this
    defendant: raw['owner_mailing'] (situs-based), a plain street_address
    (frequently merged in from a sibling notice for the same case -- see the
    JAMES DAYTON PLEMMONS case in the module docstring), or a favorable
    raw['resolved_from_name'] (name-based reverse lookup)."""
    om = mailing_of(li)
    mailing = (om.get("mailing") or "").strip()
    if mailing and mailing != "-":
        return {"kind": "owner_mailing", "address": mailing, "parcel_id": li.parcel_id}
    if (li.street_address or "").strip():
        return {"kind": "situs_on_row", "address": li.street_address, "parcel_id": li.parcel_id}
    raw = li.raw if isinstance(li.raw, dict) else {}
    rfn = raw.get("resolved_from_name")
    if isinstance(rfn, dict) and rfn.get("confidence") in _FAVORABLE_RESOLVER_CONFIDENCE:
        return {
            "kind": "resolved_from_name",
            "address": li.street_address,
            "matched_owner": rfn.get("matched_owner"),
            "confidence": rfn.get("confidence"),
        }
    return None


def _county_key(li: Listing) -> Optional[tuple[str, str]]:
    county = (li.county or "").strip().lower()
    state = (li.state or "").strip().upper()
    if not county or not state:
        return None
    return state, county


def _index_candidate(li: Listing) -> Optional[tuple[str, dict]]:
    """(name, evidence) for this listing if it is usable as a board-wide
    cross-reference candidate: a real name with a real resolved address."""
    evidence = _own_row_evidence(li)
    if not evidence:
        return None
    name = (li.owner_name or li.defendant or "").strip()
    if len(name) < 4 or is_entity(name) or _GENERIC_PARTY_RE.search(name):
        return None
    return name, evidence


def enrich_notice_service_defect(listings: Iterable[Listing]) -> dict:
    """Stamp raw['notice_service_defect'] when a tax-foreclosure defendant served
    by publication/alternative service shares a name that resolves to a real
    mailing or situs address in the SAME county's assessor/GIS data -- on the row
    itself or on any other board row. Never drops a lead; additive only. NC
    only (see SC NOTE in the module docstring)."""
    listings = list(listings)
    stats = {
        "candidate_rows": 0,
        "sc_skipped": 0,
        "generic_party_skipped": 0,
        "no_evidence_yet": 0,
        "same_row_hit": 0,
        "cross_board_hit": 0,
        "tagged": 0,
    }

    # One pass to build the county-scoped name -> evidence index every trigger
    # row will search. Built from the WHOLE board (any source/listing_type),
    # since the synthesis's claim is "this name resolves to SOME assessor
    # address in this county", not "on this same notice".
    index: dict[tuple[str, str], list[tuple[str, dict, int]]] = {}
    for li in listings:
        key = _county_key(li)
        if not key:
            continue
        cand = _index_candidate(li)
        if not cand:
            continue
        name, evidence = cand
        index.setdefault(key, []).append((name, evidence, id(li)))

    for li in listings:
        if not _is_tax_foreclosure_plaintiff(li):
            continue
        if not _is_publication_service(li):
            continue
        stats["candidate_rows"] += 1
        if li.state != "NC":
            stats["sc_skipped"] += 1
            continue

        name = _real_party_name(li)
        if not name:
            stats["generic_party_skipped"] += 1
            continue

        key = _county_key(li)
        evidence = _own_row_evidence(li)
        source_kind = "same_row"
        if not evidence and key is not None:
            for cand_name, cand_evidence, cand_id in index.get(key, []):
                if cand_id == id(li):
                    continue  # this row's own (nonexistent) evidence, already checked above
                if match_owner(name, cand_name):
                    evidence = cand_evidence
                    source_kind = "cross_board"
                    break

        if not evidence:
            stats["no_evidence_yet"] += 1
            continue

        if source_kind == "same_row":
            stats["same_row_hit"] += 1
        else:
            stats["cross_board_hit"] += 1

        m = _PUBLICATION_SERVICE_RE.search(_notice_text(li))
        raw = li.raw if isinstance(li.raw, dict) else {}
        raw["notice_service_defect"] = {
            "defendant": name,
            "county": li.county,
            "state": li.state,
            "plaintiff": li.plaintiff,
            "case_number": li.case_number,
            "service_language_matched": m.group(0) if m else None,
            "evidence_source": source_kind,
            "resolved_address": evidence.get("address"),
            "resolved_parcel_id": evidence.get("parcel_id"),
            "resolved_via": evidence.get("kind"),
            "resolver_confidence": evidence.get("confidence"),
            "note": (
                f"{li.plaintiff or 'the county'} served {name} by publication/"
                "alternative service, representing to the court the defendant "
                "could not be located -- but the same county's own assessor/GIS "
                "records carry a real mailing or situs address for this exact "
                "name. Grounds to challenge service as defective: leverage to "
                "pull a pending sale, or a cloud on any tax deed already issued."
            ),
        }
        li.raw = raw
        stats["tagged"] += 1

    if stats["tagged"] or stats["candidate_rows"]:
        log.info("notice_service_defect.done", **stats)
    return stats
