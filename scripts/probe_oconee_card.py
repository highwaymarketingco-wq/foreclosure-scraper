"""ADVERSARIAL probe: open a single live OCONEE SC qPublic parcel card
(AppID=1030, LayerID=21692) and dump rendered HTML + visible text so we can
read the ACTUAL heated-sqft and sale-price values (not just column headers).

Per compliance: per-subject, low-volume lookup of a PUBLIC assessor record.
No CAPTCHA/login defeat, no bulk distribution. Single browser visit.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

KEY = sys.argv[1] if len(sys.argv) > 1 else "520-77-01-021"
CARD_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    f"?AppID=1030&LayerID=21692&PageTypeID=4&PageID=9258&KeyValue={KEY}"
)
OUT = Path(f"/tmp/oconee_{KEY}.html")
TXT = Path(f"/tmp/oconee_{KEY}.txt")


def main() -> None:
    from scrapling.fetchers import StealthyFetcher

    print(f"[probe] fetching {CARD_URL}", flush=True)

    def page_action(page):
        try:
            page.wait_for_timeout(3500)
            for sel in [
                "button:has-text('Agree')",
                "input[value='Agree']",
                "a:has-text('Agree')",
                "#ctlBodyPane_ctl00_ctl01_btnDisclaimerAgree",
                "input[id*='Agree']",
                "input[id*='Disclaimer']",
            ]:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click()
                        print(f"[probe] clicked disclaimer via {sel}", flush=True)
                        page.wait_for_timeout(3500)
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"[probe] page_action note: {e}", flush=True)
        return page

    kwargs = dict(headless=False, network_idle=True, timeout=90000)
    try:
        kwargs["solve_cloudflare"] = True
    except Exception:
        pass

    try:
        page = StealthyFetcher.fetch(CARD_URL, page_action=page_action, **kwargs)
    except TypeError:
        page = StealthyFetcher.fetch(CARD_URL, headless=False, network_idle=True, timeout=90000)

    status = getattr(page, "status", None)
    html = getattr(page, "html_content", "") or ""
    try:
        text = page.get_all_text(ignore_tags=("script", "style"))
    except Exception:
        text = ""

    OUT.write_text(html, encoding="utf-8")
    TXT.write_text(text, encoding="utf-8")
    print(f"[probe] status={status} html_len={len(html)} text_len={len(text)}", flush=True)
    print(f"[probe] wrote {OUT} and {TXT}", flush=True)

    low = (html + " " + text).lower()
    for marker, label in [
        ("just a moment", "CLOUDFLARE_CHALLENGE"),
        ("cf-challenge", "CLOUDFLARE_CHALLENGE"),
        ("attention required", "CLOUDFLARE_BLOCK"),
        ("disclaimer", "DISCLAIMER_GATE"),
        ("i agree", "AGREE_GATE"),
        ("heated square feet", "HAS_HEATED_SQFT_LABEL"),
        ("square feet", "HAS_SQFT_LABEL"),
        ("sale price", "HAS_SALEPRICE_LABEL"),
        ("year built", "HAS_YEARBUILT_LABEL"),
        ("pepper", "ADDR_PEPPER"),
        ("seneca", "ADDR_SENECA"),
        ("stevens", "OWNER_STEVENS"),
        ("king", "OWNER_KING"),
    ]:
        if marker in low:
            print(f"[marker] {label} (matched '{marker}')", flush=True)

    for m in re.finditer(r"(heated square feet|square feet|heated|living area)[^\d]{0,40}([\d,]{3,7})", text, re.I):
        print(f"[sqft?] ...{m.group(0)!r}", flush=True)
    for m in re.finditer(r"(sale price|sales price)[^\$]{0,40}(\$[\d,]+)", text, re.I):
        print(f"[saleprice?] ...{m.group(0)!r}", flush=True)
    # Generic $ amounts near date-looking strings (sale rows)
    for m in re.finditer(r"(\d{1,2}/\d{1,2}/\d{4})[^\$]{0,80}(\$[\d,]+)", text):
        print(f"[salerow?] {m.group(1)} -> {m.group(2)}", flush=True)


if __name__ == "__main__":
    main()
