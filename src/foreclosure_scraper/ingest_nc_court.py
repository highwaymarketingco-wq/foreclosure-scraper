"""Manual NC eCourts (Tyler) court-data ingest — the compliant NC court lane.

NC eCourts Smart Search is WAF-walled to automation, so we DON'T scrape it. Instead the operator runs
the portal's HEARING SEARCH by COURTROOM or JUDICIAL OFFICER (date-keyed, no names needed) for our
core counties, exports/copies the result grid, and drops it here. This parser normalizes those exports
into court records {name, county, case_no, case_type, hearing_type, date, role, source} which the
name->property resolver turns into scored motivated-seller leads (divorce / probate / criminal / civil).

Compliant: the human operates the bot-walled search; we only parse the public data they retrieved.
Tolerant by design — accepts a CSV/TSV export OR a raw copy-paste of the grid, and maps the many header
spellings Tyler/county portals use. Refine _FIELD_MAP against the first real export if a column is missed.
"""
from __future__ import annotations

import csv
import io
import re

# Normalized field -> accepted header spellings (compared after stripping non-alphanumerics, lowercased)
_FIELD_MAP = {
    "name": ("name", "party", "partyname", "defendant", "respondent", "petitioner", "plaintiff",
             "casestyle", "style", "caption", "parties", "partynames"),
    "case_no": ("caseno", "casenumber", "case", "casenbr", "caseid", "caseidnbr", "casenumbers"),
    "case_type": ("casetype", "type", "casecategory", "category", "casecategorytype"),
    "hearing_type": ("hearingtype", "hearing", "eventtype", "event", "settingtype", "proceeding"),
    "date": ("date", "hearingdate", "fileddate", "filed", "eventdate", "settingdate", "hearingdatetime"),
    "county": ("county", "location", "locationname", "court", "courtlocation"),
    "role": ("role", "partytype", "connection", "connectiontype"),
}
_VS = re.compile(r"\bvs?\.?\b|\bversus\b|\bv\.\b", re.I)
_ENTITY = re.compile(r"\b(LLC|INC|CORP|TRUST|BANK|COUNTY|STATE OF|CITY OF|DEPT|ASSOC|COMPANY|CO\.?)\b", re.I)


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (k or "").lower())


def _split_parties(style: str) -> list[str]:
    """'BRANDI CALDWELL vs JEREMIAH CALDWELL' -> ['BRANDI CALDWELL','JEREMIAH CALDWELL']."""
    parts = _VS.split(style or "")
    return [p.strip(" ,;\t") for p in parts if p and p.strip(" ,;\t")]


def parse_nc_court_export(raw: str, default_county: str | None = None,
                          default_case_type: str | None = None) -> list[dict]:
    """Normalize a Tyler hearing-search export (CSV/TSV or pasted grid) into court records."""
    raw = (raw or "").strip()
    if not raw:
        return []
    records: list[dict] = []

    # 1) Try delimited (CSV/TSV/pipe) with a header row.
    parsed_delimited = False
    try:
        dialect = csv.Sniffer().sniff(raw.splitlines()[0] + "\n" + (raw.splitlines()[1] if len(raw.splitlines()) > 1 else ""),
                                      delimiters=",\t|")
        reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
        if reader.fieldnames and len([f for f in reader.fieldnames if f]) > 1:
            keymap: dict[str, str] = {}
            for col in reader.fieldnames:
                nk = _norm_key(col)
                for field, variants in _FIELD_MAP.items():
                    if nk in variants:
                        keymap[col] = field
                        break
            if "name" in keymap.values():
                parsed_delimited = True
                for r in reader:
                    rec = {field: (r.get(col) or "").strip()
                           for col, field in keymap.items() if (r.get(col) or "").strip()}
                    if rec.get("name"):
                        records.append(rec)
    except Exception:  # noqa: BLE001
        pass

    # 2) Fallback: line-oriented paste — pull a case# + a party-style string per line.
    if not parsed_delimited:
        case_re = re.compile(r"\b(\d{2}\s?[A-Z]{2,3}\s?\d{2,6})\b")  # 24 CVD 1234 / 24CVD001234
        for line in raw.splitlines():
            line = line.strip()
            if not line or _VS.search(line) is None and not case_re.search(line):
                continue
            rec: dict = {}
            cm = case_re.search(line)
            if cm:
                rec["case_no"] = re.sub(r"\s+", " ", cm.group(1))
            # the party/style is the longest alpha run on the line
            rec["name"] = line
            records.append(rec)

    # 3) Expand parties + apply defaults -> one normalized record per resolvable person.
    out: list[dict] = []
    for rec in records:
        county = rec.get("county") or default_county
        ctype = rec.get("case_type") or default_case_type
        nm = rec.get("name", "")
        names = _split_parties(nm) if _VS.search(nm) else [nm.strip()]
        for n in names:
            n = re.sub(r"\s+", " ", n).strip(" ,;")
            if len(n) < 3 or n.replace(" ", "").isdigit() or _ENTITY.search(n):
                continue  # skip entities (banks/state) + junk — we want people who own homes
            out.append({
                "name": n, "county": county, "case_no": rec.get("case_no"),
                "case_type": ctype, "hearing_type": rec.get("hearing_type"),
                "date": rec.get("date"), "role": rec.get("role"),
                "source": "nc_ecourts_manual",
            })
    # dedup on (name, case_no)
    seen, deduped = set(), []
    for r in out:
        k = (r["name"].upper(), r.get("case_no"))
        if k not in seen:
            seen.add(k)
            deduped.append(r)
    return deduped
