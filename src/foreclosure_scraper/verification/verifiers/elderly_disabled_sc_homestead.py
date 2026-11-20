"""elderly_disabled, SC homestead counties (York, Lexington, Spartanburg): does the county's own
CAMA/parcel GIS layer still carry the SC Code 12-37-250 homestead exemption flag (owner age 65+,
totally and permanently disabled, or legally blind -- the first $50,000 of a legal residence's
fair market value excluded) on this parcel?

WHY A SEPARATE MODULE, SAME SIGNAL. verifiers/elderly_disabled.py's own applies() covers Buncombe
NC only ("applies() covers Buncombe NC rows only: the county publishes the exemption code per
parcel and the tax bills per levy year"). scrapers/counties_sc/{york,lexington,spartanburg}_
homestead.py each write the identical claim shape that module's carries_claim() recognizes
(listing_type == elderly_disabled, raw['tax_relief'] = {"kind": "homestead_exemption", "basis":
"sc_homestead_age65_disabled", ...}, raw['gis_exempt'] = {..., "tag": "sc_homestead_exemption"})
for three SC counties the Buncombe module's state/county gate rejects outright -- documented as a
known, deliberate gap in each scraper's own docstring ("even though that verifier's applies() is
Buncombe-only and will not try to verify these rows"). gap_matrix.py's `layer == "verify"` cells
for SC/York, SC/Spartanburg, SC/Lexington under lt_elderly_disabled read exactly the shape its own
big comment at the top of that loop describes for heir_roll.py/HEIR_SOURCE: real hit rows exist
(York 78,965; Spartanburg 29,420; Lexington 28,099, live gap_matrix run 2026-11-19), built=ran, but
no registered verifier's applies() recognized them (v_applies stayed 0 for all three), so the cell
read "built-not-verified (source status unknown)" rather than ever running a check.
verification/registry.py's own contract anticipates exactly this ("Several modules may share a
SIGNAL (one per county/vendor: tax_lien_buncombe, tax_lien_ptscloud...); their applies() must not
overlap") -- this module's applies() (SC + county in COUNTIES) and the Buncombe module's (NC +
Buncombe) are disjoint by construction.

THE CLAIM is the SAME one elderly_disabled.py's Buncombe module checks: "the row's owner has the
exclusion", here read directly off a single boolean-shaped CAMA field rather than Buncombe's
Exempt code + levy-bill history, because none of these three counties' layers expose a comparable
per-year billing trail the way Buncombe's tax site does (each scraper's own docstring already
live-verified the field and its live count; see the modules named below). That makes this
verifier's check simpler by construction: one layer query, one flag, one owner comparison -- no
bill look-back is needed or attempted.

ENDPOINTS (free, anonymous, no auth/CAPTCHA/paywall -- the SAME ones each scraper already queries
to source these rows; see each module's own docstring for the live-verified counts and dates):
  York:        services1.arcgis.com/.../Parcels/FeatureServer/0/query, HOMESTEAD='Y'
               (counties_sc.york_homestead, live-verified 2026-11-11, ~80,611 parcels)
  Lexington:   maps.lex-co.com/.../Property/MapServer/4/query, Homestead='YES'
               (counties_sc.lexington_homestead, live-verified 2026-11-11, ~28,277 parcels)
  Spartanburg: maps.spartanburgcounty.org/.../CAMA_Parcels/FeatureServer/0/query,
               HomesteadNumber='H' (counties_sc.spartanburg_homestead, live-verified 2026-11-16,
               ~31,265 parcels)

WHICH PARCEL. Each scraper writes the SAME county id field it queried by as `parcel_id` (York:
ParcelID, falling back to TAXMAPID when ParcelID is blank; Lexington: TMS / TMS_No_Dash;
Spartanburg: GISParcelNumber / MAPNUMBER -- see each scraper's own two-tier fallback). This
verifier re-queries by the primary id field first, then the fallback field when the primary finds
nothing, the identical order each scraper already uses, so a row sourced on the fallback id is
still found.

VERDICTS:
  confirmed    the layer shows the homestead flag on this parcel today, and the county's owner
               string is the row's owner (or a partial/shared-surname match -- an heir, a spouse;
               the same tolerance elderly_disabled.py's Buncombe module gives a non-strict board
               parcel, since the board's own owner can be a later GIS refresh).
  unconfirmed  the flag is present but the county's owner is clearly a DIFFERENT person
               (`owner_differs_relief_present`: the property fact holds, not for this row's
               owner -- never suppresses, mirrors Buncombe's own `owner_differs` category);
               the parcel could not be found on the layer at all (`parcel_not_in_county_layer`:
               nothing proves the claim never held, only that today's id lookup found nothing --
               a retired/renumbered parcel, same caution as Buncombe's own unconfirmed-not-refuted
               choice for an unreadable parcel); the layer could not be read
               (`layer_unreadable`); or the row names no parcel id (`parcel_unresolvable`).
  stale        the parcel WAS found and the flag is absent today. The claim always comes from a
               producer that read this EXACT field (the bulk scraper itself, or
               enrichment_tax_relief.py's per-lead check of the same county field -- see each
               scraper's own docstring: "no further scoring change needed" because both write the
               identical raw['tax_relief'] shape), so the flag was true when the row was built and
               a parcel found with it absent today is a real change (the exemption was removed, or
               re-applied for under a different parcel after a sale), not a parcel this check
               cannot speak to. `refuted` is deliberately never returned here: unlike Buncombe's
               multi-year bill trail, a single flag check has no way to rule out the flag ever
               having been set on an EARLIER county refresh (no history is queried), so "never on
               record" is not a call this verifier can make -- an absent flag is read as `stale`
               (was true, is not now), consistent with VERDICTS' own "an aged record is handled by
               expires_at, never by rewriting its verdict" -- a false claim would correctly surface
               as `stale` repeatedly, the same scoring effect `refuted` would have (SUPPRESSING).

NOT DONE HERE (deliberately, time-boxed; a later pass's job, not a reason to withhold this one):
voter-status corroborating evidence (Buncombe's own voter check is NC-specific, vt.ncsbe.gov; SC
publishes no comparable open voter-file lookup this pipeline reads today) and an address-parcel /
lien-bill-parcel cross-check (Buncombe's v4 three-parcel judging) -- these three scrapers are
property-keyed bulk sweeps (one parcel = one row, no merge-by-address path feeding them the way
Buncombe's older address-key merge did), so the board parcel IS the row's own source parcel in
the overwhelming case; a future pass can add the same cross-check if live evidence of a mismatch
turns up.

PRIVACY (the ledger is a committed file in a public repo). Evidence keeps the verdict basis, the
county, the parcel id, the flag field name and today's value, and an owner-match CATEGORY (never
the county's owner name). ROW_SUMMARY_EXCLUDE keeps the board's owner_name out of the ledger's row
summaries too.

TTL 60 days (an exemption changes on a death, a sale, or lapses without re-application -- the same
cadence elderly_disabled.py's Buncombe module uses), retry 7.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result
from .tax_lien_buncombe import owner_match

SIGNAL = "elderly_disabled"
VERSION = "v1"
TTL_DAYS = 60
RETRY_DAYS = 7
SOURCE = "county CAMA/parcel GIS: York/Lexington/Spartanburg SC"
GOVERNS = ("elderly_disabled", "senior_exemption")
ROW_SUMMARY_EXCLUDE = ("owner_name",)

_NAME = __name__.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class _County:
    layer_url: str
    id_fields: tuple[str, ...]   # primary first, then fallback(s) -- the scraper's own order
    owner_fields: tuple[str, ...]
    out_fields: str
    flag_field: str
    flag_present: str           # the field's value meaning "homesteaded" (exact string match)


#: counties_sc.{york,lexington,spartanburg}_homestead.py's own QUERY_URL / field names (not
#: imported -- the registry does not pull the scraper stack in; a test pins these equal).
COUNTIES: dict[str, _County] = {
    "york": _County(
        layer_url="https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Parcels/FeatureServer/0/query",
        id_fields=("ParcelID", "TAXMAPID"),
        owner_fields=("Owner1", "Owner2", "Owner3"),
        out_fields="ParcelID,TAXMAPID,Owner1,Owner2,Owner3,HOMESTEAD",
        flag_field="HOMESTEAD", flag_present="Y",
    ),
    "lexington": _County(
        layer_url="https://maps.lex-co.com/agstserver/rest/services/Property/MapServer/4/query",
        id_fields=("TMS", "TMS_No_Dash"),
        owner_fields=("Owner",),
        out_fields="TMS,TMS_No_Dash,Owner,Homestead",
        flag_field="Homestead", flag_present="YES",
    ),
    "spartanburg": _County(
        layer_url="https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query",
        id_fields=("GISParcelNumber", "MAPNUMBER"),
        owner_fields=("OwnerName", "TaxpayerName"),
        out_fields="GISParcelNumber,MAPNUMBER,OwnerName,TaxpayerName,HomesteadNumber",
        flag_field="HomesteadNumber", flag_present="H",
    ),
}


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def carries_claim(row: dict) -> bool:
    if row.get("listing_type") == "elderly_disabled":
        return True
    raw = _raw(row)
    tr = raw.get("tax_relief")
    if isinstance(tr, dict) and tr.get("basis") == "sc_homestead_age65_disabled":
        return True
    ge = raw.get("gis_exempt")
    return isinstance(ge, dict) and ge.get("tag") == "sc_homestead_exemption"


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "SC":
        return False
    return str(row.get("county") or "").strip().lower() in COUNTIES and carries_claim(row)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

def layer_url(cfg: _County, field: str, value: str) -> str:
    return cfg.layer_url + "?" + urlencode({"where": f"{field}='{value}'",
                                            "outFields": cfg.out_fields,
                                            "returnGeometry": "false", "f": "json"})


def parse_features(data: Any, cfg: _County) -> list[dict]:
    """Every parcel the layer's JSON holds (empty when none): {'owner', 'present'}. Raises
    ValueError for an error payload or a response that is not a layer query result."""
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    if data.get("error"):
        raise ValueError(f"layer error: {str(data['error'])[:160]}")
    feats = data.get("features")
    if not isinstance(feats, list):
        raise ValueError("no features array")
    out = []
    for ft in feats:
        a = (ft or {}).get("attributes") or {}
        owner = "; ".join(s for s in (str(a.get(f) or "").strip() for f in cfg.owner_fields) if s) or None
        flag = a.get(cfg.flag_field)
        flag_str = str(flag).strip() if flag is not None else ""
        out.append({"owner": owner, "present": flag_str == cfg.flag_present, "flag_raw": flag_str or None})
    return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, evidence, source=SOURCE, version=VERSION, verifier=_NAME)


async def _query_by_id(client, cfg: _County, pid: str) -> list[dict]:
    """The parcel's features by the primary id field, then the fallback field when the primary
    finds nothing -- the same order each scraper's own two-tier id already uses. A URL a replay
    has no recording for (LookupError) is never retried on the fallback."""
    url = layer_url(cfg, cfg.id_fields[0], pid)
    feats = parse_features(await client.get_json(url), cfg)
    if feats or len(cfg.id_fields) < 2:
        return feats
    return parse_features(await client.get_json(layer_url(cfg, cfg.id_fields[1], pid)), cfg)


async def verify(row: dict, client) -> VerificationResult:
    county = str(row.get("county") or "").strip().lower()
    cfg = COUNTIES.get(county)
    pid = str(row.get("parcel_id") or "").strip()
    ev: dict[str, Any] = {"county": county.title() if cfg else row.get("county")}
    if cfg is None or not pid:
        return _res("unconfirmed", {**ev, "reason": "parcel_unresolvable", "parcel_id": row.get("parcel_id")})
    ev["parcel_id"] = pid
    try:
        feats = await _query_by_id(client, cfg, pid)
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", {**ev, "reason": "layer_unreadable",
                                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    if not feats:
        return _res("unconfirmed", {**ev, "reason": "parcel_not_in_county_layer"})
    f = feats[0]
    ev.update(flag_field=cfg.flag_field, flag_present_today=f["present"])
    om = owner_match(row.get("owner_name"), f["owner"])
    if om is not None:
        ev["owner_match"] = om
    if f["present"]:
        if om == "different":
            ev["reason"] = "owner_differs_relief_present"
            return _res("unconfirmed", ev)
        ev["basis"] = "exemption_on_record"
        return _res("confirmed", ev)
    ev["basis"] = "homestead_flag_cleared"
    return _res("stale", ev)
