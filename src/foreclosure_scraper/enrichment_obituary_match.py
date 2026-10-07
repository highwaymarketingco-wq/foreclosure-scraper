"""Link an obituary's decedent to a board lead: strict full-name fit, plus county, plus dates.

WHAT IT WRITES. raw['obituary_match'] on a lead:
  {"status": "attached" | "ambiguous",
   "url", "date", "source",                       # the obituary (attached only)
   "name_fit": {"level", "reasons", "owner_reading", "decedent_reading"},
   "county_fit": "...", "date_checks": [...],
   "survivors": [...], "unnamed": [...],          # parsed 'survived by' list (attached only)
   "candidates": [{"url", "date", "level"}],     # what fit (ambiguous only)
   "why_ambiguous": "...",
   "note": "a name fit is not a finding of identity"}

THE NAME RULE (quiet_title.names.death_fit, the attorney's full-name rule, reused not rewritten):
  full            given + middle + surname agree word for word;
  middle_initial  given + surname agree and the middle name agrees as an initial (J / JAMES);
  given_surname   given + surname agree and at least one side prints no middle name (the stated
                  reason is kept with the match).
A different given name, middle name or suffix, or a married woman indexed as 'MRS', is another
person. Roll strings without a comma are read both ways (LAST FIRST and FIRST LAST) because
county rolls use both; a Title Case name is read FIRST ... LAST.

COUNTY. The decedent's residence city (from the obituary text or the feed's own city field) must
lie in the lead's county (three city->county tables, split towns listed both ways). When the
obituary prints no residence, the county of the funeral home or paper that published it stands in,
and the reason says so.

DATES. Checked when the record allows it: an owner birth year on the lead (a jail roster DOB) must
agree with the obituary's birth year (+-1); an elderly exemption on the roll rules out a death
before 62; a recorded sale INTO the owner after the obituary's death date, on a roll that does not
already say heirs/estate, rules the match out. What could not be checked is listed.

ATTACH OR NOT. Exactly one distinct death must fit. Two different obituaries fitting one lead is
ambiguous; one obituary fitting owners whose names disagree with each other is ambiguous for all of
them; and a given_surname fit on a lead with no other sign of death (the roll does not say heirs or
estate, no probate) is recorded as ambiguous, because a common name without a middle name cannot
tell two people apart. Ambiguous matches are recorded and NOT attached: no survivors are copied.

PRIVACY. raw['obituary_match'] carries private people's names (survivors) and is NOT in RAW_KEEP:
it never reaches the published board. enrichment_heir_candidates publishes counts and flags only and
writes the names to the private file under data/heirs/ (heirs_store.py).

No network. Pure function of the rows and the private obituary store.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Optional

import structlog

from .obituary_text import tidy_name
from .quiet_title.names import (
    PersonName,
    SUFFIXES,
    clean,
    death_fit,
    is_entity,
    parse_indexed,
    parse_roll,
    roll_markers,
    split_owners,
)

log = structlog.get_logger()

NOTE = ("A name, county and date fit links this obituary to the owner of record as a candidate. "
        "It is not a finding that the owner is the decedent.")

#: scrapers whose rows ARE obituaries (the decedent is the row's own owner name)
OBITUARY_SOURCES = (
    "public_notices.funeral_home_rss",
    "public_notices.gannett_obituaries",
    "public_notices.obituary_feeds",
    "public_notices.echovita_obituaries",
)

# --------------------------------------------------------------------------- row access


def _get(row: Any, field: str):
    if isinstance(row, dict):
        return row.get(field)
    return getattr(row, field, None)


def _raw(row: Any) -> dict:
    r = row.get("raw") if isinstance(row, dict) else getattr(row, "raw", None)
    return r if isinstance(r, dict) else {}


def _norm_county(c: Optional[str]) -> str:
    return re.sub(r"\s+county$", "", str(c or "").strip(), flags=re.I).lower()


def parse_date(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        from dateutil import parser as dp
        d = dp.parse(s, fuzzy=True)
        return d.replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def iso_date(v: Any) -> Optional[str]:
    d = parse_date(v)
    return d.strftime("%Y-%m-%d") if d else None


# --------------------------------------------------------------------------- city -> county

#: towns that straddle a county line (or whose mail serves two counties): every county counts
_SPLIT_TOWNS: dict[tuple[str, str], tuple[str, ...]] = {
    ("greer", "SC"): ("Greenville", "Spartanburg"),
    ("fountain inn", "SC"): ("Greenville", "Laurens"),
    ("chesnee", "SC"): ("Spartanburg", "Cherokee"),
    ("easley", "SC"): ("Pickens", "Anderson"),
    ("clemson", "SC"): ("Pickens", "Anderson"),
    ("piedmont", "SC"): ("Anderson", "Greenville"),
    ("honea path", "SC"): ("Anderson", "Abbeville"),
    ("ware shoals", "SC"): ("Greenwood", "Laurens", "Abbeville"),
    ("simpsonville", "SC"): ("Greenville",),
    ("kings mountain", "NC"): ("Cleveland", "Gaston"),
    ("arden", "NC"): ("Buncombe", "Henderson"),
    ("fletcher", "NC"): ("Henderson", "Buncombe"),
    ("saluda", "NC"): ("Polk", "Henderson"),
    ("hickory", "NC"): ("Catawba", "Burke", "Caldwell"),
    ("high point", "NC"): ("Guilford", "Davidson", "Randolph", "Forsyth"),
    ("mooresville", "NC"): ("Iredell",),
    ("lake lure", "NC"): ("Rutherford",),
    ("cherryville", "NC"): ("Gaston",),
    ("bostic", "NC"): ("Rutherford",),
    ("ellenboro", "NC"): ("Rutherford",),
    ("mars hill", "NC"): ("Madison",),
    ("leicester", "NC"): ("Buncombe",),
    ("candler", "NC"): ("Buncombe",),
    ("fairview", "NC"): ("Buncombe",),
    ("swannanoa", "NC"): ("Buncombe",),
}


def counties_for_city(city: Optional[str], state: Optional[str]) -> set[str]:
    if not city or not state:
        return set()
    c = re.sub(r"\s+", " ", str(city)).strip().lower()
    st = str(state).strip().upper()
    out: set[str] = set(_SPLIT_TOWNS.get((c, st), ()))
    try:
        from ._upstate_city_to_county import _LOOKUP as up
        v = up.get(c)
        if v and v[1] == st:
            out.add(v[0])
    except Exception:  # noqa: BLE001
        pass
    try:
        from ._coastal_city_to_county import coastal_county_for
        v = coastal_county_for(c, st)
        if v:
            out.add(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        from ._bankruptcy_city_to_county import bankruptcy_county_for
        v = bankruptcy_county_for(c, st)
        if v:
            out.add(v)
    except Exception:  # noqa: BLE001
        pass
    return out


# --------------------------------------------------------------------------- names

_NOISE = re.compile(r"\(\s*HEIRS?\s*\)|\bHEIRS?\s+OF\b|\bHEIRS?\b|\bHRS\b|\bESTATE\s+OF\b|\bEST\s+OF\b|\bESTATE\b|"
                    r"\bDECEASED\b|\bDEC'?D\b|\bDECD\b|\bET\s*AL\b|\bET\s*UX\b|\bET\s*VIR\b|\bLIFE\s+EST(?:ATE)?\b|"
                    r"\bC/O\b|\bUNKNOWN\b|\b\d+/\d+\b")
_PARTICLE_SURNAME = {"VAN", "VON", "DE", "DEL", "DELA", "LA", "LE", "DA", "DI", "MC", "MAC", "ST"}


def obit_person(name: Optional[str]) -> Optional[PersonName]:
    """'Harlan "Buddy" Vickery Pope Jr.' -> PersonName('POPE', ['HARLAN', 'VICKERY'], 'JR')."""
    if not name:
        return None
    nm, _ = tidy_name(str(name))
    if not nm:
        nm = str(name)
    words = [w for w in clean(nm).replace(",", " ").split() if w not in ("MRS", "MR", "MS", "DR", "REV")]
    suf = None
    # a suffix is the LAST word only: 'Harlan V. Pope' has a middle initial V, not 'the fifth'
    if len(words) >= 3 and words[-1] in SUFFIXES:
        suf = words[-1]
        words = words[:-1]
    keep = words
    if len(keep) < 2:
        return None
    last = keep[-1]
    given = keep[:-1]
    # 'Van Horn', 'De La Cruz': a surname particle joins the surname
    while len(given) >= 2 and given[-1] in _PARTICLE_SURNAME:
        last = f"{given[-1]} {last}"
        given = given[:-1]
    return PersonName(last=last, given=given, suffix=suf, raw=str(name))


def owner_readings(owner: Optional[str]) -> list[tuple[PersonName, str]]:
    """Every person reading of an owner-of-record string: (PersonName, how it was read)."""
    if not owner or not str(owner).strip():
        return []
    s = str(owner)
    if is_entity(s) and not roll_markers(s):
        return []
    title_case = bool(re.search(r"[a-z]", s))
    out: list[tuple[PersonName, str]] = []
    for part in split_owners(s):
        if is_entity(part):
            continue
        core = _NOISE.sub(" ", part)
        core = re.sub(r"\s+", " ", core).strip(" ,;&")
        if not core:
            continue
        if "," in core:
            p = parse_indexed(core)
            if p:
                out.append((p, "LAST, FIRST MIDDLE"))
            continue
        orders = ("first_last",) if title_case else ("last_first", "first_last")
        for order in orders:
            p = parse_roll(core, order)
            if p:
                out.append((p, "LAST FIRST MIDDLE" if order == "last_first" else "FIRST MIDDLE LAST"))
    # quiet_title.names reads any 'V' as the suffix 'the fifth'; on a roll a trailing single V is
    # a middle initial far more often ('POPE HARLAN V'), so read it that way here
    fixed = []
    for p, how in out:
        if p.suffix == "V" and str(p.raw or "").upper().rstrip(" .").endswith(" V"):
            p = PersonName(last=p.last, given=p.given + ["V"], suffix=None, mrs=p.mrs, raw=p.raw)
        fixed.append((p, how))
    out = fixed
    # one reading per distinct (last, given, suffix)
    seen, uniq = set(), []
    for p, how in out:
        k = (p.last, tuple(p.given), p.suffix)
        if k not in seen:
            seen.add(k)
            uniq.append((p, how))
    return uniq


_ACCEPT = (
    ("the owner-of-record name gives no middle name", "given_surname"),
    ("the entry gives no middle name", "given_surname"),
    ("neither name has a middle name", "given_surname"),
    ("middle name agrees only as an initial", "middle_initial"),
)
_RANK = {"full": 3, "middle_initial": 2, "given_surname": 1}


def name_level(owner: PersonName, decedent: PersonName) -> tuple[Optional[str], list[str]]:
    """(level, reasons) under the full-name rule, or (None, reasons) when it is another person."""
    fit = death_fit(owner, decedent)
    if fit.verdict == "fit":
        return "full", []
    if fit.verdict != "candidate":
        return None, fit.reasons
    level = "full"
    for r in fit.reasons:
        hit = next((lv for prefix, lv in _ACCEPT if r.startswith(prefix)), None)
        if hit is None:
            return None, fit.reasons
        if _RANK[hit] < _RANK[level]:
            level = hit
    return level, fit.reasons


def _show(p: PersonName) -> str:
    return " ".join(p.given + [p.last] + ([p.suffix] if p.suffix else []))


# --------------------------------------------------------------------------- obituary records


def record_from_row(row: Any) -> Optional[dict]:
    """The obituary record a board row carries (an obituary scraper's own row, or a lead an
    obituary row was merged into), or None."""
    raw = _raw(row)
    ob = raw.get("obituary")
    if not isinstance(ob, dict) or not ob.get("decedent"):
        return None
    priv = raw.get("obituary_private") if isinstance(raw.get("obituary_private"), dict) else {}
    url = ob.get("url") or _get(row, "source_url")
    death = ob.get("death_date") or ob.get("death_date_text") or priv.get("death_date_text")
    if not death and ob.get("cms") == "frazer":
        death = ob.get("title_date")
    return {
        "url": url,
        "source": ob.get("source") or _get(row, "source"),
        "decedent": ob.get("decedent"),
        "state": (ob.get("state") or _get(row, "state") or "").upper() or None,
        "county": ob.get("county") or _get(row, "county"),
        "residence_city": priv.get("residence") or ob.get("deceased_city") or ob.get("residence_city"),
        "age": ob.get("age") or priv.get("age"),
        "birth_date": iso_date(ob.get("birth_date") or priv.get("birth_date_text")),
        "death_date": iso_date(death),
        "published": iso_date(ob.get("pub_date") or ob.get("published")),
        "survivors": priv.get("survivors") or [],
        "unnamed": priv.get("unnamed") or [],
        "predeceased": priv.get("predeceased") or [],
        # None, not False, when unread: the store keeps a True a later unread sighting cannot undo
        "detail_read": True if (ob.get("detail_read") or priv.get("survivors")) else None,
        "county_basis": ob.get("county_basis"),
    }


def is_obituary_row(row: Any) -> bool:
    src = str(_get(row, "source") or "")
    return any(src.startswith(s) for s in OBITUARY_SOURCES)


def county_fit(rec: dict, lead_county: str, lead_state: str) -> tuple[bool, str]:
    lc = _norm_county(lead_county)
    if not lc or (rec.get("state") or "").upper() != (lead_state or "").upper():
        return False, "state differs or the lead has no county"
    city = rec.get("residence_city")
    if city:
        cs = counties_for_city(city, rec.get("state"))
        if cs:
            if lc in {_norm_county(c) for c in cs}:
                return True, f"the obituary's residence ({city}) lies in {lead_county} County"
            return False, f"the obituary's residence ({city}) lies in {', '.join(sorted(cs))} County, not {lead_county}"
    if _norm_county(rec.get("county")) == lc:
        basis = rec.get("county_basis") or "the funeral home or paper that published it"
        why = (f"the obituary prints no residence the city tables know; the county is that of {basis}" if city
               else f"the record prints no residence; the county is that of {basis}")
        return True, why
    return False, f"the obituary's county ({rec.get('county')}) is not {lead_county}"


def _lead_birth_year(raw: dict) -> Optional[int]:
    for blk in ("jail_booking", "owner_phone", "voter", "sc_voter_xref"):
        b = raw.get(blk)
        if not isinstance(b, dict):
            continue
        for k in ("roster_dob", "dob", "birth_date", "date_of_birth"):
            d = parse_date(b.get(k))
            if d:
                return d.year
        for k in ("birth_year",):
            try:
                return int(b.get(k))
            except (TypeError, ValueError):
                continue
    return None


def date_checks(row: Any, rec: dict) -> tuple[bool, list[str]]:
    """(conflict, notes). conflict=True rules the match out."""
    raw = _raw(row)
    notes: list[str] = []
    conflict = False
    by = _lead_birth_year(raw)
    ob_birth = parse_date(rec.get("birth_date"))
    ob_by = ob_birth.year if ob_birth else None
    if ob_by is None and rec.get("age") and rec.get("death_date"):
        dd = parse_date(rec["death_date"])
        if dd:
            ob_by = dd.year - int(rec["age"])
    if by and ob_by:
        if abs(by - ob_by) > 1:
            conflict = True
            notes.append(f"birth year on the lead's record ({by}) differs from the obituary's ({ob_by})")
        else:
            notes.append(f"birth year agrees ({by})")
    else:
        notes.append("birth year not checked: none on the lead's record" if ob_by else
                     "birth year not checked: the obituary gives none")
    ex = raw.get("gis_exempt")
    tag = str((ex or {}).get("tag") or "") if isinstance(ex, dict) else ""
    if "elder" in tag.lower() and rec.get("age"):
        try:
            if int(rec["age"]) < 62:
                conflict = True
                notes.append(f"the roll carries an elderly exemption but the obituary gives age {rec['age']}")
            else:
                notes.append("the roll's elderly exemption agrees with the obituary's age")
        except (TypeError, ValueError):
            pass
    dd = parse_date(rec.get("death_date"))
    owner = str(_get(row, "owner_name") or "")
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    ls = gis.get("last_sale") if isinstance(gis.get("last_sale"), dict) else {}
    sale = parse_date(ls.get("date") or ls.get("sale_date")) if ls else None
    if dd and sale and not roll_markers(owner):
        if sale.date() > dd.date():
            conflict = True
            notes.append(f"the owner's recorded purchase ({sale:%Y-%m-%d}) is after the obituary's death date "
                         f"({dd:%Y-%m-%d})")
        else:
            notes.append("the owner's recorded purchase is before the obituary's death date")
    elif not dd:
        notes.append("death date not checked against the record: the obituary gives none")
    return conflict, notes


def _same_death(a: dict, b: dict) -> bool:
    """Two records are one death: same surname and given name, middle names that do not conflict
    (QUIMBY / Q), and the same death date; without a date on both, the names must be identical."""
    from .quiet_title.names import name_compat
    pa, pb = obit_person(a.get("decedent")), obit_person(b.get("decedent"))
    if not pa or not pb:
        return str(a.get("decedent")).upper() == str(b.get("decedent")).upper()
    if pa.last != pb.last or pa.first != pb.first or name_compat(pa, pb) is None:
        return False
    da, db = a.get("death_date"), b.get("death_date")
    if da and db:
        return da == db
    return pa.given == pb.given and pa.suffix == pb.suffix


def _distinct_deaths(recs: list[dict]) -> list[list[dict]]:
    """Group records that are the same death (_same_death)."""
    groups: list[list[dict]] = []
    for r in recs:
        for g in groups:
            if any(_same_death(r, x) for x in g):
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def death_signal_on_roll(row: Any) -> bool:
    """The record already says the owner died: heirs/estate wording on the roll or a probate block."""
    raw = _raw(row)
    owners = [_get(row, "owner_name"), (raw.get("gis") or {}).get("owner") if isinstance(raw.get("gis"), dict) else None]
    he = raw.get("heir_estate")
    if isinstance(he, dict):
        owners.append(he.get("owner_of_record"))
    if any(roll_markers(o) for o in owners if o):
        return True
    if str(_get(row, "listing_type") or "") in ("probate_notice", "ListingType.PROBATE_NOTICE"):
        return True
    for k in ("sc_probate_notice", "mcdowell_probate", "heir_naming_publication"):
        if raw.get(k):
            return True
    try:
        from .signal_freshness import has_real_probate
        if has_real_probate(raw.get("probate")):
            return True
    except Exception:  # noqa: BLE001
        pass
    sp = raw.get("sc_probate_net")
    return isinstance(sp, dict) and sp.get("record_kind") == "probate"


def _lead_owner_strings(row: Any) -> list[str]:
    raw = _raw(row)
    out: list[str] = []
    for s in (_get(row, "owner_name"), (raw.get("gis") or {}).get("owner") if isinstance(raw.get("gis"), dict) else None):
        if s and s not in out:
            out.append(str(s))
    he = raw.get("heir_estate")
    if isinstance(he, dict):
        for h in he.get("heir_names") or []:
            if isinstance(h, dict) and h.get("role") in ("heir", "estate") and h.get("name"):
                if h["name"] not in out:
                    out.append(str(h["name"]))
    for k in ("probate", "sc_probate_notice"):
        b = raw.get(k)
        if isinstance(b, dict):
            nm = b.get("decedent") or b.get("estate")
            if nm and str(nm) not in out:
                out.append(str(nm))
    return out


# --------------------------------------------------------------------------- the match


class ObituaryIndex:
    """surname -> [(record, PersonName)] over every obituary record."""

    def __init__(self, records: Iterable[dict]) -> None:
        self.by_last: dict[str, list[tuple[dict, PersonName]]] = {}
        self.n = 0
        for r in records:
            p = obit_person(r.get("decedent"))
            if not p or not r.get("state"):
                continue
            self.by_last.setdefault(p.last, []).append((r, p))
            self.n += 1

    def fits(self, row: Any) -> list[dict]:
        state = str(_get(row, "state") or "").upper()
        county = _get(row, "county") or ""
        if not state or not county:
            return []
        out: list[dict] = []
        for owner_s in _lead_owner_strings(row):
            for reading, how in owner_readings(owner_s):
                for rec, dp in self.by_last.get(reading.last, []):
                    if rec.get("state") != state:
                        continue
                    level, reasons = name_level(reading, dp)
                    if not level:
                        continue
                    ok, cwhy = county_fit(rec, county, state)
                    if not ok:
                        continue
                    conflict, dnotes = date_checks(row, rec)
                    if conflict:
                        continue
                    out.append({"rec": rec, "level": level, "reasons": reasons,
                                "owner_reading": f"{_show(reading)} (read as {how})",
                                "decedent_reading": _show(dp), "county_fit": cwhy, "date_checks": dnotes,
                                "owner_key": (reading.last, tuple(reading.given), reading.suffix)})
        # best level per obituary url
        best: dict[str, dict] = {}
        for f in out:
            u = f["rec"]["url"]
            if u not in best or _RANK[f["level"]] > _RANK[best[u]["level"]]:
                best[u] = f
        return list(best.values())


def _merged_survivors(fits: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Survivors from every record of the one death (an obituary and a memorial of the same
    person), each tagged with the record it came from; one entry per (name, relation)."""
    surv, unnamed, urls, seen = [], [], [], set()
    for f in sorted(fits, key=lambda x: -_RANK[x["level"]]):
        rec = f["rec"]
        urls.append(rec.get("url"))
        for p in rec.get("survivors") or []:
            k = (str(p.get("name", "")).lower(), p.get("relation"))
            if k in seen:
                continue
            seen.add(k)
            surv.append({**p, "source_url": rec.get("url"),
                         "source_date": rec.get("death_date") or rec.get("published")})
        unnamed += rec.get("unnamed") or []
    return surv, unnamed, urls


def _attached(f: dict, group: Optional[list[dict]] = None) -> dict:
    rec = f["rec"]
    surv, unnamed, urls = _merged_survivors(group or [f])
    return {
        "status": "attached",
        "url": rec.get("url"),
        "date": rec.get("death_date") or rec.get("published"),
        "source": rec.get("source"),
        "name_fit": {"level": f["level"], "reasons": f["reasons"], "owner_reading": f["owner_reading"],
                     "decedent_reading": f["decedent_reading"]},
        "county_fit": f["county_fit"],
        "date_checks": f["date_checks"],
        "survivors": surv,
        "unnamed": unnamed,
        "also_found_in": [u for u in urls if u and u != rec.get("url")],
        "note": NOTE,
    }


def _ambiguous(fits: list[dict], why: str) -> dict:
    return {
        "status": "ambiguous",
        "why_ambiguous": why,
        "candidates": [{"url": f["rec"].get("url"), "date": f["rec"].get("death_date") or f["rec"].get("published"),
                        "level": f["level"], "name_fit_reasons": f["reasons"], "county_fit": f["county_fit"]}
                       for f in fits][:10],
        "note": "Recorded, not attached: more than one reading fits, so no survivors are copied. " + NOTE,
    }


def _incompatible(keys: set) -> bool:
    from .quiet_title.names import name_compat
    people = [PersonName(last=k[0], given=list(k[1]), suffix=k[2]) for k in keys]
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            if a.last == b.last and name_compat(a, b) is None:
                return True
    return False


def match_rows(rows: list[Any], records: Iterable[dict]) -> dict:
    """Set raw['obituary_match'] on every lead an obituary fits. Returns counts."""
    idx = ObituaryIndex(records)
    stats = {"obituaries_indexed": idx.n, "leads_checked": 0, "attached": 0, "ambiguous": 0}
    if not idx.n:
        return stats
    per_row: list[tuple[Any, list[dict]]] = []
    obit_owner_keys: dict[str, set] = {}
    for row in rows:
        raw = _raw(row)
        if not isinstance(raw, dict):
            continue
        raw.pop("obituary_match", None)
        if is_obituary_row(row):
            continue
        stats["leads_checked"] += 1
        fits = idx.fits(row)
        if not fits:
            continue
        per_row.append((row, fits))
        for f in fits:
            obit_owner_keys.setdefault(f["rec"]["url"], set()).add(f["owner_key"])
    for row, fits in per_row:
        raw = _raw(row)
        groups = _distinct_deaths([f["rec"] for f in fits])
        if len(groups) > 1:
            raw["obituary_match"] = _ambiguous(fits, f"{len(groups)} different obituaries fit this owner's name")
            stats["ambiguous"] += 1
            continue
        best = max(fits, key=lambda f: _RANK[f["level"]])
        # one obituary fitting owners whose names disagree with each other (it prints no middle
        # name; the owners carry different ones) cannot be all of them
        keys = set().union(*(obit_owner_keys.get(f["rec"]["url"], set()) for f in fits))
        if _incompatible(keys):
            raw["obituary_match"] = _ambiguous(fits, "this obituary fits owners in the county whose names "
                                                     "disagree with each other (different middle names)")
            stats["ambiguous"] += 1
            continue
        if best["level"] == "given_surname" and not death_signal_on_roll(row):
            raw["obituary_match"] = _ambiguous(
                fits, "given name and surname fit without a middle name, and nothing else on the record says "
                      "the owner died")
            stats["ambiguous"] += 1
            continue
        raw["obituary_match"] = _attached(best, fits)
        stats["attached"] += 1
    return stats


def harvest_records(rows: Iterable[Any], store) -> int:
    """Copy every obituary a row carries into the private store. Returns how many were new or
    changed."""
    n = 0
    for row in rows:
        rec = record_from_row(row)
        if rec and store.upsert(rec):
            n += 1
    return n


def enrich_obituary_match(listings: list, store=None) -> dict:
    """Pipeline entry: harvest this run's obituary rows into the private store, then match every
    lead against everything in the store. Env OBITUARY_MATCH=0 turns it off."""
    import os
    if os.environ.get("OBITUARY_MATCH", "1") == "0":
        return {"skipped": "OBITUARY_MATCH=0"}
    from .heirs_store import ObituaryStore
    st = store or ObituaryStore().load()
    added = harvest_records(listings, st)
    try:
        st.save()
    except OSError as exc:
        log.warning("obituary_match.store_save_failed", error=str(exc)[:200])
    stats = match_rows(listings, st.values())
    stats["store_size"] = len(st)
    stats["store_added"] = added
    log.info("obituary_match.done", **stats)
    return stats
