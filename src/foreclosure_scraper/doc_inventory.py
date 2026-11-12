"""Which documents and images a board row (or a Listing's raw) holds a URL for, classified.

One classifier shared by the documents_images audit (scripts/audit_checks/documents_images.py),
the processed-documents ledger (doc_ledger.py), the doc OCR enricher (enrichment_doc_ocr.py)
and the inventory script (scripts/doc_image_inventory.py), so "a row with a notice PDF" means
the same thing in the count, the queue and the gate.

Pure functions over plain dicts: a published board row (top-level `source_url`, `raw`, ...) or
`li.raw` plus `li.source_url`. Nothing here fetches.

DOCUMENT categories (what the URL points at, by where scrapers put it):
  notice         a per-lead notice / filing / sale document: raw.document_url, raw.documents[],
                 raw.notice_url and the other enrich_doc_ocr fields, plus the source-specific
                 keys scrapers stash a lead's own notice under (Column e-notice PDFs, the
                 Dorchester BillTrax delinquent notice, Brunswick / coastal / Swain / Haywood
                 notice PDFs, master-in-equity sale PDFs, SC forfeited-land documents).
  list           a roster the row was parsed from (a source_url that is a PDF, a county
                 tax-sale list PDF). Read by the scraper itself; the doc OCR aggregate pass
                 reads it again only to fill a blank street address from the row's own line.
  deed_image     a recorded deed or plat image link a county GIS layer hands out
                 (raw.gis_attrs_full.DEED_URL / PLAT_URL, Courthouse Computer Systems).
  assessor_card  a property record card page (parsed by enrichment_assessor_card: the card's
                 fields land in raw.assessor_card).
  env_search     a state environmental document SEARCH link (NC DEQ Laserfiche
                 Search.aspx?searchcommand=...): a query over a facility's folder, not one
                 document.
IMAGE categories:
  listing_photo  a real listing photo (Realtor / Zillow / LandWatch / auction CDNs).
  assessor_photo the county's own drive-by photo (Spatialest / devnetwedge / PTS Cloud copies
                 under parcel_photos/ / ArcGIS attachments).
  aerial         Esri World Imagery tiles or exports.
  map            the OSM static basemap (never graded by design).
  street         street-level imagery (Mapillary / Street View).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DOC_CATEGORIES = ("notice", "list", "deed_image", "assessor_card", "env_search")
IMAGE_CATEGORIES = ("listing_photo", "assessor_photo", "aerial", "map", "street")
#: image categories the vision pass can grade (a map basemap is skipped by design)
GRADABLE_IMAGE_CATEGORIES = frozenset({"listing_photo", "assessor_photo", "aerial", "street"})

#: the top-level raw fields enrich_doc_ocr has always scanned (kept in its order)
OCR_DOC_FIELDS = (
    "document_url", "doc_url", "notice_url", "notice_image", "doc_image",
    "instrument_image", "instrument_url", "pdf_url", "image_url", "scan_url",
    "recorded_document_url", "deed_url", "source_pdf", "documents",
)

#: source-specific blocks that carry the row's OWN notice document (block, key). A list value
#: is read element by element. Found by the 2026-10-09 inventory pass over the 10/7 board.
NESTED_NOTICE_FIELDS = (
    ("column", "pdfurl"),
    ("brunswick_legal_notices", "notice_pdf"),
    ("nc_coastal_tax_foreclosure", "notice_pdf"),
    ("swain_tax_foreclosures", "notice_url"),
    ("swain_tax_foreclosures", "pdf_url"),
    ("haywood_tax_foreclosures", "pdf_url"),
    ("pickens_mie", "sale_result_pdf"),
    ("anderson_mie", "source_pdf"),
    ("anderson_mie_deficiency", "source_pdf"),
    ("sc_flc", "doc_url"),
    ("sc_tax_delinquent", "source_pdf"),
    ("xome", "documents"),
)
#: blocks whose list entries each carry one of the row's own notices (block, list key, url key)
NESTED_NOTICE_LISTS: tuple = ()
#: the row's own notice, held as a link plain HTTP cannot turn into the document: counted in the
#: inventory (category notice) but not handed to the OCR reader. (block, key, reason)
NESTED_NOTICE_UNREADABLE = (
    # BillTrax's /view/bill/pdfbill?<base64> is an Angular viewer whose PDF comes from a
    # JS-driven redirect (dorchester_billtrax_delinquent_tax module docstring); the bill's
    # owner, amount and years are already on the row from the BillTrax API.
    ("billtrax_dorchester_delinquent_tax", "notice_pdf_view_url", "js_viewer_needs_browser"),
)
#: roster documents a row was parsed from (block, key)
NESTED_LIST_FIELDS = (
    ("florence_delinquent_tax", "pdf_url"),
    ("charleston_delinquent_tax", "list_pdf"),
)
NESTED_DEED_FIELDS = (("gis_attrs_full", "DEED_URL"), ("gis_attrs_full", "PLAT_URL"))
NESTED_CARD_FIELDS = (
    ("assessor_card", "source_url"),
    ("gis_attrs_full", "propcard"),
    ("gis_attrs_full", "PropertyRecordCard"),
    ("bt_appraisal_card", "card_url"),
    ("rutherford_foreclosure", "property_record_cards"),
)
NESTED_ENV_FIELDS = (
    ("state_contamination", "DocsLink"),
    ("state_contamination", "Laserfiche"),
    ("sc_des_brownfield", "url"),
)

_DOC_EXT = re.compile(r"\.(pdf|tiff?)(?:[?#]|$)", re.I)
_ANY_DOC_EXT = (".pdf", ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".gif", ".bmp")

# query parameters that only bust a cache: the same file under ?v=292 and ?v=688 (Charleston's
# tax-sale list) is ONE document, so aggregate detection and the ledger key ignore them.
_CACHE_BUSTERS = frozenset({"v", "t", "ts", "_", "cb", "cachebuster", "nocache", "ver",
                            "version", "rand", "r"})


def _is_url(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://")) and len(v) < 4000


def normalize_url(url: str) -> str:
    """Scheme/host lower-cased, fragment dropped, cache-buster query params dropped, the rest of
    the query kept in its order. Two URLs that differ only by a cache buster are one document."""
    try:
        sp = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in parse_qsl(sp.query, keep_blank_values=True)
         if k.lower() not in _CACHE_BUSTERS]
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), sp.path, urlencode(q), ""))


def doc_key(url: str) -> str:
    """Ledger key of a document URL: a hash of the normalized URL (the URL itself never goes
    into the public ledger: some carry names in their path or query)."""
    return "u:" + hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:20]


def url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def url_ext(url: str) -> str:
    p = urlsplit(url).path.lower() if _is_url(url) else ""
    m = re.search(r"\.([a-z0-9]{2,5})$", p)
    return m.group(1) if m else ""


def _vals(v: Any) -> list[str]:
    if _is_url(v):
        return [v]
    if isinstance(v, list):
        return [u for u in v if _is_url(u)]
    return []


def _nested(raw: dict, block: str, key: str) -> list[str]:
    b = raw.get(block)
    return _vals(b.get(key)) if isinstance(b, dict) else []


def _raw_and_source(row: Any, source_url: Optional[str] = None) -> tuple[dict, str]:
    """(raw dict, source_url) from a board row dict, a Listing, or a bare raw dict."""
    if isinstance(row, dict) and "raw" in row:
        raw = row.get("raw")
        su = row.get("source_url") if source_url is None else source_url
    elif isinstance(row, dict):
        raw, su = row, source_url
    else:
        raw = getattr(row, "raw", None)
        su = getattr(row, "source_url", None) if source_url is None else source_url
    return (raw if isinstance(raw, dict) else {}), (su if isinstance(su, str) else "")


def ocr_doc_urls(row: Any, source_url: Optional[str] = None) -> list[str]:
    """The document URLs the doc OCR pass reads for this row, best first: the classic
    OCR_DOC_FIELDS, then the source-specific notice blocks, then a source_url that is itself a
    document. De-duplicated by normalized URL. (enrich_doc_ocr before 2026-10-09 read only the
    classic fields and only the first URL.)"""
    raw, su = _raw_and_source(row, source_url)
    out: list[str] = []
    for f in OCR_DOC_FIELDS:
        out.extend(_vals(raw.get(f)))
    for block, key in NESTED_NOTICE_FIELDS:
        out.extend(_nested(raw, block, key))
    for block, lst, key in NESTED_NOTICE_LISTS:
        b = raw.get(block)
        if isinstance(b, dict) and isinstance(b.get(lst), list):
            for it in b[lst][:20]:
                if isinstance(it, dict):
                    out.extend(_vals(it.get(key)))
    if _is_url(su) and su.lower().split("?")[0].endswith(_ANY_DOC_EXT):
        out.append(su)
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        n = normalize_url(u)
        if n not in seen:
            seen.add(n)
            uniq.append(u)
    return uniq


def legacy_ocr_doc_urls(row: Any, source_url: Optional[str] = None) -> list[str]:
    """What enrich_doc_ocr._doc_urls returned before 2026-10-09: the classic OCR_DOC_FIELDS and
    a document-like source_url, exact-string de-duplicated, FIRST URL ONLY. Kept to measure the
    backlog the old reader could not see."""
    raw, su = _raw_and_source(row, source_url)
    out: list[str] = []
    for f in OCR_DOC_FIELDS:
        out.extend(_vals(raw.get(f)))
    if _is_url(su) and su.lower().split("?")[0].endswith(_ANY_DOC_EXT):
        out.append(su)
    return out[:1]


def unreadable_notice_reason(row: Any) -> Optional[str]:
    """The reason the row's own notice link cannot be read by plain HTTP, when that is the only
    notice it holds (see NESTED_NOTICE_UNREADABLE); else None."""
    raw, _ = _raw_and_source(row)
    for block, key, why in NESTED_NOTICE_UNREADABLE:
        if _nested(raw, block, key):
            return why
    return None


def document_refs(row: Any, source_url: Optional[str] = None) -> list[tuple[str, str]]:
    """Every (category, url) document reference on the row. A URL is listed once, under the
    first category that claims it (notice before list)."""
    raw, su = _raw_and_source(row, source_url)
    refs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(cat: str, urls: Iterable[str]) -> None:
        for u in urls:
            n = normalize_url(u)
            if n not in seen:
                seen.add(n)
                refs.append((cat, u))

    notice: list[str] = []
    for f in OCR_DOC_FIELDS:
        notice.extend(_vals(raw.get(f)))
    for block, key in NESTED_NOTICE_FIELDS:
        notice.extend(_nested(raw, block, key))
    for block, lst, key in NESTED_NOTICE_LISTS:
        b = raw.get(block)
        if isinstance(b, dict) and isinstance(b.get(lst), list):
            for it in b[lst][:20]:
                if isinstance(it, dict):
                    notice.extend(_vals(it.get(key)))
    for block, key, _why in NESTED_NOTICE_UNREADABLE:
        notice.extend(_nested(raw, block, key))
    add("notice", notice)
    lists: list[str] = []
    if _is_url(su) and _DOC_EXT.search(su):
        lists.append(su)
    for block, key in NESTED_LIST_FIELDS:
        lists.extend(_nested(raw, block, key))
    add("list", lists)
    for block, key in NESTED_DEED_FIELDS:
        add("deed_image", _nested(raw, block, key))
    for block, key in NESTED_CARD_FIELDS:
        add("assessor_card", _nested(raw, block, key))
    for block, key in NESTED_ENV_FIELDS:
        add("env_search", _nested(raw, block, key))
    return refs


_AERIAL_HOSTS = ("arcgisonline.com",)
_MAP_HOSTS = ("staticmap.openstreetmap", "openstreetmap.org", "tile.openstreetmap")
_ASSESSOR_HOSTS = ("devnetwedge.com", "spatialest.com", "ncptscloud.com", "lincolncounty",
                   "services.arcgis.com", "arcgisserver.")
_STREET_HOSTS = ("mapillary", "maps.googleapis.com/maps/api/streetview", "streetview")


def image_category(url: str, slot: str = "real") -> str:
    """Category of one image URL. `slot` is the raw.images key it sat in (real, primary,
    aerial, map, street) or 'zillow'/'other'."""
    u = url.lower()
    if slot == "map" or any(h in u for h in _MAP_HOSTS):
        return "map"
    if slot == "street" or any(h in u for h in _STREET_HOSTS):
        return "street"
    if slot == "aerial" or any(h in u for h in _AERIAL_HOSTS):
        return "aerial"
    if "parcel_photos/" in u or any(h in u for h in _ASSESSOR_HOSTS):
        return "assessor_photo"
    return "listing_photo"


def image_refs(row: Any) -> list[tuple[str, str]]:
    """Every (category, url) image reference on the row, de-duplicated. raw.images.primary and
    raw.zillow.photo are aliases of an image already listed elsewhere, so they only add a URL
    nothing else carries."""
    raw, _ = _raw_and_source(row)
    refs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(urls: Iterable[str], slot: str) -> None:
        for u in urls:
            if not isinstance(u, str) or not u:
                continue
            if u not in seen:
                seen.add(u)
                refs.append((image_category(u, slot), u))

    imgs = raw.get("images")
    if isinstance(imgs, dict):
        real = imgs.get("real")
        add(real if isinstance(real, list) else ([real] if isinstance(real, str) else []), "real")
        for slot in ("street", "aerial", "map"):
            v = imgs.get(slot)
            add([v] if isinstance(v, str) else (v if isinstance(v, list) else []), slot)
        v = imgs.get("primary")
        add([v] if isinstance(v, str) else [], "real")
    z = raw.get("zillow")
    if isinstance(z, dict):
        add([u for u in (z.get("photos") or []) if isinstance(u, str)], "real")
        if isinstance(z.get("photo"), str):
            add([z["photo"]], "real")
    b = raw.get("bid4assets")
    if isinstance(b, dict) and isinstance(b.get("image_url"), str):
        add([b["image_url"]], "real")
    return refs


def image_set_key(urls: Iterable[str]) -> str:
    """Ledger key of the image set a vision call grades: a hash of the sorted URLs."""
    s = "\n".join(sorted({u for u in urls if isinstance(u, str) and u}))
    return "i:" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:20]


def owner_search_key(state: str, county: str, owner: str) -> str:
    """Ledger key of one owner's recorded-deed-of-trust search (dot_ocr resolves the images at
    run time; no URL is held). Hash only: the public ledger never carries the name."""
    o = re.sub(r"\s+", " ", (owner or "").strip().upper())
    s = f"{(state or '').strip().upper()}|{(county or '').strip().lower()}|{o}"
    return "o:" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:20]


_TIER_RANK = {"HOT": 0, "WARM": 1}


def lead_value_key(row: Any) -> tuple:
    """Sort key, lower first: HOT, then WARM, then the rest; inside a tier the higher stacked
    distress score, then the higher intent score, then a sale date sooner. Works on a board row
    dict or a Listing."""
    raw, _ = _raw_and_source(row)
    ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
    tier = _TIER_RANK.get(str(ds.get("tier") or "").upper(), 2)
    try:
        score = -float(ds.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        intent = -float(raw.get("intent_score") or 0)
    except (TypeError, ValueError):
        intent = 0.0
    sd = row.get("sale_date") if isinstance(row, dict) else getattr(row, "sale_date", None)
    sds = str(sd)[:10] if sd else "9999-12-31"
    return (tier, score, intent, sds)
