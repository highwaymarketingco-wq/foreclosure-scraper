# porsche-scraper

Aggregate **cheap Porsche listings** across used-car and auction sites.

## Search criteria

A listing is **kept** when **all** of these hold:

| Rule | Logic |
|------|-------|
| Year | between **2014** and **current year** inclusive (see `--year-min` / `--year-max`). |
| Price | **≤ $45,000** *OR* title is **salvage** / **rebuilt**. |
| Drivable | not **parts-only**, not **non-running** / **blown motor** / etc. Auction sites' "Run & Drive = No" flag is also rejected. |
| Excluded models | **Panamera**, **Cayenne**, **Macan** — substring match on title + model fields. |

The defaults are tunable via `FilterCriteria` (`src/porsche_scraper/filters.py`)
and CLI flags.

## Sources

| Slug | Site | Notes |
|------|------|-------|
| `cars_com` | cars.com | Used listings — JSON-LD primary, HTML fallback. Friendly. |
| `ebay_motors` | ebay.com Motors | HTML scrape; if `EBAY_OAUTH_TOKEN` is set, uses the Browse API. |
| `autotempest` | autotempest.com | Metasearch (aggregates other sources' deeplinks). |
| `carsforsale` | carsforsale.com | JSON-LD primary, HTML fallback. Stealth transport. |
| `autotrader` | autotrader.com | Reads `__NEXT_DATA__`. Heavy Cloudflare — needs proxy. |
| `bring_a_trailer` | bringatrailer.com | Auctions. Reads embedded JS data. Cloudflare-gated. |
| `cars_and_bids` | carsandbids.com | Auctions. Public JSON API + `__NEXT_DATA__` fallback. DataDome-gated. |
| `copart` | copart.com | Salvage. Public Solr endpoint (`/lotdetails/solr/lotSearch`). |
| `iaai` | iaai.com | Salvage. `Search/GetVehicleSearchResults` JSON. |

> The four bot-protected sites (BaT, C&B, Autotrader, IAAI) will run reliably
> only with a residential / mobile-proxy `PROXY_URL` set. Cars.com, eBay,
> AutoTempest, CarsForSale, and Copart work without a proxy most of the time.

## Quick start

```bash
uv sync
uv run porsche-scraper -vv               # all sources, default criteria
uv run porsche-scraper --only cars_com   # one source
uv run porsche-scraper --price-max 30000 --year-min 2016
```

Outputs `listings.json` and `listings.csv` to `./porsche_output/` by default.
The CLI also prints the top-10 cheapest finds.

## Environment variables

| Var | Purpose |
|-----|---------|
| `PROXY_URL` | `http://user:pass@host:port` residential proxy for bot-protected sites. |
| `EBAY_OAUTH_TOKEN` | If set, the eBay scraper uses the Browse API instead of HTML scraping. |

## Adding a new site

1. Create `src/porsche_scraper/scrapers/<slug>.py` with a `BaseScraper`
   subclass that returns `Listing` objects.
2. Append it to `ALL_SCRAPERS` in `registry.py`.
3. Add a fixture-based parser test under `tests/porsche/`.

## Architecture

```
src/porsche_scraper/
├── models.py       ← Listing schema, TitleStatus enum, parse_* helpers
├── filters.py      ← FilterCriteria + matches()
├── http_client.py  ← fetch_text / fetch_json / fetch_text_stealth (curl-cffi)
├── base.py         ← BaseScraper ABC with safe_run() error swallowing
├── registry.py     ← ALL_SCRAPERS list + build_scrapers()
├── pipeline.py     ← run_all() → dedupe → filter
├── output.py       ← JSON + CSV writers
├── cli.py          ← `porsche-scraper` entrypoint
└── scrapers/       ← per-site modules
```

Listings are deduplicated by **VIN** first, then by `(source, listing_id)`,
then by URL hash. When the same VIN appears across sources, the richer
record (price present + higher mileage value) wins.
