"""County jail booking scraper — current in-custody inmate rosters.

Queries public county jail booking systems across our NC/SC footprint and
extracts inmate name, booking date, charges, and DOB (where available).
Returns Listing objects with listing_type=UNKNOWN (these are lead-discovery
signals, not property listings — the orchestrator cross-references inmate
names against property owner records downstream).

Supported systems (all free, public, no auth):
  - CentralSquare P2C (policetocitizen.com) — Buncombe NC (modern SPA variant
    with XSRF token handshake, ~540 in custody)
  - CentralSquare P2C jqGrid — Cleveland NC (classic ASP.NET jqGrid)
  - Zuercher Portal — Cherokee SC, Anderson SC (JSON API)
  - Southern Software Citizen Connect — Henderson NC (PHP AJAX "current
    confinements" roster; publishes FULL DOB on every record)
  - Tyler New World InmateInquiry — Gaston NC (plain GET form + HTML grid;
    publishes FULL DOB on every record)

NOT AN OWNER MATCH (checked 2026-10-05). Unlike enrichment_jail_bookings, this
scraper never compares an inmate to a property owner: each Listing IS the
inmate (defendant = the roster name, no address), and its raw['jail_booking']
describes that person's own booking. It sets no raw['incarceration'], so
distress_score's incarceration signal never fires off these rows, and it
carries no matched_name/confidence, so the enricher's same-county middle-name
gate and re-evaluation (which only touch the enricher's own stamps) leave these
rows alone by design.

Each system returns current in-custody inmates. We extract:
  - Inmate name (last, first, and the middle name where the vendor prints one)
  - DOB (if exposed — Buncombe redacts; Cleveland/Cherokee/Henderson/Gaston
    publish it in full, which is the point: DOB is the single biggest lift to
    downstream skip-trace match rates)
  - Booking/arrest date
  - Primary charge description
  - Release status (in-custody flag + scheduled release date where published)

FIXED 2026-10-14 (source-completeness audit, "mugshot inconsistency across
vendors" flag). Before this fix, 2 of 5 vendors (Zuercher's inline base64, the
modern P2C/Buncombe ImageId URL) carried a real mugshot through to
raw['jail_booking']['mugshot'], and the other 3 silently carried none, even
though 2 of those 3 genuinely publish one:
  - Citizen Connect (Henderson NC): every booking card's HTML already embeds
    a per-inmate `<img class='booking-mugshot' src='https://ssmugshots.blob.
    core.windows.net/images/<agency>-<nameid>-<bookingid>-...-Mugshot-1.jpg'>`
    -- live-verified 179/180 real photo URLs across the full roster (1 row
    fell back to the vendor's own literal "NoMugshot.jpg", which is filtered
    out rather than kept as if it were a photo). Free: the URL is already in
    the fetched HTML, no extra request.
  - Tyler New World (Gaston NC): the grid's own "Photo" column (previously
    discarded -- `_strip_tags` on an `<img>`-only cell strips it to "") is a
    real, directly-fetchable `/Inmate/Photo/<id>?type=Search` path -- live-
    verified on 2 ids returning distinct real JPEGs (25,879 / 32,308 bytes),
    no session or auth needed. Free: also just a URL, no extra request.
  - CentralSquare P2C jqGrid (Cleveland NC): THE ONE REAL EXCEPTION. This
    legacy ASP.NET WebForms system has no direct per-row image URL at all --
    live-verified the only way to reach a mugshot is to replay the grid's own
    "select row" postback (GET page for __VIEWSTATE, POST the grid query to
    seed server-side session state, POST the postback with the row's `invid`,
    then GET the now-session-scoped `Mug.aspx`) and that produces a real,
    distinct JPEG per row (confirmed on 5 rows, 5 different byte counts).
    That is 2+ extra requests PER INMATE against one small county host for
    ~300 rows every run -- the same "rude and slow" math the Tyler detail
    page already solved below by deferring to on-demand hydration. The fetch
    helper (`_fetch_p2c_jqgrid_mugshot`) is built and exposed for that same
    selective-hydration pattern (only rows that actually matched an owner),
    not called eagerly from `_fetch_p2c_jqgrid`.

NOT covered — Spartanburg SC: the Sheriff's Office "Bookings Search"
(spartanburgsheriff.org/258/Bookings-Search) 302s to
http://mugshots.spartanburgsheriff.org/, a legacy PHP roster
(/myscripts/mugshot_card.php?number=<id>) whose host stopped answering on both
:80 and :443. DNS still resolves (34.239.50.64) but the ports are closed, and
the Internet Archive's last successful capture is 2026-03-08 — i.e. the portal
is offline, not bot-walled. Spartanburg is not a Zuercher / P2C / JailTracker
tenant either, so there is no substitute host today. Re-check the redirect
target periodically; when it answers again, add a roster entry here.

The scraper follows the BaseScraper pattern with async fetch() returning
Iterable[Listing]. Uses curl_cffi (chrome impersonation) for systems that
fingerprint-block plain httpx, and the shared http_client for rate limiting.

Robots.txt: These are public-records APIs, not crawlable web pages. The
endpoints are the same JSON XHRs the public search UIs use. We check
robots.txt on the host anyway and fail-closed if disallowed.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import math
import re
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# County roster configurations
# ---------------------------------------------------------------------------
# (state, county, vendor, target)
# vendor: "p2c_centralsquare" | "p2c_jqgrid" | "zuercher" | "citizen_connect"
#         | "tyler_inmate_inquiry"
# target: Zuercher subdomain, P2C base URL, "host|listId" for modern P2C,
#         "AgencyID|JMSAgencyID" for Citizen Connect, or the app base URL for
#         Tyler New World InmateInquiry.

ROSTERS: list[tuple[str, str, str, str]] = [
    # Buncombe NC — CentralSquare P2C modern (policetocitizen.com SPA)
    # Verified live 2026-07-01: 542 in custody. XSRF token handshake.
    ("NC", "Buncombe", "p2c_centralsquare",
     "https://buncombecountyso.policetocitizen.com|23"),

    # Cleveland NC — CentralSquare P2C jqGrid (classic ASP.NET)
    # Verified live: jqGrid JSON endpoint at /jqHandler.ashx?op=s
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),

    # Cherokee SC — Zuercher Portal
    # Verified live: JSON API at /api/portal/inmates/load
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),

    # Anderson SC — Zuercher Portal
    # Verified live: JSON API at /api/portal/inmates/load
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),

    # Laurens SC, Zuercher Portal (build queue J-03, 2026-09-20)
    # Verified live 2026-09-20: 181 in custody; DOB blank on this tenant.
    ("SC", "Laurens", "zuercher", "laurens-911-sc"),

    # Oconee SC, Zuercher Portal (build queue J-04, 2026-09-20)
    # The sheriff's inmate-search page links straight to this tenant.
    # Verified live 2026-09-20: 183 in custody, DOB on every row.
    ("SC", "Oconee", "zuercher", "oconee-so-sc"),

    # Pickens SC, Zuercher Portal (found 2026-10-22: subdomain-pattern discovery sweep
    # against the project's own 18-county footprint, following the jail_bookings identity
    # fix). Verified live: 339 in custody. DOB is blank on this tenant (same as Laurens).
    ("SC", "Pickens", "zuercher", "pickens-so-sc"),

    # Union SC, Zuercher Portal (same discovery sweep). Verified live: 102 in custody. This
    # tenant redacts DOB and substitutes Age in the same JSON key -- handled by the int/str
    # type check in _fetch_zuercher (see that function's own 2026-10-22 comment).
    ("SC", "Union", "zuercher", "union-so-sc"),

    # Henderson NC — Southern Software Citizen Connect
    # Verified live 2026-07-31: 182 in custody, full DOB on 182/182.
    ("NC", "Henderson", "citizen_connect", "HendersonCoNC|NC0450000"),

    # Gaston NC — Tyler New World InmateInquiry (replaces the retired
    # newworld.aegis.webportal InmateInquiry.aspx, which now 302s away).
    # Verified live 2026-07-31: 695 in custody, full DOB on 695/695.
    ("NC", "Gaston", "tyler_inmate_inquiry",
     "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"),

    # York SC — standalone ASP.NET WebForms DataGrid (no vendor-product match; a county-built
    # system, not one of the 4 vendors above). No source existed for York at all before this
    # (gap_matrix: jail_booking/jail_booking_new/atty_obituary_match all "no source known").
    # Verified live 2026-10-22: 432 in custody total; this fetcher covers the first ~150
    # (10 pages) -- see _fetch_york_webforms's own docstring for the pagination-depth scope.
    ("SC", "York", "york_webforms",
     "https://inmatesinjail.yorkcountygov.com/detentioncenter/inmatesinjail.aspx"),
]

# Southern Software hosts every Citizen Connect tenant off one origin; the
# AgencyID query param selects the agency and seeds the PHP session.
CITIZEN_CONNECT_BASE = "https://cc.southernsoftware.com"

# Charge-string cap. Was 300, which truncated multi-charge rosters mid-charge
# (a booking can list 10+ counts). 2000 keeps the full charge list.
_CHARGE_CAP = 2000

# Generational suffixes to drop before deciding which token is the surname.
_NAME_SUFFIXES = frozenset(
    {"JR", "SR", "II", "III", "IV", "V", "JUNIOR", "SENIOR"})

# ---------------------------------------------------------------------------
# Name parsing helpers
# ---------------------------------------------------------------------------

def _norm_alpha(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _split_comma_name(name: str) -> tuple[str, str] | None:
    """'Smith, John Michael' -> ('SMITH', 'JOHN')."""
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    return last.strip().upper(), toks[0].strip().upper()


def _comma_middle(name: str) -> str:
    """'Smith, John Michael' -> 'MICHAEL'; '' when only one given name.

    Kept separate from `_split_comma_name` so that function's 2-tuple contract
    is unchanged. The middle is what enrichment_jail_bookings' same-county
    middle-name gate (2026-10-05) compares against the owner's middle initial;
    the 2026-10-02 live validation found 12.9% of same-county matches that had
    a middle on both sides were a different person.
    """
    if not name or "," not in name:
        return ""
    toks = name.partition(",")[2].strip().split()
    return toks[1].strip().upper() if len(toks) > 1 else ""


def _space_middle(name: str) -> str:
    """'MICHAEL LEE ABSHER' -> 'LEE' (the token after the given name, once
    trailing suffixes are dropped the same way `_split_space_name` does)."""
    toks = [t for t in re.split(r"\s+", (name or "").strip().upper()) if t]
    while len(toks) > 2 and _norm_alpha(toks[-1]) in _NAME_SUFFIXES:
        toks.pop()
    return toks[1] if len(toks) > 2 else ""


def _split_space_name(name: str) -> tuple[str, str] | None:
    """'MICHAEL LEE ABSHER' -> ('ABSHER', 'MICHAEL').

    Citizen Connect prints one flat "first middle last" string. The first token
    is the given name and the last the surname; trailing generational suffixes
    are dropped first so 'BOBBY DEAN ABEE JR' still yields ('ABEE', 'BOBBY').
    Compound surnames collapse to their final word, which is what the owner-name
    normalizer downstream does too.
    """
    toks = [t for t in re.split(r"\s+", (name or "").strip().upper()) if t]
    while len(toks) > 2 and _norm_alpha(toks[-1]) in _NAME_SUFFIXES:
        toks.pop()
    if len(toks) < 2:
        return None
    return toks[-1], toks[0]


def _strip_tags(fragment: str) -> str:
    """Flatten an HTML fragment to collapsed, entity-decoded plain text."""
    txt = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


def _parse_date(s: str | None) -> datetime | None:
    """Parse common date formats from jail rosters."""
    if not s:
        return None
    s = str(s).strip()
    # ISO format (Zuercher/ArrestDate)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 5], fmt) if "T" in fmt else datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    # US format — bare dates, 24h stamps (Citizen Connect) and 12h stamps
    # (Tyler New World).
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Vendor fetchers — each returns a list of inmate dicts
# ---------------------------------------------------------------------------

async def _fetch_zuercher(subdomain: str) -> list[dict]:
    """Fetch current in-custody roster from a Zuercher Portal instance.

    API: POST https://{subdomain}.zuercherportal.com/api/portal/inmates/load
    Returns JSON with 'records' array. Each record has name, dob, charges,
    arrest_date.
    """
    from curl_cffi.requests import AsyncSession

    url = f"https://{subdomain}.zuercherportal.com/api/portal/inmates/load"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {
        "name": "", "race": "all", "sex": "all", "cell_block": "all",
        "held_for_agency": "any", "in_custody": now,
        "paging": {"count": 2000, "start": 0},
        "sorting": {"sort_by_column_tag": "name", "sort_descending": False},
    }
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.post(url, json=body, timeout=30)
            recs = (r.json() or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.zuercher_fail", subdomain=subdomain,
                    error=str(exc)[:120])
        return []

    for rec in recs:
        parts = _split_comma_name(rec.get("name") or "")
        if not parts:
            continue
        last, first = parts
        charges = rec.get("hold_reasons") or rec.get("charges") or ""
        if isinstance(charges, list):
            charges = "; ".join(str(x) for x in charges)[:_CHARGE_CAP]
        else:
            # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch
            # 17): hold_reasons is a vendor-formatted HTML string with
            # embedded `<br />` tags between multiple charges (live-sampled
            # 4 counties: 200/291 Cherokee, 361/538 Anderson, 113/193
            # Laurens, 161/203 Oconee rows carry literal "<br" in the raw
            # string) -- was never stripped, so most charge descriptions
            # shipped with literal HTML markup instead of a clean separator.
            charges = _strip_tags(str(charges))
        # Extra Zuercher fields (live-verified present): race/sex/cell_block,
        # a release date, and a mugshot ref. Carry them through for skip-trace.
        cell_block = rec.get("cell_block")
        release_date = (rec.get("release_date")
                        or rec.get("actual_release_date")
                        or rec.get("projected_release_date"))
        # Refine the otherwise-hardcoded in_custody flag from cell_block/release.
        if release_date:
            release_status = f"release_scheduled {release_date}"
        elif cell_block:
            release_status = f"in_custody cell_block={cell_block}"
        else:
            release_status = "in_custody"
        # FOUND 2026-10-04: `mugshot` (and its `image`/`photo` aliases) is
        # raw base64 JPEG bytes embedded directly in the JSON response (the
        # `/9j/...` prefix is the base64 encoding of a JPEG's SOI marker,
        # confirmed live across all 4 Zuercher counties) -- NOT a URL, and
        # nothing downstream decodes or renders it (grepped the whole repo:
        # no other reference to "mugshot" exists). Storing the bare base64
        # string made it unusable to any consumer expecting an <img src=...>
        # value; wrapping it as a proper data: URI makes it actually
        # renderable without changing where it's stored (still namespaced
        # under raw.jail_booking, not raw.images, since this is a photo of
        # a PERSON, not the property, and the dashboard's images.real
        # channel is documented as the property-photo channel).
        mugshot_b64 = rec.get("mugshot") or rec.get("image") or rec.get("photo")
        mugshot_uri = (
            f"data:image/jpeg;base64,{mugshot_b64}"
            if isinstance(mugshot_b64, str) and mugshot_b64
            else None
        )
        # FOUND 2026-10-22 (Pickens/Union SC discovery): Union's tenant redacts the real DOB
        # and substitutes the subject's AGE in the same `dob` JSON key -- but as a bare integer
        # (`"dob": 42`), never the "YYYY-MM-DD" string every other live Zuercher county sends.
        # Type is a clean, vendor-provided signal: pass a real date straight through; route an
        # int into `age` instead of storing an age value under a dob key (same redaction
        # precedent as Buncombe's p2c_centralsquare feed, which also substitutes Age for DOB).
        dob_raw = rec.get("dob")
        out.append({
            "last": last, "first": first,
            "middle": _comma_middle(rec.get("name") or "") or None,
            "dob": dob_raw if isinstance(dob_raw, str) else None,
            "age": dob_raw if isinstance(dob_raw, (int, float)) else None,
            "arrest_date": rec.get("arrest_date"),
            "charge": str(charges)[:_CHARGE_CAP],
            "race": rec.get("race"),
            "sex": rec.get("sex"),
            "cell_block": cell_block,
            "release_date": release_date,
            "mugshot": mugshot_uri,
            "release_status": release_status,
            # Rarely true (3/291 live on Cherokee, 0 elsewhere) but a real,
            # free field -- flagged rather than silently dropped so a
            # downstream owner-cross-reference pass can choose to exclude
            # minors rather than never knowing the flag existed.
            "is_juvenile": bool(rec.get("is_juvenile")),
        })
    log.info("jail_scraper.zuercher_ok", subdomain=subdomain, count=len(out))
    return out


async def _fetch_p2c_jqgrid(base: str) -> list[dict]:
    """Fetch current in-custody roster from a CentralSquare P2C jqGrid system.

    Handshake: GET /jailinmates.aspx to seed session cookie, then POST to
    /jqHandler.ashx?op=s with jqGrid parameters. Returns JSON with 'rows'
    array.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(f"{base}/jailinmates.aspx", timeout=20)
            r = await s.post(
                f"{base}/jqHandler.ashx?op=s",
                data={
                    "t": "ii", "_search": "false", "rows": "2000",
                    "page": "1", "sidx": "disp_name", "sord": "asc",
                },
                timeout=30,
            )
            rows = (r.json() or {}).get("rows") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_jqgrid_fail", base=base,
                    error=str(exc)[:120])
        return []

    for rw in rows:
        last = (rw.get("lastname") or "").strip().upper()
        first = (rw.get("firstname") or "").strip().upper()
        if not last or not first:
            continue
        out.append({
            "last": last, "first": first,
            "dob": rw.get("dob"),
            "arrest_date": rw.get("disp_arrest_date"),
            "charge": (rw.get("chrgdesc") or rw.get("disp_charge") or "")[:_CHARGE_CAP],
            # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch
            # 17): live-verified every one of these is already on the same
            # jqGrid row this code already fetches, never read before.
            # book_id is a stable per-booking vendor id (better dedupe key
            # than name+county); middlename/age/race/sex are real skip-trace
            # identity signals.
            "middle": (rw.get("middlename") or "").strip().upper() or None,
            "age": rw.get("age"),
            "race": rw.get("race"),
            "sex": rw.get("sex"),
            "book_id": rw.get("book_id"),
            "agency": rw.get("disp_agency") or rw.get("agency"),
        })
    log.info("jail_scraper.p2c_jqgrid_ok", base=base, count=len(out))
    return out


async def _fetch_p2c_jqgrid_mugshot(base: str, book_id: str) -> str | None:
    """Fetch ONE inmate's mugshot from a classic CentralSquare P2C jqGrid system.

    Unlike every other vendor in this file, this system has no direct per-row
    image URL -- the photo is revealed only by replaying the live grid's own
    "select row" ASP.NET WebForms postback in a session that has already
    loaded that row, then GETting the now session-scoped Mug.aspx. Confirmed
    live 2026-10-14 on Cleveland NC: 5 different rows produced 5 real,
    differently-sized JPEGs this way.

    That is a GET (fresh __VIEWSTATE) + a POST (seed the session with the
    same full, sorted grid query `_fetch_p2c_jqgrid` already runs, so this
    book_id's position in it is reproducible) + a POST (the postback,
    selecting that position) + a GET (the photo) -- 4 requests for ONE photo.
    Doing that for an entire ~300-row roster every run would multiply this
    scraper's request volume against one small county host by ~300x, the
    same "rude and slow" math Tyler's `_fetch_tyler_detail` below already
    exists to avoid. So this is NOT called from `_fetch_p2c_jqgrid` --
    it is exposed standalone for selective, matched-row-only hydration
    (same pattern as `_hydrate_tyler_hits` in enrichment_jail_bookings.py).

    Returns a `data:image/jpeg;base64,...` URI (consistent with how the
    Zuercher vendor's own inline base64 mugshot is stored), or None.
    """
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(f"{base}/jailinmates.aspx", timeout=20)
            body = r.text or ""

            def _hidden(name: str) -> str:
                m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', body)
                return m.group(1) if m else ""

            viewstate = _hidden("__VIEWSTATE")
            viewstategen = _hidden("__VIEWSTATEGENERATOR")
            eventvalidation = _hidden("__EVENTVALIDATION")
            if not viewstate:
                return None

            gr = await s.post(
                f"{base}/jqHandler.ashx?op=s",
                data={
                    "t": "ii", "_search": "false", "rows": "2000",
                    "page": "1", "sidx": "disp_name", "sord": "asc",
                },
                timeout=30,
            )
            rows = (gr.json() or {}).get("rows") or []
            invid = next(
                (rw.get("invid") for rw in rows
                 if str(rw.get("book_id") or "") == str(book_id)),
                None,
            )
            if not invid:
                return None

            data = {
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstategen,
                "__EVENTVALIDATION": eventvalidation,
                "ctl00$MasterPage$mainContent$CenterColumnContent$hfRecordIndex": str(invid),
                "ctl00$MasterPage$mainContent$CenterColumnContent$btnInmateDetail": "",
            }
            await s.post(f"{base}/jailinmates.aspx", data=data, timeout=30)
            mug = await s.get(f"{base}/Mug.aspx", timeout=20)
            if mug.status_code != 200 or not mug.content:
                return None
            return "data:image/jpeg;base64," + base64.b64encode(mug.content).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_jqgrid_mugshot_fail", base=base,
                    book_id=book_id, error=str(exc)[:120])
        return None


async def _fetch_p2c_centralsquare(target: str) -> list[dict]:
    """Fetch current in-custody roster from modern CentralSquare P2C (policetocitizen.com).

    Handshake: GET an app route (/en/Inmates) to obtain the XSRF-TOKEN
    cookie, then echo it as X-XSRF-TOKEN header on the JSON search POST to
    /api/Inmates/<listId>. Page in blocks of 200 until a short page.
    DOB is redacted on the public feed; Age + ArrestDate survive.
    """
    from curl_cffi.requests import AsyncSession

    host, _, list_id = target.partition("|")
    list_id = list_id or "23"
    api = f"{host}/api/Inmates/{list_id}"
    page_size = 200
    out: list[dict] = []

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            # 1) Establish XSRF-TOKEN cookie via app-route GET
            await s.get(f"{host}/en/Inmates", timeout=25)
            token = s.cookies.get("XSRF-TOKEN")
            if not token:
                log.warning("jail_scraper.p2c_cs_no_token", host=host)
                return []
            hdr = {
                "X-XSRF-TOKEN": token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{host}/en/Inmates",
                "Origin": host,
            }
            skip = 0
            while True:
                body = {
                    "FilterOptionsParameters": {
                        "IntersectionSearch": True, "SearchText": "",
                        "Parameters": [],
                    },
                    "IncludeCount": True,
                    "PagingOptions": {
                        "SortOptions": [{
                            "Name": "ArrestDate",
                            "SortDirection": "Descending",
                            "Sequence": 1,
                        }],
                        "Take": page_size, "Skip": skip,
                    },
                }
                r = await s.post(api, headers=hdr, json=body, timeout=60)
                recs = (r.json() or {}).get("Inmates") or []
                if not recs:
                    break
                for rec in recs:
                    last = (rec.get("LastName") or "").strip().upper()
                    first = (rec.get("FirstName") or "").strip().upper()
                    if not last or not first:
                        continue
                    # FOUND 2026-10-04 (HERMES extraction-completeness audit,
                    # batch 17): live-verified this record already carries
                    # all of the below (same /api/Inmates/<listId> response
                    # this code already parses), none previously read.
                    # ScarsMarksTattoos populated on 174/200 (87%) of a live
                    # sample -- a strong identity-confirmation signal for
                    # skip-trace. Charges (the full list) carries a SECOND+
                    # charge on 158/200 (79%) of bookings -- the old code
                    # kept only PrimaryChargeDescription. ImageId maps to a
                    # real, directly fetchable mugshot at
                    # /api/Inmates/Image/<listId>/<ImageId> (confirmed live,
                    # 200 OK, real JPEG bytes) -- a photo source this vendor
                    # has never had wired at all. HomeAddress exists in the
                    # schema but was 0/200 populated live (this agency
                    # evidently redacts it, same policy as DateOfBirth) --
                    # captured anyway in case that policy ever changes, at
                    # zero marginal cost.
                    charges_list = rec.get("Charges") or []
                    extra_charges = [
                        c.get("Description") for c in charges_list
                        if isinstance(c, dict) and c.get("Description")
                        and c.get("Description") != rec.get("PrimaryChargeDescription")
                    ]
                    tattoos = rec.get("ScarsMarksTattoos") or []
                    tattoo_desc = "; ".join(
                        f"{t.get('Type', '')} {t.get('Location', '')} "
                        f"{t.get('BodyPart', '')}: {t.get('Description', '')}".strip()
                        for t in tattoos if isinstance(t, dict)
                    ) or None
                    image_id = rec.get("ImageId")
                    # FOUND 2026-10-22 (jail_bookings dedupe-collision audit): every charge in
                    # `Charges` already carries a real court docket number (live-verified e.g.
                    # "26CR 434460"), never read before. Booking-level, not charge-level, but one
                    # booking's docket is stable and unique enough to serve as a real per-record
                    # id -- the same role book_id plays for the jqGrid vendor.
                    docket = next((c.get("DocketNumber") for c in charges_list
                                   if isinstance(c, dict) and c.get("DocketNumber")), None)
                    out.append({
                        "last": last, "first": first,
                        "middle": (rec.get("MiddleName") or "").strip().upper() or None,
                        "dob": rec.get("DateOfBirth"),
                        "age": rec.get("Age"),
                        "arrest_date": rec.get("ArrestDate"),
                        "docket_number": docket,
                        "charge": (rec.get("PrimaryChargeDescription") or "")[:_CHARGE_CAP],
                        "other_charges": "; ".join(extra_charges)[:_CHARGE_CAP] or None,
                        "race": rec.get("Race"),
                        "sex": rec.get("Sex"),
                        "height": rec.get("Height"),
                        "weight": rec.get("Weight"),
                        "scars_marks_tattoos": tattoo_desc,
                        "holding_facility": rec.get("HoldingFacility"),
                        "booking_agency": rec.get("BookingAgency"),
                        "court_date": rec.get("CourtDate") or None,
                        "release_date_raw": rec.get("ReleaseDate") or None,
                        "total_bond_amount": rec.get("TotalBondAmount"),
                        "home_address": rec.get("HomeAddress") or None,
                        "mugshot_url": (
                            f"{host}/api/Inmates/Image/{list_id}/{image_id}"
                            if image_id else None
                        ),
                    })
                if len(recs) < page_size:
                    break
                skip += page_size
                if skip > 5000:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_cs_fail", host=host,
                    error=str(exc)[:120])
        return []

    log.info("jail_scraper.p2c_cs_ok", host=host, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Southern Software Citizen Connect (Henderson NC)
# ---------------------------------------------------------------------------

_CC_CARD_SPLIT = '<div class="card booking-card">'
_CC_NAME_RE = re.compile(r'<h5 class="mb-0">([^<]+)</h5>')
_CC_ROW_RE = re.compile(
    r'<span class="detail-label">([^<]*)</span>\s*'
    r'<span class="detail-value[^"]*">([^<]*)</span>')
_CC_CHARGE_RE = re.compile(
    r'<div class="charge-details"><div>(.*?)<span class="charge-agency"', re.S)
_CC_TOTAL_RE = re.compile(r"Total Inmates:.*?>(\d+)<", re.S)
_CC_SHOWING_RE = re.compile(r"Showing\s+\d+-(\d+)\s+of\s+(\d+)\s+inmates")
_CC_PAGE_SIZE = 20
# FOUND 2026-10-14: every card already embeds a real per-inmate mugshot
# <img>, previously never read (see module docstring). The vendor's own
# fallback for a booking with no uploaded photo is a literal, shared
# "NoMugshot.jpg" asset -- NOT per-row data, so it's detected and dropped
# rather than kept as if it were a real photo (live-verified 179 real /
# 1 fallback across Henderson's full roster).
_CC_MUGSHOT_RE = re.compile(r"""class=['"]booking-mugshot[^'"]*['"]\s*\n?\s*src=['"]([^'"]+)['"]""")


def _parse_citizen_connect_cards(html_text: str) -> list[dict]:
    """Parse the booking cards out of one fetch_current_confinements.php page."""
    out: list[dict] = []
    for card in (html_text or "").split(_CC_CARD_SPLIT)[1:]:
        nm = _CC_NAME_RE.search(card)
        if not nm:
            continue
        flat_name = html.unescape(nm.group(1))
        parts = _split_space_name(flat_name)
        if not parts:
            continue
        last, first = parts
        fields = {k.strip().rstrip(":"): html.unescape(v).strip()
                  for k, v in _CC_ROW_RE.findall(card)}
        charges = [_strip_tags(c) for c in _CC_CHARGE_RE.findall(card)]
        charges = [c for c in charges if c]
        # "36 years / W / M" -> "36"
        age = (fields.get("Demographics", "").split(" years")[0].strip()
               or None)
        mm = _CC_MUGSHOT_RE.search(card)
        mugshot_src = mm.group(1) if mm else None
        if mugshot_src and "nomugshot" in mugshot_src.lower():
            mugshot_src = None
        out.append({
            "last": last, "first": first,
            "middle": _space_middle(flat_name) or None,
            "dob": fields.get("Date of Birth") or None,
            "age": age,
            "arrest_date": (fields.get("Booked")
                            or fields.get("Arrest Date/Time") or None),
            "charge": "; ".join(charges)[:_CHARGE_CAP],
            # This feed is the CURRENT-confinements list, so every row is a
            # person still in custody; the vendor publishes no release column.
            "release_status": "in_custody",
            "mugshot_url": mugshot_src,
            # Forward the full label:value card dict (Demographics, Booked,
            # Facility, etc.) — the parser reads few of these but they carry
            # extra skip-trace signal.
            "fields": fields,
        })
    return out


async def _fetch_citizen_connect(target: str) -> list[dict]:
    """Southern Software Citizen Connect current-confinements roster.

    target is "<AgencyID>|<JMSAgencyID>", e.g. "HendersonCoNC|NC0450000".

    Handshake: the AJAX endpoint answers 500 "Session AgencyID not set" unless a
    PHP session has already been seeded, so GET the booking-search page once
    (?AgencyID=...) and reuse the session cookie. Page 1 posts JMSAgencyID; the
    vendor's own pager then posts IDX=<1-based page> against the same session.
    Full DOB is published on every card. Free + compliant: this is the page's
    own XHR, no login, no CAPTCHA, no WAF token.
    """
    from curl_cffi.requests import AsyncSession

    agency, _, jms = target.partition("|")
    page_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID={agency}"
    api = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/fetchesforajax/"
           "fetch_current_confinements.php")
    hdr = {"X-Requested-With": "XMLHttpRequest", "Referer": page_url}
    out: list[dict] = []

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(page_url, timeout=30)
            r = await s.post(api, headers=hdr, timeout=60, data={
                "JMSAgencyID": jms, "search": "", "agency": "", "sort": "name"})
            body = r.text or ""
            if "booking-card" not in body:
                log.warning("jail_scraper.citizen_connect_empty", agency=agency)
                return []
            out.extend(_parse_citizen_connect_cards(body))

            tm = _CC_TOTAL_RE.search(body)
            sm = _CC_SHOWING_RE.search(body)
            total = int(tm.group(1)) if tm else (
                int(sm.group(2)) if sm else len(out))
            pages = min(math.ceil(total / _CC_PAGE_SIZE) if total else 1, 60)
            for page in range(2, pages + 1):
                await asyncio.sleep(0.3)  # polite pacing
                pr = await s.post(api, headers=hdr, timeout=60, data={
                    "IDX": page, "search": "", "agency": "", "sort": "name"})
                recs = _parse_citizen_connect_cards(pr.text or "")
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.citizen_connect_fail", agency=agency,
                    error=str(exc)[:120])
        return out

    log.info("jail_scraper.citizen_connect_ok", agency=agency, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Tyler New World InmateInquiry (Gaston NC)
# ---------------------------------------------------------------------------

_TNW_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TNW_CELL_RE = re.compile(r'<td class="([A-Za-z]+)">(.*?)</td>', re.S)
_TNW_DETAIL_RE = re.compile(r"Inmate/Detail/(\d+)")
_TNW_SHOWING_RE = re.compile(
    r"Showing\s*(\d+)\s*to\s*(\d+)\s*of\s*(\d+)", re.S)
_TNW_FIELD_RE = re.compile(r'<span id=([A-Za-z]+)>(.*?)</span>', re.S)
_TNW_MAX_PAGES = 30
# FOUND 2026-10-14: the grid's own "Photo" column was always discarded --
# `_TNW_CELL_RE` matches `class="Photo"` same as any other cell, but
# `_strip_tags` on a cell that is ONLY an `<img>` (no text) strips it to ""
# before this regex ever runs, so the field quietly became useless. This
# captures the real `src` directly off the row, live-verified on 2 ids as
# distinct, directly-fetchable real JPEGs (25,879 / 32,308 bytes), no
# session or auth needed -- unlike the jqGrid vendor below, this is a plain
# URL with zero extra request cost.
_TNW_PHOTO_RE = re.compile(r'<td class="Photo"><img src="([^"]+)"', re.S)


def _parse_tyler_rows(html_text: str, base: str = "") -> list[dict]:
    """Parse the in-custody grid of a Tyler New World InmateInquiry page."""
    out: list[dict] = []
    for rowm in _TNW_ROW_RE.finditer(html_text or ""):
        row = rowm.group(1)
        cells = {k: _strip_tags(v) for k, v in _TNW_CELL_RE.findall(row)}
        if not cells.get("Name"):
            continue
        parts = _split_comma_name(html.unescape(cells["Name"]))
        if not parts:
            continue
        last, first = parts
        in_custody = cells.get("InCustody", "").upper() == "YES"
        if not in_custody:
            continue
        det = _TNW_DETAIL_RE.search(row)
        photo_m = _TNW_PHOTO_RE.search(row)
        mugshot_url = (
            urljoin(base, html.unescape(photo_m.group(1))) if photo_m and base
            else (html.unescape(photo_m.group(1)) if photo_m else None)
        )
        sched = cells.get("ScheduledReleaseDate") or None
        out.append({
            "last": last, "first": first,
            "middle": _comma_middle(html.unescape(cells["Name"])) or None,
            "dob": cells.get("DateOfBirth") or None,
            "mugshot_url": mugshot_url,
            "arrest_date": None,   # booking date lives on the detail page
            "charge": "",          # charges live on the detail page
            "release_status": (f"scheduled_release {sched}" if sched
                               else "in_custody"),
            "scheduled_release": sched,
            "facility": cells.get("HousingFacility") or None,
            "detail_id": det.group(1) if det else None,
            # Forward the full parsed grid-cell dict (Name/DateOfBirth/
            # InCustody/HousingFacility/ScheduledReleaseDate/...).
            "cells": cells,
        })
    return out


def _parse_tyler_detail(html_text: str) -> dict:
    """Pull booking date + charge list off one Inmate/Detail page.

    The page lists the subject's whole booking history newest-first; the open
    booking is the first one with an empty Release Date.
    """
    body = html_text or ""
    charges = [_strip_tags(v) for _, v in
               re.findall(r'<td class="(ChargeDescription)">(.*?)</td>', body, re.S)]
    charges = [c for c in charges if c]
    booking_date = None
    for block in body.split('<div class="Booking">')[1:]:
        fields = {k: _strip_tags(v) for k, v in _TNW_FIELD_RE.findall(block)}
        if fields.get("ReleaseDate"):
            continue
        booking_date = fields.get("BookingDate") or None
        break
    return {"arrest_date": booking_date, "charge": "; ".join(charges)[:_CHARGE_CAP]}


async def _fetch_tyler_detail(base: str, detail_id: str) -> dict:
    """Fetch one Tyler Inmate/Detail page and return {arrest_date, charge}.

    Kept standalone so the enricher can hydrate only the rows it actually
    matched to an owner (one GET each) instead of the whole 700-row roster.
    """
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(f"{base}/Inmate/Detail/{detail_id}", timeout=45)
        return _parse_tyler_detail(r.text or "")
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.tyler_detail_fail", detail_id=detail_id,
                    error=str(exc)[:120])
        return {}


async def _fetch_tyler_inmate_inquiry(base: str, detail_limit: int = 0) -> list[dict]:
    """Tyler New World InmateInquiry current in-custody roster.

    The search form is a plain GET, so `?InCustody=True&Page=<n>` returns the
    whole roster 100 rows at a time. The grid carries FULL DOB, the in-custody
    flag and the scheduled release date. Booking date and charges are only on
    the per-inmate detail page, so they are fetched for at most `detail_limit`
    records (0 = grid only) to keep one run to a handful of requests.

    Free + compliant: a public GET form, no login, no CAPTCHA, no WAF token.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            page = 1
            while page <= _TNW_MAX_PAGES:
                r = await s.get(f"{base}?InCustody=True&Page={page}", timeout=60)
                body = r.text or ""
                recs = _parse_tyler_rows(body, base=base)
                if not recs:
                    break
                out.extend(recs)
                sm = _TNW_SHOWING_RE.search(body)
                if not sm or int(sm.group(2)) >= int(sm.group(3)):
                    break
                page += 1
                await asyncio.sleep(0.3)  # polite pacing

            for rec in out[:max(detail_limit, 0)]:
                if not rec.get("detail_id"):
                    continue
                await asyncio.sleep(0.3)
                dr = await s.get(f"{base}/Inmate/Detail/{rec['detail_id']}",
                                 timeout=45)
                rec.update(_parse_tyler_detail(dr.text or ""))
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.tyler_fail", base=base, error=str(exc)[:120])
        return out

    log.info("jail_scraper.tyler_ok", base=base, count=len(out))
    return out


def _york_clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


_YORK_PAGE_SIZE = 15
#: Numeric page-link postback targets 2-10 (page 1 is the initial GET). The pager's own "..."
#: control advances to the NEXT page-GROUP (11-20, 21-30, ...) rather than a single page -- full
#: coverage of the ~29-page/432-row roster would need to walk those groups too. Scoped to the
#: first 10 pages (~150 most-recent bookings) for now: jail_booking_new specifically cares about
#: RECENT activity, and this directly-addressable range covers that without the added complexity
#: of re-deriving the group-advance target from each page's own pager state. Revisit if full
#: historical coverage is ever needed.
_YORK_PAGE_TARGETS = [f"dgJackets$ctl01$ctl0{n}" for n in range(1, 10)]


def _parse_york_page(body: str) -> list[dict]:
    """Pure: one page's inmate records from York County SC's inmatesinjail.aspx (classic
    ASP.NET WebForms DataGrid, no JSON API -- live-verified 2026-10-22, 15 records/page)."""
    out: list[dict] = []
    chunks = body.split('<td colspan="2" class="cell1">')[1:]
    for chunk in chunks:
        name_m = re.match(r"([^<]*)</td>", chunk)
        if not name_m:
            continue
        name_parts = _york_clean(name_m.group(1)).split(" ", 1)
        last = name_parts[0].rstrip(",")
        rest = name_parts[1].split(" ", 1) if len(name_parts) > 1 else []
        first = rest[0] if rest else ""
        middle = rest[1] if len(rest) > 1 else None
        if not (last and first):
            continue

        def field(label: str) -> str | None:
            m = re.search(
                rf'class="text1">{label}:?\s*</td>\s*<td class="medBoldBlack">([^<]*)</td>', chunk)
            return _york_clean(m.group(1)) if m else None

        booking_date = field("Booking Date")
        city = field("City")
        state_zip = (field("State/Zip") or "").split(" ", 1)
        race_sex = (field("Race/Sex") or "").split(" ")
        age = field("Age")

        photo_m = re.search(r'href="(/photos/[^"]+)"', chunk)
        photo = urljoin("https://inmatesinjail.yorkcountygov.com", photo_m.group(1)) if photo_m else None

        booking_m = re.search(
            r'class="medBlackText">\s*([^<]+?)\s*</td>\s*'
            r'<td class="medBlackTexta">\s*([^<]+?)\s*</td>\s*'
            r'<td class="medBlackTexta">([^<]*?)\s*</td>\s*'
            r'<td class="medBlackTexta2">\s*([^<]+?)\s*</td>',
            chunk,
        )
        charges = re.findall(
            r'class="medBlackText3">\s*(\d+)\s*</td>\s*'
            r'<td class="medBlackText3">\s*([^<]+?)\s*</td>\s*'
            r'<td class="medBlackText3">\s*([^<]+?)\s*</td>',
            chunk,
        )
        # Worst/first charge as the headline (same "one charge field" contract every other
        # vendor fetcher here returns); the full list is kept too for anyone who wants it.
        charge_list = [{"seq": c[0], "desc": _york_clean(c[1]), "agency": _york_clean(c[2])}
                       for c in charges]
        out.append({
            "last": last.upper(), "first": first.upper(),
            "middle": middle.upper() if middle else None,
            "age": age, "race": race_sex[0] if race_sex else None,
            "sex": race_sex[1] if len(race_sex) > 1 else None,
            "arrest_date": booking_date,
            "book_id": _york_clean(booking_m.group(1)) if booking_m else None,
            "charge": (charge_list[0]["desc"] if charge_list else "")[:_CHARGE_CAP],
            "agency": charge_list[0]["agency"] if charge_list else None,
            "charges": charge_list,
            "release_status": _york_clean(booking_m.group(3)) if booking_m else None,
            "bond": _york_clean(booking_m.group(4)) if booking_m else None,
            "city": city, "state": state_zip[0] if state_zip else None,
            "zip": state_zip[1] if len(state_zip) > 1 else None,
            "photo_url": photo,
        })
    return out


async def _fetch_york_webforms(target: str) -> list[dict]:
    """Fetch current in-custody roster from York County SC's inmatesinjail.aspx (classic ASP.NET
    WebForms DataGrid -- no vendor product match in this file, a county-built/standalone system).

    No source existed for York SC at all before this (gap_matrix: jail_booking/jail_booking_new/
    atty_obituary_match all "no source known", "ran": False). Live-verified 2026-10-22: 432 in
    custody total, this fetches the first ~150 (10 pages, see _YORK_PAGE_TARGETS' own docstring
    for why not the full roster yet). Pagination is a classic ASP.NET DataGrid postback
    (__EVENTTARGET=dgJackets$ctl01$ctlNN + the page's own __VIEWSTATE/__VIEWSTATEGENERATOR/
    __EVENTVALIDATION resubmitted each time), same technique this file's own
    _fetch_p2c_jqgrid_mugshot() already uses for a different vendor's postback.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=20)
            body = r.text or ""
            out.extend(_parse_york_page(body))

            def _hidden(html_body: str, name: str) -> str:
                m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', html_body)
                return m.group(1) if m else ""

            for page_target in _YORK_PAGE_TARGETS:
                vs = _hidden(body, "__VIEWSTATE")
                vsg = _hidden(body, "__VIEWSTATEGENERATOR")
                ev = _hidden(body, "__EVENTVALIDATION")
                if not vs:
                    break
                data = {
                    "__EVENTTARGET": page_target, "__EVENTARGUMENT": "",
                    "__VIEWSTATE": vs, "__VIEWSTATEGENERATOR": vsg, "__EVENTVALIDATION": ev,
                }
                r = await s.post(target, data=data, timeout=20)
                body = r.text or ""
                recs = _parse_york_page(body)
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.york_webforms_fail", target=target, error=str(exc)[:120])
        return out

    log.info("jail_scraper.york_webforms_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Vendor dispatcher
# ---------------------------------------------------------------------------

async def _fetch_roster(state: str, county: str, vendor: str, target: str) -> list[dict]:
    """Dispatch to the correct vendor fetcher."""
    try:
        if vendor == "zuercher":
            return await _fetch_zuercher(target)
        elif vendor == "p2c_jqgrid":
            return await _fetch_p2c_jqgrid(target)
        elif vendor == "p2c_centralsquare":
            return await _fetch_p2c_centralsquare(target)
        elif vendor == "citizen_connect":
            return await _fetch_citizen_connect(target)
        elif vendor == "tyler_inmate_inquiry":
            return await _fetch_tyler_inmate_inquiry(target)
        elif vendor == "york_webforms":
            return await _fetch_york_webforms(target)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.fetch_error", county=county, vendor=vendor,
                    error=str(exc)[:160])
    return []


# ---------------------------------------------------------------------------
# Listing builder
# ---------------------------------------------------------------------------

def _booking_identity(rec: dict, last: str, first: str) -> Optional[str]:
    """A stable per-booking identifier for dedupe_key()'s case_number branch.

    FOUND 2026-10-22 (jail_bookings dedupe-collision audit, following the York SC build):
    every county's booking Listings fell through to dedupe_key()'s `url:{source_url}` branch
    (source_url is the same fixed per-county search-page URL for every booking at that county),
    the exact collision class fixed for Cleveland/York via book_id/case_number -- confirmed LIVE
    on the published board: Gaston's 673 jail_booking rows (pre-fix) all shared ONE dedupe key,
    meaning every booking past the first was silently rejected as "already on board".

    Preference order: a real vendor-issued id (p2c_jqgrid's book_id, Tyler's detail_id, now
    p2c_centralsquare's docket_number -- each already carried on `rec` by its own fetcher) wins.
    Zuercher and Citizen-Connect publish no id of any kind (live-verified: neither vendor's own
    JSON/HTML exposes anything beyond name/dob/demographics/charges) -- for those, synthesize a
    stable key from (name, dob, arrest_date). A hash, not a literal join: dedupe_key()'s own
    case_number normalization strips every non-alnum character, so an unhashed join could let two
    different (name, dob, date) tuples collapse onto the same stripped string at a field boundary;
    hashing the delimited tuple removes that ambiguity. Two bookings of the SAME person on
    DIFFERENT dates correctly get different keys (a new incident, not a dup)."""
    real_id = rec.get("book_id") or rec.get("detail_id") or rec.get("docket_number")
    if real_id:
        return str(real_id)
    dob = (rec.get("dob") or "").strip()
    adate = (rec.get("arrest_date") or "").strip()
    if not (last or first) or not (dob or adate):
        return None
    basis = f"{last.strip().upper()}|{first.strip().upper()}|{dob}|{adate}"
    return "synth" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _to_listing(rec: dict, state: str, county: str) -> Listing:
    """Convert an inmate record to a Listing object."""
    last = rec.get("last", "")
    first = rec.get("first", "")
    full_name = f"{last}, {first}" if last and first else (last or first)

    booking_date = _parse_date(rec.get("arrest_date"))

    # Build a source URL — link to the county's public search page
    if state == "NC" and county == "Buncombe":
        # FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 17):
        # /en/Inmates returns HTTP 200 (so the scraper's own XSRF-token
        # handshake still works) but the Angular SPA's client-side router
        # has no route for that locale-prefixed path and renders its own
        # "404 - Not Found" page to a human visitor (confirmed live via
        # browser render). The real, working nav target (confirmed live by
        # clicking the site's own "Inmates" menu link) is /Inmates/Catalog.
        source_url = "https://buncombecountyso.policetocitizen.com/Inmates/Catalog"
    elif state == "NC" and county == "Cleveland":
        source_url = "http://74.218.167.200/p2c/jailinmates.aspx"
    elif state == "SC" and county == "Cherokee":
        source_url = "https://cherokee-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Anderson":
        source_url = "https://anderson-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Laurens":
        source_url = "https://laurens-911-sc.zuercherportal.com/"
    elif state == "SC" and county == "Oconee":
        source_url = "https://oconee-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Pickens":
        source_url = "https://pickens-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Union":
        source_url = "https://union-so-sc.zuercherportal.com/"
    elif state == "NC" and county == "Henderson":
        source_url = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/"
                      "index.php?AgencyID=HendersonCoNC")
    elif state == "NC" and county == "Gaston":
        source_url = ("https://tepsweb.cityofgastonia.com/"
                      "NewWorld.InmateInquiry/GastonCounty?InCustody=True")
    else:
        source_url = ""

    charge = rec.get("charge") or ""

    return Listing(
        source="national.jail_bookings",
        source_url=source_url,
        # See _booking_identity()'s own docstring: routes every vendor (real id where one
        # exists, a stable name+dob+arrest_date hash where none does) through dedupe_key()'s
        # (case_number, county) branch instead of the shared-per-county url: fallback.
        case_number=_booking_identity(rec, last, first),
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        defendant=full_name,
        county=county,
        state=state,
        sale_date=booking_date,  # re-purposed as booking date
        description=charge or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "jail_booking": {
                "county": county,
                "state": state,
                "inmate_name": full_name,
                "last_name": last,
                "first_name": first,
                "dob": rec.get("dob"),
                "age": rec.get("age"),
                "booking_date": booking_date.isoformat() if booking_date else None,
                "charge": charge,
                "release_status": rec.get("release_status") or "in_custody",
                "scheduled_release": rec.get("scheduled_release"),
                "facility": rec.get("facility"),
                # Zuercher demographics + release detail (dropped before).
                "race": rec.get("race"),
                "sex": rec.get("sex"),
                "cell_block": rec.get("cell_block"),
                "release_date": rec.get("release_date"),
                "mugshot": rec.get("mugshot") or rec.get("mugshot_url"),
                "is_juvenile": rec.get("is_juvenile"),
                # Full vendor field/cell dicts (Citizen-Connect / Tyler).
                "fields": rec.get("fields"),
                "cells": rec.get("cells"),
                "vendor": "jail_bookings_scraper",
                # FOUND 2026-10-04 (HERMES extraction-completeness audit,
                # batch 17): the below were all already on the vendor row
                # this scraper already fetches (p2c_jqgrid Cleveland /
                # p2c_centralsquare Buncombe) but never read or carried
                # through to the Listing. See the two vendor fetchers'
                # inline comments for live-sample evidence.
                "middle_name": rec.get("middle"),
                "book_id": rec.get("book_id"),
                "agency": rec.get("agency"),
                "other_charges": rec.get("other_charges"),
                "height": rec.get("height"),
                "weight": rec.get("weight"),
                "scars_marks_tattoos": rec.get("scars_marks_tattoos"),
                "holding_facility": rec.get("holding_facility"),
                "booking_agency": rec.get("booking_agency"),
                "court_date": rec.get("court_date"),
                "total_bond_amount": rec.get("total_bond_amount"),
                "home_address": rec.get("home_address"),
            },
        },
    )


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class JailBookingsScraper(BaseScraper):
    """Scrape current in-custody jail rosters across NC/SC counties.

    Returns Listing objects with listing_type=UNKNOWN — these are name-only
    lead signals for cross-referencing against property owner records.
    """

    slug = "national.jail_bookings"
    name = "County Jail Bookings (NC/SC)"
    category = "jail_bookings"
    expected_min_count = 0
    timeout_s = 120.0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        # Fetch all rosters concurrently
        tasks = [
            _fetch_roster(state, county, vendor, target)
            for state, county, vendor, target in ROSTERS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (state, county, vendor, target), inmates in zip(ROSTERS, results):
            if isinstance(inmates, Exception):
                log.warning("jail_scraper.county_error",
                            county=county, error=str(inmates)[:160])
                continue
            if not inmates:
                continue
            for rec in inmates:
                out.append(_to_listing(rec, state, county))

        log.info("jail_scraper.done", total=len(out),
                 counties=sum(1 for r in results if isinstance(r, list) and r))
        return out
