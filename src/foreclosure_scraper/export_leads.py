"""Export Listings to multiple formats: HTML, CSV, XLSX, PDF, image.

Takes a list of Listing objects and writes each requested format into
``output_dir``. Returns a dict mapping format name to the output file Path.

Available formats (depends on installed packages):
  - html   : f-string HTML table (always available, no deps)
  - csv    : stdlib csv module (always available)
  - xlsx   : pandas + openpyxl
  - pdf    : Playwright (render HTML then page.pdf())
  - image  : Playwright screenshot of the HTML table

Playwright is used for both PDF and image export because weasyprint, pdfkit,
and reportlab are NOT installed in the venv, while Playwright IS. Playwright's
``page.pdf()`` uses Chromium's print-to-PDF engine, which produces high-quality
output from HTML+CSS.

Usage:
    from foreclosure_scraper.export_leads import export_leads
    paths = export_leads(listings, "output/", formats=['html','csv','pdf','xlsx'])
    # -> {'html': Path('output/leads.html'), 'csv': Path(...), ...}

Each format is independent: if one fails (e.g. Playwright not installed for
pdf/image), the others still succeed and the failed format is omitted from
the returned dict with a warning logged.
"""
from __future__ import annotations

import asyncio
import csv as csv_module
import os
from datetime import datetime
from pathlib import Path
from typing import Sequence

import structlog

from .models import Listing

log = structlog.get_logger()

# Column order for tabular exports (CSV, XLSX, and HTML table header).
# These are the fields a lead-gen operator wants in a spreadsheet view.
COLUMNS: list[tuple[str, str]] = [
    ("source", "Source"),
    ("listing_type", "Type"),
    ("street_address", "Address"),
    ("city", "City"),
    ("state", "State"),
    ("zip_code", "ZIP"),
    ("county", "County"),
    ("opening_bid", "Bid/Price"),
    ("sale_date", "Sale Date"),
    ("auction_status", "Status"),
    ("property_kind", "Property Kind"),
    ("bedrooms", "Beds"),
    ("bathrooms", "Baths"),
    ("living_sqft", "Sqft"),
    ("acreage", "Acreage"),
    ("year_built", "Year Built"),
    ("assessed_value", "Assessed Value"),
    ("market_value", "Market Value"),
    ("parcel_id", "Parcel ID"),
    ("case_number", "Case Number"),
    ("latitude", "Lat"),
    ("longitude", "Lng"),
    ("source_url", "URL"),
    ("description", "Description"),
]


def _row_value(listing: Listing, field: str) -> str:
    """Extract a display-friendly string for a Listing field."""
    val = getattr(listing, field, None)
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M")
    # Enums (ListingType, PropertyKind) — use their .value
    if hasattr(val, "value"):
        return str(val.value)
    if isinstance(val, float):
        # Drop trailing .0 for whole numbers
        if val == int(val):
            return str(int(val))
        return f"{val:.2f}"
    return str(val)


def _rows(listings: Sequence[Listing]) -> list[list[str]]:
    """Build a list of row-lists (one per listing) for tabular export."""
    return [[_row_value(li, field) for field, _ in COLUMNS] for li in listings]


def _header_labels() -> list[str]:
    return [label for _, label in COLUMNS]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
         margin: 0; padding: 20px; background: #f5f5f5; color: #222; }}
  h1 {{ font-size: 1.4em; margin: 0 0 4px 0; }}
  .meta {{ color: #666; font-size: 0.85em; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 0.8em; }}
  th {{ background: #2c3e50; color: #fff; text-align: left; padding: 8px 10px;
        position: sticky; top: 0; white-space: nowrap; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #e0e0e0; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f9f9f9; }}
  tr:hover td {{ background: #eef5ff; }}
  a {{ color: #2980b9; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  td[class^="type-"] {{ font-weight: bold; }}
</style>
</head>
<body>
<h1>Foreclosure &amp; Auction Leads</h1>
<div class="meta">Generated {generated} &middot; {count} listings &middot; {sources} sources</div>
<table>
<thead><tr>{thead}</tr></thead>
<tbody>
{tbody}
</tbody>
</table>
</body>
</html>"""


def _build_html(listings: Sequence[Listing]) -> str:
    """Render an HTML table from listings using an f-string template."""
    thead = "".join(f"<th>{label}</th>" for label in _header_labels())

    rows_html = []
    for li in listings:
        cells = []
        for field, _ in COLUMNS:
            val = _row_value(li, field)
            if field == "source_url" and val:
                cells.append(
                    f'<td><a href="{val}" target="_blank">link</a></td>'
                )
            elif field == "listing_type" and val:
                cells.append(
                    f'<td class="type-{val}">{val}</td>'
                )
            else:
                cells.append(f"<td>{val}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    sources = len({li.source for li in listings}) if listings else 0
    return _HTML_TEMPLATE.format(
        title="Foreclosure Leads Export",
        generated=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        count=len(listings),
        sources=sources,
        thead=thead,
        tbody="\n".join(rows_html),
    )


def _export_html(listings: Sequence[Listing], output_path: Path) -> Path:
    """Write HTML table file. Always succeeds (no external deps)."""
    html = _build_html(listings)
    output_path.write_text(html, encoding="utf-8")
    log.info("export_leads.html_done", path=str(output_path), count=len(listings))
    return output_path


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def _export_csv(listings: Sequence[Listing], output_path: Path) -> Path:
    """Write CSV using the stdlib csv module. Always available."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(_header_labels())
        writer.writerows(_rows(listings))
    log.info("export_leads.csv_done", path=str(output_path), count=len(listings))
    return output_path


# ---------------------------------------------------------------------------
# XLSX (pandas + openpyxl)
# ---------------------------------------------------------------------------

def _export_xlsx(listings: Sequence[Listing], output_path: Path) -> Path:
    """Write XLSX via pandas (engine=openpyxl)."""
    import pandas as pd  # local import: keeps the dep optional at module level

    data = {}
    for field, label in COLUMNS:
        data[label] = [_row_value(li, field) for li in listings]
    df = pd.DataFrame(data)
    df.to_excel(output_path, index=False, engine="openpyxl")
    log.info("export_leads.xlsx_done", path=str(output_path), count=len(listings))
    return output_path


# ---------------------------------------------------------------------------
# PDF (Playwright)
# ---------------------------------------------------------------------------

async def _render_with_playwright(html_path: Path, output_path: Path,
                                   fmt: str) -> Path:
    """Render the HTML file to PDF or PNG using Playwright's Chromium.

    fmt: 'pdf' or 'image'.
    """
    from playwright.async_api import async_playwright

    file_url = f"file://{html_path.resolve()}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=30000)
            # Let the table render fully
            await page.wait_for_timeout(500)

            if fmt == "pdf":
                await page.pdf(
                    path=str(output_path),
                    format="Letter",
                    landscape=True,
                    print_background=True,
                    margin={"top": "0.5in", "bottom": "0.5in",
                            "left": "0.3in", "right": "0.3in"},
                )
            elif fmt == "image":
                # Full-page screenshot of the table
                await page.screenshot(
                    path=str(output_path),
                    full_page=True,
                    type="png",
                )
            else:
                raise ValueError(f"Unknown playwright format: {fmt}")
        finally:
            await browser.close()

    log.info("export_leads.playwright_done",
             fmt=fmt, path=str(output_path), count="n/a")
    return output_path


def _export_pdf(listings: Sequence[Listing], html_path: Path,
                output_path: Path) -> Path:
    """Write PDF by rendering the HTML via Playwright's page.pdf()."""
    # Ensure the HTML is already written (it should be, but be safe)
    if not html_path.exists():
        _export_html(listings, html_path)

    asyncio.run(_render_with_playwright(html_path, output_path, fmt="pdf"))
    log.info("export_leads.pdf_done", path=str(output_path), count=len(listings))
    return output_path


def _export_image(listings: Sequence[Listing], html_path: Path,
                  output_path: Path) -> Path:
    """Write a full-page PNG screenshot of the HTML table via Playwright."""
    if not html_path.exists():
        _export_html(listings, html_path)

    asyncio.run(_render_with_playwright(html_path, output_path, fmt="image"))
    log.info("export_leads.image_done", path=str(output_path), count=len(listings))
    return output_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def export_leads(
    listings: Sequence[Listing],
    output_dir: str | Path,
    formats: list[str] | None = None,
) -> dict[str, Path]:
    """Export listings to multiple file formats.

    Args:
        listings: Sequence of Listing objects to export.
        output_dir: Directory to write files into (created if missing).
        formats: List of format names to produce. Supported:
            'html', 'csv', 'xlsx', 'pdf', 'image'.
            Defaults to ['html', 'csv', 'pdf', 'xlsx'].

    Returns:
        Dict mapping each successfully-produced format name to its file Path.
        Formats that fail (missing dependency, etc.) are omitted from the
        dict and logged as a warning.
    """
    if formats is None:
        formats = ["html", "csv", "pdf", "xlsx"]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base_name = f"leads_{timestamp}"

    results: dict[str, Path] = {}

    # HTML is produced first because PDF and image depend on it.
    html_path = out_dir / f"{base_name}.html"
    if "html" in formats or "pdf" in formats or "image" in formats:
        try:
            _export_html(listings, html_path)
            if "html" in formats:
                results["html"] = html_path
        except Exception as exc:  # noqa: BLE001
            log.error("export_leads.html_failed", error=str(exc)[:200])

    for fmt in formats:
        if fmt == "html":
            # Already done above
            if "html" not in results and html_path.exists():
                results["html"] = html_path
            continue

        if fmt == "csv":
            path = out_dir / f"{base_name}.csv"
            try:
                results["csv"] = _export_csv(listings, path)
            except Exception as exc:  # noqa: BLE001
                log.error("export_leads.csv_failed", error=str(exc)[:200])

        elif fmt == "xlsx":
            path = out_dir / f"{base_name}.xlsx"
            try:
                results["xlsx"] = _export_xlsx(listings, path)
            except Exception as exc:  # noqa: BLE001
                log.error("export_leads.xlsx_failed", error=str(exc)[:200])

        elif fmt == "pdf":
            path = out_dir / f"{base_name}.pdf"
            try:
                results["pdf"] = _export_pdf(listings, html_path, path)
            except Exception as exc:  # noqa: BLE001
                log.warning("export_leads.pdf_failed",
                            error=str(exc)[:200],
                            hint="requires Playwright + Chromium browser")

        elif fmt == "image":
            path = out_dir / f"{base_name}.png"
            try:
                results["image"] = _export_image(listings, html_path, path)
            except Exception as exc:  # noqa: BLE001
                log.warning("export_leads.image_failed",
                            error=str(exc)[:200],
                            hint="requires Playwright + Chromium browser")

        else:
            log.warning("export_leads.unknown_format", fmt=fmt)

    log.info("export_leads.done", formats=list(results.keys()),
             count=len(listings))
    return results
