# porsche-scraper

Aggregate **cheap Porsche listings** across used-car, auction, salvage,
and government-surplus sites.

## Search criteria

A listing is **kept** when **all** of these hold:

| Rule | Logic |
|------|-------|
| Year | between **2014** and **current year** inclusive (see `--year-min` / `--year-max`). |
| Price | **≤ $45,000** *OR* title is **salvage** / **rebuilt**. |
| Drivable | not **parts-only**, not **non-running** / **blown motor** / etc. Salvage-auction sites' "Run & Drive = No" flag is also rejected. |
| Excluded models | **Panamera**, **Cayenne**, **Macan** — substring match on title + model fields. |

The defaults are tunable via `FilterCriteria` (`filters.py`) and CLI flags.

## Sources (41 total)

Listed by category. **Reliability tier** indicates how well each scraper
has been validated end-to-end:

- 🟢 **green** — fixture tests + verified to return real data
- 🟡 **yellow** — fixture tests pass; selectors built from documented
  patterns but **needs DOM probe** before reliable production use
- 🔴 **red** — site is JS-rendered SPA or heavily bot-protected; needs
  Playwright + residential proxy. Scraper structure is in place but will
  return [] from a plain datacenter IP.

### Mainstream used-car

| Slug | Site | Tier |
|---|---|---|
| `cars_com` | cars.com | 🟢 JSON-LD primary, HTML fallback. Two passes (price-capped + salvage-only) |
| `ebay_motors` | ebay.com Motors | 🟡 HTML; Browse API path if `EBAY_OAUTH_TOKEN` set. Often 503 from datacenter IPs. |
| `autotempest` | autotempest.com | 🟡 Metasearch deeplinks |
| `carsforsale` | carsforsale.com | 🟡 JSON-LD + HTML, stealth |
| `autotrader` | autotrader.com | 🔴 `__NEXT_DATA__` (Cloudflare — needs proxy) |

### Enthusiast auctions

| Slug | Site | Tier |
|---|---|---|
| `bring_a_trailer` | bringatrailer.com | 🟢 `.listing-card` DOM parse; verified live |
| `cars_and_bids` | carsandbids.com | 🟡 Public JSON API + `__NEXT_DATA__` fallback (DataDome) |
| `pcarmarket` | pcarmarket.com (Porsche-focused) | 🟡 Light Cloudflare |
| `hagerty_marketplace` | hagerty.com/marketplace | 🔴 Heavily JS-rendered; needs Playwright |
| `collecting_cars` | collectingcars.com | 🔴 Cloudflare full challenge |
| `themarket` | themarket.co.uk (was bonhams) | 🟡 |
| `autohunter` | autohunter.com | 🔴 Cloudflare managed challenge |
| `broad_arrow` | broadarrowauctions.com | 🔴 |
| `iconic_auctioneers` | iconicauctioneers.com (was silverstone) | 🟡 |

### Live collector houses

| Slug | Site | Tier |
|---|---|---|
| `mecum` | mecum.com | 🔴 DataDome |
| `barrett_jackson` | barrett-jackson.com | 🔴 Cloudflare + 402 paywall to non-browser UA |
| `rm_sothebys` | rmsothebys.com | 🟡 Next.js |
| `gooding` | goodingco.com | 🟡 |
| `bonhams_cars` | cars.bonhams.com | 🔴 Imperva |

### Salvage / insurance

| Slug | Site | Tier |
|---|---|---|
| `copart` | copart.com | 🟡 Solr endpoint `lotSearch` JSON |
| `iaai` | iaai.com | 🟡 `GetVehicleSearchResults` JSON |
| `sca_auction` | en.sca.auction | 🔴 Cloudflare; broker for Copart/IAA |
| `autobidmaster` | autobidmaster.com | 🔴 Cloudflare; sitemap discovery available |
| `abetter_bid` | abetter.bid (was abetterbid.com) | 🔴 Cloudflare |
| `cars4_bid` | cars4.bid | 🔴 Mirror of abetter.bid |
| `auctionexport` | auctionexport.com | 🟡 Light Cloudflare |

### Porsche-specific

| Slug | Site | Tier |
|---|---|---|
| `rennlist` | rennlist.com forums | 🟡 vBulletin; thread-title parse |
| `6speedonline` | 6speedonline.com forums | 🟡 same infra as Rennlist |
| `pca_mart` | classifieds.pca.org | 🟡 Member-only contact info; list is public |
| `elferspot` | elferspot.com | 🟡 EUR → USD conversion via `EUR_TO_USD` env |

### Government / seized

| Slug | Site | Tier |
|---|---|---|
| `govdeals` | govdeals.com | 🔴 Angular SPA — needs XHR endpoint or headless |
| `gsa_auctions` | gsaauctions.gov | 🔴 API endpoint speculative; needs verification |
| `public_surplus` | publicsurplus.com | 🔴 JS-rendered |
| `property_room` | propertyroom.com | 🔴 Login wall for many car details |
| `municibid` | municibid.com | 🔴 Cloudflare |
| `cws_marketing` | cwsmarketing.com (US Marshals) | 🔴 Frequently offline |

### General classifieds

| Slug | Site | Tier |
|---|---|---|
| `hemmings` | hemmings.com | 🔴 Kasada/Cloudflare; JSON-LD primary if you can get past WAF |
| `classiccars_com` | classiccars.com | 🟡 Light rate-limit |
| `autotrader_classics` | classics.autotrader.com | 🟡 |

### Peer-to-peer (off by default)

| Slug | Site | Tier | Notes |
|---|---|---|---|
| `fb_marketplace` | facebook.com/marketplace | 🔴 | Needs `FB_USER_COOKIE` env (full cookie string from logged-in browser) |
| `craigslist` | craigslist.org | 🟡 | Crawls per-city subdomains. Override via `CRAIGSLIST_CITIES` env (default: 20 large US cities) |

These two are **excluded by default**; enable with `--include-off` or
`--only fb_marketplace craigslist`.

### How to upgrade tier 🟡 → 🟢 or 🔴 → 🟡

1. Run the scraper alone: `uv run porsche-scraper --only <slug> -vv`
2. If it returns 0 rows, save the HTML the site actually serves and
   compare against the selectors in the scraper module.
3. Bot-protected sites (🔴): set `PROXY_URL=http://user:pass@host:port`
   to a residential proxy. If still blocked, swap to a Playwright-stealth
   fetcher (the `scrapling[fetchers]` dep is already installed).

## Quick start

```bash
uv sync
uv run porsche-scraper -vv                          # all default-on sources
uv run porsche-scraper --only bring_a_trailer cars_com
uv run porsche-scraper --include-off                # adds FB Marketplace + Craigslist
uv run porsche-scraper --price-max 30000 --year-min 2016
```

Outputs `listings.json` and `listings.csv` to `./porsche_output/` by
default. The CLI also prints the top-10 cheapest finds.

## Environment variables

| Var | Purpose |
|-----|---------|
| `PROXY_URL` | `http://user:pass@host:port` residential proxy for bot-protected sites. |
| `EBAY_OAUTH_TOKEN` | If set, the eBay scraper uses the Browse API instead of HTML scraping. |
| `FB_USER_COOKIE` | Logged-in FB cookie string; required for `fb_marketplace`. |
| `CRAIGSLIST_CITIES` | Comma-separated CL subdomains; defaults to 20 large US cities. |
| `EUR_TO_USD` | Override the Elferspot price conversion rate (default 1.08). |

## Adding a new site

If the site looks like one of the existing config-driven groups
(salvage broker, enthusiast auction, government), add a `SiteConfig` to
the matching module — no new file needed. Otherwise:

1. Create `src/porsche_scraper/scrapers/<slug>.py` with a `BaseScraper`
   subclass that returns `Listing` objects.
2. Append it to `ALL_SCRAPERS` in `registry.py`.
3. Add a fixture-based parser test under `tests/porsche/`.

## Architecture

```
src/porsche_scraper/
├── models.py            ← Listing schema, TitleStatus enum, parse_* helpers
├── filters.py           ← FilterCriteria + matches()
├── http_client.py       ← fetch_text / fetch_json / fetch_text_stealth (curl-cffi)
├── base.py              ← BaseScraper ABC with safe_run() error swallowing
├── registry.py          ← ALL_SCRAPERS list + build_scrapers()
├── pipeline.py          ← run_all() → dedupe → filter
├── output.py            ← JSON + CSV writers
├── cli.py               ← `porsche-scraper` entrypoint
└── scrapers/
    ├── cars_com.py                 (one-off)
    ├── ebay_motors.py              (one-off)
    ├── autotempest.py              (one-off)
    ├── carsforsale.py              (one-off)
    ├── autotrader.py               (one-off)
    ├── bring_a_trailer.py          (one-off)
    ├── cars_and_bids.py            (one-off)
    ├── copart.py                   (one-off)
    ├── iaai.py                     (one-off)
    ├── pcarmarket.py               (one-off)
    ├── elferspot.py                (one-off)
    ├── forum_classifieds.py        (Rennlist + 6Speed + PCA Mart)
    ├── salvage_brokers.py          (SCA + AutoBidMaster + ABetter.bid + Cars4.bid + AuctionExport)
    ├── enthusiast_auctions.py      (Hagerty + CollectingCars + TheMarket + AutoHunter + BroadArrow + Iconic)
    ├── live_collector.py           (Mecum + Barrett-Jackson + RM + Gooding + Bonhams Cars)
    ├── government_auctions.py      (GSA + GovDeals + PublicSurplus + PropertyRoom + Municibid + CWS Marketing)
    ├── general_classifieds.py      (Hemmings + ClassicCars.com + AutoTrader Classics)
    └── peer_to_peer.py             (FB Marketplace + Craigslist)
```

Listings are deduplicated by **VIN** first, then by `(source, listing_id)`,
then by URL hash. When the same VIN appears across sources, the richer
record (price present + higher mileage value) wins.
