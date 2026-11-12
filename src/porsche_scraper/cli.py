"""CLI entry point: `python -m porsche_scraper [...]`."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .filters import FilterCriteria, MAX_PRICE_USD, MIN_YEAR, current_year
from .output import write_csv, write_json
from .pipeline import run_all
from .registry import ALL_SCRAPERS, build_scrapers


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="porsche-scraper",
        description="Scrape cheap (≤$45k or salvage/rebuilt) Porsches, 2014+, "
        "across multiple sites. Skips Panamera/Cayenne/Macan.",
    )
    p.add_argument("--year-min", type=int, default=MIN_YEAR)
    p.add_argument("--year-max", type=int, default=0, help="0 → current year")
    p.add_argument(
        "--price-max", type=int, default=int(MAX_PRICE_USD),
        help="Asking-price ceiling (default $40,000). Applies to every source "
        "and title. Only price-TBD auction cars are kept without a number.",
    )
    p.add_argument(
        "--only", nargs="*", choices=[s for s, _ in ALL_SCRAPERS],
        help="Only run these scrapers.",
    )
    p.add_argument(
        "--skip", nargs="*", choices=[s for s, _ in ALL_SCRAPERS],
        default=[], help="Skip these scrapers.",
    )
    p.add_argument(
        "--out-dir", default="./porsche_output",
        help="Directory for listings.json and listings.csv.",
    )
    p.add_argument(
        "--max-concurrency", type=int, default=4,
        help="Maximum concurrent scrapers.",
    )
    p.add_argument(
        "--keep-unknown-year", action="store_true",
        help="Keep listings with no detectable year (default drops them).",
    )
    p.add_argument(
        "--allow-unknown-price", action="store_true",
        help="Keep listings with no price (default drops them when title isn't salvage/rebuilt).",
    )
    p.add_argument(
        "--include-off", action="store_true",
        help="Include scrapers that are off by default (fb_marketplace, craigslist).",
    )
    p.add_argument("--verbose", "-v", action="count", default=0)
    p.add_argument("--list-scrapers", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG), format="%(levelname)s %(name)s | %(message)s")

    if args.list_scrapers:
        for slug, _ in ALL_SCRAPERS:
            print(slug)
        return 0

    scrapers = build_scrapers(
        year_min=args.year_min,
        price_max=args.price_max,
        only=args.only,
        skip=args.skip,
        include_off_by_default=args.include_off,
    )
    if not scrapers:
        print("no scrapers selected", file=sys.stderr)
        return 2

    criteria = FilterCriteria(
        min_year=args.year_min,
        max_year=args.year_max or current_year(),
        max_price_usd=float(args.price_max),
        allow_unknown_price=args.allow_unknown_price,
        require_known_year=not args.keep_unknown_year,
    )

    listings = asyncio.run(run_all(scrapers, criteria=criteria, max_concurrency=args.max_concurrency))

    out_dir = Path(args.out_dir)
    write_json(out_dir / "listings.json", listings)
    write_csv(out_dir / "listings.csv", listings)
    print(f"wrote {len(listings)} listings to {out_dir}/")
    # Print top 10 cheapest as a quick preview.
    cheap = sorted(
        (l for l in listings if l.effective_price is not None),
        key=lambda l: l.effective_price or float("inf"),
    )[:10]
    if cheap:
        print("\nTop 10 cheapest:")
        for l in cheap:
            price = f"${int(l.effective_price):>6,}" if l.effective_price else "  ----"
            mi = f"{l.mileage:>6,} mi" if l.mileage else "      ?"
            print(
                f"  {price}  {l.year or '????'} {l.model or '?':<10} "
                f"{l.title_status.value:<8} {mi}  [{l.source}]  {l.source_url}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
