# Screaming Frog → Porsche Dashboard

Two ways to drive this:

1. **Automated**: `.github/workflows/porsche-refresh.yml` runs SF on a
   GitHub Actions runner using your licence, opens a PR with the
   refreshed dashboard. **One-time setup** — add two secrets:

   Go to https://github.com/highwaymarketingco-wq/foreclosure-scraper/settings/secrets/actions
   and add:

   | Secret | Value |
   |---|---|
   | `SF_LICENCE_USERNAME` | Your Screaming Frog account email/username |
   | `SF_LICENCE_KEY` | Your Screaming Frog licence key |

   After that, the workflow runs on a cron (Tue + Fri 09:00 UTC by
   default — edit the `cron:` line) or via *Actions → Porsche
   dashboard refresh → Run workflow*. It opens a PR; you click merge.

2. **Manual**: run SF locally and let `scripts/sf_crawl.py` chain it
   into the importer. Details below.

## TL;DR — one-command flow (headless SF)

```bash
# Single site
uv run python scripts/sf_crawl.py cars_com

# Multiple
uv run python scripts/sf_crawl.py cars_com bring_a_trailer classiccars

# Everything, then commit + push so Pages updates
uv run python scripts/sf_crawl.py --all --push

# Includes Elferspot etc. where price is hidden behind "request quote":
uv run python scripts/sf_crawl.py --all --push --allow-unknown-price
```

`scripts/sf_crawl.py` discovers your SF binary (or honour `SF_BINARY`
env var), drives the crawl with the right per-site seed URL +
include-regex, then pipes the export through the importer.

Binary auto-detection paths:
- Linux: `/usr/bin/screamingfrogseospider` or `which screamingfrogseospider`
- macOS: `/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher`
- Windows: `%ProgramFiles%\Screaming Frog SEO Spider\ScreamingFrogSEOSpiderCli.exe`

Set `SF_BINARY=/path/to/screamingfrogseospider` to override.

Run `uv run python scripts/sf_crawl.py --list` to see the presets:

| Preset | Seed | Mode |
|---|---|---|
| `cars_com` | cars.com search URL (911/Cayman/Boxster filtered server-side) | spider |
| `bring_a_trailer` | bringatrailer.com/porsche/ | spider |
| `classiccars` | classiccars.com sitemap-index | sitemap |
| `elferspot` | elferspot.com sitemap-index | sitemap |
| `hemmings` | hemmings.com Porsche search | spider |
| `carsforsale` | carsforsale.com sitemap-index | sitemap |
| `copart` | copart-sitemaps.com sitemap-index | sitemap |
| `iaai` | iaai.com sitemap-index | sitemap |
| `autobidmaster` | autobidmaster.com sitemap-index | sitemap |
| `carsandbids` | carsandbids.com sitemap | sitemap |

## Lower-level: bring-your-own CSV

If you ran the SF GUI manually and have a CSV already:

```bash
uv run python scripts/import_sf_csv.py ~/Downloads/cars_com.csv [more.csv ...]
git add docs/porsche.json docs/porsche.csv
git commit -m "porsche: refresh from SF" && git push
```

The importer merges new rows into the existing `docs/porsche.json`
(de-duped by VIN → (source, listing_id) → URL hash). Pass `--no-merge`
to start fresh.

## Custom extractors (optional, big wins for price)

Without a config the wrapper still gets URL + page title + meta tags
from SF — enough to extract year + model from URL slugs on the
sitemap-friendly sites (cars.com, BaT, ClassicCars, Elferspot,
CarsForSale, Copart).

To get **price + mileage + image** baked into the SF export instead of
needing a second-pass detail fetch, drop a per-site config at
`scripts/screaming_frog/configs/<preset>.seospiderconfig`. The wrapper
passes it via `--config` automatically.

Two ways to create one:

1. **GUI on any machine** — open SF, set Custom Extraction rules per
   the per-site selector tables below, File → Configuration → Save As.
   Commit the file to the repo so headless invocations on other
   machines reuse it.
2. **Hand-write the XML** — SF's `.seospiderconfig` is XML; you can
   compose a minimal version with just the `<custom-extraction>` block.

## Per-site selector reference

The importer recognises these column names (case-insensitive — see the
`COLUMN_ALIASES` table in `scripts/import_sf_csv.py`):

| Field        | Aliases                                       |
|--------------|-----------------------------------------------|
| `URL`        | URL, Address, Page URL, Loc                   |
| `Year`       | Year, Model Year, Vehicle Year                |
| `Model`      | Model, Vehicle Model                          |
| `Trim`       | Trim, Variant, Package                        |
| `Price`      | Price, List Price, Asking Price, Price 1      |
| `Bid`        | Bid, Current Bid, High Bid                    |
| `Mileage`    | Mileage, Odometer, Miles                      |
| `Location`   | Location, City, State, ZIP                    |
| `Title Status` | Title Status, Title, Salvage, Title Type    |
| `VIN`        | VIN                                           |
| `Image`      | Image, Image Src, Photo, og:image             |
| `Title 1`    | Title 1, Page Title (fallback for human text) |

### cars.com

- **Crawl mode:** List (paste cars.com vehicle URLs)
- **Easier path:** SF can read JSON-LD / web-component attributes; but
  cars.com puts the whole record in the fuse-card attribute. Just
  extract it once and the importer parses it.
- **Seed:** the search URL works as a single page if you set crawl depth
  to 1 and "Extract HTML embedded JSON":
  ```
  https://www.cars.com/shopping/results/?stock_type=used&makes[]=porsche
  &models[]=porsche-911&models[]=porsche-718_cayman&models[]=porsche-cayman
  &models[]=porsche-718_boxster&models[]=porsche-boxster
  &year_min=2014&page_size=100
  ```
- **Extraction (Configuration → Custom → Custom Extraction):**

  | Name | Type | Selector |
  |---|---|---|
  | URL | n/a | use SF's `Address` column |
  | Year | CSSPath, Attribute | `fuse-card[data-vehicle-details]` → attribute `data-vehicle-details` (JSON; importer parses) |

  *Or* just spider the vehicle-detail pages directly and use:
  | Name | Type | Selector |
  |---|---|---|
  | Price | CSSPath, Extract Text | `.price-section .primary-price` |
  | Mileage | CSSPath, Extract Text | `.mileage` |
  | Year | RegEx | `(20\d{2})` against the Title |

### Bring a Trailer

- **Crawl mode:** Spider, starting at `https://bringatrailer.com/porsche/`
- **Include path:** `/listing/` (only crawl listing pages)
- **Exclude paths:** `wheels-`, `parts-`, `memorabilia-`, `seats-`,
  `literature-`, `banner-`, `bodywork-` (these are accessory auctions)
- **Extraction:**

  | Name | Selector (CSSPath, Extract Text) |
  |---|---|
  | Year | `h1.post-title` (extracts text; importer regex-parses the year) |
  | Bid | `.bid-formatted` |
  | Mileage | `.essentials li:contains('Miles')` |
  | Location | `.essentials li:contains('Location')` |
  | Image | `meta[property='og:image']` → attribute `content` |

### ClassicCars.com

- **Crawl mode:** List from sitemaps
- **Seed (paste into SF in List mode):**
  - `https://ccpublic.blob.core.windows.net/sitemaps/sitemap_listings_1.xml.gz` through
  - `https://ccpublic.blob.core.windows.net/sitemaps/sitemap_listings_78.xml.gz`
  - (or use **Crawl → Custom Search → Read sitemap_index** if your SF
    version supports it)
- **Include filter:** `porsche`
- **Extraction (JSON-LD):**

  | Name | Selector |
  |---|---|
  | Year | XPath: `//script[@type='application/ld+json']` → extract text, regex `"name":"(\d{4})\s` |
  | Price | XPath: `//script[@type='application/ld+json']` → extract text, regex `"price":"([\d.]+)"` |
  | Model | RegEx against Title 1: `Porsche\s+([A-Za-z0-9-]+)` |
  | Image | `meta[property='og:image']` content |
  | Location | RegEx against URL: `for-sale-in-([a-z-]+)-([a-z]+)` |

### Elferspot

- **Crawl mode:** List, seeded from `fahrzeug_en-sitemap*.xml`
- **Include:** `/en/car/porsche-`
- **Extraction:**

  | Name | Selector |
  |---|---|
  | Year | RegEx against URL: `porsche-[a-z0-9-]+?-(\d{4})-\d+/?` |
  | Model | RegEx against URL: `porsche-([a-z0-9-]+?)-\d{4}-\d+/?` |
  | Image | `meta[property='og:image']` content |
  | Title 1 | (SF default) |
  | Price | (skip — Elferspot is "POA". The importer will accept the row without one.) |

Pass `--allow-unknown-price` when importing Elferspot CSVs.

### Hemmings

- **Crawl mode:** Spider with realistic UA (SF setting: User-Agent → Chrome)
- **Seed:** `https://www.hemmings.com/classifieds/cars-for-sale/porsche?MinYear=2014&MaxPrice=45000`
- **Use SF's JS rendering** (`Configuration → Spider → Rendering → JavaScript`)
- **Extraction:**

  | Name | Selector |
  |---|---|
  | Price | `.price` |
  | Mileage | `.mileage` |
  | Location | `.location` |
  | Year | XPath: `//script[@type='application/ld+json']` → regex `"vehicleModelDate":"?(\d{4})"?` |

### Carsforsale.com

- Sitemap index: `https://www.carsforsale.com/sitemap_index.xml`
- Use sub-sitemap `sitemap_listing_*.xml.gz`
- Include: `porsche`
- Same JSON-LD extraction as ClassicCars.

### Salvage brokers (SCA, AutoBidMaster, A Better Bid)

These all use very similar `.car-item__*` markup. One extractor set works
for all three:

| Name | Selector |
|---|---|
| Year | `.car-item__title a` → regex `(\d{4})` |
| Bid | `.car-item__price, .price` |
| Mileage | `.car-item__odo, .odometer` |
| Location | `.car-item__location` |
| Title Status | `.car-item__doc, .title-doc` |

### Copart

- **Seed:** `https://www.copart-sitemaps.com/sitemap-index.xml`
- **Use JS rendering** (Copart is heavy SPA)
- **Include:** URL contains `/lot/`
- **Extraction:**

  | Name | Selector |
  |---|---|
  | Year | XPath: `//*[@id='lotYearMakeModel']` → regex `(\d{4})` |
  | Model | XPath: `//*[@id='lotYearMakeModel']` |
  | Bid | XPath: `//*[contains(@class,'current-bid')]` |
  | Mileage | XPath: `//*[contains(@class,'odometer')]` |
  | Title Status | XPath: `//*[contains(@class,'title-document')]` |
  | Location | XPath: `//*[contains(@class,'yard-name')]` |
  | VIN | XPath: `//*[@id='vinAnchor']/text()` |

## Tips

- **Limit crawl depth.** Most sites have infinite pagination chains. For
  search-seeded crawls, set depth=1 (page contains all results); for
  sitemap-seeded List crawls, depth is irrelevant.
- **Politeness:** set Configuration → Speed → 2 URLs/sec for sites
  you care about staying friendly with (Hemmings, ClassicCars, BaT).
- **Export only what you need:** Bulk Export → "Custom Extraction (All)"
  gives one row per crawled URL with all your extractor columns. That's
  the cleanest input for the importer.
- **Multiple CSVs at once:** the importer accepts multiple paths and
  merges them all into one dashboard refresh.

## Validating before push

After import, eyeball the printed `by source` count. Then open
`docs/porsche.html` locally:

```bash
python -m http.server -d docs 8000
# → open http://localhost:8000/porsche.html
```

If it looks right, commit + push and the live dashboard updates.
