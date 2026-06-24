"""ADVERSARIAL probe: open the Union County SC qPublic SALES SEARCH/RESULTS
page to find a real parcel that recorded an arm's-length sale, then read the
actual Sale Price + sqft off that parcel's report card.

Per compliance: per-subject, low-volume lookup of PUBLIC assessor records.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

# Union SC sales search page (PageTypeID=6 sales-search family). We'll let the
# page render and submit a broad date range to surface sold parcels.
SALES_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=861&LayerID=16112&PageTypeID=6&PageID=7172"
)
OUT = Path("/tmp/union_sales.html")
TXT = Path("/tmp/union_sales.txt")


def main() -> None:
    from scrapling.fetchers import StealthyFetcher

    url = sys.argv[1] if len(sys.argv) > 1 else SALES_URL
    print(f"[probe] fetching {url}", flush=True)

    def page_action(page):
        try:
            page.wait_for_timeout(3000)
            for sel in ["a:has-text('Agree')", "input[value='Agree']", "button:has-text('Agree')"]:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click()
                        print(f"[probe] clicked disclaimer via {sel}", flush=True)
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue
            # Try to submit the sales search with a wide range / min sale price.
            page.wait_for_timeout(1500)
        except Exception as e:
            print(f"[probe] page_action note: {e}", flush=True)
        return page

    kwargs = dict(headless=False, network_idle=True, timeout=90000, solve_cloudflare=True)
    try:
        page = StealthyFetcher.fetch(url, page_action=page_action, **kwargs)
    except TypeError:
        page = StealthyFetcher.fetch(url, headless=False, network_idle=True, timeout=90000)

    html = getattr(page, "html_content", "") or ""
    try:
        text = page.get_all_text(ignore_tags=("script", "style"))
    except Exception:
        text = ""
    OUT.write_text(html, encoding="utf-8")
    TXT.write_text(text, encoding="utf-8")
    print(f"[probe] status={getattr(page,'status',None)} html_len={len(html)} text_len={len(text)}", flush=True)
    # surface any KeyValue / parcel links + dollar amounts
    for m in set(re.findall(r"KeyValue=([0-9\-+ %A-Za-z]{6,30})", html)):
        print(f"[keyvalue] {m}", flush=True)
    for m in re.finditer(r"\$[\d,]{4,}", text):
        print(f"[$] {m.group(0)}", flush=True)


if __name__ == "__main__":
    main()
