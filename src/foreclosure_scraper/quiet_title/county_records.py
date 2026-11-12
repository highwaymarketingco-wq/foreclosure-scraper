"""The per-county 'where to look' facts, read from docs/county_records/county_records_matrix.json.

The matrix (built 2026-10-07, one record per county for 100 NC and 45 SC counties) says, for each
county, where its register of deeds, tax site, county map layer and probate route are, whether the
index and the deed images are free, how far back the online index goes, and whether a person is
needed (a CAPTCHA, a login, a payment, a Cloudflare check). Nothing here touches the network: the
sheet prints these facts so a person (or the attorney) knows where to go, including for a county
whose register is walled to scripts. The tool never fetches from a walled site.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

MATRIX_PATH = Path(__file__).resolve().parents[3] / "docs" / "county_records" / "county_records_matrix.json"

#: rod.access / tax.access as the matrix writes them -> (can a script read it, why a person is needed)
ACCESS_WORDS = {
    "open": (True, ""),
    "disclaimer_click": (False, "a person clicks through the site's disclaimer page first"),
    "captcha": (False, "a CAPTCHA (a 'prove you are human' check) stands in front of the search"),
    "blocked": (False, "the site answers scripts with a Cloudflare or similar bot check; a person uses a normal "
                       "browser"),
    "login": (False, "the site asks for a login"),
    "paywall": (False, "the site charges for the search or the images"),
    "unreachable": (False, "the site did not answer when the matrix was built"),
}


def county_key(name: Optional[str]) -> str:
    """'New Hanover' / 'new-hanover' / 'NEW HANOVER COUNTY' -> 'new hanover'."""
    s = re.sub(r"[-_]+", " ", (name or "").strip().lower())
    s = re.sub(r"\s+county$", "", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=4)
def _load(path: str) -> dict[tuple[str, str], dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out: dict[tuple[str, str], dict] = {}
    for rec in data.get("counties") or []:
        st = str(rec.get("state") or "").strip().upper()
        k = county_key(rec.get("county"))
        if st and k:
            out[(st, k)] = rec
    out[("", "__generated__")] = {"generated": data.get("generated")}
    return out


def county_record(county: str, state: str = "NC", path: Optional[Path] = None) -> Optional[dict]:
    """The matrix record for one county, or None when the matrix has none."""
    p = Path(path) if path else MATRIX_PATH
    if not p.exists():
        return None
    return _load(str(p)).get((state.strip().upper(), county_key(county)))


def matrix_date(path: Optional[Path] = None) -> Optional[str]:
    p = Path(path) if path else MATRIX_PATH
    if not p.exists():
        return None
    return (_load(str(p)).get(("", "__generated__")) or {}).get("generated")


@dataclass
class WhereToLook:
    """The block printed on every sheet: where a person goes for each record in this county."""
    county: str
    state: str
    matrix_date: Optional[str] = None
    found: bool = False
    rod_url: Optional[str] = None
    rod_platform: Optional[str] = None
    rod_access: Optional[str] = None
    rod_script_ok: bool = False
    rod_index_free: str = "unknown"
    rod_images_free: str = "unknown"
    rod_back_to: Optional[int] = None
    rod_plats_online: str = "unknown"
    rod_terms_forbid_automation: str = "unknown"
    rod_person_needed: str = ""
    rod_notes: str = ""
    manual_lane: str = ""
    probate_url: Optional[str] = None
    probate_system: str = ""
    probate_person: str = ""
    tax_url: Optional[str] = None
    tax_access: Optional[str] = None
    tax_person: str = ""
    tax_notes: str = ""
    gis_url: Optional[str] = None
    gis_notes: str = ""
    confidence: Optional[str] = None
    rows: list[tuple[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


_INTERNAL = re.compile(r"\brepo\b|\.py\b|\bsrc/|enrichment_|parcel_cache|\bHANDOFF\b", re.I)


def public_text(text: Optional[str]) -> str:
    """The matrix notes without the sentences about this codebase (file names, 'the repo ...'):
    the sheet goes to an attorney."""
    parts = re.split(r"(?<=[.;])\s+", (text or "").strip())
    return " ".join(x for x in parts if x and not _INTERNAL.search(x)).strip()


def _yn(v: Any) -> str:
    s = str(v if v is not None else "unknown").strip().lower()
    return s if s in ("yes", "no") else "unknown"


def _person(access: Optional[str]) -> tuple[bool, str]:
    """(a script may read it, why a person is needed) for one matrix access word."""
    return ACCESS_WORDS.get((access or "").strip().lower(),
                            (False, "the matrix does not say how the site is reached"))


def where_to_look(county: str, state: str = "NC", path: Optional[Path] = None) -> WhereToLook:
    """Build the block from the matrix. A county the matrix lacks still gets a block saying so."""
    w = WhereToLook(county=county, state=state.upper(), matrix_date=matrix_date(path))
    rec = county_record(county, state, path)
    if rec is None:
        w.rows = [("Records matrix", f"No entry for {county} County, {state.upper()} in the county records matrix; "
                                     f"a person finds the register of deeds, tax office and clerk of court for "
                                     f"the county.")]
        return w
    w.found = True
    rod, prob, tax, gis = (rec.get("rod") or {}), (rec.get("probate") or {}), (rec.get("tax") or {}), (rec.get("gis") or {})
    w.rod_url, w.rod_platform, w.rod_access = rod.get("url"), rod.get("platform"), rod.get("access")
    w.rod_index_free, w.rod_images_free = _yn(rod.get("free_name_search")), _yn(rod.get("images_free"))
    by = rod.get("index_online_back_to_year")
    w.rod_back_to = int(by) if isinstance(by, int) or (isinstance(by, str) and by.isdigit()) else None
    w.rod_plats_online = _yn(rod.get("plat_books_or_maps_online"))
    w.rod_terms_forbid_automation = _yn(rod.get("terms_forbid_automation"))
    w.rod_notes = public_text(rod.get("notes"))
    w.manual_lane = public_text(rec.get("manual_lane"))
    w.rod_script_ok, why = _person(w.rod_access)
    if w.rod_terms_forbid_automation == "yes":
        w.rod_script_ok, why = False, (why + "; " if why else "") + "the site's terms forbid automated searching"
    needs = []
    if why:
        needs.append(why)
    if w.rod_images_free == "no":
        needs.append("deed images are paid (the full legal description is on the image)")
    elif w.rod_images_free == "unknown":
        needs.append("whether the deed images are free was not confirmed")
    w.rod_person_needed = ("yes: " + "; ".join(needs)) if needs else "no for the index and images"
    w.probate_url, w.probate_system = prob.get("url"), (prob.get("system") or "").strip()
    pok, pwhy = _person(prob.get("access"))
    w.probate_person = "no" if pok else f"yes, a person does it: {pwhy}"
    w.tax_url, w.tax_access, w.tax_notes = tax.get("url"), tax.get("access"), public_text(tax.get("notes"))
    tok, twhy = _person(w.tax_access)
    w.tax_person = "no for the page itself" if tok else f"yes: {twhy}"
    w.gis_url, w.gis_notes = gis.get("url"), public_text(gis.get("notes"))
    w.confidence = rec.get("confidence")

    back = (f"{w.rod_back_to}" if w.rod_back_to else "not stated by the register")
    w.rows = [
        ("Register of deeds portal", f"{w.rod_url or 'not found'} ({w.rod_platform or 'platform not recorded'})"),
        ("Index free / images free", f"index: {w.rod_index_free}; deed images: {w.rod_images_free}"),
        ("Online index goes back to", back),
        ("Person needed for the register", w.rod_person_needed),
        ("Plat books and old books", f"plats or maps online: {w.rod_plats_online}. {w.rod_notes}".strip()),
        ("What a person does here", w.manual_lane or "the matrix records no step beyond the rows above"),
        ("Probate (estates)", f"{w.probate_system or 'statewide eCourts'}: {w.probate_url or ''}. "
                              f"Person needed: {w.probate_person}."),
        ("County tax site", f"{w.tax_url or 'not found'}. Person needed: {w.tax_person}. {w.tax_notes}".strip()),
    ]
    if w.gis_url:
        w.rows.append(("County map layer", w.gis_url))
    return w
