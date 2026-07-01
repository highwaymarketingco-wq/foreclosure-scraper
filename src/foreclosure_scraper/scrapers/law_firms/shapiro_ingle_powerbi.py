"""Shapiro & Ingle / LOGS — NC foreclosure docket via the public Power BI feed.

Shapiro & Ingle (a LOGS Legal Group firm; successor now trades as The Ingle
Firm) publishes its statewide NC foreclosure-sale docket as a public Power BI
report embedded on:

    https://www.logs.com/nc-upcoming-sales-report.html
      <iframe src="https://app.powerbi.com/view?r=<base64>">

Decoding that ``r=`` param yields the embed descriptor::

    {"k": "10e35a6c-3ceb-4364-84ad-0f6312c3f48e",   # resourceKey
     "t": "dffde94f-72fb-49ae-acb2-0b961abd5b41",   # tenant
     "c": 3}

Rather than render the iframe in a headless browser (the slow path used by
``law_firms.mcmichael_taylor_gray``), we call the SAME undocumented JSON-XHR
API the embed's client uses:

    POST https://wabi-us-north-central-h-primary-api.analysis.windows.net
         /public/reports/querydata?synchronous=true
    header  X-PowerBI-ResourceKey: <resourceKey>
    body    { modelId, queries:[{ Query:{ Commands:[
              SemanticQueryDataShapeCommand ]}}] }

This is a public, anonymous, no-login endpoint — the resourceKey IS the
credential the firm ships in plaintext to every visitor. No CAPTCHA, no WAF
token, no forged auth. The model id (452995) and the source entity
("web Upcoming Sales Report NC") are read live from the report's own
``conceptualschema`` endpoint so a model re-publish doesn't silently break us.

Response shape (Power BI "DSR" / DM0 delta-encoding)
----------------------------------------------------
``results[0].result.data.dsr.DS[0]``:
  * ``ValueDicts``  — {D0:[...], D1:[...], ...} de-duplicated string pools.
  * ``PH[0].DM0``   — the row list. Each row is delta-encoded vs the previous:
      - ``S``  (first row only) — column schema; ``DN`` = which ValueDict a
        column dereferences, absent = literal (epoch-ms date / number).
      - ``C``  — the PRESENT column values, in column order, SKIPPING any
        column suppressed by the repeat (R) or null (Ø) masks.
      - ``R``  — repeat bitmask: bit *i* set ⇒ reuse previous row's column *i*.
      - ``Ø``  (U+00D8) — null bitmask: bit *i* set ⇒ column *i* is null.
    So to rebuild a row you walk columns 0..n-1, consuming C left-to-right only
    for columns not masked by R or Ø. Dict columns map the int through ValueDicts.

Columns (entity ``web Upcoming Sales Report NC``)
-------------------------------------------------
  OFFICE_CODE, CASE_TYPE_NAME, STATUS_NAME, SALE_RESULTS, SALES_DATE (epoch-ms),
  SALE_DATE (display string — carries inline status), CLIENT_CODE, COUNTY_NAME,
  SALE_TIME (ms-of-day), CASE_COURT_NUMB (NC SP case #), FULL_ADDRESS, BID_AMNT.

SALE_DATE inline status
-----------------------
The SALE_DATE display column folds the auction status into the date string:
    "01/05/26"                    -> upcoming as-scheduled
    "01/05/26 Cancelled Until 07/16"   -> cancelled, re-set for 07/16
    "01/06/17 Postponed Until 08/20"   -> postponed to 08/20
We split it: the leading token is the ORIGINAL sale date; the trailing
"<Cancelled|Postponed> Until <mm/dd>" gives auction_status + the new effective
date (year inferred). We surface the effective (postponed-to) date as
``sale_date`` — matching the Ingle-HTML sibling's "prefer postponed" rule —
and keep both in ``raw`` + ``auction_status``.

Why richer than ``law_firms.ingle_firm`` (the HTML table)
---------------------------------------------------------
Same firm, but this feed is the full statewide docket (~880 NC rows vs the HTML
page's short list) and carries STATUS_NAME (ACTIVE/DELAYED), SALE_RESULTS,
CLIENT_CODE (the servicer), a precise SALE_TIME, and the NC SP case number in
one structured pull. We keep only our in-footprint NC counties via
``config.in_scope`` (authoritative allow/deny — no hardcoded list to drift).
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx

from ...base_scraper import BaseScraper
from ...config import in_scope
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

# The LOGS host page carrying the NC embed iframe (source_url on every row).
EMBED_PAGE = "https://www.logs.com/nc-upcoming-sales-report.html"

# Power BI public backend for this tenant's region (from the live report).
WABI_BASE = "https://wabi-us-north-central-h-primary-api.analysis.windows.net"
QUERYDATA_URL = f"{WABI_BASE}/public/reports/querydata?synchronous=true"

# Resource key decoded from the embed's ?r= param (the public credential).
RESOURCE_KEY = "10e35a6c-3ceb-4364-84ad-0f6312c3f48e"

# Fallbacks used only if the live conceptualschema probe fails — verified live
# 2026-07-01. The scraper prefers the values it reads from the model at runtime.
FALLBACK_MODEL_ID = 452995
FALLBACK_ENTITY = "web Upcoming Sales Report NC"

# Column projection we request, in a fixed order. Index positions below assume
# this exact order.
COLUMNS = (
    "OFFICE_CODE",      # 0  always "NC"
    "CASE_TYPE_NAME",   # 1  "Foreclosure"
    "STATUS_NAME",      # 2  ACTIVE | DELAYED
    "SALE_RESULTS",     # 3  None | Cancelled | Postponed
    "SALES_DATE",       # 4  epoch-ms original sale date
    "SALE_DATE",        # 5  display string w/ inline status
    "CLIENT_CODE",      # 6  servicer short code
    "COUNTY_NAME",      # 7
    "SALE_TIME",        # 8  ms-since-midnight
    "CASE_COURT_NUMB",  # 9  NC SP case number
    "FULL_ADDRESS",     # 10 "street, city, North Carolina zip"
    "BID_AMNT",         # 11 float opening/upset bid
)
_C = {name: i for i, name in enumerate(COLUMNS)}

# A ~30k window comfortably covers the ~500–900-row statewide docket in one call.
WINDOW_COUNT = 30_000

_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "X-PowerBI-ResourceKey": RESOURCE_KEY,
    "Origin": "https://app.powerbi.com",
    "Referer": "https://app.powerbi.com/",
}

# "1145 Tarboro Street, Rocky Mount, North Carolina 27801" (state spelled out
# or abbreviated; optional +4).
_ADDR_RE = re.compile(
    r"^(?P<street>.*?),\s*(?P<city>[A-Za-z .'\-]+?),\s+(?:NC|North Carolina),?\s*"
    r"(?P<zip>\d{5})(?:-\d{4})?\s*$",
    re.I,
)

# "01/05/26 Cancelled Until 07/16" / "01/06/17 Postponed Until 08/20".
_STATUS_RE = re.compile(
    r"^(?P<orig>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<kind>Cancelled|Postponed|Continued|Rescheduled|Held|On Hold)\b"
    r"(?:\s+Until\s+(?P<until>\d{1,2}/\d{1,2}(?:/\d{2,4})?))?",
    re.I,
)
_DATE_ONLY_RE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*$")


def decode_embed_resource_key(embed_r: str) -> str | None:
    """Return the ``k`` (resourceKey) from a Power BI ``?r=`` base64 blob."""
    try:
        pad = embed_r + "=" * (-len(embed_r) % 4)
        obj = json.loads(base64.urlsafe_b64decode(pad))
        return obj.get("k")
    except Exception:  # noqa: BLE001
        return None


def _parse_mdY(token: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d"):
        try:
            dt = datetime.strptime(token, fmt)
            if fmt == "%m/%d":  # bare mm/dd — infer the year (next 12 mo window)
                today = datetime.utcnow()
                dt = dt.replace(year=today.year)
                if dt < today - timedelta(days=180):
                    dt = dt.replace(year=today.year + 1)
            return dt
        except ValueError:
            continue
    return None


def _epoch_ms_to_dt(v) -> datetime | None:
    if not isinstance(v, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


def _ms_to_clock(v) -> str | None:
    if not isinstance(v, (int, float)):
        return None
    secs = int(v // 1000)
    h, m = divmod(secs // 60, 60)
    if not (0 <= h < 24):
        return None
    return f"{h:02d}:{m:02d}"


def _money(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v) if v and v > 0 else None
    if isinstance(v, str):
        m = re.search(r"([\d,]+(?:\.\d+)?)", v)
        if m:
            try:
                f = float(m.group(1).replace(",", ""))
                return f if f > 0 else None
            except ValueError:
                return None
    return None


def split_sale_date(display: str | None) -> tuple[datetime | None, datetime | None, str | None]:
    """Split a SALE_DATE display string.

    Returns (original_sale_date, effective_sale_date, auction_status). For a
    plain date the effective == original and status is None. For a
    "<...> Until <mm/dd>" the effective is the postponed/re-set date and status
    is one of active|postponed|cancelled|withdrawn.
    """
    if not display or not display.strip():
        return None, None, None
    s = display.strip()

    m = _DATE_ONLY_RE.match(s)
    if m:
        d = _parse_mdY(m.group(1))
        return d, d, "active"

    m = _STATUS_RE.match(s)
    if m:
        orig = _parse_mdY(m.group("orig"))
        kind = m.group("kind").lower()
        until = m.group("until")
        eff = _parse_mdY(until) if until else None
        # If the "Until" token is a bare mm/dd (no year), anchor its year to the
        # original sale year, rolling forward when it lands before the original.
        if eff is not None and orig is not None and until and until.count("/") == 1:
            eff = eff.replace(year=orig.year)
            if eff < orig:
                eff = eff.replace(year=orig.year + 1)
        status = {
            "cancelled": "cancelled",
            "postponed": "postponed",
            "continued": "postponed",
            "rescheduled": "postponed",
            "held": "withdrawn",
            "on hold": "withdrawn",
        }.get(kind, "postponed")
        # Prefer the effective (postponed/re-set) date as the actionable sale date.
        return orig, (eff or orig), status

    # Unrecognized — try a leading date token, else give up gracefully.
    lead = re.match(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})", s)
    if lead:
        d = _parse_mdY(lead.group(1))
        return d, d, None
    return None, None, None


def decode_dm0(ds0: dict) -> list[dict]:
    """Rebuild the delta-encoded DM0 rows into a list of {column: value} dicts.

    Handles the C (present values) / R (repeat mask) / Ø (null mask) encoding
    and dereferences dict-backed columns through ValueDicts.
    """
    value_dicts: dict = ds0.get("ValueDicts", {}) or {}
    ph = ds0.get("PH") or []
    if not ph:
        return []
    dm0 = ph[0].get("DM0") or []
    if not dm0:
        return []

    schema = dm0[0].get("S")
    if not schema:
        return []
    ncol = len(schema)
    # Per-column ValueDict name (or None for literal date/number columns).
    dict_names = [col.get("DN") for col in schema]
    col_order = [col.get("N") for col in schema]  # ("G0","G1",...) request order

    out: list[dict] = []
    prev: list = [None] * ncol
    for item in dm0:
        r_mask = item.get("R", 0) or 0
        null_mask = item.get("Ø", 0) or 0  # Ø
        present = item.get("C", []) or []
        row = [None] * ncol
        ci = 0
        for i in range(ncol):
            if null_mask & (1 << i):
                row[i] = None
                continue
            if r_mask & (1 << i):
                row[i] = prev[i]
                continue
            if ci >= len(present):
                row[i] = None
                continue
            v = present[ci]
            ci += 1
            dn = dict_names[i]
            if dn is not None and isinstance(v, int):
                pool = value_dicts.get(dn, [])
                row[i] = pool[v] if 0 <= v < len(pool) else v
            else:
                row[i] = v
        prev = row
        # Map back to real column names. The Select order we sent == COLUMNS,
        # and G0..Gn follow that order, so zip positionally.
        out.append({COLUMNS[i]: row[i] for i in range(min(ncol, len(COLUMNS)))})
        _ = col_order  # kept for debugging / future non-positional safety
    return out


def _build_query(model_id: int, entity: str) -> dict:
    src = "s"
    selects = [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": src}},
                "Property": col,
            },
            "Name": f"{entity}.{col}",
        }
        for col in COLUMNS
    ]
    command = {
        "SemanticQueryDataShapeCommand": {
            "Query": {
                "Version": 2,
                "From": [{"Name": src, "Entity": entity, "Type": 0}],
                "Select": selects,
                "OrderBy": [
                    {
                        "Direction": 1,
                        "Expression": {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": src}},
                                "Property": "SALE_DATE",
                            }
                        },
                    }
                ],
            },
            "Binding": {
                "Primary": {"Groupings": [{"Projections": list(range(len(COLUMNS)))}]},
                "DataReduction": {
                    "DataVolume": 4,
                    "Primary": {"Window": {"Count": WINDOW_COUNT}},
                },
                "Version": 1,
            },
            "ExecutionMetricsKind": 1,
        }
    }
    return {
        "version": "1.0.0",
        "queries": [
            {
                "Query": {"Commands": [command]},
                "CacheKey": "",
                "QueryId": "",
                "ApplicationContext": {
                    "DatasetId": "",
                    "Sources": [{"ReportId": "", "VisualId": ""}],
                },
            }
        ],
        "cancelQueries": [],
        "modelId": model_id,
    }


async def _discover_model(c: httpx.AsyncClient) -> tuple[int, str]:
    """Read modelId + the source entity name from the report's own schema.

    Falls back to the live-verified constants if the probe fails, so a transient
    hiccup on the schema endpoint doesn't take the scraper down.
    """
    model_id = FALLBACK_MODEL_ID
    entity = FALLBACK_ENTITY
    url = f"{WABI_BASE}/public/reports/{RESOURCE_KEY}/conceptualschema"
    try:
        r = await c.get(url, headers=_HEADERS)
        if r.status_code == 200:
            js = r.json()
            for sc in js.get("schemas", []):
                mid = sc.get("modelId")
                if isinstance(mid, int):
                    model_id = mid
                for ent in sc.get("schema", {}).get("Entities", []):
                    if ent.get("Private"):
                        continue
                    props = {p.get("Name") for p in ent.get("Properties", [])}
                    # The NC docket entity is the one carrying our real columns.
                    if {"FULL_ADDRESS", "CASE_COURT_NUMB", "SALE_DATE"} <= props:
                        entity = ent.get("Name", entity)
                        break
    except Exception:  # noqa: BLE001
        pass
    return model_id, entity


def _row_to_listing(rec: dict, slug: str) -> Listing | None:
    county = (rec.get("COUNTY_NAME") or "").strip() or None
    if not county or not in_scope(county, "NC"):
        return None

    addr_raw = (rec.get("FULL_ADDRESS") or "").strip()
    street = city = zip_code = None
    if addr_raw:
        m = _ADDR_RE.match(addr_raw)
        if m:
            street = m.group("street").strip()
            city = m.group("city").strip()
            zip_code = m.group("zip")
        else:
            street = addr_raw  # let the downstream address parser try

    case_no = (rec.get("CASE_COURT_NUMB") or "").strip() or None
    if not addr_raw and not case_no:
        return None  # nothing identifying

    orig_dt, eff_dt, inline_status = split_sale_date(rec.get("SALE_DATE"))
    # SALES_DATE is the epoch-ms original date; use it to backstop a missing orig.
    if orig_dt is None:
        orig_dt = _epoch_ms_to_dt(rec.get("SALES_DATE"))
    sale_date = eff_dt or orig_dt

    # Reconcile inline status with the structured SALE_RESULTS column.
    results = (rec.get("SALE_RESULTS") or "").strip().lower() or None
    status = inline_status
    if results in ("cancelled", "canceled"):
        status = "cancelled"
    elif results in ("postponed", "continued"):
        status = "postponed"
    elif status is None:
        status = "active"

    process = "power_of_sale" if (rec.get("CASE_TYPE_NAME") or "").lower().startswith("foreclos") else None

    return Listing(
        source=slug,
        source_url=EMBED_PAGE,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        street_address=street or None,
        city=city,
        zip_code=zip_code,
        sale_date=sale_date,
        sale_time=_ms_to_clock(rec.get("SALE_TIME")),
        opening_bid=_money(rec.get("BID_AMNT")),
        auction_status=status,
        foreclosure_process=process,
        trustee="Shapiro & Ingle, LLP",
        case_number=case_no,
        description=(
            f"Shapiro & Ingle (LOGS) NC trustee sale — {county} County"
            + (f", servicer {rec.get('CLIENT_CODE')}" if rec.get("CLIENT_CODE") else "")
            + (f" [{rec.get('STATUS_NAME')}]" if rec.get("STATUS_NAME") else "")
        ),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "shapiro_ingle_pbi": {
                "sale_date_raw": rec.get("SALE_DATE"),
                "sales_date_ms": rec.get("SALES_DATE"),
                "original_sale_date": orig_dt.isoformat() if orig_dt else None,
                "status_name": rec.get("STATUS_NAME"),
                "sale_results": rec.get("SALE_RESULTS"),
                "client_code": rec.get("CLIENT_CODE"),
                "bid_amnt": rec.get("BID_AMNT"),
                "full_address": addr_raw or None,
            }
        },
    )


class ShapiroInglePowerBI(BaseScraper):
    slug = "law_firms.shapiro_ingle_powerbi"
    name = "Shapiro & Ingle / LOGS (NC Power BI docket)"
    category = "law_firm"
    requires_apify = False
    expected_min_count = 0
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=60.0, follow_redirects=True) as c:
            model_id, entity = await _discover_model(c)
            payload = _build_query(model_id, entity)
            r = await c.post(QUERYDATA_URL, headers=_HEADERS, json=payload)
            r.raise_for_status()
            data = r.json()

        try:
            result = data["results"][0]["result"]["data"]
            ds0 = result["dsr"]["DS"][0]
        except (KeyError, IndexError, TypeError):
            return []

        records = decode_dm0(ds0)
        out: list[Listing] = []
        for rec in records:
            li = _row_to_listing(rec, self.slug)
            if li is not None:
                out.append(li)
        return out
