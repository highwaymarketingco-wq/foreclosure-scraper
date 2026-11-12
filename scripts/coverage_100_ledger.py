#!/usr/bin/env python3
"""Per-county x per-signal coverage ledger for the 18-county footprint.

`county_coverage_matrix.py` counts a signal family as "present" from source
NAMES, so it misses signals that live as stamps on leads (court-verified divorce,
incarceration, obituaries) and says nothing about how many leads carry a family.
This ledger streams the board once (constant memory, safe next to another board
process) and reports, for each footprint county:

  * LAYERS  rows, identity (parcel+situs), value, owner name, mail, phone, actual debt
  * SIGNALS a lead count per family, from the union of (a) the source name,
            (b) distress_stack.signals, and (c) raw stamps (divorce, incarceration)
  * the weakest layer and every family with ZERO leads

A family with 0 leads is either a build target or a documented wall; the walls
live in docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md and are overlaid by hand in
the ledger doc, not guessed here.

    python scripts/coverage_100_ledger.py            # prints markdown to stdout
    python scripts/coverage_100_ledger.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from foreclosure_scraper.enrichment_sc_phone import usable_owner_phone  # noqa: E402

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.config import NC_COUNTIES, SC_COUNTIES  # noqa: E402
from foreclosure_scraper.distress_score import _divorce_signal  # noqa: E402

# family -> (source-name fragments, distress_stack signal names). A lead counts
# toward a family if ANY of them matches.
#
# The signal-name half must be a signal that ONLY ever fires from a source that
# genuinely belongs to the family -- not a generic cross-cutting stamp that many
# unrelated sources can set. `distressed_condition` used to sit on code_vacancy:
# it looks family-specific ("a distressed structure") but distress_score.py
# actually sets it from raw['distressed'], which is stamped by bulk CAMA
# assessor-condition enrichment (enrichment_cama_condition.py /
# enrichment_sc_cama.py / enrichment_owner_mailing.py's condition-column scan)
# on ANY row in ANY county with a "Poor"/"Unsound" appraiser condition code,
# regardless of which scraper produced that row. A tax-delinquent lead in a
# county with a bulk condition layer (e.g. Buncombe) got counted as
# "code_vacancy" evidence even though no code-enforcement/vacancy scraper ever
# touched it -- the same false-positive class the 2026-09-29 completeness audit
# separately flagged for `recorded_debt` under "liens" (a real-debt signal any
# tax/foreclosure source can set -- distress_score.py fires it off a real
# raw['tax_owed']['balance'] or any countable raw['amount_owed'], neither of
# which is lien-registry-specific; fixed below the same way). `vacant_structure`
# is the one genuinely code_vacancy-scoped derived signal: it only fires from
# raw['vacancy']/raw['vacant'] being a dict with vacant/boarded_up True, which
# only hendersonville_vacant_structures.py ever writes.
#
# "liens" has the same generic-flag problem `recorded_debt` had for code_vacancy,
# but no source-name fragment rescues it the way vacant_structure did: the three
# ROD scrapers that actually discover lien recordings (nc_rod_logan, sc_rod_cott,
# sc_rod_acclaim) sweep ALL distress recording types for their county/vendor --
# lis pendens, foreclosure deeds, probate -- and only classify SOME of those rows
# as a real lien (LIEN/JUDGMENT/MECH/EXECUTION instrument codes). Each already
# computes that classification precisely via its own `_classify()` and stamps it
# on the row as `listing_type == "tax_lien"` (ListingType.TAX_LIEN) -- the same
# field a NC/SC tax-delinquency scraper also happens to use for an unrelated
# reason (a delinquent PARCEL, not a recorded LIEN instrument), so listing_type
# alone is not enough either. The precise match is BOTH: the row's source is one
# of the three ROD scrapers (a sweep of all their recording types) AND its own
# listing_type says LIEN (that source's own per-row instrument classification,
# not a generic distress-stack flag). See `_ROD_LIEN_SOURCES` and the `family ==
# "liens"` branch in family_hits().
FAMILIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "tax_delinquent": (("delinquent_tax", "tax_delinquent", "ptscloud", "pdf_delinquent",
                        "csv_delinquent", "multi_year", "qpaybill", "flc"), ("tax_lien",)),
    "tax_sale": (("tax_sale", "tax_foreclos", "kania", "zacchaeus"), ("tax_sale",)),
    "mortgage_foreclosure": (("hutchens", "brock_scott", "shapiro", "substitute_trustee",
                              "foreclosure_sale", "sheriff", "trustee", "upset"),
                             ("foreclosure_sale", "upset_bid", "sheriff_sale", "auction")),
    "lis_pendens": (("lis_pendens", "public_index"), ("lis_pendens",)),
    "probate_estate": (("probate", "estate", "obitu", "funeral", "deceased"),
                       ("probate", "probate_notice", "probate_deed")),
    # "zombie" dropped from the fragments (audit false-positive #2): zombie_properties.py
    # is a DERIVED stalled-foreclosure signal (a stale lis pendens that never progressed
    # to sale) -- it is not a code-enforcement/vacancy source and has no physical-condition
    # evidence at all. Real dedicated scrapers: henderson_code_violations,
    # hendersonville_vacant_structures, lincoln_code_violations, spartanburg_vacant,
    # spartanburg_condemned, spartanburg_city_condemned (SC) +
    # city_websites.asheville_min_housing (Buncombe). gaston_vacant, lincoln_vacant and
    # transylvania_vacant also match the "vacant" fragment by name but are EXCLUDED at
    # match time (see _VACANT_LAND_NOT_CODE_VACANCY_SOURCES below) -- 2026-09-30 audit
    # found all three are vacant-LAND (unimproved lot) parcel feeds, not code-enforcement
    # or vacant-STRUCTURE sources.
    "code_vacancy": (("code_violation", "condemn", "vacant", "min_housing", "demoli",
                      "nuisance", "code_enforcement"),
                     ("code_enforcement", "vacant_structure")),
    # "courtlistener" (bare) dropped 2026-09-30: it also matched
    # national.courtlistener_civil, a federal CIVIL real-property/foreclosure
    # docket scraper (nature-of-suit 220/230/240/290 -- Foreclosure, Rent Lease
    # & Ejectment, Torts to Land, Other Real Property; emits
    # listing_type=LIS_PENDENS, never bankruptcy). "courtlistener_bankruptcy"
    # already matches via the "bankruptcy" fragment (substring), so only the
    # genuinely-bankruptcy sibling "courtlistener_adversary" (lift-stay
    # motions / Sec. 363 sales inside a bankruptcy docket) needs its own
    # fragment.
    "bankruptcy": (("bankruptcy", "courtlistener_adversary"), ("bankruptcy",)),
    "divorce": (("divorce",), ()),               # + raw['divorce'] stamp, below
    # `recorded_debt` dropped (2026-09-30 fix) -- see the module comment above.
    # Real lien-registry sources (sc_dew_lien_registry, sc_state_tax_lien,
    # national.nc_sos_ucc, national.liensnc) already match on the "lien" /
    # "judgment" / "ucc" name fragments; the three ROD sweep-scrapers are
    # handled by the source+listing_type special case in family_hits().
    "liens": (("lien", "judgment", "ucc"), ()),
    "incarceration": ((), ("incarceration",)),   # + raw['incarceration'] stamp
}

# The three ROD "sweep" scrapers: each discovers ALL recent distress recordings
# for its county/vendor (lis pendens, foreclosure deeds, probate, liens) and
# classifies every row's instrument code itself (see each module's own
# `_classify()`). Only a row that source classified as a LIEN
# (listing_type == "tax_lien") is real lien-registry evidence from them --
# their lis-pendens/foreclosure-deed/probate rows must not count toward
# "liens" just because they share a source with a real lien row.
#
# 2026-09-30 audit: the same three sources' LIEN rows were ALSO leaking into
# "tax_delinquent", the mirror-image of the bug fixed above. tax_delinquent
# matches the `tax_lien` distress_stack signal, which -- like `recorded_debt`
# -- is not family-specific: it is just listing_type=="tax_lien" restated as
# a signal name (distress_score.py's _LISTING_TYPE_SIGNAL), and ALL THREE ROD
# scrapers' own `_classify()` stamps listing_type=="tax_lien" on a real
# recorded LIEN/JUDGMENT instrument (mechanics lien, civil judgment) -- not a
# delinquent tax parcel. Confirmed live: nc_rod_logan._classify() maps
# {LIEN, LN, LIEN000, JUDGMENT, JGMT, JUDG, JUDGM} -> ListingType.TAX_LIEN,
# and sc_rod_cott.py / sc_rod_acclaim.py do the same for their own doc-type
# sets. None of the three source names contain a tax_delinquent fragment, so
# the fix (see the "tax_delinquent" branch in family_hits()) simply drops the
# signal-based hit for rows from these three sources -- their only route into
# this family was the mislabeled signal.
_ROD_LIEN_SOURCES = ("nc_rod_logan", "sc_rod_cott", "sc_rod_acclaim")

# gaston_vacant / lincoln_vacant / transylvania_vacant (2026-09-30 audit): despite
# the a22dc20c fix listing these as 3 of the "6 real dedicated" code_vacancy
# scrapers, none of the three is actually a code-enforcement or vacant-STRUCTURE
# source. Read from the scraper bodies themselves:
#   * gaston_vacant.py      -- county GIS `VacantImpro=='Vacant'` = the parcel has
#                              NO improvements at all (an unbuilt LOT).
#   * lincoln_vacant.py     -- county GIS `VACANT` flag = "unimproved / no-structure".
#   * transylvania_vacant.py -- county GIS `BUILDING_V==0` = no building value (raw land).
# That is the OPPOSITE condition from code_vacancy (a STRUCTURE a code-enforcement
# office is working a vacant/condemned/boarded-up case on) -- vacant LAND is a
# real, different distress signal (absentee holding cost, no CAMA improvement),
# just not this family's. None of the three ever writes raw['condemned'] or a
# raw['code_enforcement'] block (confirmed: grep finds no such assignment in
# either file), so their only route into code_vacancy was the bare "vacant"
# name fragment. spartanburg_vacant is NOT included here: its "allvacant" layer
# carries CAMA specs (year_built/beds/baths/condition) for every row, which only
# exist for an IMPROVED parcel -- a genuine vacant-STRUCTURE registry, not raw
# land, so it keeps matching by name.
_VACANT_LAND_NOT_CODE_VACANCY_SOURCES = ("gaston_vacant", "lincoln_vacant", "transylvania_vacant")

# national.hibid_real_estate (2026-09-30 audit): a generic national real-estate
# AUCTION-category aggregator, by its own docstring "the catch-all net: small
# NC/SC auctioneers list estate / distressed / land / tax real estate here" --
# every row is typed listing_type==AUCTION regardless of whether the lot is a
# decedent-estate sale, a routine non-distressed listing, or anything else. It
# rode into two families it has no real evidence for:
#   * probate_estate, via the "estate" name fragment -- a coincidental substring
#     of "real_estate" (its own slug), not a decedent-estate signal. The bare
#     "estate" fragment is otherwise genuine (nc_ecourts_estates,
#     nc_heir_estate_parcels, estate_sales all really are estate-scoped), so it
#     can't just be dropped -- this one source is excluded by name instead.
#   * mortgage_foreclosure, via the generic `auction` distress_stack signal --
#     unlike the OTHER dedicated REO/foreclosure-auction platforms that signal
#     covers (govdeals, hubzu, xome, auction.com, bid4assets, servicelink),
#     hibid's own docs say it is not distress-scoped at all.
_HIBID_REAL_ESTATE_SOURCE = "hibid_real_estate"

# The two AOC/court-records "sweep" sources for lis_pendens: each discovers a
# broader set of case/record types under one slug and classifies every row's
# own listing_type itself -- like the ROD sources above, only SOME of their
# rows are real lis-pendens evidence.
#   * counties_nc.nc_ecourts_lis_pendens -- despite the slug, classifies by
#     `causeOfActionDesc`: a divorce cause -> DIVORCE_NOTICE, a "Tax"/"Tax
#     Liability" cause -> TAX_LIEN, and only a "Lis Pendens" (or non-tax
#     "Lien") cause -> LIS_PENDENS. Its DIVORCE_NOTICE and TAX_LIEN rows are
#     not lis-pendens evidence.
#   * counties_sc.sc_public_index -- the BULK civil+criminal sweep (its own
#     docstring: "civil (Common Pleas) and criminal (General Sessions)"),
#     NOT its dedicated, single-type sibling sc_public_index_lis_pendens
#     (counties_sc) or national.sc_public_index. Only its Common-Pleas rows
#     are typed LIS_PENDENS; its General-Sessions criminal rows are typed
#     UNKNOWN and carry no lis-pendens evidence at all.
# The exact slug strings are used (not a substring test) so this does not also
# catch sc_public_index_lis_pendens, whose slug contains "sc_public_index" as
# a prefix.
_LIS_PENDENS_SWEEP_SOURCES = frozenset({
    "counties_nc.nc_ecourts_lis_pendens",
    "counties_sc.sc_public_index",
})


def _pos(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def _cd(d: dict, k: tuple[str, str]) -> dict:
    return d.setdefault(k, defaultdict(int))


def family_hits(source: str | None, raw: dict, listing_type: str | None = None) -> set[str]:
    """Which FAMILIES keys one row counts as evidence for.

    A hit requires the row's own source/scraper identity to match a family's
    name fragments, OR a distress_stack signal that only that family's sources
    ever set. It deliberately does NOT match on a generic flag (like
    raw['distressed']) directly -- see the FAMILIES comment for the
    code_vacancy / liens false positives that pattern caused.

    `listing_type` is the row's own top-level ListingType value (e.g.
    "tax_lien"), needed for the "liens" / "tax_delinquent" / "lis_pendens"
    special cases below -- it is not a distress_stack signal, and several
    values are ambiguous on their own (every tax-delinquency scraper also
    uses listing_type=="tax_lien" for an unrelated reason: a delinquent
    parcel, not a recorded lien instrument), so it is only meaningful paired
    with a specific sweep-source's identity.
    """
    low = (source or "").lower()
    ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
    sigs = set(ds.get("signals") or [])
    hits: set[str] = set()
    for fam, (frags, snames) in FAMILIES.items():
        hit = any(f in low for f in frags) or any(s in sigs for s in snames)
        if fam == "divorce":
            dv = raw.get("divorce")
            hit = hit or (isinstance(dv, dict) and bool(dv.get("case_count")))
        if fam == "incarceration":
            hit = hit or bool(raw.get("incarceration"))
        if fam == "liens":
            # One of the three ROD sweep-scrapers, AND that source's own
            # per-row instrument classification says LIEN -- not a generic
            # distress-stack flag, and not just "any row from this source"
            # (their lis-pendens/foreclosure-deed/probate rows must not count).
            hit = hit or (any(f in low for f in _ROD_LIEN_SOURCES) and listing_type == "tax_lien")
        if fam == "tax_delinquent" and any(f in low for f in _ROD_LIEN_SOURCES):
            # Mirror of the "liens" special case above: these three sources'
            # own LIEN/JUDGMENT rows also carry listing_type=="tax_lien" (see
            # _ROD_LIEN_SOURCES), which is the same value every real
            # tax-delinquency scraper uses -- but for them it means a
            # recorded private lien, not a delinquent tax parcel. Drop the
            # signal-based hit; none of the three names carry a
            # tax_delinquent fragment, so this only ever removes the false
            # positive.
            hit = any(f in low for f in frags)
        if fam == "code_vacancy" and any(f in low for f in _VACANT_LAND_NOT_CODE_VACANCY_SOURCES):
            # gaston_vacant / lincoln_vacant / transylvania_vacant are vacant-LAND
            # (unimproved lot) sources, not code-enforcement/vacant-structure ones
            # -- drop the name-fragment hit. A genuine code_enforcement signal
            # (e.g. from the cross-cutting enrichment_code_enforcement.py city
            # registry, if it separately matched the same address) still counts.
            hit = any(s in sigs for s in snames)
        if fam in ("probate_estate", "mortgage_foreclosure") and _HIBID_REAL_ESTATE_SOURCE in low:
            # HiBid's generic Real-Estate-auction catch-all: no real evidence for
            # either family (see _HIBID_REAL_ESTATE_SOURCE above).
            hit = False
        if fam == "lis_pendens" and low in _LIS_PENDENS_SWEEP_SOURCES:
            # nc_ecourts_lis_pendens and the sc_public_index BULK sweep (not its
            # dedicated sc_public_index_lis_pendens sibling) each classify only
            # SOME of their own rows as a real lis pendens -- require the row's
            # own listing_type to say so, not just the source name.
            hit = listing_type == "lis_pendens"
        if hit:
            hits.add(fam)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write the raw numbers here")
    args = ap.parse_args()

    footprint = [(c.name, c.state) for c in list(NC_COUNTIES) + list(SC_COUNTIES)]
    want = {(n.lower(), s) for n, s in footprint}
    cnt: dict = {}

    for r in iter_board_rows():
        cty = (r.get("county") or "").replace(" County", "").strip().lower()
        st = (r.get("state") or "").strip().upper()
        k = (cty, st)
        if k not in want:
            continue
        c = _cd(cnt, k)
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        c["rows"] += 1
        if (r.get("parcel_id") or "").strip() and (r.get("street_address") or "").strip():
            c["identity"] += 1
        cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
        if any(_pos(v) for v in (r.get("market_value"), cama.get("appraised_value"),
                                 cama.get("total_value"), r.get("tax_value"))):
            c["value"] += 1
        has_name = bool((r.get("owner_name") or "").strip())
        if has_name:
            c["owner_name"] += 1
        st_ = raw.get("skip_trace") if isinstance(raw.get("skip_trace"), dict) else {}
        out_ = raw.get("outreach") if isinstance(raw.get("outreach"), dict) else {}
        op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
        rel = raw.get("liensnc_related") if isinstance(raw.get("liensnc_related"), dict) else {}
        oc = rel.get("owner_contact") if isinstance(rel.get("owner_contact"), dict) else {}
        om = raw.get("owner_mailing") if isinstance(raw.get("owner_mailing"), dict) else {}
        if has_name and (st_.get("owner_mailing_address") or out_.get("mailing_address")
                         or oc.get("mailing") or om.get("mailing")):
            c["mail"] += 1
        # usable_owner_phone drops do-not-dial xref matches, agent/attorney lines and people-search phones
        if usable_owner_phone(raw) or out_.get("phones") or oc.get("phone"):
            c["phone"] += 1
        # ACTUAL debt only: raw['tax_owed'].balance is a real delinquent balance;
        # raw['amount_owed'] is often an estimate (is_actual_debt False).
        to = raw.get("tax_owed") if isinstance(raw.get("tax_owed"), dict) else {}
        ao = raw.get("amount_owed") if isinstance(raw.get("amount_owed"), dict) else {}
        if _pos(to.get("balance")) or (_pos(ao.get("value")) and ao.get("is_actual_debt") is True):
            c["debt_actual"] += 1

        dv = raw.get("divorce")
        if isinstance(dv, dict) and _divorce_signal(raw):
            c["divorce_scored"] += 1              # recent enough to reach the score
        for fam in family_hits(r.get("source"), raw, r.get("listing_type")):
            c["fam:" + fam] += 1

    fams = list(FAMILIES)
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "-"
    lines = ["| county | rows | ident | value | name | mail | phone | debt$ | weakest |",
             "|---|--:|--:|--:|--:|--:|--:|--:|---|"]
    weak_of = {}
    for name, state in footprint:
        c = cnt.get((name.lower(), state), {})
        n = c.get("rows", 0)
        layers = {k: (c.get(k, 0) / n if n else 0) for k in ("identity", "value", "owner_name", "mail", "phone")}
        worst = min(layers, key=layers.get) if n else "NO ROWS"
        weak_of[(name, state)] = worst
        lines.append(f"| {name} {state} | {n:,} | {pct(c.get('identity', 0), n)} | {pct(c.get('value', 0), n)} | "
                     f"{pct(c.get('owner_name', 0), n)} | {pct(c.get('mail', 0), n)} | {pct(c.get('phone', 0), n)} | "
                     f"{pct(c.get('debt_actual', 0), n)} | {worst} {pct(int(layers.get(worst, 0) * n), n) if n else ''} |")
    print("## Layers (share of the county's leads)\n")
    print("\n".join(lines))

    hdr = "| county | " + " | ".join(f[:9] for f in fams) + " |"
    print("\n## Signals (lead count; `0` = no lead carries that family)\n")
    print(hdr)
    print("|---|" + "--:|" * len(fams))
    zero_cells = []
    for name, state in footprint:
        c = cnt.get((name.lower(), state), {})
        row = []
        for f in fams:
            v = c.get("fam:" + f, 0)
            row.append(f"**0**" if v == 0 else f"{v:,}")
            if v == 0:
                zero_cells.append((f"{name} {state}", f))
        print(f"| {name} {state} | " + " | ".join(row) + " |")

    print(f"\n## Zero cells: {len(zero_cells)} of {len(footprint) * len(fams)}\n")
    by_fam = defaultdict(list)
    for cty, f in zero_cells:
        by_fam[f].append(cty)
    for f in fams:
        if by_fam[f]:
            print(f"- **{f}** missing in {len(by_fam[f])}/{len(footprint)}: {', '.join(by_fam[f])}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {f"{n} {s}": dict(cnt.get((n.lower(), s), {})) for n, s in footprint}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
