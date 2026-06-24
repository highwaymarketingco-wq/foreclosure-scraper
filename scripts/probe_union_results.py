"""ADVERSARIAL probe v4: type address, click the address-panel SEARCH button
(returns a multi-result page with KeyValue links), follow the first result to
the report card, and read the actual Sales Information + Living Area values.

Per compliance: per-subject, low-volume lookup of a PUBLIC assessor record.
"""
from __future__ import annotations
import re, sys
from pathlib import Path

ADDR = sys.argv[1] if len(sys.argv) > 1 else "247 NEWLAND"
SEARCH_URL = ("https://qpublic.schneidercorp.com/Application.aspx"
              "?AppID=861&LayerID=16112&PageTypeID=2&PageID=7168")
safe = ADDR.replace(" ", "_")
OUT = Path(f"/tmp/union_res_{safe}.html"); TXT = Path(f"/tmp/union_res_{safe}.txt")


def main() -> None:
    from scrapling.fetchers import StealthyFetcher
    print(f"[probe] address {ADDR!r}", flush=True)
    cap = {"url": "", "html": "", "text": "", "keyvals": []}

    def page_action(page):
        try:
            page.set_default_timeout(15000)
            page.wait_for_timeout(2500)
            for sel in ["a:has-text('Agree')", "input[value='Agree']"]:
                el = page.query_selector(sel)
                if el:
                    el.click(); page.wait_for_timeout(2500); break
            # find the LOCATION ADDRESS panel: its input + its own Search button.
            box = None
            for sel in ["input[id*='Address'][type='text']", "input[id*='txtAddress']"]:
                box = page.query_selector(sel)
                if box: break
            if not box:
                print("[probe] NO address box", flush=True); return page
            box.click(); box.fill(""); box.type(ADDR, delay=60)
            page.wait_for_timeout(1200)
            # press Escape to dismiss autocomplete, then click the panel Search button
            box.press("Escape")
            page.wait_for_timeout(400)
            btn = None
            for bsel in ["input[id*='Address'][type='submit']",
                          "input[id*='btnSearchAddress']",
                          "a[id*='Address'][id*='Search']"]:
                btn = page.query_selector(bsel)
                if btn: break
            if btn:
                btn.click(); print("[probe] clicked address Search button", flush=True)
            else:
                box.press("Enter"); print("[probe] pressed Enter", flush=True)
            try: page.wait_for_load_state("networkidle", timeout=15000)
            except Exception: pass
            page.wait_for_timeout(2500)
            # collect KeyValue links on the results page
            kv = []
            for a in page.query_selector_all("a[href*='KeyValue=']"):
                href = a.get_attribute("href") or ""
                m = re.search(r"KeyValue=([^&]+)", href)
                if m: kv.append(m.group(1))
            cap["keyvals"] = kv[:8]
            print(f"[probe] result KeyValues: {cap['keyvals']}", flush=True)
            # follow the first result to the card
            link = page.query_selector("a[href*='PageTypeID=4'], a[href*='KeyValue=']")
            if link:
                link.click()
                try: page.wait_for_load_state("networkidle", timeout=15000)
                except Exception: pass
                page.wait_for_timeout(2500)
            cap["url"] = page.url
            cap["html"] = page.content()
            cap["text"] = page.inner_text("body")
        except Exception as e:
            print(f"[probe] note: {e}", flush=True)
            try:
                cap["url"] = page.url; cap["html"] = page.content(); cap["text"] = page.inner_text("body")
            except Exception: pass
        return page

    try:
        page = StealthyFetcher.fetch(SEARCH_URL, page_action=page_action,
            headless=False, network_idle=True, timeout=90000, solve_cloudflare=True)
    except TypeError:
        page = StealthyFetcher.fetch(SEARCH_URL, headless=False, network_idle=True, timeout=90000)

    html = cap["html"] or getattr(page, "html_content", "") or ""
    text = cap["text"] or ""
    OUT.write_text(html, encoding="utf-8"); TXT.write_text(text, encoding="utf-8")
    print(f"[probe] FINAL url={cap['url']} html_len={len(html)} text_len={len(text)}", flush=True)
    low = text.lower()
    for marker, label in [
        ("sales information","SALES_MODULE"),("no data available","NO_DATA"),
        ("sale price","SALEPRICE"),("sales price","SALESPRICE"),("sale date","SALEDATE"),
        ("deed book","DEEDBOOK"),("living area","LIVINGAREA"),("first floor sq ft","FIRSTFLOOR"),
        ("heated","HEATED"),("year built","YEARBUILT"),
    ]:
        if marker in low: print(f"[marker] {label}", flush=True)
    idx = low.find("sale")
    if idx >= 0: print("[ctx] " + repr(text[max(0,idx-20):idx+350]), flush=True)
    for m in re.finditer(r"\$[\d,]{3,}", text): print(f"[$] {m.group(0)}", flush=True)


if __name__ == "__main__":
    main()
