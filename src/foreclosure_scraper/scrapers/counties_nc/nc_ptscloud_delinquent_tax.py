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

# PARCEL_NUM is usually a Farragut-internal sequence number that genuinely stays
# stable for ONE physical property across tax years (live-verified: Madison's
# "183" ties 14 years of bills to the same owner + the same embedded PIN). But
# at least one tenant exports a literal "0" for any bill whose internal parcel
# link was never backfilled -- not a real parcel number (no property's parcel
# id is zero) -- and live-pulling Hyde's current export found 532 DISTINCT
# properties (different owners, different legal descriptions) sharing that one
# value. The old code used PARCEL_NUM as both the aggregation key AND the
# published parcel_id, so those 532 real delinquent-tax leads were silently
# collapsing into a single Listing (531 destroyed, not just a dropped field).
# DESCRIPTION is the field that actually stays per-property and stable across
# years on these rows (live-verified: the same owner+description recurs across
# up to 13 tax years for one real Hyde parcel), so it stands in for identity
# whenever PARCEL_NUM is this placeholder.
_PLACEHOLDER_PARCELS = {"0"}

# "PIN: 09706955900" embedded in DESCRIPTION is the real county GIS parcel
# identifier -- far more useful for cross-source parcel matching than
# Farragut's own internal sequence number -- so prefer it for the PUBLISHED
# parcel_id whenever it is present, on every row, not only placeholder ones.
_PIN_IN_DESC_RE = re.compile(r"\bPIN:\s*([0-9]{5,20})\b", re.I)


def _row_identity(parcel: str, description: str) -> tuple[str, str]:
    """(aggregation_key, parcel_id_to_publish) for one delinquent-tax row.

    aggregation_key is what multi-year bills on the same real property are
    summed under. parcel_id_to_publish is what reaches the Listing. A real,
    non-placeholder PARCEL_NUM is kept as the aggregation key (it already
    correctly ties multi-year bills together -- do not disturb working
    behavior), but a cleaner embedded GIS PIN is still preferred for display
    when one exists. A placeholder PARCEL_NUM falls back to DESCRIPTION (or
    the embedded PIN, when the placeholder row happens to carry one) for BOTH,
    so distinct properties stop colliding.
    """
    pin_m = _PIN_IN_DESC_RE.search(description or "")
    pin = pin_m.group(1) if pin_m else None
    if parcel in _PLACEHOLDER_PARCELS:
        desc_key = (description or "").strip()
        key = pin or desc_key or parcel
        return key, (pin or desc_key or parcel)
    return parcel, (pin or parcel)


def _acres(v) -> float | None:
    m = _ACRES_RE.search(str(v or ""))
    if not m:
        return None
    try:
        f = float(m.group(1))
    except (ValueError, TypeError):
        return None
    return f if f > 0 else None


# FLAGS is a free-text, comma-joined column every row already carries but
# nothing ever read -- live-verified 2026-10-03 across 7 tenants (Henderson,
# Guilford, Forsyth, Orange, Pitt, Hyde, Madison, Beaufort), each with its own
# vocabulary beyond plain "DLQ": FORECLOSURE (Guilford 6,907+, Beaufort
# 4,300+ rows -- the county's own in-foreclosure flag, same concept
# nc_its_public_tax.py already surfaces as raw['tax_sale_status']=
# "in_foreclosure"), BANKRUPTCY (Hyde), ADVERTISED (the NCGS 105-369
# tax-lien advertisement, matching rutherford_wildfire_tax's own flag),
# OWNERSHIP TRANSFER, judgement/Judgement Filed, FINAL NOTICE, HARDSHIP PAY
# PLAN, REJECTED FORECLOSURE (must NOT count as foreclosure=True), and
# several USPS return-mail reason codes (RM-NOT DELIVERABLE, RM-VACANT
# PROPERTY, RM-ATTMPTD NOT KNOWN, RM-FWD. TIME EXPIRED / "MAIL RETURNED") --
# a direct, structured "this owner's mail is bouncing" signal, worth far
# more than the free-text noise-stripping _OWNER_NOISE_RE already does.
# Henderson alone: 142/2,120 REI rows ownership-transferred, 37 undeliverable
# mail, 34 with a judgment filed, 8 flagged vacant by the postal system.
def _flags_summary(flags_raw: str) -> dict:
    tokens = [t.strip() for t in (flags_raw or "").split(",") if t.strip()]
    joined = " | ".join(t.upper() for t in tokens)
    def has(sub: str) -> bool:
        return sub in joined
    rejected_fcl = has("REJECTED") and has("FORECLOSURE")
    return {
        "raw": flags_raw or None,
        "tokens": tokens or None,
        "in_foreclosure": has("FORECLOSURE") and not rejected_fcl,
        "foreclosure_rejected": rejected_fcl,
        "bankruptcy_mentioned": has("BANKRUPTCY"),
        "advertised": has("ADVERTISED"),
        "final_notice": has("FINAL NOTICE"),
        "ownership_transfer": has("OWNERSHIP TRANSFER"),
        "judgment_filed": has("JUDGEMENT FILED") or has("JUDGMENT FILED"),
        "mail_undeliverable": (has("NOT DELIVERABLE") or has("MAIL RETURNED")
                               or has("ATTMPTD NOT KNOWN") or has("TIME EXPIRED")
                               or has("RM-")),
        "vacant_property_flag": has("VACANT PROPERTY"),
        "hardship_plan": has("HARDSHIP"),
        "retired_parcel": has("RETIRED PARCEL"),
    }


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


def _bill_entry(r: dict, owed: float) -> dict:
    """One delinquent bill (one tax year) of a parcel, as the roll states it."""
    return {
        "tax_year": (r.get("TAX_YEAR") or "").strip() or None,
        "bill_number": (r.get("BILL_NUMBER") or "").strip() or None,
        "bill_amount": _money(r.get("BILL_AMOUNT")),
        "bill_due_amt": _money(r.get("BILL_DUE_AMT")),
        "interest_due": _money(r.get("INTEREST_DUE")),
        "total_due": round(owed, 2),
        "bill_status": (r.get("BILL_STATUS") or "").strip() or None,
        "bill_due_date": (r.get("BILL_DUE_DATE") or "").strip() or None,
    }


def _year_summary(by_year: list[dict], bill_due_amt: float) -> dict:
    """years_unpaid / years_delinquent / oldest_year / by_year for the raw block.

    years_unpaid and years_delinquent use the key names enrichment_tax_owed already
    promotes into raw['tax_owed'] (_YEARS_LIST_KEYS / _YEARS_DELINQUENT_KEYS), so the
    depth reaches the normalized tax block without a new reader."""
    years = sorted({b["tax_year"] for b in by_year if b.get("tax_year")})
    return {
        "years_unpaid": years or None,
        "years_delinquent": len(years) or None,
        "oldest_year": years[0] if years else None,
        # BILL_DUE_AMT summed: the unpaid tax itself, without the interest that
        # TOTAL_DUE_AMOUNT (principal_tax_due above) folds in.
        "unpaid_bill_amount": round(bill_due_amt, 2) if bill_due_amt else None,
        "by_year": sorted(by_year, key=lambda b: b.get("tax_year") or "", reverse=True),
    }


def _parse_csv(text: str, county: str, state: str, tenant: str) -> list[Listing]:
    # Some extracts carry a stray NUL byte inside a field (seen in Pitt's roll),
    # which makes csv.DictReader raise "line contains NUL" and drop the whole
    # county. Strip NULs up front so one bad byte can't nuke thousands of leads.
    if "\x00" in text:
        text = text.replace("\x00", "")
    rows = list(csv.DictReader(io.StringIO(text)))
    # Aggregate REI rows by parcel identity: sum amount owed across tax years,
    # keep the latest year + the richest owner/assess/mailing snapshot. The
    # identity key is NOT always the raw PARCEL_NUM -- see _row_identity.
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
        description_raw = (r.get("DESCRIPTION") or "").strip()
        identity_key, parcel_id = _row_identity(parcel, description_raw)
        if not identity_key:
            continue
        a = agg.setdefault(identity_key, {"owed": 0.0, "year": "", "row": r,
                                           "parcel_id": parcel_id, "parcel_raw": parcel,
                                           "interest_due": 0.0, "bill_amount": 0.0,
                                           "bill_due_amt": 0.0, "by_year": [],
                                           "flags_seen": []})
        a["owed"] += owed
        # Per-bill history (2026-10-07 extraction audit). The aggregation below keeps
        # only the newest year's row, so a parcel owing 2019-2025 used to publish as
        # "tax_year 2025" with one summed amount: the multi-year depth (the strongest
        # tax-distress signal on this roll) was read and thrown away.
        a["by_year"].append(_bill_entry(r, owed))
        a["bill_due_amt"] += _money(r.get("BILL_DUE_AMT")) or 0.0
        a["interest_due"] += _money(r.get("INTEREST_DUE")) or 0.0
        a["bill_amount"] += _money(r.get("BILL_AMOUNT")) or 0.0
        flags_this_row = (r.get("FLAGS") or "").strip()
        if flags_this_row and flags_this_row not in a["flags_seen"]:
            a["flags_seen"].append(flags_this_row)
        yr = (r.get("TAX_YEAR") or "").strip()
        if yr >= a["year"]:
            a["year"], a["row"], a["parcel_id"], a["parcel_raw"] = yr, r, parcel_id, parcel

    out: list[Listing] = []
    now = datetime.utcnow()
    for _identity_key, a in agg.items():
        r = a["row"]
        parcel = a["parcel_id"]
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
        # FLAGS across every aggregated year/bill for this parcel, unioned
        # (a parcel can pick up FORECLOSURE on a later year's bill even if an
        # earlier year's row -- the one `a["row"]` keeps as representative --
        # only said plain "DLQ"). See _flags_summary's docstring.
        flags = _flags_summary(" | ".join(a["flags_seen"]))
        taxable_value = _money(r.get("ABSTRACT_TAXABLE_VALUE"))
        due_date = (r.get("BILL_DUE_DATE") or "").strip() or None
        bits = [owner or "", f"{county} NC delinquent tax ${a['owed']:,.0f} owed (parcel {parcel})"]
        description = " — ".join(b for b in bits if b)
        if flags["in_foreclosure"]:
            description = "ACTIVE TAX FORECLOSURE — " + description
        elif flags["bankruptcy_mentioned"]:
            description = "BANKRUPTCY FLAG — " + description
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
            description=description[:300],
            first_seen=now,
            last_seen=now,
            raw={
                "nc_ptscloud_delinquent_tax": {
                    "tenant": tenant,
                    "parcel": parcel,
                    # raw Farragut PARCEL_NUM before the placeholder/PIN substitution
                    # above -- kept for provenance even when `parcel` differs from it.
                    "parcel_raw": a.get("parcel_raw"),
                    # back-tax OWED (summed across years) -> tax_owed, NOT value
                    "principal_tax_due": round(a["owed"], 2),
                    # interest accrued + original tax, summed across the same
                    # aggregated years as principal_tax_due -- TOTAL_DUE_AMOUNT
                    # was always principal+interest conflated into one number.
                    "interest_due": round(a["interest_due"], 2) if a["interest_due"] else None,
                    "original_bill_amount": round(a["bill_amount"], 2) if a["bill_amount"] else None,
                    "assessed_value": assessed,
                    "taxable_value": taxable_value,
                    "bill_due_date": due_date,
                    "tax_year": a["year"] or None,
                    "owner": owner,
                    "in_care_of": in_care_of,
                    "legal_description": legal,
                    "prop_size": (r.get("PROP_SIZE") or "").strip() or None,
                    "mailing": mail,
                    "bill_number": (r.get("BILL_NUMBER") or "").strip() or None,
                    "flags": flags,
                    **_year_summary(a["by_year"], a["bill_due_amt"]),
                },
                # Same key + value nc_its_public_tax.py already publishes for
                # the identical concept (the county's own in-rem foreclosure
                # flag) -- one canonical name across sources, see
                # _flags_summary's docstring.
                **({"tax_sale_status": "in_foreclosure"} if flags["in_foreclosure"] else {}),
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
        # Bank rows as they are collected: if the soft timeout fires,
        # base_scraper ships self.partial instead of discarding the run.
        out = self.partial
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
