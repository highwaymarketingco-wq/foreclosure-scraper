"""Divorce decree with no subsequent deed (Dirty Deeds Tier B #20).

docs/dirty_deeds_synthesis_2026-09-10.md, source #20: "Ex-spouses still 50/50
on record, deadlocked on spite. $50k for the wife's half, then $55k to the
husband whose only condition was out-earning her; $105k on a property they
had offered $184k for a month earlier." Marked "Easy negative join on the
eCourts Judgment JSON already in the pipeline" and NC-only (SC family court is
access-restricted — see project_hwm_reddit_intel_tooling-adjacent notes; this
module never runs on state=="SC", full stop).

THE JOIN, AS ACTUALLY BUILDABLE (found live, not assumed)
    A DIVORCE_NOTICE row (scrapers/counties_nc/nc_ecourts_lis_pendens.py's
    "FAM - Divorce" judgments, and nc_ecourts_divorce.py's SmartSearch filing
    rows) carries the two spouses' names (Listing.plaintiff / Listing.defendant)
    and a case_number/county, but NEVER a street_address or parcel_id at
    construction time — confirmed live 2026-09-28 (see LIVE VERIFICATION below):
    0 of either scraper's rows are built with one. "No subsequent deed" is a
    negative claim about a SPECIFIC property, so a property has to be found
    before the claim can be tested.

    The property IS found — not by this module, but by the resolver this board
    already runs: enrichment_resolve_name_to_property.py takes exactly this
    class of name-only lead (owner_name/defendant, no address/parcel) and runs
    an owner-name search against the county GIS/tax-roll layer, writing
    provenance to raw['resolved_from_name'] (RAW_KEEP'd, `"resolved_from_name":
    "*"`) whether or not it ends up committing an address. Two fields in that
    block are the whole mechanism this module needs:
      * matched_owner — the GIS layer's OWN owner-of-record cell for the
        parcel(s) it found for the querying spouse. NC OneMap and the Buncombe
        structured index both pack co-owners into one cell joined by ';'
        ('GREENE KENNETH;GREENE YVONNE') — see enrichment_resolve_name_to_
        property._owner_segments, mirrored below.
      * candidates[].owner — the SAME owner cell, but present even when the
        resolver found 2+ parcels for the name and stopped short of committing
        an address (confidence "ambiguous_multi_parcel"). This is the case that
        actually matters here: a couple who jointly owned 2 parcels reads to
        the resolver as an ambiguous multi-parcel owner and gets no address —
        but the owner-cell TEXT it already fetched is sitting in raw right now,
        RAW_KEEP'd, and is exactly the "still 50/50 on record" evidence.

    So the join is: for a DIVORCE_NOTICE row with a raw['resolved_from_name']
    block (any confidence), does ANY owner-cell text it carries (matched_owner,
    or any candidate's owner) contain BOTH spouses as distinct ';'-segments,
    each independently clearing name_normalize.match_owner? If yes, the two
    ex-spouses are still jointly titled on a real parcel post-judgment — no
    deed ever moved the property to one of them alone.

    This module does NOT call the resolver, does NOT hit any network, and does
    NOT require an address/parcel to ever land on the row. It is a pure re-read
    of raw['resolved_from_name'], already fetched and already on the board.

LIVE VERIFICATION 2026-09-28 (board_stream.iter_board_rows, read-only, no
load_board — see /tmp scratch scoring script, not committed):
  * 6,678 divorce_notice rows on the board (5,316 nc_ecourts_lis_pendens,
    1,361 nc_ecourts_divorce, 1 ncnotices). 0% carry a street_address or
    parcel_id AT CONSTRUCTION; only 88/93 have one at all today (from later
    enrichment, not the scrapers themselves).
  * Only 48 of the 6,678 (0.7%) have been through the name resolver at all —
    it is a shared, budget-capped, cross-source backlog
    (enrichment_resolve_name_to_property._CAP / _budget_for), and divorce_
    notice is one slice of a much larger name-indexed queue (SC Public Index,
    probate, tax liens, ...). This is a real, current ceiling on this
    module's yield, not a defect in this module: every run that drains more
    of that backlog gives this join more to check, for free, with no code
    change here.
  * Of those 48: 44 no_match, 2 ambiguous_multi_parcel, 2 strong.
  * FOUND LIVE AND GUARDED AGAINST: 2 of those 4 non-no_match rows
    (Dare 25CV000580-270 "Stecher", Buncombe 26CV001212-100 "Yim") are a
    caption-parsing artifact upstream — the SAME PERSON is captioned as both
    plaintiff and defendant ("STECHER, REESE E" v. "Stecher, Reese Edward"),
    so their single-name matched_owner trivially "matches both spouses"
    because there is only one spouse. Guarded by requiring match_owner(
    plaintiff, defendant) to be EMPTY (the two parties must not already look
    like the same person) before anything else runs — see _distinct_spouses.
    Without that guard this module would have shipped 2 false positives and
    exactly 1 true one on today's board; a 66% false-positive rate on the
    only test data available. With it: 1 real hit today — Buncombe
    25CV001998-100, Greene v. Greene, owner cell "GREENE KENNETH;GREENE
    YVONNE" across 2 Buncombe parcels (071081525000000 / 071081539300000),
    confirmed as a granted judgment (raw['nc_ecourts']['civilJudgmentStatus']
    == 'Active', orderedDate 2026-07-12) merged onto the same case's original
    SmartSearch filing row.

VERIFIED DEAD END: raw['gis']['owner'] is NOT a usable second source for the
current owner-of-record text. enrichment_gis_attrs.apply_gis_attrs only ever
mirrors li.owner_name (`gis.setdefault("owner", li.owner_name)`) — and for a
divorce lead li.owner_name is already set (to the plaintiff, at scrape time),
so apply_gis_attrs's real GIS read is thrown away and raw['gis']['owner'] just
echoes the single name already known. Confirmed by reading the source, not
assumed. resolved_from_name.matched_owner / candidates[].owner are the ONLY
place the real, possibly-joint GIS owner cell survives on this board.

Reads Listing.plaintiff / Listing.defendant (never owner_name — it is cleared
or overwritten on these rows by other passes on this board, confirmed live on
the one real hit above, where top-level owner_name is None despite the
scraper setting it at construction). No network. Additive only, same
contract as every enricher in this family.
"""
from __future__ import annotations

from typing import Iterable, Optional

import structlog

from .models import Listing, ListingType
from .name_normalize import match_owner

log = structlog.get_logger()


def _owner_segments(owner: str) -> list[str]:
    """Co-owner strings inside one GIS owner cell, first party first.

    A local copy of enrichment_resolve_name_to_property._owner_segments
    (same ';'-join convention NC OneMap and the Buncombe owner index both
    use) rather than an import — that module pulls in the full async/httpx
    resolver stack for a 6-line pure string helper, which this offline,
    read-only pass has no other reason to load.
    """
    raw = str(owner or "")
    if ";" not in raw:
        return [raw] if raw.strip() else []
    return [seg.strip() for seg in raw.split(";") if seg.strip()]


def _distinct_spouses(plaintiff: str, defendant: str) -> bool:
    """True only when plaintiff and defendant read as two DIFFERENT people.

    Live-required guard (see module docstring): a caption-parse artifact on
    this board captions the same person as both plaintiff and defendant on a
    small number of rows. Without this check, that single name would trivially
    "match both spouses" against its own single-party owner cell.
    """
    return match_owner(plaintiff, defendant) is None


def _owner_cells(rfn: dict) -> list[str]:
    """Every owner-cell text this resolver pass fetched for the row, deduped,
    matched_owner first (present on strong/exact AND ambiguous_multi_parcel
    resolutions) then every ambiguous candidate's own owner cell."""
    cells: list[str] = []
    seen: set[str] = set()

    def _add(cell: Optional[str]) -> None:
        c = (cell or "").strip()
        if c and c not in seen:
            seen.add(c)
            cells.append(c)

    _add(rfn.get("matched_owner"))
    for cand in rfn.get("candidates") or []:
        if isinstance(cand, dict):
            _add(cand.get("owner"))
    return cells


def _both_spouses_on_cell(
    cell: str, plaintiff: str, defendant: str,
) -> Optional[tuple[str, str]]:
    """(plaintiff_match_kind, defendant_match_kind) if BOTH spouses clear
    match_owner against distinct segments of this one owner cell, else None."""
    p_kind: Optional[str] = None
    d_kind: Optional[str] = None
    for segment in _owner_segments(cell):
        if p_kind is None:
            k = match_owner(plaintiff, segment)
            if k:
                p_kind = k
        if d_kind is None:
            k = match_owner(defendant, segment)
            if k:
                d_kind = k
    if p_kind and d_kind:
        return p_kind, d_kind
    return None


def _decree_provenance(raw: dict) -> tuple[Optional[str], str]:
    """(iso_date, kind) for the divorce event date, preferring a GRANTED
    judgment (nc_ecourts_lis_pendens.py's Judgment Search hit, "FAM - Divorce")
    over a raw SmartSearch FILING date (nc_ecourts_divorce.py) — a decree is
    what the synthesis's title names, a pending filing is weaker evidence the
    marital home is actually deadlocked post-divorce."""
    judgment = raw.get("nc_ecourts")
    if isinstance(judgment, dict) and judgment.get("ordered_date_iso"):
        return judgment["ordered_date_iso"], "judgment_ordered"
    filing = raw.get("nc_ecourts_divorce")
    if isinstance(filing, dict) and filing.get("filed_date_iso"):
        return filing["filed_date_iso"], "filing_date"
    return None, "unknown"


def enrich_divorce_no_subsequent_deed(listings: Iterable[Listing]) -> dict:
    """Stamp raw['divorce_no_subsequent_deed'] when a divorce judgment's two
    ex-spouses both still clear match_owner against the same current
    GIS/tax-roll owner-of-record cell (raw['resolved_from_name'], already
    fetched by enrichment_resolve_name_to_property). Never drops a lead;
    additive only. NC only — SC family court is access-restricted, so no SC
    divorce_notice row can ever carry the raw['resolved_from_name'] this join
    depends on, but the state check is explicit here too, defense in depth."""
    listings = list(listings)
    stats = {
        "divorce_notice_rows": 0,
        "sc_skipped": 0,
        "no_resolution_yet": 0,
        "same_person_artifact": 0,
        "resolved_no_joint_owner": 0,
        "tagged": 0,
    }

    for li in listings:
        if li.listing_type != ListingType.DIVORCE_NOTICE:
            continue
        stats["divorce_notice_rows"] += 1
        if li.state != "NC":
            stats["sc_skipped"] += 1
            continue

        plaintiff = (li.plaintiff or "").strip()
        defendant = (li.defendant or "").strip()
        if not plaintiff or not defendant:
            continue

        if not _distinct_spouses(plaintiff, defendant):
            stats["same_person_artifact"] += 1
            continue

        raw = li.raw if isinstance(li.raw, dict) else {}
        rfn = raw.get("resolved_from_name")
        if not isinstance(rfn, dict):
            stats["no_resolution_yet"] += 1
            continue

        hit_cell = None
        match_kinds = None
        for cell in _owner_cells(rfn):
            kinds = _both_spouses_on_cell(cell, plaintiff, defendant)
            if kinds:
                hit_cell = cell
                match_kinds = kinds
                break

        if not hit_cell:
            stats["resolved_no_joint_owner"] += 1
            continue

        p_kind, d_kind = match_kinds
        confidence = "high" if p_kind == "exact" and d_kind == "exact" else "medium"

        candidate_parcels = sorted({
            str(cand.get("parcel_id")).strip()
            for cand in (rfn.get("candidates") or [])
            if isinstance(cand, dict) and cand.get("parcel_id")
        }) or ([li.parcel_id] if li.parcel_id else [])

        decree_date, decree_kind = _decree_provenance(raw)

        li.raw["divorce_no_subsequent_deed"] = {
            "case_number": li.case_number,
            "county": li.county,
            "state": li.state,
            "spouse_plaintiff": plaintiff,
            "spouse_defendant": defendant,
            "matched_owner": hit_cell,
            "plaintiff_match": p_kind,
            "defendant_match": d_kind,
            "confidence": confidence,
            "candidate_parcel_ids": candidate_parcels,
            "resolver_confidence": rfn.get("confidence"),
            "judgment_confirmed": isinstance(raw.get("nc_ecourts"), dict),
            "decree_date": decree_date,
            "decree_date_kind": decree_kind,
        }
        stats["tagged"] += 1

    if stats["tagged"]:
        log.info("divorce_no_subsequent_deed.done", **stats)
    return stats
