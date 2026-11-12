"""Merge user-saved LiensNC search-results pages into the board (builder/investor distress).

LiensNC (NC Lien Agent System) is login-walled and its ToS bars automated querying, so the
data is gathered BY THE OPERATOR (logged-in, manual save) and this script only PARSES the
saved HTML offline — same compliant pattern as ingest_publicindex_files.py.

Results-table structure (mapped live 2026-08-17 from the authenticated Advanced Search page):
  columns = Filing (type + date) | Filed By | Project Property (name + address) | Owner
            (name + mailing) | Active Related Filings? (Yes/No) | Action

The DISTRESS SIGNAL is not a single Notice-to-Lien-Agent — it's a CLUSTER: a project with
"Active Related Filings? = Yes" (multiple contractors preserving lien rights on one job) or
the same address appearing on multiple rows = an over-leveraged flipper/builder running out of
capital, contractors lining up to file mechanic's liens = a motivated seller BEFORE bank
foreclosure. Those get a `builder_distress` signal; single isolated filings are kept but not flagged.

Board-writer — run ALONE, only when no other board writer holds the lock. Loads via
web_artifact.load_board() so the sidecar round-trips. Idempotent (dedupes by entry/address+owner).

    1. (You, logged in) run Advanced Search per NC county, last ~90 days, save each results
       page: Ctrl-S -> "Webpage, HTML only" into a folder.
    2. uv run python scripts/ingest_liensnc.py [dir ...]      (default scan: repo root + ~/Downloads)
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from selectolax.parser import HTMLParser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402
from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402
from foreclosure_scraper.name_normalize import normalize_name  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SCAN = [Path(p) for p in sys.argv[1:]] or [REPO, Path.home() / "Downloads"]

_HEADER_MAP = {   # fuzzy header -> our field
    "filing": "filing", "filed by": "filed_by", "project": "project",
    "owner": "owner", "related filings": "related", "action": "action",
}
_ADDR_RE = re.compile(r"\d{1,6}\s+[A-Za-z0-9.\- ]+(?:st|street|rd|road|ave|avenue|dr|drive|ln|lane|"
                      r"ct|court|way|hwy|highway|blvd|cir|circle|pl|place|ter|trl|trail|loop|pkwy)\b",
                      re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def _split_addr(cell: str) -> tuple[str | None, str | None]:
    """Project Property cell = 'Project Name\\n<street address, city ...>'. Pull the street addr."""
    parts = [p.strip() for p in re.split(r"[\n\r]+", cell) if p.strip()]
    name = parts[0] if parts else None
    addr = None
    for p in parts:
        m = _ADDR_RE.search(p)
        if m:
            addr = m.group(0).strip()
            break
    return name, addr


def _parse_file(path: Path) -> list[dict]:
    html = path.read_text(errors="ignore")
    if "lien agent" not in html.lower() and "advanced search" not in html.lower():
        return []
    tree = HTMLParser(html)
    out = []
    for table in tree.css("table"):
        rows = table.css("tr")
        if len(rows) < 2:
            continue
        heads = [c.text(strip=True).lower() for c in rows[0].css("th,td")]
        col = {}
        for i, h in enumerate(heads):
            # order matters: check the SPECIFIC 'related filings' before the generic 'filing'
            if "related" in h:
                col["related"] = i
            elif h.startswith("filing"):
                col["filing"] = i
            elif "filed by" in h:
                col["filed_by"] = i
            elif "project" in h:
                col["project"] = i
            elif h.startswith("owner"):
                col["owner"] = i
            elif "action" in h:
                col["action"] = i
        if "project" not in col:   # not the results table
            continue
        for r in rows[1:]:
            cells = r.css("td")
            if len(cells) < len(heads) - 1:
                continue
            def cell(f):
                i = col.get(f)
                return cells[i].text(separator="\n", strip=True) if i is not None and i < len(cells) else ""
            filing = cell("filing")
            name, addr = _split_addr(cell("project"))
            owner_cell = cell("owner")
            owner = re.split(r"[\n\r]", owner_cell)[0].strip() if owner_cell else None
            dm = _DATE_RE.search(filing)
            out.append({
                "filing_type": re.split(r"[\n\r]", filing)[0].strip() if filing else None,
                "filing_date": dm.group(1) if dm else None,
                "filed_by": cell("filed_by") or None,
                "project": name, "address": addr,
                "owner": owner, "owner_mailing": owner_cell or None,
                "related": "yes" in cell("related").lower(),
            })
    return out


def _to_listing(rec: dict, cluster: bool) -> Listing | None:
    if not rec.get("address"):
        return None
    now = datetime.utcnow()
    sale = None
    li = Listing(
        source="counties_generic.liensnc",
        source_url="https://www.liensnc.com/",
        state="NC",
        street_address=rec["address"],
        owner_name=rec.get("owner"),
        listing_type=ListingType.DISTRESSED,   # builder/investor distress, pre-foreclosure
        property_kind=PropertyKind.UNKNOWN,
        first_seen=now, last_seen=now,
        description=(f"LiensNC {rec.get('filing_type') or 'lien-agent filing'}"
                     + (f" — {rec['project']}" if rec.get("project") else "")
                     + (" — CLUSTER (related filings)" if (cluster or rec.get("related")) else "")),
        raw={"liensnc": {k: rec.get(k) for k in
                         ("filing_type", "filing_date", "filed_by", "project",
                          "owner_mailing", "related")}},
    )
    if cluster or rec.get("related"):
        li.raw["builder_distress"] = {"related_filings": bool(rec.get("related")),
                                      "cluster": cluster, "source": "liensnc"}
    return li


def _parse_csv(path: Path) -> list[dict]:
    """Parse a LiensNC Advanced-Search / Related-Filings CSV export (cleaner than HTML).
    Column names vary, so map fuzzily by header — address/owner/filing-type/date/related."""
    import csv
    out = []
    try:
        rows = list(csv.reader(path.open(newline="", errors="ignore")))
    except Exception:
        return []
    if not rows:
        return []
    hdr = [h.strip().lower() for h in rows[0]]
    if not any("owner" in h or "project" in h or "property" in h or "filing" in h for h in hdr):
        return []   # not a LiensNC export

    def find(*keys):
        for i, h in enumerate(hdr):
            if any(k in h for k in keys):
                return i
        return None
    ci = {"filing": find("filing type", "type"), "date": find("filing date", "date", "filed"),
          "filed_by": find("filed by", "filer"), "proj": find("project", "property", "address"),
          "owner": find("owner"), "related": find("related")}
    for r in rows[1:]:
        def g(k):
            i = ci.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        name, addr = _split_addr(g("proj"))
        if not addr:
            am = _ADDR_RE.search(g("proj"))
            addr = am.group(0) if am else None
        dm = _DATE_RE.search(g("date"))
        out.append({
            "filing_type": g("filing") or None, "filing_date": dm.group(1) if dm else (g("date") or None),
            "filed_by": g("filed_by") or None, "project": name, "address": addr,
            "owner": g("owner") or None, "owner_mailing": g("owner") or None,
            "related": "yes" in g("related").lower(),
        })
    return out


def main() -> int:
    recs = []
    for d in SCAN:
        if not d.exists():
            continue
        for f in d.glob("*.html"):
            recs.extend(_parse_file(f))
        for f in d.glob("*.csv"):      # CSV export (Advanced Search / Related Filings Report)
            recs.extend(_parse_csv(f))
    print(f"parsed {len(recs)} LiensNC filing rows from {len(SCAN)} scan dir(s)")
    if not recs:
        print("no LiensNC results pages found — save Advanced Search pages (HTML only) first.")
        return 0
    # CLUSTER detection: an address with >=2 filings, OR a row flagged related=Yes
    addr_counts = Counter(r["address"] for r in recs if r.get("address"))
    listings, seen = [], set()
    for r in recs:
        cluster = addr_counts.get(r.get("address"), 0) >= 2
        li = _to_listing(r, cluster)
        if not li:
            continue
        key = (li.street_address or "").upper() + "|" + normalize_name(li.owner_name)
        if key in seen:
            continue
        seen.add(key)
        listings.append(li)
    n_cluster = sum(1 for l in listings if (l.raw or {}).get("builder_distress"))
    print(f"built {len(listings)} LiensNC leads | {n_cluster} flagged builder_distress (clusters/related)")

    board = load_board(DOCS)
    board_keys = {(li.street_address or "").upper() for li in board if li.street_address}
    net_new = [l for l in listings if (l.street_address or "").upper() not in board_keys]
    board.extend(net_new)
    print(f"board {len(board)-len(net_new)} -> {len(board)} (+{len(net_new)} net-new LiensNC)")
    lp, mp = write_artifact(board, {"notes": "liensnc ingest"}, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
