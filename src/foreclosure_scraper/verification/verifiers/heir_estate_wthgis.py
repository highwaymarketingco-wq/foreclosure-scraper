"""heir_estate (WTH "tgis" platform), SC: does the legacy ASP.NET GIS viewer at
`<county>sc.wthgis.com` STILL title this parcel to a decedent's heirs, estate or life-estate
holder, re-checked live against the SAME search+detail mechanics
counties_sc.sc_wthgis_heir_estate.py reads at discovery?

WHY A SEPARATE VERIFIER FROM heir_roll.py (2026-11-18, gap_matrix built-not-verified sweep).
heir_roll.py already covers every OTHER heir_estate producer -- nc_heir_estate_parcels.py's live
ArcGIS layers, sc_heir_estate_parcel_cache.py's local parcel_cache read -- but its own
layer_spec()/_sc_cache_cfg() deliberately return None for any county whose parcel_cache url is not
a live ArcGIS /query endpoint (_is_query_url): exactly the WTH tgis platform's own legacy shape
(custom.aspx/getftr.aspx, no REST query at all -- parcel_cache.py's own research note, and this
platform's own _WTHGIS_COUNTIES registry below is not in parcel_cache's PARCEL_LAYERS/SC_DUAL_
LAYERS at all). counties_sc.sc_wthgis_heir_estate.py (round 18/19, 2026-11-17) reads this platform
LIVE for Chesterfield/Dillon/McCormick/Marion -- gap_matrix flags Chesterfield's own slice alone at
579 rows -- but heir_roll's applies() excludes every one of them (confirmed live: none of the 4
carries a parcel_cache entry at all), leaving this producer's rows with no verifier. This module
closes that gap with the SAME platform's own mechanics, not a new layer.

THE SOURCE (plain HTTP, no login/CAPTCHA -- live-confirmed 2026-11-18 against Chesterfield,
matching the producer's own module docstring):
  custom.aspx?DSID=<n>&RequestType=CustomSearchRequest&SearchType=Name&SearchCriteria=<text>|
      a plain SUBSTRING match against the current owner-name field -> {Map Number: FeatureID} for
      every matching parcel (live-confirmed: searching "BLAKENEY" surfaces Map Number
      "001 000 000 046" at FeatureID 68, the same parcel/owner this producer's own sample row names).
  getftr.aspx?D=<n>&F=<FeatureID>&Z=1
      that one parcel's current detail (Owner Name/Name2, field-identical to the producer's own
      capture -- live-confirmed the SAME FeatureID still answers "Blakeney Mavis T Life Estate"
      today).

NO DIRECT PER-PARCEL LOOKUP EXISTS on this platform (unlike heir_roll's ArcGIS /query, which can
ask for a parcel id directly) -- the only live entry point is a name-substring SEARCH, so this
verifier re-finds the row's own Map Number by searching, in order, stopping at the first hit:
  1. the decedent's own longest name word (decedent_words(row)) -- narrow and fast, exactly how a
     person would re-look up this specific parcel;
  2. the SAME two canonical tokens the producer itself searched at discovery (ESTATE, HEIR) --
     broader, catches a parcel whose owner text has since changed enough that the original word no
     longer appears in it but which the roll still flags as some decedent's estate.
A Map Number found under NEITHER search is `unconfirmed` (parcel_not_in_search_results): on a
platform with no direct id lookup, "not found by two name searches" does not prove the parcel is
gone or retitled -- only that these two searches did not surface it today.

VERDICTS (heir_roll.py's own meanings, reused verbatim -- the identical claim, the same platform
family, just a different live entry point):
  confirmed    the roll today still carries a death word (HEIR, HEIRS, ESTATE, EST, DECEASED) on an
               owner sharing a word with the decedent/co-owners the claim named (or the claim
               itself named none to compare against): roll_still_says_heirs.
  stale        the roll today names an owner with NO death word who shares no name word with the
               claim's own decedent/co-owners: conveyed_out.
  refuted      the claim's own roll string carried no death word at all and the roll today carries
               none either: no_death_word_on_roll. Not actually reachable today -- the producer's
               own _classify() requires a death/life-estate word to emit a row at all (module
               docstring's is_life_estate/_is_decedent gate) -- kept for the same structural reason
               tax_lien_polk.py keeps an unreachable branch of its own.
  unconfirmed  neither search finds the Map Number (parcel_not_in_search_results); the FeatureID
               found carries no Map Number at all (dead_feature_id); the fetch failed
               (fetch_failed, retried on the transient cadence).
  wall         never: the platform is open HTTP, no login/CAPTCHA (confirmed live 2026-11-18).

GOVERNS: "estate_lead" only (heir_roll.py's first GOVERNS entry) -- this producer never derives a
separate probate_deed from this same roll (unlike nc_heir_estate_parcels's own rel_from_roll path),
so heir_roll.py's second GOVERNS entry is never claimed here.

PRIVACY (public ledger): evidence holds the Map Number, the county, whether a death word is on the
roll today and whether it still shares a name word with the claim -- never a name.
ROW_SUMMARY_EXCLUDE drops owner_name/defendant.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from ..core import VerificationResult, result

SIGNAL = "heir_roll"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "<county>sc.wthgis.com (WTH tgis legacy GIS viewer)"
GOVERNS = ("estate_lead",)
ROW_SUMMARY_EXCLUDE = ("owner_name", "defendant")
TRANSIENT_REASONS = ("fetch_failed",)

#: the one producer this verifier answers for (module docstring's own HEIR_SOURCES-equivalent)
PRODUCER_SOURCE = "counties_sc.sc_wthgis_heir_estate"
_NAME = __name__.rsplit(".", 1)[-1]
_DEATH = re.compile(r"\bHEIRS?\b|\bESTATE\b|\bEST\b|\bDECEASED\b|\bDEC'?D\b|\bDECD\b", re.I)
#: a sub-account suffix rides as an extra 5th space-separated group on ~15% of this board's own
#: WTH Map Numbers (sc_wthgis_heir_estate's sibling ingest script, _base_mapno's own docstring);
#: re-derived here rather than imported -- that sibling lives in scripts/, a one-off CLI tool, not
#: a package module (sc_wthgis_heir_estate.py's own _field() docstring says exactly this).
_BASE_MAPNO_RE = re.compile(r"^(\d{3} \d{3} \d{3} \d{3})(?:\s+\S+)?$")


def _base_mapno(pid: str) -> str:
    m = _BASE_MAPNO_RE.match((pid or "").strip())
    return m.group(1) if m else (pid or "").strip()


def _wth():
    """counties_sc.sc_wthgis_heir_estate, imported lazily on first use -- the registry imports
    every verifier module at discovery time, and the producer's own module-level imports
    (httpx, nc_heir_estate_parcels's classifiers) need not load in just to answer applies()."""
    from ...scrapers.counties_sc import sc_wthgis_heir_estate as m
    return m


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _block(row: Any) -> Optional[dict]:
    b = _raw(row).get("heir_estate")
    return b if isinstance(b, dict) and b.get("source") == "wthgis_live" else None


def applies(row: dict) -> bool:
    if str(_get(row, "source") or "") != PRODUCER_SOURCE:
        return False
    if str(_get(row, "state") or "").strip().upper() != "SC":
        return False
    county = str(_get(row, "county") or "").replace(" County", "").strip()
    if county not in _wth()._WTHGIS_COUNTIES:
        return False
    if not str(_get(row, "parcel_id") or "").strip():
        return False
    return _block(row) is not None


def _words(s: str) -> set[str]:
    from ...name_normalize import core_tokens
    return {t for t in core_tokens(_DEATH.sub(" ", s or "")) if len(t) >= 3}


def claim_text(row: Any) -> str:
    b = _block(row) or {}
    return str(b.get("owner_of_record") or _get(row, "defendant") or "").strip()


def decedent_words(row: Any) -> set[str]:
    out = _words(claim_text(row))
    for h in (_block(row) or {}).get("heir_names") or []:
        if isinstance(h, dict):
            out |= _words(str(h.get("name") or h.get("raw") or ""))
    return out


def priority(row: Any) -> int:
    return 0


async def _find_feature(row: Any, cfg: dict, client: Any) -> tuple[Optional[int], list[str]]:
    """(this row's own Map Number's current FeatureID, or None; the search URLs tried)."""
    m = _wth()
    pid = str(_get(row, "parcel_id") or "").strip()
    base_pid = _base_mapno(pid)
    dw = sorted(decedent_words(row), key=len, reverse=True)
    terms: list[str] = ([dw[0]] if dw else []) + ["ESTATE", "HEIR"]
    asked: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        url = (cfg["base"] + f"custom.aspx?DSID={cfg['dsid']}&RequestType=CustomSearchRequest"
               f"&SearchType=Name&SearchCriteria={quote(term)}%7C")
        asked.append(url)
        txt = await client.get_text(url, timeout=20.0)
        hits = m._parse_search_hits(txt)
        if pid in hits:
            return hits[pid], asked
        if base_pid != pid and base_pid in hits:
            return hits[base_pid], asked
    return None, asked


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client: Any) -> VerificationResult:
    m = _wth()
    county = str(_get(row, "county") or "").replace(" County", "").strip()
    cfg = m._WTHGIS_COUNTIES.get(county)
    pid = str(_get(row, "parcel_id") or "").strip()
    claim = claim_text(row)
    ev: dict[str, Any] = {"parcel_id": pid, "county": county,
                          "claim_death_word": bool(_DEATH.search(claim))}
    if cfg is None or not pid:
        ev["reason"] = "no_county_cfg_or_parcel"
        return _res("unconfirmed", ev)
    try:
        fid, asked = await _find_feature(row, cfg, client)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        ev.update(reason="fetch_failed", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    ev["requests"] = len(asked)
    if fid is None:
        ev["reason"] = "parcel_not_in_search_results"
        return _res("unconfirmed", ev)
    url = cfg["base"] + f"getftr.aspx?D={cfg['dsid']}&F={fid}&Z=1"
    try:
        txt = await client.get_text(url, timeout=20.0)
    except Exception as exc:  # noqa: BLE001
        ev.update(reason="fetch_failed", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    rec = m._parse_detail(txt, cfg.get("fields"))
    if not rec:
        ev["reason"] = "dead_feature_id"
        return _res("unconfirmed", ev)
    today = " ".join(p for p in (rec.get("owner") or "", rec.get("owner2") or "") if p).strip()
    death_today = bool(_DEATH.search(today))
    dw = decedent_words(row)
    shared = bool(dw & _words(today))
    ev.update(owner_death_word_today=death_today, shares_name_with_claim=shared)
    if not today:
        ev["reason"] = "no_owner_on_roll"
        return _res("unconfirmed", ev)
    if not ev["claim_death_word"] and not death_today:
        ev["reason"] = "no_death_word_on_roll"
        return _res("refuted", ev)
    if death_today:
        if shared or not dw:
            ev["reason"] = "roll_still_says_heirs"
            return _res("confirmed", ev)
        ev["reason"] = "heirs_of_other"
        return _res("unconfirmed", ev)
    if shared:
        ev["reason"] = "titled_to_family"
        return _res("unconfirmed", ev)
    ev["reason"] = "conveyed_out"
    return _res("stale", ev)
