"""Possible heirs for a dead owner, each with its source. Candidates only, never findings.

The attorney's ask: tax notices often go to a dead person; he needs the taxpayer of record and the
potential heirs, and obituaries are one of the records he checks.

WHICH LEADS. A lead whose roll or records say the owner died (deceased_signals):
  roll_heirs_estate   HEIRS / ESTATE OF / DECEASED wording on the owner of record (the row's owner,
                      the county GIS owner, or the heir-estate roll block); a business name with a
                      bare 'ESTATE' in it ('... REAL ESTATE LLC') does not count;
  probate             a probate notice or record names the estate (Notice to Creditors, the probate
                      court index, a published heir-naming suit, McDowell's deceased-owner roll);
  obituary            the row carries an obituary, or enrichment_obituary_match attached one;
  death_index         the probate_heir verifier confirmed a death entry (raw['verification']).

WHAT IT BUILDS. raw['heir_candidates'] = [{name, relation, source_kind, source_url, source_date,
confidence_note, label: 'candidate'} (+ address and address_note for a representative, only when
the public notice prints one)]. source_kind is one of:
  obituary_survivor                       named in the obituary's 'survived by' list, with the
                                          relation the obituary states (in-laws and the
                                          predeceased are left out);
  probate_notice_personal_representative  the executor / administrator / personal representative a
                                          published Notice to Creditors names;
  probate_record_personal_representative  the personal representative on the probate court's own
                                          index (SC probate index);
  court_notice_named_heir                 a person a published court notice names as an heir;
  county_record                           another owner on the tax roll beside the heirs/estate
                                          entry, or the roll's care-of addressee.
None of these is a finding that the person is an heir, is alive, or is anyone in particular.

PRIVACY. Names are private people's names. raw['heir_candidates'] and raw['obituary_match'] are NOT
in RAW_KEEP, so they never reach the public board; the published key is
raw['heir_candidates_summary'] (counts and flags, no names). The names go to the private file
data/heirs/heir_candidates.jsonl.gz (heirs_store.py; data/ is gitignored).

No network. Env HEIR_CANDIDATES=0 turns it off; HEIR_CANDIDATES_PRIVATE_OUT=0 skips the private file.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

import structlog

from .enrichment_obituary_match import (
    OBITUARY_SOURCES,
    _get,
    _raw,
    iso_date,
    obit_person,
    owner_readings,
    record_from_row,
)
from .obituary_text import IN_LAW, tidy_name
from .quiet_title.names import clean, is_entity, roll_markers, split_owners

log = structlog.get_logger()

SOURCE_KINDS = (
    "obituary_survivor",
    "probate_notice_personal_representative",
    "probate_record_personal_representative",
    "court_notice_named_heir",
    "county_record",
)

_REL_WORDS = {
    "spouse": "spouse", "son": "son", "daughter": "daughter", "child": "child", "brother": "brother",
    "sister": "sister", "sibling": "sibling", "half_sibling": "half-sibling", "stepchild": "stepchild",
    "step_sibling": "step-sibling", "step_parent": "step-parent", "grandchild": "grandchild",
    "great_grandchild": "great-grandchild", "great_great_grandchild": "great-great-grandchild",
    "step_grandchild": "step-grandchild", "mother": "mother", "father": "father", "parent": "parent",
    "nephew": "nephew", "niece": "niece", "aunt": "aunt", "uncle": "uncle", "cousin": "cousin",
    "companion": "companion", "godchild": "godchild",
}


# --------------------------------------------------------------------------- death signals

def _entity_safe_markers(s: Optional[str]) -> list[str]:
    m = roll_markers(s)
    if m and is_entity(s):
        m = [w for w in m if w != "ESTATE"]
    return m


def deceased_signals(row: Any) -> list[dict]:
    raw = _raw(row)
    out: list[dict] = []
    owners = [("owner_name", _get(row, "owner_name"))]
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    owners.append(("gis.owner", gis.get("owner")))
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    owners.append(("heir_estate.owner_of_record", he.get("owner_of_record")))
    for field, val in owners:
        mk = _entity_safe_markers(val)
        if mk:
            out.append({"kind": "roll_heirs_estate", "evidence": f"{field}: {', '.join(mk)}"})
            break
    lt = str(_get(row, "listing_type") or "")
    probate_ev: list[str] = []
    if lt.endswith("probate_notice") or lt == "PROBATE_NOTICE":
        probate_ev.append("listing type probate_notice")
    if isinstance(raw.get("sc_probate_notice"), dict):
        probate_ev.append("SC Notice to Creditors")
    try:
        from .signal_freshness import has_real_probate
        if has_real_probate(raw.get("probate")):
            probate_ev.append("probate notice block")
    except Exception:  # noqa: BLE001
        pass
    sp = raw.get("sc_probate_net")
    if isinstance(sp, dict) and sp.get("record_kind") == "probate":
        probate_ev.append("SC probate court index")
    if isinstance(raw.get("mcdowell_probate"), dict):
        probate_ev.append("McDowell deceased-owner roll")
    if isinstance(raw.get("heir_naming_publication"), dict):
        probate_ev.append("published heir-naming court notice")
    if isinstance(raw.get("liensnc_posthumous_filing"), dict):
        probate_ev.append("lien filed after a recorded death")
    if probate_ev:
        out.append({"kind": "probate", "evidence": "; ".join(probate_ev)})
    om = raw.get("obituary_match")
    if isinstance(raw.get("obituary"), dict) and raw["obituary"].get("decedent"):
        out.append({"kind": "obituary", "evidence": "the row carries an obituary"})
    elif isinstance(om, dict) and om.get("status") == "attached":
        out.append({"kind": "obituary", "evidence": f"obituary matched ({(om.get('name_fit') or {}).get('level')})"})
    for v in raw.get("verification") or []:
        if isinstance(v, dict) and v.get("signal") == "probate_heir" and v.get("verdict") == "confirmed":
            out.append({"kind": "death_index", "evidence": "probate_heir verifier: death entry confirmed"})
            break
    return out


# --------------------------------------------------------------------------- candidates

def _cand(name: str, relation: str, kind: str, url: Optional[str], date: Optional[str], note: str,
          **extra) -> dict:
    c = {"name": name, "relation": relation, "source_kind": kind, "source_url": url,
         "source_date": date, "confidence_note": note, "label": "candidate"}
    c.update({k: v for k, v in extra.items() if v})
    return c


_SUF = ("JR", "SR", "II", "III", "IV")


def _tokens(name: str) -> tuple[frozenset, Optional[str]]:
    """(name words without initials or suffix, suffix) for a decedent / candidate comparison."""
    words = [w for w in clean(re.sub(r"(?i)^\s*c/o\s+", "", name)).replace(",", " ").split() if w]
    suf = next((w for w in words if w in _SUF), None)
    return frozenset(w for w in words if w not in _SUF and len(w) > 1), suf


def _decedent_tokens(row: Any) -> set[tuple[frozenset, Optional[str]]]:
    """Every reading of the decedent / owner, so a decedent never comes back as his own heir."""
    raw = _raw(row)
    out: set[tuple[frozenset, Optional[str]]] = set()
    strings: list[str] = []
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    # not the row's `defendant`: on a probate-index row it is the personal representative
    # (sc_probate_net), and on a court row a living party
    for owner in (_get(row, "owner_name"), gis.get("owner")):
        if not owner:
            continue
        parts = split_owners(owner)
        marked = [p for p in parts if roll_markers(p)]
        if marked:
            strings += marked                      # 'DOE JOHN HEIRS; DOE MARY': only John died
        elif len(parts) == 1:
            strings.append(str(owner))
    for k in ("probate", "sc_probate_notice", "obituary"):
        b = raw.get(k)
        if isinstance(b, dict) and (b.get("decedent") or b.get("estate")):
            strings.append(str(b.get("decedent") or b.get("estate")))
    om = raw.get("obituary_match")
    if isinstance(om, dict) and om.get("status") == "attached":
        strings.append(str((om.get("name_fit") or {}).get("decedent_reading") or ""))
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    for h in he.get("heir_names") or []:
        if isinstance(h, dict) and h.get("role") in ("heir", "estate") and h.get("name"):
            strings.append(str(h["name"]))
    for s in strings:
        if not s:
            continue
        for p, _ in owner_readings(s):
            out.add((frozenset(w for w in [p.last, *p.given] if len(w) > 1), p.suffix))
        p = obit_person(s)
        if p:
            out.add((frozenset(w for w in [p.last, *p.given] if len(w) > 1), p.suffix))
    return out


def _is_decedent(name: str, dec: set) -> bool:
    """The name is a reading of the decedent: same words (initials aside) and the same suffix.
    'DOE JOHN JR' is not the decedent 'DOE JOHN'; 'DOE JOHN Q' is the decedent 'DOE JOHN QUINCY'."""
    toks, suf = _tokens(name)
    if len(toks) < 2:
        return False
    for d, dsuf in dec:
        if (suf or None) != (dsuf or None):
            continue
        if toks == d or toks <= d or (d <= toks and len(toks) - len(d) <= 1 and len(d) >= 2):
            return True
    return False


def _obituary_candidates(row: Any) -> list[dict]:
    raw = _raw(row)
    out: list[dict] = []
    om = raw.get("obituary_match") if isinstance(raw.get("obituary_match"), dict) else None
    sources: list[tuple[dict, str]] = []
    if om and om.get("status") == "attached":
        lvl = (om.get("name_fit") or {}).get("level")
        how = {"full": "given, middle and surname all agree",
               "middle_initial": "given name and surname agree and the middle name agrees as an initial",
               "given_surname": "given name and surname agree; no middle name to compare"}.get(lvl, str(lvl))
        sources.append(({"url": om.get("url"), "death_date": om.get("date"), "survivors": om.get("survivors") or []},
                        f"the obituary is linked to this owner by name ({how}) and county; {om.get('county_fit') or ''}"
                        .strip("; ")))
    rec = record_from_row(row)
    if rec and rec.get("survivors"):
        own = any(str(_get(row, "source") or "").startswith(s) for s in OBITUARY_SOURCES)
        sources.append((rec, "the obituary is this row's own source" if own else
                        "the obituary was merged into this row by the board's own parcel match"))
    for src, link_note in sources:
        for s in src.get("survivors") or []:
            rel = s.get("relation")
            if not s.get("name") or rel in IN_LAW or rel == "in_law":
                continue
            word = _REL_WORDS.get(rel, str(rel).replace("_", " "))
            bits = [f"named as {word} in the obituary's survivor list", link_note]
            if s.get("surname_stated") is False:
                bits.append("the obituary gives no surname for this person")
            if s.get("surname_from_list"):
                bits.append("surname taken from the list it is printed in")
            out.append(_cand(s["name"], word, "obituary_survivor", s.get("source_url") or src.get("url"),
                             s.get("source_date") or src.get("death_date") or src.get("published"),
                             "; ".join(b for b in bits if b) + ". A candidate, not a finding that this person is "
                                                              "an heir."))
    return out


def _pr_candidates(row: Any) -> list[dict]:
    raw = _raw(row)
    out: list[dict] = []
    url = _get(row, "source_url")
    pn = raw.get("public_notice") if isinstance(raw.get("public_notice"), dict) else {}
    pub_date = iso_date(pn.get("published_at") or pn.get("publication_date"))
    sp = raw.get("sc_probate_notice")
    if isinstance(sp, dict) and sp.get("personal_representative"):
        out.append(_cand(str(sp["personal_representative"]), "personal representative",
                         "probate_notice_personal_representative", url, pub_date,
                         f"named personal representative in the published Notice to Creditors for case "
                         f"{sp.get('case_number') or '(no number)'}; a representative administers the estate and "
                         f"is often, not always, an heir.",
                         address=sp.get("pr_address"),
                         address_note="address as printed in the public notice" if sp.get("pr_address") else None))
    pb = raw.get("probate")
    if isinstance(pb, dict) and pb.get("personal_representative"):
        role = str(pb.get("pr_role") or "personal representative").lower()
        for nm in re.split(r"\s*(?:;|\band\b|&)\s*", str(pb["personal_representative"])):
            nm_t, _ = tidy_name(nm)
            if not nm_t or len(nm_t.split()) < 2:
                continue
            out.append(_cand(nm_t, role, "probate_notice_personal_representative", url, pub_date,
                             f"named {role} in the published estate notice"
                             f"{' (file ' + str(pb.get('es_case_number') or pb.get('nc_estate_file_no')) + ')' if (pb.get('es_case_number') or pb.get('nc_estate_file_no')) else ''}"
                             "; a representative administers the estate and is often, not always, an heir.",
                             address=pb.get("pr_address"),
                             address_note="address as printed in the public notice" if pb.get("pr_address") else None))
    spn = raw.get("sc_probate_net")
    if isinstance(spn, dict) and isinstance(spn.get("personal_representative"), dict):
        pr = spn["personal_representative"]
        if pr.get("name"):
            nm_t = tidy_name(str(pr["name"]))[0] or str(pr["name"]).strip()
            out.append(_cand(nm_t, str(pr.get("type") or "personal representative").lower(),
                             "probate_record_personal_representative", url, iso_date(spn.get("appointment_date") or spn.get("filing_date")),
                             f"personal representative on the probate court's own index ({spn.get('case_type') or 'estate'}); "
                             "a representative administers the estate and is often, not always, an heir."))
    hp = raw.get("heir_naming_publication")
    if isinstance(hp, dict):
        for h in hp.get("named_heirs") or []:
            nm = h.get("name") if isinstance(h, dict) else h
            nm_t = tidy_name(str(nm or ""))[0]
            if nm_t:
                out.append(_cand(nm_t, "named heir (defendant)", "court_notice_named_heir", url, pub_date,
                                 f"named as an heir in a published court notice (case {hp.get('case_number') or '?'}); "
                                 "the plaintiff's naming, not a court finding."))
    return out


def _county_candidates(row: Any, dec: set[frozenset]) -> list[dict]:
    raw = _raw(row)
    out: list[dict] = []
    url = _get(row, "source_url")
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    for h in he.get("heir_names") or []:
        if not isinstance(h, dict) or h.get("role") != "other" or not h.get("name"):
            continue
        nm = str(h["name"])
        care = bool(re.match(r"\s*C/O\b", nm, re.I))
        nm = re.sub(r"^\s*C/O\s+", "", nm, flags=re.I)
        if is_entity(nm) or _is_decedent(nm, dec):
            continue
        out.append(_cand(nm, "care-of addressee on the tax roll" if care else "co-owner of record on the tax roll",
                         "county_record", url, None,
                         ("the county tax roll prints this name as the care-of addressee on the heirs/estate entry"
                          if care else "the county tax roll lists this name beside the heirs/estate entry")
                         + "; a family member is often named this way, but the roll does not say so."))
    if he.get("care_of") and not is_entity(he["care_of"]) and not _is_decedent(str(he["care_of"]), dec):
        out.append(_cand(str(he["care_of"]), "care-of addressee on the tax roll", "county_record", url, None,
                         "the county tax roll mails the bill in care of this name; the roll does not say why."))
    md = raw.get("mcdowell_probate")
    if isinstance(md, dict) and md.get("ownname2") and not is_entity(md["ownname2"]) \
            and not _is_decedent(str(md["ownname2"]), dec):
        out.append(_cand(str(md["ownname2"]), "second owner line on the tax roll", "county_record", url, None,
                         "McDowell's roll prints this as the second owner line of a deceased owner's parcel."))
    # other owners in the owner-of-record string itself ('DOE JOHN HEIRS; DOE MARY')
    owner = _get(row, "owner_name")
    if owner and _entity_safe_markers(owner):
        for part in split_owners(owner):
            if roll_markers(part) or is_entity(part) or len(part.split()) < 2:
                continue
            if _is_decedent(part, dec):
                continue
            out.append(_cand(part, "co-owner of record on the tax roll", "county_record", url, None,
                             "the owner of record lists this name beside the heirs/estate entry; the roll does "
                             "not say how this person is related."))
    return out


def _dedupe(cands: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cands:
        k = (clean(c["name"]), c["source_kind"], c.get("source_url"))
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def candidates_for(row: Any) -> list[dict]:
    dec = _decedent_tokens(row)
    cands = _obituary_candidates(row) + _pr_candidates(row) + _county_candidates(row, dec)
    # a representative or named heir who reads as the decedent is a parsing slip, not a candidate
    cands = [c for c in cands if c["source_kind"] in ("obituary_survivor", "county_record")
             or not _is_decedent(c["name"], dec)]
    return _dedupe(cands)


def summary_of(signals: list[dict], cands: list[dict], obituary_match: Optional[dict]) -> dict:
    by: dict[str, int] = {}
    for c in cands:
        by[c["source_kind"]] = by.get(c["source_kind"], 0) + 1
    return {
        "count": len(cands),
        "by_source_kind": by,
        "deceased_signals": sorted({s["kind"] for s in signals}),
        "obituary_match": (obituary_match or {}).get("status") if isinstance(obituary_match, dict) else None,
        "label": "candidates, not findings; names are kept off the public board",
    }


def _lead_key(row: Any) -> str:
    st = str(_get(row, "state") or "")
    co = str(_get(row, "county") or "")
    pid = _get(row, "parcel_id")
    return f"{st}|{co}|{pid}" if pid else f"{st}|{co}|url:{_get(row, 'source_url')}"


def enrich_heir_candidates(listings: Iterable[Any], *, private_out: Optional[bool] = None) -> dict:
    if os.environ.get("HEIR_CANDIDATES", "1") == "0":
        return {"skipped": "HEIR_CANDIDATES=0"}
    rows = list(listings)
    stats = {"dead_owner_leads": 0, "with_candidates": 0, "candidates": 0, "by_source_kind": {},
             "by_signal": {}}
    private_rows: list[dict] = []
    for row in rows:
        raw = _raw(row)
        if not isinstance(raw, dict):
            continue
        raw.pop("heir_candidates", None)
        raw.pop("heir_candidates_summary", None)
        sig = deceased_signals(row)
        if not sig:
            continue
        stats["dead_owner_leads"] += 1
        for s in {x["kind"] for x in sig}:
            stats["by_signal"][s] = stats["by_signal"].get(s, 0) + 1
        cands = candidates_for(row)
        raw["heir_candidates"] = cands
        raw["heir_candidates_summary"] = summary_of(sig, cands, raw.get("obituary_match"))
        if cands:
            stats["with_candidates"] += 1
            stats["candidates"] += len(cands)
            for c in cands:
                stats["by_source_kind"][c["source_kind"]] = stats["by_source_kind"].get(c["source_kind"], 0) + 1
        gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
        private_rows.append({
            "lead_key": _lead_key(row), "state": _get(row, "state"), "county": _get(row, "county"),
            "parcel_id": _get(row, "parcel_id"), "source": _get(row, "source"),
            "source_url": _get(row, "source_url"), "street_address": _get(row, "street_address"),
            "taxpayer_of_record": _get(row, "owner_name") or gis.get("owner"),
            "deceased_signals": sig, "heir_candidates": cands,
            "obituary_match": raw.get("obituary_match"),
        })
    write = private_out if private_out is not None else os.environ.get("HEIR_CANDIDATES_PRIVATE_OUT", "1") != "0"
    if write and private_rows:
        try:
            from .heirs_store import write_heir_candidates
            path, n = write_heir_candidates(private_rows)
            stats["private_file"] = str(path)
            stats["private_rows"] = n
        except OSError as exc:
            log.warning("heir_candidates.private_write_failed", error=str(exc)[:200])
    log.info("heir_candidates.done", **{k: v for k, v in stats.items() if k != "private_file"})
    return stats
