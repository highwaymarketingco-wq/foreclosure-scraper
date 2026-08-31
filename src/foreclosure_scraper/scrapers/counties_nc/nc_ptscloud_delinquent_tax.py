"""NC PTS Cloud (Farragut "BillPWA") countywide delinquent-tax roll — the full
NCGS 105-369 delinquent list for the counties on the bcpwa.ncptscloud.com
cluster (FREE, unauthenticated JSON+CSV API).

Several small W-NC counties run their tax billing on Farragut's NC Property Tax
System cloud. Each exposes an UNauthenticated "taxpayer downloads" endpoint that
hands you a full delinquent-extract CSV — owner, parcel, amount owed, assessed
value, mailing address, tax year — i.e. the entire 105-369 universe, not just
the tiny foreclosure-sale subset. This is the structured-API sibling of
buncombe_delinquent_tax.py (which parses Buncombe's PDF).

Flow (all plain GETs, no login/CAPTCHA; live-verified 2026-06-30):
  1. GET /api/GetTaxpayerDownloadList          (header X-Tenant: <County>)
        -> [{blobName, fileSize, fileDate}]  — pick the "Delinquent" blob
  2. GET /api/DownloadTaxpayerDownloadBlob?fileName=<blob>  (X-Tenant)
        -> {downloadUrl: <short-lived Azure SAS>, expiresAt}
  3. GET downloadUrl  (encode literal spaces in the PATH only; leave the signed
        query untouched or the SAS signature fails) -> the CSV.

Keep only BILL_TYPE=REI (real-estate) rows — IND (vehicle/personal) and BUS
(business personal property) aren't real property. Dedupe multi-year rows by
parcel, summing the amount owed. Amount is back-tax OWED -> raw (normalized to
raw['tax_owed'] by enrichment_tax_owed); assessed value + mailing address are
kept in raw for valuation/skip-trace. Situs isn't in the file — parcel_id backfills
the address via NC OneMap/GIS. Gate off with FORECLOSURE_NC_PTSCLOUD=0.
"""
from __future__ import annotations

import csv
import io
import os
import re
import urllib.parse
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...layer_guard import LayerHarvest
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://bcpwa.ncptscloud.com"
# X-Tenant value -> (County, State). Every tenant on this shared Farragut
# app-gateway host (bcpwa.ncptscloud.com) is probed; the county is selected by
# the X-Tenant header, NOT by a per-county subdomain (the *.ncptscloud.com
# wildcard is a decoy that black-holes to a parking IP). Unknown tenants return
# HTTP 500 and are simply absent below. Tenants WITHOUT a current delinquent
# export just yield 0 (Burke/Rutherford/etc today) and light up automatically
# when their county posts a fresh extract.
#
# Full valid-tenant set was enumerated 2026-07-01 by probing all 100 NC counties
# as X-Tenant against /api/GetTaxpayerDownloadList (200 = valid tenant, 500 =
# not on this cluster). Live delinquent exports verified end-to-end that day for
# Beaufort/Forsyth/Guilford/Henderson/Hyde/Madison/Orange/Pitt. The rest are
# valid tenants standing by with no export blob yet. NB: Cleveland/Gaston/Polk/
# Transylvania are NOT tenants here (they run Government Window / DEVNET Wedge /
# self-hosted tax portals) — do not re-add them.
TENANTS: dict[str, tuple[str, str]] = {
    # verified live exports (2026-07-01)
    "Madison": ("Madison", "NC"),
    "Henderson": ("Henderson", "NC"),
    "Beaufort": ("Beaufort", "NC"),
    "Forsyth": ("Forsyth", "NC"),
    "Guilford": ("Guilford", "NC"),
    "Hyde": ("Hyde", "NC"),
    "Orange": ("Orange", "NC"),
    "Pitt": ("Pitt", "NC"),
    # valid tenants, no live delinquent-export blob yet (auto-light-up)
    "Rutherford": ("Rutherford", "NC"),
    "Burke": ("Burke", "NC"),
    "Cumberland": ("Cumberland", "NC"),
    "Durham": ("Durham", "NC"),
    "Hertford": ("Hertford", "NC"),
    "Mecklenburg": ("Mecklenburg", "NC"),
    "Randolph": ("Randolph", "NC"),
    "Stokes": ("Stokes", "NC"),
    "Wayne": ("Wayne", "NC"),
}


# Data-entry notes that leak into OWNER_NAME on these rolls — strip them so the
# owner-name resolver + skip-trace get a clean name.
_OWNER_NOISE_RE = re.compile(
    r"\s*[;,]?\s*(address\s+is\s+wrong|do\s+not\s+send|return\s+to\s+sender|"
    r"undeliverable|no\s+forward(?:ing)?|bad\s+addr\w*|deceased).*$", re.I)


def _clean_owner(s: str | None) -> str | None:
    s = (s or "").strip().strip(";,").strip()
    s = _OWNER_NOISE_RE.sub("", s).strip().strip(";,").strip()
    return s or None


def _money(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip() or 0)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


# PROP_SIZE comes as e.g. "0.17 AC" / "1.5 AC" / "12.3 ACRES" — pull the leading
# numeric and treat it as acreage. Anything non-numeric (blank, "0", junk) -> None.
_ACRES_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")


def _acres(v) -> float | None:
    m = _ACRES_RE.search(str(v or ""))
    if not m:
        return None
    try:
        f = float(m.group(1))
    except (ValueError, TypeError):
        return None
    return f if f > 0 else None


class TenantExportBroken(RuntimeError):
    """The tenant's export pipeline failed. Distinct from 'published nothing'."""


#: Returned when a tenant answered correctly but publishes no delinquent export
#: right now. Burke, Rutherford and Mecklenburg were all verified live in this
#: state: HTTP 200 with an empty blob list. That is a real answer, not a break.
NO_EXPORT = "no_export"


async def _download_delinquent_csv(c, tenant: str) -> str | None:
    """Run the 3-step BillPWA flow for one tenant.

    Returns CSV text, or None when the tenant simply has no delinquent export
    published today. Raises TenantExportBroken when a step actually fails.

    This used to have five bare ``return None`` exits, so "this county has no
    export this week" and "this county's endpoint is broken" were the same
    value, on the largest source in the board (21,463 rows). Nine of the
    seventeen declared tenants produced no log line at all and there was no way
    to tell which kind of nine they were.
    """
    hdr = {"X-Tenant": tenant, "Accept": "application/json"}
    try:
        r = await c.get(f"{BASE}/api/GetTaxpayerDownloadList", headers=hdr)
    except Exception as exc:  # noqa: BLE001
        raise TenantExportBroken(f"list request failed: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise TenantExportBroken(f"list HTTP {r.status_code}")
    try:
        blobs = r.json()
    except Exception as exc:  # noqa: BLE001
        raise TenantExportBroken("list response is not JSON") from exc

    blob = next((b.get("blobName") for b in blobs
                 if "delinquent" in (b.get("blobName") or "").lower()), None)
    if not blob:
        # Answered cleanly, nothing delinquent published. Legitimate zero.
        return None

    try:
        r2 = await c.get(f"{BASE}/api/DownloadTaxpayerDownloadBlob",
                         params={"fileName": blob}, headers=hdr)
        url = r2.json().get("downloadUrl")
    except Exception as exc:  # noqa: BLE001
        raise TenantExportBroken(f"blob request failed: {type(exc).__name__}") from exc
    if not url:
        raise TenantExportBroken(f"blob {blob!r} returned no downloadUrl")

    # Encode literal spaces in the blob PATH; keep the signed query string intact.
    p = urllib.parse.urlsplit(url)
    dl = urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, p.fragment))
    try:
        r3 = await c.get(dl)
    except Exception as exc:  # noqa: BLE001
        raise TenantExportBroken(f"download failed: {type(exc).__name__}") from exc
    if r3.status_code != 200:
        raise TenantExportBroken(f"download HTTP {r3.status_code}")
    return r3.content.decode("utf-8-sig", errors="replace")


def _parse_csv(text: str, county: str, state: str, tenant: str) -> list[Listing]:
    # Some extracts carry a stray NUL byte inside a field (seen in Pitt's roll),
    # which makes csv.DictReader raise "line contains NUL" and drop the whole
    # county. Strip NULs up front so one bad byte can't nuke thousands of leads.
    if "\x00" in text:
        text = text.replace("\x00", "")
    rows = list(csv.DictReader(io.StringIO(text)))
    # Aggregate REI rows by parcel: sum amount owed across tax years, keep the
    # latest year + the richest owner/assess/mailing snapshot.
    agg: dict[str, dict] = {}
    for r in rows:
        if (r.get("BILL_TYPE") or "").strip().upper() != "REI":
            continue
        parcel = (r.get("PARCEL_NUM") or "").strip()
        if not parcel or parcel.upper().startswith("UNK"):
            continue
        owed = _money(r.get("TOTAL_DUE_AMOUNT"))
        if not owed:
            continue
        a = agg.setdefault(parcel, {"owed": 0.0, "year": "", "row": r})
        a["owed"] += owed
        yr = (r.get("TAX_YEAR") or "").strip()
        if yr >= a["year"]:
            a["year"], a["row"] = yr, r

    out: list[Listing] = []
    now = datetime.utcnow()
    for parcel, a in agg.items():
        r = a["row"]
        owner = _clean_owner(r.get("OWNER_NAME"))
        assessed = _money(r.get("ABSTRACT_ASSESS_VALUE"))
        legal = (r.get("DESCRIPTION") or "").strip() or None
        acreage = _acres(r.get("PROP_SIZE"))
        in_care_of = (r.get("IN_CARE_OF") or "").strip() or None
        # Full mailing street: join ADDR1-3 (some rolls put unit/attn on 2/3) so
        # skip-trace doesn't lose the suite line. Keep the parts too.
        addr_parts = [
            (r.get("MAIL_ADDR1") or "").strip(),
            (r.get("MAIL_ADDR2") or "").strip(),
            (r.get("MAIL_ADDR3") or "").strip(),
        ]
        mail = {
            "addr": ", ".join(p for p in addr_parts if p) or None,
            "addr1": addr_parts[0] or None,
            "addr2": addr_parts[1] or None,
            "addr3": addr_parts[2] or None,
            "city": (r.get("MAIL_CITY") or "").strip() or None,
            "state": (r.get("MAIL_STATE") or "").strip() or None,
            "zip": (r.get("MAIL_ZIP") or "").strip() or None,
            "in_care_of": in_care_of,
        }
        out.append(Listing(
            source="counties_nc.nc_ptscloud_delinquent_tax",
            source_url=f"{BASE}/",
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state=state,
            county=county,
            owner_name=owner,
            defendant=owner,
            parcel_id=parcel,
            legal_description=legal,
            acreage=acreage,
            # The county's assessed value IS a real value (NC assesses ~market) —
            # set it so these leads grade/score without needing GIS. calc caps
            # confidence + data_quality flags it as assessed-basis.
            market_value=assessed if (assessed and 1000 <= assessed <= 20_000_000) else None,
            foreclosure_process="tax",
            description=(f"{owner or ''} — {county} NC delinquent tax "
                         f"${a['owed']:,.0f} owed (parcel {parcel})")[:300],
            first_seen=now,
            last_seen=now,
            raw={
                "nc_ptscloud_delinquent_tax": {
                    "tenant": tenant,
                    "parcel": parcel,
                    # back-tax OWED (summed across years) -> tax_owed, NOT value
                    "principal_tax_due": round(a["owed"], 2),
                    "assessed_value": assessed,
                    "tax_year": a["year"] or None,
                    "owner": owner,
                    "in_care_of": in_care_of,
                    "legal_description": legal,
                    "prop_size": (r.get("PROP_SIZE") or "").strip() or None,
                    "mailing": mail,
                    "bill_number": (r.get("BILL_NUMBER") or "").strip() or None,
                }
            },
        ))
    return out


class NCPtsCloudDelinquentTax(BaseScraper):
    slug = "counties_nc.nc_ptscloud_delinquent_tax"
    name = "NC PTS Cloud Delinquent Tax Roll (Farragut bcpwa cluster, ~17 NC tenants)"
    category = "county_tax"
    expected_min_count = 0  # depends on which tenants have a live export
    # 2026-08-30 fix: the ~17 tenants download SEQUENTIALLY, so the 180s BaseScraper
    # default soft-timeout killed the loop after ~1 tenant (1,155 rows of ~21,506 —
    # the single biggest lead-loss in the system). Give the sequential CSV pulls
    # room to finish; this is the largest source, so it earns a generous budget.
    timeout_s = 1200.0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_NC_PTSCLOUD") == "0":
            return []
        out: list[Listing] = []
        # Every declared tenant must account for itself. A tenant that breaks is
        # now a hard failure the run report shows, instead of 21,463 rows that
        # look fine because nobody has last week's per-county number to compare.
        # LayerHarvest is a SYNC context manager; putting it in the `async with`
        # header raises TypeError at runtime, which is exactly the kind of break
        # a test that only exercises the helpers will not catch.
        # Tenants without a live delinquent export today are tolerated —
        # their connection failures must NOT discard the 20k+ good rows from
        # counties that DID publish. (Cumberland/Durham/Mecklenburg/etc often
        # have intermittent connectivity but no data to lose when they're down.)
        _tolerate = {
            "Rutherford", "Burke", "Cumberland", "Durham", "Hertford",
            "Mecklenburg", "Randolph", "Stokes", "Wayne",
        }
        guard = LayerHarvest(self.slug, list(TENANTS), tolerate=_tolerate)
        # Sequential per tenant — one shared throttled client, gentle on the host.
        async with client(timeout=30.0) as c:
            with guard:
                for tenant, (county, state) in TENANTS.items():
                    out.extend(await guard.harvest(
                        tenant, self._tenant_fetcher(c, tenant, county, state)))
        return out

    @staticmethod
    def _tenant_fetcher(c, tenant: str, county: str, state: str):
        """Zero-arg callable for one tenant, so LayerHarvest can retry it."""
        async def _one() -> list[Listing]:
            text = await _download_delinquent_csv(c, tenant)
            if text is None:
                log.info("nc_ptscloud.tenant_empty", tenant=tenant,
                         county=county, reason=NO_EXPORT)
                return []
            leads = _parse_csv(text, county, state, tenant)
            log.info("nc_ptscloud.tenant_done", tenant=tenant,
                     county=county, leads=len(leads))
            return leads

        return _one
