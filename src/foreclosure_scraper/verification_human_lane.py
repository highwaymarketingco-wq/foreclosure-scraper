"""Human-assisted, per-lead verification lane for the two real walls named in
``docs/validation_2026-10-02/VERIFICATION_PIPELINE_SPEC.md`` section 4 ("The
honest gap"): **NC eCourts Smart Search** (AWS-WAF image-grid CAPTCHA) and
**NC Secretary of State business search** (a separate bot-check). That spec
proposes two non-exclusive options for a wall no verifier in this codebase can
close on its own: (1) label it ``verdict: "wall"``, never fake it, and (2) "A
human-assisted on-demand lane ... a tool that queues the eCourts check and
pauses for a human to clear the CAPTCHA once ... not a bulk/background thing,
a per-lead button for when it actually matters." THIS MODULE IS OPTION 2's
CORE LOGIC. The operator-facing CLI is ``scripts/verify_lead_human_assisted.py``.
See ``docs/HANDOFF.md`` (search "verify_lead_human_assisted") for the
narrative write-up of where this fits and how to invoke it.

WHERE THIS LIVES IN THE PIPELINE
---------------------------------
This is scoped, on purpose, to the two highest-priority verifier types in the
spec's own priority table: ``probate``/``heir_estate`` (the "Boone St" 9th-heir
pattern — a decedent's estate case can name more heirs than the board's slim
fields show) and ``lis_pendens``/``divorce`` (the underlying NC eCourts case
detail a lis-pendens or divorce judgment points at). It is explicitly NOT a
bulk sweep: every other verifier the spec describes (``tax_lien``,
``bankruptcy_stay``, ``code_enforcement``, ...) either has no CAPTCHA at all or
is out of scope here. It is also explicitly NOT wired into ``main.py`` or any
scheduled job — the spec is equally explicit that a CAPTCHA step must never be
a bulk/background thing.

HARD RULE -- NON-NEGOTIABLE
----------------------------
Nothing in this module, or in its CLI, ever attempts to solve, bypass, defeat,
or auto-complete a CAPTCHA / WAF / bot-check challenge. Every function here
either:
  (a) reads the ONE board row an operator named (``find_lead``, via
      ``board_stream.iter_board_rows()`` -- read-only, never ``load_board()``
      on this 8 GB Mac),
  (b) works out exactly which NC eCourts Smart Search and/or NC SOS lookup it
      needs, with what pre-filled search criteria (``build_check_specs``) --
      pure, no I/O, fully unit-testable,
  (c) opens that site's plain search URL in the OPERATOR'S OWN browser
      (``open_for_human`` -> ``webbrowser.open``) -- a bare navigation. Nothing
      is typed into the page, nothing is clicked, nothing is submitted, by
      this tool. The CAPTCHA, the search criteria, and the save-page step are
      100% done by the human, by hand, in their own browser session -- the
      exact same "compliant pattern" this codebase already uses for every
      other walled source (``docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md``
      section 5: "the OPERATOR ... opens the site, runs the search, saves the
      page ... an offline parser ingests it. The robot never logs in or
      defeats the wall."), or
  (d) parses a page the human already saved to disk (``parse_saved_ecourts_page``,
      ``parse_saved_sos_page``) and turns it into a ``raw.verification`` record.

Before a human has done (c)/saved anything, the only record this module will
ever produce is ``verdict: "wall"`` (see ``pending_wall_record``) -- an
unexecuted check is labeled honestly, never silently treated as confirmed.

REUSE, NOT REBUILD (per the spec's own instruction)
-----------------------------------------------------
- NC eCourts page parsing reuses ``scripts/parse_nc_ecourts_export.py``'s
  ``parse_nc_ecourts_html`` verbatim -- the SAME parser
  ``scripts/ingest_saved.sh`` already runs against every other operator-saved
  NC eCourts page in this codebase. Not re-derived here.
- NC SOS profile parsing reuses ``enrichment_sos_agent.py``'s ``_parse_profile``
  verbatim -- the SAME parser the live Scrapling-stealth lane already uses,
  just pointed at a saved page's text instead of a live-rendered one.
- Heir/decedent liveness reuses ``enrichment_nc_voter_lookup.nc_voter_lookup``
  -- the exact free, no-CAPTCHA check
  ``docs/validation_2026-10-03/scripts/validate_probate_heir_buncombe.py``'s
  ``heir_voter_check`` already proved live. A name a saved eCourts page reveals
  that the board did not already know about (the Boone-St-9th-heir pattern) is
  run through this automatically -- this IS automatable; only the eCourts page
  itself needs the human.

SCOPE -- NC ONLY, TWO SIGNAL FAMILIES ONLY
---------------------------------------------
``build_check_specs`` refuses (returns an explanatory error, not a guess) for
any row whose ``state`` is not ``"NC"`` -- NC eCourts and NC SOS cannot answer
anything about an SC case -- and for any ``listing_type`` outside the
probate/heir_estate/lis_pendens/divorce families this pass is scoped to.

REACHES THE BOARD THROUGH THE VERIFICATION LEDGER (2026-10-05, docs/HANDOFF.md item 66)
--------------------------------------------------------------------------------------
``record_to_ledger(row, record)`` merges each record this lane produces (the ``wall``
placeholder at step 1, the real verdict at step 2) into the same per-signal ledger the
automated verifiers use, ``docs/handoff/verification/<signal>.json``
(``verification/ledger.py``), keyed by ``verification.core.row_key(row)``. The CLI writes it
and pushes only those files (``ledger.publish_ledgers``; ``HANDOFF_PUSH=0`` or ``--no-push``
skips git); the VM's next run attaches it as ``raw['verification']`` before scoring
(``verification/apply.py``). Nothing here writes the board itself. The ledger's merge rule
keeps a placeholder ``wall`` from ever displacing a real verdict on the same row.
``build_patch_preview`` is kept for inspection only.
"""
from __future__ import annotations

import re
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup

from . import board_stream
from .name_normalize import is_entity, primary_party as _gis_primary_party
from .scrapers.counties_nc.nc_ecourts_divorce import DIVORCE_CATEGORY_LABELS
from .scrapers.counties_nc.nc_ecourts_estates import (
    ESTATE_CATEGORY_LABELS,
    SEARCH_URL as _ECOURTS_SEARCH_URL,
)
from .enrichment_nc_sos import _SEARCH_PAGE_URL as _SOS_SEARCH_URL
from .enrichment_sos_agent import _parse_profile as _parse_sos_profile

_REPO = Path(__file__).resolve().parent.parent.parent

VERIFIER_VERSION = "v1"

#: The schema's full verdict vocabulary (VERIFICATION_PIPELINE_SPEC.md section 1).
#: "stale" is deliberately never PRODUCED by this module -- it describes a
#: confirmed/refuted record that has aged past its TTL, which is a later
#: freshness-pass concern (same shape as signal_freshness.is_stale()), not
#: something this point-in-time human check computes itself.
VALID_VERDICTS = ("confirmed", "refuted", "stale", "unconfirmed", "wall")

#: How long a human-cleared verdict stays good in the verification ledger (no verifier module
#: exists for these signals, so the ledger entry carries its own TTL). A court case or an
#: entity's status changes slowly; a lis pendens moves fastest.
LEDGER_TTL_DAYS = {"probate": 365, "heir_estate": 365, "divorce": 180, "lis_pendens": 90,
                   "sos_entity": 180}
#: Scorer signal names a refuted/stale verdict of each signal would remove. This lane never
#: emits refuted/stale for an eCourts check today (see verify_ecourts_from_saved_page), and
#: an SOS entity's status governs no scorer signal, so these only take effect if that changes.
LEDGER_GOVERNS = {"probate": ("probate", "probate_notice", "estate_lead"),
                  "heir_estate": ("probate", "probate_notice", "estate_lead"),
                  "divorce": ("divorce", "divorce_notice"),
                  "lis_pendens": ("lis_pendens",),
                  "sos_entity": ()}
LEDGER_VERIFIER = "human_lane"

#: listing_type -> which of the two scoped signal families it belongs to.
_PROBATE_LISTING_TYPES = {"probate_notice", "estate_lead"}
_DIVORCE_LISTING_TYPES = {"divorce_notice"}
_LIS_PENDENS_LISTING_TYPES = {"lis_pendens", "foreclosure_sale", "sheriff_sale", "auction"}

#: Decedent/heir-estate caption noise -- adapted from
#: docs/validation_2026-10-03/scripts/validate_probate_heir_buncombe.py's
#: `_HEIR_SUFFIX_RE` (that script is a one-off audit tool, not an importable
#: package, so the regex is reproduced here rather than sys.path-hacked in).
_HEIR_SUFFIX_RE = re.compile(
    r"\(HEIRS\)|\bHEIRS?\s*OF\b|\bHEIRS?\b|\bESTATE\s+OF\b|\bESTATE\b", re.I)


@dataclass(frozen=True)
class ECourtsCheckSpec:
    """Exactly which NC eCourts Smart Search lookup a lead needs, and with
    what pre-filled criteria -- the output of `build_check_specs`, consumed by
    `pending_wall_record` / `parse_saved_ecourts_page` / the CLI."""

    signal: str  # "probate" | "heir_estate" | "lis_pendens" | "divorce"
    county: str
    case_category_labels: tuple[str, ...]
    category_name: str
    search_name: Optional[str]
    case_number: Optional[str]
    portal_url: str
    instructions: tuple[str, ...]


@dataclass(frozen=True)
class SOSCheckSpec:
    """An NC Secretary of State business-entity lookup -- only built when the
    lead's primary party reads as a business (`name_normalize.is_entity`),
    since most probate/lis-pendens/divorce leads are individuals and forcing
    an SOS check on every one of them would be dishonest busywork."""

    entity_name: str
    portal_url: str
    instructions: tuple[str, ...]


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _digits(s: Optional[str]) -> str:
    return re.sub(r"\D", "", s or "")


# --------------------------------------------------------------------------- #
# (a) find the one lead the operator named
# --------------------------------------------------------------------------- #
def _match_row(
    row: dict,
    *,
    source_url: Optional[str] = None,
    parcel_id: Optional[str] = None,
    case_number: Optional[str] = None,
    street_address: Optional[str] = None,
    county: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> bool:
    """Pure predicate -- does `row` match every identifier the caller gave?
    Split out of `find_lead` so the matching logic is testable without
    touching the board file at all."""
    if source_url and _norm(row.get("source_url")) != _norm(source_url):
        return False
    if parcel_id and _digits(row.get("parcel_id")) != _digits(parcel_id):
        return False
    if case_number and _norm(row.get("case_number")) != _norm(case_number):
        return False
    if street_address and _norm(row.get("street_address")) != _norm(street_address):
        return False
    if county and _norm(row.get("county")) != _norm(county):
        return False
    if zip_code and (row.get("zip_code") or "")[:5] != zip_code[:5]:
        return False
    return True


def find_lead(
    *,
    docs_dir: Path | str = "docs",
    source_url: Optional[str] = None,
    parcel_id: Optional[str] = None,
    case_number: Optional[str] = None,
    street_address: Optional[str] = None,
    county: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> Optional[dict]:
    """Stream the published board (`board_stream.iter_board_rows()`, read-only
    -- the slim view, no lazy-detail sidecar, ~295 MB peak per that module's
    own docstring) looking for the ONE row the operator named, then stop. This
    is deliberately a linear scan with no index: it is a per-lead, on-demand
    tool invoked a handful of times a day, not a bulk pass, so the ~7s it
    takes to walk the whole board (board_stream.py's own measured figure) is
    an acceptable, honest cost -- not something worth building an index for.

    At least one identifier must be given, or this raises ValueError: a
    per-lead tool with no identifier at all would otherwise silently return
    the FIRST row on the board, which is a worse failure than refusing."""
    if not any([source_url, parcel_id, case_number, street_address]):
        raise ValueError(
            "give at least one of source_url / parcel_id / case_number / "
            "street_address to identify the lead"
        )
    path = Path(docs_dir) / "listings.json.gz"
    for row in board_stream.iter_board_rows(path):
        if _match_row(
            row, source_url=source_url, parcel_id=parcel_id,
            case_number=case_number, street_address=street_address,
            county=county, zip_code=zip_code,
        ):
            return row
    return None


# --------------------------------------------------------------------------- #
# (b) work out exactly which check(s) this lead needs
# --------------------------------------------------------------------------- #
def classify_signal(row: dict) -> Optional[str]:
    """Which of the two scoped signal families (if any) `row` belongs to,
    read off the SLIM `listing_type` field alone -- the one field
    `board_stream.iter_board_rows()` always carries, so this never depends on
    the lazy-detail sidecar this tool deliberately does not load."""
    lt = row.get("listing_type")
    if lt in _PROBATE_LISTING_TYPES:
        return "probate"
    if lt in _DIVORCE_LISTING_TYPES:
        return "divorce"
    if lt in _LIS_PENDENS_LISTING_TYPES:
        return "lis_pendens"
    return None


def _clean_decedent_name(name: str) -> str:
    stripped = _HEIR_SUFFIX_RE.sub(" ", name)
    stripped = re.sub(r"\s+", " ", stripped).strip(" ,;")
    return _gis_primary_party(stripped) or stripped.strip()


def _primary_person_name(row: dict, signal: str) -> Optional[str]:
    """The one party name this check should search NC eCourts for. Field
    preference is signal-dependent and grounded in a live read of the real
    board (2026-10-04): probate/heir_estate rows carry the decedent in
    `owner_name` (GIS record owner), e.g. 'MARTHA MCDONALD (HEIRS)' --
    `defendant` on those rows is sometimes the personal representative
    instead, so it is only a fallback. lis_pendens/divorce rows carry the
    sued/filing-against party in `defendant` first, matching
    `validate_lis_pendens_buncombe.py`'s own `primary_party()` field order."""
    order = (
        ("owner_name", "defendant", "plaintiff")
        if signal in ("probate", "heir_estate")
        else ("defendant", "owner_name", "plaintiff")
    )
    for field_name in order:
        v = row.get(field_name)
        if not v:
            continue
        first = v.split(";")[0].strip()
        if not first:
            continue
        if signal in ("probate", "heir_estate"):
            first = _clean_decedent_name(first)
        return first or None
    return None


def _known_person_names(row: dict) -> set[str]:
    """Every person name the SLIM board row already carries, so a saved
    eCourts page can be checked for a name it did NOT already know about (the
    Boone-St-9th-heir pattern) instead of just re-confirming what is already
    on file. Deliberately reads only owner_name/defendant/plaintiff -- the
    lazy-detail sidecar (raw.heir_estate.heirs etc.) is not loaded by
    `find_lead`, so it cannot be consulted here either; a name already listed
    there but not in these three fields would be reported as "new" again,
    which is the SAFE direction to be wrong in (more human attention on a
    real name, never less)."""
    names: set[str] = set()
    for field_name in ("owner_name", "defendant", "plaintiff"):
        v = row.get(field_name)
        if not v:
            continue
        for part in re.split(r"[;]", v):
            p = re.sub(r"\s+", " ", part).strip(" ,;")
            if p:
                names.add(p.upper())
    return names


def build_check_specs(
    row: dict,
) -> tuple[Optional[ECourtsCheckSpec], Optional[SOSCheckSpec], Optional[str]]:
    """Pure, no I/O. Returns (ecourts_spec, sos_spec, scope_error) -- exactly
    one of (specs) / (scope_error) is populated. `sos_spec` is None whenever
    the primary party does not read as a business; that is the normal,
    expected case, not a failure."""
    state = (row.get("state") or "").strip().upper()
    if state != "NC":
        return None, None, (
            f"row state is {state or '(none)'}, not NC -- this lane only "
            "covers NC eCourts Smart Search / NC Secretary of State; a "
            "non-NC row is out of scope for it, not a bug."
        )

    signal = classify_signal(row)
    if signal is None:
        return None, None, (
            f"listing_type={row.get('listing_type')!r} is not one of the "
            "probate/heir_estate/lis_pendens/divorce families this lane is "
            "scoped to (per VERIFICATION_PIPELINE_SPEC.md's priority table)."
        )

    county = (row.get("county") or "").strip()
    if not county:
        return None, None, "row has no county -- cannot scope the eCourts Smart Search county search."

    name = _primary_person_name(row, signal)
    case_number = row.get("case_number")
    case_number = str(case_number).strip() if case_number else None

    category_labels: tuple[str, ...]
    category_name: str
    if signal in ("probate", "heir_estate"):
        category_labels, category_name = tuple(ESTATE_CATEGORY_LABELS), "Estate / Special Proceedings"
    elif signal == "divorce":
        category_labels, category_name = tuple(DIVORCE_CATEGORY_LABELS), "Family / Civil Action"
    else:
        category_labels, category_name = ("Civil", "Civil Action"), "Civil"

    instructions = [
        f"1. Open {_ECOURTS_SEARCH_URL} (opens automatically in your browser).",
        "2. If a human-verification / CAPTCHA challenge is shown, solve it "
        "YOURSELF -- this tool will never do this step for you.",
        f"3. Set Case Category to '{category_name}' "
        f"(Tyler's exact label may vary -- any of {', '.join(category_labels)} is right).",
    ]
    if case_number:
        instructions.append(
            f"4. Search by exact case number: {case_number!r} -- the most "
            "precise option; skips name-ambiguity entirely."
        )
    if name:
        instructions.append(f"4b. Or search by name: {name!r} in {county} County, NC.")
    if not case_number and not name:
        instructions.append(
            "4. WARNING: this row has neither a case number nor a usable "
            "party name -- there is nothing to search on. Consider whether "
            "this lead is even checkable before continuing."
        )
    instructions.append(
        "5. Once the MATCHING CASE's full detail page has finished loading "
        "(click into the case first -- a hitlist row alone will not show a "
        "full party/heir list), save it: Ctrl+S / File > Save Page As > "
        "'Webpage, HTML only'. Pass that saved file to this tool's "
        "--saved-ecourts-page argument to finish the check."
    )

    ecourts_spec = ECourtsCheckSpec(
        signal=signal,
        county=county,
        case_category_labels=tuple(category_labels),
        category_name=category_name,
        search_name=name,
        case_number=case_number,
        portal_url=_ECOURTS_SEARCH_URL,
        instructions=tuple(instructions),
    )

    sos_spec = None
    if name and is_entity(name):
        sos_instructions = (
            f"1. Open {_SOS_SEARCH_URL} (opens automatically in your browser).",
            "2. If a bot-check challenge is shown, solve it YOURSELF -- this "
            "tool will never do this step for you.",
            f"3. Search Business Registration for: {name!r}",
            "4. Once the business profile page has loaded, save it: Ctrl+S / "
            "File > Save Page As > 'Webpage, HTML only'. Pass that saved "
            "file to this tool's --saved-sos-page argument to finish the "
            "check.",
        )
        sos_spec = SOSCheckSpec(
            entity_name=name, portal_url=_SOS_SEARCH_URL, instructions=sos_instructions,
        )

    return ecourts_spec, sos_spec, None


# --------------------------------------------------------------------------- #
# (c) open the real search for a human -- navigation only, nothing else
# --------------------------------------------------------------------------- #
def open_for_human(url: str) -> bool:
    """Open `url` in the OPERATOR'S OWN default browser. A plain navigation --
    nothing is typed, clicked, or submitted by this tool; the CAPTCHA, the
    search criteria, and the save-page step are entirely the human's. Returns
    False (callers should fall back to printing the URL) on a headless box
    with no browser to open -- never raises."""
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# raw.verification record construction (schema per VERIFICATION_PIPELINE_SPEC.md)
# --------------------------------------------------------------------------- #
def make_verification_record(
    *, signal: str, verdict: str, evidence: dict, source: str,
    now: Optional[datetime] = None,
) -> dict:
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"verdict must be one of {VALID_VERDICTS}, got {verdict!r}")
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "signal": signal,
        "checked_at": ts,
        "verdict": verdict,
        "evidence": evidence,
        "source": source,
        "verifier_version": VERIFIER_VERSION,
    }


def pending_wall_record(spec: ECourtsCheckSpec | SOSCheckSpec, *, now: Optional[datetime] = None) -> dict:
    """The record to emit right after QUEUING a check, before any human has
    cleared the CAPTCHA/bot-check and saved a results page. Per the spec:
    'wall' = genuinely can't be checked by code -- label it honestly, never
    silently treat a queued-but-unexecuted check as confirmed."""
    query: dict[str, Any]
    if isinstance(spec, SOSCheckSpec):
        signal, source = "sos_entity", spec.portal_url
        query = {"entity_name": spec.entity_name, "portal_url": spec.portal_url}
    else:
        signal, source = spec.signal, spec.portal_url
        query = {
            "county": spec.county, "search_name": spec.search_name,
            "case_number": spec.case_number, "category_name": spec.category_name,
            "portal_url": spec.portal_url,
        }
    return make_verification_record(
        signal=signal, verdict="wall",
        evidence={
            "reason": "queued for human-assisted NC eCourts/SOS check; "
                      "CAPTCHA/bot-check not yet cleared by a human",
            "query": query,
        },
        source=source, now=now,
    )


# --------------------------------------------------------------------------- #
# (d) parse what the human saved
# --------------------------------------------------------------------------- #
def read_saved_page(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _import_ecourts_parser():
    """Lazy import of scripts/parse_nc_ecourts_export.py -- mirrors
    crewai_tools.py's own existing `sys.path.insert(0, str(_REPO / "scripts"))`
    pattern (that function's comment: "NC eCourts parser is in scripts/") so
    this reuses the SAME parser rather than re-deriving Smart-Search-grid /
    case-detail-card parsing rules a second time."""
    scripts_dir = str(_REPO / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from parse_nc_ecourts_export import parse_nc_ecourts_html  # noqa: E402
    return parse_nc_ecourts_html


def parse_saved_ecourts_page(html: str, spec: ECourtsCheckSpec, row: dict) -> dict:
    """Parse an operator-saved NC eCourts Smart Search page into the
    `raw.verification` record for `spec.signal`. Pure function of its inputs
    (no network, no file I/O) -- `html` is already in memory. Reuses
    `scripts/parse_nc_ecourts_export.parse_nc_ecourts_html` verbatim.

    Verdict is deliberately conservative: `parse_nc_ecourts_html`'s own output
    schema (case_number/plaintiff/defendant/party_names/case_type/filing_date/
    county) carries no case-STATUS field, so this never guesses "dismissed" /
    "satisfied" from data the parser does not actually expose -- that would be
    exactly the "silent success" failure mode CLAUDE.md warns this codebase
    already has a problem with. "confirmed" here means "a real, human-cleared
    eCourts case record was found and parsed," not "the underlying distress
    signal is definitely still true" -- the evidence is attached in full so a
    human (or a future scoring change) can read AND decide."""
    parse_nc_ecourts_html = _import_ecourts_parser()
    cases = parse_nc_ecourts_html(html, default_county=spec.county)

    if not cases:
        return make_verification_record(
            signal=spec.signal, verdict="unconfirmed",
            evidence={"cases_found": 0, "reason": "saved page had no parseable case record"},
            source=spec.portal_url,
        )

    matched = cases
    if spec.case_number:
        # Same alnum-only, uppercased normalization on BOTH sides (a bare
        # _digits() compare would wrongly treat "26E000100-320" and
        # "26E999999-320" as equal once the letter is stripped from only
        # one side -- caught by this module's own test suite).
        target = re.sub(r"[^0-9A-Za-z]", "", spec.case_number).upper()
        narrowed = [
            c for c in cases
            if target and target in re.sub(r"[^0-9A-Za-z]", "", c.get("case_number") or "").upper()
        ]
        if narrowed:
            matched = narrowed

    all_parties: set[str] = set()
    for c in matched:
        for p in (c.get("party_names") or []):
            cleaned = re.sub(r"\s+", " ", p).strip().upper()
            if cleaned:
                all_parties.add(cleaned)

    known = _known_person_names(row)
    new_names = sorted(n for n in all_parties if n not in known)

    evidence = {
        "cases_found": len(cases),
        "matched_cases": matched[:5],
        "all_party_names_on_saved_page": sorted(all_parties),
        "already_known_on_board": sorted(known),
        "newly_discovered_names": new_names,
    }
    return make_verification_record(
        signal=spec.signal, verdict="confirmed", evidence=evidence, source=spec.portal_url,
    )


_SOS_NEGATIVE_STATUSES = ("dissolved", "administratively dissolved", "revoked", "withdrawn")


def parse_saved_sos_page(html: str, spec: SOSCheckSpec) -> dict:
    """Parse an operator-saved NC SOS business-registration profile page into
    the `raw.verification` record for signal `"sos_entity"`. Reuses
    `enrichment_sos_agent._parse_profile` verbatim against the saved page's
    visible text -- the same parser the live Scrapling-stealth lane already
    uses, just pointed at a human-saved page instead of a live-rendered one."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    profile = _parse_sos_profile(text)

    found = bool(profile.get("legal_name") or profile.get("status") or profile.get("registered_agent"))
    if not found:
        return make_verification_record(
            signal="sos_entity", verdict="unconfirmed",
            evidence={"entity_searched": spec.entity_name,
                      "reason": "saved page had no parseable SOS profile"},
            source=spec.portal_url,
        )

    status = (profile.get("status") or "").strip().lower()
    verdict = "refuted" if status in _SOS_NEGATIVE_STATUSES else "confirmed"
    return make_verification_record(
        signal="sos_entity", verdict=verdict,
        evidence={"entity_searched": spec.entity_name, "profile": profile},
        source=spec.portal_url,
    )


# --------------------------------------------------------------------------- #
# Heir/decedent liveness for newly-discovered names -- free, no CAPTCHA, the
# one piece of the "Boone St" pattern that already WAS automatable.
# --------------------------------------------------------------------------- #
async def check_new_names_liveness(new_names: list[str]) -> dict[str, dict]:
    """For each name a saved eCourts page revealed that the board did not
    already carry, run the SAME free, no-CAPTCHA NC voter-file liveness check
    `validate_probate_heir_buncombe.py`'s `heir_voter_check()` already proved
    live (2026-10-03) -- not a new check, the existing one, reused. This is
    real network I/O against vt.ncsbe.gov, not the walled resource, so it is
    fine to run automatically; it just cannot run until the eCourts step
    (which DOES need a human) has produced a name to check."""
    from .enrichment_nc_voter_lookup import nc_voter_lookup

    out: dict[str, dict] = {}
    for name in new_names:
        toks = [t for t in re.sub(r"[.,]", " ", name).split() if t]
        if len(toks) < 2:
            out[name] = {"category": "unparseable_name"}
            continue
        first, last = toks[0], toks[-1]
        try:
            res = await nc_voter_lookup(first, last, "ALL", match_city=None, include_history=True)
        except Exception as exc:  # noqa: BLE001
            out[name] = {"category": "lookup_error", "error": f"{type(exc).__name__}: {str(exc)[:150]}"}
            continue
        if not res.get("ok"):
            out[name] = {"category": "lookup_error", "error": res.get("error")}
            continue
        status = str(res.get("status") or "")
        out[name] = {
            "category": {
                "active": "confirmed_active_locatable",
                "not_active": "found_but_not_active",
                "not_found": "not_found",
                "ambiguous": "ambiguous_common_name",
            }.get(status, status),
            "voter_result": res,
        }
    return out


async def verify_ecourts_from_saved_page(html: str, spec: ECourtsCheckSpec, row: dict) -> dict:
    """`parse_saved_ecourts_page` plus, for the probate/heir_estate family,
    an automatic liveness check on every newly-discovered name -- the full
    Boone-St pattern: a human clears the eCourts CAPTCHA once, this tool
    reads what it revealed, and (free, automatically) checks whether anyone
    it found that the board did not already know about is still alive."""
    record = parse_saved_ecourts_page(html, spec, row)
    if spec.signal in ("probate", "heir_estate"):
        new_names = record["evidence"].get("newly_discovered_names") or []
        if new_names:
            record["evidence"]["new_name_liveness"] = await check_new_names_liveness(new_names)
    return record


# --------------------------------------------------------------------------- #
# Write-back: the per-signal verification ledger the VM applies
# --------------------------------------------------------------------------- #
def record_to_ledger(row: dict, record: dict, *, directory: Optional[Path] = None,
                     now: Optional[datetime] = None) -> Path:
    """Merge one record from this lane into ``docs/handoff/verification/<signal>.json`` under
    ``verification.core.row_key(row)``; returns the ledger path. Raises
    ``verification.ledger.LedgerUnreadable`` rather than overwrite a broken ledger."""
    from .verification.core import VerificationResult
    from .verification.ledger import Ledger

    res = VerificationResult.from_dict(record)
    res.verifier = res.verifier or LEDGER_VERIFIER
    led = Ledger.load(res.signal, directory)
    led.record(row, res, ttl_days=LEDGER_TTL_DAYS.get(res.signal, 180),
               governs=LEDGER_GOVERNS.get(res.signal, ()), now=now)
    return led.save()


# --------------------------------------------------------------------------- #
# What a direct board patch WOULD apply (inspection only; the ledger is the write path).
# --------------------------------------------------------------------------- #
def build_patch_preview(row: dict, record: dict) -> dict:
    """The shape a follow-up board-write script would need to call
    `web_artifact.patch_existing_rows()`: a `dedupe_key()`-able identity
    (recomputed by that follow-up script itself from these raw identity
    fields, not trusted pre-computed here -- `patch_existing_rows()`'s own
    contract) plus the `raw.verification` LIST to merge in (that function
    merges `raw` updates rather than overwriting them). This module never
    calls `patch_existing_rows()` itself: records reach the board through
    `record_to_ledger()` and the VM's verification apply (module docstring,
    "REACHES THE BOARD THROUGH THE VERIFICATION LEDGER")."""
    identity = {
        k: row.get(k)
        for k in ("source_url", "parcel_id", "street_address", "zip_code",
                  "case_number", "county", "state")
    }
    existing = (row.get("raw") or {}).get("verification")
    existing = existing if isinstance(existing, list) else []
    merged = [r for r in existing if r.get("signal") != record.get("signal")] + [record]
    return {"row_identity": identity, "raw_patch": {"verification": merged}}
