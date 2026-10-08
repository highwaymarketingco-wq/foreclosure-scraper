"""Additions invariants (audit 2026-10-09, area additions_verify): everything added to the pipeline
since 2026-10-01 (new sources, new enrichers, re-enabled approaches, run flags) keeps producing
output, keeps reaching the published row shape, and stays in the run profile, so no later run loses
it silently. docs/audit_2026-10-09/additions_ledger.md is the ledger (one row per addition, by id).

THE REGISTRY (ADDITIONS below) names, per addition: how its output is recognised on a board row
(row source slugs, raw keys, or a predicate), the raw keys that must publish (RAW_KEEP) or must
never publish (private), the env flags the run profile must declare, and two floors:
  floor        rows carrying the output on a FULL board (>= FULL_BOARD_ROWS rows; a canary or a
               sample board reports counts only), carried rows included;
  fresh_floor  rows whose own fetch date (fresh_key, e.g. raw.rod.fetched_at) falls within
               FRESH_DAYS of the board's newest last_seen: proof the enricher RAN in the run that
               wrote the board, not only that older rows were carried (the 10/8 checkpoint carried
               7,078 register blocks while the run itself reached 5 of 60 register counties).

Checks (make_checks):
  addition-<id>                    one per addition: rows (and fresh rows) at or above the
                                   floors, and at or under the ceiling where one is set (HomePath:
                                   the Fannie Mae REO inventory is about 60 rows; 580 retail
                                   listings were published as REO on 10/8). Additions recorded as a wall, an owner
                                   decision or off by default have floor 0 and always pass (their
                                   counts are still reported).
  additions-publish-shape          static: every publish key is in web_artifact.RAW_KEEP and every
                                   private key is not. 0 allowed.
  additions-profile-flags          static: every flag an addition needs is declared with that value
                                   in deploy/oracle/run_profile.json AND exported by vm_lib.sh. 0.
  additions-ledger-complete        static: the ledger lists every addition id. 0 allowed.
  additions-heir-relations         every published heir candidate's relation is in
                                   enrichment_heir_candidates.PUBLISHABLE_HEIR_RELATIONS and it has
                                   no age, birth date, phone or e-mail field. 0 allowed.
  additions-private-blocks         raw.obituary_match / raw.obituary_private on a published row. 0.
  additions-rod-binds-owner        a register block (raw.rod from generic_rod, or raw.rod_chain with
                                   status ok) whose instruments / searched name do not carry the
                                   row's owner surname: a lookup bound to another person or a stale
                                   block after an owner change. At most 3% of such rows.
  additions-richland-county        raw.richland_parcel matched on a row outside Richland SC. 0.
  additions-near-beach-bar         raw.near_beach_drive outside its own bar (distance over max_m,
                                   ocean-facing distance over 3,500 m, or an imprecise point). 0.
  additions-sos-agent-bound        a government-owned row publishing another entity's NC SoS
                                   profile (120 Lincoln county parcels on 10/8). 0 allowed.
  additions-rod-chain-binding      a deed chain read since 2026-10-09 with no raw.rod_chain.binding,
                                   or a 'contradicted' binding still marked status ok. 0 allowed
                                   (30 sampled 10/8 chains: 14 right, 16 another parcel or stale).
  additions-alias-is-pin           raw.parcel_id_alias mapping a short id to anything but a 10-digit
                                   NC PIN (53 Rutherford rows got another property's id on 10/8). 0.
  additions-window-lanes-not-aging court rows of a filed-date-window lane (Charleston Public Index,
                                   judgment_lien sub-lanes) marked presumed withdrawn by the carry-
                                   forward aging because the window no longer reaches them. At most
                                   10% (would flag the 1,549 Charleston rows on the run after 10/8).

Memory: counters, a few date counters per addition, at most SAMPLE examples (source slugs, county
names, parcel ids; never a person's name).

Measurement CLI (the ledger's numbers; streams the RAW checkpoint so private keys are counted too):
  uv run python scripts/audit_checks/additions.py --checkpoint DIR [--samples OUT.json] [--json OUT]
--samples writes up to 30 random rows per addition with the fields needed to check them by hand.
It holds names, so OUT must be outside the repo (the owner's audit folder on the Desktop).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SAMPLE = 8
FULL_BOARD_ROWS = 200_000
FRESH_DAYS = 3
LEDGER = _REPO / "docs" / "audit_2026-10-09" / "additions_ledger.md"
PROFILE = _REPO / "deploy" / "oracle" / "run_profile.json"
VM_LIB = _REPO / "deploy" / "oracle" / "vm_lib.sh"
ROD_BIND_MAX_SHARE = 0.03


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _nonempty(v: Any) -> bool:
    return v not in (None, "", [], {}, False)


def _src_match(source: str, slugs: tuple[str, ...]) -> bool:
    for s in slugs:
        if s.endswith("*"):
            if source.startswith(s[:-1]):
                return True
        elif source == s or source.startswith(s + "."):
            return True
    return False


def _also_seen(row: dict) -> list[str]:
    out = []
    for x in _raw(row).get("also_seen_in") or []:
        if isinstance(x, dict) and isinstance(x.get("source"), str):
            out.append(x["source"])
        elif isinstance(x, str):
            out.append(x)
    return out


def _dig(d: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def _day(v: Any) -> Optional[str]:
    s = str(v or "")[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


# ------------------------------------------------------------------------------------ predicates
def _p_generic_rod(row: dict) -> bool:
    rod = _raw(row).get("rod")
    return isinstance(rod, dict) and rod.get("source") == "generic_rod"


def _p_rod_chain_ok(row: dict) -> bool:
    rc = _raw(row).get("rod_chain")
    return isinstance(rc, dict) and rc.get("status") == "ok"


def _p_richland_matched(row: dict) -> bool:
    rp = _raw(row).get("richland_parcel")
    return isinstance(rp, dict) and bool(rp.get("matched"))


def _p_heir_published(row: dict) -> bool:
    hc = _raw(row).get("heir_candidates")
    return isinstance(hc, list) and len(hc) > 0


def _p_judgment_lien(row: dict) -> bool:
    s = str(row.get("source") or "")
    return s.endswith(".judgment_lien") or s == "nc_ecourts_judgments"


def _p_homepath_reo(row: dict) -> bool:
    return str(row.get("source") or "") in ("national.fannie_homepath", "national.homepath_json")


def _p_sc_divorce(row: dict) -> bool:
    return (row.get("state") == "SC") and _nonempty(_raw(row).get("divorce"))


def _p_fjudgment(row: dict) -> bool:
    return _raw(row).get("foreclosure_judgment_entered") is True


def _p_cache_join(row: dict) -> bool:
    om = _raw(row).get("owner_mailing")
    return isinstance(om, dict) and om.get("source") == "parcel_cache"


PREDICATES: dict[str, Callable[[dict], bool]] = {
    "generic_rod": _p_generic_rod,
    "rod_chain_ok": _p_rod_chain_ok,
    "richland_matched": _p_richland_matched,
    "heir_published": _p_heir_published,
    "judgment_lien": _p_judgment_lien,
    "homepath_reo": _p_homepath_reo,
    "sc_divorce": _p_sc_divorce,
    "foreclosure_judgment_entered": _p_fjudgment,
    "cache_join": _p_cache_join,
}


class Addition(NamedTuple):
    """One addition (a NamedTuple, not a dataclass: audit_suite loads check modules from their
    file path without registering them in sys.modules, which dataclasses need)."""
    id: str
    title: str
    kind: str                       # source | enricher | approach | flag
    commits: tuple[str, ...]
    lane: str                       # vm | mac_handoff | script
    sources: tuple[str, ...] = ()   # row source slugs (exact, slug + '.', or prefix*)
    raw_keys: tuple[str, ...] = ()  # any of these raw keys non-empty
    pred: Optional[str] = None      # PREDICATES name (replaces sources/raw_keys when set)
    publish_keys: tuple[str, ...] = ()
    private_keys: tuple[str, ...] = ()
    flags: dict = {}                # read only
    floor: int = 0
    fresh_key: Optional[str] = None  # dotted raw path to the block's own fetch date
    fresh_floor: int = 0
    ceiling: Optional[int] = None    # rows on a full board above this are a violation too
    status: str = ""


A = Addition
#: Every addition since 2026-10-01 that the 10/8 gated run (pin d42058b3) carried or that the next
#: run must keep. Floors are on a full board (>= FULL_BOARD_ROWS); the 10/8 pre_publish checkpoint
#: counts are in the ledger. Keep ids stable: the ledger is keyed by them.
ADDITIONS: tuple[Addition, ...] = (
    # ---------------------------------------------------------------- new sources (VM run)
    A("src-bankruptcy-rss-relief", "bankruptcy-court RSS: relief-from-stay motions", "source",
      ("49353e8d",), "vm", sources=("national.bankruptcy_rss_relief_from_stay",),
      publish_keys=("bankruptcy_relief_from_stay",), floor=5, status="working"),
    A("src-echovita-obituaries", "Echovita NC/SC obituaries (heir candidates)", "source",
      ("3bc56410", "a7b73d4a"), "vm", sources=("public_notices.echovita_obituaries",),
      publish_keys=("obituary",), private_keys=("obituary_private",), floor=150, status="working"),
    A("src-obituary-feeds", "paper and funeral-home obituary feeds", "source", ("3bc56410",), "vm",
      sources=("public_notices.obituary_feeds",), floor=10, status="working"),
    A("src-publicnoticesc-estates", "SC estate notices (scpublicnotices.com)", "source",
      ("ff795773", "cf044d6f"), "vm", sources=("public_notices.publicnoticesc_estates",),
      floor=0, status="zero"),
    A("src-charleston-energov-history", "Charleston County code cases and demolition permits", "source",
      ("ba366cc5",), "vm", sources=("counties_sc.charleston_energov_history",),
      publish_keys=("charleston_energov",), floor=0, status="zero"),
    A("src-horry-probate", "Horry County probate estates (Spartan portal)", "source",
      ("8e156c5d",), "vm", sources=("counties_sc.horry_probate",), floor=2000, status="working"),
    A("src-york-tax-sale-parcels", "York County SC tax-sale layer", "source", ("f73b2bf9",), "vm",
      sources=("counties_sc.york_tax_sale_parcels",), publish_keys=("york_tax_sale",), floor=400,
      status="working"),
    A("src-cumberland-delinquent-tax", "Cumberland NC delinquent-tax advertisement", "source",
      ("ba366cc5",), "vm", sources=("counties_nc.cumberland_delinquent_tax",),
      publish_keys=("cumberland_delinquent_tax",), floor=1800, status="working"),
    A("src-guilford-tax-foreclosures", "Guilford NC tax-foreclosure layer", "source",
      ("f8ad91f8",), "vm", sources=("counties_nc.guilford_tax_foreclosures",),
      publish_keys=("guilford_tax_foreclosure",), floor=400, status="working"),
    A("src-iredell-delinquent-tax", "Iredell NC delinquent-tax layer", "source", ("ba366cc5",), "vm",
      sources=("counties_nc.iredell_delinquent_tax",), publish_keys=("iredell_delinquent_tax",),
      floor=1100, status="working"),
    A("src-kinston-proposed-demolition", "Kinston NC proposed demolitions", "source",
      ("f73b2bf9",), "vm", sources=("counties_generic.arcgis_distress.kinston_proposed_demolition",
                                    "counties_nc.kinston_proposed_demolition"),
      publish_keys=("kinston_demolition",), floor=20, status="working"),
    A("src-mecklenburg-delinquent-tax", "Mecklenburg NC delinquent list (XLSX)", "source",
      ("f8ad91f8",), "vm", sources=("counties_nc.mecklenburg_delinquent_tax",),
      publish_keys=("mecklenburg_delinquent_tax",), flags={"FORECLOSURE_MECKLENBURG_DELINQUENT": "0"},
      floor=0, status="off_by_decision"),
    A("src-mecklenburg-tax-foreclosures", "Mecklenburg NC tax-foreclosure layer", "source",
      ("f8ad91f8",), "vm", sources=("counties_nc.mecklenburg_tax_foreclosures",),
      publish_keys=("mecklenburg_tax_foreclosure",), floor=300, status="working"),
    A("src-nc-metro-demolition-permits", "demolition permits: Charlotte, Durham, Greensboro, Cary",
      "source", ("ba366cc5",), "vm", sources=("counties_nc.nc_metro_demolition_permits",),
      publish_keys=("demolition_permit",), floor=800, status="working"),
    A("src-nc-tax-lien-ads", "NC tax-lien advertisement PDFs (Hoke, Lee, Davidson, Randolph)",
      "source", ("ba366cc5",), "vm", sources=("counties_nc.nc_tax_lien_ads",),
      publish_keys=("nc_tax_lien_ad",), floor=5000, status="working"),
    A("src-rocky-mount-blight-survey", "Rocky Mount 2025 parcel condition survey", "source",
      ("f73b2bf9",), "vm", sources=("counties_generic.arcgis_distress.rocky_mount_blight_survey_2025",
                                    "counties_nc.rocky_mount_blight_survey"),
      publish_keys=("blight_survey",), floor=300, status="working"),
    A("src-rowan-delinquent-tax", "Rowan NC delinquent-tax spreadsheet", "source", ("ba366cc5",),
      "vm", sources=("counties_nc.rowan_delinquent_tax",), publish_keys=("rowan_delinquent_tax",),
      floor=1300, status="working"),
    A("src-wake-code-cases", "Wake County code cases (90 days)", "source", ("ba366cc5",), "vm",
      sources=("counties_nc.wake_code_cases",), publish_keys=("wake_code_case",), floor=20,
      status="working"),
    A("src-columbia-star", "Columbia Star Richland MIE sale notices", "source", ("5042a060",), "vm",
      sources=("newspapers.columbia_star",), floor=3, status="working"),
    A("src-mecklenburg-times", "Mecklenburg Times legal notices RSS", "source", ("d75db9f5",), "vm",
      sources=("newspapers.mecklenburg_times",), floor=0, status="zero"),
    A("src-raleigh-structure-fires", "Raleigh structure fires", "source", ("f73b2bf9",), "vm",
      sources=("counties_generic.arcgis_distress.raleigh_structure_fires",
               "city_websites.raleigh_structure_fires"), publish_keys=("fire_incident",), floor=150,
      status="working"),
    A("src-asheville-code-enforcement", "Asheville code enforcement cases", "source", ("066605da",),
      "vm", sources=("counties_nc.asheville_code_enforcement",), floor=0, status="zero"),
    A("src-anderson-acpass-deeds", "Anderson SC ACPASS deed index (source)", "source", ("80f20417",),
      "vm", sources=("counties_sc.anderson_acpass_deeds",), publish_keys=("anderson_acpass",),
      floor=0, status="zero"),
    A("src-calhoun-overage-claims", "Calhoun SC tax-sale overage claims", "source", ("1449d702",),
      "vm", sources=("counties_sc.calhoun_overage_claims",), publish_keys=("tax_sale_overage",),
      floor=20, status="working"),
    A("src-fairfield-overage-claims", "Fairfield SC tax-sale overage claims", "source",
      ("1449d702",), "vm", sources=("counties_sc.fairfield_overage_claims",), floor=20,
      status="working"),
    A("src-laurens-overage-claims", "Laurens SC tax-sale overage claims", "source", ("d0923313",),
      "vm", sources=("counties_sc.laurens_overage_claims",), floor=0, status="zero"),
    A("src-orangeburg-overage-claims", "Orangeburg SC tax-sale overage claims", "source",
      ("d0923313",), "vm", sources=("counties_sc.orangeburg_overage_claims",), floor=0,
      status="zero"),
    A("src-greenwood-cama-condemned", "Greenwood SC condemned parcels (CAMA layer)", "source",
      ("2e32a73d",), "vm", sources=("counties_generic.arcgis_distress.greenwood_cama_condemned",),
      floor=300, status="working"),
    A("src-funeral-home-rss", "funeral-home obituary feeds (hosts recovered, concurrent reads)",
      "source", ("5b7e3ae8", "a896a642"), "vm", sources=("public_notices.funeral_home_rss",),
      floor=50, status="capped"),
    # ---------------------------------------------------------------- hand-off lanes (Mac; observed only)
    A("src-liensnc-incremental", "LiensNC filings: Mac incremental refresh + never age out", "source",
      ("23e05763", "7a15c683"), "mac_handoff", sources=("counties_generic.liensnc", "liensnc"),
      publish_keys=("liensnc", "liensnc_related"), floor=30000, status="working"),
    A("src-judgment-lien-lane", "NC eCourts / SC Public Index docketed judgments as judgment_lien",
      "source", ("375b4b72", "5cb93b78"), "mac_handoff", pred="judgment_lien", floor=1000,
      status="next_run"),
    A("src-charleston-public-index-lanes", "Charleston Public Index lanes; judgment-entered flag",
      "approach", ("bb935e1f", "7b104baa", "0d07cf96", "ab44ec1e"), "mac_handoff",
      pred="foreclosure_judgment_entered", publish_keys=("foreclosure_judgment_entered",), floor=0,
      status="next_run"),
    A("src-sc-divorce-46-counties", "SC Family Court divorce: all 46 county codes", "approach",
      ("11a20a99",), "mac_handoff", pred="sc_divorce", publish_keys=("divorce",), floor=500,
      status="working"),
    A("src-nc-ecourts-estates", "NC eCourts estates (WAF path, as the owner left it)", "source",
      ("3827b032",), "mac_handoff", sources=("counties_nc.nc_ecourts_estates",),
      publish_keys=("nc_ecourts_estates",), floor=0, status="zero_wall"),
    A("src-sos-dissolution", "NC SoS dissolution check (WAF path, as the owner left it)", "approach",
      ("3827b032",), "vm", raw_keys=("sos_dissolution",), publish_keys=("sos_dissolution",),
      floor=0, status="zero_wall"),
    A("src-loopnet-render", "LoopNet render rewrite (re-enabled)", "source", ("44a61fe6",),
      "mac_handoff", sources=("national.loopnet",), publish_keys=("loopnet",), floor=0,
      status="zero_wall"),
    # ---------------------------------------------------------------- register of deeds
    A("enr-generic-rod-platforms", "register-of-deeds platform readers (raw.rod by owner name)",
      "enricher", ("a237f78b", "8611d9f3", "9edff1f3"), "vm", pred="generic_rod",
      publish_keys=("rod",), floor=3000, fresh_key="rod.fetched_at", fresh_floor=200,
      flags={"FORECLOSURE_NC_COTT_ROD": "1", "FORECLOSURE_NC_LOOKUP_ROD": "1",
             "FORECLOSURE_NC_ORS_ROD": "1", "FORECLOSURE_NC_CCHS_CLASSIC_ROD": "1",
             "FORECLOSURE_NC_TYLER_ROD": "1", "FORECLOSURE_SC_ORS_ROD": "1",
             "FORECLOSURE_SC_ACPASS_ROD": "1", "FORECLOSURE_SC_PUBLICSEARCH_ROD": "1",
             "FORECLOSURE_SC_ACCLAIM_ROD": "1", "FORECLOSURE_SC_GREENWOOD_ROD": "1",
             "FORECLOSURE_SC_RECORDROOM_ROD": "1", "FORECLOSURE_SC_COTT_ESEARCH_ROD": "1",
             "FORECLOSURE_SC_LOOKUP_ROD": "1", "FORECLOSURE_GENERIC_ROD_BUDGET_S": "2400",
             "GENERIC_ROD_COUNTY_CONCURRENCY": "8"},
      status="capped"),
    A("enr-rod-chain", "deed chain per lead (raw.rod_chain)", "enricher", ("a237f78b", "853ceb5c"),
      "vm", pred="rod_chain_ok", raw_keys=("rod_chain",), publish_keys=("rod_chain",), floor=60,
      fresh_key="rod_chain.fetched_at", fresh_floor=60,
      flags={"FORECLOSURE_ROD_CHAIN": "1", "FORECLOSURE_ROD_CHAIN_BUDGET_S": "1800",
             "ROD_CHAIN_COUNTY_CONCURRENCY": "8"}, status="capped"),
    A("enr-nc-rod-render", "browser-rendered NC registers (Harris, Logan)", "enricher",
      ("50d059c4", "853ceb5c"), "vm", raw_keys=(),
      flags={"FORECLOSURE_NC_HARRIS_ROD": "0", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD": "0",
             "FORECLOSURE_NC_LOGAN_REMOTE_ROD": "0"}, floor=0, status="off_by_decision"),
    # ---------------------------------------------------------------- heirs and obituaries
    A("enr-heir-candidates", "heir candidates per dead-owner lead (published, filtered)", "enricher",
      ("bb9355a2", "0126b88f", "8611d9f3"), "vm", pred="heir_published",
      publish_keys=("heir_candidates", "heir_candidates_summary"), floor=2000, status="working"),
    A("enr-obituary-match", "obituary-to-owner match (private store; feeds heir candidates)",
      "enricher", ("bb9355a2",), "vm", raw_keys=("obituary_match",),
      private_keys=("obituary_match", "obituary_private"), floor=0, status="working"),
    A("enr-obituary-lookup", "obituary lookups by name (Echovita, Find a Grave)", "enricher",
      ("2f0d038b",), "vm", flags={"OBITUARY_LOOKUPS": "0"}, floor=0, status="off_by_decision"),
    A("enr-nc-heir-estate-cap", "heir/estate parcels: per-county cap 80 -> 400, value first",
      "approach", ("b287eb79",), "vm", sources=("counties_nc.nc_heir_estate_parcels",),
      publish_keys=("heir_estate",), floor=3000, status="working"),
    # ---------------------------------------------------------------- contact and facts
    A("enr-richland-parcel", "Richland SC map-viewer parcel facts and mailing", "enricher",
      ("b1a82194", "8592d84b"), "vm", pred="richland_matched", publish_keys=("richland_parcel",),
      floor=150, fresh_key="richland_parcel.attempted", fresh_floor=100,
      flags={"RICHLAND_PARCEL_MAX": "500"}, status="capped"),
    A("enr-parcel-cache-join", "parcel-cache join on every row + fact columns", "approach",
      ("0adf8bba",), "vm", pred="cache_join", publish_keys=("owner_mailing",), floor=30000,
      status="working"),
    A("enr-sos-agent-handoff", "NC SoS registered-agent contacts (Mac hand-off)", "enricher",
      ("ee44ec25", "ed456b3b"), "mac_handoff", raw_keys=("sos_agent",), publish_keys=("sos_agent",),
      floor=400, status="working"),
    A("enr-entity-type", "owner entity type", "enricher", ("18dcf810",), "vm",
      raw_keys=("entity_type",), publish_keys=("entity_type",), floor=150000, status="working"),
    # ---------------------------------------------------------------- tax age and scoring
    A("enr-tax-age", "tax age: late years only, big-old tax, not-yet-late", "approach",
      ("c80963f0", "ae28568e"), "vm", raw_keys=("tax_big_old", "tax_not_yet_late"),
      publish_keys=("tax_big_old", "tax_not_yet_late"), floor=500, status="working"),
    A("enr-tax-aging-surfaced", "tax aging surfaced into scoring", "enricher", ("f514bd45",), "vm",
      raw_keys=("tax_aging_surfaced", "tax_aging_high"),
      publish_keys=("tax_aging_surfaced", "tax_aging_high"), floor=50000, status="working"),
    A("enr-co-defendant-signal", "co-defendant lienholders on court leads", "enricher",
      ("52e64f80",), "vm", raw_keys=("co_defendant_signal",), publish_keys=("co_defendant_signal",),
      floor=60, status="working"),
    A("enr-hoa-plaintiff-signal", "HOA-plaintiff foreclosure flag", "enricher", ("a900271b",), "vm",
      raw_keys=("hoa_plaintiff_signal",), publish_keys=("hoa_plaintiff_signal",), floor=25,
      status="working"),
    A("enr-liensnc-posthumous", "LiensNC filing after the owner's death", "enricher",
      ("23e05763",), "vm", raw_keys=("liensnc_posthumous_filing",),
      publish_keys=("liensnc_posthumous_filing",), floor=50, status="working"),
    # ---------------------------------------------------------------- carried-data corrections
    A("apr-prior-correction", "in-run correction of carried rows (fallback points, name counties, "
      "exemption claims)", "approach", ("ea6a4e0a", "f7acaeb1", "4170cbbc"), "vm",
      raw_keys=("parcel_withdrawn_fallback_point", "county_was_name_derived", "exempt_claim_withdrawn"),
      publish_keys=("parcel_withdrawn_fallback_point", "county_was_name_derived",
                    "exempt_claim_withdrawn"), floor=1000, status="working"),
    A("apr-parcel-alias", "Lincoln/Rutherford 10-digit PIN with a merge alias", "approach",
      ("38748f73",), "vm", raw_keys=("parcel_id_alias",), publish_keys=("parcel_id_alias",),
      floor=300, status="working"),
    A("apr-coastal-flip-5min", "coastal flips within a 5 minute drive of the beach", "approach",
      ("67375356",), "vm", raw_keys=("near_beach_drive",), publish_keys=("near_beach_drive",),
      floor=20, status="working"),
    A("apr-homepath-reo-only", "HomePath: Fannie Mae REO only", "approach", ("c33369b5", "7d5b7ae1",
                                                                            "aef7c291"), "vm",
      pred="homepath_reo", floor=0, ceiling=300, status="fixed_next_run"),
    A("apr-verification-apply", "county-site verdicts applied to the board", "approach",
      ("465e6c1e",), "vm", raw_keys=("verification",), publish_keys=("verification",), floor=1500,
      flags={}, status="working"),
    A("apr-pickens-2026-cycle", "Pickens 2026 delinquent cycle; prior-cycle-only context", "approach",
      ("03f6428a", "ad56ce7e"), "vm", raw_keys=("pickens_prior_cycle_only",),
      publish_keys=("pickens_delinquent", "pickens_prior_cycle_only"), floor=100, status="working"),
    A("apr-qpaybill-staged-detail", "qPayBill delinquent roll with staged detail pages", "approach",
      ("e95dd10e", "708630b7"), "vm", sources=("counties_sc.qpaybill_delinquent_roll",),
      publish_keys=("qpaybill_roll",), floor=20000, status="capped"),
    # ---------------------------------------------------------------- documents
    A("doc-ocr-notices", "notice PDF OCR (RECAP documents, county notice PDFs wired)", "enricher",
      ("236179bc", "ea498cd0", "048b69b5", "7c68431c"), "vm", raw_keys=("doc_ocr",),
      publish_keys=("doc_ocr",), floor=40, status="capped"),
    A("doc-dot-ocr", "deed-of-trust image OCR (loan amount)", "enricher", ("ab8de34e",), "vm",
      raw_keys=("dot_ocr",), publish_keys=("dot_ocr", "loan_amount"), floor=10,
      status="zero_wall"),
)

BY_ID = {a.id: a for a in ADDITIONS}


def matches(a: Addition, row: dict) -> bool:
    if a.pred:
        return PREDICATES[a.pred](row)
    if a.sources:
        src = str(row.get("source") or "")
        if _src_match(src, a.sources):
            return True
        if any(_src_match(s, a.sources) for s in _also_seen(row)):
            return True
    raw = _raw(row)
    return any(_nonempty(raw.get(k)) for k in a.raw_keys)


# ------------------------------------------------------------------------------------ checks
class _Board:
    """Shared per-pass state: rows seen and the newest last_seen day (for the fresh window)."""

    def __init__(self) -> None:
        self.rows = 0
        self.newest = ""

    def feed(self, row: dict) -> None:
        self.rows += 1
        d = _day(row.get("last_seen"))
        if d and d > self.newest:
            self.newest = d


class AdditionFloor:
    def __init__(self, a: Addition) -> None:
        self.a = a
        self.name = f"addition-{a.id}"
        self.board = _Board()          # each check counts the rows it is fed (no shared state)
        self.n = 0
        self.days: Counter = Counter()

    def feed(self, row: dict) -> None:
        self.board.feed(row)
        if not matches(self.a, row):
            return
        self.n += 1
        if self.a.fresh_key:
            d = _day(_dig(_raw(row), self.a.fresh_key))
            if d:
                self.days[d] += 1

    def fresh(self) -> int:
        if not self.board.newest:
            return 0
        cut = (date.fromisoformat(self.board.newest) - timedelta(days=FRESH_DAYS)).isoformat()
        return sum(c for d, c in self.days.items() if d >= cut)

    def finish(self) -> dict:
        full = self.board.rows >= FULL_BOARD_ROWS
        fresh = self.fresh()
        bad = []
        if full and self.n < self.a.floor:
            bad.append(f"{self.n} rows < floor {self.a.floor}")
        if full and self.a.fresh_key and fresh < self.a.fresh_floor:
            bad.append(f"{fresh} fresh rows < fresh floor {self.a.fresh_floor}")
        if full and self.a.ceiling is not None and self.n > self.a.ceiling:
            bad.append(f"{self.n} rows > ceiling {self.a.ceiling}")
        detail = (f"{self.n} rows" + (f", {fresh} fetched within {FRESH_DAYS} days of "
                                      f"{self.board.newest}" if self.a.fresh_key else "")
                  + f"; status {self.a.status}" + ("" if full else "; not a full board: counts only"))
        if bad:
            detail = "; ".join(bad) + " | " + detail
        return {"name": self.name, "checked": self.board.rows, "violations": 1 if bad else 0,
                "max_violations": 0, "ok": not bad, "detail": detail}


class _Static:
    """A check decided without the board (registry vs code, profile, ledger)."""

    def __init__(self, name: str, fn: Callable[[], tuple[int, int, str]]) -> None:
        self.name = name
        self._fn = fn

    def feed(self, row: dict) -> None:
        return None

    def finish(self) -> dict:
        checked, bad, detail = self._fn()
        return {"name": self.name, "checked": checked, "violations": bad, "max_violations": 0,
                "ok": bad == 0, "detail": detail}


def _publish_shape() -> tuple[int, int, str]:
    from foreclosure_scraper.web_artifact import RAW_KEEP
    checked, bad = 0, []
    for a in ADDITIONS:
        for k in a.publish_keys:
            checked += 1
            if k not in RAW_KEEP:
                bad.append(f"{a.id}: {k} not in RAW_KEEP")
        for k in a.private_keys:
            checked += 1
            if k in RAW_KEEP:
                bad.append(f"{a.id}: private {k} is in RAW_KEEP")
    return checked, len(bad), "; ".join(bad[:SAMPLE]) or f"{checked} keys as declared"


def _profile_flags(profile_path: Path = PROFILE, vm_lib: Path = VM_LIB) -> tuple[int, int, str]:
    try:
        profile = json.loads(profile_path.read_text())
    except (OSError, ValueError) as exc:
        return 1, 1, f"run profile unreadable: {exc}"
    want = profile.get("flags") or {}
    from pipeline_wiring import vm_lib_flags  # scripts/pipeline_wiring.py
    have = vm_lib_flags(vm_lib)
    checked, bad = 0, []
    for a in ADDITIONS:
        for k, v in a.flags.items():
            checked += 1
            if str(want.get(k)) != v:
                bad.append(f"{a.id}: profile {k}={want.get(k, '<undeclared>')} (want {v})")
            elif str(have.get(k)) != v:
                bad.append(f"{a.id}: vm_lib {k}={have.get(k, '<unset>')} (want {v})")
    return checked, len(bad), "; ".join(bad[:SAMPLE]) or f"{checked} flags declared and exported"


def _ledger_complete(path: Path = LEDGER) -> tuple[int, int, str]:
    try:
        text = path.read_text()
    except OSError:
        return len(ADDITIONS), len(ADDITIONS), f"no ledger at {path.name}"
    missing = [a.id for a in ADDITIONS if f"`{a.id}`" not in text]
    return len(ADDITIONS), len(missing), ("missing: " + ", ".join(missing[:SAMPLE])) if missing \
        else f"{len(ADDITIONS)} additions listed"


class HeirRelations:
    name = "additions-heir-relations"
    _FORBIDDEN = ("age", "birth", "born", "dob", "phone", "email", "e_mail")

    def __init__(self) -> None:
        from foreclosure_scraper.enrichment_heir_candidates import PUBLISHABLE_HEIR_RELATIONS
        self.allowed = PUBLISHABLE_HEIR_RELATIONS
        self.checked = 0
        self.bad = 0
        self.examples: list[str] = []

    def feed(self, row: dict) -> None:
        hc = _raw(row).get("heir_candidates")
        if not isinstance(hc, list):
            return
        for c in hc:
            if not isinstance(c, dict):
                continue
            self.checked += 1
            rel = str(c.get("relation") or "").strip().lower()
            keys = {str(k).lower() for k in c}
            forbidden = [k for k in keys if any(k == f or k.startswith(f + "_") for f in self._FORBIDDEN)]
            if rel not in self.allowed or forbidden:
                self.bad += 1
                if len(self.examples) < SAMPLE:
                    self.examples.append(f"{row.get('county')}|{row.get('parcel_id')}|{rel or '-'}"
                                         + (f"|{','.join(forbidden)}" if forbidden else ""))

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": "; ".join(self.examples) or f"{self.checked} published candidates"}


class PrivateBlocks:
    name = "additions-private-blocks"

    def __init__(self) -> None:
        self.checked = 0
        self.bad = 0

    def feed(self, row: dict) -> None:
        self.checked += 1
        raw = _raw(row)
        if _nonempty(raw.get("obituary_match")) or _nonempty(raw.get("obituary_private")):
            self.bad += 1

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": f"{self.bad} rows publish a private obituary block"}


_SURNAME_SKIP = {"THE", "OF", "ESTATE", "HEIRS", "HEIR", "LLC", "INC", "TRUST", "AND", "ET", "AL",
                 "UX", "VIR", "JR", "SR", "II", "III", "IV", "MRS", "MR", "DR", "CO", "LLP", "LP"}


def owner_tokens(owner: str) -> set[str]:
    toks = re.findall(r"[A-Z][A-Z'\-]+", str(owner or "").upper())
    return {t for t in toks if len(t) >= 3 and t not in _SURNAME_SKIP}


def rod_bound(row: dict) -> Optional[bool]:
    """None when the row carries no register block to judge; else whether the block names a
    token of the row's owner (surname or given name; the searched name for a chain)."""
    raw = _raw(row)
    own = owner_tokens(row.get("owner_name") or "")
    if not own:
        return None
    if _p_generic_rod(row):
        blob = " ".join(f"{i.get('grantor') or ''} {i.get('grantee') or ''}"
                        for i in (raw["rod"].get("instruments") or []) if isinstance(i, dict))
        return bool(own & owner_tokens(blob)) if blob.strip() else None
    if _p_rod_chain_ok(row):
        return bool(own & owner_tokens(raw["rod_chain"].get("owner_searched") or ""))
    return None


class RodBindsOwner:
    name = "additions-rod-binds-owner"

    def __init__(self) -> None:
        self.checked = 0
        self.bad = 0
        self.examples: list[str] = []

    def feed(self, row: dict) -> None:
        b = rod_bound(row)
        if b is None:
            return
        self.checked += 1
        if not b:
            self.bad += 1
            if len(self.examples) < SAMPLE:
                self.examples.append(f"{row.get('state')}|{row.get('county')}|{row.get('parcel_id')}")

    def finish(self) -> dict:
        cap = int(self.checked * ROD_BIND_MAX_SHARE)
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": cap, "ok": self.bad <= cap,
                "detail": (f"{self.bad} of {self.checked} register blocks name none of the row "
                           f"owner's name words; e.g. " + "; ".join(self.examples)) if self.bad
                else f"{self.checked} register blocks bound to the row owner"}


class RichlandCounty:
    name = "additions-richland-county"

    def __init__(self) -> None:
        self.checked = 0
        self.bad = 0
        self.examples: list[str] = []

    def feed(self, row: dict) -> None:
        if not _p_richland_matched(row):
            return
        self.checked += 1
        if not (row.get("state") == "SC" and str(row.get("county") or "").strip() == "Richland"):
            self.bad += 1
            if len(self.examples) < SAMPLE:
                self.examples.append(f"{row.get('state')}|{row.get('county')}|{row.get('parcel_id')}")

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": "; ".join(self.examples) or f"{self.checked} Richland matches in Richland"}


class NearBeachBar:
    name = "additions-near-beach-bar"
    OCEAN_FACING_MAX_M = 3500.0

    def __init__(self) -> None:
        self.checked = 0
        self.bad = 0
        self.examples: list[str] = []

    def feed(self, row: dict) -> None:
        nb = _raw(row).get("near_beach_drive")
        if not isinstance(nb, dict):
            return
        self.checked += 1
        try:
            dist = float(nb.get("distance_m"))
            cap = float(nb.get("max_m") or 2500.0)
            facing = float(nb.get("ocean_facing_m")) if nb.get("ocean_facing_m") is not None else None
        except (TypeError, ValueError):
            dist, cap, facing = float("inf"), 0.0, None
        if dist > cap or facing is None or facing > self.OCEAN_FACING_MAX_M or nb.get("geo_precise") is False:
            self.bad += 1
            if len(self.examples) < SAMPLE:
                self.examples.append(f"{row.get('county')}|{row.get('parcel_id')}|{dist:.0f}m")

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": "; ".join(self.examples) or f"{self.checked} near-beach flips inside the bar"}


class SosAgentGovernment:
    """A government-owned row (county, city, state ...) whose published raw.sos_agent names an
    entity that is none of the row's own: one LLC's officers as the contact on 120 Lincoln
    county-owned parcels on 10/8. 0 allowed. Other unbound legacy profiles are counted only
    (HANDOFF item 57 left stale owner-change profiles to the owner)."""
    name = "additions-sos-agent-bound"

    def __init__(self) -> None:
        from types import SimpleNamespace
        from foreclosure_scraper import sos_agent_handoff as ho
        self._ns = SimpleNamespace
        self._ho = ho
        self.checked = 0
        self.bad = 0
        self.kept = 0
        self.examples: list[str] = []

    def feed(self, row: dict) -> None:
        prof = _raw(row).get("sos_agent")
        if not isinstance(prof, dict) or not prof.get("legal_name"):
            return
        self.checked += 1
        li = self._ns(owner_name=row.get("owner_name"), defendant=row.get("defendant"), raw=_raw(row))
        if self._ho.profile_bound_to_row(prof, li):
            return
        if self._ho.government_owned(li):
            self.bad += 1
            if len(self.examples) < SAMPLE:
                self.examples.append(f"{row.get('county')}|{row.get('parcel_id')}")
        else:
            self.kept += 1

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": (f"{self.bad} government-owned rows carry another entity's profile"
                           + (": " + "; ".join(self.examples) if self.examples else "")
                           + f"; {self.kept} other unbound legacy profiles (owner policy, item 57)")}


#: Court lanes fed by a filed-date WINDOW (only new filings arrive): a carried row the window no
#: longer reaches is aged by board_persist like a pulled listing (presumed_withdrawn after one run,
#: dropped after FULLRUN_PERSIST_MAX_MISSES). The Charleston Public Index pass moved to a 60-day
#: window on 10/7 (CHARLESTON_PI_LOOKBACK_DAYS): the 1,549 Charleston rows the 10/7 letter search
#: delivered are not re-read by it.
WINDOW_LANE_SOURCES = ("national.sc_public_index", "national.sc_public_index.judgment_lien",
                       "counties_nc.nc_ecourts_lis_pendens.judgment_lien")
WINDOW_AGING_MAX_SHARE = 0.10


class WindowLanesNotAging:
    name = "additions-window-lanes-not-aging"

    def __init__(self) -> None:
        self.checked = 0
        self.aging = 0
        self.by: Counter = Counter()

    def feed(self, row: dict) -> None:
        src = str(row.get("source") or "")
        if src not in WINDOW_LANE_SOURCES:
            return
        if src.startswith("national.sc_public_index") and str(row.get("county") or "") != "Charleston":
            return
        self.checked += 1
        ps = _raw(row).get("pulled_sale")
        if (isinstance(ps, dict) and ps.get("presumed_withdrawn")) or row.get("auction_status") == "presumed_withdrawn":
            self.aging += 1
            self.by[src] += 1

    def finish(self) -> dict:
        cap = int(self.checked * WINDOW_AGING_MAX_SHARE)
        return {"name": self.name, "checked": self.checked, "violations": self.aging,
                "max_violations": cap, "ok": self.aging <= cap,
                "detail": (f"{self.aging} of {self.checked} window-fed court rows are aging out "
                           f"(presumed withdrawn): " + ", ".join(f"{k} {v}" for k, v in self.by.most_common())
                           + "; widen the Mac lane's look-back or re-read open cases")
                if self.aging else f"{self.checked} window-fed court rows, none aging"}


class AliasIsPin:
    """raw.parcel_id_alias whose 'long' side is not a 10-digit NC PIN: a short id mapped to another
    short id, i.e. another property's id (53 Rutherford rows on 10/8; fixed in parcel_alias.build).
    0 allowed."""
    name = "additions-alias-is-pin"

    def __init__(self) -> None:
        self.checked = 0
        self.bad = 0
        self.examples: list[str] = []

    def feed(self, row: dict) -> None:
        pa = _raw(row).get("parcel_id_alias")
        if not isinstance(pa, dict):
            return
        self.checked += 1
        if not re.match(r"^\d{10}$", re.sub(r"[^0-9A-Za-z]", "", str(pa.get("long") or ""))):
            self.bad += 1
            if len(self.examples) < SAMPLE:
                self.examples.append(f"{row.get('county')}|{row.get('source')}|{pa.get('short')}->{pa.get('long')}")

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": "; ".join(self.examples) or f"{self.checked} aliases map to a 10-digit PIN"}


#: chains read on or after this day must carry raw.rod_chain.binding (a2c7f3ad); older carried
#: chains are re-read after FORECLOSURE_ROD_CHAIN_REFRESH_DAYS and are counted, not failed.
CHAIN_BINDING_SINCE = "2026-10-09"


class RodChainBinding:
    """A deed chain read since the binding fix with no binding, or a chain whose binding is
    'contradicted' but whose status still says ok. 0 allowed. Reports the binding mix."""
    name = "additions-rod-chain-binding"

    def __init__(self) -> None:
        self.checked = 0
        self.bad = 0
        self.mix: Counter = Counter()

    def feed(self, row: dict) -> None:
        rc = _raw(row).get("rod_chain")
        if not isinstance(rc, dict) or rc.get("status") not in ("ok", "unbound"):
            return
        self.checked += 1
        b = rc.get("binding") if isinstance(rc.get("binding"), dict) else None
        self.mix[(b or {}).get("status", "none")] += 1
        fetched = _day(rc.get("fetched_at")) or ""
        if (b is None and fetched >= CHAIN_BINDING_SINCE) or \
                (b is not None and b.get("status") == "contradicted" and rc.get("status") == "ok"):
            self.bad += 1

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad,
                "max_violations": 0, "ok": self.bad == 0,
                "detail": "binding " + ", ".join(f"{k} {v}" for k, v in self.mix.most_common())}


def make_checks() -> list:
    floors = [AdditionFloor(a) for a in ADDITIONS]
    return floors + [
        _Static("additions-publish-shape", _publish_shape),
        _Static("additions-profile-flags", _profile_flags),
        _Static("additions-ledger-complete", _ledger_complete),
        HeirRelations(), PrivateBlocks(), RodBindsOwner(), RichlandCounty(), NearBeachBar(),
        SosAgentGovernment(), WindowLanesNotAging(), AliasIsPin(), RodChainBinding(),
    ]


# ------------------------------------------------------------------------------------ measurement
_SAMPLE_FIELDS = ("source", "source_url", "state", "county", "parcel_id", "street_address", "city",
                  "owner_name", "case_number", "listing_type", "sale_date", "first_seen", "last_seen",
                  "opening_bid", "judgment_amount", "plaintiff", "defendant")


def _sample_row(a: Addition, rec: dict) -> dict:
    raw = _raw(rec)
    out = {k: rec.get(k) for k in _SAMPLE_FIELDS if rec.get(k) not in (None, "")}
    keys = set(a.raw_keys) | set(a.publish_keys) | set(a.private_keys)
    if a.pred == "generic_rod":
        keys.add("rod")
    if a.pred == "rod_chain_ok":
        keys.add("rod_chain")
    if a.pred == "richland_matched":
        keys |= {"richland_parcel", "owner_mailing"}
    if a.pred == "heir_published":
        keys |= {"heir_candidates", "heir_candidates_summary"}
    if a.pred == "cache_join":
        keys |= {"owner_mailing", "gis"}
    if a.sources:
        # the source's own block is usually keyed by the slug's last part
        keys.add(str(rec.get("source") or "").split(".")[-1])
    out["raw"] = {k: raw.get(k) for k in sorted(keys) if _nonempty(raw.get(k))}
    return out


def measure(ckpt: Path, samples_out: Optional[Path], json_out: Optional[Path], seed: int = 20261009) -> dict:
    """Stream the RAW checkpoint once: per addition, rows on the raw board, rows on the published
    shape (web_artifact._to_dict), fresh rows, counties, and a 30-row random sample."""
    from foreclosure_scraper.board_parts import iter_gz_rows
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.web_artifact import _to_dict

    rng = random.Random(seed)
    k = 30
    res = {a.id: {"raw_rows": 0, "pub_rows": 0, "days": Counter(), "counties": Counter(),
                  "sources": Counter()} for a in ADDITIONS}
    samples: dict[str, list] = {a.id: [] for a in ADDITIONS}
    board = _Board()
    checks = make_checks()
    bad = 0
    for rec in iter_gz_rows(ckpt / "board.json.gz"):
        board.feed(rec)
        try:
            pub = _to_dict(Listing.model_validate(rec))
        except Exception:  # noqa: BLE001 - counted like checkpoint.load()
            bad += 1
            pub = None
        if pub is not None:
            for c in checks:
                c.feed(pub)
        for a in ADDITIONS:
            if not matches(a, rec):
                continue
            r = res[a.id]
            r["raw_rows"] += 1
            if pub is not None and matches(a, pub):
                r["pub_rows"] += 1
            r["counties"][f"{rec.get('state')}|{rec.get('county')}"] += 1
            r["sources"][str(rec.get("source") or "")] += 1
            if a.fresh_key:
                d = _day(_dig(_raw(rec), a.fresh_key))
                if d:
                    r["days"][d] += 1
            n = r["raw_rows"]
            if len(samples[a.id]) < k:
                samples[a.id].append(_sample_row(a, rec))
            else:
                j = rng.randrange(n)
                if j < k:
                    samples[a.id][j] = _sample_row(a, rec)
    cut = ((date.fromisoformat(board.newest) - timedelta(days=FRESH_DAYS)).isoformat()
           if board.newest else "9999")
    out = {"checkpoint": str(ckpt), "rows": board.rows, "unvalidated": bad, "newest_last_seen": board.newest,
           "additions": {}, "checks": [c.finish() for c in checks]}
    for a in ADDITIONS:
        r = res[a.id]
        out["additions"][a.id] = {
            "raw_rows": r["raw_rows"], "pub_rows": r["pub_rows"],
            "fresh_rows": sum(c for d, c in r["days"].items() if d >= cut) if a.fresh_key else None,
            "counties": len(r["counties"]), "top_counties": r["counties"].most_common(8),
            "sources": r["sources"].most_common(6), "floor": a.floor, "status": a.status}
    if json_out:
        json_out.write_text(json.dumps(out, indent=1, default=str))
    if samples_out:
        if _REPO in samples_out.resolve().parents:
            raise SystemExit("--samples holds names: write it outside the repo")
        samples_out.write_text(json.dumps(samples, indent=1, default=str))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--samples", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    sys.path.insert(0, str(_REPO / "scripts"))
    out = measure(args.checkpoint, args.samples, args.json)
    print(f"rows {out['rows']:,}  newest last_seen {out['newest_last_seen']}")
    print(f"{'addition':42s} {'raw':>8s} {'pub':>8s} {'fresh':>7s} {'cty':>4s} {'floor':>6s}  status")
    for aid, r in out["additions"].items():
        print(f"{aid:42s} {r['raw_rows']:>8,} {r['pub_rows']:>8,} "
              f"{'' if r['fresh_rows'] is None else r['fresh_rows']:>7} {r['counties']:>4} "
              f"{r['floor']:>6,}  {r['status']}")
    for c in out["checks"]:
        if not c["name"].startswith("addition-"):
            print(f"{c['name']:42s} ok={c['ok']} violations={c['violations']}/{c['max_violations']} "
                  f"checked={c['checked']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
