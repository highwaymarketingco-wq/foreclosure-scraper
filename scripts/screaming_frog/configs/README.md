# Per-site SF configs

Drop `<site>.seospiderconfig` files here (one per preset slug in
`scripts/sf_crawl.py`). The wrapper passes them via `--config` to
headless SF automatically.

A config typically defines:
- Custom Extraction rules (CSS/XPath → CSV columns)
- Spider rules (max depth, include/exclude patterns)
- Rendering mode (Text-only / JavaScript)
- Crawl politeness (req/sec, max URLs)

Generate via SF GUI: Configuration → set what you want → File →
Configuration → Save As → drop the resulting file here.

Or run without configs — the importer will still parse year + model
from URL slugs for the sitemap-friendly sites.
