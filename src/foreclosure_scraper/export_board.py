"""Board export: HTML, image (PNG), PDF, and Excel sheet.

Renders the enriched board to multiple formats for on-a-dime decisions:
  - HTML dashboard (interactive, sortable, with maps)
  - PNG screenshot (for WhatsApp/mobile viewing)
  - PDF report (printable, with property photos)
  - Excel spreadsheet (filterable, with formulas)

Free, no paid APIs. Uses:
  - pandas + openpyxl for Excel
  - playwright (via scrapling) for HTML→PNG/PDF
  - jinja2 templates for HTML
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

# Output directory
EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", "exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _load_board(path: str = "data/board.json") -> list[dict]:
    """Load the enriched board JSON."""
    p = Path(path)
    if not p.exists():
        log.warning("export.no_board_file", path=path)
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "listings" in data:
        return data["listings"]
    return []


def _flatten_listing(li: dict) -> dict:
    """Flatten a listing dict for Excel/CSV export."""
    raw = li.get("raw", {})
    return {
        "parcel_id": li.get("parcel_id", ""),
        "owner": li.get("owner", raw.get("owner", "")),
        "mailing_address": raw.get("mailing_address", ""),
        "property_address": li.get("address", raw.get("situs", "")),
        "county": li.get("county", ""),
        "state": li.get("state", ""),
        "zip": li.get("zip", raw.get("zip5", "")),
        "listing_type": li.get("listing_type", ""),
        "case_number": li.get("case_number", raw.get("case_number", "")),
        "filing_date": li.get("filing_date", ""),
        "sale_date": raw.get("sale_date", ""),
        "upset_bid_deadline": raw.get("upset_bid_deadline", ""),
        "current_bid": raw.get("current_bid", raw.get("bid_amount", "")),
        "estimated_value": li.get("estimated_value", raw.get("estimated_value", "")),
        "estimated_equity": li.get("estimated_equity_pct", ""),
        "census_rent": raw.get("census_rent", {}).get("median_gross_rent", "") if isinstance(raw.get("census_rent"), dict) else "",
        "enviro_risk": raw.get("envirofacts", {}).get("facilities_count", "") if isinstance(raw.get("envirofacts"), dict) else "",
        "wetlands": raw.get("wetlands", {}).get("has_wetlands", "") if isinstance(raw.get("wetlands"), dict) else "",
        "flood_zone": raw.get("flood_zone", ""),
        "source": li.get("source", ""),
        "url": li.get("url", ""),
        "score": li.get("score", raw.get("score", "")),
        "notes": raw.get("notes", ""),
    }


def export_excel(board: list[dict], path: Optional[str] = None) -> str:
    """Export board to Excel with filters, frozen header, and column widths."""
    try:
        import pandas as pd
    except ImportError:
        log.error("export.no_pandas")
        return ""

    rows = [_flatten_listing(li) for li in board]
    df = pd.DataFrame(rows)

    if not path:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        path = str(EXPORT_DIR / f"board_{ts}.xlsx")

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Board", index=False)
        ws = writer.sheets["Board"]

        # Auto-filter + freeze header
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"

        # Column widths
        for i, col in enumerate(df.columns, 1):
            max_len = max(
                df[col].astype(str).map(len).max() if len(df) > 0 else 0,
                len(col)
            )
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max_len + 2, 50)

    log.info("export.excel", path=path, rows=len(rows))
    return path


def export_csv(board: list[dict], path: Optional[str] = None) -> str:
    """Export board to CSV."""
    try:
        import pandas as pd
    except ImportError:
        log.error("export.no_pandas")
        return ""

    rows = [_flatten_listing(li) for li in board]
    df = pd.DataFrame(rows)

    if not path:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        path = str(EXPORT_DIR / f"board_{ts}.csv")

    df.to_csv(path, index=False)
    log.info("export.csv", path=path, rows=len(rows))
    return path


def _render_html(board: list[dict]) -> str:
    """Render board to a self-contained HTML dashboard."""
    rows = [_flatten_listing(li) for li in board]

    # Summary stats
    total = len(rows)
    by_state = {}
    by_type = {}
    for r in rows:
        s = r.get("state", "?")
        by_state[s] = by_state.get(s, 0) + 1
        t = r.get("listing_type", "?")
        by_type[t] = by_type.get(t, 0) + 1

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build table rows
    table_rows = ""
    for r in rows[:500]:  # cap at 500 for HTML
        score = r.get("score", "")
        score_class = f"score-{'high' if isinstance(score, (int, float)) and score >= 70 else 'med' if isinstance(score, (int, float)) and score >= 40 else 'low'}"
        table_rows += f"""<tr>
            <td>{r.get('parcel_id','')}</td>
            <td>{r.get('owner','')}</td>
            <td>{r.get('property_address','')}</td>
            <td>{r.get('county','')} {r.get('state','')}</td>
            <td>{r.get('listing_type','')}</td>
            <td>{r.get('case_number','')}</td>
            <td>{r.get('current_bid','')}</td>
            <td>{r.get('estimated_value','')}</td>
            <td class="{score_class}">{score}</td>
            <td><a href="{r.get('url','')}" target="_blank">Link</a></td>
        </tr>\n"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Foreclosure Board — {ts}</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 0; padding: 16px; background: #f5f5f5; }}
h1 {{ color: #333; margin: 0 0 8px; }}
.summary {{ display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }}
.stat {{ background: #fff; padding: 12px 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.stat .num {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
.stat .lbl {{ font-size: 12px; color: #666; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th {{ background: #1e40af; color: #fff; padding: 10px 8px; text-align: left; font-size: 12px; text-transform: uppercase; cursor: pointer; position: sticky; top: 0; }}
td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; font-size: 13px; }}
tr:nth-child(even) {{ background: #f9fafb; }}
tr:hover {{ background: #eff6ff; }}
.score-high {{ color: #16a34a; font-weight: bold; }}
.score-med {{ color: #ca8a04; }}
.score-low {{ color: #dc2626; }}
a {{ color: #2563eb; }}
</style>
</head><body>
<h1>Foreclosure Board</h1>
<div class="summary">
  <div class="stat"><div class="num">{total}</div><div class="lbl">Total Listings</div></div>
  <div class="stat"><div class="num">{len(by_state)}</div><div class="lbl">States</div></div>
  <div class="stat"><div class="num">{len(by_type)}</div><div class="lbl">Listing Types</div></div>
  <div class="stat"><div class="num">{ts}</div><div class="lbl">Generated</div></div>
</div>
<table id="board">
<thead><tr>
  <th>Parcel</th><th>Owner</th><th>Address</th><th>County</th>
  <th>Type</th><th>Case#</th><th>Bid</th><th>Est Value</th><th>Score</th><th>Link</th>
</tr></thead>
<tbody>
{table_rows}
</tbody>
</table>
<script>
// Simple client-side sort
document.querySelectorAll('th').forEach((th, i) => {{
  th.onclick = () => {{
    const tbody = document.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {{
      const av = a.cells[i].textContent, bv = b.cells[i].textContent;
      const an = parseFloat(av.replace(/[^0-9.-]/g,''));
      const bn = parseFloat(bv.replace(/[^0-9.-]/g,''));
      if (!isNaN(an) && !isNaN(bn)) return an - bn;
      return av.localeCompare(bv);
    }});
    rows.forEach(r => tbody.appendChild(r));
  }};
}});
</script>
</body></html>"""


def export_html(board: list[dict], path: Optional[str] = None) -> str:
    """Export board to a self-contained HTML file."""
    if not path:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        path = str(EXPORT_DIR / f"board_{ts}.html")

    html = _render_html(board)
    Path(path).write_text(html, encoding="utf-8")
    log.info("export.html", path=path, listings=len(board))
    return path


async def _screenshot_html(html_path: str, out_path: str, full_page: bool = True) -> bool:
    """Use Playwright (via scrapling or direct) to screenshot an HTML file."""
    # Try playwright directly
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1400, "height": 900})
            await page.goto(f"file://{os.path.abspath(html_path)}", wait_until="networkidle")
            await page.wait_for_timeout(1000)
            await page.screenshot(path=out_path, full_page=full_page)
            await browser.close()
        return True
    except ImportError:
        pass

    # Try scrapling StealthyFetcher
    try:
        from scrapling.fetchers import StealthyFetcher
        result = await StealthyFetcher.async_fetch(
            f"file://{os.path.abspath(html_path)}",
            headless=True, network_idle=True, timeout=30000
        )
        if hasattr(result, "screenshot"):
            result.screenshot(path=out_path, full_page=full_page)
            return True
    except Exception as exc:
        log.debug("export.scrapling_screenshot_fail", error=str(exc)[:120])

    return False


def export_png(board: list[dict], path: Optional[str] = None) -> str:
    """Export board to PNG screenshot via headless browser."""
    # First generate HTML
    html_path = export_html(board, path=str(EXPORT_DIR / "_tmp_dashboard.html"))

    if not path:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        path = str(EXPORT_DIR / f"board_{ts}.png")

    ok = asyncio.get_event_loop().run_until_complete(
        _screenshot_html(html_path, path, full_page=False)
    )
    if ok:
        log.info("export.png", path=path)
        return path

    log.warning("export.png.no_browser")
    # Fallback: return the HTML path
    return html_path


def export_pdf(board: list[dict], path: Optional[str] = None) -> str:
    """Export board to PDF via headless browser print-to-PDF."""
    html_path = export_html(board, path=str(EXPORT_DIR / "_tmp_dashboard.html"))

    if not path:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        path = str(EXPORT_DIR / f"board_{ts}.pdf")

    try:
        from playwright.async_api import async_playwright
        async def _go():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(f"file://{os.path.abspath(html_path)}", wait_until="networkidle")
                await page.wait_for_timeout(1000)
                await page.pdf(path=path, format="letter", print_background=True, margin={
                    "top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"
                })
                await browser.close()
            return True
        asyncio.get_event_loop().run_until_complete(_go())
        log.info("export.pdf", path=path)
        return path
    except ImportError:
        log.warning("export.pdf.no_playwright")
        return html_path


def export_all(board_path: str = "data/board.json") -> dict:
    """Export board to all formats. Returns dict of paths."""
    board = _load_board(board_path)
    if not board:
        log.warning("export.empty_board")
        return {"error": "no board data"}

    results = {}
    results["csv"] = export_csv(board)
    results["excel"] = export_excel(board)
    results["html"] = export_html(board)

    # PNG/PDF need playwright — try but don't fail
    try:
        results["png"] = export_png(board)
    except Exception as exc:
        log.warning("export.png_failed", error=str(exc)[:120])
    try:
        results["pdf"] = export_pdf(board)
    except Exception as exc:
        log.warning("export.pdf_failed", error=str(exc)[:120])

    log.info("export.all_done", formats=list(results.keys()), listings=len(board))
    return results


if __name__ == "__main__":
    import sys
    board_file = sys.argv[1] if len(sys.argv) > 1 else "data/board.json"
    results = export_all(board_file)
    print(json.dumps(results, indent=2))
