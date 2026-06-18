"""Apply the stacked-distress score (HOT/WARM/COLD tiers) to docs/listings.json
and republish. Pure computation over existing signals — no scraping."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.distress_score import score_board
from foreclosure_scraper.web_artifact import _to_dict


def _hydrate(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    for ef, enum in (("listing_type", ListingType), ("property_kind", PropertyKind)):
        if isinstance(fields.get(ef), str):
            try:
                fields[ef] = enum(fields[ef])
            except ValueError:
                fields.pop(ef, None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


def main() -> int:
    path = Path("docs/listings.json")
    data = json.loads(path.read_text())
    listings, by_id = [], {}
    for d in data:
        li = _hydrate(d)
        if li:
            listings.append(li)
            by_id[id(li)] = d
    hist = score_board(listings)
    print(f"[{time.strftime('%H:%M:%S')}] tiers: {hist}", flush=True)

    for li in listings:
        by_id[id(li)]["raw"] = _to_dict(li)["raw"]

    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    hot = sum(1 for x in data if (x.get("raw") or {}).get("distress_stack", {}).get("tier") == "HOT")
    warm = sum(1 for x in data if (x.get("raw") or {}).get("distress_stack", {}).get("tier") == "WARM")
    print(f"[{time.strftime('%H:%M:%S')}] wrote — {hot} HOT, {warm} WARM", flush=True)

    if os.environ.get("STACK_PUBLISH", "1") == "1":
        import subprocess
        root = str(Path(__file__).parent.parent)
        subprocess.run(["git", "add", "docs/listings.json"], cwd=root, check=False)
        if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root).returncode != 0:
            subprocess.run(["git", "commit", "-q", "-m",
                            f"distress score: {hot} HOT / {warm} WARM ({time.strftime('%Y-%m-%d')})"], cwd=root, check=False)
            subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=root, check=False)
            p = subprocess.run(["git", "push", "origin", "main"], cwd=root)
            print("published ✓" if p.returncode == 0 else "push failed ⚠", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
