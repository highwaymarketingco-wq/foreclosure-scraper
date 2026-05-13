"""Import a Screaming Frog SEO Spider CSV export into the porsche dashboard.

Usage:
    uv run python scripts/import_sf_csv.py <path>.csv [<path>.csv ...]

The CSV is assumed to be a Screaming Frog "Internal" or "Custom
Extraction" export. We use these column names if present (case-
insensitive, both human-friendly and SF's own):

    URL / Address          → source_url
    Source                 → source slug (else inferred from URL host)
    Year                   → year
    Model                  → model
    Trim                   → trim
    Price / Price 1        → price_usd
    Bid / Current Bid      → current_bid_usd
    Mileage / Odometer     → mileage
    Location               → location
    Title Status / Title   → title_status (clean/salvage/rebuilt/parts_only/…)
    VIN                    → vin
    Image / Photo / og:image → photo_url
    Title 1 / Page Title   → fallback for human title if no Year+Model

After import we apply the same filter the live scrapers use (year ≥ 2014,
not Cayenne/Macan/Panamera, drivable, price ≤ $45k OR salvage/rebuilt)
and merge into the existing docs/porsche.json (dedupe by VIN / URL).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from porsche_scraper.filters import FilterCriteria, filter_listings
from porsche_scraper.models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)
from porsche_scraper.pipeline import dedupe


# Column aliases — left side is what we want, right side is anything SF
# might call it. Lower-cased exact match.
COLUMN_ALIASES = {
    "url":          ("url", "address", "page url", "loc"),
    "source":       ("source", "site", "domain"),
    "year":         ("year", "model year", "vehicle year"),
    "model":        ("model", "vehicle model"),
    "trim":         ("trim", "variant", "package"),
    "price":        ("price", "list price", "asking price", "price 1", "sale price"),
    "bid":          ("bid", "current bid", "high bid"),
    "mileage":      ("mileage", "odometer", "miles", "kilometres"),
    "location":     ("location", "city", "state", "zip", "address 1"),
    "title_status": ("title status", "title", "salvage", "title type", "title doc"),
    "vin":          ("vin", "vehicle identification number"),
    "photo":        ("image", "image src", "photo", "og:image", "primary image 1"),
    "title_text":   ("title 1", "page title", "name"),
}


def _build_index(fieldnames: list[str]) -> dict[str, str]:
    """Map our canonical names to the actual CSV column header (case-aware)."""
    lower_to_real = {f.lower().strip(): f for f in fieldnames}
    out: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in lower_to_real:
                out[canonical] = lower_to_real[a]
                break
    return out


def _source_from_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    # Map common hosts → canonical slugs that match the existing scrapers.
    mapping = {
        "www.cars.com":           "cars_com",
        "cars.com":               "cars_com",
        "bringatrailer.com":      "bring_a_trailer",
        "carsandbids.com":        "cars_and_bids",
        "www.ebay.com":           "ebay_motors",
        "www.autotempest.com":    "autotempest",
        "www.carsforsale.com":    "carsforsale",
        "www.autotrader.com":     "autotrader",
        "www.copart.com":         "copart",
        "www.iaai.com":           "iaai",
        "classiccars.com":        "classiccars_com",
        "www.hemmings.com":       "hemmings",
        "elferspot.com":          "elferspot",
        "www.elferspot.com":      "elferspot",
        "classifieds.pca.org":    "pca_mart",
        "rennlist.com":           "rennlist",
        "www.6speedonline.com":   "6speedonline",
        "www.pcarmarket.com":     "pcarmarket",
        "www.hagerty.com":        "hagerty_marketplace",
        "collectingcars.com":     "collecting_cars",
        "www.autohunter.com":     "autohunter",
        "broadarrowauctions.com": "broad_arrow",
        "www.iconicauctioneers.com": "iconic_auctioneers",
    }
    if host in mapping:
        return mapping[host]
    return host.replace("www.", "").replace(".", "_") or "screaming_frog"


def _row_to_listing(row: dict, idx: dict[str, str]) -> Listing | None:
    def get(key: str) -> str:
        c = idx.get(key)
        return (row.get(c) or "").strip() if c else ""

    url = get("url")
    if not url:
        return None

    source = get("source") or _source_from_url(url)
    title_text = get("title_text")
    raw_year = get("year")
    year = int(raw_year) if raw_year.isdigit() else parse_year(title_text)
    model = get("model") or None
    trim = get("trim") or None
    title_parts = [str(year or ""), "Porsche", model or "", trim or ""]
    title = title_text or " ".join(p for p in title_parts if p)

    status = _normalize_status(get("title_status")) or infer_title_status(title)
    listing = Listing(
        source=source,
        source_url=url,
        listing_id=get("vin") or _fallback_id(url),
        vin=get("vin") or None,
        title=title,
        year=year,
        model=model,
        trim=trim,
        price_usd=parse_price(get("price")),
        current_bid_usd=parse_price(get("bid")),
        mileage=parse_miles(get("mileage")),
        location=get("location") or None,
        title_status=status,
        photo_url=get("photo") or None,
        seller_type=_infer_seller(source),
        raw={"sf_csv": True},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _normalize_status(raw: str) -> TitleStatus | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if "salvage" in s:   return TitleStatus.SALVAGE
    if "rebuilt" in s:   return TitleStatus.REBUILT
    if "parts" in s:     return TitleStatus.PARTS_ONLY
    if "flood" in s:     return TitleStatus.FLOOD
    if "lemon" in s:     return TitleStatus.LEMON
    if "clean" in s or "clear" in s: return TitleStatus.CLEAN
    return None


def _infer_seller(source: str) -> str:
    if source in {"copart", "iaai", "sca_auction", "autobidmaster",
                  "abetter_bid", "cars4_bid", "auctionexport"}:
        return "salvage_auction"
    if source in {"bring_a_trailer", "cars_and_bids", "pcarmarket",
                  "hagerty_marketplace", "collecting_cars", "themarket",
                  "autohunter", "broad_arrow", "iconic_auctioneers",
                  "mecum", "barrett_jackson", "rm_sothebys", "gooding",
                  "bonhams_cars"}:
        return "auction"
    if source in {"rennlist", "6speedonline", "pca_mart",
                  "fb_marketplace", "craigslist"}:
        return "private"
    if source in {"govdeals", "gsa_auctions", "public_surplus",
                  "property_room", "municibid", "cws_marketing"}:
        return "government"
    return "dealer"


def _fallback_id(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def load_csv(path: Path) -> Iterable[Listing]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return
        idx = _build_index(reader.fieldnames)
        if "url" not in idx:
            print(f"WARNING: {path.name} has no URL/Address column; skipping", file=sys.stderr)
            return
        for row in reader:
            listing = _row_to_listing(row, idx)
            if listing:
                yield listing


def load_existing(path: Path) -> list[Listing]:
    """Re-hydrate the current docs/porsche.json so we can merge into it."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    out: list[Listing] = []
    for d in raw:
        try:
            out.append(Listing.model_validate(d))
        except Exception:  # noqa: BLE001
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("csv", nargs="+", type=Path, help="One or more SF CSV exports")
    p.add_argument("--out", type=Path, default=Path("docs/porsche.json"))
    p.add_argument("--csv-out", type=Path, default=Path("docs/porsche.csv"))
    p.add_argument("--no-merge", action="store_true",
                   help="Don't merge with the existing porsche.json — start fresh")
    p.add_argument("--keep-unknown-year", action="store_true")
    p.add_argument("--allow-unknown-price", action="store_true")
    args = p.parse_args(argv)

    fresh: list[Listing] = []
    for path in args.csv:
        n = 0
        for listing in load_csv(path):
            fresh.append(listing)
            n += 1
        print(f"  loaded {n:>5} rows from {path}")

    base = [] if args.no_merge else load_existing(args.out)
    combined = base + fresh
    deduped = dedupe(combined)
    criteria = FilterCriteria(
        require_known_year=not args.keep_unknown_year,
        allow_unknown_price=args.allow_unknown_price,
    )
    filtered = filter_listings(deduped, criteria)
    filtered.sort(key=lambda l: (l.effective_price is None, l.effective_price or 9e9))

    from porsche_scraper.output import write_json, write_csv
    write_json(args.out, filtered)
    write_csv(args.csv_out, filtered)

    print()
    print(f"  fresh from SF:    {len(fresh)}")
    print(f"  pre-existing:     {len(base)}")
    print(f"  after dedupe:     {len(deduped)}")
    print(f"  after filter:     {len(filtered)}")
    print(f"  wrote:            {args.out} + {args.csv_out}")

    by_source: dict[str, int] = {}
    for l in filtered:
        by_source[l.source] = by_source.get(l.source, 0) + 1
    print()
    print("  by source:")
    for s, c in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"    {s:30s} {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
