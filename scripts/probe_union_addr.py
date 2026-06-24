"""ADVERSARIAL probe: public address search on Union County SC qPublic, follow
the first result to its report card, and read actual Sale Price + sqft.

Per compliance: per-subject, low-volume lookup of a PUBLIC assessor record.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ADDR = sys.argv[1] if len(sys.argv) > 1 else "209 PARK"
SEARCH_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=861&LayerID=16112&PageTypeID=2&PageID=7168"
)
safe = ADDR.replace(" ", "_")
OUT = Path(f"/tmp/union_addr_{safe}.html")
TXT = Path(f"/tmp/union_addr_{safe}.txt")


def main() -> None:
    from scrapling.fetchers import StealthyFetcher

    print(f"[probe] searching address {ADDR!r}", flush=True)

    captured = {"card_html": "", "card_text": "", "card_url": ""}

    def page_action(page):
        try:
            page.wait_for_timeout(3000)
            # disclaimer
            for sel in ["a:has-text('Agree')", "input[value='Agree']", "button:has-text('Agree')"]:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click()
                        print(f"[probe] disclaimer agreed via {sel}", flush=True)
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue
            # type address into the LOCATION ADDRESS search box, then click the
            # Search button that is the sibling of that specific field.
            addr_box = None
            for sel in [
                "input[id*='txtSearchAddress']",
                "input[id*='Address'][type='text']",
                "input[id*='txtAddress']",
                "input[placeholder*='address']",
            ]:
                try:
                    box = page.query_selector(sel)
                    if box:
                        box.click()
                        box.fill("")
                        box.type(ADDR, delay=80)
                        addr_box = box
                        print(f"[probe] typed address into {sel}", flush=True)
                        break
                except Exception:
                    continue
            page.wait_for_timeout(2500)
            # Accept autocomplete first option if a dropdown is showing, else
            # just press Enter to submit the location-address search.
            try:
                opt = page.query_selector("ul.ui-autocomplete li a, .ui-menu-item a")
                if opt:
                    opt.click()
                    print("[probe] selected autocomplete option", flush=True)
                    page.wait_for_timeout(1500)
            except Exception:
                pass
            # Click the Search button inside the same address panel.
            clicked = False
            for sel in [
                "input[id*='btnSearchAddress']",
                "button[id*='SearchAddress']",
                "input[id*='Address'][type='submit']",
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn:
                        btn.click()
                        print(f"[probe] clicked address Search via {sel}", flush=True)
                        clicked = True
                        page.wait_for_timeout(6000)
                        break
                except Exception:
                    continue
            if not clicked and addr_box:
                try:
                    addr_box.press("Enter")
                    print("[probe] pressed Enter to submit address search", flush=True)
                    page.wait_for_timeout(6000)
                except Exception:
                    pass
            # follow first parcel result link
            link = None
            for sel in ["a[href*='PageTypeID=4']", "a[href*='KeyValue=']"]:
                try:
                    link = page.query_selector(sel)
                    if link:
                        href = link.get_attribute("href")
                        print(f"[probe] result link: {href}", flush=True)
                        link.click()
                        page.wait_for_timeout(5000)
                        break
                except Exception:
                    continue
            captured["card_url"] = page.url
            captured["card_html"] = page.content()
            captured["card_text"] = page.inner_text("body")
        except Exception as e:
            print(f"[probe] page_action note: {e}", flush=True)
        return page

    kwargs = dict(headless=False, network_idle=True, timeout=90000, solve_cloudflare=True)
    try:
        page = StealthyFetcher.fetch(SEARCH_URL, page_action=page_action, **kwargs)
    except TypeError:
        page = StealthyFetcher.fetch(SEARCH_URL, headless=False, network_idle=True, timeout=90000)

    html = captured["card_html"] or getattr(page, "html_content", "") or ""
    text = captured["card_text"]
    if not text:
        try:
            text = page.get_all_text(ignore_tags=("script", "style"))
        except Exception:
            text = ""
    OUT.write_text(html, encoding="utf-8")
    TXT.write_text(text, encoding="utf-8")
    print(f"[probe] final_url={captured['card_url']}", flush=True)
    print(f"[probe] html_len={len(html)} text_len={len(text)} wrote {OUT} {TXT}", flush=True)

    low = text.lower()
    for marker, label in [
        ("sales information", "SALES_MODULE"),
        ("no data available", "NO_DATA_NOTE"),
        ("sale price", "SALEPRICE_LABEL"),
        ("sale date", "SALEDATE_LABEL"),
        ("deed book", "DEEDBOOK_LABEL"),
        ("heated", "HEATED_LABEL"),
        ("living area", "LIVINGAREA_LABEL"),
    ]:
        if marker in low:
            print(f"[marker] {label}", flush=True)
    for m in re.finditer(r"\$[\d,]{4,}", text):
        print(f"[$] {m.group(0)}", flush=True)


if __name__ == "__main__":
    main()
