"""Print a ranked list of 'layup' quiet-title candidates (rules: quiet_title/layups.py).

  uv run python scripts/quiet_title_layups.py --county Buncombe --top 25

ONE read-only pass over the board through board_stream.iter_board_rows() (the parts board; never
docs/listings.json, never written), the verification ledgers read from
docs/handoff/verification/ (read only). The situs of the printed parcels comes from ONE batched
query to the county parcel layer (--no-situs skips it). Prints PIN, situs address, signals and
why each ranked to stdout; counts of what each rule dropped go to stderr. Writes no file.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.quiet_title.layups import LayupScan, iter_candidates_text  # noqa: E402
from foreclosure_scraper.quiet_title.model import EASTERN, utc_now  # noqa: E402
from foreclosure_scraper.verification.core import property_part, row_keys  # noqa: E402
from foreclosure_scraper.verification.ledger import Ledger, ledger_path  # noqa: E402

GIS = {"buncombe": "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"}


def load(signal: str, directory: Path) -> Ledger | None:
    p = ledger_path(signal, directory)
    return Ledger.load_file(p) if p.exists() else None


def property_index(led: Ledger | None) -> dict[str, list[str]]:
    """property key -> verdicts, for a case-scoped ledger ('<case>@<property>' keys)."""
    out: dict[str, list[str]] = {}
    if led is None:
        return out
    for ek, e in led.rows.items():
        v = (e.get("latest") or {}).get("verdict")
        for k in {ek, *(e.get("keys") or [])}:
            out.setdefault(property_part(k), []).append(v)
    return out


def situs_lookup(county: str, pins: list[str]) -> dict[str, str]:
    """One query for every printed PIN; {pin: situs}. Polite: one request, a browser User-Agent,
    retried after a pause on the layer's intermittent error body."""
    url = GIS.get(county.lower())
    if not url or not pins:
        return {}
    import requests
    from foreclosure_scraper.quiet_title.fetch import HEADERS, detect_wall
    where = "pinnum IN (" + ",".join(f"'{p}'" for p in pins) + ")"
    params = {"where": where, "returnGeometry": "false", "f": "json",
              "outFields": "pinnum,HouseNumber,NumberSuffix,direction,streetname,StreetType,PostDirection"}
    for wait in (0, 5, 15):
        time.sleep(wait)
        r = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if detect_wall(r.status_code, r.url, r.text):
            print(f"situs lookup walled ({r.status_code}); addresses come from the board", file=sys.stderr)
            return {}
        try:
            j = r.json()
        except ValueError:
            continue
        if "error" in j:
            continue
        out = {}
        for f in j.get("features") or []:
            a = f.get("attributes") or {}
            hn = str(a.get("HouseNumber") or "").strip()
            street = " ".join(str(a.get(k) or "").strip() for k in ("direction", "streetname", "StreetType",
                                                                     "PostDirection") if str(a.get(k) or "").strip())
            if hn and hn.lstrip("0") and hn != "99999":
                s = f"{hn.lstrip('0')} {street} (situs, county layer)"
            else:
                s = f"no house number on {street} (situs, county layer)"
            out[str(a.get("pinnum"))] = s
        return out
    print("situs lookup failed (county layer error); addresses come from the board", file=sys.stderr)
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", default="Buncombe")
    ap.add_argument("--state", default="NC")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--ledger-dir", default=str(REPO / "docs" / "handoff" / "verification"))
    ap.add_argument("--no-situs", action="store_true", help="do not query the county layer for situs")
    ap.add_argument("--strict-owner-match", action="store_true",
                    help="also exclude rows flagged owner_record_mismatch (default: printed as a caution)")
    a = ap.parse_args(argv)
    if Path(a.board).name == "listings.json":
        print("Refusing to read docs/listings.json; pass the .json.gz (parts) board.", file=sys.stderr)
        return 2

    d = Path(a.ledger_dir)
    tax = load("tax_lien", d)
    if tax is None:
        print("no tax_lien ledger", file=sys.stderr)
        return 1
    probate = property_index(load("probate_heir", d))
    court = {sig: property_index(load(sig, d)) for sig in ("bankruptcy_stay", "foreclosure_rod")}
    today = utc_now().astimezone(EASTERN).date()

    def find_tax(row):
        return tax.find(row_keys(row), address=row.get("street_address"))[1]

    def find_probate(row):
        vs = [v for k in row_keys(row) for v in probate.get(k, [])]
        return "confirmed" if "confirmed" in vs else (vs[0] if vs else None)

    def find_court(row):
        ks = row_keys(row)
        return [sig for sig, idx in court.items() if any("confirmed" in idx.get(k, []) for k in ks)]

    scan = LayupScan(county=a.county, state=a.state, today=today, find_tax=find_tax, find_probate=find_probate,
                     find_confirmed_court=find_court, strict=a.strict_owner_match)
    t0 = time.time()
    for row in iter_board_rows(a.board):
        if isinstance(row, dict):
            scan.add_row(row)
    cands = scan.candidates()
    top = cands[:a.top]
    situs = {} if a.no_situs else situs_lookup(a.county, [c.pin for c in top])

    print(f"Layup candidates, {a.county} {a.state}, {today} (top {len(top)} of {len(cands)}).")
    print("Rules: R1 county; R2 tax_lien ledger confirmed for >= 2 completed levy years (PTS Cloud verdicts "
          "ignored; current-year bill never counts); R3 no bankruptcy or foreclosure signal; R4 heirs/estate "
          "wording on the roll; R5 single parcel (no condo unit, no fused-key flag, one address per PIN; "
          f"owner_record_mismatch {'excluded' if a.strict_owner_match else 'printed as a caution'}). "
          "Rank: heirs claim confirmed in the probate_heir ledger first, then the smaller balance.")
    for line in iter_candidates_text(top, situs):
        print(line)
    print(f"[board rows {scan.rows_seen:,}; {a.county} rows {scan.in_county:,}; candidates {len(cands)}; "
          f"{time.time() - t0:.0f} s]", file=sys.stderr)
    for why, n in sorted(scan.dropped.items(), key=lambda kv: -kv[1]):
        print(f"  dropped {n:>7,}  {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
