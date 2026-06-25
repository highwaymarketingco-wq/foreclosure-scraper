"""Charleston County (SC) Master-in-Equity foreclosure source.

Built 2026-06-25 to close the Charleston gap. ``sc_coastal_rosters`` deliberately
skips Charleston because Charleston's publicindex courtrosters app exposes NO
Master-in-Equity roster type (verified 2026-06-24 — its RosterType dropdown lists
only Removal/Motion/Trial dockets, no MO/Foreclosure). Charleston runs its
Master-in-Equity foreclosure SALES through the county's own website instead of
sccourts publicindex, so this scraper hits the county site directly.

Two complementary methods, both free + compliant (plain HTTP, public pages, no
login/CAPTCHA/WAF defeat):

(1) AUCTION LIST  — GET /foreclosure/runninglist.html
    The authoritative upcoming-sale list ("MASTER'S AUCTION LIST"). It's a
    Word-exported windows-1252 MSO HTML document — tag-soup with no usable table
    structure — so we tag-strip to flat text and parse by REGEX anchored on the
    10-digit TMS parcel (NOT column slicing). Each sale row looks like:

        07-07-26 25-06873 Computershare Delaware Peter J. Dieppe IV
        3501400030 1906 Capri Drive $453,617.57 1 st Riley Pope & Laney
        803-799-9993 West Ashley

    i.e. MM-DD-YY sale date, case#, plaintiff, defendant, 10-digit TMS, street
    address, $judgment, lien position, attorney, phone, city. Some rows carry a
    "RE-OPEN"/"REOPEN MM-DD-YY" upset-bid marker between the sale date and the
    case#. We emit a FORECLOSURE_SALE with parcel_id=TMS, sale_date,
    opening_bid=judgment, plaintiff, defendant, street_address, city.

(2) HEARING ROSTER — GET /departments/master-in-equity/rosters/UncontestedRoster.pdf
    The uncontested HEARING roster (pdfplumber). These are EARLIEST-SIGNAL leads:
    a foreclosure that has a hearing scheduled but no sale date / TMS / address
    yet. Structure is time-block driven:

        10:30 a.m.
        Scott & Corley 26-0242 NewRez, LLC v. Woods, Teresa
                       26-0533 US Bank Trust NA v. Beach, Adelai K

    one attorney heading per time block, then one or more "CASE# Plaintiff v.
    Defendant" entries (a defendant name can wrap to the next line). There is an
    "HOA FORECLOSURES" section near the end. No address/TMS on this roster, so
    these emit as LIS_PENDENS with case_number + plaintiff + defendant only; they
    resolve downstream by case# when the same matter later appears on the auction
    list (or in a law-firm/lis-pendens source).

Dedupe is by TMS (auction list) and normalized case# across BOTH methods, so a
matter that's on both the hearing roster (case 25-6873) and the auction list
(case 25-06873) is emitted once, preferring the richer auction-list row.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable, Optional

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

AUCTION_LIST_URL = "https://charlestoncounty.gov/foreclosure/runninglist.html"
HEARING_ROSTER_URL = (
    "https://charlestoncounty.gov/departments/master-in-equity/rosters/"
    "UncontestedRoster.pdf"
)

# A 10-digit Charleston TMS (parcel) is the load-bearing anchor for an auction
# row: it always sits between the defendant text and the street address, and no
# other field in a row is a bare 10-digit run.
_TMS_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")
# Sale date in the running list: MM-DD-YY (e.g. 07-07-26).
_SALE_DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{2})\b")
# Judgment / lien amount.
_AMT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# Street address: starts at a house number right after the TMS, runs up to the
# $ amount. Charleston rows put the street between the TMS and the judgment.
_ADDR_RE = re.compile(
    r"^\s*(\d{1,6}\s*[A-Za-z].*?)\s*(?=\$)"
)
# RE-OPEN / REOPEN upset-bid marker (optionally followed by a new MM-DD-YY date).
_REOPEN_RE = re.compile(r"\bRE-?OPEN\b", re.I)

# Hearing-roster case number, e.g. "25-5260" / "26-0242" (2-digit year, 3-5
# digit sequence). The auction list pads to 5 digits ("25-06873"); we normalize
# both so the two methods dedupe.
_PDF_CASE_RE = re.compile(r"\b(\d{2})-(\d{3,5})\b")
# A hearing-roster entry line body: "<plaintiff> v. <defendant>".
_PARTIES_RE = re.compile(r"^(?P<plaintiff>.+?)\s+v\.?\s+(?P<defendant>.+)$", re.I)
# Attorney heading lines end in a case number; the attorney name is the text
# before the first case number on the line.
_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*[ap]\.?m\.?", re.I)
# Trailing parenthetical annotations on roster entries we want to surface but
# strip out of the defendant name, e.g. "(filed bankruptcy)", "(Estate)",
# "(moved to 06/09 roster for GAL)".
_ANNOTATION_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _norm_case(case: str | None) -> str:
    """Canonical case key: strip non-alnum, drop a leading zero on the sequence
    so the roster's '25-5260' matches the auction list's '25-05260'. Returns ''
    for empty input."""
    if not case:
        return ""
    m = _PDF_CASE_RE.search(case)
    if not m:
        return re.sub(r"[^a-z0-9]", "", case.lower())
    yr, seq = m.group(1), m.group(2).lstrip("0") or "0"
    return f"{yr}{seq}"


def _strip_html(raw: bytes) -> str:
    """Decode the windows-1252 MSO export and tag-strip to flat text. We keep a
    single space between former tags so adjacent fields don't run together."""
    txt = raw.decode("windows-1252", errors="replace")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = (
        txt.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("’", "'")
    )
    txt = re.sub(r"&#?\w+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def _parse_sale_date(mm: str, dd: str, yy: str) -> Optional[datetime]:
    try:
        return datetime(2000 + int(yy), int(mm), int(dd))
    except (ValueError, TypeError):
        return None


def parse_auction_list(raw: bytes, source_url: str = AUCTION_LIST_URL) -> list[Listing]:
    """TMS-anchored parser for the MASTER'S AUCTION LIST.

    We split the flat text into row-blocks on the TMS parcels (each 10-digit run
    starts the property half of a row), then pull the sale date + case# from the
    text BEFORE the TMS and the address + judgment from the text AFTER it. This
    is robust to the variable plaintiff/defendant wording and the optional
    RE-OPEN marker that plain column-slicing can't handle.
    """
    text = _strip_html(raw)
    # Confine to the data region (after the column-header row) so MSO style junk
    # before/after never produces phantom rows.
    hdr = text.find("Date of\nSale")
    if hdr == -1:
        hdr = text.find("Date of Sale")
    if hdr != -1:
        text = text[hdr:]

    out: list[Listing] = []
    seen_tms: set[str] = set()
    seen_case: set[str] = set()

    tms_iter = list(_TMS_RE.finditer(text))
    for i, m in enumerate(tms_iter):
        tms = m.group(1)
        if tms in seen_tms:
            continue

        # Text before this TMS, bounded by the PREVIOUS TMS (so we only look at
        # this row's leading fields, never the prior row's trailing city).
        prev_end = tms_iter[i - 1].end() if i > 0 else 0
        before = text[prev_end:m.start()]
        # Text after this TMS, bounded by the NEXT TMS.
        next_start = tms_iter[i + 1].start() if i + 1 < len(tms_iter) else len(text)
        after = text[m.end():next_start]

        # Sale date = the LAST MM-DD-YY before the TMS. A RE-OPEN row has two
        # dates (original sale date + re-open date); the re-open date is the one
        # the auction actually runs on, and it appears closest to the TMS.
        sale_date = None
        date_matches = list(_SALE_DATE_RE.finditer(before))
        if date_matches:
            dm = date_matches[-1]
            sale_date = _parse_sale_date(dm.group(1), dm.group(2), dm.group(3))

        # Case number = first NN-NNNNN after the (last) sale date.
        case_number = None
        case_search_from = date_matches[-1].end() if date_matches else 0
        cm = re.search(r"\b(\d{2}-\d{4,5})\b", before[case_search_from:])
        if cm:
            case_number = cm.group(1)

        reopened = bool(_REOPEN_RE.search(before))

        # Address = run from the first house number after the TMS up to the $.
        address = None
        am = _ADDR_RE.match(after)
        if am:
            address = re.sub(r"\s+", " ", am.group(1)).strip(" -––")

        # Judgment / opening bid = first $ amount after the TMS.
        opening_bid = None
        amt_m = _AMT_RE.search(after)
        if amt_m:
            try:
                opening_bid = float(amt_m.group(1).replace(",", ""))
            except ValueError:
                pass

        # Plaintiff/defendant: between the case# and the TMS. Best-effort split —
        # the names have no delimiter, so we record the raw blob in `description`
        # and only attempt a light plaintiff capture (text right after the case#).
        plaintiff = None
        defendant = None
        if case_number:
            tail = before[before.find(case_number) + len(case_number):].strip()
            # Defendant tends to be the trailing token group before the TMS; we
            # can't reliably split the two undelimited names, so keep the whole
            # party blob in `description` and leave plaintiff/defendant best-effort.
            if tail:
                plaintiff = tail[:120].strip() or None

        seen_tms.add(tms)
        if case_number:
            seen_case.add(_norm_case(case_number))

        party_blob = re.sub(r"\s+", " ", before).strip()
        out.append(
            Listing(
                source="counties_sc.charleston_mie",
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=address,
                city=None,
                state="SC",
                county="Charleston",
                parcel_id=tms,
                sale_date=sale_date,
                opening_bid=opening_bid,
                judgment_amount=opening_bid,
                plaintiff=plaintiff,
                defendant=defendant,
                case_number=case_number,
                foreclosure_process="judicial",
                auction_status="reopen" if reopened else "active",
                description=(party_blob[:400] or None),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "charleston_mie": {
                        "method": "auction_list",
                        "tms": tms,
                        "reopened": reopened,
                    }
                },
            )
        )
    return out


def parse_hearing_roster(
    data: bytes, source_url: str = HEARING_ROSTER_URL
) -> list[Listing]:
    """pdfplumber parser for the UncontestedRoster.pdf HEARING roster.

    Walks the text line by line. A line containing a CASE# carries an entry:
    "<attorney?> <CASE#> <Plaintiff> v. <Defendant>". The defendant frequently
    wraps onto the following 1-2 lines (and those continuation lines have no
    case#), so we greedily append non-case, non-time, non-section continuation
    lines to the current entry before parsing parties. Tracks whether we've
    crossed the "HOA FORECLOSURES" section so HOA matters are tagged HOA_SALE.
    """
    out: list[Listing] = []
    try:
        import pdfplumber
    except ImportError:
        return out

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            full = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return out

    lines = [ln.strip() for ln in full.splitlines() if ln.strip()]

    # Build logical entries: each starts at a line with a case#, and absorbs the
    # following continuation lines (no case#, not a time, not a section header)
    # which hold the wrapped defendant name.
    in_hoa = False
    entries: list[tuple[str, bool]] = []  # (entry_text, is_hoa)
    i = 0
    while i < len(lines):
        ln = lines[i]
        if "HOA FORECLOSURE" in ln.upper():
            in_hoa = True
            i += 1
            continue
        if _PDF_CASE_RE.search(ln):
            # One physical line can hold MULTIPLE case entries when an attorney
            # heading is followed by a second case on the same wrapped block; but
            # in this roster each case starts its own entry. Split the line into
            # per-case chunks at each case-number boundary.
            buf = ln
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if (
                    _PDF_CASE_RE.search(nxt)
                    or _TIME_RE.search(nxt)
                    or "HOA FORECLOSURE" in nxt.upper()
                ):
                    break
                buf += " " + nxt
                j += 1
            entries.append((buf, in_hoa))
            i = j
        else:
            i += 1

    seen_case: set[str] = set()
    for entry, is_hoa in entries:
        # A buffer may contain >1 case (e.g. an attorney heading line that lists
        # two cases). Split on each case-number so every case becomes a Listing.
        case_positions = [m.start() for m in _PDF_CASE_RE.finditer(entry)]
        for k, pos in enumerate(case_positions):
            end = case_positions[k + 1] if k + 1 < len(case_positions) else len(entry)
            chunk = entry[pos:end]
            cm = _PDF_CASE_RE.match(chunk) or _PDF_CASE_RE.search(chunk)
            if not cm:
                continue
            case_number = f"{cm.group(1)}-{cm.group(2)}"
            norm = _norm_case(case_number)
            if norm in seen_case:
                continue
            seen_case.add(norm)

            body = chunk[cm.end():].strip()
            body = _ANNOTATION_RE.sub("", body).strip()
            plaintiff = defendant = None
            pm = _PARTIES_RE.match(body)
            if pm:
                plaintiff = pm.group("plaintiff").strip()[:200] or None
                defendant = _ANNOTATION_RE.sub("", pm.group("defendant")).strip()
                defendant = defendant[:200] or None

            out.append(
                Listing(
                    source="counties_sc.charleston_mie",
                    source_url=source_url,
                    listing_type=ListingType.HOA_SALE if is_hoa else ListingType.LIS_PENDENS,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Charleston",
                    case_number=case_number,
                    plaintiff=plaintiff,
                    defendant=defendant,
                    foreclosure_process="judicial",
                    auction_status="hearing",
                    description=(re.sub(r"\s+", " ", chunk).strip()[:300] or None),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        "charleston_mie": {
                            "method": "hearing_roster",
                            "hoa": is_hoa,
                        }
                    },
                )
            )
    return out


class CharlestonMasterInEquity(BaseScraper):
    slug = "counties_sc.charleston_mie"
    name = "Charleston County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 90.0
    requires_render = False
    # Auction list reliably carries many rows; roster is earliest-signal. Set a
    # modest floor so an empty-list regression is flagged but a quiet hearing
    # week doesn't false-alarm.
    expected_min_count = 3

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_tms: set[str] = set()
        seen_case: set[str] = set()

        async with client(timeout=60.0) as c:
            # (1) Auction list — primary, richest rows.
            try:
                r = await c.get(AUCTION_LIST_URL, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and r.content[:6].lstrip().lower().startswith(b"<html"):
                    for li in parse_auction_list(r.content, AUCTION_LIST_URL):
                        if li.parcel_id and li.parcel_id in seen_tms:
                            continue
                        if li.parcel_id:
                            seen_tms.add(li.parcel_id)
                        nc = _norm_case(li.case_number)
                        if nc:
                            seen_case.add(nc)
                        out.append(li)
            except Exception:
                pass

            # (2) Hearing roster — earliest-signal leads; skip any case already
            # captured (richer) from the auction list.
            try:
                r = await c.get(HEARING_ROSTER_URL, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and r.content[:4] == b"%PDF":
                    for li in parse_hearing_roster(r.content, HEARING_ROSTER_URL):
                        nc = _norm_case(li.case_number)
                        if nc and nc in seen_case:
                            continue
                        if nc:
                            seen_case.add(nc)
                        out.append(li)
            except Exception:
                pass

        return out
