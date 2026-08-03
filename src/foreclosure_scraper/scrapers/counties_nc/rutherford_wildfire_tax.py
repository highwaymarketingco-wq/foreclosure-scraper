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
``take``/``size``/``limit`` in the body are ignored.

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

COMPLIANCE — ROBOTS WALL, GATED OFF BY DEFAULT
----------------------------------------------
Both hosts that serve this API publish::

    User-agent: *
    Disallow: /

That is ``d1ebsyxxbc7tep.cloudfront.net`` (the CDN the SPA actually calls) and
``avalon.sturgiswebservices.com`` (its origin, which serves the identical API).
Under this project's compliance line — render an OPEN, robots-ALLOWED page's own
JS; never ride a CAPTCHA / login / WAF / robots-ban — a blanket ``Disallow: /``
is a machine-readable no-automation directive, so this source is WALLED even
though it is free, unauthenticated and returns HTTP 200. Same posture, same
guard shape as ``rod/kofile.py``.

So ``fetch()`` runs a robots preflight that FAILS CLOSED and short-circuits to
``[]``. That is a compliant no-op, not a scraper bug. Two ways it turns on:

  * the vendor relaxes robots (drop the ``Disallow``, or add an ``Allow: /data/``)
    — the guard notices on the next run and the source lights up for free; or
There is deliberately NO override switch. An env flag that skips a machine-
readable ``Disallow: /`` is a bypass with a config file in front of it, so it was
removed rather than shipped defaulted-off. If this data is wanted before the
vendor relaxes robots, the route is to ask Rutherford County or the vendor for
access, not to flip a flag.

Because of the wall the full sweep has never been run: 29,319 is the server's
own ``TotalRecords`` for the delinquent filter, read from the facet response
during verification — it is not a harvested count.

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

Dateless: a delinquent bill has no sale date, so this slug must be added to
``main.DATELESS_OK_SOURCES`` before it can land anything. Inert while the robots
wall stands (the source returns 0 either way), required the moment it lifts::

    "counties_nc.rutherford_wildfire_tax",       # Rutherford Sturgis Wildfire delinquent bills (dateless)

The module is named ``…_wildfire_tax`` on purpose: ``enrichment_tax_owed``
recognises a delinquent-amount source by a "tax"/"lien"/"delinquent" substring
in the slug, and without one ``raw['amount_owed']`` would never normalize into
``raw['tax_owed']``.
"""
from __future__ import annotations

import datetime
import json
import os
import re
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
        year = rec.get("BillYear")
        a = agg.setdefault(parcel, {
            "owed": 0.0, "years": set(), "bills": [], "flags": set(),
            "newest": None, "newest_year": -1,
        })
        a["owed"] += owed
        if isinstance(year, int):
            a["years"].add(year)
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
                "bill_numbers": sorted(set(a["bills"]))[:10],
                "bill_count": len(a["bills"]),
                "flags": flags,
                "advertised": advertised,
                "outside_law_firm": outside_firm,
                "delinquent_flag": any(_FLAG_DELINQUENT in f for f in flags),
                "owner_mailing": _mailing(rec),
                "situs_raw": situs_raw,
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


async def _fetch_year(c, url: str, year: int) -> list[dict]:
    """Page one tax year to exhaustion. Page 1 mints the SearchToken; every
    later page must echo it or the server answers 401."""
    body = {"value": "", "skip": 0, "facets": _facets([year]), "direct": False}
    token: str | None = None
    total: int | None = None
    seen: set[str] = set()
    out: list[dict] = []

    for page in range(MAX_PAGES_PER_YEAR):
        body["skip"] = page * PAGE_SIZE
        headers = {"Content-Type": "application/json"}
        if token:
            headers["SearchToken"] = token
        r = await c.post(url, content=json.dumps(body), headers=headers)
        if r.status_code != 200:
            log.warning("rutherford_wildfire.http", year=year, page=page,
                        status=r.status_code)
            break
        try:
            payload = r.json()
        except Exception:  # noqa: BLE001
            log.warning("rutherford_wildfire.bad_json", year=year, page=page)
            break
        token = payload.get("SearchToken") or token
        if total is None:
            total = int(payload.get("TotalRecords") or 0)
        recs = payload.get("Records") or []
        if not recs:
            break
        # skip-paging on one search context: dedupe defensively so a repeated
        # window can never double-count an amount owed.
        fresh = 0
        for rec in recs:
            key = str(rec.get("IDHash") or rec.get("Bill") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(rec)
            fresh += 1
        if fresh == 0:
            break
        if total is not None and (page + 1) * PAGE_SIZE >= total:
            break

    log.info("rutherford_wildfire.year", year=year, total=total, rows=len(out))
    return out


class RutherfordWildfireDelinquent(BaseScraper):
    slug = SLUG
    name = "Rutherford NC delinquent tax bills (Sturgis Wildfire API)"
    category = "county_tax"
    #: Robots-walled by default -> a compliant 0. Never flag that as a
    #: regression.
    expected_min_count = 0
    requires_apify = False
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        api_host, client_id = DEFAULT_API_HOST, DEFAULT_CLIENT_ID
        try:
            html = await get_text(TAX_SEARCH_URL, timeout=45.0)
            api_host, client_id = _discover_endpoint(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_wildfire.shell_fetch_failed",
                        error=str(exc)[:160])

        path = f"/data/{client_id}/Wildfire/Records"
        url = api_host.rstrip("/") + path

        if await _robots_blocks(api_host, path):
            # Compliant no-op: the API host publishes `Disallow: /`. See the
            # module docstring — this is a wall, not a bug.
            log.info("rutherford_wildfire.robots_skip", host=api_host, path=path)
            return []

        years = _delinquent_years()
        records: list[dict] = []
        async with client(timeout=90.0) as c:
            for year in years:
                try:
                    records.extend(await _fetch_year(c, url, year))
                except Exception as exc:  # noqa: BLE001
                    log.warning("rutherford_wildfire.year_failed",
                                year=year, error=str(exc)[:160])

        out = _records_to_listings(records, url, self.slug)
        log.info("rutherford_wildfire.done", raw_records=len(records),
                 listings=len(out),
                 total_owed=round(sum(li.judgment_amount or 0.0 for li in out), 2))
        return out
