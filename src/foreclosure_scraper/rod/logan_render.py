"""Render-based name search for the AJAX/DataTables Logan ROD sites (Spartanburg SC).

Spartanburg's Logan "The Lookup" renders everything via jQuery DataTables AJAX, so the httpx path
gets empty tables (unlike the older server-rendered Logan counties). This drives the flow with a
headless browser — compliant: free, guest session, no login/CAPTCHA defeated, just the JS the page
itself runs. Flow (live-verified 2026-06-30): GET /index.php -> click Accept -> setSearch('name')
-> fill last/first -> Search (F2) -> pick-list (DataTables, results iframe) -> checkAllPickList() +
submitPickList() -> records iframe (600 summary cells / 100 rows for SMITH JOHN). Records are parsed
by the existing logan._parse_records. SLOW (~20-40s/owner) so it's for GATED high-value lookups only.
"""
from __future__ import annotations

import re

from .models import RodDoc
from . import logan as _logan

LOGAN_RENDER_COUNTIES = {
    ("SC", "Spartanburg"): "https://search.spartanburgdeeds.com",
}

_SUMMARY_RE = re.compile(r'class="summary"', re.I)


async def _records_frame_html(pg):
    """Return the HTML of whichever frame now holds the records grid (summary cells)."""
    for fr in pg.frames:
        try:
            html = await fr.content()
        except Exception:
            continue
        if len(_SUMMARY_RE.findall(html)) >= 3:
            return html
    return ""


async def search_by_name_render(state: str, county: str, name: str,
                                start_date: str = "01/01/2010", timeout_ms: int = 75000) -> list[RodDoc]:
    base = LOGAN_RENDER_COUNTIES.get((state, county))
    if not base or not name:
        return []
    last, first = name, ""
    if "," in name:
        a, b = name.split(",", 1)
        last, first = a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    elif " " in name:
        parts = name.split()
        last, first = parts[0], parts[1]
    try:
        from playwright.async_api import async_playwright
    except Exception:  # pragma: no cover
        return []

    html = ""
    try:
        async with async_playwright() as p:
            br = await p.chromium.launch(headless=True)
            ctx = await br.new_context(ignore_https_errors=True)
            pg = await ctx.new_page()
            pg.set_default_timeout(timeout_ms)
            await pg.goto(base + "/index.php", wait_until="domcontentloaded", timeout=30000)
            await pg.wait_for_timeout(1500)
            el = await pg.query_selector("input[name=Accept]")
            if el:
                await el.click()
            await pg.wait_for_timeout(2500)
            # find the form frame
            tgt = None
            for fr in pg.frames:
                try:
                    if await fr.query_selector("input[name=last_name]"):
                        tgt = fr
                        break
                except Exception:
                    pass
            if tgt is None:
                await br.close()
                return []
            try:
                await tgt.eval_on_selector("a[onclick*=\"setSearch('name')\"]", "e=>e.click()")
            except Exception:
                pass
            await pg.wait_for_timeout(500)
            await tgt.fill("input[name=last_name]", last)
            if first:
                try:
                    await tgt.fill("input[name=first_name]", first)
                except Exception:
                    pass
            await tgt.eval_on_selector_all(
                "a", "els=>{const e=els.find(x=>/Search \\(F2\\)/.test(x.innerText));if(e)e.click();}")
            await pg.wait_for_timeout(9000)
            # results / pick-list frame
            rf = None
            for fr in pg.frames:
                try:
                    n = await fr.evaluate("()=>{const pl=document.querySelector('#plresults');return pl?pl.querySelectorAll('tbody tr').length:0;}")
                    if n and n > 0:
                        rf = fr
                        break
                except Exception:
                    pass
            if rf is not None:
                await rf.evaluate("()=>{try{if(window.checkAllPickList)checkAllPickList();}catch(e){}}")
                await pg.wait_for_timeout(1000)
                await rf.evaluate("()=>{try{if(window.submitPickList)submitPickList();}catch(e){}}")
            # poll for the records frame
            for _ in range(10):
                await pg.wait_for_timeout(3000)
                html = await _records_frame_html(pg)
                if html:
                    break
            await br.close()
    except Exception:
        return []
    if not html:
        return []
    return _logan._parse_records(html, state, county)
