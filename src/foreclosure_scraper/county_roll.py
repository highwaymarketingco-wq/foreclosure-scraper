"""Load a county assessor/auditor roll file (obtained by public-records request) into the parcel
cache's roll sidecar, data/parcel_cache/<county>.roll.sqlite, so the existing cache join
(parcel_cache_join, run by enrich_gis_attrs every pipeline run, and
scripts/join_parcel_cache_to_board.py) fills board rows' owner mailing address, values and facts.

Files arrive in /Users/cashhigh/Desktop/Records_Requests/Received/ as
<ST>_<County>_roll_<YYYY-MM-DD>.<ext> (the packet README): delimited text (comma, tab, pipe,
semicolon), fixed-width text, .xlsx, or a .zip holding one of those. The CLI is
scripts/ingest_county_roll.py.

WHAT IT DOES
  * read_table      sniffs the format; fixed-width columns come from a mapping JSON
                    ("fixed_width") or are inferred from the header line's column starts.
  * every header set goes through sensitive_fields.is_sensitive_field FIRST: an SSN, driver
    licence or birth-date column is dropped before any value is read, whatever the file holds.
  * detect_mapping  maps headers to the cache schema by common county column names (parcel /
                    TMS / PIN / REID / account / bill number; owner; owner mailing street, city,
                    state, ZIP; situs; land use; assessed and market value; year built; beds;
                    baths; sqft; stories; last sale date and price; acreage). A small per-county
                    JSON override replaces any role ({"id": [...], "owner": "OWNER_NAME", ...}).
  * write_roll      indexes each parcel under every id column and every id variant
                    (parcel_cache._id_variants, the same indexing refresh_county uses, so the
                    board's dashed / zero-padded / 10-vs-15-digit shapes all resolve), stamps
                    prov='county_roll_request' and the file's date, and replaces the sidecar
                    atomically. Re-running the same file produces the same sidecar (idempotent);
                    several files for one county go in one run.

The sidecar sits BESIDE the layer cache, never in it: the weekly layer refresh rebuilds
<county>.sqlite and cannot touch a roll, and parcel_cache.lookup lets the roll fill only what the
layer lacks (Beaufort SC: a roll merges with beaufort_sc.sqlite instead of replacing it; Hyde,
Washington, Perquimans NC: the roll's account / REID / bill-number columns become extra keys).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from . import parcel_cache as pc
from .sensitive_fields import is_sensitive_field

SC_COUNTIES = ("Abbeville", "Aiken", "Allendale", "Anderson", "Bamberg", "Barnwell", "Beaufort",
               "Berkeley", "Calhoun", "Charleston", "Cherokee", "Chester", "Chesterfield",
               "Clarendon", "Colleton", "Darlington", "Dillon", "Dorchester", "Edgefield",
               "Fairfield", "Florence", "Georgetown", "Greenville", "Greenwood", "Hampton", "Horry",
               "Jasper", "Kershaw", "Lancaster", "Laurens", "Lee", "Lexington", "McCormick",
               "Marion", "Marlboro", "Newberry", "Oconee", "Orangeburg", "Pickens", "Richland",
               "Saluda", "Spartanburg", "Sumter", "Union", "Williamsburg", "York")

DATA_EXT = (".csv", ".txt", ".tsv", ".dat", ".prn", ".psv", ".xlsx", ".asc")


def canonical_county(county: str, state: str) -> str:
    """The cache's spelling of a county name; ValueError for a name that is not a county
    of that state (a typo must not create a stray cache file)."""
    st = (state or "").strip().upper()
    c = (county or "").replace(" County", "").strip()
    if st == "NC":
        canon = pc._nc_name_ci(c)
    elif st == "SC":
        canon = {n.lower(): n for n in SC_COUNTIES}.get(c.lower())
    else:
        raise ValueError(f"state must be NC or SC, got {state!r}")
    if not canon:
        raise ValueError(f"{county!r} is not a {st} county")
    return canon


# ------------------------------------------------------------------------------- reading

def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _pick_zip_member(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(DATA_EXT)
             and not n.split("/")[-1].startswith((".", "__"))]
    if not names:
        raise ValueError("zip holds no csv/txt/xlsx data file")
    return max(names, key=lambda n: zf.getinfo(n).file_size)


def infer_fixed_width(header_line: str) -> list[tuple[str, int, int]]:
    """Columns of a fixed-width file from its header line: a column starts where a header token
    starts after two or more spaces (single spaces stay inside a header such as 'OWNER NAME')."""
    starts = [m.start() for m in re.finditer(r"(?:^|(?<=\s{2}))\S", header_line.rstrip("\n"))]
    cols = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else None
        name = header_line[s:e].strip() if e else header_line[s:].strip()
        cols.append((name, s, e if e is not None else 10 ** 6))
    return cols


def _layout(spec) -> list[tuple[str, int, int]]:
    """A mapping's "fixed_width": [[name, start0, end0], ...] or
    [{"name":..., "start": 1-based, "length": n}, ...]."""
    out = []
    for c in spec:
        if isinstance(c, dict):
            s = int(c["start"]) - 1
            out.append((c["name"], s, s + int(c["length"])))
        else:
            out.append((c[0], int(c[1]), int(c[2])))
    return out


def read_table(path: Path | str, *, override: Optional[dict] = None
               ) -> tuple[list[str], list[list[str]], str]:
    """(headers, rows, format) for one roll file. Format is 'xlsx', 'delimited:<d>' or
    'fixed'. Header cells are whitespace-squashed; rows are padded to the header width."""
    override = override or {}
    p = Path(path)
    raw = p.read_bytes()
    name = p.name
    if raw[:2] == b"PK" and not name.lower().endswith(".xlsx"):
        zf = zipfile.ZipFile(io.BytesIO(raw))
        name = _pick_zip_member(zf)
        raw = zf.read(name)
    if raw[:2] == b"PK":
        from .scrapers._xlsx_stdlib import read_rows
        rows = read_rows(raw, int(override.get("sheet", 1)))
        hi = next((i for i, r in enumerate(rows[:30]) if sum(1 for c in r if str(c).strip()) >= 3), 0)
        headers = [re.sub(r"\s+", " ", str(c)).strip() for c in rows[hi]] if rows else []
        body = [list(r) + [""] * (len(headers) - len(r)) for r in rows[hi + 1:]]
        return headers, body, "xlsx"
    if name.lower().endswith(".xls"):
        raise ValueError("legacy .xls is not read: open it in a spreadsheet app and save as .xlsx or .csv")
    text = _decode(raw)
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return [], [], "empty"
    if override.get("fixed_width"):
        layout = _layout(override["fixed_width"])
        has_header = bool(override.get("fixed_width_header", True))
        body_lines = lines[1:] if has_header else lines
        headers = [n for n, _s, _e in layout]
        body = [[ln[s:e].strip() for _n, s, e in layout] for ln in body_lines if ln.strip()]
        return headers, body, "fixed"
    delim = override.get("delimiter")
    if not delim:
        head = lines[0]
        counts = {d: head.count(d) for d in (",", "\t", "|", ";")}
        best = max(counts, key=counts.get)
        delim = best if counts[best] >= 2 else None
    if delim:
        rdr = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
        rows = [r for r in rdr]
        headers = [re.sub(r"\s+", " ", h).strip() for h in rows[0]]
        body = [list(r) + [""] * (len(headers) - len(r)) for r in rows[1:] if any(c.strip() for c in r)]
        return headers, body, f"delimited:{'TAB' if delim == chr(9) else delim}"
    layout = infer_fixed_width(lines[0])
    headers = [n for n, _s, _e in layout]
    body = [[ln[s:e].strip() for _n, s, e in layout] for ln in lines[1:] if ln.strip()]
    return headers, body, "fixed"


# ------------------------------------------------------------------------------- mapping

def _n(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


#: role -> ordered regexes on the normalised header. First unused match wins.
_ROLE_PATTERNS: dict[str, list[str]] = {
    "id": [r"^(parcel(id|no|num|number)?|pin(number|no)?|tms(number|no)?|taxmap(number|no)?|"
           r"mapnumber|parno|nparno|altparno|reid|realestateid|parcelnumber|taxparcel(id)?|"
           r"propertyid|propid|account(number|no|num)?|acct(no|num|number)?|billnumber|billno|"
           r"gpin|parcelkey|mapblockparcel|mbp)$"],
    "owner1": [r"^(owner|ownername|owner1|ownername1|name1|primaryowner|taxpayer(name)?|"
               r"taxpayername1|currentowner|name)$"],
    "owner2": [r"^(owner2|ownername2|name2|secondaryowner|coowner|taxpayername2)$"],
    "mail_single": [r"^(mailingaddress|owneraddress|mailaddress|fullmailingaddress)$"],
    "mail_street": [r"^(mail(ing)?(address|addr|street)1?|owner(mailing)?addr(ess)?1|"
                    r"taxpayeraddress(line)?1?|address1|addr1|mailstreet)$"],
    "mail_street2": [r"^(mail(ing)?(address|addr|street)2|owner(mailing)?addr(ess)?2|"
                     r"taxpayeraddress(line)?2|address2|addr2)$"],
    "mail_city": [r"^(mail(ing)?city|ownercity|taxpayercity|city)$"],
    "mail_state": [r"^(mail(ing)?(state|st)|ownerstate|taxpayerstate|state|st)$"],
    "mail_zip": [r"^(mail(ing)?(zip|zipcode|postal(code)?)|ownerzip|taxpayerzip|zip|zipcode|zip5|postalcode)$"],
    "mail_citystatezip": [r"^(citystatezip|cityst(ate)?zip|mail(ing)?citystatezip|csz)$"],
    "situs": [r"^(situs(address)?|propertyaddress|physicaladdress|locationaddress|siteaddress|"
              r"propaddr(ess)?|location|propertylocation|siteadd|situsaddr)$"],
    "situs_num": [r"^(situs|street|house|prop|site|location)?(number|num|no)$", r"^(stnum|streetnumber|housenumber)$"],
    "situs_street": [r"^(situs|prop|site|location)?(streetname|street|stname)$"],
    "land_use": [r"^(landuse(code|desc(ription)?)?|propertyclass|classcode|propertytype|usecode|"
                 r"proptype|landusedesc|class)$"],
    "market_value": [r"^(market(value|val|total)?|totalmarketvalue|appraisedvalue|appraised|"
                     r"totalappraisal|totalvalue|fairmarketvalue|fmv|marketvaluetotal|totval)$"],
    "tax_value": [r"^(assessed(value)?|assessment|totalassessed|taxablevalue|taxable|"
                  r"assessedvaluetotal|taxvalue)$"],
    "acreage": [r"^(acres|acreage|deededacres|totalacres|calcacres|gisacres|acre)$"],
    "living_sqft": [r"^(sqft|squarefeet|heatedsqft|heatedarea|livingarea|finishedsqft|"
                    r"totalsqft|bldgsqft|heatedsquarefeet|grosssqft)$"],
    "year_built": [r"^(yearbuilt|yrbuilt|yearblt|yrblt|actualyearbuilt|effyearbuilt|built)$"],
    "bedrooms": [r"^(bedrooms|beds|bedrms|nbrbedrooms|numbedrooms|bedroom)$"],
    "baths_full": [r"^(bathrooms|baths|fullbaths|bathrms|nbrfullbath|numbaths|fullbath)$"],
    "baths_half": [r"^(halfbaths|halfbath|nbrhalfbath|hbaths)$"],
    "stories": [r"^(stories|story|storyheight|numstories|floors)$"],
    "sale_price": [r"^(saleprice|lastsaleprice|saleamount|salesamt|consideration|saleamt|price)$"],
    "sale_date": [r"^(saledate|lastsaledate|deeddate|saledt|dateofsale|transferdate)$"],
}
_SINGLE = [r for r in _ROLE_PATTERNS if r != "id"]


@dataclass
class Mapping:
    roles: dict[str, Any] = field(default_factory=dict)   # role -> header or [headers]

    def to_cache_specs(self) -> dict[str, Any]:
        """Cache column -> _map_val spec (a header name, a list of headers, or a baths dict)."""
        r = self.roles
        specs: dict[str, Any] = {}
        owners = [h for h in (r.get("owner1"), r.get("owner2")) if h]
        if owners:
            specs["owner"] = owners if len(owners) > 1 else owners[0]
        if r.get("mail_single"):
            specs["owner_mailing"] = r["mail_single"]
        else:
            parts = [r.get(k) for k in ("mail_street", "mail_street2", "mail_city", "mail_state",
                                        "mail_zip", "mail_citystatezip")]
            parts = [p for p in parts if p]
            if parts and (r.get("mail_street") or r.get("mail_street2")):
                specs["owner_mailing"] = parts
        if r.get("situs"):
            specs["address"] = r["situs"]
        elif r.get("situs_num") and r.get("situs_street"):
            specs["address"] = [r["situs_num"], r["situs_street"]]
        for c in ("land_use", "market_value", "tax_value", "acreage", "living_sqft", "year_built",
                  "bedrooms", "stories", "sale_price", "sale_date"):
            if r.get(c):
                specs[c] = r[c]
        if r.get("baths_full"):
            specs["bathrooms"] = ({"baths": [r["baths_full"], r["baths_half"]]} if r.get("baths_half")
                                  else r["baths_full"])
        return specs


def safe_headers(headers: Iterable[str]) -> list[str]:
    """Headers with every SSN / licence / birth-date column removed."""
    return [h for h in headers if h and not is_sensitive_field(h)]


def detect_mapping(headers: Iterable[str], override: Optional[dict] = None) -> Mapping:
    hs = safe_headers(headers)
    used: set[str] = set()
    roles: dict[str, Any] = {}
    ids = [h for h in hs if any(re.match(p, _n(h)) for p in _ROLE_PATTERNS["id"])]
    roles["id"] = ids
    used.update(ids)
    for role in _SINGLE:
        for pat in _ROLE_PATTERNS[role]:
            hit = next((h for h in hs if h not in used and re.match(pat, _n(h))), None)
            if hit:
                roles[role] = hit
                used.add(hit)
                break
    # A lone "address1/city/state/zip" block with no situs columns is the owner's mailing block
    # in every roll layout seen; a file that also labels a situs keeps both. Nothing to undo here.
    for k, v in (override or {}).items():
        if k in ("fixed_width", "fixed_width_header", "delimiter", "sheet"):
            continue
        if k == "id":
            v = v if isinstance(v, list) else [v]
            v = [h for h in v if not is_sensitive_field(h)]
        elif isinstance(v, str) and is_sensitive_field(v):
            continue
        roles[k] = v
    return Mapping(roles)


# ------------------------------------------------------------------------------- writing

_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y%m%d", "%m-%d-%Y", "%d-%b-%Y", "%d-%b-%y",
                 "%b %d %Y", "%Y/%m/%d")


def parse_date(v) -> Optional[str]:
    """ISO date from the shapes rolls use ('03/14/2019', '20190314', an Excel serial, ISO)."""
    s = str(v or "").strip()
    if not s or s in ("0", "00000000"):
        return None
    s = s.split(" ")[0] if re.match(r"\d{1,2}/\d{1,2}/\d{2,4} ", s) else s
    if re.fullmatch(r"\d{5}(\.0+)?", s):
        n = int(float(s))
        if 20000 < n < 80000:
            return (date(1899, 12, 30) + timedelta(days=n)).isoformat()
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        return d.isoformat() if 1850 <= d.year <= 2100 else None
    return None


_FILE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def file_date(path: Path | str) -> str:
    """The roll's date: the YYYY-MM-DD in its name (<ST>_<County>_roll_<YYYY-MM-DD>.ext), else
    the file's modification date."""
    m = _FILE_DATE.search(Path(path).name)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(Path(path).stat().st_mtime).date().isoformat()


@dataclass
class RollRecords:
    rows: list[tuple] = field(default_factory=list)   # (id, *_COLS values)
    stats: dict[str, int] = field(default_factory=dict)


def build_records(headers: list[str], body: list[list[str]], mapping: Mapping) -> RollRecords:
    """Cache rows (one per id variant) from a roll's rows. Sensitive columns never leave this
    function: each row dict is built from the safe headers only."""
    keep = [(i, h) for i, h in enumerate(headers) if h and not is_sensitive_field(h)]
    specs = mapping.to_cache_specs()
    ids = list(mapping.roles.get("id") or [])
    out = RollRecords()
    st = {"rows": 0, "rows_with_id": 0, "parcels_indexed": 0}
    for c in pc._COLS:
        st[c] = 0
    seen_keys: set[str] = set()
    for r in body:
        st["rows"] += 1
        rec = {h: (r[i] if i < len(r) else "") for i, h in keep}
        keys: set[str] = set()
        for f in ids:
            keys |= pc._id_variants(rec.get(f))
        if not keys:
            continue
        st["rows_with_id"] += 1
        vals = []
        for c in pc._COLS:
            v = pc._map_val(rec, c, specs.get(c))
            if c == "sale_date":
                # Read the cell itself: _map_val's epoch-ms rule turns "20200101" into None.
                cell = rec.get(specs[c]) if isinstance(specs.get(c), str) else v
                v = parse_date(cell) or (v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v or "")) else None)
            if c == "sale_price" and v is not None:
                v = pc._num(v)
                v = v if v and v > 0 else None
            if c in ("year_built", "bedrooms", "bathrooms", "stories") and v is not None and v <= 0:
                v = None
            if v not in (None, ""):
                st[c] += 1
            vals.append(v)
        fresh = keys - seen_keys
        if not fresh:
            continue
        seen_keys |= fresh
        st["parcels_indexed"] += 1
        out.rows.extend((k, *vals) for k in sorted(fresh))
    out.stats = st
    return out


def write_roll(county: str, state: str, records: RollRecords, prov_date: str,
               cache_dir: Optional[Path] = None) -> Path:
    """Replace the county's roll sidecar with `records` (atomic). Same input -> same file."""
    canon = canonical_county(county, state)
    base = cache_dir or pc.CACHE_DIR
    target = base / pc.roll_db_path(canon, state).name
    base.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute(pc.PARCELS_DDL)
    pc.ensure_columns(con, extra=pc.ROLL_PROV_COLS)
    cols = ["id", *pc._COLS, *pc.ROLL_PROV_COLS]
    con.executemany(f"INSERT INTO parcels({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [(*row, pc.ROLL_PROVENANCE, prov_date) for row in records.rows])
    con.execute("CREATE INDEX idx_id ON parcels(id)")
    con.commit()
    con.close()
    old = pc._CONN.pop(target.name, None)      # a reader holding the old file must reopen
    if old is not None:
        old.close()
    tmp.replace(target)
    pc._CONN_COLS.pop(target.name, None)
    return target


def load_override(path: Optional[str]) -> dict:
    return json.loads(Path(path).read_text()) if path else {}
