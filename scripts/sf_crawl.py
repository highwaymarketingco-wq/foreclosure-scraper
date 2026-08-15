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
        name="Cars.com (API)",
        # SF spider-mode against cars.com search pages only crawls the seed
        # — listing-card links are JS-injected and SF doesn't render. The
        # in-tree CarsComScraper uses cars.com's JSON search endpoint with
        # the same query params and produces real listings.
        seed="https://www.cars.com/shopping/results/",
        crawl_mode="api",
        include_regex="",
        max_urls=2000,
    ),
    "bring_a_trailer": SitePreset(
        slug="bring_a_trailer",
        name="Bring a Trailer (API)",
        # SF spider-mode discovers thousands of BaT pages but rarely exports
        # them cleanly (CSV write phase aborts on large crawls). The in-tree
        # BringATrailerScraper hits the curated /porsche/<model>/ indexes
        # directly and parses listing-cards from server-rendered HTML.
        seed="https://bringatrailer.com/porsche/",
        crawl_mode="api",
        include_regex="",
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
        name="Copart (Solr API)",
        # Copart's public sitemaps return Incapsula "Loading" placeholders
        # for every endpoint — SF will crawl thousands of them but find zero
        # real lot URLs. The working approach is the public Solr search API
        # used by src/porsche_scraper/scrapers/copart.py. This preset routes
        # there via crawl_mode="api"; the seed is informational only.
        seed="https://www.copart.com/public/data/lotdetails/solr/lotSearch",
        crawl_mode="api",
        include_regex="",
        max_urls=3000,
    ),
    "iaai": SitePreset(
        slug="iaai",
        name="IAA (API)",
        # IAA's public sitemap is 116k URLs and SF can't honour --max-urls
        # for --crawl-sitemap, so the whole crawl times out. The in-tree
        # IaaiScraper queries IAA's vehicle-search JSON endpoint directly
        # for Porsche-only results.
        seed="https://www.iaai.com/Xj9rDOVMEi0hc38S/sitemap_index.xml",
        crawl_mode="api",
        include_regex="",
        max_urls=3000,
    ),
    "autobidmaster": SitePreset(
        slug="autobidmaster",
        name="AutoBidMaster (API)",
        # AutoBidMaster's sitemaps.autobidmaster.com/en/sitemap_index.xml
        # responds with HTML, not XML — SF rejects it as "not a sitemap".
        # The in-tree make_autobidmaster() scraper queries their search API.
        seed="https://sitemaps.autobidmaster.com/en/sitemap_index.xml",
        crawl_mode="api",
        include_regex="",
        max_urls=3000,
    ),
    "carsandbids": SitePreset(
        slug="cars_and_bids",
        name="Cars & Bids (API)",
        # carsandbids.com/sitemap.xml is HTML, not XML; SF rejects it as
        # "not a sitemap". CarsAndBidsScraper hits their auction listing
        # API with a Porsche filter.
        seed="https://carsandbids.com/sitemap.xml",
        crawl_mode="api",
        include_regex="",
        max_urls=2000,
    ),
    # Nationwide dealer inventory — real-browser JSON-LD readers, run in-tree.
    "carvana": SitePreset(
        slug="carvana", name="Carvana (API)",
        seed="https://www.carvana.com/cars/porsche",
        crawl_mode="api", include_regex="", max_urls=2000,
    ),
    "truecar": SitePreset(
        slug="truecar", name="TrueCar (API)",
        seed="https://www.truecar.com/used-cars-for-sale/listings/porsche/",
        crawl_mode="api", include_regex="", max_urls=2000,
    ),
    "carfax": SitePreset(
        slug="carfax", name="CarFax (API)",
        seed="https://www.carfax.com/Used-Porsche_m28",
        crawl_mode="api", include_regex="", max_urls=2000,
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
    # SF 23.3's CLI is intentionally minimal: --max-urls and --include
    # and --accept-license are NOT real CLI flags despite my prior
    # guesses. Each guess produces `FATAL - Unrecognized option`. EULA
    # acceptance lives in the spider.config that the workflow pre-writes;
    # max-urls / include are applied Python-side post-export.
    cmd = [binary, "--headless",
           "--save-crawl", "--output-folder", str(out_dir)]
    if config and config.exists():
        cmd += ["--config", str(config)]
    if preset.crawl_mode == "sitemap":
        cmd += ["--crawl-sitemap", preset.seed]
    elif preset.crawl_mode == "list":
        cmd += ["--crawl-list", preset.seed]
    else:
        cmd += ["--crawl", preset.seed]
    exports = ["Internal:All"]
    if config and config.exists():
        exports.append("Custom Extraction:All")
    cmd += ["--export-tabs", ",".join(exports), "--export-format", "csv"]
    cmd += ["--overwrite"]
    return cmd


def _find_csvs(out_dir: Path) -> list[Path]:
    return sorted(out_dir.rglob("*.csv"))


async def _run_api_preset(preset: SitePreset) -> list[dict]:
    """Bypass SF entirely for presets where the source's anti-bot makes SF
    crawling pointless (e.g. Copart sitemap → Incapsula "Loading" wall).
    Run the in-tree porsche_scraper for that source instead, return rows
    in the same shape _enrich_urls produces."""
    # Pull the year floor and price ceiling from the single source of truth so
    # this path can't drift from the filter (it used to hardcode year_min=2014,
    # which silently hid every pre-2014 911/Cayman/Boxster from the refresh).
    from porsche_scraper.filters import MIN_YEAR, MAX_PRICE_USD
    ymin, pmax = MIN_YEAR, int(MAX_PRICE_USD)

    if preset.slug == "copart":
        from porsche_scraper.scrapers.copart import CopartScraper
        scraper = CopartScraper()
    elif preset.slug == "cars_com":
        from porsche_scraper.scrapers.cars_com import CarsComScraper
        scraper = CarsComScraper(year_min=ymin, price_max=pmax)
    elif preset.slug == "bring_a_trailer":
        from porsche_scraper.scrapers.bring_a_trailer import BringATrailerScraper
        scraper = BringATrailerScraper()
    elif preset.slug == "iaai":
        from porsche_scraper.scrapers.iaai import IaaiScraper
        scraper = IaaiScraper(year_min=ymin)
    elif preset.slug == "cars_and_bids":
        from porsche_scraper.scrapers.cars_and_bids import CarsAndBidsScraper
        scraper = CarsAndBidsScraper(year_min=ymin, max_bid=pmax)
    elif preset.slug == "autobidmaster":
        from porsche_scraper.scrapers.salvage_brokers import make_autobidmaster
        scraper = make_autobidmaster(ymin, pmax)
    elif preset.slug == "carvana":
        from porsche_scraper.scrapers.carvana import CarvanaScraper
        scraper = CarvanaScraper(year_min=ymin, price_max=pmax)
    elif preset.slug == "truecar":
        from porsche_scraper.scrapers.truecar import TrueCarScraper
        scraper = TrueCarScraper(year_min=ymin, price_max=pmax)
    elif preset.slug == "carfax":
        from porsche_scraper.scrapers.carfax import CarfaxScraper
        scraper = CarfaxScraper(year_min=ymin, price_max=pmax)
    else:
        raise ValueError(f"no api scraper wired for preset slug {preset.slug!r}")
    listings = await scraper.fetch()
    rows = []
    for li in listings:
        rows.append({
            "URL":          li.source_url,
            "Source":       li.source,
            "Year":         li.year or "",
            "Model":        li.model or "",
            "Trim":         li.trim or "",
            "Price":        li.price_usd or "",
            "Bid":          li.current_bid_usd or "",
            "Mileage":      li.mileage or "",
            "Location":     li.location or "",
            "Title Status": li.title_status.value if li.title_status else "",
            "VIN":          li.vin or "",
            "Image":        li.photo_url or "",
            "Sale Date":    li.sale_date.isoformat() if li.sale_date else "",
            "Lot Number":   li.lot_number or "",
            "Title 1":      li.title or "",
        })
    return rows


def run_site(preset: SitePreset, binary: str, work_root: Path) -> list[Path]:
    out_dir = work_root / preset.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    # API mode: skip SF entirely, run the in-tree scraper that bypasses
    # the source's anti-bot. Writes a single CSV in the same shape the
    # enrichment step produces, so the importer treats it identically.
    if preset.crawl_mode == "api":
        print(f"\n┌── API scrape: {preset.name} ──────────────────────")
        print(f"│  preset: {preset.slug} (skipping SF — anti-bot blocks sitemap)")
        try:
            rows = asyncio.run(_run_api_preset(preset))
        except Exception as exc:
            print(f"  ✗ API scraper {preset.slug} failed: {exc}")
            return []
        if not rows:
            print(f"  → API scraper {preset.slug} returned 0 listings")
            return []
        out_csv = out_dir / "internal_all.csv"
        _write_enriched_csv(rows, out_csv)
        print(f"  → API scraper {preset.slug} produced {len(rows)} listings ({out_csv})")
        return [out_csv]

    config = CONFIG_DIR / f"{preset.slug}.seospiderconfig"
    cmd = _build_sf_command(binary, preset, out_dir, config)
    print(f"\n┌── SF crawl: {preset.name} ──────────────────────")
    print(f"│  seed:    {preset.seed}")
    print(f"│  mode:    {preset.crawl_mode}")
    print(f"│  include: {preset.include_regex or '(none)'}")
    print(f"│  config:  {'(none)' if not config.exists() else config}")
    print(f"│  out:     {out_dir}")
    print(f"└── running: {' '.join(cmd)}")
    # Per-site timeout. Some sitemaps (classiccars, carsforsale) have
    # hundreds of sub-sitemaps and SF doesn't honor --max-urls on
    # --crawl-sitemap, so a single bad site can hang the whole crawl
    # for hours. 10 minutes is generous for any reasonable source —
    # api-mode presets short-circuit before this code path anyway.
    SF_TIMEOUT_S = 600
    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True,
            timeout=SF_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        print(f"  ✗ SF binary not executable: {exc}")
        return []
    except subprocess.TimeoutExpired:
        print(f"  ⚠ SF crawl for {preset.slug} exceeded {SF_TIMEOUT_S}s — killed.")
        print(f"  → skipping {preset.slug}; continuing with remaining sources.")
        return _find_csvs(out_dir)
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


def _extract_urls_from_sf_csv(path: Path, preset: "SitePreset | None" = None) -> list[str]:
    """Pull the URL column (SF calls it 'Address') from any SF export CSV.

    SF 23.3 has no `--include` or `--max-urls` CLI flag, so we apply
    both filters here (using the SitePreset that produced this CSV).
    """
    import re as _re

    include_re = (
        _re.compile(preset.include_regex)
        if preset and preset.include_regex
        else None
    )
    cap = preset.max_urls if preset else 10_000
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
            if not u.startswith("http"):
                continue
            if include_re and not include_re.search(u):
                continue
            urls.append(u)
            if len(urls) >= cap:
                break
    return urls


def _preset_for_csv(path: Path) -> "SitePreset | None":
    """SF dumps each site's CSV under work_root/<preset.slug>/ so we map
    the CSV back to its preset by the parent directory name."""
    parent_name = path.parent.name
    for preset in PRESETS.values():
        if preset.slug == parent_name:
            return preset
    return None


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
    refilter_existing: bool = True,
) -> None:
    if not csvs:
        print("  nothing to import")
        return

    import_paths = list(csvs)

    if enrich:
        # Split CSVs: api-mode ones are already fully enriched (Copart's
        # Solr scraper returns Year/Model/Price/etc. directly), pass them
        # through unchanged. SF-mode CSVs go through detail-page enrichment.
        api_csvs = [c for c in csvs
                    if (p := _preset_for_csv(c)) and p.crawl_mode == "api"]
        sf_csvs = [c for c in csvs if c not in api_csvs]

        urls: set[str] = set()
        for c in sf_csvs:
            preset = _preset_for_csv(c)
            urls.update(_extract_urls_from_sf_csv(c, preset))
        urls_l = sorted(urls)
        print(f"\n  enriching {len(urls_l)} URLs via detail-page fetches "
              f"(concurrency={enrich_concurrency}); skipping "
              f"{len(api_csvs)} already-enriched API CSV(s) …")
        rows = asyncio.run(_enrich_urls(urls_l, enrich_concurrency)) if urls_l else []
        enriched_csv = work_root / "_enriched.csv"
        _write_enriched_csv(rows, enriched_csv)
        # Importer gets: enriched-from-SF (if any) + api-mode CSVs as-is.
        import_paths = []
        if rows:
            print(f"  → {len(rows)} listings enriched ({enriched_csv})")
            import_paths.append(enriched_csv)
        elif urls_l:
            print("  → enrichment produced 0 rows; falling back to raw SF CSVs")
            import_paths.extend(sf_csvs)
        import_paths.extend(api_csvs)
        if not import_paths:
            import_paths = list(csvs)

    cmd = ["uv", "run", "python", str(IMPORTER), *map(str, import_paths)]
    if allow_unknown_price:
        cmd.append("--allow-unknown-price")
    if not refilter_existing:
        cmd.append("--no-refilter-existing")
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

    # Copart's API returns upcoming-auction lots with price=$0 until the
    # first bid lands — without --allow-unknown-price they all get
    # filtered out (verified 2026-05-13: 46 imported vs 95 with the flag).
    # Auto-enable it whenever an api-mode preset (currently just copart)
    # is in the run. Caller can still pass --allow-unknown-price
    # explicitly for SF-mode presets if they want it too.
    auto_allow = any(PRESETS[s].crawl_mode == "api" for s in sites)
    # Partial-refresh guard: on subset runs (not --all), tell the importer to
    # keep pre-existing listings from un-touched sources as-is. Otherwise the
    # filter pass naturally ages out auctions whose sale_date has passed and
    # the dashboard shrinks for sources that weren't even re-scraped.
    full_refresh = args.all or set(sites) == set(PRESETS)
    if not full_refresh:
        print(f"\n  ⓘ partial refresh ({len(sites)} of {len(PRESETS)} sources): "
              f"preserving pre-existing entries from un-touched sources")
    run_import(
        all_csvs,
        allow_unknown_price=args.allow_unknown_price or auto_allow,
        enrich=not args.no_enrich,
        enrich_concurrency=args.enrich_concurrency,
        work_root=work_root,
        refilter_existing=full_refresh,
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
