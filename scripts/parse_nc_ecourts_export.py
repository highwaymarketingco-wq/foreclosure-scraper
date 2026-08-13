#!/usr/bin/env python
"""Parse a SAVED NC eCourts (Tyler / Odyssey Portal) search-results HTML file.

NC eCourts "Smart Search" / case-search is WAF + CAPTCHA walled to automation,
so we DON'T scrape it. Instead the operator runs the portal search in their own
browser (Smart Search by name / case-type, or the Hearing Search grid), saves the
results page to disk (Ctrl-S / "Save Page As"), and drops the .html file here.
This standalone parser reads that saved page and extracts one record per case:

    case_number, plaintiff, defendant, party_names, case_type, filing_date, county

then writes merge-ready JSON. It complements src/foreclosure_scraper/ingest_nc_court.py
(which handles CSV/TSV/pipe or copy-pasted grids) by handling a literally-saved .html
export — the third export shape an operator is likely to produce.

Compliant: the human operates the bot-walled search; we only parse the public HTML
they retrieved.

Odyssey markup varies by county / portal version, so selectors are deliberately
tolerant: we try (1) case-detail cards/divs (label -> value pairs), then
(2) tabular result rows (thead-mapped or positional), and finally fall back to a
regex sweep of visible text. Each strategy is best-effort; whatever fields it can
recover it emits.

Usage:
    # dump parsed cases as JSON to stdout
    uv run python scripts/parse_nc_ecourts_export.py results.html

    # write JSON to a file, stamping a default county for exports that omit it
    uv run python scripts/parse_nc_ecourts_export.py results.html \
        --county Buncombe --out cases.json

    # emit Listing-shaped dicts (owner_name/defendant/listing_type) ready to
    # merge onto the board via the name->property resolver
    uv run python scripts/parse_nc_ecourts_export.py results.html --as-listings
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Field vocabulary (tolerant). Compared after lowercasing + stripping non-alnum.
# --------------------------------------------------------------------------- #

# label text (in a detail card) -> normalized field
_LABEL_MAP = {
    "case_number": ("casenumber", "caseno", "case", "casenbr", "caseid",
                    "casenumbers", "casenumberdescription"),
    "case_type": ("casetype", "type", "casecategory", "category",
                  "casecategorytype", "casetypedescription"),
    "filing_date": ("filedate", "fileddate", "filingdate", "datefiled",
                    "filed", "hearingdate", "eventdate", "settingdate"),
    "county": ("county", "location", "locationname", "court",
               "courtlocation", "node"),
    "plaintiff": ("plaintiff", "petitioner", "state"),
    "defendant": ("defendant", "respondent"),
    "style": ("style", "casestyle", "caption", "title", "casetitle",
              "partyname", "parties", "party"),
}

# header text (in a result table) -> normalized field (same vocabulary)
_HEADER_MAP = dict(_LABEL_MAP)

_VS = re.compile(r"\bvs?\.?\b|\bversus\b|\bv\.\b", re.I)
_ENTITY = re.compile(
    r"\b(LLC|INC|CORP|TRUST|BANK|COUNTY|STATE OF|CITY OF|DEPT|DEPARTMENT|"
    r"ASSOC|COMPANY|CREDIT UNION|MORTGAGE|SERVICING|N\.?A\.?|CO\.?)\b", re.I)
# Odyssey NC case numbers: 24CV001234-590 / 24 CVD 1234 / 2024CVS000123
_CASE_RE = re.compile(r"\b(\d{2,4}\s?[A-Z]{2,4}\s?\d{3,7}(?:-\d{2,4})?)\b")
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
# Estate/special-proceeding captions carry boilerplate around the person's name.
# Handles the full family of NC estate / special-proceeding caption lead-ins:
#   "ESTATE OF X", "IN RE ESTATE OF X", "IN RE: ESTATE OF X",
#   "IN THE MATTER OF THE ESTATE OF X", "IN THE MATTER OF THE GUARDIANSHIP OF X",
#   "IN THE MATTER OF THE FORECLOSURE OF ..." — strips the leading "in re" /
#   "in the matter of", any "the", and up to two nested "<estate|matter|
#   guardianship|foreclosure|administration> of [the]" clauses, leaving the name.
_ESTATE_PREFIX_RE = re.compile(
    r"^\s*"
    r"(?:in\s+re:?\s*)?"
    r"(?:in\s+the\s+matter\s+of\s+)?"
    r"(?:the\s+)?"
    r"(?:(?:estate|matter|guardianship|foreclosure|administration)\s+of\s+(?:the\s+)?){0,2}",
    re.I)
_ESTATE_SUFFIX_RE = re.compile(
    r"[,\s]+(deceased|decedent|an?\s+incompetent|a\s+minor|estate)\.?\s*$", re.I)
# NC eCourts location labels are "<County> County" / "<County> District Court"
_COURT_SUFFIX_RE = re.compile(
    r"\s*(county|district|superior|civil|criminal|clerk of|"
    r"court(?:house)?|magistrate|division).*$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _txt(node) -> str:
    """Collapsed visible text of a BeautifulSoup node."""
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _map_label(label: str, table: dict) -> str | None:
    nk = _norm(label)
    if not nk:
        return None
    for field, variants in table.items():
        if nk in variants:
            return field
    # loose contains-match for compound labels ("Case Filing Date:")
    for field, variants in table.items():
        for v in variants:
            if v and (v in nk):
                return field
    return None


def _strip_court_suffix(loc: str) -> str:
    """'Buncombe County District Court' -> 'Buncombe'."""
    if not loc:
        return ""
    return _COURT_SUFFIX_RE.sub("", loc.strip()).strip(" ,-").strip()


def _split_parties(style: str) -> tuple[str | None, str | None, list[str]]:
    """'STATE vs JOHN DOE' -> (plaintiff, defendant, [all persons])."""
    parts = [p.strip(" ,;\t") for p in _VS.split(style or "") if p and p.strip(" ,;\t")]
    plaintiff = parts[0] if len(parts) >= 1 else None
    defendant = parts[1] if len(parts) >= 2 else None
    return plaintiff, defendant, parts


def _is_person(name: str) -> bool:
    n = re.sub(r"\s+", " ", (name or "")).strip(" ,;")
    return bool(n) and len(n) >= 3 and not n.replace(" ", "").isdigit() \
        and not _ENTITY.search(n)


# --------------------------------------------------------------------------- #
# Strategy 1 — case-detail cards. Odyssey renders each case as a block of
# label/value pairs. We look for common label containers and pair them with the
# adjacent value.
# --------------------------------------------------------------------------- #

def _parse_detail_cards(soup: BeautifulSoup) -> list[dict]:
    records: list[dict] = []
    # Candidate case containers: divs/sections whose class hints at a case card.
    containers = soup.select(
        "[class*='case'], [class*='Case'], [id*='case'], [id*='Case'], "
        "div.result, li.result, tr.k-master-row")
    seen_ids = set()
    for c in containers:
        if id(c) in seen_ids:
            continue
        seen_ids.add(id(c))
        rec: dict = {}
        # label/value pairs: <label|dt|th|span.label> ... <value>
        for lab in c.select(
                "label, dt, th, [class*='label'], [class*='Label'], "
                "[class*='fieldName'], [class*='caption']"):
            field = _map_label(_txt(lab), _LABEL_MAP)
            if not field:
                continue
            # value = the labeled sibling / paired cell / next node
            val_node = (lab.find_next_sibling(["dd", "td", "span", "div"])
                        or (lab.parent.find_next_sibling(["dd", "td"])
                            if lab.parent else None))
            val = _txt(val_node)
            if not val:
                # "Label: value" packed in one node
                whole = _txt(lab)
                if ":" in whole:
                    val = whole.split(":", 1)[1].strip()
            if val and field not in rec:
                rec[field] = val
        if _looks_useful(rec):
            records.append(rec)
    return records


def _looks_useful(rec: dict) -> bool:
    return bool(rec.get("case_number") or rec.get("style")
                or rec.get("defendant") or rec.get("plaintiff"))


# --------------------------------------------------------------------------- #
# Strategy 2 — result tables. thead maps columns to fields; otherwise positional.
# --------------------------------------------------------------------------- #

def _parse_result_tables(soup: BeautifulSoup) -> list[dict]:
    records: list[dict] = []
    for table in soup.find_all("table"):
        headers: list[str | None] = []
        head_row = table.find("thead")
        if head_row:
            headers = [_map_label(_txt(th), _HEADER_MAP)
                       for th in head_row.find_all(["th", "td"])]
        body = table.find("tbody") or table
        for tr in body.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells or (head_row and tr.find_parent("thead")):
                continue
            texts = [_txt(td) for td in cells]
            if not any(texts):
                continue
            rec: dict = {}
            if headers and any(headers):
                for i, val in enumerate(texts):
                    field = headers[i] if i < len(headers) else None
                    if field and val and field not in rec:
                        rec[field] = val
            else:
                # No header mapping — infer by cell content.
                joined = " ".join(texts)
                cm = _CASE_RE.search(joined)
                if cm:
                    rec["case_number"] = re.sub(r"\s+", " ", cm.group(1))
                for t in texts:
                    if _VS.search(t) and "style" not in rec:
                        rec["style"] = t
                dm = _DATE_RE.search(joined)
                if dm:
                    rec["filing_date"] = dm.group(1)
            if _looks_useful(rec):
                records.append(rec)
    return records


# --------------------------------------------------------------------------- #
# Strategy 3 — raw text fallback. Sweep visible text for case# + party style.
# --------------------------------------------------------------------------- #

def _parse_text_fallback(soup: BeautifulSoup) -> list[dict]:
    records: list[dict] = []
    text = soup.get_text("\n", strip=True)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        has_case = _CASE_RE.search(line)
        has_vs = _VS.search(line)
        if not (has_case or has_vs):
            continue
        rec: dict = {}
        if has_case:
            rec["case_number"] = re.sub(r"\s+", " ", has_case.group(1))
        if has_vs:
            rec["style"] = line
        dm = _DATE_RE.search(line)
        if dm:
            rec["filing_date"] = dm.group(1)
        if _looks_useful(rec):
            records.append(rec)
    return records


# --------------------------------------------------------------------------- #
# Normalization: raw field dicts -> clean per-case records.
# --------------------------------------------------------------------------- #

def _finalize(records: list[dict], default_county: str | None,
              default_case_type: str | None) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        plaintiff = rec.get("plaintiff")
        defendant = rec.get("defendant")
        parties: list[str] = []
        # Derive parties from a combined "style"/caption if present.
        style = rec.get("style")
        if style and (not plaintiff or not defendant) and _VS.search(style):
            # A raw text/grid line may pack the case# and a trailing date into
            # the style ("24CVD0042 SARAH LOWE vs DERRICK LOWE 06/01/2026").
            # Strip those so the party split yields clean person names.
            clean = _CASE_RE.sub(" ", style)
            clean = _DATE_RE.sub(" ", clean)
            p, d, allp = _split_parties(clean)
            plaintiff = plaintiff or p
            defendant = defendant or d
            parties = allp
        elif style and not plaintiff and not defendant:
            # Single-party caption with no "vs" — common for estates
            # ("In re: Estate of MARGARET P WHITMIRE", "MARGARET WHITMIRE,
            # Deceased"). Strip the boilerplate and keep the person as the
            # defendant/party-of-interest (the likely record owner).
            cap = _CASE_RE.sub(" ", style)
            cap = _DATE_RE.sub(" ", cap)
            cap = _ESTATE_PREFIX_RE.sub(" ", cap)
            cap = _ESTATE_SUFFIX_RE.sub(" ", cap)
            cap = re.sub(r"\s+", " ", cap).strip(" ,;")
            if _is_person(cap):
                defendant = cap
                parties = [cap]
        if not parties:
            parties = [x for x in (plaintiff, defendant) if x]
        # Keep only person party names (drop banks/state/entities) for resolve.
        person_parties = [re.sub(r"\s+", " ", p).strip(" ,;")
                          for p in parties if _is_person(p)]

        county = _strip_court_suffix(rec.get("county") or "") or default_county
        case_type = rec.get("case_type") or default_case_type
        case_number = rec.get("case_number")
        if case_number:
            case_number = re.sub(r"\s+", " ", case_number).strip()

        if not (case_number or person_parties):
            continue  # nothing resolvable

        out.append({
            "case_number": case_number,
            "plaintiff": plaintiff,
            "defendant": defendant,
            "party_names": person_parties,
            "case_type": case_type,
            "filing_date": rec.get("filing_date"),
            "county": county,
            "source": "nc_ecourts_manual",
        })

    # dedup on (case_number, defendant)
    seen, deduped = set(), []
    for r in out:
        key = (r.get("case_number") or "", (r.get("defendant") or "").upper(),
               "|".join(sorted(n.upper() for n in r["party_names"])))
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


# --------------------------------------------------------------------------- #
# Strategy 0 — Tyler "Smart Search" Kendo results grid. Its cells carry stable
# per-field classes (.party-case-caseid / -style / -type / -location /
# -partyname / -filedate), so we read those directly. This MUST run before the
# generic strategies: the grid's tr.k-master-row rows otherwise trip
# _parse_detail_cards into label/value garbage (case# <- style, defendant <-
# file date, county null — verified against a live 26SP* page). The `26SP*`
# foreclosure operator lane for the 10 NC-Courts-Portal counties depends on this.
# All SP rows are returned with an accurate case_type; the caller filters to
# case_type == "Foreclosure (Special Proceeding)" for the foreclosure lane.
# --------------------------------------------------------------------------- #

def _parse_smartsearch_grid(soup: BeautifulSoup) -> list[dict]:
    records: list[dict] = []
    for tr in soup.select("tr.k-master-row"):
        cid = tr.select_one(".party-case-caseid a") or tr.select_one(".party-case-caseid")
        if cid is None:
            continue  # not a Smart Search grid row
        case_number = (cid.get("title") or _txt(cid)).strip()
        if not case_number:
            continue

        def _cell(cls: str) -> str | None:
            el = tr.select_one(f".{cls}")
            return _txt(el) or None if el is not None else None

        fd = (tr.select_one(".party-case-filedate span[title]")
              or tr.select_one(".party-case-filedate"))
        filing_date = None
        if fd is not None:
            filing_date = (fd.get("title") or _txt(fd)) or None

        records.append({
            "case_number": re.sub(r"\s+", " ", case_number).strip(),
            "style": _cell("party-case-style"),
            "case_type": _cell("party-case-type"),
            "filing_date": filing_date,
            "county": _strip_court_suffix(_cell("party-case-location") or "") or None,
            "defendant": _cell("party-case-partyname"),
        })
    return records


def parse_nc_ecourts_html(html: str, default_county: str | None = None,
                          default_case_type: str | None = None) -> list[dict]:
    """Parse a saved Odyssey results page into per-case records.

    Returns a list of dicts:
      {case_number, plaintiff, defendant, party_names, case_type,
       filing_date, county, source}
    """
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Try strategies in order of specificity; use the first that yields records
    # (smart-search grid > cards > tables > text), so we don't double-count the
    # same cases parsed two different ways.
    for strategy in (_parse_smartsearch_grid, _parse_detail_cards,
                     _parse_result_tables, _parse_text_fallback):
        raw = strategy(soup)
        final = _finalize(raw, default_county, default_case_type)
        if final:
            return final
    return []


# --------------------------------------------------------------------------- #
# dict -> Listing adapter (mirrors nc_ecourts_estates._row_to_listing) so the
# name->property resolver (reads owner_name/defendant + county + listing_type)
# can consume the output directly.
# --------------------------------------------------------------------------- #

def _listing_type_for(case_type: str | None) -> str:
    """Map the eCourts case-type text to a board ListingType value so estates and
    divorce score as themselves, not as generic lis-pendens. Foreclosure/lien and
    anything unrecognized fall through to lis_pendens (the name-driven default)."""
    t = (case_type or "").lower()
    if "estate" in t or "decedent" in t:
        return "probate_notice"
    if "divorce" in t:
        return "divorce_notice"
    return "lis_pendens"


def record_to_listing_dict(rec: dict, slug: str = "counties_nc.nc_ecourts_manual") -> dict | None:
    """Turn one parsed case record into a Listing-shaped dict.

    We keep this as a plain dict (not a models.Listing instance) so this script
    stays import-light and standalone; the ingest CLI / merge step validates it
    into a Listing. Field parity with the rest of the pipeline:
      owner_name = defendant (the party who likely owns a home / is distressed)
      defendant  = defendant; plaintiff = plaintiff
    """
    defendant = rec.get("defendant")
    parties = rec.get("party_names") or []
    # Prefer an explicit defendant; else the first (or last) person party.
    owner = defendant or (parties[-1] if parties else None)
    if not owner and rec.get("plaintiff"):
        owner = rec["plaintiff"]
    if not owner and not rec.get("case_number"):
        return None

    case_number = rec.get("case_number")
    county = rec.get("county")
    case_type = rec.get("case_type") or "Court filing"
    return {
        "source": slug,
        "source_url": (
            f"https://portal-nc.tylertech.cloud/Portal/#/search?caseNumber={quote(case_number)}"
            if case_number else "https://portal-nc.tylertech.cloud/Portal/"
        ),
        "listing_type": _listing_type_for(case_type),  # estate/divorce/foreclosure-aware
        "property_kind": "unknown",
        "state": "NC",
        "county": county,
        "case_number": case_number,
        "owner_name": owner,
        "defendant": owner,
        "plaintiff": rec.get("plaintiff"),
        "description": (
            f"NC eCourts manual export: {case_type} {case_number or ''}"
            f"{(' in ' + county) if county else ''}".strip()
        ),
        "raw": {"nc_ecourts_manual": {k: rec.get(k) for k in (
            "case_number", "plaintiff", "defendant", "party_names",
            "case_type", "filing_date", "county")}},
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html_path", help="saved NC eCourts / Odyssey results .html file")
    ap.add_argument("--county", default=None,
                    help="default county to stamp when the export omits it")
    ap.add_argument("--case-type", default=None,
                    help="default case_type to stamp when the export omits it")
    ap.add_argument("--as-listings", action="store_true",
                    help="emit Listing-shaped dicts (owner_name/defendant/listing_type)")
    ap.add_argument("--out", default=None, help="write JSON here (default: stdout)")
    args = ap.parse_args()

    path = Path(args.html_path)
    if not path.exists():
        print(f"ERROR: no such file: {path}", file=sys.stderr)
        return 2
    html = path.read_text(encoding="utf-8", errors="replace")
    records = parse_nc_ecourts_html(html, default_county=args.county,
                                    default_case_type=args.case_type)

    if args.as_listings:
        payload = [d for d in (record_to_listing_dict(r) for r in records) if d]
    else:
        payload = records

    out_json = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        print(f"parsed {len(records)} case(s) -> {len(payload)} record(s), "
              f"wrote {args.out}", file=sys.stderr)
    else:
        print(out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
