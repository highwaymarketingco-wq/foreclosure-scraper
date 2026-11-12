"""The attorney's quiet-title intake list per lead (lane C of call_ready.py), each item sourced AND dated.

Stephen (the attorney) asked for, per property, before he starts a quiet-title action:
  1. the tax parcel number;
  2. the legal description off the MOST RECENT deed, with that deed's references;
  3. the deed chain (a couple of deeds back);
  4. the taxpayer of record;
  5. the possible heirs, with their relation to the owner;
  6. which records were checked: register of deeds, tax, probate (estate files), obituaries.

ITEM STATUS (items(row) -> {item: {status, on, source, why}})
  sourced   a record on the row supplies it, with the date it was read or recorded (`on`) and where
            from (`source`: a slug or host, never a name). Only `sourced` counts toward a complete list.
  missing   a script could supply it but has not (not run yet, not wired, nothing found)
  walled    a person has to pull it: the county's site for it is behind a CAPTCHA, a login, a
            payment or is not online (docs/county_records/county_records_matrix.json; the owner's
            steps are in docs/walls_register.json)
  n/a       does not apply (heirs on a row with no death on any record)

raw['deed_latest'] (written by stamp_deed_latest from a register chain BOUND to the row's own parcel)
  {v, state, county, parcel_id, doc_id, book, page, instrument_no, recorded, type, grantors, grantees,
   legal_description, legal_description_source, source_url, platform, fetched_at, bound, bound_on}
  `legal_description` is the register index's description of the instrument (the brief legal a
  register's name index shows: lot, subdivision, acreage, township); the full metes-and-bounds
  text is printed only in the deed image, which no script here reads (images are paywalled or
  behind a bot check in the counties checked; rod/doc_images.py). `bound` says how the deed was
  tied to the parcel: 'book_page' (the county parcel record cites this deed's book and page) or
  'sale_date' (recorded within 31 days of the parcel's last sale on the county record). A chain
  found by the owner's NAME only is never written here.

Pure: no network, no file writes. stamp_deed_latest() mutates rows in place (board dicts or
models.Listing) and never drops a row.
"""
from __future__ import annotations

import re
from functools import lru_cache
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

VERSION = 1

ITEMS = ("parcel", "legal_description", "deed_chain", "taxpayer", "heirs",
         "rod_checked", "tax_checked", "probate_checked", "obituaries_checked")
LABELS = {"parcel": "Parcel number", "legal_description": "Legal description off the latest deed",
          "deed_chain": "Deed chain", "taxpayer": "Taxpayer of record", "heirs": "Possible heirs (with relation)",
          "rod_checked": "Records checked: register of deeds", "tax_checked": "Records checked: tax",
          "probate_checked": "Records checked: probate (estate files)",
          "obituaries_checked": "Records checked: obituaries"}

#: chain bindings that tie a register chain to the row's own parcel
BOUND = frozenset({"book_page", "sale_date"})
#: a latest deed recorded this many days before the parcel's last sale on the county record is stale
STALE_DAYS = 31
#: register access words in the county matrix a person has to get past (not a script)
_PERSON_ACCESS = frozenset({"captcha", "login", "payment", "blocked", "unreachable", "paywall", "account"})


# ---------------------------------------------------------------------------------------------
# small helpers (dict rows and models.Listing alike)
# ---------------------------------------------------------------------------------------------

def _g(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _g(row, "raw")
    return r if isinstance(r, dict) else {}


def to_date(v: Any) -> Optional[date]:
    from .signal_freshness import to_date as _td
    try:
        return _td(v)
    except Exception:  # noqa: BLE001
        return None


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _host(url: Any) -> str:
    m = re.match(r"^\s*https?://([^/\s]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def _record(raw: dict, signal: str) -> Optional[dict]:
    from .verification.core import records_of
    for r in records_of(raw):
        if r.get("signal") == signal:
            return r
    return None


def _z(s: Any) -> str:
    """A book or page number compared without zero padding or letters' case: '000123' -> '123'."""
    t = re.sub(r"[^0-9A-Za-z]", "", str(s or "")).upper().lstrip("0")
    return t


def _src(status: str, on: Optional[str] = None, source: str = "", why: str = "") -> dict:
    return {"status": status, "on": on, "source": source, "why": why}


# ---------------------------------------------------------------------------------------------
# where a person is needed (the county records matrix)
# ---------------------------------------------------------------------------------------------

def county_access(county: Any, state: Any) -> dict:
    return dict(_county_access(re.sub(r"\s+county$", "", str(county or "").strip().lower()),
                               str(state or "").upper().strip()))


@lru_cache(maxsize=512)
def _county_access(county: str, state: str) -> tuple:
    """{rod, probate, tax}: 'script' | 'person' | 'unknown' for the county, from the matrix.
    rod is 'script' when a registered platform adapter reads the county's register by plain HTTP
    (enrichment_generic_rod ROD_CONFIG / CHAIN_ONLY_CONFIG; the headless-browser registers count
    as script too, they are credential-free)."""
    st = str(state or "").upper().strip()
    out = {"rod": "unknown", "probate": "unknown", "tax": "unknown"}
    try:
        from .quiet_title.county_records import county_record
        rec = county_record(str(county or ""), st) or {}
    except Exception:  # noqa: BLE001
        rec = {}
    if register_adapter(county, st):
        out["rod"] = "script"
    else:
        acc = str(((rec.get("rod") or {}).get("access")) or "").lower()
        out["rod"] = "person" if acc in _PERSON_ACCESS or not acc else "unknown"
    pb = rec.get("probate") or {}
    acc = str(pb.get("access") or "").lower()
    if st == "NC":
        out["probate"] = "person"          # NC estates: eCourts behind a CAPTCHA (every county)
    elif acc in _PERSON_ACCESS or (not acc and str(pb.get("free_search") or "").lower() in ("no", "")):
        out["probate"] = "person"
    else:
        out["probate"] = "unknown"         # an open index nobody reads by script yet
    tacc = str(((rec.get("tax") or {}).get("access")) or "").lower()
    out["tax"] = "person" if tacc in _PERSON_ACCESS else ("script" if tacc else "unknown")
    return tuple(out.items())


def register_adapter(county: Any, state: Any) -> Optional[str]:
    """The register platform module that can read this county's chain, or None."""
    try:
        from .enrichment_generic_rod import CHAIN_ONLY_CONFIG, RENDER_ROD_CONFIG, ROD_CONFIG
    except Exception:  # noqa: BLE001
        return None
    st = str(state or "").upper().strip()
    c = re.sub(r"\s+county$", "", str(county or "").strip().lower())
    for reg in (CHAIN_ONLY_CONFIG, ROD_CONFIG, RENDER_ROD_CONFIG):
        for (s, name), e in reg.items():
            if s == st and name.lower() == c and e[0] not in ("cott", "kofile"):   # lien-only modules
                return e[0]
    return None


# ---------------------------------------------------------------------------------------------
# the latest deed, bound to the parcel
# ---------------------------------------------------------------------------------------------

def county_deed_ref(row: Any) -> dict:
    """The county parcel record's own latest-sale facts on the row: {date, book, page, source}, from
    raw['gis']['last_sale'] completed by raw['county_deed_ref'] (county_deed_ref.py)."""
    raw = _raw(row)
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    ls = gis.get("last_sale") if isinstance(gis.get("last_sale"), dict) else {}
    out = {"date": ls.get("date") or None, "book": ls.get("book") or ls.get("deed_book") or None,
           "page": ls.get("page") or ls.get("deed_page") or None, "source": "gis" if ls else None}
    cdr = raw.get("county_deed_ref") if isinstance(raw.get("county_deed_ref"), dict) else {}
    if cdr and not (out["book"] and out["page"]) and cdr.get("book") and cdr.get("page"):
        # the parcel layer's deed reference (county_deed_ref.py) and its own date go together
        out = {"date": cdr.get("date") or out["date"], "book": cdr["book"], "page": cdr["page"],
               "source": cdr.get("source") or "county_deed_ref"}
    elif cdr and not out["date"] and cdr.get("date"):
        out["date"], out["source"] = cdr["date"], cdr.get("source") or "county_deed_ref"
    return out


def same_book_page(a_book: Any, a_page: Any, b_book: Any, b_page: Any) -> Optional[bool]:
    """True when both carry a book and a page and they agree; False when both do and differ; None
    when either side lacks one."""
    if not (_z(a_book) and _z(a_page) and _z(b_book) and _z(b_page)):
        return None
    return _z(a_book) == _z(b_book) and _z(a_page) == _z(b_page)


def deed_latest_from_chain(row: Any, chain: dict) -> Optional[dict]:
    """raw['deed_latest'] from a register chain whose binding ties it to the row's parcel, else None."""
    if not isinstance(chain, dict) or chain.get("status") not in ("ok", "partial"):
        return None
    b = chain.get("binding") if isinstance(chain.get("binding"), dict) else {}
    if b.get("status") not in BOUND:
        return None
    ld = chain.get("last_deed") if isinstance(chain.get("last_deed"), dict) else None
    if not ld or not (ld.get("recorded") and (ld.get("book") or ld.get("instrument_no"))):
        return None
    book, page, inst = ld.get("book"), ld.get("page"), ld.get("instrument_no")
    doc_id = str(inst).strip() if inst else f"{book}/{page}" if page else str(book)
    desc = str(ld.get("description") or "").strip() or None
    return {"v": VERSION, "state": chain.get("state") or _g(row, "state"),
            "county": chain.get("county") or _g(row, "county"),
            "parcel_id": _g(row, "parcel_id"), "doc_id": doc_id, "book": book, "page": page,
            "instrument_no": inst, "recorded": ld.get("recorded"), "type": ld.get("type") or ld.get("kind"),
            "grantors": list(ld.get("grantors") or [])[:6], "grantees": list(ld.get("grantees") or [])[:6],
            "legal_description": desc, "legal_description_source": "register_index" if desc else None,
            "source_url": chain.get("source_url"), "platform": chain.get("platform"),
            "fetched_at": chain.get("fetched_at"), "bound": b.get("status"),
            "bound_on": b.get("parcel_last_sale")}


def deed_latest_stale(row: Any, dl: dict) -> bool:
    """The county record shows a sale more than STALE_DAYS after the deed: it is not the latest."""
    sale = to_date(county_deed_ref(row).get("date"))
    rec = to_date((dl or {}).get("recorded"))
    if not sale or not rec:
        return False
    s = str(county_deed_ref(row).get("date") or "")
    if re.fullmatch(r"\d{4}(-01-01|0101)?", s.strip()):       # a year only
        return sale.year > rec.year
    return (sale - rec).days > STALE_DAYS


def deed_latest_ok(row: Any) -> Optional[dict]:
    """The row's raw['deed_latest'] when it is bound to this row's parcel and not stale, else None."""
    from .tax_binding import norm_id
    dl = _raw(row).get("deed_latest")
    if not isinstance(dl, dict) or dl.get("bound") not in BOUND or not dl.get("recorded"):
        return None
    if norm_id(dl.get("parcel_id")) != norm_id(_g(row, "parcel_id")):
        return None
    if deed_latest_stale(row, dl):
        return None
    return dl


def stamp_deed_latest(listings: Iterable[Any], now: Optional[datetime] = None) -> dict:
    """For every row with a register chain: give a chain stamped before the parcel binding existed
    its binding (from the row's own county record, no network), turn a contradicted one to
    'unbound', and write raw['deed_latest'] from a bound chain (or remove one that no longer
    holds: another parcel's, stale, or from a chain now unbound)."""
    from .enrichment_rod_chain import bind_chain
    now = now or datetime.now(timezone.utc)
    st = {"chains": 0, "rebound": 0, "unbound": 0, "bound": 0, "deed_latest": 0, "removed": 0}
    for li in listings:
        raw = _raw(li)
        rc = raw.get("rod_chain")
        if isinstance(rc, dict) and rc.get("status") in ("ok", "partial", "unbound"):
            st["chains"] += 1
            if not isinstance(rc.get("binding"), dict) and rc.get("status") in ("ok", "partial"):
                rc["binding"] = bind_chain(li, rc, now)
                st["rebound"] += 1
                if rc["binding"].get("status") == "contradicted":
                    rc["status"] = "unbound"
            if rc.get("status") == "unbound":
                st["unbound"] += 1
            dl = deed_latest_from_chain(li, rc)
            if dl:
                st["bound"] += 1
                raw["deed_latest"] = dl
        if "deed_latest" in raw:
            if deed_latest_ok(li):
                st["deed_latest"] += 1
            else:
                raw.pop("deed_latest", None)
                st["removed"] += 1
    return st


# ---------------------------------------------------------------------------------------------
# the items
# ---------------------------------------------------------------------------------------------

def _bound_chain(raw: dict) -> Optional[dict]:
    rc = raw.get("rod_chain")
    if isinstance(rc, dict) and rc.get("status") in ("ok", "partial") \
            and (rc.get("binding") or {}).get("status") in BOUND and rc.get("last_deed"):
        return rc
    return None


def items(row: Any, today: Optional[date] = None) -> dict:
    """{item: {status, on, source, why}} for the attorney's list (see the module doc)."""
    from .block_binding import row_owner_strength
    from .enrichment_heir_candidates import PUBLISHABLE_HEIR_RELATIONS
    from .signal_freshness import has_real_probate
    from .tax_binding import norm_id, usable_id
    raw = _raw(row)
    county, state = _g(row, "county"), _g(row, "state")
    acc = county_access(county, state)
    seen = _iso(to_date(_g(row, "last_seen")) or to_date(_g(row, "first_seen")))
    out: dict = {}

    # 1. parcel number: the row's own usable parcel id, read on the row's last sighting
    pid = _g(row, "parcel_id")
    if pid and usable_id(norm_id(pid)) and seen:
        gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
        out["parcel"] = _src("sourced", seen, str(gis.get("source") or _g(row, "source") or ""))
    else:
        out["parcel"] = _src("missing", why="no usable parcel id on the row")

    # 2. legal description off the latest deed: raw['deed_latest'], bound to this parcel, with text
    dl = deed_latest_ok(row)
    if dl and dl.get("legal_description") and to_date(dl.get("fetched_at")):
        out["legal_description"] = _src("sourced", _iso(to_date(dl["fetched_at"])),
                                        str(dl.get("platform") or _host(dl.get("source_url"))),
                                        f"latest deed {dl.get('doc_id')} recorded {dl.get('recorded')}; "
                                        f"the register index's description")
    elif dl:
        out["legal_description"] = _src("missing", why="the latest deed is bound but its index shows no description; "
                                                       "the deed image has it")
    elif acc["rod"] == "person":
        out["legal_description"] = _src("walled", why="the county register is not readable by a script")
    else:
        out["legal_description"] = _src("missing", why="no register chain bound to this parcel yet")

    # 3. deed chain: a bound register chain with an earlier conveyance, or the death-index/deeds check
    rc = _bound_chain(raw)
    ph = _record(raw, "probate_heir")
    ph_chain = bool(((((ph or {}).get("evidence") or {}).get("transfer") or {}).get("chain") or {}).get("complete"))
    if rc and rc.get("prior_instruments") and to_date(rc.get("fetched_at")):
        out["deed_chain"] = _src("sourced", _iso(to_date(rc["fetched_at"])), str(rc.get("platform") or ""),
                                 f"{1 + len(rc['prior_instruments'])} deeds")
    elif ph_chain and to_date(ph.get("checked_at")):
        out["deed_chain"] = _src("sourced", _iso(to_date(ph["checked_at"])), str(ph.get("verifier") or ""))
    elif rc:
        out["deed_chain"] = _src("missing", why="only the latest deed was found; the walk back stopped: "
                                                + str(rc.get("chain_stopped") or "no earlier deed in the index"))
    elif acc["rod"] == "person":
        out["deed_chain"] = _src("walled", why="the county register is not readable by a script")
    else:
        out["deed_chain"] = _src("missing", why="no register chain bound to this parcel yet")

    # 4. taxpayer of record: the tax site matched the owner, or the county roll on the row agrees
    tl = _record(raw, "tax_lien")
    tev = (tl or {}).get("evidence") if isinstance((tl or {}).get("evidence"), dict) else {}
    try:
        strength = row_owner_strength(row)
    except Exception:  # noqa: BLE001
        strength = "none"
    if tl and str(tev.get("owner_match") or "") == "same" and to_date(tl.get("checked_at")):
        out["taxpayer"] = _src("sourced", _iso(to_date(tl["checked_at"])), str(tl.get("source") or tl.get("verifier") or ""))
    elif strength == "roll" and seen:
        out["taxpayer"] = _src("sourced", seen, "county roll on the row")
    else:
        out["taxpayer"] = _src("missing", why={"contradicted": "the county roll names someone else",
                                               "unbacked": "no county roll owner on the row",
                                               "none": "no owner on the row"}.get(strength, "not confirmed"))

    # 5. possible heirs with a stated relation (a personal representative counts)
    hdates: list[date] = []
    hsrc = ""
    for key in ("probate", "sc_probate_notice"):
        b = raw.get(key)
        if isinstance(b, dict) and (key != "probate" or has_real_probate(b)) \
                and str(b.get("personal_representative") or "").strip():
            d = to_date(_g(row, "first_seen"))
            if d:
                hdates.append(d)
                hsrc = hsrc or key
    for c in raw.get("heir_candidates") or []:
        if isinstance(c, dict) and str(c.get("relation") or "").strip().lower() in PUBLISHABLE_HEIR_RELATIONS:
            d = to_date(c.get("source_date"))
            if d:
                hdates.append(d)
                hsrc = hsrc or str(c.get("source_kind") or "")
    if hdates:
        out["heirs"] = _src("sourced", _iso(max(hdates)), hsrc)
    else:
        out["heirs"] = _src("missing", why="no heir or representative with a stated relation and a dated source")

    # 6a. register of deeds checked (any dated register read for this owner or parcel)
    rod_d: list[tuple[date, str]] = []
    for sig in ("probate_heir", "foreclosure_rod"):
        r = _record(raw, sig)
        if r and to_date(r.get("checked_at")):
            rod_d.append((to_date(r["checked_at"]), str(r.get("source") or sig)))
    for key, fld in (("rod_lookup", ("looked_up_at", "checked_at", "as_of", "fetched_at")),
                     ("rod", ("fetched_at",)), ("rod_chain", ("fetched_at",))):
        b = raw.get(key)
        if isinstance(b, dict) and not (key == "rod_chain" and b.get("status") in ("walled", "capped", "error")):
            d = next((to_date(b.get(f)) for f in fld if to_date(b.get(f))), None)
            if d:
                rod_d.append((d, str(b.get("platform") or b.get("source") or key)))
    if rod_d:
        d, s = max(rod_d)
        out["rod_checked"] = _src("sourced", _iso(d), s)
    else:
        out["rod_checked"] = _src("walled" if acc["rod"] == "person" else "missing",
                                  why="the register is not readable by a script" if acc["rod"] == "person"
                                  else "the register was not searched for this owner")

    # 6b. county tax site checked
    if tl and to_date(tl.get("checked_at")) and str(tl.get("verdict") or "") != "wall":
        out["tax_checked"] = _src("sourced", _iso(to_date(tl["checked_at"])), str(tl.get("source") or tl.get("verifier") or ""))
    elif (tl and str(tl.get("verdict") or "") == "wall") or acc["tax"] == "person":
        out["tax_checked"] = _src("walled", why="the county tax site is not readable by a script")
    else:
        out["tax_checked"] = _src("missing", why="the county tax site was not checked for this parcel")

    # 6c. probate (estate files) checked: a probate record or notice on the row, or a dated search of
    # the estate index (raw['probate_search'] {checked_at, result, source}: a reader's or the
    # owner's search, 'none found' included). The death-index check (probate_heir) is a register
    # check, not an estate-file search, so it counts under 6a only.
    pr_d: list[tuple[date, str]] = []
    ps = raw.get("probate_search")
    if isinstance(ps, dict) and to_date(ps.get("checked_at")):
        pr_d.append((to_date(ps["checked_at"]), str(ps.get("source") or "probate_search")))
    for key in ("probate", "sc_probate_notice"):
        b = raw.get(key)
        if isinstance(b, dict) and (key != "probate" or has_real_probate(b)) and to_date(_g(row, "first_seen")):
            pr_d.append((to_date(_g(row, "first_seen")), key))
    if pr_d:
        d, s = max(pr_d)
        out["probate_checked"] = _src("sourced", _iso(d), s)
    elif acc["probate"] == "person":
        out["probate_checked"] = _src("walled", why="the estate index is behind a CAPTCHA, a login or is not online")
    else:
        out["probate_checked"] = _src("missing", why="the estate index is open but no script reads it yet")

    # 6d. obituaries checked (an obituary on the row, an obituary survivor list, or a dated search
    # that found none: raw['obituary_search'] {checked_at, result, source})
    ob_d: list[date] = []
    os_ = raw.get("obituary_search")
    if isinstance(os_, dict) and to_date(os_.get("checked_at")):
        ob_d.append(to_date(os_["checked_at"]))
    ob = raw.get("obituary")
    if isinstance(ob, dict):
        d = to_date(ob.get("pub_date") or ob.get("title_date"))
        if d:
            ob_d.append(d)
    for c in raw.get("heir_candidates") or []:
        if isinstance(c, dict) and c.get("source_kind") == "obituary_survivor" and to_date(c.get("source_date")):
            ob_d.append(to_date(c["source_date"]))
    if ob_d:
        out["obituaries_checked"] = _src("sourced", _iso(max(ob_d)), "obituary")
    else:
        out["obituaries_checked"] = _src("missing", why="no dated obituary search on the row (per-lead obituary "
                                                        "lookups are off by the owner's decision)")
    return out


def complete(its: dict) -> bool:
    return all(its.get(k, {}).get("status") == "sourced" for k in ITEMS)


def published(its: dict) -> dict:
    """The public-safe form call_ready publishes: {item: ISO date | 'missing' | 'walled' | 'n/a'}."""
    return {k: (v["on"] if v["status"] == "sourced" else v["status"]) for k, v in its.items()}


# ---------------------------------------------------------------------------------------------
# quiet-title candidate classes (measurement; never a filter)
# ---------------------------------------------------------------------------------------------

#: a long hold: years since the parcel's last recorded sale on the county record
LONG_HELD_YEARS = 20
_ELDERLY_TAGS = frozenset({"life_estate", "elderly", "senior", "elderly_disabled", "elderly_exemption",
                           "homestead_elderly", "senior_exemption"})


def candidate_classes(row: Any, cr: Optional[dict] = None) -> list[str]:
    """The quiet-title candidate classes a row falls in:
    heir_estate      a record or a marker says the owner of record died (roll HEIRS / ESTATE wording,
                     a probate record or notice, the death index, an obituary match);
    elderly_long     an elderly marker (tax-relief exemption, life estate, the elderly verifier)
                     on a parcel held LONG_HELD_YEARS or more;
    tax2_unclear     two or more years of delinquent tax on the record and an unclear title (a
                     title-risk block, a chain break, roll heir wording, an estate or unknown owner)."""
    from .call_ready import death_fact, owner_kind
    raw = _raw(row)
    out = []
    d = death_fact(row)
    if d["record"] or d["weak"]:
        out.append("heir_estate")
    ten = raw.get("tenure") if isinstance(raw.get("tenure"), dict) else {}
    years_held = ten.get("years_held") if isinstance(ten.get("years_held"), (int, float)) else None
    le = raw.get("life_events") if isinstance(raw.get("life_events"), list) else []
    eld = bool(set(map(str, le)) & _ELDERLY_TAGS) or isinstance(raw.get("tax_relief"), dict) \
        or isinstance(raw.get("gis_exempt"), dict) or bool(_record(raw, "elderly_disabled"))
    if eld and years_held is not None and years_held >= LONG_HELD_YEARS:
        out.append("elderly_long")
    fm = raw.get("fullmer") if isinstance(raw.get("fullmer"), dict) else {}
    yrs = None
    tl = _record(raw, "tax_lien")
    if tl and str(tl.get("verdict") or "") == "confirmed":
        ev = tl.get("evidence") if isinstance(tl.get("evidence"), dict) else {}
        yrs = ev.get("years_delinquent") if isinstance(ev.get("years_delinquent"), int) else None
    if yrs is None and isinstance(fm.get("years_delinquent"), (int, float)):
        yrs = fm.get("years_delinquent")
    if yrs is None and raw.get("two_year_delinquent"):
        yrs = 2
    dc = raw.get("deed_chain") if isinstance(raw.get("deed_chain"), dict) else {}
    breaks = ((dc.get("summary") or {}).get("chain_breaks")) if isinstance(dc.get("summary"), dict) else None
    unclear = bool(raw.get("title_risk")) or bool(breaks) or isinstance(raw.get("heir_estate"), dict) \
        or owner_kind(row) in ("estate", "unknown") or bool(d["weak"])
    if yrs is not None and yrs >= 2 and unclear:
        out.append("tax2_unclear")
    return out
