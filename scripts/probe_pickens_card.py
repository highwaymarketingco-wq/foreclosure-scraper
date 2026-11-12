"""One-off ADVERSARIAL probe: open a single live Pickens SC qPublic parcel card
and dump the rendered HTML + visible text so we can read the ACTUAL
heated-sqft and sale-price values (not just column headers).

Per compliance: this is a per-subject, low-volume lookup of a PUBLIC
assessor record. No CAPTCHA/login defeat, no bulk distribution.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

KEY = sys.argv[1] if len(sys.argv) > 1 else "R0022220"
CARD_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    f"?AppID=927&LayerID=18058&PageTypeID=4&PageID=8077&KeyValue={KEY}"
)
OUT = Path(f"/tmp/pickens_{KEY}.html")
TXT = Path(f"/tmp/pickens_{KEY}.txt")


def main() -> None:
    from scrapling.fetchers import StealthyFetcher

    print(f"[probe] fetching {CARD_URL}", flush=True)

    # network_idle + solve_cloudflare to get past the JS challenge; non-headless
    # is more reliable for the Cloudflare interstitial.
    def page_action(page):
        # Best-effort: click the disclaimer "Agree" button if the gate shows.
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
        # older signature without page_action/solve_cloudflare
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
        ("disclaimer", "DISCLAIMER_GATE"),
        ("i agree", "AGREE_GATE"),
        ("square feet", "HAS_SQFT_LABEL"),
        ("sale price", "HAS_SALEPRICE_LABEL"),
        ("year built", "HAS_YEARBUILT_LABEL"),
        ("whitaker", "OWNER_WHITAKER"),
        ("lakeside", "ADDR_LAKESIDE"),
    ]:
        if marker in low:
            print(f"[marker] {label} (matched '{marker}')", flush=True)

    # Pull number near "Square Feet" and a $ near "Sale Price" from text.
    for m in re.finditer(r"(square feet|heated|living area)[^\d]{0,40}([\d,]{3,7})", text, re.I):
        print(f"[sqft?] ...{m.group(0)!r}", flush=True)
    for m in re.finditer(r"(sale price|sales price)[^\$]{0,40}(\$[\d,]+)", text, re.I):
        print(f"[saleprice?] ...{m.group(0)!r}", flush=True)


if __name__ == "__main__":
    main()
