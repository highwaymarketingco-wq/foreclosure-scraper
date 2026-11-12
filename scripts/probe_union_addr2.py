"""ADVERSARIAL probe v3: type a Union SC address into the qPublic autocomplete,
select the first suggestion via keyboard, land on the parcel report card, and
read the actual Sales Information + Building sqft values.

Per compliance: per-subject, low-volume lookup of a PUBLIC assessor record.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ADDR = sys.argv[1] if len(sys.argv) > 1 else "114 JENKINS"
SEARCH_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=861&LayerID=16112&PageTypeID=2&PageID=7168"
)
safe = ADDR.replace(" ", "_")
OUT = Path(f"/tmp/union_card_{safe}.html")
TXT = Path(f"/tmp/union_card_{safe}.txt")


def main() -> None:
    from scrapling.fetchers import StealthyFetcher

    print(f"[probe] address {ADDR!r}", flush=True)
    cap = {"url": "", "html": "", "text": ""}

    def page_action(page):
        try:
            page.set_default_timeout(20000)
            page.wait_for_timeout(2500)
            for sel in ["a:has-text('Agree')", "input[value='Agree']", "button:has-text('Agree')"]:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    print(f"[probe] agreed via {sel}", flush=True)
                    page.wait_for_timeout(2500)
                    break
            # find the location-address autocomplete input
            box = None
            for sel in ["input[id*='Address'][type='text']", "input[id*='txtAddress']"]:
                box = page.query_selector(sel)
                if box:
                    break
            if not box:
                print("[probe] NO address box found", flush=True)
                return page
            box.click()
            box.type(ADDR, delay=120)
            print("[probe] typed; waiting for autocomplete", flush=True)
            # wait for jquery-ui autocomplete list, then MOUSE-click first option
            clicked = False
            try:
                page.wait_for_selector("ul.ui-autocomplete li a, .ui-menu-item a, ul.ui-autocomplete li", timeout=10000)
                print("[probe] autocomplete visible; mouse-click first", flush=True)
                for osel in ["ul.ui-autocomplete li a", ".ui-menu-item a", "ul.ui-autocomplete li"]:
                    opt = page.query_selector(osel)
                    if opt:
                        opt.click()
                        clicked = True
                        print(f"[probe] clicked option via {osel}", flush=True)
                        break
            except Exception as e:
                print(f"[probe] no autocomplete ({e})", flush=True)
            if not clicked:
                # fall back to clicking the panel Search button
                for bsel in ["input[id*='Address'][type='submit']", "input[id*='btnSearchAddress']", "input[value='Search']"]:
                    b = page.query_selector(bsel)
                    if b:
                        b.click()
                        print(f"[probe] clicked Search button {bsel}", flush=True)
                        break
            # the select usually triggers navigation to the report card
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            cap["url"] = page.url
            cap["html"] = page.content()
            cap["text"] = page.inner_text("body")
        except Exception as e:
            print(f"[probe] note: {e}", flush=True)
            try:
                cap["url"] = page.url
                cap["html"] = page.content()
                cap["text"] = page.inner_text("body")
            except Exception:
                pass
        return page

    try:
        page = StealthyFetcher.fetch(
            SEARCH_URL, page_action=page_action,
            headless=False, network_idle=True, timeout=90000, solve_cloudflare=True,
        )
    except TypeError:
        page = StealthyFetcher.fetch(SEARCH_URL, headless=False, network_idle=True, timeout=90000)

    html = cap["html"] or getattr(page, "html_content", "") or ""
    text = cap["text"]
    if not text:
        try:
            text = page.get_all_text(ignore_tags=("script", "style"))
        except Exception:
            text = ""
    OUT.write_text(html, encoding="utf-8")
    TXT.write_text(text, encoding="utf-8")
    print(f"[probe] FINAL url={cap['url']}", flush=True)
    print(f"[probe] html_len={len(html)} text_len={len(text)} wrote {OUT}", flush=True)

    low = text.lower()
    for marker, label in [
        ("sales information", "SALES_MODULE_PRESENT"),
        ("no data available", "NO_DATA_NOTE"),
        ("sale price", "SALEPRICE_LABEL"),
        ("sales price", "SALESPRICE_LABEL"),
        ("sale date", "SALEDATE_LABEL"),
        ("deed book", "DEEDBOOK_LABEL"),
        ("first floor sq ft", "FIRSTFLOOR_SQFT"),
        ("heated", "HEATED_LABEL"),
        ("living area", "LIVINGAREA_LABEL"),
        ("year built", "YEARBUILT_LABEL"),
    ]:
        if marker in low:
            print(f"[marker] {label}", flush=True)
    # context around Sales Information
    idx = low.find("sales information")
    if idx >= 0:
        print("[context-sales] " + repr(text[max(0, idx-40):idx+400]), flush=True)
    for m in re.finditer(r"\$[\d,]{3,}", text):
        print(f"[$] {m.group(0)}", flush=True)


if __name__ == "__main__":
    main()
