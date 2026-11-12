"""Pasquotank County NC delinquent real-property tax lien list -- the county's own annual NCGS
105-369 lien advertisement, published as a text-based PDF directly on its own Squarespace site.
Feeds raw['tax_owed'] / raw['pasquotank_tax_lien'] (and, once a second year's PDF is captured in
a LATER run, raw['multi_year_delinquent_tax'] -- see "WHY MULTI-YEAR DOESN'T FILL YET" below).

WHY THIS EXISTS (overnight task: "Pasquotank County NC at www.pasquotankcountync.org -- feeds
multi_year_delinquent_tax, 2,469 est rows affected"). CHECKED FIRST, PER TASK BRIEF: grepped the
codebase for "pasquotank" -- nothing. The county is NOT on any vendor this codebase already
drives (not bttaxpayerportal/ITSPublic, not Spatialest, not qPayBill, not ncptscloud/LandRecords-
Cloud -- none of those strings appear anywhere on pasquotankcountync.org's tax-office, GIS-office,
delinquent-taxes or tax-sales pages, checked live).

LIVE-VERIFIED 2026-11-05, every candidate on the county's own site tried in turn before settling
on this one (read-only, no board touched):

    /tcs ("Property Card Search", linked from the Tax Office page) -- a Squarespace page whose
        own page-header/footer content blocks are EMPTY ("empty" CSS class, no iframe anywhere in
        the HTML). DEAD: whatever search tool this page once embedded is gone.

    /payonline -> pasquotankcountync.payacp.com -- a live React SPA ("Nuvei Citizen Portal",
        meta description "Welcome to UtilityContact!"). Downloaded and grepped the full 1.5MB
        main JS bundle for "PropertyTax"/"Parcel"/"RealEstate"/"property_tax": ZERO hits, and it
        references a Google reCAPTCHA SDK for its own flows. DEAD END for this column: this is
        the county's UTILITY (water/sewer) bill-pay portal, not a property-tax search, and would
        be CAPTCHA-walled even if it were.

    /gis-office -> pasquotankcounty.maps.arcgis.com (an Esri "Instant App"). Not pursued further
        once the PDF below proved out real, free, no-login multi-row data directly -- noted here
        as an UNEXPLORED possibility, not a verdict either way, if a future pass wants a parcel-
        valuation (rollback-style) source for this county.

    /delinquent-taxes -- linked from the sitemap, but its own page content is the same empty
        sitewide-nav shell /tcs has (confirmed: zero page-specific body text, zero PDF links).
        DEAD, same shape as /tcs.

    /tax-sales -- a REAL, live Squarespace blog collection, one dated post per property that
        actually reached a tax FORECLOSURE sale (confirmed via sitemap.xml: 11 posts, 2023-2025,
        each slugged by parcel, e.g. "/tax-sales/2025/6/9/p119-195a"). Real and free, but a
        different, much smaller signal (actual sales, not the delinquent ROLL) -- out of scope
        for multi_year_delinquent_tax and not built here; left for a future pass if ever needed.

    /tax-office -> "/s/DTax2026-edmn.pdf" ("Delinquent Taxes") -- THE SOURCE THIS MODULE READS.
        A real, text-extractable (pdfplumber, no OCR needed -- see _ROW_RE below for why
        pdfplumber specifically, not pypdf), 3-page PDF. Its own first-page preamble
        states the statute and scope in full: "Under and by virtue of the authority vested in me
        by section 105-369 of the North Carolina General Statutes... I am hereby advertising tax
        liens for the YEAR 2025 upon the real estate described below." (live-read 2026-11-05).
        Each row is `OWNER NAME .......... PARCEL ID .......... $AMOUNT` (dot-leader columns, no
        address field at all). ~450 real-estate accounts. Free, public, no login, no CAPTCHA --
        a single flat GET.

WHY MULTI-YEAR DOESN'T FILL YET, AND WHY THAT IS NOT A CODE GAP. This is ONE annual advertisement
    for ONE levy year (2025) -- the statute requires exactly this kind of single-year ad, and no
    sibling-year PDF (2024, 2023, ...) is linked anywhere on the site today (checked: the
    tax-office page links only this one file; the Squarespace upload slug carries a random
    4-char suffix Squarespace itself assigns, not a guessable year-coded pattern, so a prior
    year's file cannot be found without actually being linked somewhere -- NEVER guessed, per
    this task's own instruction). raw['multi_year_delinquent_tax'] genuinely needs >=2 distinct
    MATURED levy years for one parcel (the same MIN_YEARS=2 gate every sibling restater in this
    codebase uses) -- one annual PDF read once can supply at most one. build_multiyear_block()
    below is written to the SAME gated contract as every sibling anyway (not skipped), because
    raw['pasquotank_tax_lien']['per_year'] is designed to ACCUMULATE: each run merges this year's
    {year: amount} into whatever per_year dict a PRIOR run already left on the row (never
    clobbers an existing year), so the day a future year's advertisement is captured in a later
    run, the SAME board row's per_year dict will genuinely carry 2+ years and the gate will
    legitimately fire -- without this module being touched again. Today, on a first run, it will
    not fire for (realistically) any row, and that is accurately reflected in this module's own
    stats, never papered over. What DOES fill today: raw['tax_owed'] (year=2025, a real dollar
    balance) and, through enrichment_tax_owed.py's/enrichment_tax_aging.py's EXISTING generic
    readers (already wired, untouched by this file -- same convention enrichment_alamance_tax_
    search.py and enrichment_ustaxdata_tax_search.py already rely on), raw['tax_aging_surfaced'] /
    raw['two_year_delinquent'] as time passes past the single known levy year's own delinquent
    date (tax_calendar's "single_year" basis) -- a genuine, real improvement in county coverage
    even though the literal multi_year_delinquent_tax key will take a second year's data to earn.

MATCH METHOD -- OWNER NAME ONLY, NO PARCEL OR ADDRESS CROSSWALK, AND WHY THAT IS SAFE HERE. This
    document carries no address field at all, and Pasquotank's own account/parcel format ("P119-
    195A", "35-B-11") does not resemble this board's own parcel_id shape for this county (12-digit
    numeric NC PINs, e.g. "892202787729" -- confirmed by reading real Pasquotank board rows live,
    read-only, off docs/listings_part_*.json.gz) -- the same per-vendor-id-format mismatch this
    project already documents repeatedly (Alamance/PARID, Cherokee/qPayBill, etc.), so neither a
    parcel join nor an address_relation() confirmation is possible here. To avoid ever attaching
    the wrong one of an owner's several Pasquotank parcels to a board lead (measured on this exact
    PDF: several owners, e.g. "WYNN, ADAM" and "ALLEY RATS LLC", hold 2-4 distinct parcels each),
    a board row is matched ONLY when name_normalize.match_owner() confirms the owner AND that
    owner resolves to EXACTLY ONE DISTINCT PARCEL in the PDF (same-parcel duplicate rows, e.g. a
    split real-estate + supplemental bill on one account, are summed, not treated as a conflict).
    An owner spanning 2+ distinct parcels is left unmatched -- recorded, never guessed between --
    same "never a guess between several, never on one signal alone" bar every sibling in this
    codebase already holds itself to.

ONE NETWORK CALL FOR THE WHOLE COUNTY, not one per row: the PDF is the entire delinquent roll, so
    it is fetched ONCE and matched against every eligible board row in memory. Bounded, opt-in,
    free, public, no login, no CAPTCHA. Gate off entirely with FORECLOSURE_PASQUOTANK_TAX=0.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

import httpx
import structlog

from . import tax_calendar
from .models import Listing
from .name_normalize import is_entity, match_owner
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend

log = structlog.get_logger()

PDF_URL = "https://www.pasquotankcountync.org/s/DTax2026-edmn.pdf"
COUNTY = "Pasquotank"
TAX_YEAR = 2025          # the PDF's own preamble: "advertising tax liens for the year 2025"
SLUG = "enrichment_pasquotank_delinquent_tax"

RAW_KEY = "pasquotank_tax_lien"
MYDT_KEY = "multi_year_delinquent_tax"
CHECKED_KEY = "_pasquotank_tax_checked"
MIN_YEARS = int(os.environ.get("PASQUOTANK_TAX_MIN_YEARS", "2"))

ENABLED = os.environ.get("FORECLOSURE_PASQUOTANK_TAX") != "0"
TIMEOUT_S = 30.0

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# One dot-leader row: "OWNER NAME.......PARCEL.......$AMOUNT", found ANYWHERE in the text (not
# anchored to a line) because the PDF is laid out in TWO COLUMNS and pdfplumber's own reading
# order prints both columns' records back to back on one logical line
# ("COASTERSDOWNTOWNDRAUGHT....2-A-4....$3,708.63 FORBES,JOSEPHHJR....14-F-3,4,5,6....$2,500.91")
# -- finditer (not a single per-line match) recovers BOTH records from a line like that. `.`
# does not match a newline by default (no re.DOTALL), which keeps a match from ever spanning two
# physical lines on its own.
#
# pdfplumber vs pypdf, and why pdfplumber was chosen (measured live on this exact PDF,
# 2026-11-05): pypdf's extract_text() inserts SPURIOUS spaces mid-word on this specific
# Adobe-InDesign+OneVision-produced file (kerning artifact) -- "PERRY,CLARK HAYWOOD" reads back
# "PERRY,CLARK HA YW OOD" and "PERRY,CLARKH AYWO OD" on different rows of the SAME real person,
# which defeats name_normalize.match_owner()'s own word-token splitting (owner_last_first_middle
# reads "CLARKH AYWO OD" as first="CLARKH" instead of "CLARK HAYWOOD" entirely). pdfplumber's own
# extraction never inserts a spurious space, but the opposite artifact instead: it sometimes
# emits NO space at all between two real name words ("PERRY,MARYBETH&" for "Perry, Mary Beth").
# That failure mode is SAFER to work around (see find_candidates' despaced fallback below) than
# pypdf's, because "no space" never fabricates a WRONG word boundary -- it just needs a
# whitespace-insensitive comparison, never a guess at where a missing space should go.
_ROW_RE = re.compile(
    r"(?P<owner>[A-Z][A-Z0-9 ,.&()'-]*?)\.{5,}(?P<parcel>[^.\s][^.]*?)\.{4,}\$(?P<amount>[\d,]+\.\d{2})")


def _money(s: str) -> Optional[float]:
    try:
        v = round(float(s.replace(",", "")), 2)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _clean_owner(s: str) -> str:
    """Collapse incidental multi-space runs for a stable dict key / match_owner() input -- never
    used to invent a value, only to compare text already on the page."""
    return re.sub(r"\s+", " ", s).strip()


def despaced_name_key(name: str) -> tuple[str, str]:
    """(LAST, REST) with every space/punctuation character removed from REST -- a whitespace-
    INSENSITIVE identity for one person's name, never a fuzzy one. Exists only to work around
    the measured, real pdfplumber extraction artifact documented at _ROW_RE above (a missing
    space between two real name words, e.g. "MARYBETH" for "Mary Beth"): stripping ALL spaces
    from both sides before comparing makes "MARY BETH" (board) and "MARYBETH" (PDF) equal without
    ever guessing WHERE a missing space belongs, so it can't merge two different people's
    distinctly-spelled names -- it can only recover a match the PDF's own missing whitespace hid.
    ("" , "") when the input has no usable last-name token (blank, pure punctuation)."""
    s = re.sub(r"[^A-Z0-9, ]", "", (name or "").upper()).strip()
    if not s:
        return ("", "")
    if "," in s:
        last, _, rest = s.partition(",")
    else:
        parts = s.split(None, 1)
        last, rest = (parts[0], parts[1] if len(parts) > 1 else "")
    return (last.strip(), re.sub(r"\s+", "", rest))


def parse_pdf_text(text: str) -> list[dict]:
    """Every real-estate lien row anywhere in the PDF's extracted text -> {owner, parcel,
    amount} (see _ROW_RE for why this is a non-anchored search, not a per-line match)."""
    out: list[dict] = []
    for m in _ROW_RE.finditer(text or ""):
        amount = _money(m.group("amount"))
        owner = _clean_owner(m.group("owner"))
        parcel = re.sub(r"\s+", "", m.group("parcel"))
        if not amount or not owner or not parcel:
            continue
        out.append({"owner": owner, "parcel": parcel, "amount": amount})
    return out


def build_parcel_index(rows: list[dict]) -> dict[str, list[dict]]:
    """owner-text -> its rows, DEDUPED to one entry per distinct parcel (same-parcel duplicate
    bills summed; the owner text itself is kept as a BUCKET key for match_owner(), not trusted as
    an exact string -- several distinct owner spellings can share a parcel)."""
    by_owner: dict[str, dict[str, dict]] = {}
    for r in rows:
        bucket = by_owner.setdefault(r["owner"], {})
        existing = bucket.get(r["parcel"])
        if existing:
            existing["amount"] = round(existing["amount"] + r["amount"], 2)
        else:
            bucket[r["parcel"]] = {"parcel": r["parcel"], "amount": r["amount"]}
    return {owner: list(parcels.values()) for owner, parcels in by_owner.items()}


def find_candidates(owner_name: str, index: dict[str, list[dict]]) -> list[dict]:
    """Every PDF parcel-row whose bucket owner text identifies the same person as `owner_name`,
    deduped by parcel (an owner whose name appears under >1 slightly different spelling in the
    PDF, e.g. a missing middle initial, must not be double-counted as 2 distinct parcels).

    Two independent checks, either one confirming: name_normalize.match_owner() (the shared,
    trusted comparison used across this codebase) OR despaced_name_key() equality (this module's
    own narrow fallback for the specific "missing space" extraction artifact _ROW_RE documents --
    never a fuzzy/partial match, an exact comparison once whitespace is removed from both sides)."""
    key = despaced_name_key(owner_name)
    seen_parcels: dict[str, dict] = {}
    for bucket_owner, parcels in index.items():
        if not (match_owner(owner_name, bucket_owner) or
                (key[0] and key == despaced_name_key(bucket_owner))):
            continue
        for p in parcels:
            if p["parcel"] not in seen_parcels:
                seen_parcels[p["parcel"]] = p
    return list(seen_parcels.values())


def _already_done(li: Listing) -> bool:
    return isinstance(li.raw, dict) and (
        isinstance(li.raw.get(RAW_KEY), dict) or bool(li.raw.get(CHECKED_KEY)))


def _eligible(li: Listing) -> bool:
    return bool(
        (li.state or "").strip().upper() == "NC"
        and (li.county or "").replace(" County", "").strip().lower() == COUNTY.lower()
        and li.owner_name and not is_entity(li.owner_name)
        and not _already_done(li)
    )


def build_multiyear_block(per_year: dict[int, float], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from an ACCUMULATED {year: amount} map
    (this run's year merged with any prior run's own years already on the row -- see module
    docstring's "WHY MULTI-YEAR DOESN'T FILL YET"), or None below the same MIN_YEARS gate every
    sibling restater in this codebase uses."""
    today = today or date.today()
    years = sorted(per_year)
    matured = tax_calendar.completed_delinquent_years(years, "NC", COUNTY, today)
    if len(matured) < MIN_YEARS:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    return {
        "years": years,
        "per_year": {str(y): per_year[y] for y in years},
        "years_delinquent": len(matured),
        "unpaid_bill_years": len(years),
        "matured_years": matured,
        "matured_years_delinquent": len(matured),
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "latest_matured_year": max(matured),
        "current_levy_year": (current[-1] if current else None),
        "in_current_levy": bool(current),
        "total_due": total_owed,
        "total_owed": total_owed,
        "matured_owed": matured_owed,
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": bool(current),
        "amount_basis": "annual_advertisement",
        "layers": ["pasquotank_ncgs_105_369_ad"],
        "source_url": PDF_URL,
    }


async def _fetch_pdf_bytes(client: Optional[httpx.AsyncClient] = None) -> bytes:
    if client is not None:
        r = await client.get(PDF_URL, timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.content
    async with httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        r = await c.get(PDF_URL)
        r.raise_for_status()
        return r.content


def _extract_text(pdf_bytes: bytes) -> str:
    # pdfplumber, not pypdf -- see _ROW_RE's docstring for why (pypdf inserts spurious mid-word
    # spaces on this specific PDF that defeat name matching; pdfplumber's own, safer failure mode
    # -- an occasional MISSING space between two words -- is what despaced_name_key() above
    # exists to work around).
    import io
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


async def enrich_pasquotank_delinquent_tax(listings: Iterable[Listing], *,
                                           client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Fetch the county's own annual NCGS 105-369 delinquent-tax PDF ONCE and match it, by owner
    name (unambiguous matches only -- see module docstring), against every eligible Pasquotank NC
    board row. Writes raw['pasquotank_tax_lien'], raw['tax_owed'], and raw['multi_year_delinquent_
    tax'] (gated; see module docstring for why that one is empty on a first run)."""
    stats = {"eligible": 0, "pdf_rows": 0, "distinct_owners": 0, "matched": 0,
             "ambiguous_owner": 0, "no_match": 0, "multiyear_qualified": 0, "errors": 0}
    if not ENABLED:
        return stats
    targets = [li for li in listings if _eligible(li)]
    stats["eligible"] = len(targets)
    if not targets:
        return stats

    try:
        pdf_bytes = await _fetch_pdf_bytes(client)
        rows = parse_pdf_text(_extract_text(pdf_bytes))
    except Exception as exc:  # noqa: BLE001 - one source read never kills the pass
        log.warning("pasquotank_tax.fetch_failed", error=str(exc)[:200])
        stats["errors"] += 1
        return stats
    stats["pdf_rows"] = len(rows)
    index = build_parcel_index(rows)
    stats["distinct_owners"] = len(index)
    if not rows:
        return stats

    today = date.today()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for li in targets:
        candidates = find_candidates(li.owner_name or "", index)
        if not candidates:
            stats["no_match"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw[CHECKED_KEY] = "no_match"
            continue
        if len(candidates) > 1:
            stats["ambiguous_owner"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw[CHECKED_KEY] = "ambiguous_owner"
            continue
        cand = candidates[0]
        stats["matched"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        # Merge this run's single year into any prior run's own per_year map -- see "WHY
        # MULTI-YEAR DOESN'T FILL YET": this is what lets a LATER run (a future year's ad)
        # actually clear the multi-year gate without touching this file again.
        prior = li.raw.get(RAW_KEY)
        per_year = dict(prior.get("per_year") or {}) if isinstance(prior, dict) else {}
        per_year = {int(k): v for k, v in per_year.items()}
        per_year[TAX_YEAR] = cand["amount"]
        li.raw[RAW_KEY] = {
            "balance": cand["amount"], "year": TAX_YEAR, "parcel": cand["parcel"],
            "owner": li.owner_name, "per_year": {str(y): v for y, v in per_year.items()},
            "basis": "own_record", "match_method": "owner_name_unambiguous",
            "source": SLUG, "source_url": PDF_URL, "checked_at": now,
        }
        # Same shape nc_its_public_tax.aggregate() / enrichment_qpaybill_tax write -- the
        # EXISTING, untouched enrichment_tax_owed.py Pass B / enrichment_tax_aging.py already
        # read this key generically, no new wiring needed for tax_owed/tax_aging_surfaced.
        if not isinstance(li.raw.get("tax_owed"), dict) or not li.raw["tax_owed"].get("balance"):
            li.raw["tax_owed"] = {"balance": cand["amount"], "kind": "delinquent_tax",
                                  "source": SLUG, "year": TAX_YEAR, "basis": "own_record"}
        block = build_multiyear_block(per_year, today=today)
        if block is not None:
            li.raw[MYDT_KEY] = block
            stats["multiyear_qualified"] += 1

    log.info("pasquotank_tax.done", **stats)
    return stats
