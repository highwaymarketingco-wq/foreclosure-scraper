"""One-command Porsche-dashboard refresh via headless Screaming Frog.

Drives a local headless Screaming Frog SEO Spider install, pipes the
crawl through scripts/import_sf_csv.py, and (optionally) commits + pushes
docs/porsche.json so the live dashboard updates.

Usage
-----

    # Single site
    uv run python scripts/sf_crawl.py cars_com

    # Multiple
    uv run python scripts/sf_crawl.py cars_com bring_a_trailer classiccars

    # All known sites
    uv run python scripts/sf_crawl.py --all

    # Refresh and push when done
    uv run python scripts/sf_crawl.py --all --push

Sites
-----

Run `--list` to see them. Each site has:
- a sitemap or search URL we seed SF with
- an include-regex so we only keep Porsche-listing URLs
- an optional .seospiderconfig path (custom extractors); if present it
  is passed via `--config`. Without it SF still emits URL + Title +
  meta tags, which is enough for the importer to parse year + model
  from slugs and titles.

Prerequisites
-------------

- Screaming Frog SEO Spider installed on this machine.
- SF binary on PATH, or set SF_BINARY env var. Defaults:
  * Linux:   /usr/bin/screamingfrogseospider
  * macOS:   /Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher
  * Windows: %ProgramFiles%\\Screaming Frog SEO Spider\\ScreamingFrogSEOSpiderCli.exe
- A paid SF licence is required for headless mode beyond the 500-URL
  free crawl limit.

Per-site configs
----------------

Drop hand-saved `.seospiderconfig` files at
`scripts/screaming_frog/configs/<site>.seospiderconfig`. Two ways to make one:

- Open SF GUI once on any machine → Configuration → set custom
  extractors per scripts/screaming_frog/README.md → File → Configuration
  → Save As, commit the file.
- Or just run without a config — basic crawl still gives URL+title and
  the importer can year+model from the slug for the sitemap-friendly
  sites (cars.com, BaT, ClassicCars, Elferspot).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

CONFIG_DIR = REPO_ROOT / "scripts" / "screaming_frog" / "configs"
IMPORTER = REPO_ROOT / "scripts" / "import_sf_csv.py"


@dataclasses.dataclass(frozen=True)
class SitePreset:
    slug: str
    name: str
    # Use --crawl-sitemap when this is a sitemap.xml; --crawl otherwise.
    seed: str
    crawl_mode: str  # "sitemap" | "spider" | "list"
    # SF "Include" regex (URLs to keep). Empty means crawl everything seeded.
    include_regex: str = ""
    # Max URLs (passed via --max-urls, defensive — SF licence may also cap).
    max_urls: int = 5000


PRESETS: dict[str, SitePreset] = {
    "cars_com": SitePreset(
        slug="cars_com",
        name="Cars.com",
        seed=(
            "https://www.cars.com/shopping/results/?stock_type=used"
            "&makes[]=porsche"
            "&models[]=porsche-911&models[]=porsche-718_cayman"
            "&models[]=porsche-cayman&models[]=porsche-718_boxster"
            "&models[]=porsche-boxster"
            "&year_min=2014&list_price_max=45000&page_size=100"
        ),
        crawl_mode="spider",
        include_regex=r"^https://www\.cars\.com/vehicledetail/.+",
        max_urls=2000,
    ),
    "bring_a_trailer": SitePreset(
        slug="bring_a_trailer",
        name="Bring a Trailer",
        seed="https://bringatrailer.com/porsche/",
        crawl_mode="spider",
        # Vehicle slugs always start with a 4-digit year.
        include_regex=r"^https://bringatrailer\.com/listing/(?:19|20)\d{2}-porsche-.+",
        max_urls=3000,
    ),
    "classiccars": SitePreset(
        slug="classiccars_com",
        name="ClassicCars.com",
        seed="https://classiccars.com/sitemap_index.xml",
        crawl_mode="sitemap",
        include_regex=r"/listings/view/\d+/20(?:1[4-9]|[2-9]\d)-porsche-.+",
        max_urls=5000,
    ),
    "elferspot": SitePreset(
        slug="elferspot",
        name="Elferspot",
        seed="https://www.elferspot.com/sitemap_index.xml",
        crawl_mode="sitemap",
        include_regex=r"/en/car/porsche-.+-20(?:1[4-9]|[2-9]\d)-\d+/?$",
        max_urls=5000,
    ),
    "hemmings": SitePreset(
        slug="hemmings",
        name="Hemmings",
        seed=(
            "https://www.hemmings.com/classifieds/cars-for-sale/porsche"
            "?MinYear=2014&MaxPrice=45000"
        ),
        crawl_mode="spider",
        include_regex=r"hemmings\.com/classifieds/cars-for-sale/porsche/",
        max_urls=2000,
    ),
    "carsforsale": SitePreset(
        slug="carsforsale",
        name="CarsForSale",
        seed="https://www.carsforsale.com/sitemap_index.xml",
        crawl_mode="sitemap",
        include_regex=r"carsforsale\.com/.*porsche",
        max_urls=5000,
    ),
    "copart": SitePreset(
        slug="copart",
        name="Copart",
        seed="https://www.copart-sitemaps.com/sitemap-index.xml",
        crawl_mode="sitemap",
        include_regex=r"copart\.com/lot/\d+/.*porsche-(?:911|cayman|boxster|718)",
        max_urls=3000,
    ),
    "iaai": SitePreset(
        slug="iaai",
        name="IAA",
        seed="https://www.iaai.com/Xj9rDOVMEi0hc38S/sitemap_index.xml",
        crawl_mode="sitemap",
        include_regex=r"iaai\.com/VehicleDetail/.*porsche",
        max_urls=3000,
    ),
    "autobidmaster": SitePreset(
        slug="autobidmaster",
        name="AutoBidMaster",
        seed="https://sitemaps.autobidmaster.com/en/sitemap_index.xml",
        crawl_mode="sitemap",
        include_regex=r"autobidmaster\.com/.*porsche",
        max_urls=3000,
    ),
    "carsandbids": SitePreset(
        slug="cars_and_bids",
        name="Cars & Bids",
        seed="https://carsandbids.com/sitemap.xml",
        crawl_mode="sitemap",
        include_regex=r"carsandbids\.com/auctions/.*porsche",
        max_urls=2000,
    ),
}


def _detect_sf_binary() -> str:
    env = os.environ.get("SF_BINARY")
    if env and Path(env).exists():
        return env
    candidates = []
    sysname = platform.system().lower()
    if sysname == "darwin":
        candidates.append(
            "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/"
            "ScreamingFrogSEOSpiderLauncher"
        )
    elif sysname == "windows":
        for pf in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(pf)
            if base:
                candidates.append(
                    str(Path(base) / "Screaming Frog SEO Spider" / "ScreamingFrogSEOSpiderCli.exe")
                )
    else:
        candidates.append("/usr/bin/screamingfrogseospider")
        candidates.append("/usr/local/bin/screamingfrogseospider")
    for c in candidates:
        if Path(c).exists():
            return c
    on_path = shutil.which("screamingfrogseospider")
    if on_path:
        return on_path
    raise SystemExit(
        "Couldn't find Screaming Frog binary. Install SF or set SF_BINARY="
        "/path/to/screamingfrogseospider"
    )


def _build_sf_command(
    binary: str, preset: SitePreset, out_dir: Path, config: Path | None
) -> list[str]:
    cmd = [binary, "--headless", "--save-crawl", "--output-folder", str(out_dir)]
    if config and config.exists():
        cmd += ["--config", str(config)]
    if preset.crawl_mode == "sitemap":
        cmd += ["--crawl-sitemap", preset.seed]
    elif preset.crawl_mode == "list":
        # Caller would supply a URL list file via the seed path.
        cmd += ["--crawl-list", preset.seed]
    else:
        cmd += ["--crawl", preset.seed]
    # Bulk exports — Internal:All always; Custom Extraction:All if config sets extractors.
    exports = ["Internal:All"]
    if config and config.exists():
        exports.append("Custom Extraction:All")
    cmd += ["--bulk-export", ",".join(exports), "--export-format", "csv"]
    cmd += ["--max-urls", str(preset.max_urls)]
    if preset.include_regex:
        cmd += ["--include", preset.include_regex]
    cmd += ["--overwrite"]
    return cmd


def _find_csvs(out_dir: Path) -> list[Path]:
    return sorted(out_dir.rglob("*.csv"))


def run_site(preset: SitePreset, binary: str, work_root: Path) -> list[Path]:
    out_dir = work_root / preset.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    config = CONFIG_DIR / f"{preset.slug}.seospiderconfig"
    cmd = _build_sf_command(binary, preset, out_dir, config)
    print(f"\n┌── SF crawl: {preset.name} ──────────────────────")
    print(f"│  seed:    {preset.seed}")
    print(f"│  mode:    {preset.crawl_mode}")
    print(f"│  include: {preset.include_regex or '(none)'}")
    print(f"│  config:  {'(none)' if not config.exists() else config}")
    print(f"│  out:     {out_dir}")
    print(f"└── running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        print(f"  ✗ SF binary not executable: {exc}")
        return []
    # Always echo SF's output so the CI log shows what it actually did.
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"  ⚠ SF exited {result.returncode}")
    csvs = _find_csvs(out_dir)
    print(f"  → exported CSVs from {preset.slug}: {len(csvs)}")
    return csvs


def _extract_urls_from_sf_csv(path: Path) -> list[str]:
    """Pull the URL column (SF calls it 'Address') from any SF export CSV."""
    urls: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return urls
        addr_col = next(
            (c for c in reader.fieldnames if c.lower().strip() in ("address", "url")),
            None,
        )
        if not addr_col:
            return urls
        for row in reader:
            u = (row.get(addr_col) or "").strip()
            if u.startswith("http"):
                urls.append(u)
    return urls


async def _enrich_urls(urls: list[str], concurrency: int) -> list[dict]:
    """Run per-source detail-page parsers (from the user's IP) and return
    a list of dicts ready to write as an importer-compatible CSV row.
    """
    from porsche_scraper.sf_enrichers import enrich  # local import — sys.path patched

    sem = asyncio.Semaphore(concurrency)

    async def one(u):
        async with sem:
            try:
                listing = await enrich(u)
            except Exception:  # noqa: BLE001
                return None
            if listing is None:
                return None
            return {
                "URL":          listing.source_url,
                "Source":       listing.source,
                "Year":         listing.year or "",
                "Model":        listing.model or "",
                "Trim":         listing.trim or "",
                "Price":        listing.price_usd or "",
                "Bid":          listing.current_bid_usd or "",
                "Mileage":      listing.mileage or "",
                "Location":     listing.location or "",
                "Title Status": listing.title_status.value if listing.title_status else "",
                "VIN":          listing.vin or "",
                "Image":        listing.photo_url or "",
                "Title 1":      listing.title or "",
            }

    results = await asyncio.gather(*(one(u) for u in urls))
    return [r for r in results if r is not None]


def _write_enriched_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_import(
    csvs: list[Path],
    allow_unknown_price: bool,
    *,
    enrich: bool,
    enrich_concurrency: int,
    work_root: Path,
) -> None:
    if not csvs:
        print("  nothing to import")
        return

    import_paths = list(csvs)

    if enrich:
        urls: set[str] = set()
        for c in csvs:
            urls.update(_extract_urls_from_sf_csv(c))
        urls_l = sorted(urls)
        print(f"\n  enriching {len(urls_l)} URLs via detail-page fetches "
              f"(concurrency={enrich_concurrency}) …")
        rows = asyncio.run(_enrich_urls(urls_l, enrich_concurrency))
        enriched_csv = work_root / "_enriched.csv"
        _write_enriched_csv(rows, enriched_csv)
        if rows:
            print(f"  → {len(rows)} listings enriched ({enriched_csv})")
            # Prefer the enriched data — it has prices.
            import_paths = [enriched_csv]
        else:
            print("  → enrichment produced 0 rows; falling back to raw SF CSVs")

    cmd = ["uv", "run", "python", str(IMPORTER), *map(str, import_paths)]
    if allow_unknown_price:
        cmd.append("--allow-unknown-price")
    print(f"\n  importing {len(import_paths)} CSV(s) into docs/porsche.json …")
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def maybe_push() -> None:
    # Stage + commit + push the dashboard files if they changed.
    status = subprocess.run(
        ["git", "status", "--porcelain", "docs/porsche.json", "docs/porsche.csv"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout.strip()
    if not status:
        print("\n  dashboard unchanged — nothing to push.")
        return
    msg = f"porsche: refresh dashboard from SF ({dt.datetime.now().strftime('%Y-%m-%d %H:%M')})"
    subprocess.run(
        ["git", "add", "docs/porsche.json", "docs/porsche.csv"],
        check=True, cwd=REPO_ROOT,
    )
    subprocess.run(["git", "commit", "-m", msg], check=True, cwd=REPO_ROOT)
    subprocess.run(["git", "push"], check=True, cwd=REPO_ROOT)
    print("\n  ✔ pushed. Pages will redeploy in ~60s.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sites", nargs="*", help="Site presets to crawl (see --list)")
    p.add_argument("--all", action="store_true", help="Crawl every preset")
    p.add_argument("--list", action="store_true", help="List preset names and exit")
    p.add_argument("--push", action="store_true",
                   help="Commit + push docs/porsche.json after import")
    p.add_argument("--allow-unknown-price", action="store_true",
                   help="Keep listings with no discovered price (e.g. Elferspot)")
    p.add_argument("--keep-output", action="store_true",
                   help="Don't delete the SF temp output folder after import")
    p.add_argument("--no-enrich", action="store_true",
                   help="Skip the detail-page enrichment step (faster, fewer prices)")
    p.add_argument("--enrich-concurrency", type=int, default=8,
                   help="How many detail pages to fetch in parallel (default 8)")
    args = p.parse_args(argv)

    if args.list:
        for slug, preset in PRESETS.items():
            cfg = CONFIG_DIR / f"{preset.slug}.seospiderconfig"
            tag = "✓ config" if cfg.exists() else "  no config"
            print(f"  {slug:18s}  [{tag}]  {preset.name}  ({preset.crawl_mode})")
        return 0

    sites = list(PRESETS) if args.all else args.sites
    if not sites:
        p.print_help()
        return 2
    unknown = [s for s in sites if s not in PRESETS]
    if unknown:
        print(f"Unknown sites: {unknown}. Run --list to see options.", file=sys.stderr)
        return 2

    binary = _detect_sf_binary()
    print(f"Using SF binary: {binary}")
    work_root = Path(tempfile.mkdtemp(prefix="sf-porsche-"))
    print(f"Work folder:     {work_root}")

    all_csvs: list[Path] = []
    for slug in sites:
        try:
            all_csvs.extend(run_site(PRESETS[slug], binary, work_root))
        except subprocess.CalledProcessError as exc:
            print(f"  ⚠ {slug} failed: {exc}")
            continue

    run_import(
        all_csvs,
        allow_unknown_price=args.allow_unknown_price,
        enrich=not args.no_enrich,
        enrich_concurrency=args.enrich_concurrency,
        work_root=work_root,
    )
    if args.push:
        maybe_push()

    if not args.keep_output:
        shutil.rmtree(work_root, ignore_errors=True)
        print(f"\n  cleaned up {work_root}")
    else:
        print(f"\n  kept SF output at {work_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
