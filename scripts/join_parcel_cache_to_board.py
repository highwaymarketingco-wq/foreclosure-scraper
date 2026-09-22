#!/usr/bin/env python3
"""Join the local parcel cache onto the board. Fills situs, owner mailing, value, sqft.

WHY THIS EXISTS AS A SCRIPT
    100 county caches were built holding 11.5M parcels, 10.8M of them carrying an owner
    MAILING address -- and the board's mailing coverage stayed at 65%, because
    enrich_gis_attrs only runs inside a full pipeline run and no run had landed since.
    The single biggest contact win available was sitting on disk, unused. SC owner
    contact is the measured binding constraint (Cherokee SC was at 1% mailing).

SAFETY
  * FILLS ONLY. Never overwrites a value the board already has, never adds or removes a
    row, and asserts the row count is unchanged.
  * The cache is keyed by county NAME with no state, so a lookup is only attempted when
    the county is not one of the four names that exist in BOTH Carolinas -- Beaufort,
    Cherokee, Lee, Union. Reading NC parcel data onto an SC lead would be worse than
    leaving the row empty.

    python scripts/join_parcel_cache_to_board.py --dry-run
    python scripts/join_parcel_cache_to_board.py
"""
from __future__ import annotations

import argparse
import re
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

#: This USED to hardcode {"beaufort","cherokee","lee","union"} and skip them
#: outright -- a second, independent copy of the same "cache key carries no
#: state" concern parcel_cache.DUAL_STATE_COUNTIES already solves, out of sync
#: with it (missing anson/chester) and, worse, now WRONG: lookup() has required
#: and correctly used an explicit state since 2026-09-13, and NC caches for Lee,
#: Cherokee, Union, Beaufort were built today. This blanket skip was silently
#: discarding real, correctly-resolvable NC data -- found 2026-09-14 when Lee/
#: Cherokee/Union/Beaufort NC rows all showed 0% value fill despite live
#: lookup(county, parcel_id, "NC") returning real market values for the same
#: parcel_ids. lookup() already refuses to guess when state is missing; this
#: file no longer needs its own copy of that rule, only a friendlier counter
#: for the one case lookup() can't explain on its own: no li.state at all.
from foreclosure_scraper.parcel_cache import DUAL_STATE_COUNTIES  # noqa: E402
from foreclosure_scraper.models import ListingType  # noqa: E402
_DUAL_LOWER = {n.lower() for n in DUAL_STATE_COUNTIES}
sys.path.insert(0, str(REPO / "scripts"))
from fill_address_from_parcel import classify_situs  # noqa: E402



_MAIL_STATE_RE = re.compile(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def _mail_state(mailing: str) -> str | None:
    """Two-letter state from the tail of a mailing string, e.g.
    '250 SAWGRASS CT SUMTER SC 29150' -> 'SC'. Returns None rather than guessing."""
    m = _MAIL_STATE_RE.search((mailing or "").strip().upper())
    return m.group(1) if m else None

def apply_rows(rows, *, dry_run: bool = False) -> dict:
    """The join itself, on the rows load_board returned. Fill-only; never changes len(rows).
    Extracted 2026-09-21 so scripts/apply_board_fixes.py can run it in the same single load."""
    from foreclosure_scraper.parcel_cache import lookup, sale_amount
    from foreclosure_scraper.enrichment_owner_mailing import _is_absentee
    from foreclosure_scraper.dedupe import suspicious_parcel_keys
    # A parcel id shared by many distinct addresses (a lien-agent filing batch citing a
    # subdivision's master-tract PIN for every lot) is one cache lookup that would copy one
    # property's owner, mailing and value onto every other address that cites the same id
    # (audit 2026-09-22: Pender County 3208-90-5620-0000 covered 216 addresses). Refuse the
    # lookup for any of them rather than trust it.
    suspicious = suspicious_parcel_keys(rows)
    c = Counter()
    for li in rows:
        if li.listing_type == ListingType.TAX_SALE_OVERAGE:
            # The parcel's cache row describes whoever owns it NOW -- a
            # different person from the overage claimant this listing is
            # about (the claimant lost the property AT the tax sale this
            # claim came from). Filling owner_mailing here would silently
            # attach a stranger's mailing address under the claimant's
            # name. The scraper already sets situs address + owner_name
            # (the claimant) directly from the claim document; nothing
            # else here is safe to join onto this listing_type.
            c["skipped: tax_sale_overage, owner != cache owner"] += 1
            continue
        if not li.parcel_id:
            c["no parcel_id"] += 1
            continue
        county = (li.county or "").replace(" County", "").strip()
        if not county:
            c["no county"] += 1
            continue
        if county.lower() in _DUAL_LOWER and not li.state:
            # lookup() would return None here too (it refuses to guess), but
            # naming this case separately from an ordinary cache miss makes
            # the reason auditable instead of invisible.
            c["skipped: dual-state name, li.state is empty"] += 1
            continue
        if li.dedupe_key() in suspicious:
            c["skipped: parcel id shared by many distinct addresses"] += 1
            continue
        try:
            hit = lookup(county, li.parcel_id, li.state)
        except Exception:  # noqa: BLE001
            c["lookup error"] += 1
            continue
        if not hit:
            c["cache miss"] += 1
            continue
        c["cache HIT"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}

        # A parcel resolved from the lead's street address may belong to someone else (a builder, a tenant, a
        # debtor, or the parcel has a new owner): value, sqft and acreage are property facts and are safe, but the
        # OWNER's mailing address is not, so it is withheld when the resolver recorded owner_agrees False.
        _pfa = li.raw.get("parcel_from_address") if isinstance(li.raw, dict) else None
        _owner_differs = isinstance(_pfa, dict) and _pfa.get("owner_agrees") is False
        if _owner_differs and hit.get("owner_mailing"):
            c["mailing withheld: parcel owner differs from the lead's party"] += 1
        if hit.get("owner_mailing") and not _owner_differs:
            g = li.raw.setdefault("gis", {})
            if not g.get("mailing"):
                g["mailing"] = hit["owner_mailing"]
                c["filled owner mailing"] += 1
            # ALSO write the CANONICAL block. raw["gis"]["mailing"] alone is
            # invisible: the absentee derivation reads
            # raw["owner_mailing"], fullmer_rank reads owner_mailing.absentee,
            # and the slim payload's allowlist ships owner_mailing, not gis.mailing.
            # Sumter proved it — 2,342 rows had gis.mailing and ZERO were flagged
            # absentee, including 220 SAWGRASS CT whose owner mails from 250
            # SAWGRASS CT. Fetching a mailing address and never deriving the
            # signal from it is the same silent loss as not fetching it.
            # owner_mailing is a STRING on some rows, not a dict. This exact
            # shape drift crashed the mail spine once before, so it is checked
            # rather than assumed. A string already carries a mailing address —
            # leave it alone rather than clobbering real data to fit the schema.
            om_existing = li.raw.get("owner_mailing")
            if om_existing is not None and not isinstance(om_existing, dict):
                c["owner_mailing was a string — left as is"] += 1
                om = None
            else:
                om = li.raw.setdefault("owner_mailing", {})
            if om is not None and not om.get("mailing"):
                om["mailing"] = hit["owner_mailing"]
                situs = hit.get("address") or li.street_address
                om["absentee"] = _is_absentee(situs, hit["owner_mailing"])
                st = _mail_state(hit["owner_mailing"])
                if st:
                    om["mail_state"] = st
                    om["out_of_state"] = bool(li.state and st != li.state)
                if om["absentee"]:
                    c["flagged absentee"] += 1
        if hit.get("address") and not (li.street_address or "").strip():
            # 2026-09-21: the cache "address" column is often NOT a street ("SPLIT FROM 116-00-01-048",
            # "OFF SR 1151 EXT", Transylvania's LEGAL_ADDR, "0 CALHOUN TRL"). Only a numbered street
            # is written; see scripts/fill_address_from_parcel.py for the classifier and the city/zip rule.
            _sit = classify_situs(hit["address"])
            if _sit["kind"] == "numbered":
                li.street_address = _sit["address"]
                c["filled situs address"] += 1
            else:
                c[f"situs not written ({_sit['kind']})"] += 1
        if hit.get("owner") and not (li.owner_name or "").strip():
            li.owner_name = hit["owner"]
            c["filled owner name"] += 1
        if hit.get("market_value") and not li.market_value:
            li.market_value = hit["market_value"]
            c["filled market value"] += 1
        if hit.get("tax_value") and not li.tax_value:
            li.tax_value = hit["tax_value"]
            c["filled tax value"] += 1
        if hit.get("living_sqft") and not li.living_sqft:
            li.living_sqft = hit["living_sqft"]
            c["filled sqft"] += 1
        if hit.get("acreage") and not li.acreage:
            li.acreage = hit["acreage"]
            c["filled acreage"] += 1
        _amt = sale_amount(hit.get("sale_price"))
        if _amt:
            g = li.raw.setdefault("gis", {})
            ls = g.setdefault("last_sale", {})
            if not ls.get("amount"):
                ls["amount"] = _amt
                c["filled last sale"] += 1

    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="cache_join")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        c = apply_rows(rows, dry_run=args.dry_run)

        print()
        for k, n in c.most_common():
            print(f"  {n:>8,}  {k}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert len(rows) == before, "a join must never change the row count"
        write_artifact(rows, {
            "total": before,
            "notes": (f"parcel-cache join: {c['cache HIT']:,} hits, "
                      f"{c['filled owner mailing']:,} owner mailing, "
                      f"{c['filled situs address']:,} situs, {c['filled sqft']:,} sqft"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
