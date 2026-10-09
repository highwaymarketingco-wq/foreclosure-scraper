"""The coverage cube of the published board, counts only: columns x counties x check depth.

WHAT IT MEASURES (one read-only pass over the board, board_stream.iter_board_rows_with_detail,
which is iter_board_rows plus the index-aligned lazy-detail sidecar for the one detail key
"comps"; ~300 MB peak, never writes the board).

  Dimension 1, the columns. The owner's own 73 columns from
  ~/Desktop/county_signal_coverage_FINAL.csv (2026-10-01): computed here with the 10/1
  script's definitions, character for character, so the two files compare. Plus nine
  attorney-checklist columns, prefixed atty_ (legal description, deed book/page, taxpayer of
  record, heir candidates, obituary match, register-of-deeds lien check, deed chain fetched,
  probate case, tax claim verified).
  Dimension 2, the counties: 100 NC + 46 SC, plus the rows whose county is blank (UNKNOWN).
  Dimension 3, check depth. "X% of rows carry signal Y" is not "we check Y in this county".
  For every column and county the cube also says: is the check APPLICABLE (rows it applies
  to), is a SOURCE known (docs/county_records/county_records_matrix.json, or a statewide
  source), is it BUILT (rows show it, or the producing code names the county, or it is
  statewide), did it RUN here (board evidence: a hit, or a negative-result wrapper), what share
  of applicable rows were CHECKED, and what share carry a VERIFIED verdict
  (docs/handoff/verification/*.json and raw.verification, read only).

THE GAP LIST. Every (county, column) cell under 100% of its target gets a class:
  sourced-not-built | built-but-low-yield | walled (<the wall>) | no source known |
  not applicable
with a one-line next action and the rows it affects. The target is the FILL share for a field
column (every applicable row should carry the value) and the CHECKED share for a signal column
(every applicable row should be screened; a low hit rate after a full screen is a county with
little of that distress, not a gap).

PRIVACY. The repo is public. Everything written is a count, a percentage, a county name, a
column name, a source slug or a format shape ("9999-99-9999"). No owner names, phones,
e-mails or street addresses are written or printed.

Usage:
  uv run python scripts/gap_matrix.py                  # docs/gap_matrix/*, today's date
  uv run python scripts/gap_matrix.py --desktop ~/Desktop --baseline ~/Desktop/county_signal_coverage_FINAL.csv
  uv run python scripts/gap_matrix.py --limit 5000     # smoke test on the first rows
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from foreclosure_scraper.county_name import canonical_county  # noqa: E402
from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES  # noqa: E402

PKG = SRC / "foreclosure_scraper"
STATE_COUNTIES = {"NC": NC_COUNTIES, "SC": SC_COUNTIES}
UNKNOWN = "UNKNOWN"

# =============================================================================================
# The owner's 73 columns, in the 10/1 file's order, with the 10/1 definitions
# =============================================================================================

FIELD_COLS = ["address", "parcel_id", "owner_name", "phone", "email",
              "sqft", "beds_baths", "lot_size", "assessed_value", "comps", "comps_tight"]

LISTING_TYPE_COLS = {
    "lt_foreclosure_sale": "foreclosure_sale", "lt_sheriff_sale": "sheriff_sale",
    "lt_lis_pendens": "lis_pendens", "lt_tax_lien": "tax_lien", "lt_tax_sale": "tax_sale",
    "lt_auction": "auction", "lt_reo": "reo", "lt_hoa_sale": "hoa_sale",
    "lt_distressed": "distressed", "lt_divorce_notice": "divorce_notice",
    "lt_probate_notice": "probate_notice", "lt_estate_lead": "estate_lead",
    "lt_elderly_disabled": "elderly_disabled", "lt_tax_sale_overage": "tax_sale_overage",
    "lt_bankruptcy": "bankruptcy",
}

SIMPLE_PRESENCE_COLS = [
    "multi_year_delinquent_tax", "repeat_tax_loss",
    "heir_estate", "heir_naming_publication", "owner_cluster",
    "divorce_no_subsequent_deed", "marriage_license",
    "bankruptcy_stay", "bankruptcy_tax_combo",
    "condemned", "vacant_lot", "vacant", "storm_damage", "usps_vacancy",
    "liens", "child_support", "sc_state_tax_lien", "lien_priority", "rollback_exposure",
    "jail_booking", "jail_booking_new", "incarceration", "bop_federal",
    "builder_distress", "liensnc_related", "liensnc_posthumous_filing", "sos_dissolution",
    "title_risk", "owner_mismatch", "notice_service_defect",
]

NAME_TOKENS = (
    ("name_estate_of", re.compile(r"\bEST(?:ATE)?\s+OF\b", re.I)),
    ("name_deceased", re.compile(r"\b(?:DECEASED|DEC'?D)\b", re.I)),
    ("name_life_estate", re.compile(r"\bLIFE\s+EST", re.I)),
    ("name_heirs", re.compile(r"\bHEIRS?\b", re.I)),
    ("name_et_al", re.compile(r"\bET\.?\s*AL\b", re.I)),
    ("name_trust", re.compile(r"\bTRUST(?:EE)?\b", re.I)),
    ("name_care_of", re.compile(r"\bC\s*/\s*O\b|\bC/O\b", re.I)),
)

CORRECTED_COLS = [
    "two_year_delinquent", "tax_aging_surfaced", "divorce", "probate",
    "vacancy", "code_enforcement",
    "deed_chain_has_history", "deed_chain_break", "deed_chain_distress_transfer",
]

OWNER_COLUMNS: list[str] = (FIELD_COLS + list(LISTING_TYPE_COLS) + SIMPLE_PRESENCE_COLS
                            + [t[0] for t in NAME_TOKENS] + CORRECTED_COLS + ["quiet_title"])

ATTY_COLUMNS: list[str] = [
    "atty_legal_description", "atty_deed_ref", "atty_taxpayer_of_record", "atty_heir_candidates",
    "atty_obituary_match", "atty_rod_lien_checked", "atty_deed_chain_fetched", "atty_probate_case",
    "atty_tax_verified_confirmed",
]

ALL_COLUMNS: list[str] = OWNER_COLUMNS + ATTY_COLUMNS

_EMPTY = (None, [], {}, "", False)


def _present(v: Any) -> bool:
    """The 10/1 script's presence test, kept exactly (0 and 0.0 count as empty, like False)."""
    return v not in _EMPTY


def owner_columns(rec: dict) -> set[str]:
    """The owner's 73 columns this row counts toward, with the 2026-10-01 script's definitions
    exactly (county_signal_coverage_FINAL.csv). Pure."""
    raw = rec.get("raw") or {}
    if not isinstance(raw, dict):
        raw = {}
    out: set[str] = set()
    if rec.get("street_address"):
        out.add("address")
    if rec.get("parcel_id"):
        out.add("parcel_id")
    owner_name = rec.get("owner_name") or ""
    if owner_name:
        out.add("owner_name")
    ph = raw.get("owner_phone")
    if isinstance(ph, dict) and ph.get("phone"):
        out.add("phone")
    em = raw.get("owner_email")
    if isinstance(em, dict) and em.get("best_email"):
        out.add("email")
    if rec.get("living_sqft"):
        out.add("sqft")
    if rec.get("bedrooms") and rec.get("bathrooms"):
        out.add("beds_baths")
    if rec.get("acreage") or rec.get("lot_size_sqft"):
        out.add("lot_size")
    if rec.get("assessed_value") or rec.get("market_value") or rec.get("tax_value"):
        out.add("assessed_value")
    comps = raw.get("comps")
    if isinstance(comps, list) and comps:
        out.add("comps")
        if any(isinstance(c, dict) and "sqft" in (c.get("match_quality") or "")
               and "beds" in (c.get("match_quality") or "") for c in comps):
            out.add("comps_tight")
    lt = rec.get("listing_type")
    for col, val in LISTING_TYPE_COLS.items():
        if lt == val:
            out.add(col)
    for k in SIMPLE_PRESENCE_COLS:
        if _present(raw.get(k)):
            out.add(k)
    if isinstance(owner_name, str) and owner_name:
        for col, pat in NAME_TOKENS:
            if pat.search(owner_name):
                out.add(col)
    ty = raw.get("two_year_delinquent")
    if isinstance(ty, dict) and ty.get("is_two_year_plus"):
        out.add("two_year_delinquent")
    ta = raw.get("tax_aging_surfaced")
    if isinstance(ta, dict) and ta.get("status") != "current" and (ta.get("years_delinquent") or 0) > 0:
        out.add("tax_aging_surfaced")
    if divorce_positive(raw):
        out.add("divorce")
    if probate_positive(raw):
        out.add("probate")
    vc = raw.get("vacancy")
    if isinstance(vc, dict) and (vc.get("vacant") or vc.get("boarded_up") or vc.get("utility_status")):
        out.add("vacancy")
    ce = raw.get("code_enforcement")
    if (isinstance(ce, dict) and (ce.get("condemned") or ce.get("has_open") or ce.get("severe"))) or ce is True:
        out.add("code_enforcement")
    dc = raw.get("deed_chain")
    if isinstance(dc, dict):
        out.add("deed_chain_has_history")
        summ = dc.get("summary") or {}
        if isinstance(summ, dict):
            if summ.get("chain_breaks"):
                out.add("deed_chain_break")
            if summ.get("distress_transfers"):
                out.add("deed_chain_distress_transfer")
    for k2 in ("column", "court", "case", "rod_docs", "heir_naming_publication"):
        blk = raw.get(k2)
        if (isinstance(blk, dict) and blk.get("is_quiet_title")) or (
                isinstance(blk, list) and any(isinstance(x, dict) and x.get("is_quiet_title") for x in blk)):
            out.add("quiet_title")
            break
    return out


def divorce_positive(raw: dict) -> bool:
    dv = raw.get("divorce")
    return isinstance(dv, dict) and ((dv.get("case_count") or 0) > 0
                                     or (isinstance(dv.get("cases"), list) and len(dv["cases"]) > 0))


def probate_positive(raw: dict) -> bool:
    pr = raw.get("probate")
    return isinstance(pr, dict) and bool(pr.get("decedent") or pr.get("es_case_number")
                                         or pr.get("nc_estate_file_no"))


# =============================================================================================
# Attorney-checklist columns, row predicates
# =============================================================================================

_LEGAL_KEYS = re.compile(r"(?i)^(legal_?desc|legaldescription|legal_descr|txt_legaldesc|legalreference|property_descr)")
_DEED_BOOK_KEYS = ("DeedBook", "DEED_BOOK", "DBOOK", "txt_deedbook", "Deed_Book", "DEED_BK", "DEEDREF",
                   "DEED_BOOK_PAGE", "deed_book")


def legal_description_present(rec: dict) -> bool:
    if rec.get("legal_description"):
        return True
    raw = rec.get("raw") or {}
    ga = raw.get("gis_attrs_full")
    if isinstance(ga, dict) and any(_LEGAL_KEYS.match(str(k)) and v not in _EMPTY for k, v in ga.items()):
        return True
    cl = raw.get("county_legal")           # gis_fill.py: the assessor's short legal off the county parcel record
    if isinstance(cl, dict) and cl.get("text"):
        return True
    dl = raw.get("deed_latest")            # lawyer_lane: the register index's description of the bound deed
    if isinstance(dl, dict) and dl.get("bound") and dl.get("legal_description"):
        return True
    mp = raw.get("mcdowell_probate")
    return isinstance(mp, dict) and bool(mp.get("legal_description"))


def deed_ref_present(raw: dict) -> bool:
    """A deed book and page (or an instrument number) the attorney can pull."""
    dc = raw.get("deed_chain")
    if isinstance(dc, dict):
        for t in dc.get("transfers") or []:
            if isinstance(t, dict) and t.get("book") and t.get("page"):
                return True
    g = raw.get("gis")
    if isinstance(g, dict):
        ls = g.get("last_sale")
        if isinstance(ls, dict) and ((ls.get("book") and ls.get("page"))
                                     or (ls.get("deed_book") and ls.get("deed_page")) or ls.get("instrument")):
            return True
    for k in ("rod", "nc_rod"):
        b = raw.get(k)
        # the register scrapers (nc_rod_logan, sc_rod_cott, sc_rod_acclaim) write 'instrument'
        if isinstance(b, dict) and ((b.get("book") and b.get("page")) or b.get("instrument_no")
                                    or b.get("instrument")):
            return True
    rd = raw.get("rod_docs")
    if isinstance(rd, list) and any(isinstance(x, dict) and x.get("book") and x.get("page") for x in rd):
        return True
    ga = raw.get("gis_attrs_full")
    if isinstance(ga, dict) and any(ga.get(k) not in _EMPTY for k in _DEED_BOOK_KEYS):
        return True
    cd = raw.get("county_deed_ref")        # gis_fill.py / county_deed_ref.py: the county parcel record's own deed ref
    if isinstance(cd, dict) and cd.get("book") and cd.get("page"):
        return True
    dl = raw.get("deed_latest")            # lawyer_lane: the register-index deed BOUND to this parcel
    if isinstance(dl, dict) and dl.get("bound") and dl.get("book") and dl.get("page"):
        return True
    mp = raw.get("mcdowell_probate")
    return isinstance(mp, dict) and bool(mp.get("deed_book_page"))


def taxpayer_of_record_present(rec: dict) -> bool:
    """A name read from the county's tax roll / parcel record (not from a notice or a court
    caption)."""
    raw = rec.get("raw") or {}
    g = raw.get("gis")
    if isinstance(g, dict) and g.get("owner"):
        return True
    om = raw.get("owner_mailing")
    # 2026-10-09: not a LiensNC filing's owner block (liensnc_handoff, source 'liensnc_filing': what the
    # contractor wrote, not the roll), and not `addressee` (sc_probate_notices writes the personal
    # representative there)
    if isinstance(om, dict) and om.get("owner") and om.get("source") != "liensnc_filing":
        return True
    for k, f in (("qpaybill_roll", "owner"), ("lrcpwa", "owner"), ("heir_estate", "owner_of_record"),
                 ("mcdowell_probate", "ownname")):
        b = raw.get(k)
        if isinstance(b, dict) and b.get(f):
            return True
    # a tax roll row's owner is the roll's; a LiensNC lien-agent filing typed tax_lien is not a roll
    return (bool(rec.get("owner_name")) and rec.get("listing_type") in ("tax_lien", "tax_sale")
            and not _is_liensnc_row(rec))


def heir_candidates_present(raw: dict) -> bool:
    # 2026-10-09: raw['heir_candidates'] (enrichment_heir_candidates, the published candidate list the
    # dashboard renders) was not read here, so a row with candidates counted as having none
    hc = raw.get("heir_candidates")
    if isinstance(hc, list) and any(isinstance(h, dict) and h.get("name") for h in hc):
        return True
    he = raw.get("heir_estate")
    if isinstance(he, dict) and he.get("heir_names"):
        return True
    pr = raw.get("probate")
    if isinstance(pr, dict) and pr.get("personal_representative"):
        return True
    for k in ("sc_probate_notice", "sc_probate_net"):
        b = raw.get(k)
        if isinstance(b, dict) and b.get("personal_representative"):
            return True
    ob = raw.get("obituary")
    return isinstance(ob, dict) and bool(ob.get("survivors"))


def probate_case_present(rec: dict) -> bool:
    raw = rec.get("raw") or {}
    pr = raw.get("probate")
    # 2026-10-09: + case_number (enrichment_probate_search, horry_probate, greenville_hard_distress
    # write it; signal_freshness.has_real_probate already reads it)
    if isinstance(pr, dict) and (pr.get("es_case_number") or pr.get("nc_estate_file_no")
                                 or str(pr.get("case_number") or "").strip()):
        return True
    sn = raw.get("sc_probate_notice")
    if isinstance(sn, dict) and sn.get("case_number"):
        return True
    sp = raw.get("sc_probate_net")
    if isinstance(sp, dict) and sp.get("docket"):
        return True
    return rec.get("listing_type") in ("probate_notice", "estate_lead") and bool(rec.get("case_number"))


def obituary_present(raw: dict) -> bool:
    return isinstance(raw.get("obituary"), dict) or raw.get("life_event") == "death"


def obituary_matched(raw: dict) -> bool:
    """atty_obituary_match: an obituary block. life_event == 'death' alone is not one: the SC probate
    notice readers stamp it too (sc_probate_notices, publicnoticesc_estates), so a probate notice
    counted as an obituary match (audit 2026-10-09)."""
    return isinstance(raw.get("obituary"), dict) and bool(raw.get("obituary"))


def rod_checked(raw: dict) -> bool:
    rod = raw.get("rod")
    if isinstance(rod, dict) and (rod.get("instrument_count") is not None or rod.get("book")):
        return True
    sweep = raw.get("rod_lien_sweep")
    if isinstance(sweep, dict) and sweep.get("status") and sweep.get("checked_at"):
        return True               # county-wide lien sweep (top80 Logan/Harris): dated, window-bounded
    return bool(raw.get("rod_docs")) or isinstance(raw.get("nc_rod"), dict)


def deed_chain_fetched(raw: dict) -> bool:
    dc = raw.get("deed_chain")
    return isinstance(dc, dict) and bool(dc.get("transfers"))


_TAX_KEY = re.compile(r"delinquent|^tax_owed$|^qpaybill_roll$|^catalis_roll$|_tax$|tax_list$|^tax_aging")
_NOT_PROPERTY_TAX = {"sc_state_tax_lien", "bankruptcy_tax_combo"}


def tax_status_known(raw: dict) -> bool:
    """The county tax roll was read for this parcel (delinquent or not)."""
    for k, v in raw.items():
        if k in _NOT_PROPERTY_TAX or v in _EMPTY:
            continue
        if _TAX_KEY.search(k):
            return True
    return False


def tax_claim(rec: dict, raw: dict, owner: set[str]) -> bool:
    if rec.get("listing_type") in ("tax_lien", "tax_sale"):
        return True
    to = raw.get("tax_owed")
    if isinstance(to, dict) and "delinq" in str(to.get("kind") or ""):
        return True
    return bool(owner & {"two_year_delinquent", "multi_year_delinquent_tax", "tax_aging_surfaced"})


# =============================================================================================
# Applicability, positives and row-level check evidence (the second view)
# =============================================================================================

_DECEASED_NAME = re.compile(r"\b(EST(?:ATE)?\s+OF|DECEASED|DEC'?D|HEIRS?)\b", re.I)
PERSON_TYPES = {"individual", "unknown", ""}


def entity_type(raw: dict) -> str:
    v = raw.get("entity_type")
    return v if isinstance(v, str) else ""


def is_deceased_owner(rec: dict, raw: dict, owner: set[str]) -> bool:
    if rec.get("listing_type") in ("probate_notice", "estate_lead") or "probate" in owner:
        return True
    if raw.get("heir_estate") or raw.get("obituary") or raw.get("life_event") == "death":
        return True
    if raw.get("mcdowell_probate") or raw.get("sc_probate_notice") or raw.get("sc_probate_net"):
        return True
    le = raw.get("life_events")
    if isinstance(le, list) and any(e in ("estate_probate", "multiple_heirs") for e in le if isinstance(e, str)):
        return True
    if entity_type(raw) == "estate":
        return True
    name = rec.get("owner_name")
    return isinstance(name, str) and bool(_DECEASED_NAME.search(name))


def is_improved(rec: dict, raw: dict) -> bool:
    return rec.get("property_kind") not in ("land", "commercial") and not raw.get("vacant_lot")


_OCEANFRONT: Optional[frozenset] = None


def oceanfront_counties() -> frozenset:
    """main.OCEANFRONT_COASTAL_COUNTIES ((county, state) pairs), read from main.py's source with
    ast so the cube does not import the orchestrator."""
    global _OCEANFRONT
    if _OCEANFRONT is None:
        import ast
        out: set = set()
        try:
            tree = ast.parse((PKG / "main.py").read_text())
            for node in tree.body:
                tgt = node.target if isinstance(node, ast.AnnAssign) else (
                    node.targets[0] if isinstance(node, ast.Assign) and node.targets else None)
                if isinstance(tgt, ast.Name) and tgt.id == "OCEANFRONT_COASTAL_COUNTIES" and node.value is not None:
                    for el in ast.walk(node.value):
                        if isinstance(el, ast.Tuple) and len(el.elts) == 2 and all(
                                isinstance(e, ast.Constant) for e in el.elts):
                            out.add((el.elts[0].value, el.elts[1].value))
        except (OSError, SyntaxError):
            pass
        _OCEANFRONT = frozenset(out)
    return _OCEANFRONT


def in_flip_scope(state: str, county: Optional[str]) -> bool:
    """The owner's flip scope: config.in_scope (the 18 footprint counties) or an oceanfront
    coastal county (beach-drive flips). A row with no county is in scope (it cannot be ruled out)."""
    if not county:
        return True
    from foreclosure_scraper.config import in_scope
    return bool(in_scope(county, state)) or (county, state) in oceanfront_counties()


def row_rules(rec: dict, raw: dict, owner: set[str]) -> set[str]:
    """Which applicability rules hold for the row. Pure."""
    st = (rec.get("state") or "").strip().upper()
    et = entity_type(raw)
    lt = rec.get("listing_type")
    r = {"all", st}
    if in_flip_scope(st, canonical_county(rec.get("county"))):
        r.add("flip_scope")
    if is_improved(rec, raw):
        r.add("improved")
    if et != "government":
        r.add("contactable")
    if et in PERSON_TYPES:
        r.add("person")
    if et == "entity":
        r.add("entity")
    if is_deceased_owner(rec, raw, owner):
        r.add("deceased")
    if lt == "bankruptcy" or raw.get("bankruptcy") or raw.get("courtlistener") or raw.get("bankruptcy_stay"):
        r.add("bankrupt")
    if "divorce" in owner or lt == "divorce_notice":
        r.add("divorced")
    if lt in ("foreclosure_sale", "lis_pendens", "auction", "sheriff_sale", "hoa_sale"):
        r.add("foreclosure")
    if rec.get("defendant"):
        r.add("court_party")
    if tax_claim(rec, raw, owner):
        r.add("tax_claim")
    if raw.get("rod") or raw.get("liens"):
        r.add("has_rod")
    if raw.get("liensnc"):
        r.add("liensnc")
    if raw.get("nc_ecourts") or raw.get("court") or raw.get("court_record"):
        r.add("court_case")
    return r


@dataclass(frozen=True)
class Spec:
    kind: str                 # "field": target = fill share | "signal": target = checked share
    scope: str                # row | derived | county | state | feed (see SCOPES)
    family: str               # source family (county records matrix or a named statewide source)
    applies: str = "all"      # a row_rules() rule
    states: tuple = ("NC", "SC")
    ledger: Optional[str] = None
    verify_family: Optional[str] = None   # the matrix family of the VERIFYING source when it differs from
                                          # the detecting one (a notice is detected statewide, verified at the county probate court)
    producers: tuple = ()     # src/foreclosure_scraper-relative files whose code names counties
    statewide: tuple = ()     # ((state, source name), ...): a free statewide source the code reads
    statewide_except: tuple = ()   # ((state, county), ...): counties that statewide source does NOT reach;
                                   # there the state's `walls` entry (if any) applies instead
    sources: tuple = ()       # ((state, source name), ...): a free statewide source NOT yet read
    walls: tuple = ()         # ((state, wall), ...): the state's source is walled
    doc: str = ""             # how the column is computed (README)
    ambiguity: str = ""       # where the 10/1 definition is ambiguous


def ledger_signals(spec: "Spec") -> tuple:
    """The verifier signal names a column's hit rows are verified by (Spec.ledger, 'a|b' = either)."""
    return tuple(x for x in (spec.ledger or "").split("|") if x)


SCOPES = {
    "row": "checked when the row carries the value or a negative-result wrapper",
    "derived": "computed from inputs already on the row: checked when the inputs are present",
    "county": "a county-wide roster/source: when it ran in the county every applicable row was screened",
    "state": "a statewide roster: when it ran anywhere in the state every applicable row was screened",
    "feed": "a listing type: the county has a feed that emits it (a scraper of that type has rows there)",
}

NC_ONEMAP = "NC OneMap statewide parcel layer (free ArcGIS REST)"
NOTICES = (("NC", "NC public notices (ncpublicnotices scraper)"), ("SC", "SC public notices (sc_public_notices scraper)"))
_F = "field"
_S = "signal"
#: Quiet-title suits naming heirs by publication are parsed only in Column's SC estate lane
#: (column_legal_notices._parse_sc_quiet_title); no NC notice parser looks for them (2026-10-09).
SC_QUIET_TITLE = (("SC", "SC estate notices via Column (column_legal_notices, SC estate lane)"),)
NC_QUIET_TITLE_SOURCE = ()      # was: NC notices known, no parser. scrapers/public_notices/nc_heir_notices.py reads them
NC_QUIET_TITLE_WALL = (("NC", "no Column paper in this county; ncnotices.com bodies are CAPTCHA-walled"),)
NC_QUIET_TITLE_READ = (("NC", "NC quiet-title / heir notices via Column (nc_heir_notices, notices searched by text)"),)


def _nc_without_column_paper() -> tuple:
    """The NC counties nc_heir_notices cannot reach (no Column notice in 365 days, measured
    2026-10-09): there the source is a verdict (walled), not a gap."""
    try:
        from foreclosure_scraper.scrapers.public_notices.nc_heir_notices import COLUMN_NC_COUNTIES
        from foreclosure_scraper.validation import NC_COUNTIES
        return tuple(("NC", c) for c in NC_COUNTIES if c not in set(COLUMN_NC_COUNTIES))
    except Exception:  # noqa: BLE001 - without the module every NC county reads as unreached
        return ()

SPECS: dict[str, Spec] = {
    # ---- fields --------------------------------------------------------------------------
    "address": Spec(_F, "row", "gis", statewide=(("NC", NC_ONEMAP),),
                    doc="street_address is non-empty",
                    ambiguity="counts placeholders ('0 MAIN ST') and road-only situs as filled"),
    "parcel_id": Spec(_F, "row", "gis", statewide=(("NC", NC_ONEMAP),), doc="parcel_id is non-empty",
                      ambiguity="no format check: a mis-parsed value counts as filled"),
    "owner_name": Spec(_F, "row", "gis", statewide=(("NC", NC_ONEMAP),), doc="owner_name is non-empty",
                       ambiguity="the name may come from a court caption or notice, not the tax roll"),
    "phone": Spec(_F, "row", "contact", applies="contactable",
                  statewide=(("NC", "NC voter file (ncsbe, free download)"),),
                  walls=(("SC", "SC voter list is sold, not free"),),
                  doc="raw.owner_phone.phone is non-empty",
                  ambiguity="includes phones from NC lien-agent appointment filings (liensnc) and "
                            "voter-file name matches; not every phone is proven to be the owner's"),
    "email": Spec(_F, "row", "email", applies="contactable", doc="raw.owner_email.best_email is non-empty",
                  ambiguity="a wrapper with no best_email is not counted (correct); emails come from "
                            "notices and filings only"),
    "sqft": Spec(_F, "row", "assessor", applies="improved", doc="living_sqft is non-zero",
                 ambiguity="counts footprint x stories ESTIMATES (living_sqft_estimated) as filled; "
                           "10/1 divided by all rows, land included"),
    "beds_baths": Spec(_F, "row", "assessor", applies="improved", doc="bedrooms and bathrooms both non-zero",
                       ambiguity="10/1 divided by all rows, vacant land included"),
    "lot_size": Spec(_F, "row", "gis", statewide=(("NC", NC_ONEMAP),), doc="acreage or lot_size_sqft non-zero"),
    "assessed_value": Spec(_F, "row", "gis", statewide=(("NC", NC_ONEMAP),),
                           doc="assessed_value, market_value or tax_value non-zero",
                           ambiguity="market_value can be a model value, not the county's assessment"),
    "comps": Spec(_F, "row", "sales", applies="improved", ledger="comps", verify_family="sales",
                  statewide=(("NC", "comps engine over county sales"), ("SC", "comps engine over county sales")),
                  doc="raw.comps (lazy-detail sidecar) is a non-empty list",
                  ambiguity="any comp counts, including kind-only matches across a whole county"),
    "comps_tight": Spec(_F, "row", "sales", applies="improved", ledger="comps", verify_family="sales",
                        statewide=(("NC", "comps engine over county sales"), ("SC", "comps engine over county sales")),
                        doc="at least one comp whose match_quality has both +sqft and +beds"),
    # ---- listing types (feeds) -----------------------------------------------------------
    "lt_foreclosure_sale": Spec(_S, "feed", "foreclosure", ledger="foreclosure_rod|foreclosure_sale_list|court_wall",
                                statewide=(("NC", "trustee/law-firm sale lists + NC public notices"),),
                                doc="listing_type == foreclosure_sale"),
    "lt_sheriff_sale": Spec(_S, "feed", "notices", statewide=NOTICES,
                            doc="listing_type == sheriff_sale",
                            ambiguity="NC forecloses by trustee/clerk, SC by Master-in-Equity; sheriff "
                                      "execution sales of land are rare, so 0 is expected"),
    "lt_lis_pendens": Spec(_S, "feed", "court", ledger="foreclosure_rod|nc_ecourts_case|court_wall",
                           statewide=(("NC", "NC eCourts Judgment Search (open JSON) + register indexes"),),
                           walls=(("SC", "SC Public Index terms forbid automated querying"),),
                           doc="listing_type == lis_pendens"),
    "lt_tax_lien": Spec(_S, "feed", "tax", ledger="tax_lien|lien_registry_wall|nc_ecourts_case", doc="listing_type == tax_lien"),
    "lt_tax_sale": Spec(_S, "feed", "tax", ledger="tax_lien|lien_registry_wall|foreclosure_sale_list", doc="listing_type == tax_sale"),
    "lt_auction": Spec(_S, "feed", "auction",
                       statewide=(("NC", "national auction sites"), ("SC", "national auction sites")),
                       doc="listing_type == auction"),
    "lt_reo": Spec(_S, "feed", "reo", statewide=(("NC", "HUD/HomePath/bank REO"), ("SC", "HUD/HomePath/bank REO")),
                   doc="listing_type == reo"),
    "lt_hoa_sale": Spec(_S, "feed", "notices", statewide=NOTICES, doc="listing_type == hoa_sale",
                        ambiguity="10/2 note: a working source exists but its rows are typed foreclosure_sale"),
    "lt_distressed": Spec(_S, "feed", "county_layers", doc="listing_type == distressed (generic distress layers)"),
    "lt_divorce_notice": Spec(_S, "feed", "court", ledger="nc_ecourts_case|divorce",
                              statewide=(("NC", "NC eCourts Judgment Search (open JSON)"),),
                              walls=(("SC", "SC family-court index (Public Index/FCCMS) terms forbid automation"),),
                              doc="listing_type == divorce_notice"),
    "lt_probate_notice": Spec(_S, "feed", "notices", statewide=NOTICES, ledger="probate_heir|court_wall", verify_family="probate", doc="listing_type == probate_notice"),
    "lt_estate_lead": Spec(_S, "feed", "probate", ledger="probate_heir|heir_roll|court_wall", verify_family="probate", doc="listing_type == estate_lead"),
    "lt_elderly_disabled": Spec(_S, "feed", "gis_exempt", ledger="elderly_disabled",
                                doc="listing_type == elderly_disabled"),
    "lt_tax_sale_overage": Spec(_S, "feed", "tax", doc="listing_type == tax_sale_overage",
                                ambiguity="SC counties publish excess-funds lists; NC clerks hold surplus "
                                          "without a published list"),
    "lt_bankruptcy": Spec(_S, "feed", "federal", ledger="bankruptcy_stay",
                          statewide=(("NC", "CourtListener/RECAP (federal)"), ("SC", "CourtListener/RECAP (federal)")),
                          doc="listing_type == bankruptcy"),
    # ---- raw signals ---------------------------------------------------------------------
    "multi_year_delinquent_tax": Spec(_S, "row", "tax", ledger="tax_lien|lien_registry_wall",
                                      producers=("enrichment_tax_owed.py",
                                                 "scrapers/counties_generic/multi_year_delinquent_tax.py"),
                                      doc="raw.multi_year_delinquent_tax present; checked = the tax roll was read "
                                          "(any property-tax block on the row)"),
    "repeat_tax_loss": Spec(_S, "derived", "tax", producers=("enrichment_repeat_tax_loss.py",),
                            doc="raw.repeat_tax_loss present; checked = tax roll read"),
    "heir_estate": Spec(_S, "county", "gis", ledger="probate_heir|heir_roll",
                        producers=("scrapers/counties_nc/nc_heir_estate_parcels.py",
                                   "scrapers/counties_nc/henderson_foreclosure_parcels.py"),
                        doc="raw.heir_estate present (a parcel owner-of-record naming heirs/estate)"),
    "heir_naming_publication": Spec(_S, "county", "notices", statewide=SC_QUIET_TITLE + NC_QUIET_TITLE_READ,
                                    statewide_except=_nc_without_column_paper(),
                                    sources=NC_QUIET_TITLE_SOURCE, walls=NC_QUIET_TITLE_WALL,
                                    producers=("scrapers/newspapers/column_legal_notices.py",
                                               "scrapers/public_notices/nc_heir_notices.py"),
                                    doc="raw.heir_naming_publication present",
                                    ambiguity="SC: Column estate lane; NC: Column notices searched by text (nc_heir_notices); 75 of 100 NC counties have a Column paper"),
    "owner_cluster": Spec(_S, "derived", "derived", producers=("enrichment_owner_cluster.py",),
                          statewide=(("NC", "board-wide owner clustering"), ("SC", "board-wide owner clustering")),
                          doc="raw.owner_cluster present; checked = owner_name present"),
    "divorce_no_subsequent_deed": Spec(_S, "derived", "rod", applies="divorced",
                                       producers=("enrichment_divorce_no_subsequent_deed.py",),
                                       doc="raw.divorce_no_subsequent_deed present; applies to divorce rows; "
                                           "checked = deed chain present"),
    "marriage_license": Spec(_S, "row", "rod", applies="person", producers=("enrichment_marriage_license.py",),
                             doc="raw.marriage_license present",
                             ambiguity="10/1 counts the {'status': 'no_match'} wrapper as a hit; the second "
                                       "view counts only a found license"),
    "bankruptcy_stay": Spec(_S, "row", "federal", applies="bankrupt", ledger="bankruptcy_stay",
                            producers=("enrichment_bankruptcy_stay.py",),
                            statewide=(("NC", "CourtListener/RECAP (federal)"), ("SC", "CourtListener/RECAP (federal)")),
                            doc="raw.bankruptcy_stay present; applies to rows with a bankruptcy match"),
    "bankruptcy_tax_combo": Spec(_S, "derived", "federal", applies="bankrupt",
                                 producers=("enrichment_bankruptcy_tax_combo.py",),
                                 statewide=(("NC", "derived"), ("SC", "derived")),
                                 doc="raw.bankruptcy_tax_combo present; checked = tax roll read"),
    "condemned": Spec(_S, "county", "code", ledger="vacant_structure",
                      producers=("scrapers/city_websites/charlotte_open_data.py",
                                 "scrapers/counties_generic/arcgis_distress_layers.py",
                                 "scrapers/counties_nc/hendersonville_vacant_structures.py",
                                 "scrapers/counties_sc/spartanburg_city_condemned.py",
                                 "scrapers/counties_sc/spartanburg_condemned.py"),
                      doc="raw.condemned is true"),
    "vacant_lot": Spec(_S, "derived", "gis", producers=("enrichment_vacant_landuse.py",),
                       statewide=(("NC", NC_ONEMAP + " land use"),),
                       doc="raw.vacant_lot present; checked = a land-use value is on the row"),
    "vacant": Spec(_S, "county", "code", ledger="vacant_structure",
                   producers=("enrichment_arcgis.py", "scrapers/counties_nc/hendersonville_vacant_structures.py",
                              "scrapers/counties_sc/spartanburg_vacant.py", "nc_burke_spine.py", "nc_lincoln_bulk.py"),
                   doc="raw.vacant present (a city/county vacant-structure registry)"),
    "storm_damage": Spec(_S, "county", "disaster", producers=("enrichment_helene_damage.py",),
                         doc="raw.storm_damage present (post-Helene damage-assessment layers)"),
    "usps_vacancy": Spec(_S, "county", "usps", producers=("enrichment_usps_vacancy.py",),
                         walls=(("NC", "HUD USPS vacancy data needs a registered login"),
                                ("SC", "HUD USPS vacancy data needs a registered login")),
                         doc="raw.usps_vacancy present"),
    "liens": Spec(_S, "row", "rod", producers=("enrichment_dew_liens.py", "enrichment_irs_lien.py",
                                               "enrichment_lien_stack.py",
                                               # the register-of-deeds name readers (raw['rod'] is this
                                               # column's check): the platform registry names the counties
                                               "enrichment_generic_rod.py", "enrichment_rod_chain.py"),
                  doc="raw.liens present; checked = a register-of-deeds pull is on the row (raw.rod)"),
    "child_support": Spec(_S, "derived", "court", applies="court_case",
                          producers=("enrichment_case_detail.py", "enrichment_nc_case_status_tyler.py"),
                          doc="raw.child_support present; applies to rows with a court case"),
    "sc_state_tax_lien": Spec(_S, "state", "state_lien", states=("SC",),
                              statewide=(("SC", "SC state tax lien registry"),),
                              producers=("scrapers/counties_sc/sc_state_tax_lien.py",
                                         "scrapers/counties_sc/sc_dew_lien_registry.py"),
                              doc="raw.sc_state_tax_lien present (SC only)"),
    "lien_priority": Spec(_S, "derived", "rod", applies="has_rod", producers=("rod/enrich.py",),
                          doc="raw.lien_priority present; applies to rows with a register pull"),
    "rollback_exposure": Spec(_S, "county", "tax", producers=("enrichment_rollback_deferral.py",
                                                              "enrichment_tax_relief.py"),
                              doc="raw.rollback_exposure present (present-use/ag deferral rollback)"),
    "jail_booking": Spec(_S, "county", "jail", applies="person", ledger="jail_booking",
                         producers=("enrichment_jail_bookings.py", "scrapers/national/jail_bookings.py",
                                    "jail_matching.py"),
                         doc="raw.jail_booking present (county jail roster match)",
                         ambiguity="counts released bookings and every confidence level"),
    "jail_booking_new": Spec(_S, "county", "jail", applies="person", ledger="jail_booking",
                             producers=("enrichment_jail_bookings.py",), doc="raw.jail_booking_new present"),
    "incarceration": Spec(_S, "row", "prison", applies="person",
                          producers=("enrichment_incarceration.py",),
                          statewide=(("NC", "NC DAC offender search"), ("SC", "SC DOC inmate search")),
                          doc="raw.incarceration present; checked = incarceration or incarceration_check",
                          ambiguity="incarceration_check ({'result': 'no_match'}) is a negative record; 10/1 "
                                    "rightly ignores it for hits; here it counts as 'checked'"),
    "bop_federal": Spec(_S, "row", "prison", applies="person", producers=("enrichment_bop_federal.py",),
                        statewide=(("NC", "federal BOP inmate locator"), ("SC", "federal BOP inmate locator")),
                        doc="raw.bop_federal present; checked = bop_federal or bop_check"),
    "builder_distress": Spec(_S, "state", "liensnc", states=("NC",),
                             statewide=(("NC", "liensnc.com lien-agent filings"),),
                             doc="raw.builder_distress present (NC only)"),
    "liensnc_related": Spec(_S, "state", "liensnc", states=("NC",),
                            statewide=(("NC", "liensnc.com lien-agent filings"),),
                            doc="raw.liensnc_related present (NC only)"),
    "liensnc_posthumous_filing": Spec(_S, "derived", "liensnc", applies="liensnc", states=("NC",),
                                      producers=("enrichment_liensnc_posthumous.py",),
                                      statewide=(("NC", "derived from liensnc + death records"),),
                                      doc="raw.liensnc_posthumous_filing present; applies to NC rows with a liensnc filing"),
    "sos_dissolution": Spec(_S, "row", "sos", applies="entity", producers=("enrichment_sos_dissolution.py",),
                            statewide=(("NC", "NC Secretary of State business search"),),
                            walls=(("SC", "SC Secretary of State search is CAPTCHA-walled"),),
                            doc="raw.sos_dissolution present; applies to entity owners; checked = an SoS lookup "
                                "is on the row (sos_agent)"),
    "title_risk": Spec(_S, "derived", "derived", applies="foreclosure", producers=("enrichment_title_risk.py",),
                       statewide=(("NC", "derived"), ("SC", "derived")),
                       doc="raw.title_risk present; applies to foreclosure-type rows",
                       ambiguity="60% of title_risk blocks are kind 'unknown' (no senior/junior call)"),
    "owner_mismatch": Spec(_S, "derived", "derived", applies="court_party",
                           producers=("enrichment_court_owner_verify.py",),
                           statewide=(("NC", "derived"), ("SC", "derived")),
                           doc="raw.owner_mismatch present; applies to rows with a defendant"),
    "notice_service_defect": Spec(_S, "derived", "derived", applies="foreclosure",
                                  producers=("enrichment_notice_service_defect.py",),
                                  statewide=(("NC", "derived from notice text"), ("SC", "derived from notice text")),
                                  doc="raw.notice_service_defect present; checked = notice text on the row"),
    **{col: Spec(_S, "derived", "derived", statewide=(("NC", "derived from owner_name"), ("SC", "derived from owner_name")),
                 doc=f"owner_name matches /{pat.pattern}/; checked = owner_name present")
       for col, pat in NAME_TOKENS},
    "two_year_delinquent": Spec(_S, "row", "tax", ledger="tax_lien|lien_registry_wall",
                                producers=("scrapers/counties_nc/albemarle_observer_tax_lists.py",
                                           "scrapers/counties_nc/nc_its_public_tax.py",
                                           "scrapers/counties_sc/sc_catalis_delinquent_roll.py"),
                                doc="raw.two_year_delinquent.is_two_year_plus is true; checked = tax roll read"),
    "tax_aging_surfaced": Spec(_S, "row", "tax", ledger="tax_lien|lien_registry_wall", producers=("enrichment_tax_aging.py",),
                               doc="raw.tax_aging_surfaced.status != 'current' and years_delinquent > 0; "
                                   "checked = tax roll read"),
    "divorce": Spec(_S, "row", "court", applies="person", ledger="divorce",
                    producers=("enrichment_nc_divorce.py", "enrichment_sc_divorce.py"),
                    statewide=(("NC", "NC eCourts Judgment Search (open JSON)"),),
                    walls=(("SC", "SC family-court index terms forbid automation"),),
                    doc="raw.divorce.case_count > 0 or cases non-empty; checked = the divorce wrapper is present"),
    "probate": Spec(_S, "county", "probate", applies="person", ledger="probate_heir",
                    producers=("enrichment_probate_search.py", "scrapers/counties_sc/sc_public_notices.py"),
                    doc="raw.probate names a decedent, es_case_number or nc_estate_file_no"),
    "vacancy": Spec(_S, "row", "code", ledger="vacant_structure",
                    producers=("scrapers/counties_nc/hendersonville_vacant_structures.py",),
                    doc="raw.vacancy.vacant/boarded_up/utility_status truthy; checked = vacancy wrapper"),
    "code_enforcement": Spec(_S, "row", "code", ledger="code_enforcement",
                             producers=("enrichment_code_enforcement.py", "enrichment_charlotte_code.py",
                                        "enrichment_greensboro_code.py", "scrapers/counties_nc/asheville_code_enforcement.py",
                                        "scrapers/counties_generic/arcgis_distress_layers.py"),
                             doc="raw.code_enforcement condemned/has_open/severe (or True); checked = wrapper present"),
    "deed_chain_has_history": Spec(_F, "row", "gis_deed", producers=("enrichment_deed_chain.py",),
                                   doc="raw.deed_chain is a dict (history fetched; not a distress signal)",
                                   ambiguity="a dict with an empty transfers list counts as history"),
    "deed_chain_break": Spec(_S, "derived", "gis_deed", producers=("enrichment_deed_chain.py",),
                             doc="raw.deed_chain.summary.chain_breaks truthy; checked = deed chain present"),
    "deed_chain_distress_transfer": Spec(_S, "derived", "gis_deed", producers=("enrichment_deed_chain.py",),
                                         doc="raw.deed_chain.summary.distress_transfers truthy; checked = deed chain present"),
    "quiet_title": Spec(_S, "county", "court", statewide=SC_QUIET_TITLE + NC_QUIET_TITLE_READ,
                        statewide_except=_nc_without_column_paper(), sources=NC_QUIET_TITLE_SOURCE,
                        walls=NC_QUIET_TITLE_WALL,
                        producers=("scrapers/newspapers/column_legal_notices.py",
                                   "scrapers/public_notices/nc_heir_notices.py"),
                        doc="is_quiet_title on raw.column/court/case/rod_docs/heir_naming_publication"),
    # ---- attorney checklist --------------------------------------------------------------
    "atty_legal_description": Spec(_F, "row", "gis_legal",
                                   doc="legal_description, or a legal field in raw.gis_attrs_full / mcdowell_probate"),
    "atty_deed_ref": Spec(_F, "row", "gis_deed", sources=(("NC", NC_ONEMAP + " (deed reference field)"),),
                          doc="a deed book+page (or instrument no.) in deed_chain, gis.last_sale, rod, nc_rod, "
                              "rod_docs, gis_attrs_full or mcdowell_probate"),
    "atty_taxpayer_of_record": Spec(_F, "row", "tax", statewide=(("NC", NC_ONEMAP + " (owner of record)"),),
                                    producers=("parcel_cache.py", "enrichment_qpaybill_tax.py"),
                                    doc="a name read from the tax roll/parcel record: gis.owner, owner_mailing.owner, "
                                        "qpaybill_roll, lrcpwa, heir_estate, mcdowell_probate, or owner_name on a "
                                        "tax_lien/tax_sale row"),
    "atty_heir_candidates": Spec(_F, "row", "probate", applies="deceased", ledger="probate_heir",
                                 doc="heir names or a personal representative (heir_estate, probate, SC probate, "
                                     "obituary survivors); applies to rows whose owner is dead or an estate"),
    "atty_obituary_match": Spec(_S, "county", "obituary", applies="person",
                                producers=("scrapers/public_notices/gannett_obituaries.py",
                                           "scrapers/public_notices/funeral_home_rss.py"),
                                doc="raw.obituary present or life_event == 'death'"),
    "atty_rod_lien_checked": Spec(_F, "row", "rod",
                                  producers=("enrichment_aumentum_rod.py", "enrichment_cchs_rod.py", "enrichment_gaston_rod.py",
                                             "enrichment_generic_rod.py", "enrichment_spartanburg_rod.py",
                                             "scrapers/counties_nc/nc_rod_logan.py", "scrapers/counties_sc/sc_rod_acclaim.py",
                                             "scrapers/counties_sc/sc_rod_cott.py"),
                                  doc="a register-of-deeds instrument pull on the row (raw.rod with instrument_count, "
                                      "rod_docs or nc_rod)"),
    "atty_deed_chain_fetched": Spec(_F, "row", "gis_deed", producers=("enrichment_deed_chain.py",),
                                    doc="raw.deed_chain.transfers is non-empty"),
    "atty_probate_case": Spec(_F, "row", "probate", applies="deceased", ledger="probate_heir",
                              doc="an estate file number (probate, sc_probate_notice, sc_probate_net, or a "
                                  "probate_notice/estate_lead row's case_number); applies to dead/estate owners"),
    "atty_tax_verified_confirmed": Spec(_S, "row", "tax", applies="tax_claim", ledger="tax_lien",
                                        doc="hit = a tax_lien verdict 'confirmed'; checked = any decisive tax_lien "
                                            "verdict (confirmed/refuted/stale); applies to rows claiming delinquent tax"),
}
#: The owner's flip scope (2026-09-15, main._FLIP_LISTING_TYPES / _flip_outside_footprint): a flip
#: type is wanted only in the 18 footprint counties (config.in_scope), plus the oceanfront coastal
#: counties' beach-drive flips (owner, 2026-10-06). Outside them the run drops flip rows by design,
#: so the flip feed columns do not apply there: the cell is "not applicable", not a gap.
FLIP_FEED_COLS = ("lt_foreclosure_sale", "lt_sheriff_sale", "lt_auction", "lt_reo", "lt_hoa_sale")
for _c in FLIP_FEED_COLS:
    SPECS[_c] = replace(SPECS[_c], applies="flip_scope",
                        doc=SPECS[_c].doc + "; applies in the owner's flip scope (18 footprint counties + "
                                            "oceanfront beach-drive counties)")
assert set(SPECS) == set(ALL_COLUMNS), set(ALL_COLUMNS) ^ set(SPECS)
assert len(OWNER_COLUMNS) == 73


# ---------------------------------------------------------------------------------------------
# Scorer-consistent hits (audit 2026-10-09, drops_lineage). The 10/1 definitions count a raw key's
# PRESENCE; for these columns the writer also stores negative results, ended states or weak matches,
# and the scorer (distress_score / signal_freshness / the phone gate) counts a hit only when its own
# predicate says so. The second view now asks the scorer's own predicate (one source of truth), so
# a column means what the scorer acts on. owner_columns() keeps the 10/1 rule for comparability.
# Each gate: column -> (raw key that, when present, still means "checked", predicate).
# ---------------------------------------------------------------------------------------------

def _gate_stay(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.distress_score import _stay_block
    return _stay_block(raw, today) is not None              # {'status': 'lapsed'} or an old stay: no


def _gate_code(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.signal_freshness import code_enforcement_open
    ce = raw.get("code_enforcement")
    return ce not in _EMPTY and code_enforcement_open(ce, today)   # TTL, vacancy_adjacent, lists


def _gate_divorce(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.distress_score import _divorce_signal
    return _divorce_signal(raw, today, rec.get("owner_name")) is not None


def _gate_storm(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.distress_score import _storm_signal
    return _storm_signal(raw.get("storm_damage")) is not None      # moderate or worse


def _gate_vacancy(rec: dict, raw: dict, today: date) -> bool:
    v = raw.get("vacancy")                                          # distress_score._vacant_structure
    return isinstance(v, dict) and (v.get("vacant") is True or v.get("boarded_up") is True)


def _gate_title(rec: dict, raw: dict, today: date) -> bool:
    trs = raw.get("title_risk")
    trs = trs if isinstance(trs, list) else [trs]
    return any(isinstance(t, dict) and t.get("surviving_senior_debt_risk") for t in trs)


def _gate_incarceration(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.signal_freshness import incarceration_active
    return incarceration_active(raw.get("incarceration"), raw.get("jail_booking"), today)


def _gate_jail(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.signal_freshness import custody_ended
    jb = raw.get("jail_booking")
    return isinstance(jb, dict) and bool(jb) and not custody_ended(jb, today)


def _gate_bop(rec: dict, raw: dict, today: date) -> bool:
    b = raw.get("bop_federal")
    return isinstance(b, dict) and b.get("in_custody") is True


def _gate_usps(rec: dict, raw: dict, today: date) -> bool:
    u = raw.get("usps_vacancy")
    return isinstance(u, dict) and str(u.get("vacancy_level") or "").lower() in ("high", "moderate")


def _gate_lien_priority(rec: dict, raw: dict, today: date) -> bool:
    lp = raw.get("lien_priority")
    return isinstance(lp, dict) and any(lp.get(k) for k in ("senior_liens", "junior_liens",
                                                            "super_priority_warnings"))


def _gate_phone(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.enrichment_sc_phone import is_owner_phone_usable
    op = raw.get("owner_phone")
    return isinstance(op, dict) and bool(op.get("phone")) and is_owner_phone_usable(op)


def _gate_email(rec: dict, raw: dict, today: date) -> bool:
    # not a scorer predicate: the outreach one. best_email can be an attorney's or agent's, and the
    # LiensNC owner e-mail has no best_email (enrichment_email_extract.owner_email_of)
    from foreclosure_scraper.enrichment_email_extract import owner_email_of
    return bool(owner_email_of(raw))


def _gate_probate(rec: dict, raw: dict, today: date) -> bool:
    from foreclosure_scraper.signal_freshness import has_real_probate
    return has_real_probate(raw.get("probate"))


def _is_liensnc_row(rec: dict) -> bool:
    return "liensnc" in [p for p in str(rec.get("source") or "").split(".") if p]   # ds._is_liensnc


def _gate_lt_tax_lien(rec: dict, raw: dict, today: date) -> bool:
    # 46,989 LiensNC lien-agent filings are typed tax_lien; the scorer treats them as context only
    return rec.get("listing_type") == "tax_lien" and not _is_liensnc_row(rec)


SCORER_GATES: dict[str, tuple[str, Any]] = {
    "bankruptcy_stay": ("bankruptcy_stay", _gate_stay),
    "code_enforcement": ("code_enforcement", _gate_code),
    "divorce": ("divorce", _gate_divorce),
    "storm_damage": ("storm_damage", _gate_storm),
    "vacancy": ("vacancy", _gate_vacancy),
    "title_risk": ("title_risk", _gate_title),
    "incarceration": ("incarceration", _gate_incarceration),
    "jail_booking": ("jail_booking", _gate_jail),
    "bop_federal": ("bop_federal", _gate_bop),
    "usps_vacancy": ("usps_vacancy", _gate_usps),
    "lien_priority": ("lien_priority", _gate_lien_priority),
    "phone": ("owner_phone", _gate_phone),
    "email": ("owner_email", _gate_email),
    "probate": ("probate", _gate_probate),
    "lt_tax_lien": ("", _gate_lt_tax_lien),
}


def scorer_consistent_hits(rec: dict, owner: set[str], today: Optional[date] = None) -> set[str]:
    """`owner` (the 10/1 hits) with every SCORER_GATES column set to the scorer's own verdict:
    removed where the scorer would not count it, added where the 10/1 rule could not see it (a
    list-shaped code_enforcement block). Pure, given `today`."""
    raw = rec.get("raw") or {}
    if not isinstance(raw, dict):
        raw = {}
    today = today or date.today()
    out = set(owner)
    for col, (_key, gate) in SCORER_GATES.items():
        try:
            hit = bool(gate(rec, raw, today))
        except Exception:  # noqa: BLE001 - an odd block is not a hit
            hit = False
        if hit:
            out.add(col)
        else:
            out.discard(col)
    return out


def positive_columns(rec: dict, owner: set[str], verdicts: dict[str, Optional[str]],
                     today: Optional[date] = None) -> set[str]:
    """The second view's hits: the 10/1 hits with marriage_license's no-match wrapper removed and
    the SCORER_GATES columns set to the scorer's own verdict, plus the attorney columns. Pure."""
    raw = rec.get("raw") or {}
    pos = scorer_consistent_hits(rec, owner, today)
    ml = raw.get("marriage_license")
    if "marriage_license" in pos and not (isinstance(ml, dict) and (ml.get("spouse_name") or ml.get("license_date"))
                                          and ml.get("status") != "no_match"):
        pos.discard("marriage_license")
    if legal_description_present(rec):
        pos.add("atty_legal_description")
    if deed_ref_present(raw):
        pos.add("atty_deed_ref")
    if taxpayer_of_record_present(rec):
        pos.add("atty_taxpayer_of_record")
    if heir_candidates_present(raw):
        pos.add("atty_heir_candidates")
    if obituary_matched(raw):
        pos.add("atty_obituary_match")
    if rod_checked(raw):
        pos.add("atty_rod_lien_checked")
    if deed_chain_fetched(raw):
        pos.add("atty_deed_chain_fetched")
    if probate_case_present(rec):
        pos.add("atty_probate_case")
    if verdicts.get("tax_lien") == "confirmed":
        pos.add("atty_tax_verified_confirmed")
    return pos


def checked_columns(rec: dict, pos: set[str], verdicts: dict[str, Optional[str]]) -> set[str]:
    """Columns whose check observably ran for this row: a hit, a negative-result wrapper, or
    (derived columns) the inputs being present. County/state/feed-scope columns only show a
    hit here; the county roll-up decides the rest. Pure."""
    raw = rec.get("raw") or {}
    out = set(pos)
    # a scorer-gated column whose block is on the row was checked, hit or not (scorer_consistent_hits)
    out |= {c for c, (k, _g) in SCORER_GATES.items() if k and raw.get(k) not in _EMPTY}
    tax = tax_status_known(raw)
    if tax:
        out |= {"multi_year_delinquent_tax", "repeat_tax_loss", "two_year_delinquent", "tax_aging_surfaced",
                "bankruptcy_tax_combo"}
    # gis_fill.py screened this parcel in its county layer and the record is blank for the field: a dated
    # per-row 'screened, none found' verdict for the four fill columns it covers (roll_up counts it)
    from foreclosure_scraper import gis_fill as _gf
    out |= _gf.verdict_columns(raw)
    if isinstance(raw.get("owner_email"), dict):
        out.add("email")
    if isinstance(raw.get("divorce"), dict):
        out.add("divorce")
    if isinstance(raw.get("vacancy"), dict):
        out.add("vacancy")
    if raw.get("code_enforcement") is not None and raw.get("code_enforcement") != {}:
        out.add("code_enforcement")
    if isinstance(raw.get("deed_chain"), dict):
        out |= {"deed_chain_break", "deed_chain_distress_transfer", "divorce_no_subsequent_deed"}
    ml = raw.get("marriage_license")
    if isinstance(ml, dict) and (ml.get("checked_at") or ml.get("license_date") or ml.get("spouse_name")):
        out.add("marriage_license")          # an undated no-match (retired module) is not a check
    if raw.get("incarceration") or raw.get("incarceration_check"):
        out.add("incarceration")
    if raw.get("bop_federal") or raw.get("bop_check"):
        out.add("bop_federal")
    if raw.get("bankruptcy_stay"):
        out.add("bankruptcy_stay")
    if rec.get("owner_name"):
        out |= {"owner_cluster"} | {c for c, _ in NAME_TOKENS}
    if rec.get("land_use") or raw.get("vacant_lot"):
        out.add("vacant_lot")
    if raw.get("rod") or raw.get("liens"):
        out |= {"liens", "lien_priority"}
    sweep = raw.get("rod_lien_sweep")
    if isinstance(sweep, dict) and sweep.get("status") and sweep.get("checked_at"):
        out.add("liens")          # 'screened, none found' is a check; the stamp carries its window
    if raw.get("nc_ecourts") or raw.get("court") or raw.get("court_record"):
        out.add("child_support")
    if raw.get("liensnc"):
        out.add("liensnc_posthumous_filing")
    if raw.get("sos_agent") or raw.get("sos_dissolution"):
        out.add("sos_dissolution")
    if rec.get("plaintiff") or rec.get("defendant"):
        out.add("title_risk")
    if rec.get("owner_name") and rec.get("defendant"):
        out.add("owner_mismatch")
    if rec.get("description"):
        out.add("notice_service_defect")
    if verdicts.get("tax_lien") in ("confirmed", "refuted", "stale"):
        out.add("atty_tax_verified_confirmed")
    else:
        out.discard("atty_tax_verified_confirmed")
    return out


def applicable_columns(rec: dict, rules: set[str]) -> set[str]:
    st = (rec.get("state") or "").strip().upper()
    return {c for c, s in SPECS.items() if s.applies in rules and st in s.states}


# =============================================================================================
# Verification verdicts (ledgers + raw.verification), read only
# =============================================================================================

LEDGER_DIR = REPO / "docs" / "handoff" / "verification"
DECISIVE = ("confirmed", "refuted", "stale")


def load_ledger_index(directory: Path = LEDGER_DIR) -> tuple[dict[str, dict[str, Optional[str]]], dict]:
    """{signal: {property key: latest verdict}} from every ledger, either layout (the single
    <signal>.json or the <signal>/ shard directory, both merged while a ledger is in transition:
    verification.ledger LAYOUTS), and per-signal summary counts by (state, county, verdict). A
    case-scoped key '<case>@<key>' indexes by its property part. One ledger in memory at a time."""
    from foreclosure_scraper.verification import ledger as VL

    idx: dict[str, dict[str, Optional[str]]] = {}
    by_county: dict = {}
    for name in VL.signals_on_disk(directory):
        led = VL.Ledger.load(name, directory, strict=False)
        for what, why in {**led.problems, **led.warnings}.items():
            print(f"  ledger {what}: {why} ({'skipped' if what in led.problems else 'read'})",
                  file=sys.stderr)
        if not led.rows:
            continue
        sig = led.signal or name
        m = idx.setdefault(sig, {})
        bc = by_county.setdefault(sig, Counter())
        for k, e in led.rows.items():
            if not isinstance(e, dict):
                continue
            verdict = (e.get("latest") or {}).get("verdict")
            row = e.get("row") or {}
            bc[f"{(row.get('state') or '').upper()}|{canonical_county(row.get('county')) or UNKNOWN}|{verdict}"] += 1
            for key in [k] + list(e.get("keys") or []):
                pp = str(key).split("@", 1)[1] if "@" in str(key) else str(key)
                if pp.startswith("row:"):
                    continue
                prev = m.get(pp)
                if prev in DECISIVE and verdict not in DECISIVE:
                    continue
                m[pp] = verdict
    return idx, {s: dict(c) for s, c in by_county.items()}


def row_verdicts(rec: dict, idx: dict[str, dict[str, Optional[str]]], keys: Iterable[str]) -> dict[str, Optional[str]]:
    """{signal: verdict} for the row: raw.verification records first (what the VM attached),
    then the ledgers by any of the row's property keys."""
    out: dict[str, Optional[str]] = {}
    raw = rec.get("raw") or {}
    ver = raw.get("verification")
    if isinstance(ver, list):
        for v in ver:
            if isinstance(v, dict) and v.get("signal"):
                out[v["signal"]] = v.get("verdict")
    keys = list(keys)
    for sig, m in idx.items():
        if sig in out and out[sig] in DECISIVE:
            continue
        for k in keys:
            if k in m:
                v = m[k]
                if sig not in out or (v in DECISIVE and out.get(sig) not in DECISIVE):
                    out[sig] = v
                break
    return out


# =============================================================================================
# County records matrix: source status per (family, county)
# =============================================================================================

ACCESS_WALL = {"captcha": "CAPTCHA", "blocked": "bot check (Cloudflare/WAF)", "login": "login",
               "payment": "paywall"}
ACCESS_FREE = {"open", "disclaimer_click"}


def load_matrix(path: Path) -> dict[tuple[str, str], dict]:
    try:
        m = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    return {((c.get("state") or "").upper(), canonical_county(c.get("county"))): c for c in m.get("counties") or []}


def _host(url: Any) -> str:
    m = re.match(r"https?://([^/]+)", str(url or ""))
    return m.group(1) if m else ""


def _access_status(block: dict, free_flag: str) -> tuple[str, str]:
    acc = str(block.get("access") or "").lower()
    if acc in ACCESS_WALL:
        return "walled", ACCESS_WALL[acc]
    if str(block.get("terms_forbid_automation") or "") == "yes":
        return "walled", "terms forbid automation"
    if acc in ACCESS_FREE or str(block.get(free_flag) or "") == "yes":
        return "free", ""
    if acc == "unreachable":
        return "unknown", "site unreachable on 2026-10-07"
    return "unknown", ""


def source_status(spec: Spec, state: str, crec: Optional[dict], col: str = "") -> tuple[str, str, str]:
    """(status, wall, where): status free | walled | unknown. `where` names the source.
    `col` lets a county's register block carry a per-column verdict (rod.column_access[col]:
    a wall kind from ACCESS_WALL, or 'none' = no free source), for the columns whose source is a
    different system of the same office (marriage licenses: the vital-records login, the probate
    court) than the name index the rest of the block describes."""
    sw = dict(spec.statewide).get(state)
    if sw and spec.statewide_except and crec and \
            (state, canonical_county(crec.get("county"))) in set(spec.statewide_except):
        sw = None
    if sw:
        return "free", "", f"statewide: {sw}"
    wall = dict(spec.walls).get(state)
    if wall:
        return "walled", wall, f"statewide: {wall}"
    known = dict(spec.sources).get(state)
    if known:
        return "free", "", f"statewide (not read yet): {known}"
    fam = spec.family
    if not crec:
        return "unknown", "", "county missing from the county records matrix" if fam in (
            "rod", "probate", "tax", "assessor", "gis", "gis_legal", "gis_deed") else ""
    rod, pro, tax, gis = (crec.get(k) or {} for k in ("rod", "probate", "tax", "gis"))
    if fam == "rod":
        ca = str((rod.get("column_access") or {}).get(col) or "").lower() if col else ""
        if ca in ACCESS_WALL:
            return "walled", ACCESS_WALL[ca], f"register: {_host(rod.get('url'))} ({col}: {ca})"
        if ca == "none":
            return "unknown", "", f"register: {_host(rod.get('url'))} ({col}: no free source)"
        st, w = _access_status(rod, "free_name_search")
        return st, w, f"register: {rod.get('platform') or ''} {_host(rod.get('url'))}".strip()
    if fam == "probate":
        st, w = _access_status(pro, "free_search")
        return st, w, f"probate: {_host(pro.get('url'))}"
    if fam in ("tax", "assessor"):
        st, w = _access_status(tax, "free_by_parcel")
        return st, w, f"tax/property card: {_host(tax.get('url'))}"
    if fam == "gis":
        if gis.get("url") or str(gis.get("owner_field")) == "yes":
            return "free", "", f"county GIS: {_host(gis.get('url'))}"
        return "unknown", "", ""
    if fam == "gis_legal":
        if str(gis.get("legal_description_field")) == "yes":
            return "free", "", f"county GIS legal field: {_host(gis.get('url'))}"
        if str(rod.get("legal_description_in_index")) == "yes":
            st, w = _access_status(rod, "free_name_search")
            return st, w, f"register index: {_host(rod.get('url'))}"
        if str(gis.get("legal_description_field")) == "no" and str(rod.get("legal_description_in_index")) == "no":
            return "walled", "only on the deed image", f"register: {_host(rod.get('url'))}"
        return "unknown", "", ""
    if fam == "sales":
        # the VERIFYING source of a sold comp is a recorded sale price keyed to an address. Read
        # 2026-10-09: NC OneMap carries a sale date but no price; the only county layers with a
        # price are Buncombe (verified: verifiers/comps_buncombe), Anderson (SALOCA is a legal
        # description, no address key) and Cleveland (no address; a two-hop join nobody validated)
        return "unknown", "", "no free per-sale price record outside Buncombe"
    if fam == "gis_deed":
        if str(gis.get("deed_book_page_field")) == "yes":
            return "free", "", f"county GIS deed book/page: {_host(gis.get('url'))}"
        st, w = _access_status(rod, "free_name_search")
        return st, w, f"register index: {_host(rod.get('url'))}"
    return "unknown", "", ""


# =============================================================================================
# "Built in code": which counties each producer file names
# =============================================================================================

def _county_patterns() -> list[tuple[str, str, re.Pattern]]:
    out = []
    for st, names in STATE_COUNTIES.items():
        for n in names:
            slug = r"[ _-]?".join(re.escape(w) for w in n.lower().split())
            out.append((st, n, re.compile(r"(?i)(?:['\"/_]" + slug + r"(?:['\"_.]|\s+county)|\b" + slug
                                          + r"\s+county\b)")))
    return out


def counties_named_in(paths: Iterable[Path], pats=None) -> set[tuple[str, str]]:
    """(state, county) pairs a set of source files name (quoted, in a slug/filename, or as
    'X County'). A county name shared by both states (Union, Cherokee, Lee, Beaufort) counts for
    both: a grep cannot tell them apart."""
    pats = pats or _county_patterns()
    found: set[tuple[str, str]] = set()
    for p in paths:
        try:
            rel = str(p.relative_to(PKG)) if p.is_relative_to(PKG) else p.name
            text = "/" + rel.lower() + "\n" + p.read_text(errors="ignore")
        except OSError:
            continue
        for st, n, rx in pats:
            if rx.search(text):
                found.add((st, n))
    return found


def listing_type_producers(lt: str) -> list[Path]:
    rx = re.compile(r"ListingType\." + lt.upper() + r"\b|listing_type\s*=\s*['\"]" + lt + r"['\"]")
    out = []
    for p in (PKG / "scrapers").rglob("*.py"):
        try:
            if rx.search(p.read_text(errors="ignore")):
                out.append(p)
        except OSError:
            continue
    return out


def built_in_code() -> dict[str, set[tuple[str, str]]]:
    pats = _county_patterns()
    out: dict[str, set[tuple[str, str]]] = {}
    for col, spec in SPECS.items():
        files = [PKG / f for f in spec.producers]
        if spec.scope == "feed":
            files += listing_type_producers(LISTING_TYPE_COLS[col])
        out[col] = counties_named_in([f for f in files if f.exists()], pats) if files else set()
    # marriage licenses: the Cott v4 tenants whose guest search carries a MARRIAGES index are read by
    # enrichment_register_checks (rod/register_checks.MARRIAGE_ADAPTER); the module names no county in text
    try:
        from foreclosure_scraper.rod import register_checks as _rc
        out.setdefault("marriage_license", set()).update(("NC", c) for c in _rc.MARRIAGE_ADAPTER.counties)
    except Exception:  # noqa: BLE001 - a missing optional module only leaves the cell 'not built'
        pass
    return out


# =============================================================================================
# Data-correctness invariants (pure, counts only)
# =============================================================================================

_ADDR_LIKE = re.compile(r"^\s*\d+\s+\S+.*\b(ST|STREET|RD|ROAD|AVE|AVENUE|DR|DRIVE|LN|LANE|CT|COURT|HWY|BLVD|WAY|"
                        r"CIR|PL|TRL|PKWY|PO BOX)\b", re.I)
_PO_BOX = re.compile(r"\bP\.?\s*O\.?\s*BOX\b", re.I)
STATE_BBOX = {"NC": (33.7, 36.65, -84.4, -75.3), "SC": (31.95, 35.3, -83.45, -78.45)}
ZIP_PREFIX = {"NC": ("27", "28"), "SC": ("29",)}


def parcel_shape(pid: Any) -> str:
    """'9999-99-9999' style shape of a parcel id: digits -> 9, letters -> A, runs kept."""
    s = str(pid or "").strip()
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", s))[:40]


def parcel_junk(pid: Any) -> bool:
    s = re.sub(r"[^A-Za-z0-9]", "", str(pid or ""))
    if not s:
        return False
    return (len(s) < 4 or not re.search(r"\d", s) or set(s) <= {"0"}
            or bool(re.search(r"(?i)unknown|none|^na$|tbd|various", s)))


def phone_problem(phone: Any) -> Optional[str]:
    """None for a well-formed NANP 10-digit number, else the problem."""
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return "not_10_digits"
    if d[0] in "01" or d[3] in "01":
        return "bad_area_or_exchange"
    if d[3:6] == "555" and d[6:8] == "01":
        return "fictional_555"
    if len(set(d)) == 1:
        return "repeated_digit"
    return None


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s[:32])
    except ValueError:
        try:
            dt = datetime.strptime(str(v)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def row_invariants(rec: dict, today: date) -> set[str]:
    """Names of the data-correctness invariants the row breaks. Pure."""
    out: set[str] = set()
    raw = rec.get("raw") or {}
    st = (rec.get("state") or "").strip().upper()
    co_raw = (rec.get("county") or "").strip()
    co = canonical_county(co_raw)
    if not co_raw:
        out.add("county_blank")
    elif co not in STATE_COUNTIES.get(st, ()):
        out.add("county_not_in_state")
    elif co_raw != co:
        out.add("county_noncanonical_spelling")
    z = str(rec.get("zip_code") or "").strip()
    if z and st in ZIP_PREFIX and not z.startswith(ZIP_PREFIX[st]):
        out.add("zip_not_in_state")
    lat, lon = rec.get("latitude"), rec.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and st in STATE_BBOX:
        a, b, c, d = STATE_BBOX[st]
        if not (a <= lat <= b and c <= lon <= d):
            out.add("latlon_outside_state")
    if rec.get("parcel_id") and parcel_junk(rec.get("parcel_id")):
        out.add("parcel_junk")
    name = rec.get("owner_name")
    if isinstance(name, str) and name:
        if _ADDR_LIKE.search(name) or _PO_BOX.search(name):
            out.add("owner_name_looks_like_address")
        om = raw.get("owner_mailing")
        mail = om.get("mailing") if isinstance(om, dict) else om
        if mail and _norm(name) and _norm(name) == _norm(mail):
            out.add("owner_name_equals_mailing")
    if raw.get("address_was_owner_mailing"):
        out.add("situs_was_owner_mailing")
    calc = raw.get("calc") or {}
    arv = calc.get("arv_expected") if isinstance(calc, dict) else None
    if isinstance(arv, (int, float)):
        if arv <= 0:
            out.add("arv_nonpositive")
        elif arv > 5_000_000:
            out.add("arv_over_5m")
        base = rec.get("tax_value") or rec.get("assessed_value") or rec.get("market_value")
        if isinstance(base, (int, float)) and base >= 10_000 and arv > 0:
            if arv / base > 5:
                out.add("arv_over_5x_assessed")
            elif arv / base < 0.2:
                out.add("arv_under_0.2x_assessed")
        sq = rec.get("living_sqft")
        if isinstance(sq, (int, float)) and sq >= 300 and arv > 0:
            if arv / sq > 1000:
                out.add("arv_over_1000_per_sqft")
            elif arv / sq < 15:
                out.add("arv_under_15_per_sqft")
    now = datetime(today.year, today.month, today.day)
    sd = _parse_dt(rec.get("sale_date"))
    if sd and (sd < datetime(1990, 1, 1) or sd > now + timedelta(days=730)):
        out.add("sale_date_impossible")
    fs, ls = _parse_dt(rec.get("first_seen")), _parse_dt(rec.get("last_seen"))
    if fs and ls and fs > ls + timedelta(seconds=1):
        out.add("first_seen_after_last_seen")
    if ls and ls > now + timedelta(days=2):
        out.add("last_seen_in_future")
    yb = rec.get("year_built")
    if isinstance(yb, (int, float)) and yb and (yb < 1700 or yb > today.year + 1):
        out.add("year_built_impossible")
    ub = _parse_dt(rec.get("upset_bid_deadline"))
    if ub and sd and ub < sd:
        out.add("upset_deadline_before_sale")
    rd = _parse_dt(rec.get("redemption_deadline"))
    if rd and sd and rd < sd:
        out.add("redemption_before_sale")
    lsale = raw.get("last_sale")
    lsd = _parse_dt(lsale.get("date")) if isinstance(lsale, dict) else None
    if lsd and lsd > now + timedelta(days=2):
        out.add("last_sale_in_future")
    ph = raw.get("owner_phone")
    if isinstance(ph, dict) and ph.get("phone"):
        prob = phone_problem(ph["phone"])
        if prob:
            out.add("phone_" + prob)
    return out


# =============================================================================================
# The pass
# =============================================================================================

def county_key(rec: dict) -> tuple[str, str]:
    st = (rec.get("state") or "?").strip().upper() or "?"
    return st, canonical_county(rec.get("county")) or UNKNOWN


def _h(s: str) -> bytes:
    return hashlib.blake2b(s.encode(), digest_size=8).digest()


@dataclass
class Cube:
    today: date
    ledger_idx: dict = field(default_factory=dict)
    verifiers: list = field(default_factory=list)
    rows: Counter = field(default_factory=Counter)
    owner: dict = field(default_factory=lambda: defaultdict(Counter))      # 10/1 hits
    app: dict = field(default_factory=lambda: defaultdict(Counter))
    pos: dict = field(default_factory=lambda: defaultdict(Counter))
    chk: dict = field(default_factory=lambda: defaultdict(Counter))
    v_any: dict = field(default_factory=lambda: defaultdict(Counter))      # hit rows with any verdict
    v_dec: dict = field(default_factory=lambda: defaultdict(Counter))      # hit rows with a decisive verdict
    v_conf: dict = field(default_factory=lambda: defaultdict(Counter))
    v_applies: dict = field(default_factory=lambda: defaultdict(Counter))  # hit rows a verifier covers
    v_wall: dict = field(default_factory=lambda: defaultdict(Counter))     # hit rows only a WALL verifier covers
    slug_county: Counter = field(default_factory=Counter)
    slug_lt: Counter = field(default_factory=Counter)
    slug_rows: Counter = field(default_factory=Counter)
    inv: dict = field(default_factory=lambda: defaultdict(Counter))         # invariant -> county -> n
    shapes: dict = field(default_factory=lambda: defaultdict(Counter))      # county -> parcel shape -> n
    parcels: dict = field(default_factory=dict)                            # hash -> count
    phone_owner: dict = field(default_factory=dict)                        # phone hash -> (owner hash, multi)
    phone_rows: Counter = field(default_factory=Counter)
    phone_source: Counter = field(default_factory=Counter)
    unknown_sources: Counter = field(default_factory=Counter)
    n: int = 0

    def add(self, rec: dict) -> None:
        self.n += 1
        raw = rec.get("raw")
        if not isinstance(raw, dict):
            raw = rec["raw"] = {}
        key = county_key(rec)
        self.rows[key] += 1
        owner = owner_columns(rec)
        keys: list[str] = []
        if self.ledger_idx:
            from foreclosure_scraper.verification.core import row_keys
            try:
                keys = row_keys(rec)
            except Exception:  # noqa: BLE001 - an odd row has no key
                keys = []
        verdicts = row_verdicts(rec, self.ledger_idx, keys) if (self.ledger_idx or raw.get("verification")) else {}
        pos = positive_columns(rec, owner, verdicts)
        rules = row_rules(rec, raw, owner)
        app = applicable_columns(rec, rules)
        chk = checked_columns(rec, pos, verdicts)
        for c in owner:
            self.owner[key][c] += 1
        for c in app:
            self.app[key][c] += 1
        for c in pos & app:
            self.pos[key][c] += 1
        for c in chk & app:
            self.chk[key][c] += 1
        # verification depth, for hit rows of columns that have a ledger
        sig_applies: dict[str, str] = {}
        for v in self.verifiers:
            if v.signal in sig_applies and sig_applies[v.signal] == "live":
                continue
            try:
                ok = v.applies(rec)
            except Exception:  # noqa: BLE001 - a verifier that chokes on a row covers nothing
                ok = False
            if ok:
                sig_applies[v.signal] = "wall" if v.wall else "live"
        for c in pos & app:
            sigs = ledger_signals(SPECS[c])
            if not sigs:
                continue
            if c == "atty_tax_verified_confirmed":
                continue
            # a column may name several verifier signals ("a|b"): the best verdict of any of them
            vds = [verdicts.get(sg) for sg in sigs]
            vd = next((v for v in vds if v in DECISIVE), None) or next((v for v in vds if v), None)
            if vd:
                self.v_any[key][c] += 1
            if vd in DECISIVE:
                self.v_dec[key][c] += 1
            if vd == "confirmed":
                self.v_conf[key][c] += 1
            kinds = {sig_applies.get(sg) for sg in sigs}
            if "live" in kinds:
                self.v_applies[key][c] += 1
            elif "wall" in kinds:
                self.v_wall[key][c] += 1
        src = str(rec.get("source") or "")
        self.slug_county[(src, key)] += 1
        self.slug_lt[(src, str(rec.get("listing_type")))] += 1
        self.slug_rows[src] += 1
        if key[1] == UNKNOWN:
            self.unknown_sources[(key[0], src)] += 1
        # correctness
        for name in row_invariants(rec, self.today):
            self.inv[name][key] += 1
        pid = rec.get("parcel_id")
        if pid:
            self.shapes[key][parcel_shape(pid)] += 1
            from foreclosure_scraper.models import _normalize_parcel
            np_ = _normalize_parcel(pid)
            if np_:
                hk = _h(f"{key[0]}|{key[1]}|{np_}")
                self.parcels[hk] = self.parcels.get(hk, 0) + 1
        ph = raw.get("owner_phone")
        if isinstance(ph, dict) and ph.get("phone"):
            d = re.sub(r"\D", "", str(ph["phone"]))[-10:]
            hp = _h(d)
            ho = _h(_norm(rec.get("owner_name")))
            prev = self.phone_owner.get(hp)
            if prev is None:
                self.phone_owner[hp] = (ho, 1)
            elif prev[0] != ho:
                self.phone_owner[hp] = (prev[0], prev[1] + 1)
            self.phone_rows[hp] += 1
            self.phone_source[str(ph.get("source"))] += 1


# =============================================================================================
# Roll-up, classification, outputs
# =============================================================================================

def pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 2) if b else 0.0


NEXT_ACTION = {
    ("sourced-not-built", "rod"): "build a register adapter for {where}",
    ("sourced-not-built", "probate"): "add a probate reader for {where}",
    ("sourced-not-built", "tax"): "add a tax-roll reader for {where}",
    ("sourced-not-built", "assessor"): "add a property-card (CAMA) reader for {where}",
    ("sourced-not-built", "gis"): "add the county parcel layer ({where}) to parcel_cache",
    ("sourced-not-built", "gis_legal"): "read the legal-description field from {where}",
    ("sourced-not-built", "gis_deed"): "read deed book/page from {where}",
}


def next_action(cls: str, col: str, spec: Spec, where: str, wall: str, crec: Optional[dict], missing: int,
                ran: bool = True) -> str:
    if cls == "not applicable":
        return "none"
    if cls.startswith("walled"):
        lane = (crec or {}).get("manual_lane") if spec.family in ("rod", "probate", "tax", "gis_legal",
                                                                    "gis_deed", "assessor") else None
        if lane:
            return "manual lane: " + str(lane)[:140]
        return f"human lane or a lawful source: {where or wall}"[:160]
    if spec.family == "email" and not cls.startswith("walled"):
        return "no free owner-email source: e-mails come only from notices and filings; research a lawful source"
    if cls == "built-but-low-yield":
        prod = ", ".join(Path(p).stem for p in spec.producers[:2]) or "existing enrichers"
        if spec.kind == "field":
            return f"backfill {col} for the {missing:,} applicable rows without it ({prod})"
        if spec.scope in ("county", "state", "feed") and not ran:
            return (f"code covers this county ({prod}) but nothing landed here: run it for this county and "
                    f"stamp 'screened, none found' so {missing:,} rows count as checked")[:200]
        if spec.scope == "derived":
            return f"{missing:,} rows lack the inputs {col} is computed from: fill the inputs, then recompute"
        return f"screen the {missing:,} unchecked rows ({prod}); write a negative result per row"
    if cls == "sourced-not-built":
        t = NEXT_ACTION.get((cls, spec.family))
        if t:
            return t.format(where=where or "the county portal")[:160]
        return f"build {col} for this county from {where or 'the known source'}"[:160]
    return f"research a free source for {col} in this county"


#: fill columns whose per-row 'screened, none found' verdict (gis_fill.verdict_columns) counts as checked
GIS_FILL_VERDICT_COLS = frozenset({"atty_deed_ref", "atty_legal_description", "assessed_value", "lot_size"})


def fill_verdict_class(st: str, co: str, col: str, cls: Optional[str]) -> Optional[str]:
    """A fill cell that ENDS as a verdict (gis_fill.VERDICTS: the county's only source is behind a bot check, or
    no free source exists) reads walled / no source known instead of built-but-low-yield. Pure."""
    if cls is None or not cls.startswith("built-but-low-yield"):
        return cls
    from foreclosure_scraper import gis_fill as _gf
    v = _gf.verdict_for(st, co, col)
    if not v:
        return cls
    return "walled (Cloudflare check on the county property card)" if v[0] == "walled" else "no source known"


def classify_cell(spec: Spec, app: int, target: int, ran: bool, built: str, src: tuple[str, str, str]) -> Optional[str]:
    """The cell's gap class, or None when it is at 100% of its target. Pure."""
    if app == 0:
        return "not applicable"
    if target >= app:
        return None
    status, wall, _ = src
    if ran:
        return "built-but-low-yield"
    if built == "code" and status != "walled":
        return "built-but-low-yield"
    if status == "walled":
        return f"walled ({wall})"
    if status == "free":
        return "sourced-not-built"
    return "no source known"


def roll_up(cube: Cube, matrix: dict, code_counties: dict[str, set], screens: Optional[dict] = None) -> dict:
    """screens: a screen ledger (foreclosure_scraper.screen_ledger, docs/screen_ledger.json) of the
    run that wrote the board. A county/state/feed-scope cell it records as screened RAN even with
    no hit on the board ('screened, none found'); a county-roster row column it records (the tax
    family) counts every applicable row as checked."""
    from foreclosure_scraper import screen_ledger as SL
    counties = sorted(cube.rows, key=lambda k: (k[0], k[1] == UNKNOWN, k[1]))
    # feeds: which slugs emit each listing type, and where they have rows
    lt_slugs: dict[str, set[str]] = defaultdict(set)
    for (slug, lt), n in cube.slug_lt.items():
        lt_slugs[lt].add(slug)
    slug_where: dict[str, set] = defaultdict(set)
    for (slug, key), n in cube.slug_county.items():
        slug_where[slug].add(key)
    state_hits: dict[str, Counter] = defaultdict(Counter)
    for key in counties:
        for c, n in cube.pos[key].items():
            state_hits[c][key[0]] += n
    # median hit rate per (column, state) among counties where the feed/roster ran: an
    # estimate of what a county that is blind would hold
    rates: dict[tuple[str, str], list[float]] = defaultdict(list)
    cells: dict[tuple, dict] = {}
    for key in counties:
        st, co = key
        crec = matrix.get(key)
        for col, spec in SPECS.items():
            app = cube.app[key][col]
            pos = cube.pos[key][col]
            chk = cube.chk[key][col]
            if spec.scope == "feed":
                lt = LISTING_TYPE_COLS[col]
                ran = any(key in slug_where[s] for s in lt_slugs.get(lt, ()))
            elif spec.scope == "state":
                ran = state_hits[col][st] > 0
            else:
                ran = pos > 0 or chk > 0
            scr = bool(screens) and co != UNKNOWN and SL.screened(screens, col, st, co)
            if scr and spec.kind == "signal" and (spec.scope in ("county", "state", "feed")
                                                  or col in SL.COUNTY_ROSTER_ROW_COLUMNS):
                ran = True
            if spec.kind == "field":
                # a fill column gis_fill screens: a row whose county parcel record is blank for it carries a
                # 'screened, none found' verdict (checked), which closes the row like a hit
                target = chk if col in GIS_FILL_VERDICT_COLS else pos
            elif spec.scope in ("county", "state", "feed"):
                target = app if ran else 0
            elif scr and col in SL.COUNTY_ROSTER_ROW_COLUMNS:
                target = app
            else:
                target = chk
            if spec.statewide and dict(spec.statewide).get(st):
                built = "ran" if ran else "code"
            elif ran:
                built = "ran"
            elif (st, co) in code_counties.get(col, set()):
                built = "code"
            else:
                built = "no"
            src = source_status(spec, st, crec, col) if co != UNKNOWN else ("unknown", "", "county unknown")
            cells[(st, co, col)] = dict(app=app, pos=pos, chk=chk, target=target, ran=ran, built=built, src=src,
                                        screened=scr,
                                        v_any=cube.v_any[key][col], v_dec=cube.v_dec[key][col],
                                        v_conf=cube.v_conf[key][col], v_applies=cube.v_applies[key][col],
                                        v_wall=cube.v_wall[key][col])
            if ran and app and spec.kind == "signal":
                rates[(col, st)].append(pos / app)
    med = {k: statistics.median(v) for k, v in rates.items() if v}
    gaps = []
    for (st, co, col), c in cells.items():
        spec = SPECS[col]
        crec = matrix.get((st, co))
        if co == UNKNOWN:
            cls = "built-but-low-yield" if c["app"] else "not applicable"
            if c["app"] and c["target"] >= c["app"]:
                cls = None
        else:
            cls = classify_cell(spec, c["app"], c["target"], c["ran"], c["built"], c["src"])
            cls = fill_verdict_class(st, co, col, cls)
        c["class"] = cls
        if cls is None:
            continue
        missing = max(c["app"] - c["target"], 0)
        est = missing
        if spec.scope == "feed" and not c["ran"]:
            est = round(med.get((col, st), 0.0) * cube.rows[(st, co)])
        action = ("resolve the county (zip / lat-lon / city) before any county check can run"
                  if co == UNKNOWN and cls != "not applicable"
                  else next_action(cls, col, spec, c["src"][2], c["src"][1], crec, missing, c["ran"]))
        gaps.append(dict(state=st, county=co, column=col, layer="fill" if spec.kind == "field" else "check",
                         kind=spec.kind, scope=spec.scope, applicable=c["app"], target=c["target"],
                         pct=pct(c["target"], c["app"]), est_rows_affected=est, gap_class=cls,
                         next_action=action, source=c["src"][2], built=c["built"], ran=c["ran"],
                         matrix_ref=f"county_records_matrix.json#{st}/{co}" if crec else ""))
        c["est"] = est
    # the verification layer: hit rows of a ledger-backed column without a decisive verdict
    for (st, co, col), c in cells.items():
        spec = SPECS[col]
        if not spec.ledger or col == "atty_tax_verified_confirmed" or c["pos"] == 0:
            continue
        if c["v_dec"] >= c["pos"]:
            continue
        missing = c["pos"] - c["v_dec"]
        vsrc = c["src"]
        if spec.verify_family:
            import dataclasses
            vsrc = source_status(dataclasses.replace(spec, family=spec.verify_family, statewide=(), sources=(),
                                                     walls=()), st, matrix.get((st, co)))
        if c["v_applies"] > 0:
            cls, act = "built-but-low-yield", f"run the {spec.ledger.replace('|', ' / ')} sweep over the {missing:,} unverified hit rows"
        elif c["v_wall"] > 0:
            cls, act = "walled (verifier is a declared wall)", f"human lane for {spec.ledger} in this county"
        elif vsrc[0] == "walled":
            cls, act = f"walled ({vsrc[1]})", f"human lane for {spec.ledger}: {vsrc[2]}"[:160]
        elif vsrc[0] == "free":
            cls, act = "sourced-not-built", f"write a {spec.ledger} verifier for this county ({vsrc[2]})"[:160]
        else:
            cls, act = "no source known", f"find an authoritative page to verify {spec.ledger} here"
        gaps.append(dict(state=st, county=co, column=col, layer="verify", kind=spec.kind, scope=spec.scope,
                         applicable=c["pos"], target=c["v_dec"], pct=pct(c["v_dec"], c["pos"]),
                         est_rows_affected=missing, gap_class=cls, next_action=act, source=vsrc[2],
                         built=c["built"], ran=c["ran"],
                         matrix_ref=f"county_records_matrix.json#{st}/{co}" if matrix.get((st, co)) else ""))
    gaps.sort(key=lambda g: (-g["est_rows_affected"], g["state"], g["county"], g["column"]))
    return dict(counties=counties, cells=cells, gaps=gaps, median_rates=med)


INVARIANTS = ("county_blank", "county_not_in_state", "county_noncanonical_spelling", "zip_not_in_state",
              "latlon_outside_state", "parcel_junk", "owner_name_looks_like_address", "owner_name_equals_mailing",
              "situs_was_owner_mailing", "arv_nonpositive", "arv_over_5m", "arv_over_5x_assessed",
              "arv_under_0.2x_assessed", "arv_over_1000_per_sqft", "arv_under_15_per_sqft", "sale_date_impossible",
              "first_seen_after_last_seen", "last_seen_in_future", "year_built_impossible",
              "upset_deadline_before_sale", "redemption_before_sale", "last_sale_in_future",
              "phone_not_10_digits", "phone_bad_area_or_exchange", "phone_fictional_555", "phone_repeated_digit")


def correctness(cube: Cube) -> dict:
    inv = {k: dict(total=sum(cube.inv[k].values()) if k in cube.inv else 0,
                   by_state=_by_state(cube.inv[k]) if k in cube.inv else {})
           for k in sorted(set(INVARIANTS) | set(cube.inv))}
    # parcel format by county: the shapes that cover 95% of the county's parcels; the rest off-pattern
    shape_out = {}
    for key, sh in cube.shapes.items():
        tot = sum(sh.values())
        acc, keep = 0, []
        for s, n in sh.most_common():
            if acc >= 0.95 * tot:
                break
            keep.append(s)
            acc += n
        off = tot - acc
        shape_out[f"{key[0]}|{key[1]}"] = dict(parcels=tot, shapes=len(sh), top=sh.most_common(3),
                                               off_pattern=off, off_pct=pct(off, tot))
    dup_groups = sum(1 for v in cube.parcels.values() if v > 1)
    dup_rows = sum(v for v in cube.parcels.values() if v > 1)
    shared = [(h, o) for h, o in cube.phone_owner.items() if o[1] >= 3]
    return dict(
        invariants=inv,
        parcel_format=dict(off_pattern_rows=sum(v["off_pattern"] for v in shape_out.values()),
                           worst=sorted(((k, v["off_pattern"], v["off_pct"], v["shapes"]) for k, v in shape_out.items()
                                         if v["off_pattern"]), key=lambda x: -x[1])[:25],
                           by_county=shape_out),
        duplicate_parcels=dict(groups=dup_groups, rows=dup_rows, distinct_parcels=len(cube.parcels)),
        phones=dict(rows_with_phone=sum(cube.phone_rows.values()), distinct_phones=len(cube.phone_rows),
                    phones_shared_by_3plus_owner_names=len(shared),
                    rows_on_those_phones=sum(cube.phone_rows[h] for h, _ in shared),
                    by_source=dict(cube.phone_source.most_common())),
        unknown_county_by_source=[(f"{st}|{s}", n) for (st, s), n in cube.unknown_sources.most_common(15)],
    )


def _by_state(c: Counter) -> dict:
    out: Counter = Counter()
    for (st, _), n in c.items():
        out[st] += n
    return dict(out)


def read_baseline(path: Optional[Path]) -> dict[tuple[str, str], dict]:
    if not path or not Path(path).exists():
        return {}
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            co = (r.get("County") or "").strip()
            out[((r.get("State") or "").upper(), UNKNOWN if co.upper() in ("", UNKNOWN) else canonical_county(co))] = r
    return out


def write_csvs(out_dir: Path, stamp: str, cube: Cube, roll: dict, baseline: dict,
               baseline_label: str = "2026-10-01") -> dict[str, Path]:
    paths = {}
    head = ["State", "County", "Rows"]
    p = out_dir / f"county_signal_coverage_{stamp}.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head + OWNER_COLUMNS)
        for key in roll["counties"]:
            n = cube.rows[key]
            w.writerow([key[0], key[1], n] + [pct(cube.owner[key][c], n) for c in OWNER_COLUMNS])
    paths["same_shape"] = p
    p = out_dir / f"county_signal_coverage_{stamp}_plus_attorney.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head + OWNER_COLUMNS + ATTY_COLUMNS)
        for key in roll["counties"]:
            n = cube.rows[key]
            w.writerow([key[0], key[1], n] + [pct(cube.owner[key][c], n) for c in OWNER_COLUMNS]
                       + [pct(cube.pos[key][c], n) for c in ATTY_COLUMNS])
    paths["plus_attorney"] = p
    if baseline:
        p = out_dir / f"county_signal_coverage_delta_{baseline_label}_to_{stamp}.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["State", "County", f"Rows_{baseline_label}", f"Rows_{stamp}", "Rows_delta"]
                       + [f"{c}_pp" for c in OWNER_COLUMNS])
            keys = list(roll["counties"]) + [k for k in baseline if k not in cube.rows]
            for key in keys:
                b = baseline.get(key, {})
                n = cube.rows.get(key, 0)
                bn = int(float(b.get("Rows") or 0)) if b else 0
                row = [key[0], key[1], bn, n, n - bn]
                for c in OWNER_COLUMNS:
                    now = pct(cube.owner[key][c], n) if n else 0.0
                    then = float(b.get(c) or 0.0) if b else 0.0
                    row.append(round(now - then, 2))
                w.writerow(row)
        paths["delta"] = p
    p = out_dir / f"gap_list_{stamp}.csv"
    cols = ["state", "county", "column", "layer", "kind", "scope", "applicable", "target", "pct",
            "est_rows_affected", "gap_class", "next_action", "source", "built", "ran", "matrix_ref"]
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for g in roll["gaps"]:
            w.writerow([g[c] for c in cols])
    paths["gap_list"] = p
    return paths


def summarize(cube: Cube, roll: dict, baseline: dict, ledger_counts: dict, samples: Optional[dict]) -> dict:
    cells = roll["cells"]
    per_col = {}
    for col, spec in SPECS.items():
        agg = Counter()
        st_agg: dict[str, Counter] = defaultdict(Counter)
        for key in roll["counties"]:
            c = cells[(key[0], key[1], col)]
            for k in ("app", "pos", "chk", "target", "v_dec", "v_any", "v_conf"):
                agg[k] += c[k]
                st_agg[key[0]][k] += c[k]
            if key[1] == UNKNOWN:
                continue
            agg["counties_applicable"] += c["app"] > 0
            agg["counties_source_known"] += c["src"][0] == "free"
            agg["counties_walled"] += c["src"][0] == "walled"
            agg["counties_built"] += c["built"] in ("ran", "code")
            agg["counties_ran"] += c["ran"]
            agg["counties_verified"] += c["v_dec"] > 0
            agg["counties_at_target"] += c["app"] > 0 and c["target"] >= c["app"]
        all_rows = sum(cube.rows.values())
        per_col[col] = dict(kind=spec.kind, scope=spec.scope, family=spec.family, ledger=spec.ledger,
                            doc=spec.doc, ambiguity=spec.ambiguity,
                            pct_rows_10_01_def=pct(sum(cube.owner[k][col] for k in roll["counties"]), all_rows)
                            if col in OWNER_COLUMNS else None,
                            applicable=agg["app"], hits=agg["pos"], checked=agg["chk"], target=agg["target"],
                            target_pct=pct(agg["target"], agg["app"]), hit_pct_of_applicable=pct(agg["pos"], agg["app"]),
                            verified_decisive=agg["v_dec"], verified_confirmed=agg["v_conf"],
                            by_state={s: dict(applicable=v["app"], target_pct=pct(v["target"], v["app"]),
                                              hit_pct=pct(v["pos"], v["app"])) for s, v in st_agg.items()},
                            **{k: agg[k] for k in ("counties_applicable", "counties_source_known", "counties_walled",
                                                   "counties_built", "counties_ran", "counties_verified",
                                                   "counties_at_target")})
    named = {k for k in cube.rows if k[1] != UNKNOWN}
    expected = {(st, c) for st, names in STATE_COUNTIES.items() for c in names}
    gaps = roll["gaps"]
    cls_counts = Counter(re.sub(r" \(.*", "", g["gap_class"]) for g in gaps)
    # the 146 x 82 grid itself: one class per (county, column) cell, fill/check layer (the gap
    # entries above also hold verify-layer entries, so they are not a count of cells)
    cell_counts = Counter(re.sub(r" \(.*", "", c.get("class") or "at target")
                          for (st, co, col), c in roll["cells"].items() if co != UNKNOWN)
    cls_rows = Counter()
    for g in gaps:
        cls_rows[re.sub(r" \(.*", "", g["gap_class"])] += g["est_rows_affected"]
    return dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        board_rows=sum(cube.rows.values()),
        rows_by_state=_by_state(cube.rows),
        counties_on_board=len(named), counties_expected=len(expected),
        counties_missing=sorted(f"{s}|{c}" for s, c in expected - named),
        extra_jurisdictions=sorted(f"{s}|{c}" for s, c in named - expected),
        unknown_county_rows={st: cube.rows.get((st, UNKNOWN), 0) for st in ("NC", "SC")},
        baseline_unknown_rows={st: int(float(baseline.get((st, UNKNOWN), {}).get("Rows") or 0)) for st in ("NC", "SC")}
        if baseline else {},
        columns=per_col,
        gap_class_counts=dict(cls_counts), gap_class_rows=dict(cls_rows), cell_class_counts=dict(cell_counts),
        ledger_entries_by_county=ledger_counts,
        median_hit_rate_where_ran={f"{c}|{s}": round(v, 5) for (c, s), v in roll["median_rates"].items()},
        top_sources=cube.slug_rows.most_common(30),
        source_samples=samples or {},
    )


def is_checkpoint(path: Path) -> bool:
    """A checkpoint directory (data/checkpoint: board.json.gz + manifest.json), or its board.json.gz."""
    p = Path(path)
    if p.is_file() and p.name == "board.json.gz":
        p = p.parent
    return p.is_dir() and (p / "board.json.gz").is_file() and (p / "manifest.json").is_file()


def board_rows(board: Path):
    """The rows to measure, one at a time. A published board (docs/listings.json.gz or a docs/
    directory) streams with the comps sidecar merged; a CHECKPOINT directory streams the rows it
    would publish, through board_selfcheck's reader (validated to a Listing, web_artifact._to_dict),
    exactly as compare_boards.py --candidate and audit_suite.py --checkpoint read it."""
    from foreclosure_scraper.board_stream import iter_board_rows_with_detail
    p = Path(board)
    if is_checkpoint(p):
        sd = str(Path(__file__).resolve().parent)
        if sd not in sys.path:
            sys.path.insert(0, sd)
        import board_selfcheck as BS
        yield from BS._checkpoint_rows(p if p.is_dir() else p.parent)
        return
    if p.is_dir():
        p = p / "listings.json.gz"
    yield from iter_board_rows_with_detail(p, keys=("comps",))


def run(board: Path, limit: Optional[int], use_verifiers: bool, today: date) -> Cube:
    idx, _ = load_ledger_index()
    vers = []
    if use_verifiers:
        from foreclosure_scraper.verification.registry import discover
        vers = discover()
    cube = Cube(today=today, ledger_idx=idx, verifiers=vers)
    t0 = time.time()
    for rec in board_rows(board):
        cube.add(rec)
        if cube.n % 50000 == 0:
            print(f"  ...{cube.n:,} rows ({time.time() - t0:.0f}s)", file=sys.stderr)
        if limit and cube.n >= limit:
            break
    print(f"  pass done: {cube.n:,} rows in {time.time() - t0:.0f}s", file=sys.stderr)
    return cube


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"),
                    help="docs/listings.json.gz, a board directory, or a checkpoint directory "
                         "(board.json.gz + manifest.json, read as compare_boards.py reads it)")
    ap.add_argument("--out-dir", default=str(REPO / "docs" / "gap_matrix"))
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--baseline", default=str(REPO / "docs" / "gap_matrix" / "county_signal_coverage_2026-10-01_baseline.csv"))
    ap.add_argument("--baseline-label", default="2026-10-01",
                    help="the baseline's date, for the delta file's name and header")
    ap.add_argument("--matrix", default=str(REPO / "docs" / "county_records" / "county_records_matrix.json"))
    ap.add_argument("--desktop", default="", help="also copy the coverage CSVs here")
    ap.add_argument("--samples", default="", help="JSON of source-page sample results (counts only) to embed")
    ap.add_argument("--screens", default=str(REPO / "docs" / "screen_ledger.json"),
                    help="the screen ledger of the run that wrote the board ('' = none); "
                         "ignored when older than screen_ledger.MAX_AGE_DAYS")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-verifiers", action="store_true")
    a = ap.parse_args(argv)
    stamp = a.date
    today = date.fromisoformat(stamp)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cube = run(Path(a.board), a.limit or None, not a.no_verifiers, today)
    matrix = load_matrix(Path(a.matrix))
    code = built_in_code()
    from foreclosure_scraper import screen_ledger as SL
    screens = SL.load(a.screens) if a.screens else {}
    if screens and not SL.fresh(screens, today):
        print(f"  screen ledger {a.screens} is stale (run_at {screens.get('run_at')}): ignored", file=sys.stderr)
        screens = {}
    roll = roll_up(cube, matrix, code, screens)
    baseline = read_baseline(Path(a.baseline)) if a.baseline else {}
    _, ledger_counts = load_ledger_index()
    samples = json.loads(Path(a.samples).read_text()) if a.samples and Path(a.samples).exists() else None
    summary = summarize(cube, roll, baseline, ledger_counts, samples)
    corr = correctness(cube)
    paths = write_csvs(out, stamp, cube, roll, baseline, a.baseline_label)
    cell_head = ["state", "county", "column", "applicable", "hits", "checked", "target", "target_pct", "ran",
                 "built", "source_status", "source_wall", "source", "verified_any", "verified_decisive",
                 "verified_confirmed", "verifier_covers_hits", "screened", "gap_class"]
    cells = [[st, co, col, c["app"], c["pos"], c["chk"], c["target"], pct(c["target"], c["app"]), c["ran"],
              c["built"], c["src"][0], c["src"][1], c["src"][2], c["v_any"], c["v_dec"], c["v_conf"],
              c["v_applies"], c.get("screened", False), c.get("class")] for (st, co, col), c in roll["cells"].items()]
    gap_head = list(roll["gaps"][0].keys()) if roll["gaps"] else []
    doc = dict(schema="gap-matrix-v1", date=stamp, board=str(Path(a.board).name), summary=summary,
               baseline_label=a.baseline_label,
               board_kind=("the reconciled pre-publish checkpoint (data/checkpoint)" if is_checkpoint(Path(a.board))
                           else "the published board"),
               screen_ledger=dict(run_at=screens.get("run_at"), cells=screens.get("cells_screened", 0)) if screens else None,
               scopes=SCOPES, correctness=corr,
               rows_by_county={f"{k[0]}|{k[1]}": n for k, n in sorted(cube.rows.items())},
               cells=dict(header=cell_head, rows=cells),
               gaps=dict(header=gap_head, rows=[[g[h] for h in gap_head] for g in roll["gaps"]]),
               files={k: p.name for k, p in paths.items()})
    jp = out / f"gap_matrix_{stamp}.json"
    jp.write_text(json.dumps(doc, separators=(",", ":"), default=str))
    (out / "README.md").write_text(render_readme(doc, roll, cube))
    if a.desktop:
        d = Path(a.desktop).expanduser()
        for k in ("same_shape", "plus_attorney", "delta"):
            if k in paths:
                (d / paths[k].name).write_bytes(paths[k].read_bytes())
    print(json.dumps(dict(rows=summary["board_rows"], by_state=summary["rows_by_state"],
                          counties=summary["counties_on_board"], missing=summary["counties_missing"],
                          extra=summary["extra_jurisdictions"], unknown=summary["unknown_county_rows"],
                          gaps=len(roll["gaps"]), classes=summary["gap_class_counts"],
                          files=[p.name for p in paths.values()] + [jp.name, "README.md"])))
    return 0


# =============================================================================================
# README
# =============================================================================================

def _tbl(head: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def render_readme(doc: dict, roll: dict, cube: Cube) -> str:
    s = doc["summary"]
    c = doc["correctness"]
    cols = s["columns"]
    L: list[str] = []
    L.append(f"# Gap matrix {doc['date']}: columns x counties x check depth\n")
    L.append(f"Generated by `scripts/gap_matrix.py` from {doc.get('board_kind') or 'the published board'} (one read-only pass; "
             "counts only, no names, phones or private addresses). Data: "
             f"`gap_matrix_{doc['date']}.json`; CSVs: " + ", ".join(f"`{v}`" for v in doc["files"].values()) + ".\n")
    L.append("## Headline\n")
    L.append(f"- Board: **{s['board_rows']:,} rows** ({', '.join(f'{k} {v:,}' for k, v in s['rows_by_state'].items())}).")
    L.append(f"- Counties: {s['counties_on_board']} of {s['counties_expected']} on the board; missing: "
             f"{', '.join(s['counties_missing']) or 'none'}; extra jurisdictions: {', '.join(s['extra_jurisdictions']) or 'none'}.")
    bu = s.get("baseline_unknown_rows") or {}
    L.append("- Rows with no county (UNKNOWN), a gap in themselves: " + ", ".join(
        f"{st} {n:,} ({doc.get('baseline_label') or '10/1'}: {bu.get(st, 0):,})"
        for st, n in s["unknown_county_rows"].items()) + ".")
    L.append(f"- Columns: the owner's **73** from county_signal_coverage_FINAL.csv (2026-10-01) plus **9** attorney "
             f"columns (`atty_*`) = {len(ALL_COLUMNS)}.")
    L.append("- Gap cells by class (count / estimated rows affected; a row counts once per column it misses): " + "; ".join(
        f"{k} {v:,} / {s['gap_class_rows'].get(k, 0):,}" for k, v in sorted(s["gap_class_counts"].items())) + ".")
    cc = s.get("cell_class_counts") or {}
    L.append(f"- The grid ({sum(cc.values()):,} cells = named counties x {len(ALL_COLUMNS)} columns, fill/check layer; "
             "the gap entries above add verification-layer entries, so they are not cells): " + "; ".join(
                 f"{k} {v:,}" for k, v in sorted(cc.items())) + ".")
    sl = doc.get("screen_ledger")
    L.append("- Screen ledger ('screened, none found', `docs/screen_ledger.json`): " + (
        f"run of {sl.get('run_at')}, {sl.get('cells', 0):,} (column, county) screens." if sl else
        "none for this board (written beside run_health.json from the next run on).") + "\n")
    L.append("Two views. **Fill** (the 10/1 numbers): the share of a county's rows that carry a value or a hit. "
             "**Check depth**: for each column and county, is it applicable, is a source known, is it built, did "
             "it run, what share of applicable rows were checked, and what share of hits carry a verdict. A signal "
             "column is complete when every applicable row was screened, not when every row is a hit.\n")
    L.append("Scopes: " + "; ".join(f"**{k}** = {v}" for k, v in SCOPES.items()) + ".\n")
    # (a) fill by state
    L.append("## (a) Fill and check rate per column, by state\n")
    L.append("`10/1 def %` = share of ALL rows (the 10/1 file's definition, comparable to it). `target %` = share of "
             "APPLICABLE rows that are filled (field) or checked (signal). `hits %` = hits among applicable rows.\n")
    rows = []
    for col in ALL_COLUMNS:
        v = cols[col]
        bs = v["by_state"]
        rows.append([f"`{col}`", v["kind"], v["scope"],
                     "" if v["pct_rows_10_01_def"] is None else v["pct_rows_10_01_def"],
                     f"{v['applicable']:,}", v["target_pct"], bs.get("NC", {}).get("target_pct", ""),
                     bs.get("SC", {}).get("target_pct", ""), v["hit_pct_of_applicable"],
                     f"{v['counties_ran']}/{v['counties_applicable']}", v["counties_source_known"], v["counties_walled"],
                     v["verified_decisive"]])
    L.append(_tbl(["column", "kind", "scope", "10/1 def %", "applicable", "target %", "NC target %", "SC target %",
                   "hits %", "counties ran/applicable", "counties source free", "counties walled",
                   "hits verified"], rows))
    # 25 worst cells
    L.append("\n### The 25 worst fill cells (field columns; lowest fill %, then most rows; counties with >= 200 applicable rows)\n")
    worst = [(k, v) for k, v in roll["cells"].items()
             if k[1] != UNKNOWN and v["app"] >= 200 and SPECS[k[2]].kind == "field"]
    worst.sort(key=lambda kv: (pct(kv[1]["target"], kv[1]["app"]), -kv[1]["app"]))
    L.append(_tbl(["county", "column", "applicable", "target %", "ran", "built", "source", "class"],
                  [[f"{k[1]} {k[0]}", f"`{k[2]}`", f"{v['app']:,}", pct(v["target"], v["app"]), v["ran"], v["built"],
                    (v["src"][0] + (f" ({v['src'][1]})" if v["src"][1] else "")), v.get("class") or ""]
                   for k, v in worst[:25]]))
    # (b) check x county summary
    L.append("\n## (b) Check depth per column (counties)\n")
    L.append("Per column, how many of the 146 counties: the check applies, a free source is known, the source is "
             "walled, it is built (ran, or code names the county, or statewide), it ran (board evidence), at least one "
             "hit is verified, and the county is at 100% of target. Per-county cells: `cells` in the JSON.\n")
    L.append(_tbl(["column", "applicable", "source free", "walled", "built", "ran", "verified", "at 100%"],
                  [[f"`{col}`", cols[col]["counties_applicable"], cols[col]["counties_source_known"],
                    cols[col]["counties_walled"], cols[col]["counties_built"], cols[col]["counties_ran"],
                    cols[col]["counties_verified"], cols[col]["counties_at_target"]] for col in ALL_COLUMNS]))
    # (c) gap list
    gaps = roll["gaps"]
    L.append(f"\n## (c) Gap list ({len(gaps):,} cells under 100%; full list `gap_list_{doc['date']}.csv`)\n")
    L.append("Classes: `sourced-not-built` (a free source is known, nothing built here), `built-but-low-yield` "
             "(it runs or the code covers the county, but not every applicable row is filled/checked), "
             "`walled (...)` (the only source needs a CAPTCHA, login, payment or breaks terms: a human lane), "
             "`no source known`, `not applicable` (no applicable rows). Layer `verify` = hit rows without a "
             "decisive verdict. Estimated rows for a feed that never ran = the state's median hit rate where it "
             "ran x the county's rows.\n")
    L.append("### By column (gap cells, rows affected)\n")
    by_col: dict[str, Counter] = defaultdict(Counter)
    for g in gaps:
        by_col[(g["column"], g["layer"])][re.sub(r" \(.*", "", g["gap_class"])] += g["est_rows_affected"]
    rr = []
    for (col, layer), cnt in sorted(by_col.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(cnt.values())
        if tot == 0:
            continue
        rr.append([f"`{col}`", layer, f"{tot:,}"] + [f"{cnt.get(k, 0):,}" for k in
                                                     ("sourced-not-built", "built-but-low-yield", "walled",
                                                      "no source known")])
    L.append(_tbl(["column", "layer", "rows affected", "sourced-not-built", "built-but-low-yield", "walled",
                   "no source known"], rr[:60]))
    L.append("\n### The 60 biggest cells\n")
    L.append(_tbl(["county", "column", "layer", "applicable", "target %", "rows", "class", "next action"],
                  [[f"{g['county']} {g['state']}", f"`{g['column']}`", g["layer"], f"{g['applicable']:,}", g["pct"],
                    f"{g['est_rows_affected']:,}", g["gap_class"], g["next_action"].replace("|", "/")]
                   for g in gaps if g["gap_class"] != "not applicable"][:60]))
    # (d) correctness
    L.append("\n## (d) Data correctness (invariants on the board, counts)\n")
    inv = c["invariants"]
    L.append(_tbl(["invariant", "rows", "NC", "SC"],
                  [[k, f"{v['total']:,}", f"{v['by_state'].get('NC', 0):,}", f"{v['by_state'].get('SC', 0):,}"]
                   for k, v in sorted(inv.items(), key=lambda kv: -kv[1]["total"])]))
    pf = c["parcel_format"]
    dp = c["duplicate_parcels"]
    ph = c["phones"]
    L.append(f"\n- Parcel id format: {pf['off_pattern_rows']:,} rows fall outside the shapes that cover 95% of their "
             f"county's parcels. Worst: " + "; ".join(f"{k} {n:,} ({p}%, {sh} shapes)" for k, n, p, sh in pf["worst"][:10]) + ".")
    L.append(f"- Duplicate parcels (same state + county + normalized parcel on more than one row): {dp['groups']:,} "
             f"parcels on {dp['rows']:,} rows (of {dp['distinct_parcels']:,} distinct parcels).")
    L.append(f"- Phones: {ph['rows_with_phone']:,} rows, {ph['distinct_phones']:,} distinct numbers; "
             f"{ph['phones_shared_by_3plus_owner_names']:,} numbers sit on 3+ different owner names "
             f"({ph['rows_on_those_phones']:,} rows): likely an agent's, attorney's or office number, not the owner's. "
             f"By source: " + ", ".join(f"{k} {v:,}" for k, v in ph["by_source"].items()) + ".")
    L.append("- Rows with no county, by source (top): " + ", ".join(f"{k} {n:,}" for k, n in c["unknown_county_by_source"]) + ".")
    smp = s.get("source_samples") or {}
    if smp:
        L.append("\n### Sampled rows vs the live source page\n")
        L.append(smp.get("method", ""))
        L.append("")
        L.append(_tbl(["source", "rows sampled", "record opened", "walled", "field", "matched", "differs",
                       "not on page", "board empty"],
                      [[r["source"], r["sampled"], r["opened"], r["walled"], r["field"], r["matched"], r["differs"],
                        r["not_shown"], r.get("board_empty", 0)] for r in smp.get("rows", [])]))
        L.append("")
        for f in smp.get("findings", []):
            L.append(f"- {f}")
    # column definitions
    L.append("\n## How each column is computed\n")
    L.append("The 73 owner columns use the 2026-10-01 script's definitions exactly (recovered from that session), so "
             "`county_signal_coverage_" + doc["date"] + ".csv` compares with `county_signal_coverage_FINAL.csv` "
             "column for column. Differences in method: counties are grouped by canonical spelling (the board now holds "
             "lower-case county variants that the 10/1 grouping would have split into extra rows), and raw.comps comes "
             "from the lazy-detail sidecar (the 10/1 reader merged the same sidecar). Where the 10/1 definition is "
             "ambiguous it is said in the last column.\n")
    L.append(_tbl(["column", "computed as", "10/1 ambiguity"],
                  [[f"`{col}`", SPECS[col].doc.replace("|", "/"), SPECS[col].ambiguity.replace("|", "/")]
                   for col in ALL_COLUMNS]))
    L.append("\nGeneral 10/1 ambiguities: every percentage divides by ALL rows in the county, so a column that only "
             "applies to some rows (beds/baths on land, phone on government parcels, divorce on companies) can never "
             "reach 100%; listing-type columns are one-per-row categories, not checks; presence-only columns count "
             "any block a producer wrote, including low-confidence matches. The check-depth view fixes the "
             "denominator (applicable rows) and separates 'screened, nothing found' from 'never screened'.\n")
    L.append("## What this does not measure\n")
    L.append("- Whether a negative was checked, for roster-scope signals with no per-row negative record (jail "
             "rosters, condemned/vacant registries, probate, obituaries, heir scans): the county counts as screened "
             "when the roster produced at least one hit there; a roster that ran and found nothing is invisible.\n"
             "- 'Built in code' for a county is a grep of the producer files for the county's name; a module that "
             "loops over a config list elsewhere is missed, and names shared by both states (Union, Cherokee, Lee, "
             "Beaufort) count for both.\n"
             "- Sources outside the county records matrix (jail rosters, code enforcement, obituaries, damage layers) "
             "are 'unknown' unless a statewide source or a built producer exists.\n"
             "- Field correctness against the source is sampled (above), not measured board-wide.\n")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
