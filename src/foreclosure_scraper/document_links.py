"""Document-artifact harvester — capture the deed / notice / instrument PDFs and scan
images that source pages LINK TO but scrapers historically dropped.

Scrapers parse the fields they need and throw away the rest of the page; the richest data
(exact loan amount on the deed-of-trust, lien detail, full legal description, grantor/grantee)
lives inside the linked DOCUMENT, not the listing row. This module extracts those document
URLs from a page's HTML and stamps them onto the Listing in a field `enrich_doc_ocr` scans,
so the (already-built, key-provisioned) OCR pass finally has real inputs.

Usage in a scraper, right where it has the page HTML + is building a Listing:
    from ...document_links import harvest_document_links, stamp_documents
    stamp_documents(li, harvest_document_links(html, base_url=page_url))
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .models import Listing

# a link is a DOCUMENT if it ends in a doc/scan extension OR its path hints at a doc viewer.
_DOC_EXT = re.compile(r"\.(pdf|tiff?|jpe?g|png)(?:[?#]|$)", re.I)
_DOC_HINT = re.compile(
    r"(document|docview|getdocument|viewdocument|viewimage|viewdoc|showdoc|displaydoc|"
    r"instrument|/deed|recorded|recording|/doc/|/docs/|notice|scan|imageview|image\.aspx|"
    r"getpdf|downloaddoc|attachment|/media/|/files/.*\.(pdf|tif))",
    re.I,
)
# obvious non-lead junk PDFs (site chrome) — cheap denylist so we don't feed OCR garbage.
_JUNK = re.compile(
    r"(privacy|terms|disclaimer|sitemap|recycling|holiday|calendar|brochure|newsletter|"
    r"faq|instructions|application-?form|blank|w9|logo|banner|favicon|accessibility|ada-)",
    re.I,
)
# COMPLIANCE: recorded-document IMAGE viewers are handled ONLY by rod/doc_images.py, which
# gates each vendor on live robots.txt + paywall checks. This general harvester must NOT
# capture those URLs or it would bypass that gate. Deny the known vendor image routes.
_ROD_IMAGE_VENDOR = re.compile(
    r"(view_image\.php|generatesingleimageforprint|/processedimages/|shoppingcart|/cart|"
    r"cotthosting|aumentum|kofile|publicsearch\.us|acclaim.*/(image|document)|recordroom)",
    re.I,
)
# rough priority: deed/instrument first (loan $), then notice, then generic.
_PRIORITY = (("deed", 0), ("instrument", 0), ("mortgage", 0), ("trust", 0),
             ("notice", 1), ("document", 2), ("recorded", 2))


def _rank(url: str) -> int:
    u = url.lower()
    for kw, r in _PRIORITY:
        if kw in u:
            return r
    return 3


def harvest_document_links(html: str, base_url: str = "") -> list[str]:
    """Return likely DEED/NOTICE/INSTRUMENT document URLs from a page's HTML, best first.
    Absolute-ized against base_url, de-duped, junk-filtered. Empty list on no HTML / no hits."""
    if not html:
        return []
    out: list[str] = []
    for m in re.finditer(r"""(?:href|src|data-url|data-href)\s*=\s*["']([^"'>\s]+)["']""", html, re.I):
        u = m.group(1).strip()
        if not u or u.startswith(("#", "javascript:", "mailto:", "data:")):
            continue
        if not (_DOC_EXT.search(u) or _DOC_HINT.search(u)):
            continue
        if _JUNK.search(u) or _ROD_IMAGE_VENDOR.search(u):
            continue
        full = urljoin(base_url, u) if base_url else u
        if full.lower().startswith("http"):
            out.append(full)
    # de-dupe (order-stable), then stable-sort by document priority
    seen: set[str] = set()
    uniq = [u for u in out if not (u in seen or seen.add(u))]
    return sorted(uniq, key=_rank)


def stamp_documents(li: Listing, urls: list[str], cap: int = 8) -> int:
    """Persist harvested document URLs onto the Listing so enrich_doc_ocr picks them up.
    Fills raw['documents'] (full list, capped) + raw['document_url'] (primary, if unset).
    Idempotent + additive. Returns how many NEW urls were added."""
    urls = [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")]
    if not urls:
        return 0
    if not isinstance(li.raw, dict):
        li.raw = {}
    have = li.raw.setdefault("documents", [])
    added = 0
    for u in urls:
        if u not in have and len(have) < cap:
            have.append(u)
            added += 1
    # set the primary OCR-scanned scalar if the scraper didn't already set a doc field.
    if not any(li.raw.get(f) for f in ("document_url", "deed_url", "pdf_url", "notice_url",
                                       "instrument_url", "recorded_document_url")):
        li.raw["document_url"] = have[0]
    return added
