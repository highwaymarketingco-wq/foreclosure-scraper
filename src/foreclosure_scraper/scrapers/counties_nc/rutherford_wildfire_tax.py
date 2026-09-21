"""Rutherford County NC — Sturgis/Avalon "Wildfire" tax-bill records API.

This is the engine behind ``rutherfordcountync.gov/tax_search/#/WildfireSearch``:
an AngularJS SPA ("Avalon", vendor Sturgis Web Services) whose whole bill file is
served from a JSON endpoint. It is by far the deepest Rutherford tax surface —
every bill back to 2004, with owner name, full owner MAILING address, situs
address, parcel number, assessed real value, amount due, and status flags
including ``ADVERTISED`` (the NCGS 105-369 tax-lien advertisement) and
``OUTSIDE LAW FIRM`` (already referred to Kania for foreclosure).

ACCESS PATTERN — VERIFIED LIVE 2026-08-03
------------------------------------------
``POST {host}/data/{client_id}/Wildfire/Records``
body  ``{"value": "", "skip": <n>, "facets": {...}, "direct": false}``
Page 1 needs no header and returns ``{SearchToken, TotalRecords, Records[20],
Facets}``. Every page after that must echo the page-1 token as a
``SearchToken:`` request header; without it the server answers 401. The token is
stable for the life of the search session and is returned unchanged on every
page — i.e. it is an ordinary server-side scroll cursor (an Elasticsearch-style
search context), NOT an anti-bot challenge: there is no CAPTCHA, no JS
proof-of-work, no signed nonce, no cookie, and the token is handed out by the
same unauthenticated POST that returns page 1. Page size is fixed at 20;
``take``/``size``/``limit`` in the body are ignored. RE-VERIFIED LIVE 2026-09-21: the
same shape still answers, but ONLY with ``Accept: application/json`` (see below);
the filter's ``TotalRecords`` was 27,822 that day (per year: 2025 6,925; 2024 5,568;
2023 4,637; 2022 2,667; 2021 1,384; 2020 1,803; 2019 2,352; 2018 1,678; 2017 807;
2016 1).

Facets are the filter surface, shaped ``{"Status": {"Unpaid": true}, ...}``:
  Status  Unpaid | Paid
  Type    Property | Motor Vehicle
  Years   "2004" … "2026"
``Status=Unpaid`` + ``Type=Property`` + the ten years TY2016-TY2025 returned
``TotalRecords: 29319`` on 2026-08-03 — the genuinely delinquent real+personal
property universe. The current bill year is excluded on purpose: NC bills for a
year become delinquent the following January 6th (see ``BillInterest.BeginDate``
on every record), so TY2026 "Unpaid" is 66,578 rows of merely-not-yet-due bills,
not distress.

COMPLIANCE: ROBOTS IS NOT A WALL (OWNER DECISION 2026-09-20)
------------------------------------------------------------
Both hosts that serve this API publish a blanket ``Disallow: /`` (that is
``d1ebsyxxbc7tep.cloudfront.net``, the CDN the SPA calls, and
``avalon.sturgiswebservices.com``, its origin). Until 2026-09-20 this module
treated that as a wall and ``fetch()`` failed closed to ``[]``. The owner has
since decided that a robots.txt Disallow alone is NOT a wall; a CAPTCHA, a login,
a Cloudflare/WAF challenge or a terms click-through still is. So the robots
preflight is now OFF by default and kept behind ``ROBOTS_STRICT=1`` (nothing was
deleted: ``_path_disallowed`` and ``_robots_blocks`` are unchanged, and setting the
flag restores the old fail-closed behaviour exactly).

What replaces it is politeness, which is what the decision asks for:

  * ONE request at a time, never concurrent (the shared client already spaces
    requests to a host 0.8 to 1.5 s apart; ``RUTHERFORD_WILDFIRE_DELAY_S`` adds
    0.25 s on top by default).
  * a real browser User-Agent (the shared client's).
  * ``Retry-After`` is honoured on 429 and 503 (capped at 300 s, 4 attempts).
  * HTTP 403, or a 200 whose body is a challenge/CAPTCHA page, ABORTS the whole
    sweep at once. It is a wall by the owner's own definition, so we stop rather
    than probe around it, and whatever was already collected is still shipped.
  * the sweep is RESUMABLE and CACHED (see below), so a killed run, a timeout or a
    second scoped run never repeats requests it has already made.

SILENT-SUCCESS TRAP FOUND 2026-09-21 (fixed here): the API answers HTTP 200 with
an HTML "Avalon :: Data Only" page (3.4 KB) unless the request carries
``Accept: application/json``. The shared client's default Accept is the HTML one,
so this scraper's ``r.json()`` used to fail on every page ("bad_json") and the
year loop ended with zero rows even with the robots gate open. Every POST now sends
``Accept: application/json, text/plain, */*`` (what the AngularJS SPA sends), and a
non-JSON 200 is a loud error, never an empty result.

RESUMABLE, ONE-LEAD-PER-PARCEL
------------------------------
The delinquent filter is ~27.8k bills (27,822 on 2026-09-21; 29,319 on 2026-08-03),
but more than half are ``IND``/``BUS`` personal property and one parcel carries a
bill per unpaid year, so the emitted lead count is the number of distinct real-
estate PARCELS, not bills. ``_records_to_listings`` rolls the bills up per parcel:
one TAX_LIEN lead with the summed amount and a per-year breakdown
(``raw.rutherford_wildfire.years_detail`` / ``amount_by_year``).

Progress is written after every page to ``data/rutherford_wildfire_state.json``
(per year: reported total, next skip, done) plus ``data/rutherford_wildfire_bills.jsonl``
(one slimmed real-estate bill per line). A rerun within ``RUTHERFORD_WILDFIRE_RESUME_H``
(72 h) continues at the recorded skip; a COMPLETE sweep younger than
``RUTHERFORD_WILDFIRE_CACHE_H`` (12 h) is re-used with no requests at all. Each year is
its own search context (largest year 6,925 rows, under the 10,000-row result window).
The reported per-year total is compared with what was actually fetched, and a shortfall
is logged as ``rutherford_wildfire.year_short`` (the pager on sibling vendors is lossy
and silent, so the count is checked, not trusted).

Scoped runs: ``apply_row_limit(n)`` (used by ``scripts/run_scoped_scrapers.py``) caps the
sweep at roughly ``n`` parcel leads by capping the page count.

RELATIONSHIP TO THE OTHER TWO RUTHERFORD SOURCES
------------------------------------------------
``counties_nc.rutherford_tax`` reads the county's TR-452 Excel export: 9,337
bills / $5.64M, but TY2025 only, no owner mailing address, no flags. That one is
robots-clean and county-hosted, so it is the source that actually runs today.
``national.nc_upset_bids`` reads the two ``/foreclosure_information/`` pages —
the ~26 parcels already in a sale/upset posture. This module is the superset of
both: ten tax years, mailing addresses for skip-trace, and the ADVERTISED /
OUTSIDE LAW FIRM flags that say exactly how far down the 105-369 pipeline a
parcel already is. Rows collapse into the other two by parcel key in dedupe.

Dateless: a delinquent bill has no sale date. ``counties_nc.rutherford_wildfire_tax``
is already in ``main.DATELESS_OK_SOURCES`` (added while the source was inert), so no
``main.py`` change is needed for it to survive ``_active_only``. It is a TAX_LIEN, so
``_in_scope`` applies the distressed (any NC/SC county) rule, not the 18-county flip rule.

The module is named ``…_wildfire_tax`` on purpose: ``enrichment_tax_owed``
recognises a delinquent-amount source by a "tax"/"lien"/"delinquent" substring
in the slug, and without one ``raw['amount_owed']`` would never normalize into
``raw['tax_owed']``.
"""
from __future__ import annotations

import asyncio
import datetime
import email.utils
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client, get_text
from ...models import Listing, ListingType, PropertyKind
from .rutherford_tax import _split_situs

log = structlog.get_logger()

SLUG = "counties_nc.rutherford_wildfire_tax"

#: SPA shell — used to re-discover the CDN host + client id if the vendor
#: re-points them. Robots-clean (the county's own domain).
TAX_SEARCH_URL = "https://www.rutherfordcountync.gov/tax_search/index.php"

#: Defaults observed 2026-08-03 in the SPA bundle.
DEFAULT_API_HOST = "https://d1ebsyxxbc7tep.cloudfront.net"
DEFAULT_CLIENT_ID = "5b88e44b-0038-4361-8c53-7ce1343ad3ad"

#: `<script src="//<host>/js/<client-id>/1.js">` in the tax_search page.
_APP_JS_RE = re.compile(
    r'src="(?://|https://)([a-z0-9.\-]+cloudfront\.net)/js/'
    r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/',
    re.I,
)

#: Fixed by the server; body overrides are ignored.
PAGE_SIZE = 20

#: Safety cap on pages per tax year: 500 pages x 20 = 10,000 rows. The largest
#: single year on the delinquent filter was 7,365 rows (TY2025) on 2026-08-03,
#: so the cap is headroom, not a truncation.
MAX_PAGES_PER_YEAR = int(os.environ.get("RUTHERFORD_WILDFIRE_MAX_PAGES", "500"))

#: How many tax years back to sweep (newest first, current bill year excluded).
YEARS_BACK = int(os.environ.get("RUTHERFORD_WILDFIRE_YEARS", "10"))

#: Flag tokens worth promoting. Matched as substrings of the flag Description /
#: FlagsString so a vendor wording change degrades to "unrecognised", not "lost".
_FLAG_ADVERTISED = "ADVERTISED"
_FLAG_OUTSIDE_FIRM = "OUTSIDE LAW"
_FLAG_DELINQUENT = "DELINQUENT"

#: What the AngularJS SPA sends. Without a JSON Accept the API answers 200 with an
#: HTML "Data Only" page, which is the silent-success trap described in the docstring.
API_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}

#: Politeness knobs. The shared client already spaces same-host requests 0.8-1.5 s.
EXTRA_DELAY_S = float(os.environ.get("RUTHERFORD_WILDFIRE_DELAY_S", "0.25"))
RETRY_AFTER_CAP_S = 300.0
MAX_ATTEMPTS = 4
#: A re-minted SearchToken is allowed this many times per tax year before giving up.
MAX_TOKEN_REMINTS = 2

#: Resumable-sweep state. ``data/`` is git-ignored.
_REPO = Path(__file__).resolve().parents[4]
STATE_PATH = Path(os.environ.get("RUTHERFORD_WILDFIRE_STATE",
                                 str(_REPO / "data" / "rutherford_wildfire_state.json")))
BILLS_PATH = STATE_PATH.with_name("rutherford_wildfire_bills.jsonl")
RESUME_MAX_AGE_H = float(os.environ.get("RUTHERFORD_WILDFIRE_RESUME_H", "72"))
CACHE_MAX_AGE_H = float(os.environ.get("RUTHERFORD_WILDFIRE_CACHE_H", "12"))
#: A year whose fetched bill count is below this share of the reported total is logged.
SHORTFALL_WARN = 0.98

#: Post-office city names this feed writes that ``rutherford_tax._CITIES`` lacks.
_EXTRA_CITIES: tuple[str, ...] = ("CHIMNEY ROCK VILLAGE",)


class WildfireWall(RuntimeError):
    """A 403, or a 200 that is a challenge/CAPTCHA page. The owner's rule: stop."""


class WildfireNotJson(RuntimeError):
    """A 200 that is not JSON and does not look like a challenge (e.g. the Accept
    trap). Loud on purpose: an empty result here would be a silent success."""


def _robots_strict() -> bool:
    """``ROBOTS_STRICT=1`` restores the pre-2026-09-20 fail-closed robots preflight."""
    return os.environ.get("ROBOTS_STRICT", "").strip().lower() in ("1", "true", "yes")


# --------------------------------------------------------------------------- #
# robots guard (same evaluator shape as rod/kofile.py)
# --------------------------------------------------------------------------- #

def _path_disallowed(robots_body: str, path: str) -> bool:
    """Minimal robots.txt evaluator for the ``user-agent: *`` group: True if
    ``path`` is Disallowed and not overridden by a more-specific Allow."""
    ua_star = False
    allows: list[str] = []
    disallows: list[str] = []
    for raw in (robots_body or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            ua_star = value == "*"
        elif ua_star and field == "allow":
            allows.append(value)
        elif ua_star and field == "disallow":
            disallows.append(value)

    def _matches(rule: str) -> bool:
        if not rule:
            return False
        if rule.endswith("$"):
            return path == rule[:-1]
        return path.startswith(rule)

    best_dis = max((r for r in disallows if _matches(r)), key=len, default=None)
    best_all = max((r for r in allows if _matches(r)), key=len, default=None)
    if best_dis is None:
        return False
    if best_all is not None and len(best_all.rstrip("$")) >= len(best_dis):
        return False
    return True


async def _robots_blocks(api_host: str, path: str) -> bool:
    """True if ``api_host``'s robots.txt disallows the records path for ``*``.

    Fails CLOSED when robots.txt is unreadable — we never POST at an endpoint we
    cannot confirm is robots-allowed. Compliance guard, not a bug.
    """
    try:
        async with client(timeout=20.0) as c:
            r = await c.get(api_host.rstrip("/") + "/robots.txt")
    except Exception:  # noqa: BLE001
        return True
    if r.status_code != 200:
        return True
    return _path_disallowed(r.text or "", path)


# --------------------------------------------------------------------------- #
# record -> Listing
# --------------------------------------------------------------------------- #

def _money(v: Any) -> float | None:
    try:
        f = round(float(v), 2)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _clean(v: Any) -> str | None:
    """Strip whitespace and the stray NUL bytes this feed puts in owner names."""
    s = (str(v) if v is not None else "").replace("\x00", "").strip()
    return s or None


def _owner_name(rec: dict) -> str | None:
    parts = [_clean(rec.get(f"OwnerName{i}")) for i in (1, 2, 3)]
    joined = " & ".join(p for p in parts if p)
    return joined or None


def _flag_labels(rec: dict) -> list[str]:
    """Human flag labels, from Flags[].Description with FlagsString as backup."""
    out: list[str] = []
    for f in rec.get("Flags") or []:
        if isinstance(f, dict):
            d = _clean(f.get("Description"))
            if d:
                out.append(d.upper())
    if not out:
        out = [t.strip().upper() for t in (rec.get("FlagsString") or "").split(",")
               if t.strip()]
    return out


def _mailing(rec: dict) -> dict[str, str | None] | None:
    a = rec.get("OwnerAddress") or {}
    if not isinstance(a, dict):
        return None
    out = {
        "addr": _clean(a.get("Line1")),
        "addr2": _clean(a.get("Line2")),
        "city": _clean(a.get("City")),
        "state": _clean(a.get("State")),
        "zip": _clean(a.get("Zip")),
        "in_care_of": _clean(a.get("InCareOfName")),
    }
    return out if out["addr"] or out["city"] else None


def _records_to_listings(records: Iterable[dict], source_url: str,
                         slug: str = SLUG) -> list[Listing]:
    """Fold raw Wildfire records into one Listing per parcel.

    Only ``AbstractType == "REI"`` rows with a parcel number are real property —
    ``IND`` (individual personal property) and ``BUS`` (business personal
    property) rows ride the same "Property" facet but are not land. Amounts are
    summed across every delinquent tax year for the parcel.
    """
    agg: dict[str, dict[str, Any]] = {}
    seen_bills: set[str] = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if (rec.get("AbstractType") or "").strip().upper() != "REI":
            continue
        parcel = _clean(rec.get("ParcelNumber"))
        if not parcel:
            continue
        owed = _money((rec.get("Values") or {}).get("AmountDue"))
        if not owed:
            continue
        # A resumed sweep can replay the last page; a bill must never count twice.
        bill_key = _clean(rec.get("IDHash")) or _clean(rec.get("Bill"))
        if bill_key:
            if bill_key in seen_bills:
                continue
            seen_bills.add(bill_key)
        year = rec.get("BillYear")
        a = agg.setdefault(parcel, {
            "owed": 0.0, "years": set(), "bills": [], "flags": set(),
            "newest": None, "newest_year": -1, "by_year": {},
        })
        a["owed"] += owed
        if isinstance(year, int):
            a["years"].add(year)
            yd = a["by_year"].setdefault(year, {
                "year": year, "amount_due": 0.0, "original_due": 0.0,
                "bills": [], "flags": set()})
            yd["amount_due"] += owed
            yd["original_due"] += _money((rec.get("Values") or {}).get("OriginalAmountDue")) or 0.0
            if _clean(rec.get("Bill")):
                yd["bills"].append(_clean(rec.get("Bill")))
            yd["flags"].update(_flag_labels(rec))
        bill = _clean(rec.get("Bill"))
        if bill:
            a["bills"].append(bill)
        a["flags"].update(_flag_labels(rec))
        # Keep the newest year's record as the attribute donor (freshest owner,
        # value and situs).
        yr = year if isinstance(year, int) else -1
        if yr >= a["newest_year"]:
            a["newest_year"], a["newest"] = yr, rec

    out: list[Listing] = []
    now = datetime.datetime.utcnow()
    for parcel, a in agg.items():
        rec = a["newest"] or {}
        owed = round(a["owed"], 2)
        owner = _owner_name(rec)
        situs_raw = _clean((rec.get("SitusAddress") or {}).get("Line1"))
        street, city, zipc, situs_legal = _split_situs(situs_raw or "")
        # The county writes house number 0 for a lot with no structure ("0 GLEN RIDGE
        # TRL"). That is a road name, not an address: a geocoder snaps it to the road's
        # centroid (the road-centroid trap), so keep the parcel id as the locator and the
        # raw situs in raw, and leave street_address empty.
        if street and not city:
            # This feed's post-office name for Chimney Rock is "CHIMNEY ROCK VILLAGE", which
            # rutherford_tax._CITIES (built off the TR-452 export) does not carry.
            up = street.upper()
            for extra in _EXTRA_CITIES:
                if up.endswith(" " + extra) and len(street) > len(extra) + 1:
                    street, city = street[: -(len(extra) + 1)].strip(), extra.title()
                    break
        vacant_lot = bool(street and re.match(r"^0+\s+\S", street))
        if vacant_lot:
            street = None
        # `Description` IS the legal description on this feed ("RIVERBEND
        # HIGHLANDS LO524 PL10-122"); an unparseable situs line is the fallback.
        legal = _clean(rec.get("Description")) or situs_legal

        flags = sorted(a["flags"])
        advertised = any(_FLAG_ADVERTISED in f for f in flags)
        outside_firm = any(_FLAG_OUTSIDE_FIRM in f for f in flags)

        # RealValue is the county's assessed real-property value (NC assesses at
        # ~market). Set it so these grade without needing GIS; calc caps the
        # confidence and data_quality marks it assessed-basis.
        real_value = _money((rec.get("Values") or {}).get("RealValue"))
        market = real_value if (real_value and 1000 <= real_value <= 20_000_000) else None

        acres = None
        try:
            acres = float(rec["Acres"]) if rec.get("Acres") not in (None, "") else None
        except (TypeError, ValueError):
            acres = None

        years = sorted(a["years"], reverse=True)
        years_detail = [
            {"year": y,
             "amount_due": round(a["by_year"][y]["amount_due"], 2),
             "original_due": round(a["by_year"][y]["original_due"], 2),
             "bills": sorted(set(a["by_year"][y]["bills"])),
             "flags": sorted(a["by_year"][y]["flags"])}
            for y in years if y in a["by_year"]
        ]
        bits = [owner or "Unknown owner",
                f"Rutherford NC delinquent tax ${owed:,.0f} owed",
                f"parcel {parcel}"]
        if years:
            bits.append(f"TY{years[-1]}-{years[0]}" if len(years) > 1
                        else f"TY{years[0]}")
        if outside_firm:
            bits.append("referred to outside law firm")
        elif advertised:
            bits.append("tax lien advertised")

        out.append(Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Rutherford",
            parcel_id=parcel,
            street_address=street,
            city=city,
            zip_code=zipc,
            legal_description=legal,
            owner_name=owner,
            defendant=owner,
            acreage=acres,
            market_value=market,
            # Amount owed as a first-class field (same convention as
            # counties_nc.rutherford_tax / counties_sc.horry_flc).
            judgment_amount=owed,
            foreclosure_process="tax",
            # How far down the NCGS 105-369 pipeline this parcel already is.
            auction_status=("referred_outside_counsel" if outside_firm
                            else "advertised" if advertised else None),
            description=" — ".join(bits)[:300],
            first_seen=now,
            last_seen=now,
            raw={"rutherford_wildfire": {
                "parcel": parcel,
                "owner": owner,
                # back-tax OWED (summed across years) -> tax_owed, NOT value
                "amount_owed": owed,
                "tax_years": years,
                # one entry per delinquent tax year, newest first: the amount still due
                # (tax + interest + costs) and the original bill
                "years_detail": years_detail,
                "amount_by_year": {str(d["year"]): d["amount_due"] for d in years_detail},
                "oldest_delinquent_year": years[-1] if years else None,
                "bill_numbers": sorted(set(a["bills"]))[:10],
                "bill_count": len(a["bills"]),
                "flags": flags,
                "advertised": advertised,
                "outside_law_firm": outside_firm,
                "delinquent_flag": any(_FLAG_DELINQUENT in f for f in flags),
                "owner_mailing": _mailing(rec),
                "situs_raw": situs_raw,
                "situs_vacant_lot": vacant_lot,
                "assessed_real_value": real_value,
                "id_hash": _clean(rec.get("IDHash")),
                "dateless": True,
                "source": "sturgis_avalon_wildfire",
            }},
        ))
    return out


# --------------------------------------------------------------------------- #
# live fetch
# --------------------------------------------------------------------------- #

def _delinquent_years(today: datetime.date | None = None) -> list[int]:
    """Tax years that are actually delinquent, newest first.

    NC bills for year Y go delinquent on 6 Jan of Y+1, so the current bill year
    is never delinquent and is excluded.
    """
    d = today or datetime.date.today()
    newest = d.year - 1
    return [newest - i for i in range(max(1, YEARS_BACK))]


def _facets(years: Iterable[int]) -> dict[str, dict[str, bool]]:
    return {
        "Status": {"Unpaid": True},
        "Type": {"Property": True},
        "Years": {str(y): True for y in years},
    }


def _discover_endpoint(html: str) -> tuple[str, str]:
    """(api_host, client_id) from the tax_search SPA shell, with fallbacks."""
    m = _APP_JS_RE.search(html or "")
    if m:
        return f"https://{m.group(1)}", m.group(2)
    return DEFAULT_API_HOST, DEFAULT_CLIENT_ID


# --------------------------------------------------------------------------- #
# polite POST
# --------------------------------------------------------------------------- #

_CHALLENGE_MARKERS = ("captcha", "recaptcha", "hcaptcha", "cf-challenge", "challenge-platform",
                      "just a moment", "access denied", "attention required", "are you a human",
                      "verify you are human", "incapsula", "_incapsula_", "akamai")


def _retry_after_s(headers, default: float) -> float:
    """Seconds to wait from a Retry-After header (delta-seconds or an HTTP date)."""
    raw = (headers.get("retry-after") or "").strip() if headers is not None else ""
    if not raw:
        return default
    try:
        return max(0.0, min(float(raw), RETRY_AFTER_CAP_S))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
        delta = (when - datetime.datetime.now(when.tzinfo)).total_seconds()
        return max(0.0, min(delta, RETRY_AFTER_CAP_S))
    except (TypeError, ValueError):
        return default


def _looks_like_challenge(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _CHALLENGE_MARKERS)


async def _post_page(c, url: str, body: dict, token: str | None) -> dict:
    """POST one page and return the decoded JSON payload.

    Raises ``WildfireWall`` on a 403 or a challenge page (stop the whole sweep),
    ``WildfireNotJson`` on a non-JSON 200, and ``PermissionError('401')`` when the
    search token was rejected (the caller re-mints it). 429/503 honour Retry-After.
    Anything else non-200 raises RuntimeError.
    """
    headers = dict(API_HEADERS)
    if token:
        headers["SearchToken"] = token
    last_status: int | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r = await c.post(url, content=json.dumps(body), headers=headers)
        last_status = r.status_code
        if r.status_code == 200:
            ctype = (r.headers.get("content-type") or "").lower()
            text = r.text or ""
            if "json" in ctype or text.lstrip().startswith("{"):
                try:
                    return r.json()
                except ValueError as exc:
                    raise WildfireNotJson(f"200 with a JSON content-type but undecodable body: {exc}")
            if _looks_like_challenge(text):
                raise WildfireWall("200 challenge/CAPTCHA page instead of JSON")
            m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
            raise WildfireNotJson(
                f"200 {ctype or 'no content-type'} instead of JSON "
                f"(title={(m.group(1).strip() if m else '')[:60]!r}, {len(text)} bytes)")
        if r.status_code == 403:
            raise WildfireWall("HTTP 403")
        if r.status_code == 401:
            raise PermissionError("401")
        if r.status_code in (429, 503):
            wait = _retry_after_s(r.headers, default=min(30.0 * attempt, RETRY_AFTER_CAP_S))
            log.warning("rutherford_wildfire.backoff", status=r.status_code,
                        attempt=attempt, wait_s=round(wait, 1))
            if attempt == MAX_ATTEMPTS:
                break
            await asyncio.sleep(wait)
            continue
        raise RuntimeError(f"HTTP {r.status_code}")
    raise RuntimeError(f"HTTP {last_status} after {MAX_ATTEMPTS} attempts")


# --------------------------------------------------------------------------- #
# resumable state
# --------------------------------------------------------------------------- #

def _slim(rec: dict) -> dict:
    """Keep only what ``_records_to_listings`` reads. A raw bill carries LineItems,
    payment history and a dozen vendor fields (~5 KB); this is ~0.7 KB."""
    v = rec.get("Values") or {}
    return {
        "AbstractType": rec.get("AbstractType"),
        "ParcelNumber": rec.get("ParcelNumber"),
        "BillYear": rec.get("BillYear"),
        "Bill": rec.get("Bill"),
        "BillType": rec.get("BillType"),
        "IDHash": rec.get("IDHash"),
        "Description": rec.get("Description"),
        "Acres": rec.get("Acres"),
        "OwnerName1": rec.get("OwnerName1"),
        "OwnerName2": rec.get("OwnerName2"),
        "OwnerName3": rec.get("OwnerName3"),
        "OwnerAddress": rec.get("OwnerAddress"),
        "SitusAddress": rec.get("SitusAddress"),
        "FlagsString": rec.get("FlagsString"),
        "Flags": [{"Description": (f or {}).get("Description")}
                  for f in (rec.get("Flags") or []) if isinstance(f, dict)],
        "Values": {"AmountDue": v.get("AmountDue"),
                   "OriginalAmountDue": v.get("OriginalAmountDue"),
                   "RealValue": v.get("RealValue")},
    }


def _sig(years: list[int]) -> str:
    return "S=Unpaid;T=Property;Y=" + ",".join(str(y) for y in years)


def _load_state(years: list[int]) -> dict:
    """Existing state if it is for the same facet window and young enough to resume,
    else a fresh one (and the bills file is truncated, so the two can never disagree)."""
    fresh = {"version": 1, "sig": _sig(years), "started_at": time.time(),
             "updated_at": time.time(), "complete": False, "years": {}}
    try:
        st = json.loads(STATE_PATH.read_text())
        age_h = (time.time() - float(st.get("updated_at", 0))) / 3600.0
        if st.get("version") == 1 and st.get("sig") == fresh["sig"] and age_h <= RESUME_MAX_AGE_H:
            return st
    except (OSError, ValueError, TypeError):
        pass
    try:
        BILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        BILLS_PATH.write_text("")
    except OSError as exc:
        log.warning("rutherford_wildfire.state_reset_failed", error=str(exc)[:120])
    return fresh


def _save_state(st: dict) -> None:
    st["updated_at"] = time.time()
    try:
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(STATE_PATH)
    except OSError as exc:  # never let a full disk kill a sweep that is otherwise working
        log.warning("rutherford_wildfire.state_save_failed", error=str(exc)[:120])


def _append_bills(recs: list[dict]) -> None:
    if not recs:
        return
    try:
        with BILLS_PATH.open("a") as f:
            for r in recs:
                f.write(json.dumps(_slim(r)) + "\n")
    except OSError as exc:
        log.warning("rutherford_wildfire.bills_append_failed", error=str(exc)[:120])


def _load_bills() -> list[dict]:
    out: list[dict] = []
    try:
        with BILLS_PATH.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue  # a torn last line from a killed run
    except OSError:
        pass
    return out


def _state_summary(st: dict) -> dict:
    ys = st.get("years") or {}
    return {"years_done": sum(1 for y in ys.values() if y.get("done")),
            "years_seen": len(ys),
            "reported_bills": sum(int(y.get("total") or 0) for y in ys.values()),
            "fetched_bills": sum(int(y.get("fetched") or 0) for y in ys.values())}


# --------------------------------------------------------------------------- #
# the sweep
# --------------------------------------------------------------------------- #

async def _sweep_year(c, url: str, year: int, st: dict, on_page, budget) -> bool:
    """Page one tax year, resuming at the state's next_skip. Returns True if the year is
    done, False if the page budget ran out first. Every page is saved before the next
    request, so a kill loses at most the page in flight."""
    ys = st["years"].setdefault(str(year), {"total": None, "next_skip": 0, "fetched": 0,
                                            "done": False})
    if ys.get("done"):
        return True
    body = {"value": "", "skip": 0, "facets": _facets([year]), "direct": False}
    token: str | None = None
    remints = 0
    minted = False
    skip = int(ys.get("next_skip") or 0)
    seen: set[str] = set()

    while True:
        if not budget():
            return False
        body["skip"] = skip
        try:
            if token is None and skip > 0 and not minted:
                # Resuming mid-year: the old token is gone. Mint a fresh search context
                # with a page-0 request, then continue at the saved skip.
                minted = True
                first = await _post_page(c, url, {**body, "skip": 0}, None)
                token = first.get("SearchToken") or None
                ys["total"] = int(first.get("TotalRecords") or ys.get("total") or 0)
                await asyncio.sleep(EXTRA_DELAY_S)
            payload = await _post_page(c, url, body, token)
        except PermissionError:
            remints += 1
            if remints > MAX_TOKEN_REMINTS:
                raise RuntimeError(f"search token rejected {remints} times for TY{year}")
            token = None
            first = await _post_page(c, url, {**body, "skip": 0}, None)
            token = first.get("SearchToken") or None
            continue
        token = payload.get("SearchToken") or token
        if ys.get("total") in (None, 0):
            ys["total"] = int(payload.get("TotalRecords") or 0)
        recs = payload.get("Records") or []
        if not recs:
            ys["done"] = True
            _save_state(st)
            break
        keep: list[dict] = []
        for rec in recs:
            key = str(rec.get("IDHash") or rec.get("Bill") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            ys["fetched"] = int(ys.get("fetched") or 0) + 1
            if (rec.get("AbstractType") or "").strip().upper() == "REI":
                keep.append(rec)
        _append_bills(keep)
        skip += PAGE_SIZE
        ys["next_skip"] = skip
        total = int(ys.get("total") or 0)
        if total and skip >= total:
            ys["done"] = True
        _save_state(st)
        on_page(len(keep))
        if ys["done"]:
            break
        await asyncio.sleep(EXTRA_DELAY_S)

    fetched, total = int(ys.get("fetched") or 0), int(ys.get("total") or 0)
    if total and fetched < total * SHORTFALL_WARN:
        log.warning("rutherford_wildfire.year_short", year=year, reported=total, fetched=fetched)
    log.info("rutherford_wildfire.year", year=year, total=total, fetched=fetched)
    return True


class RutherfordWildfireDelinquent(BaseScraper):
    slug = SLUG
    name = "Rutherford NC delinquent tax bills (Sturgis Wildfire API)"
    category = "county_tax"
    #: Zero is a real outcome (a wall, an outage), so never flag it as a regression.
    expected_min_count = 0
    requires_apify = False
    #: ~1,400 polite pages (~27.8k bills / 20) at ~1.4 s each is ~33 minutes; the sweep
    #: is resumable and its partial rows are shipped, so a shorter budget only defers work.
    timeout_s = float(os.environ.get("RUTHERFORD_WILDFIRE_TIMEOUT_S", "3000"))

    #: Set by ``apply_row_limit`` (scoped/dry runs) or RUTHERFORD_WILDFIRE_MAX_PAGES_TOTAL.
    max_pages_total: int | None = (
        int(os.environ["RUTHERFORD_WILDFIRE_MAX_PAGES_TOTAL"])
        if os.environ.get("RUTHERFORD_WILDFIRE_MAX_PAGES_TOTAL") else None)

    def apply_row_limit(self, n: int) -> None:
        """Cap the sweep at roughly ``n`` parcel leads. About 45% of a page's 20 bills are
        real estate and a parcel averages ~1.5 bills, so ~6 leads per page."""
        self.max_pages_total = max(1, math.ceil(max(1, n) / 6))

    async def fetch(self) -> Iterable[Listing]:
        years = _delinquent_years()
        st = _load_state(years)

        # Cache: a COMPLETE sweep younger than CACHE_MAX_AGE_H needs no requests at all.
        age_h = (time.time() - float(st.get("updated_at", 0))) / 3600.0
        if st.get("complete") and age_h <= CACHE_MAX_AGE_H:
            out = _records_to_listings(_load_bills(), f"{DEFAULT_API_HOST}/data/{DEFAULT_CLIENT_ID}"
                                       "/Wildfire/Records", self.slug)
            log.info("rutherford_wildfire.cache_hit", age_h=round(age_h, 1), listings=len(out))
            return out

        api_host, client_id = DEFAULT_API_HOST, DEFAULT_CLIENT_ID
        try:
            html = await get_text(TAX_SEARCH_URL, timeout=45.0)
            api_host, client_id = _discover_endpoint(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_wildfire.shell_fetch_failed", error=str(exc)[:160])

        path = f"/data/{client_id}/Wildfire/Records"
        url = api_host.rstrip("/") + path

        if _robots_strict() and await _robots_blocks(api_host, path):
            # Old behaviour, only under ROBOTS_STRICT=1: the host publishes `Disallow: /`.
            log.info("rutherford_wildfire.robots_skip", host=api_host, path=path)
            return []

        pages = {"n": 0, "real": 0}
        rolled_at = {"n": 0}

        def budget() -> bool:
            return self.max_pages_total is None or pages["n"] < self.max_pages_total

        def rollup() -> list[Listing]:
            return _records_to_listings(_load_bills(), url, self.slug)

        def on_page(n_real: int) -> None:
            pages["n"] += 1
            pages["real"] += n_real
            # Keep BaseScraper.partial current so a soft timeout ships the sweep so far.
            if pages["n"] - rolled_at["n"] >= 25:
                rolled_at["n"] = pages["n"]
                self.partial = rollup()

        walled: str | None = None
        all_done = True
        try:
            async with client(timeout=90.0) as c:
                for year in years:
                    try:
                        done = await _sweep_year(c, url, year, st, on_page, budget)
                    except WildfireWall as exc:
                        walled = str(exc)
                        all_done = False
                        break
                    except (WildfireNotJson, RuntimeError, OSError) as exc:
                        # One bad year must not lose the others, but it must be loud.
                        log.error("rutherford_wildfire.year_failed", year=year,
                                  error=str(exc)[:200])
                        all_done = False
                        continue
                    if not done:
                        all_done = False
                        break
        except asyncio.CancelledError:
            # Soft timeout: state is already on disk; publish what we have.
            self.partial = rollup()
            raise

        st["complete"] = bool(all_done and not walled
                              and all(st["years"].get(str(y), {}).get("done") for y in years))
        _save_state(st)
        out = rollup()
        self.partial = out
        log.info("rutherford_wildfire.done", pages=pages["n"], complete=st["complete"],
                 walled=walled, distinct_parcels=len(out), **_state_summary(st),
                 total_owed=round(sum(li.judgment_amount or 0.0 for li in out), 2))
        if walled and not out:
            # Nothing usable and the site said stop: report BLOCKED, not "empty".
            import httpx
            raise httpx.HTTPStatusError(f"wildfire wall: {walled}",
                                        request=httpx.Request("POST", url),
                                        response=httpx.Response(403))
        return out
