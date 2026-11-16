"""heir_roll, NC (outside Buncombe) + SC: does the county parcel roll STILL title this parcel to a
dead owner's heirs or estate, or has the estate already conveyed it?

THE CLAIM. Two producers feed this verifier the SAME claim shape (raw.heir_estate.owner_of_record +
raw.relationship_signal.keyword == heir_estate_owner_of_record / life_estate_owner_of_record):
counties_nc.nc_heir_estate_parcels reads a county parcel layer (enrichment_owner_mailing.COUNTY_GIS:
10 dedicated NC layers and 8 SC ones) or NC OneMap's statewide parcel layer (the 89 other NC
counties) LIVE. counties_sc.sc_heir_estate_parcel_cache (added 2026-10-19; recognized here
2026-11-16) reads the SAME owner-of-record text for ~19 more SC counties out of parcel_cache
.PARCEL_LAYERS/SC_DUAL_LAYERS' already-downloaded local cache instead of a live query. Both look
for "<NAME> HEIRS", "HEIRS OF <NAME>", "<NAME> ESTATE", "ESTATE OF <NAME>", "<NAME> (EST)" and emit
an estate_lead; scorer signals estate_lead (LIFE_EVENT 20) and probate_deed (20). On the 2026-10-08
pre_publish checkpoint that is 5,720 NC rows (4,266 WARM, 30 HOT) and 538 SC rows, the largest block
of WARM court/estate leads. Nothing re-reads the roll once the row exists, and the row is carried
for months.

THE SOURCE. The SAME layer the row's county was read from, asked for the row's own parcel id
(spec["parcel"]/spec["alt_parcel"], plus NC OneMap's altparno; _pid_variants formats; a returned
record counts only when its parcel id, letters and digits only, equals the row's: a LIKE match on
part of an id is another parcel). For the NC producer this is row.source_url's own layer
(enrichment_owner_mailing.COUNTY_GIS, matched by url). For the SC cache producer it is resolved
from the row's (state, county) against parcel_cache.PARCEL_LAYERS/SC_DUAL_LAYERS directly -- NEVER
from row.source_url: that producer's own source_url (parcel_cache.resolve_layer_cfg()) reads EMPTY
for a DUAL_STATE_COUNTIES name whose real config lives in PARCEL_LAYERS, not SC_DUAL_LAYERS
(Chester; see _sc_cache_cfg()'s own docstring), so a url-based lookup would silently drop that
county's otherwise-real layer. A candidate county whose parcel_cache entry is not a live ArcGIS
/query endpoint at all (Williamsburg's WTH-gis scrape -- parcel_cache._WTH_SOURCED, or any future
lookalike: checked here by the url's own shape, not just that one name) never gets a spec --
"unconfirmed" against a dead endpoint, retried forever, would be worse than "no verifier applies"
here. Plain ArcGIS REST, no key; one or two requests per row.

WHAT "THE ESTATE STILL HOLDS IT" MEANS HERE. The county roll's title wording is the free, public
evidence of an unsettled estate in every one of these counties (the estate FILE is the NC eCourts
Smart Search, CAPTCHA-walled: walls_register card nc_est; SC probate indexes are mostly walled or
offline: docs/county_records). This verifier reads the roll; it does not read a death index (the
Buncombe verifier, probate_heir_buncombe, does both for Buncombe rows, which this one leaves to it).

VERDICTS (core.py's meanings):
  confirmed    the roll today still carries a death word (HEIR, HEIRS, ESTATE, EST, DECEASED) on a
               name sharing a word with the decedent the claim names: roll_still_says_heirs.
  stale        the roll today names an owner with no death word who shares no name word with the
               decedent, the care-of or any co-owner the claim listed: the parcel has been
               conveyed out of the estate (conveyed_out). Where the layer gives a sale date it is
               kept; a sale dated more than a year BEFORE the row was first seen contradicts the
               claim's own reading and is unconfirmed (sale_predates_claim) instead.
  refuted      the claim's own roll string carries no death word at all (the scraper's substring
               match, "...HEIR..." inside a surname) and the roll today carries none either:
               no_death_word_on_roll. The county never titled the parcel to anyone's heirs.
  unconfirmed  the parcel is not on the layer today (parcel_not_found: retired or re-numbered
               parcels are not evidence), the roll now names the decedent's family without a death
               word (titled_to_family: an heir took title; the estate claim is settling, not
               false), the roll names another decedent's heirs (heirs_of_other), an entity owner,
               a layer error (layer_error / fetch_failed, retried in 6 hours).
  wall         never: the layers are open.

GOVERNS (per record): "estate_lead", and "probate_deed" when the row's probate_deed comes from this
same roll (relationship_signal keyword heir_estate_owner_of_record; evidence rel_from_roll): a
deed- or notice-based probate_deed on the same row is another claim and is not touched.

PRIVACY (public ledger): evidence holds the parcel id, the layer host, the category, whether a
death word is on the roll, the sale date and owner INITIALS; never a name. ROW_SUMMARY_EXCLUDE
drops owner_name.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

from ..core import VerificationResult, result

SIGNAL = "heir_roll"
VERSION = "v1"
TTL_DAYS = 30          # a distribution or estate-sale deed reaches the roll within weeks to months
RETRY_DAYS = 7
SOURCE = "county parcel layers + NC OneMap NC1Map_Parcels (ArcGIS REST)"
GOVERNS = ("estate_lead", "probate_deed")
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "layer_error")

HEIR_SOURCE = "counties_nc.nc_heir_estate_parcels"
#: 2026-11-16: the SC parcel_cache-backed sibling producer (module docstring's "THE CLAIM").
#: Its rows carry the identical raw.heir_estate/raw.relationship_signal shape (it imports
#: nc_heir_estate_parcels.py's own classifiers), just a different `source` slug and a layer
#: resolved from parcel_cache's registry instead of enrichment_owner_mailing.COUNTY_GIS.
SC_CACHE_SOURCE = "counties_sc.sc_heir_estate_parcel_cache"
HEIR_SOURCES = (HEIR_SOURCE, SC_CACHE_SOURCE)
ONEMAP_HOST_PART = "NC1Map_Parcels"
#: NC OneMap's sale-date columns (read on the layer's schema; the county layers differ and are not
#: asked for one: an unknown field makes ArcGIS answer 400)
ONEMAP_DATE_FIELDS = ("saledate", "saledatetx")
SALE_BEFORE_CLAIM_DAYS = 365

_DEATH = re.compile(r"\bHEIRS?\b|\bESTATE\b|\bEST\b|\bDECEASED\b|\bDEC'?D\b|\bDECD\b", re.I)
_NAME = __name__.rsplit(".", 1)[-1]


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _layer_url(u: Any) -> str:
    s = str(u or "").strip().rstrip("/")
    s = re.sub(r"/query$", "", s, flags=re.I)
    return s


def _is_query_url(url: Any) -> bool:
    """Does this look like a live ArcGIS /query endpoint, not a bare homepage kept only for
    provenance (parcel_cache._WTH_SOURCED's own shape -- Williamsburg's "url" is its WTH-gis
    viewer's homepage, not a REST service; refresh_county() itself refuses to treat it as one,
    see that function's own comment)? Checked by the url's own shape rather than importing
    that private registry name, so a FUTURE non-ArcGIS parcel_cache entry is caught the same
    way even before anyone adds it to that set."""
    return str(url or "").strip().rstrip("/").lower().endswith("/query")


def _sc_cache_cfg(county: str) -> Optional[dict]:
    """counties_sc.sc_heir_estate_parcel_cache's OWN layer config for `county` -- resolved the
    SAME way that producer's `_candidate_counties()` discovers it (by checking
    parcel_cache.PARCEL_LAYERS and SC_DUAL_LAYERS directly), NEVER via
    parcel_cache.resolve_layer_cfg() (what that producer calls to fill the row's own
    `source_url`). That function's DUAL_STATE_COUNTIES branch reads ONLY SC_DUAL_LAYERS for a
    dual name -- but SC_DUAL_LAYERS carries just "Beaufort" (itself excluded from this
    producer's candidates as already NC-side-live-covered), while Chester, a REAL candidate
    this producer does emit rows for, has its SC config in PARCEL_LAYERS instead. Confirmed
    live 2026-11-16: parcel_cache.resolve_layer_cfg("Chester", "SC") returns None, so the
    producer's own `source_url` for every Chester row is "" -- a url-based lookup here would
    read that as "no layer", silently dropping a county this file's own HEIR_SOURCES allowlist
    is specifically being extended to cover. Returns None for a county with no SC config, no
    owner field mapped, or no live /query endpoint (_is_query_url)."""
    from ... import parcel_cache
    co = (county or "").strip()
    if not co:
        return None
    cfg = parcel_cache.PARCEL_LAYERS.get(co)
    if cfg is None or cfg.get("state") != "SC":
        dual = {k.lower(): k for k in parcel_cache.DUAL_STATE_COUNTIES}.get(co.lower())
        cfg = parcel_cache.SC_DUAL_LAYERS.get(dual) if dual else None
    if not cfg or not (cfg.get("map") or {}).get("owner"):
        return None
    if not _is_query_url(cfg.get("url")):
        return None
    return cfg


def _sc_cache_spec(row: Any) -> Optional[dict]:
    """A heir_roll-shaped layer spec (url/parcel/alt_parcel/owner) built from this producer's
    own parcel_cache registry entry, or None. `owner` is normalised to a list (parcel_cache's
    `map["owner"]` is a bare string on some counties, e.g. Colleton's "OwnerName1", a list on
    others, e.g. Georgetown's ["Owner1","Owner2"]; query_url()/_spec_out_fields() both splat
    spec["owner"], which would iterate a bare string's CHARACTERS instead of field names).
    Only the first two of `id_fields` become parcel/alt_parcel -- the same two-field shape
    find_parcel() already searches for the NC producer; Dorchester is the only candidate with
    a 3rd id_fields entry (PARCELNO), left unsearched (a documented, narrow limitation, not a
    guess at a new field-matching scheme)."""
    cfg = _sc_cache_cfg(str(_get(row, "county") or ""))
    if cfg is None:
        return None
    owner = cfg["map"]["owner"]
    owner = [owner] if isinstance(owner, str) else list(owner or [])
    if not owner:
        return None
    ids = [i for i in (cfg.get("id_fields") or []) if i]
    if not ids:
        return None
    spec = {"url": cfg["url"], "owner": owner, "parcel": ids[0]}
    if len(ids) > 1:
        spec["alt_parcel"] = ids[1]
    where = cfg.get("where")
    if where:
        spec["where_suffix"] = where
    return spec


def layer_spec(row: Any) -> Optional[dict]:
    """The layer spec the row's claim can be re-verified against, or None.

    counties_sc.sc_heir_estate_parcel_cache rows resolve via `_sc_cache_spec` (by state+county,
    against that producer's OWN parcel_cache registry -- see its docstring for why NOT
    row.source_url). Every other HEIR_SOURCES row (counties_nc.nc_heir_estate_parcels) keeps
    the original COUNTY_GIS-by-source_url resolution, unchanged.
    """
    if str(_get(row, "source") or "") == SC_CACHE_SOURCE:
        return _sc_cache_spec(row)
    from ...enrichment_owner_mailing import COUNTY_GIS
    url = _layer_url(_get(row, "source_url"))
    if not url:
        return None
    st = str(_get(row, "state") or "").strip().upper()
    co = str(_get(row, "county") or "").strip()
    if ONEMAP_HOST_PART.lower() in url.lower():
        base = dict(COUNTY_GIS["NC:Cleveland"])          # the NC OneMap spec the scraper uses
        base.setdefault("alt_parcel", "altparno")
        return base
    # the county's own layer; when the scraper has since been repointed (an older source_url,
    # e.g. Polk's), the layer it reads today is the county's roll all the same
    return COUNTY_GIS.get(f"{st}:{co}")


def applies(row: dict) -> bool:
    if str(_get(row, "source") or "") not in HEIR_SOURCES:
        return False
    st = str(_get(row, "state") or "").strip().upper()
    co = str(_get(row, "county") or "").strip().lower()
    if st not in ("NC", "SC") or (st == "NC" and co == "buncombe"):
        return False                  # Buncombe: probate_heir_buncombe (death index + ROD)
    if not str(_get(row, "parcel_id") or "").strip():
        return False
    return layer_spec(row) is not None


# ----------------------------------------------------------------------------------------------
# the claim
# ----------------------------------------------------------------------------------------------

def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", "; ", str(s or ""), flags=re.I)).strip()


def claim_roll(row: Any) -> str:
    """The roll string the claim was built from (the scraper's owner of record)."""
    raw = _raw(row)
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    g = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    return _clean(he.get("owner_of_record") or _get(row, "owner_name") or g.get("owner"))


def _words(s: str) -> set[str]:
    from ...name_normalize import core_tokens
    return {t for t in core_tokens(_DEATH.sub(" ", s)) if len(t) >= 3}


def decedent_words(row: Any) -> set[str]:
    """Name words of the decedent(s) and every co-owner / care-of the claim lists."""
    raw = _raw(row)
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    out: set[str] = set()
    for h in he.get("heir_names") or []:
        if isinstance(h, dict):
            out |= _words(str(h.get("name") or h.get("raw") or ""))
    for s in (he.get("owner_of_record"), he.get("care_of"), _get(row, "owner_name")):
        out |= _words(_clean(s))
    return out


def rel_from_roll(row: Any) -> bool:
    rs = _raw(row).get("relationship_signal")
    return isinstance(rs, dict) and rs.get("keyword") == "heir_estate_owner_of_record"


def priority(row: Any) -> int:
    return 0


# ----------------------------------------------------------------------------------------------
# the layer
# ----------------------------------------------------------------------------------------------

def _norm_pid(v: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()


def _pid_same(a: Any, b: Any) -> bool:
    x, y = _norm_pid(a), _norm_pid(b)
    if not x or not y:
        return False
    if x == y:
        return True
    # a trailing card suffix one side carries ('...000')
    return (x.startswith(y) and set(x[len(y):]) <= {"0"}) or (y.startswith(x) and set(y[len(x):]) <= {"0"})


def query_url(spec: dict, where: str, onemap: bool) -> str:
    from ...enrichment_owner_mailing import _spec_out_fields
    fields = [f for f in _spec_out_fields(spec).split(",") if f]
    for f in [spec.get("parcel"), spec.get("alt_parcel"), *(spec.get("owner") or [])]:
        if f and f not in fields:
            fields.append(f)
    if onemap:
        fields += [f for f in ONEMAP_DATE_FIELDS if f not in fields]
    q = {"where": where, "outFields": ",".join(fields), "returnGeometry": "false",
         "resultRecordCount": "10", "f": "json"}
    return f"{_layer_url(spec['url'])}/query?{urlencode(q)}"


class _LayerError(Exception):
    pass


# ----------------------------------------------------------------------------------------------
# SC cache producer only: the row's own parcel_id is FULLY STRIPPED of punctuation at
# parcel_cache ingest time (parcel_cache._norm_id), but several of these counties' LIVE layers
# store their id field as punctuated TMS-shaped text ("354-12-00-147.000", "0006N-0B-034.00")
# -- a plain `field LIKE '%<stripped id>%'` can never match that (the digits are not
# contiguous in the stored text), which is why these rows would otherwise ALWAYS read
# "parcel_not_found" despite the parcel genuinely being on the layer today (confirmed live
# 2026-11-16: Colleton parcel_id "3541200147" vs. its live PIN "354-12-00-147.000" -- same
# parcel, by owner name too, not just a coincidental digit match). Rather than guess any one
# county's dash convention, this reads the SAME layer's own punctuation pattern off ONE live
# sample of that field (cached per url+field for the run, the same one-schema-probe-per-layer
# shape nc_heir_estate_parcels.py's own `_value_field` already uses) and reinserts it into the
# row's digits. A county whose id field is already plain digits (Berkeley, Sumter, Horry, ...)
# needs no help here -- `_pid_variants`'s existing raw/stripped candidates already match, and
# the probe itself is cheap and cached regardless. A county whose digit COUNT never lands on
# one of the sample's own group boundaries (Aiken's `PARCEL_ASR`, on a row whose id actually
# came from the longer `PARC_NO`; Lancaster's letter-bearing PINs) safely yields no candidate
# at all here -- never a wrong one; find_parcel() just has one fewer thing to try, same as a
# layer this helper does not apply to.
# ----------------------------------------------------------------------------------------------

_SEP_GROUPS_CACHE: dict[tuple[str, str], Optional[list[tuple[int, str]]]] = {}


def _parse_id_groups(sample: str) -> list[tuple[int, str]]:
    """[(digit-run length, the separator text right after it), ...], e.g. "354-12-00-147.000"
    -> [(3,"-"), (2,"-"), (2,"-"), (3,"."), (3,"")]. A letter inside a separator (Lancaster's
    "0006N-0B-034.00") rides along as ordinary separator TEXT -- never reinterpreted as a
    digit run to fill from the row's own (digit-only) parcel_id."""
    return [(len(m.group(1)), m.group(2)) for m in re.finditer(r"(\d+)(\D*)", sample or "")]


def _reseparated(pid: str, groups: list[tuple[int, str]]) -> Optional[str]:
    """`groups`' own separator pattern, reinserted into pid's bare digits, consuming groups
    left to right until pid is exhausted (a sample with a trailing group pid has no digits
    left for -- Colleton's own ".000" card suffix -- is simply never reached, so the result,
    e.g. "354-12-00-147", omits it; that is still a real substring of the live "354-12-00-
    147.000" either way, all a LIKE search needs). None when pid's digit count does not land
    exactly on one of the sample's own group boundaries -- a genuinely different id shape for
    this field/row, never forced into a wrong-length guess."""
    digits = re.sub(r"\D", "", pid or "")
    if not digits:
        return None
    out: list[str] = []
    i = 0
    for n, sep in groups:
        if i >= len(digits):
            break
        if i + n > len(digits):
            return None
        out.append(digits[i:i + n])
        i += n
        if i >= len(digits):
            break
        out.append(sep)
    return "".join(out) if i == len(digits) else None


async def _sample_groups(client, url: str, field: str) -> Optional[list[tuple[int, str]]]:
    """ONE live sample of `field` on this layer, parsed into its own separator groups (cached
    per url+field for the run) -- or None when the probe fails, the layer has no rows, or the
    sampled value carries no punctuation at all (nothing to reinsert; the plain stripped id
    already matches it directly). This probe's own request never touches find_parcel()'s
    asked/errors accounting: a failed probe just means _reseparated() is never tried for this
    field, not a layer error for the row being verified."""
    key = (url, field)
    if key not in _SEP_GROUPS_CACHE:
        groups = None
        try:
            q = urlencode({"where": "1=1", "outFields": field, "resultRecordCount": "1", "f": "json"})
            d = json.loads(await client.get_text(f"{_layer_url(url)}/query?{q}"))
            feats = d.get("features") or [] if isinstance(d, dict) else []
            v = str((feats[0].get("attributes") or {}).get(field) or "") if feats else ""
            if re.search(r"\D", v):
                groups = _parse_id_groups(v)
        except Exception:  # noqa: BLE001 - a failed probe just means no extra candidate
            groups = None
        _SEP_GROUPS_CACHE[key] = groups
    return _SEP_GROUPS_CACHE[key]


async def find_parcel(row: Any, spec: dict, client) -> tuple[Optional[dict], list[str]]:
    """(attributes of the row's own parcel or None, the URLs asked)."""
    from ...enrichment_owner_mailing import _pid_variants
    pid = str(_get(row, "parcel_id") or "").strip()
    onemap = ONEMAP_HOST_PART.lower() in str(spec.get("url") or "").lower()
    cc = ""
    if spec.get("county_field") and _get(row, "county"):
        cc = f" AND UPPER({spec['county_field']})='{str(_get(row, 'county')).strip().upper()}'"
    if spec.get("where_suffix"):
        cc += f" AND {spec['where_suffix']}"
    fields = [f for f in (spec.get("parcel"), spec.get("alt_parcel")) if f]
    variants = _pid_variants(pid)
    # SC cache rows only (see the block comment above): each field gets its OWN candidate
    # list, variants first, plus a reseparated form LAST if that field's own live punctuation
    # pattern yields one. The NC path (every other HEIR_SOURCES row) keeps `variants` shared
    # identically across every field, byte-for-byte the same lists as before this addition.
    cands_by_field: dict[str, list[str]] = {pf: list(variants) for pf in fields}
    if str(_get(row, "source") or "") == SC_CACHE_SOURCE:
        for pf in fields:
            groups = await _sample_groups(client, spec["url"], pf)
            if groups:
                resep = _reseparated(pid, groups)
                if resep and resep not in cands_by_field[pf]:
                    cands_by_field[pf].append(resep)
    max_len = max((len(v) for v in cands_by_field.values()), default=0)
    asked: list[str] = []
    errors = 0
    for i in range(max_len):
        for pf in fields:
            cands = cands_by_field[pf]
            if i >= len(cands):
                continue
            safe = cands[i].replace("'", "''")
            url = query_url(spec, f"{pf} LIKE '%{safe}%'{cc}", onemap)
            asked.append(url)
            try:
                d = json.loads(await client.get_text(url))
            except Exception:  # noqa: BLE001
                errors += 1
                continue
            if not isinstance(d, dict) or d.get("error"):
                errors += 1
                continue
            for f in d.get("features") or []:
                a = (f or {}).get("attributes") or {}
                if any(_pid_same(a.get(x), pid) for x in fields):
                    return a, asked
        if len(asked) >= 4:
            break
    if errors and errors == len(asked):
        raise _LayerError(f"{errors} layer errors")
    return None, asked


def _owner_today(spec: dict, a: dict) -> str:
    parts = []
    for f in spec.get("owner") or []:
        v = _clean(a.get(f))
        if v and v.upper() not in (p.upper() for p in parts):
            parts.append(v)
    return "; ".join(parts)


def _sale_date(a: dict) -> Optional[date]:
    v = a.get("saledate")
    if isinstance(v, (int, float)) and v > 0:
        try:
            return datetime.utcfromtimestamp(v / 1000.0).date()
        except (OverflowError, OSError, ValueError):
            pass
    s = str(a.get("saledatetx") or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%m/%d/%Y %I:%M:%S %p"):
        try:
            d = datetime.strptime(s[:len(fmt) + 6].strip(), fmt).date()
            return d if d.year > 1900 else None
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return d if d.year > 1900 else None
        except ValueError:
            return None
    return None


def _initials(s: str) -> str:
    from ...name_normalize import core_tokens
    return ".".join(t[0] for t in core_tokens(_DEATH.sub(" ", s))[:3])


def governs_for(record: dict) -> tuple[str, ...]:
    ev = (record or {}).get("evidence") or {}
    return ("estate_lead", "probate_deed") if ev.get("rel_from_roll") else ("estate_lead",)


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


def _first_seen(row: Any) -> Optional[date]:
    v = _get(row, "first_seen")
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


async def verify(row: dict, client) -> VerificationResult:
    spec = layer_spec(row)
    pid = str(_get(row, "parcel_id") or "").strip()
    claim = claim_roll(row)
    ev: dict = {"parcel_id": pid, "layer": urlsplit(str((spec or {}).get("url") or "")).hostname,
                "claim_death_word": bool(_DEATH.search(claim)), "rel_from_roll": rel_from_roll(row)}
    if spec is None or not pid:
        ev["reason"] = "no_layer_or_parcel"
        return _res("unconfirmed", ev)
    try:
        a, asked = await find_parcel(row, spec, client)
    except _LayerError as exc:
        ev.update(reason="layer_error", detail=str(exc)[:120])
        return _res("unconfirmed", ev)
    except Exception as exc:  # noqa: BLE001
        ev.update(reason="fetch_failed", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    ev["requests"] = len(asked)
    if a is None:
        ev["reason"] = "parcel_not_found"
        return _res("unconfirmed", ev)
    today = _owner_today(spec, a)
    death_today = bool(_DEATH.search(today))
    sale = _sale_date(a)
    ev.update(roll_death_word_today=death_today, owner_initials_today=_initials(today) or None,
              sale_date_today=sale.isoformat() if sale else None)
    dw = decedent_words(row)
    shared = bool(dw & _words(today))
    ev["shares_name_with_claim"] = shared
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
    from ...name_normalize import is_entity
    if shared:
        ev["reason"] = "titled_to_family"
        return _res("unconfirmed", ev)
    fs = _first_seen(row)
    if sale and fs and (fs - sale).days > SALE_BEFORE_CLAIM_DAYS:
        ev.update(reason="sale_predates_claim", first_seen=fs.isoformat())
        return _res("unconfirmed", ev)
    ev["owner_today_entity"] = is_entity(today)
    ev["reason"] = "conveyed_out"
    return _res("stale", ev)
