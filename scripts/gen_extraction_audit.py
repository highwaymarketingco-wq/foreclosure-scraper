"""Generate docs/SOURCE_EXTRACTION_AUDIT.md from the LIVE registry.

Every scraper the code actually loads, tagged with what it already extracts, so
the per-source visual audit (confirm each source is fully scoured for PDFs,
images, external/internal links, and every data field) has a complete worklist
that cannot silently miss a source. Re-run any time: it reads discover(), not a
hand-list, so it is always current.

    uv run python scripts/gen_extraction_audit.py
"""
from __future__ import annotations
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.scrapers._registry import discover  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "SOURCE_EXTRACTION_AUDIT.md"


def module_src(cand) -> tuple[str, str]:
    """Return (source_text, file_path) for a candidate's scraper module.

    Registry candidates ARE the scraper class (type is ABCMeta), so resolve the
    module from the class itself, not type(cand).
    """
    import inspect
    try:
        f = inspect.getsourcefile(cand) or inspect.getfile(cand)
    except Exception:
        f = getattr(sys.modules.get(getattr(cand, "__module__", ""), None), "__file__", None)
    if f and Path(f).exists():
        return Path(f).read_text(errors="ignore"), f
    return "", ""


def probe(src: str) -> dict:
    low = src.lower()
    return {
        "harvester": ("harvest_document_links" in src) or ("stamp_documents" in src),
        "pdf": bool(re.search(r"\.pdf|contract.?package|order.?of.?sale", low)),
        "deed_notice": bool(re.search(r"deed|notice|lis.?pendens|instrument|trustee", low)),
        "image": bool(re.search(r"image|photo|street.?view|thumbnail|/img", low)),
        "detail_fetch": bool(re.search(r"detail|/ad/|/property/|get_text|fetch_detail|_detail", low)),
        "links": bool(re.search(r"href|<a |absolute_url|urljoin", low)),
    }


def main() -> int:
    cands = sorted(discover(), key=lambda c: c.slug)
    rows = []
    for c in cands:
        src, f = module_src(c)
        p = probe(src)
        # pull literal http(s) URLs from the module so the auditor has a page to open
        found = re.findall(r"https?://[^\s\"'`)>]+", src)
        clean = []
        for u in found:
            u = u.rstrip(".,);")
            if "{" in u or "example" in u or u.endswith(("schema.org", "w3.org")):
                continue
            base = re.sub(r"(\?|#).*$", "", u)
            if base not in clean:
                clean.append(base)
        urls = "<br>".join(clean[:2]) if clean else "(see SOURCE_REGISTER.md)"
        rows.append((c.slug, p, urls, f))

    wired = [r for r in rows if r[1]["harvester"]]
    todo = [r for r in rows if not r[1]["harvester"]]

    def line(r):
        slug, p, urls, _ = r
        flags = []
        if p["pdf"]: flags.append("pdf?")
        if p["deed_notice"]: flags.append("deed/notice?")
        if p["image"]: flags.append("img?")
        if p["detail_fetch"]: flags.append("detail-page")
        if p["links"]: flags.append("links")
        hint = ", ".join(flags) or "-"
        return f"| `{slug}` | {hint} | {urls} |"

    L = []
    L.append("# SOURCE EXTRACTION AUDIT — per-source, is EVERYTHING being pulled?")
    L.append("")
    L.append(f"Auto-generated from the live registry by `scripts/gen_extraction_audit.py`. "
             f"**{len(cands)} scrapers**, of which **{len(wired)} already wire the document "
             f"harvester** (PDFs/deeds/notices) and **{len(todo)} do not yet**. Re-run the "
             f"script any time; it reads `discover()`, so it can never miss a source.")
    L.append("")
    L.append("## The audit protocol (do this for EVERY source in the TODO table)")
    L.append("")
    L.append("For each source, open the actual page (its real URL) and confirm, with eyes on the page, "
             "that the scraper captures EVERYTHING of value, not just the row it currently grabs:")
    L.append("")
    L.append("1. **Every data field on the listing/detail page** — address, owner, parcel/TMS, sale date, "
             "opening bid, debt/judgment $, case number, attorney/trustee. If a field is on the page but not "
             "in the Listing, wire it.")
    L.append("2. **PDFs** — Notice of Sale, deed, contract package, order of sale, tax list. If the page links "
             "any, route them through `harvest_document_links()` + `stamp_documents()` so doc-OCR reads them. "
             "This is the single most common miss.")
    L.append("3. **Images** — property photos / assessor card images (for the vision tier). Capture the URL, do "
             "not skip it.")
    L.append("4. **External links** — links off to a county GIS, an auction platform, a law-firm detail page: "
             "follow them if they carry data the row lacks.")
    L.append("5. **Internal links** — a 'details' / 'more info' link on the SAME site that opens a richer page. "
             "Detail pages almost always carry fields the list page omits.")
    L.append("")
    L.append("Then VERIFY the change three ways: it compiles, `discover()` still lists the slug, and a live "
             "`fetch()` returns real Listings with the newly-captured field populated. Never claim a fix you "
             "have not run. Stay in-footprint (18 counties, see `MASTER_GAPS_WALLS_AND_MANUAL_LANES.md`) and "
             "FREE/compliant (no CAPTCHA/login/WAF defeat).")
    L.append("")
    L.append("The `hint` column flags what the CODE mentions (pdf?, img?, detail-page, links) as a starting "
             "clue for where to look. It is a hint from static text, NOT proof the source has or lacks these — "
             "your eyes on the live page are the authority.")
    L.append("")
    L.append(f"## DONE — already harvest documents ({len(wired)})")
    L.append("")
    L.append("| Slug | already captures | URLs |")
    L.append("|---|---|---|")
    L.extend(line(r) for r in wired)
    L.append("")
    L.append(f"## TODO — audit each for full extraction ({len(todo)})")
    L.append("")
    L.append("| Slug | code hints (verify on the live page) | URLs |")
    L.append("|---|---|---|")
    L.extend(line(r) for r in todo)
    L.append("")

    OUT.write_text("\n".join(L))
    print(f"wrote {OUT} — {len(cands)} scrapers ({len(wired)} doc-wired, {len(todo)} to audit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
