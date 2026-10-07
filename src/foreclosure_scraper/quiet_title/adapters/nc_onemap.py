"""Any North Carolina county: the parcel record from NC OneMap, the free statewide parcel layer.

SOURCE
  * NC OneMap statewide parcels, services.nconemap.gov/secure/rest/services/NC1Map_Parcels/
    FeatureServer/1 (ArcGIS JSON; free, no key, no login; one service for all 100 counties, filtered
    by cntyname). Fields read live 2026-10-07; the ones this adapter asks for are OUT_FIELDS (an
    explicit list, never *), and every attribute bag passes sensitive_fields.drop_sensitive first.
      parno / altparno   the county's parcel number and its alternate (the format differs from
                         county to county and from the board's: 0000-12-3456 vs 0000123456, or
                         R00001-002-003-000 vs R00001002003000). The join compares letters and
                         digits only (pin_key); the one request asks for the PIN as given, its
                         usual NC spellings, and a LIKE pattern with every separator wild.
      ownname, ownname2  the taxpayer of record as the assessor's roll shows it
      siteadd / mailadd  situs and mailing address (mailadd + munit, mcity, mstate, mzip)
      gisacres           acres computed from the map; recareano/recareatx: the recorded area
      parval, landval, improvval, parvaltype   the TAX value (the layer's value type, e.g. Assessed)
      sourceref          the deed the assessor cites: 'Deed Book/Page 001234/00567' (New Hanover:
                         'Sale Book/Page'; Guilford: the book only); sourcedatx its date as written
                         (MM/DD/YYYY, YYYYMM, YYYY or blank, county by county)
      legdecfull         the assessor's SHORT legal ('LOT 7 EXAMPLE ACRES SEC B'). It is NOT the
                         deed's full legal description; the sheet says so and points to the deed
                         image. Caldwell writes the deed reference here instead ('BK 1111 PG 2222');
                         that is read as a deed reference, never shown as a legal description.
      mapref             the plat reference ('Plat Book/Page 0012/0034', 'Plat Book-Page 123-45')
      revdatetx, sourceagnt   when the record was revised and which assessor supplied it
    Coverage (county_records_matrix.json, measured 2026-10-07): the deed book/page is on 78 to 100
    percent of parcels in nearly every county (Swain none, Robeson about 35 percent, Union about
    43 percent, Hyde about 63 percent, Hoke none, Guilford the book only); the short legal is on most
    counties' parcels and blank for some (Buncombe, Polk, Madison mostly).

THE REGISTER IS NOT SEARCHED for these counties: the sheet's 'where to look' block (from the county
records matrix) gives the register's address, whether its index and images are free, how far back
it goes and why a person is needed. Tax bills are not read either; the block gives the tax site.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional
from urllib.parse import urlencode

from ...sensitive_fields import drop_sensitive, is_sensitive_field
from ..county_records import county_record, where_to_look
from ..model import DeathSearch, Instrument, NameSearch, OtherParcel, Parcel, RecordCheck, TaxStatus
from ..names import PersonName
from .base import CountyAdapter
from .buncombe import street_key

ONEMAP_LAYER = "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1"
SRC_ONEMAP = "NC OneMap statewide parcel layer (NC1Map_Parcels)"
LAYER_LABEL = "the NC OneMap statewide parcel layer"
ECOURTS = "https://portal-nc.tylertech.cloud/Portal/"
RETRY_WAITS = (0, 5)

#: the fields asked for, by name (never *). Every one is read below or kept for the exhibit.
OUT_FIELDS = ("parno", "altparno", "nparno", "cntyname", "ownname", "ownname2", "mailadd", "munit", "mcity",
              "mstate", "mzip", "siteadd", "sunit", "scity", "szip", "saddno", "saddstname", "gisacres",
              "recareano", "recareatx", "parval", "landval", "improvval", "parvaltype", "presentval",
              "saledatetx", "legdecfull", "sourceref", "sourcedatx", "subdivisio", "mapref", "revdatetx",
              "sourceagnt", "struct", "structyear", "parusedesc", "owntype")

#: the 100 NC counties, spelled as the layer's cntyname writes them
NC_COUNTIES = (
    "Alamance", "Alexander", "Alleghany", "Anson", "Ashe", "Avery", "Beaufort", "Bertie", "Bladen", "Brunswick",
    "Buncombe", "Burke", "Cabarrus", "Caldwell", "Camden", "Carteret", "Caswell", "Catawba", "Chatham", "Cherokee",
    "Chowan", "Clay", "Cleveland", "Columbus", "Craven", "Cumberland", "Currituck", "Dare", "Davidson", "Davie",
    "Duplin", "Durham", "Edgecombe", "Forsyth", "Franklin", "Gaston", "Gates", "Graham", "Granville", "Greene",
    "Guilford", "Halifax", "Harnett", "Haywood", "Henderson", "Hertford", "Hoke", "Hyde", "Iredell", "Jackson",
    "Johnston", "Jones", "Lee", "Lenoir", "Lincoln", "Macon", "Madison", "Martin", "McDowell", "Mecklenburg",
    "Mitchell", "Montgomery", "Moore", "Nash", "New Hanover", "Northampton", "Onslow", "Orange", "Pamlico",
    "Pasquotank", "Pender", "Perquimans", "Person", "Pitt", "Polk", "Randolph", "Richmond", "Robeson",
    "Rockingham", "Rowan", "Rutherford", "Sampson", "Scotland", "Stanly", "Stokes", "Surry", "Swain",
    "Transylvania", "Tyrrell", "Union", "Vance", "Wake", "Warren", "Washington", "Watauga", "Wayne", "Wilkes",
    "Wilson", "Yadkin", "Yancey",
)
_BY_KEY = {re.sub(r"[^a-z]", "", c.lower()): c for c in NC_COUNTIES}


def canonical_county(name: Optional[str]) -> Optional[str]:
    """'new-hanover' / 'MCDOWELL COUNTY' -> 'New Hanover' / 'McDowell'; None for a non-NC name."""
    s = re.sub(r"\s+county\s*$", "", (name or "").strip(), flags=re.I)
    return _BY_KEY.get(re.sub(r"[^a-z]", "", s.lower()))


# ---------------------------------------------------------------------------------------------
# pure helpers (tested on hand-written fixtures)
# ---------------------------------------------------------------------------------------------

def pin_key(s: Any) -> str:
    """Letters and digits only, upper case: the join key between the board's and the layer's ids."""
    return re.sub(r"[^A-Za-z0-9]", "", str(s or "")).upper()


def pin_variants(pin: str) -> list[str]:
    """The PIN as given, its letters-and-digits form, and the usual NC spellings of a 10- or
    13-digit PIN (4-2-4, 4-2-4-3, 4-2-4.3). Only letters, digits, '-' and '.' survive."""
    raw = re.sub(r"[^A-Za-z0-9.\-]", "", (pin or "").strip()).upper()
    k = pin_key(raw)
    out = [raw, k]
    if k.isdigit() and len(k) in (10, 13):
        base = f"{k[:4]}-{k[4:6]}-{k[6:10]}"
        out.append(base)
        if len(k) == 13:
            out += [f"{base}-{k[10:]}", f"{base}.{k[10:]}", k[:10]]
    seen: list[str] = []
    for v in out:
        if v and v not in seen:
            seen.append(v)
    return seen


def like_pattern(pin: str) -> str:
    """'0000123456' -> '0%0%0%0%1%2%3%4%5%6': matches the same characters with any separators."""
    return "%".join(pin_key(pin))


def parcel_where(county: str, pin: str) -> str:
    vals = ",".join(f"'{v}'" for v in pin_variants(pin))
    pat = like_pattern(pin)
    return (f"cntyname='{county}' AND (parno IN ({vals}) OR altparno IN ({vals}) OR parno LIKE '{pat}' "
            f"OR altparno LIKE '{pat}')")


def pick_feature(pin: str, feats: list[dict]) -> tuple[Optional[dict], str]:
    """The record whose parno (else altparno) equals the PIN letter for letter, and a note."""
    k = pin_key(pin)
    by_parno = [a for a in feats if pin_key(a.get("parno")) == k]
    by_alt = [a for a in feats if pin_key(a.get("altparno")) == k and a not in by_parno]
    hits = by_parno or by_alt
    if not hits:
        return None, (f"The layer returned {len(feats)} record(s) near PIN {pin}; none has a parcel number equal "
                      f"to it letter for letter." if feats else f"The layer returned no record for PIN {pin}.")
    field = "parno" if by_parno else "altparno"
    note = (f"Joined on {field}: the layer writes {hits[0].get(field)!s}, which equals PIN {pin} once separators "
            f"are ignored.")
    if len(hits) > 1:
        note += f" {len(hits)} records carry that number; the first is shown."
    return hits[0], note


def _z(s: Optional[str]) -> Optional[str]:
    """'000246' -> '246'; '' / '0' / '00000' -> None."""
    t = re.sub(r"\s+", "", s or "").upper()
    t = t.lstrip("0")
    return t or None


_REF = re.compile(r"^\s*([A-Za-z]+)?\s*Book\s*[/\-]\s*Page\s*:?\s*(.*)$", re.I)
_BK_PG = re.compile(r"^\s*BK\s*([A-Z0-9]+)\s+PG\s*([A-Z0-9]+)", re.I)
_SLASH_ONLY = re.compile(r"^\s*(\d{1,6})\s*/\s*(\d{1,6})(?:\s+(\d{4}))?(?:\s+\d+(?:\.\d+)?)?\s*$")


def parse_ref(text: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(the layer's word for it, book, page) from a sourceref / mapref value.
    'Deed Book/Page 000321/00654' -> ('Deed', '321', '654'); 'Plat Book-Page 123-45' ->
    ('Plat', '123', '45'); 'Deed Book/Page 007777' -> ('Deed', '7777', None); 'Plat Book/Page /' ->
    ('Plat', None, None)."""
    s = (text or "").strip()
    m = _REF.match(s)
    if m:
        rest = m.group(2).strip()
        parts = re.split(r"\s*[/\-]\s*", rest, maxsplit=1)
        book = _z(parts[0]) if parts and parts[0] else None
        page = _z(parts[1]) if len(parts) > 1 else None
        return (m.group(1) or None), book, page
    return None, None, None


def legal_as_deed_ref(text: Optional[str]) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """Caldwell writes the deed reference in legdecfull ('BK 1111 PG 2222 YR 22 ST 100.00',
    '3333/0444 1990  0.00'). Returns (book, page, year or None) for such a value, else None."""
    s = (text or "").strip()
    m = _BK_PG.match(s)
    if m:
        y = re.search(r"\bYR\s*(\d{2,4})\b", s, re.I)
        return _z(m.group(1)) or "", _z(m.group(2)), (y.group(1) if y else None)
    m = _SLASH_ONLY.match(s)
    if m:
        return _z(m.group(1)) or "", _z(m.group(2)), m.group(3)
    return None


def layer_date(text: Optional[str]) -> Optional[str]:
    """A date as the layer writes it -> ISO, as precise as the text: '03/04/1979' -> '1979-03-04';
    '20260102' -> '2026-01-02'; '2024-01-02 10:11:12.' -> '2024-01-02'; '202401' -> '2024-01';
    '2006' -> '2006'; '' -> None."""
    s = (text or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\b", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if re.fullmatch(r"\d{8}", s) and s != "00000000":
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if re.fullmatch(r"\d{6}", s):
        return f"{s[:4]}-{s[4:]}"
    if re.fullmatch(r"\d{4}", s) and s != "0000":
        return s
    return None


def split_care_of(name: str) -> tuple[str, Optional[str]]:
    """'TESTER ANNA HEIRS & C/O JOHN SAMPLE' -> ('TESTER ANNA HEIRS', 'JOHN SAMPLE'): a care-of
    contact written inside the owner field is a mailing contact, not an owner."""
    m = re.search(r"\s*(?:&\s*)?\bC\s*/\s*O\b\s*(.*)$", name or "", re.I)
    if not m:
        return name, None
    return name[:m.start()].strip(" &,;"), (m.group(1).strip() or None)


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def _s(a: dict, k: str) -> str:
    return re.sub(r"\s+", " ", str(a.get(k) or "")).strip()


def parcel_from_onemap(pin: str, a: dict, fields: list[str]) -> Parcel:
    """Fill the sheet's parcel record from one OneMap attribute bag (already through drop_sensitive)."""
    p = Parcel(pin=_s(a, "parno") or pin, found=True, field_names=list(fields), layer_label=LAYER_LABEL)
    own, co1 = split_care_of(_s(a, "ownname"))
    own2, co2 = split_care_of(_s(a, "ownname2"))
    p.owner = (f"{own}; {own2}" if own2 and own2 not in own else own) or None
    p.care_of = "; ".join(dict.fromkeys(x for x in (co1, co2) if x)) or None
    mail = " ".join(x for x in (_s(a, "mailadd"), _s(a, "munit")) if x)
    city = " ".join(x for x in (_s(a, "mcity"), _s(a, "mstate"), _s(a, "mzip")) if x)
    p.mailing = ", ".join(x for x in (mail, city) if x) or None
    p.mailing_house_number, p.mailing_street = street_key(_s(a, "mailadd"))
    site = _s(a, "siteadd")
    hn, st = street_key(site)
    placeholder = hn if hn and (set(hn) <= {"0"} or hn == "99999") else None
    if placeholder:
        # Buncombe writes 99999 and New Hanover 0 where a parcel has no house number
        site = re.sub(rf"^{placeholder}\s+", "", site)
        hn = None
    p.situs_house_number, p.situs_street = hn, st
    if not st and _s(a, "saddstname"):
        p.situs_street = street_key("1 " + _s(a, "saddstname"))[1]
    p.situs = " ".join(x for x in (site, _s(a, "sunit")) if x) or None
    if p.situs and _s(a, "scity"):
        p.situs += f", {_s(a, 'scity')}"
    if placeholder:
        p.situs_note = f"no house number (the record uses {placeholder} as a placeholder)"
    elif not hn:
        p.situs_note = "no house number on the record" if site else "no situs address on the record"
    gis, rec = _num(a.get("gisacres")), _num(a.get("recareano"))
    if rec in (None, 0.0):
        rec = _num(a.get("recareatx"))
    # the recorded area (the assessor's acreage) first; the map-computed acres otherwise. Cumberland's
    # gisacres is acres divided by 43,560 (0.71 acre written 1.63e-05, measured 2026-10-07): a value
    # under a thousandth of an acre is read as a unit error and not used
    gis_bad = gis is not None and 0 < gis < 0.001
    p.acreage = rec if rec else (gis if gis and not gis_bad else None)
    p.extra["acreage_note"] = (f"recorded area (recareano / recareatx) {rec if rec else 'blank'}; map-computed acres "
                               f"(gisacres) {gis if gis is not None else 'blank'}"
                               + (" (implausibly small, a unit error on the layer: not used)" if gis_bad else ""))
    p.land_class = _s(a, "parusedesc") or None
    p.improved = _s(a, "struct") or None
    p.tax_value, p.land_value, p.building_value = _num(a.get("parval")), _num(a.get("landval")), _num(a.get("improvval"))
    vtype = _s(a, "parvaltype")
    p.value_note = (f"tax value as the statewide layer publishes it (parval; the layer calls it "
                    f"'{vtype or 'not stated'}'), not a market price. The statewide layer is a periodic copy of the "
                    f"county roll: the county's own tax record can show a different, later figure")
    p.deed_ref_text = _s(a, "sourceref") or None
    kind, book, page = parse_ref(p.deed_ref_text)
    p.deed_book, p.deed_page = book, page
    if kind:
        p.deed_instrument = kind
    p.deed_date_text = _s(a, "sourcedatx") or None
    p.deed_date = layer_date(p.deed_date_text)
    legal = _s(a, "legdecfull")
    as_ref = legal_as_deed_ref(legal) if legal else None
    if as_ref is not None:
        p.extra["legdecfull_holds_deed_ref"] = legal
        if not p.deed_book:
            p.deed_book, p.deed_page = as_ref[0] or None, as_ref[1]
            p.deed_ref_text = f"{legal} (from the layer's legal field, which holds the deed reference here)"
            if as_ref[2] and not p.deed_date:
                y = as_ref[2]
                p.deed_date = y if len(y) == 4 else None
                p.deed_date_text = p.deed_date_text or f"year {y}"
    elif legal:
        p.legal_description, p.legal_field, p.legal_kind = legal, "legdecfull", "assessor_short"
    mk, pb, pp = parse_ref(_s(a, "mapref"))
    if (mk or "").lower() == "plat" and pb:
        p.plat_book, p.plat_page = pb, pp
    elif _s(a, "mapref"):
        p.extra["mapref"] = _s(a, "mapref")
    pl = re.search(r"\bPL\s*:\s*([A-Z]?\d+)\s*-\s*(\d+[A-Z]?)\b", p.legal_description or "")
    if not p.plat_book and pl and _z(pl.group(1)):
        # Cumberland writes the plat inside the short legal ('... LO:19 PL:0056-0078') and leaves mapref blank
        p.plat_book, p.plat_page = _z(pl.group(1)), _z(pl.group(2))
        p.extra["plat_from_legal"] = True
    p.subdivision = _s(a, "subdivisio") or None
    p.layer_updated = layer_date(_s(a, "revdatetx"))
    p.extra.update({"parno": _s(a, "parno"), "altparno": _s(a, "altparno"), "nparno": _s(a, "nparno"),
                    "cntyname": _s(a, "cntyname"), "information_source": _s(a, "sourceagnt"),
                    "owner_field": own, "second_owner_field": own2, "last_sale_date": _s(a, "saledatetx"),
                    "present_use_value": _s(a, "presentval"), "owner_type": _s(a, "owntype"),
                    "structure_year": a.get("structyear")})
    return p


# ---------------------------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------------------------

class NcOneMapAdapter(CountyAdapter):
    """One NC county, any of the 100: use NcOneMapAdapter.for_county('Henderson')."""
    state = "NC"
    county = ""
    register_fetched = False
    parcel_record_label = "Parcel record (NC OneMap statewide parcel layer)"
    marked_roll_order = "last_first"

    @classmethod
    def for_county(cls, county: str) -> type["NcOneMapAdapter"]:
        canon = canonical_county(county)
        if not canon:
            raise ValueError(f"not a North Carolina county: {county!r}")
        return type(f"NcOneMap{re.sub(r'[^A-Za-z]', '', canon)}Adapter", (cls,), {"county": canon})

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.record = county_record(self.county, "NC") or {}

    # -- parcel ------------------------------------------------------------------------------
    def _query(self, where: str, label: str, slug: str, note: str = "") -> tuple[list[dict], list[str], Any]:
        params = {"where": where, "outFields": ",".join(OUT_FIELDS), "returnGeometry": "false", "f": "json"}
        person = ONEMAP_LAYER + "/query?" + urlencode({**params, "f": "html"})
        ex = self.new_exhibit(label, SRC_ONEMAP, person, shot_kind="gis_json",
                              note=note or "Opens the statewide layer's query page with the same request.")
        err = None
        resp = None
        # the layer can answer HTTP 200 with an error body when busy: one retry after a pause, then fail
        for wait in RETRY_WAITS:
            if wait:
                self.f._sleep(wait)
            resp = self.f.get(ONEMAP_LAYER + "/query", params=params, tag="onemap")
            try:
                j = resp.json()
            except ValueError as exc:
                err = exc
                continue
            if not isinstance(j, dict) or "error" in j:
                err = ValueError(f"ArcGIS error body: {str(j.get('error') if isinstance(j, dict) else j)[:200]}")
                continue
            raw = [f.get("attributes") or {} for f in j.get("features") or []]
            feats = [drop_sensitive(a) for a in raw]
            fields = [f.get("name") for f in j.get("fields") or [] if f.get("name")]
            if any(len(a) != len(b) for a, b in zip(raw, feats)):
                # a column that looks like an SSN, licence or birth date came back although it was not
                # asked for: the saved exhibit is the response without it, and the sheet says so
                for f, kept in zip(j.get("features") or [], feats):
                    f["attributes"] = kept
                j["fields"] = [f for f in j.get("fields") or [] if not is_sensitive_field(f.get("name"))]
                self.f.exhibit(ex, resp, None)
                ex.files.append(self.f.save(self.file_name(ex, slug, "json"), json.dumps(j)))
                ex.note = (ex.note or "") + " Saved without the identifier columns the layer returned unasked."
                fields = [n for n in fields if not is_sensitive_field(n)]
            else:
                self.keep(ex, resp, slug, "json")
            return feats, fields, ex
        self.keep(ex, resp, slug, "json")
        raise RuntimeError(f"the statewide parcel layer answered with an error {len(RETRY_WAITS)} times ({err}); "
                           f"run the intake again later")

    def parcel(self, pin: str) -> Parcel:
        feats, fields, ex = self._query(parcel_where(self.county, pin),
                                        f"Statewide parcel record for PIN {pin} ({self.county} County)",
                                        "onemap_parcel")
        a, note = pick_feature(pin, feats)
        if a is None:
            p = Parcel(pin=pin, exhibit=ex.key, found=False, field_names=fields, layer_label=LAYER_LABEL)
            p.extra["join_note"] = note
            return p
        p = parcel_from_onemap(pin, a, fields)
        p.exhibit = ex.key
        p.extra["join_note"] = note
        return p

    def parcels_at_mailing_number(self, parcel: Parcel) -> tuple[list[OtherParcel], str]:
        hn, st = parcel.mailing_house_number, parcel.mailing_street
        if not hn or not st:
            return [], "The mailing address has no house number on a road (or is a post office box); not checked."
        if parcel.situs_house_number == hn and (parcel.situs_street or "").upper() == st:
            return [], "The mailing address is the parcel's own situs."
        if (parcel.situs_street or "").upper() != st:
            return [], (f"The mailing address is on a different road ({st}) from the parcel's situs "
                        f"({parcel.situs_street or 'none'}); not checked.")
        where = f"cntyname='{self.county}' AND siteadd LIKE '{hn} %{st.replace(chr(39), chr(39) * 2)}%'"
        feats, _, ex = self._query(where, f"Statewide parcel record(s) at house number {hn} on {st} (the mailing "
                                          f"address's number)", f"mailing_number_{hn}")
        out = []
        for a in feats:
            if street_key(_s(a, "siteadd")) != (hn, st):
                continue
            q = parcel_from_onemap(_s(a, "parno"), a, [])
            deed = f"book {q.deed_book} page {q.deed_page or '?'}" if q.deed_book else None
            out.append(OtherParcel(pin=q.pin, situs=q.situs or "", owner=q.owner, improved=q.improved, deed=deed))
        return out, (f"Searched the statewide layer for house number {hn} on {st} (Exhibit {ex.key}): "
                     f"{len(out)} parcel(s) at that address.")

    # -- tax: not read for these counties ------------------------------------------------------
    def tax(self, parcel: Parcel, today: date) -> TaxStatus:
        t = (self.record.get("tax") or {})
        site = t.get("url") or "the county tax office"
        return TaxStatus(fetched=False, interest_rule=("In North Carolina a levy year's bill is due September 1 and "
                                                       "interest begins January 6 of the following year."),
                         note=(f"Tax bills are not fetched by the tool for {self.county} County. A person reads them "
                               f"on the county tax site: {site}."))

    # -- register: not searched for these counties ---------------------------------------------
    def register_link(self) -> Optional[str]:
        return (self.record.get("rod") or {}).get("url")

    def deed_at(self, book: str, page: str, label: Optional[str] = None) -> tuple[list[Instrument], str]:
        return [], self.register_link() or ""

    def deed_detail(self, inst: Instrument) -> Optional[str]:
        return None

    def name_search(self, purpose: str, person: PersonName | str, *, side: str = "both",
                    date_from: str = "", date_thru: str = "") -> NameSearch:
        last = person.last if isinstance(person, PersonName) else str(person)
        first = person.first if isinstance(person, PersonName) else ""
        return NameSearch(purpose=purpose + " (not fetched by the tool: use the register link)", last=last,
                          first=first, side=side, date_from=date_from, date_thru=date_thru)

    def death_search(self, person: PersonName, reading: str) -> DeathSearch:
        return DeathSearch(person=person.indexed(), reading=reading, last=person.last, first=person.first)

    # -- obituaries: searches a person runs ----------------------------------------------------
    def obituary(self, people: list[PersonName]) -> dict:
        searches = []
        for p in people[:2]:
            full = " ".join(p.given + [p.last]).title()
            searches += [f'legacy.com obituary search: first name "{p.first.title()}", last name "{p.last.title()}", '
                         f'state North Carolina',
                         f'Web search: "{full}" obituary "{self.county} County"']
        return {"run": False,
                "reason": ("Not run by this tool for this county. Obituary search sites answer automated requests "
                           "with a block, and memorial-index sites whose terms bar automated searching are not used. "
                           "A person runs the searches listed."),
                "searches": searches}

    # -- words -------------------------------------------------------------------------------
    def static_records(self) -> list[RecordCheck]:
        w = where_to_look(self.county, "NC")
        rod = w.rod_url or "the county register of deeds"
        return [
            RecordCheck("Probate and estate files (Clerk of Superior Court, Estates)", "walled",
                        "NC eCourts estates search: CAPTCHA in front of the search. Not queried.",
                        "Whether an estate was opened, who qualified, any list of heirs: not known from this sheet."),
            RecordCheck("Court files: special proceedings, civil judgments, tax foreclosure (Clerk of Superior Court)",
                        "walled", "NC eCourts: CAPTCHA in front of the search. Not queried.",
                        "Whether a court action names this parcel or its owner: not known from this sheet."),
            RecordCheck("Deed images (the deeds themselves, including the full legal description)", "not opened",
                        f"Not fetched by the tool for this county. Register: {rod}.",
                        "The full legal description must be read from the deed image."),
            RecordCheck("Microfilm, old books and maps not online", "not checked",
                        "Not reachable by this tool. " + (f"The register's online index goes back to {w.rod_back_to}."
                                                         if w.rod_back_to else "The register does not state how far "
                                                                               "back its online index goes."),
                        "Anything recorded only in older books is not covered; records older than about 70 years "
                        "need an abstractor."),
        ]

    def how_to(self, result) -> list[tuple[str, list[str]]]:
        w = where_to_look(self.county, "NC")
        pin = result.parcel.pin if result.parcel and result.parcel.found else result.pin
        out = [
            ("Parcel record (statewide layer)", [
                "Open the query link given for the parcel exhibit in a browser; it runs the same request on the "
                "statewide layer's own query page.",
                f"Or open {ONEMAP_LAYER}/query, type cntyname='{self.county}' AND parno='{pin}' in Where, list the "
                f"fields in Out Fields, choose JSON or HTML, and press Query (GET).",
                "Read ownname (taxpayer of record), siteadd (situs), mailadd/mcity/mstate/mzip (mailing), sourceref "
                "(the deed the assessor cites), sourcedatx (its date), legdecfull (the short assessor legal), "
                "mapref (plat), gisacres and parval (the tax value).",
            ]),
            ("Register of Deeds: the deed and the chain (a person)", [
                f"Open {w.rod_url or 'the county register of deeds'} ({w.rod_platform or 'platform not recorded'}).",
                f"Person needed: {w.rod_person_needed or 'see the where-to-look block'}.",
                "Search by book and page for the deed the statewide layer cites, open it, and read the full legal "
                "description on the deed image. Then search the grantor's name as grantee for the deed before it, "
                "and so on back.",
            ] + ([w.manual_lane] if w.manual_lane else [])),
            ("Tax bills (a person)", [
                f"Open {w.tax_url or 'the county tax office site'} and search by the parcel number.",
                f"Person needed: {w.tax_person or 'not recorded'}.",
            ]),
            ("Probate and court files (walled, done by a person)", [
                f"Open the NC eCourts portal ({w.probate_url or ECOURTS}), Smart Search, and pass its CAPTCHA.",
                f"Search Estates in {self.county} County for each owner-of-record name, and civil / special "
                f"proceedings for the parcel's owner.",
            ]),
        ]
        return out

    def sources(self) -> list[tuple[str, str, str]]:
        w = where_to_look(self.county, "NC")
        out = [(SRC_ONEMAP, ONEMAP_LAYER, "Free public map service (ArcGIS), no login, no key.")]
        if w.rod_url:
            out.append((f"{self.county} County Register of Deeds ({w.rod_platform or 'platform not recorded'})",
                        w.rod_url, f"Not fetched by this tool. Person needed: {w.rod_person_needed}."))
        if w.tax_url:
            out.append((f"{self.county} County tax site", w.tax_url,
                        f"Not fetched by this tool. Person needed: {w.tax_person}."))
        out.append(("NC eCourts (estates, special proceedings, civil)", w.probate_url or ECOURTS,
                    "CAPTCHA in front of the search: walled, not queried."))
        return out

    def not_established(self) -> list[str]:
        return ["The full legal description: the statewide layer carries at most the assessor's short legal "
                "(legdecfull), which is not the deed's legal description, and the deed image was not opened.",
                "The deed chain: this county's register was not searched by the tool; the deed reference is the one "
                "the assessor cites on the statewide layer, not checked against the register's index.",
                "Tax bills and amounts due: not read for this county."]
