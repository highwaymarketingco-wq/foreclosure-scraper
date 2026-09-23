"""Spartanburg County SC delinquent real-property tax-sale list (annual PDF).

Spartanburg County (Upstate SC core) publishes its Real Property Tax Sale list
as a free, public, no-login .gov PDF:

    https://www.spartanburgcounty.gov/DocumentCenter/View/11161/Real-Property-Tax-Sale-List-PDF

(also linked from spartanburgcounty.gov/640/2025-Tax-Sale-Info). ~2,172 parcels.
Each parcel is a delinquent-tax distress signal: the owner owes back taxes and
the property heads to the annual tax sale unless redeemed (SC Code 12-51,
~12-month redemption off the sale).

PDF layout (pypdf extract_text collapses each parcel onto a single line):

    ITEM #  MAP #            DELINQUENT TAXPAYER NAME(S)        SITUS / DESCRIPTION
    83239   2-10-00-045.00   ALSBROOKS CARLOS E (LE)           1405 COUNTRY ESTATES RD
    83101   7-16-09-062.00   MEADOWS ALFRED AAA WOFTMAN LLC     512 CRESCENT AVE

Parsing strategy:
  * Each list row is `<item#> <TMS> <name(s) + situs>` on one line. The item#
    and TMS are unambiguous and parse 100%.
  * The MAP # (TMS) is the strongest field -> parcel_id. TMS format is
    N-NN-NN-NNN.NN (e.g. 2-10-00-045.00).
  * Splitting NAME from SITUS: the document interleaves a duplicated
    taxpayer-name column, so the name text is inherently noisy (owner +
    co-owner, sometimes the same name twice). The reliable boundary is the
    SITUS address — we anchor on the last house-number-led street address
    (or a HIGHWAY <n> / street-only fragment) that ends in a known street
    suffix. This recovers situs for ~99.7% of rows. Everything before the
    situs anchor is taken as the best-effort owner_name.

Free public .gov PDF; plain HTTP + pypdf. No login, no CAPTCHA, no paywall.
Live-verified 2026-06-30: PDF fetches (70 pages, ~1.25 MB), 2,172 parcel rows
parse, 2,165 with extracted situs.

2026-09-23 BLOCKED incident: the 2026-09-23 full run logged outcome=BLOCKED
(0 rows) at 15:33:33Z -- classified by base_scraper from a 401/403/406/429/5xx
status or connection-refused signal recorded by http_client's shared
_ThrottledTransport (see base_scraper.OUTCOME_BLOCKED). The host is
www.spartanburgcounty.gov (CivicPlus DocumentCenter, fronted by Cloudflare --
confirmed via the `Server: cloudflare` / `CF-RAY` response headers).
spartanburg_master_in_equity.py hits the SAME host (different DocumentCenter
doc id) and was ALSO newly BLOCKED in the same second (15:33:32Z), while the
4 other Spartanburg scrapers hitting different hosts/services succeeded in
the same window -- confirming a shared, host-specific (not blanket-network)
cause: something tripped a Cloudflare-side rate-limit/WAF rule for
spartanburgcounty.gov specifically.

Live re-verification the same day (2026-09-23, ~1h after the block) with the
UNCHANGED request -- both plain curl and this project's own get_bytes() /
client() code paths -- got a clean HTTP 200 + valid PDF immediately, with no
header or UA changes. That rules out a durable new WAF rule, a UA/header
requirement, or a URL change: the block was a TRANSIENT trip (e.g. a
short-lived Cloudflare rate-limit/managed-challenge window) that had already
cleared. http_client.get_bytes() already retries 401/403/406/429/5xx via
tenacity (stop_after_attempt(3), ~1-10s exponential backoff), but that
~10-20s window evidently didn't outlast whatever this trip's duration was.
fetch() below adds a SCRAPER-LOCAL outer retry with a longer, jittered
cooldown (tens of seconds) between waves so a block that outlasts
http_client's fast internal retry still gets a second and third chance
within this scraper's own soft timeout, before being reported BLOCKED for
real. This is ordinary backoff politeness, not a WAF/CAPTCHA bypass -- if a
future incident turns out to be a genuine login/CAPTCHA wall instead of a
rate-limit, do not extend this pattern to defeat it; flag it instead per
project policy.
"""
from __future__ import annotations

import asyncio
import io
import random
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PDF_URL = (
    "https://www.spartanburgcounty.gov/DocumentCenter/View/11161/"
    "Real-Property-Tax-Sale-List-PDF"
)
INFO_URL = "https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info"

# Spartanburg TMS / MAP #: N-NN-NN-NNN.NN  (e.g. 2-10-00-045.00, 7-16-09-062.00)
TMS_PAT = r"\d-\d{2}-\d{2}-\d{3}\.\d{2}"

# A parcel row: leading 4-6 digit ITEM #, then the TMS, then name(s) + situs.
_ROW_RE = re.compile(rf"^\s*(\d{{4,6}})\s+({TMS_PAT})\s+(.*)$")

# Street-type tokens that legitimately END a situs address. Kept broad so the
# situs anchor catches the Spartanburg variety (HIGHWAY NN, ... LINE, ... ALY,
# rural ... RD/ROAD, subdivision ESTATES/ACRES, etc.).
_STREET_SUFFIXES = (
    "AVE", "AVENUE", "ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE",
    "CT", "COURT", "BLVD", "BOULEVARD", "HWY", "HIGHWAY", "PL", "PLACE", "CIR",
    "CIRCLE", "TRL", "TRAIL", "PKWY", "PARKWAY", "TER", "TERRACE", "WAY", "XING",
    "CROSSING", "RUN", "PT", "POINT", "RDG", "RIDGE", "LOOP", "PASS", "PATH",
    "ROW", "CV", "COVE", "BEND", "PIKE", "HTS", "HEIGHTS", "SQ", "PLZ", "PLAZA",
    "CONN", "SPUR", "WALK", "MNR", "MANOR", "TRCE", "TRACE", "GLN", "GLEN",
    "GRV", "GROVE", "EXT", "EXTENSION", "CRES", "CREEK", "HALL", "PARK", "HILL",
    "LINE", "ALY", "ALLEY", "ACRES", "ESTATES", "FARM", "MILL", "SPRINGS",
    "SHORES", "ISLAND", "BRANCH", "FORD", "GAP", "KNOLL", "BLF", "BLUFF", "VW",
    "VIEW", "MEADOWS", "COMMONS", "LANDING", "CHASE", "CROSS", "CORNER",
    "DOWNS", "WOODS",
)
_SUF_RE = "(?:" + "|".join(sorted(set(_STREET_SUFFIXES), key=len, reverse=True)) + ")"

# (A) house-number-led address ending at a street suffix (optional dir / EXT tail).
_HOUSE_RE = re.compile(
    rf"(\d+\s+(?:[A-Z0-9][A-Z0-9.'/&-]*\s+){{0,6}}{_SUF_RE}(?:\s+(?:W|E|N|S|EXT))?)\b"
)
# (B) numbered highway:  <house#> HIGHWAY <route#>   (e.g. 9641 HIGHWAY 9)
_HWY_NUM_RE = re.compile(r"(\d+\s+(?:HWY|HIGHWAY)\s+\d+[A-Z]?(?:\s+[WENS])?)\b")
# (B2) trailing un-numbered highway:  HIGHWAY 92
_HWY_TAIL_RE = re.compile(r"((?:HWY|HIGHWAY)\s+\d+[A-Z]?(?:\s+[WENS])?)\s*$")
# (C) street-only situs (no house number): trailing words ending in a suffix.
_STREET_ONLY_RE = re.compile(rf"((?:[A-Z0-9][A-Z0-9.'/&-]*\s+){{0,4}}{_SUF_RE})\s*$")


def split_name_situs(rest: str) -> tuple[str | None, str | None]:
    """Split the trailing `name(s) + situs` blob into (owner_name, situs).

    Anchors on the situs address: the LAST house-number-led street address
    (or numbered highway). Falls back to a trailing street-only fragment.
    Everything before the situs anchor is the best-effort owner name."""
    anchors = []
    last_house = None
    for m in _HOUSE_RE.finditer(rest):
        last_house = m
    if last_house:
        anchors.append(last_house)
    last_hwy = None
    for m in _HWY_NUM_RE.finditer(rest):
        last_hwy = m
    if last_hwy:
        anchors.append(last_hwy)
    if anchors:
        a = max(anchors, key=lambda m: m.start())
        return (rest[: a.start()].strip() or None), rest[a.start():].strip()

    m = _HWY_TAIL_RE.search(rest)
    if m:
        return (rest[: m.start()].strip() or None), m.group(1).strip()
    m = _STREET_ONLY_RE.search(rest)
    if m:
        return (rest[: m.start()].strip() or None), m.group(1).strip()
    return (rest.strip() or None), None


def _pdf_text(data: bytes) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:  # noqa: BLE001
        log.warning("spartanburg_delinquent.pdf_parse_fail", error=str(exc)[:160])
        return ""


def parse_list(text: str, url: str) -> list[Listing]:
    """Parse the tax-sale list PDF text into one Listing per delinquent parcel."""
    out: list[Listing] = []
    seen: set[str] = set()
    year = datetime.utcnow().year
    redemption = datetime(year, 12, 31)  # ~12-mo SC redemption off the Dec sale
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s{2,}", " ", raw_line.strip())
        m = _ROW_RE.match(line)
        if not m:
            continue
        item_no, tms, rest = m.group(1), m.group(2), m.group(3).strip()
        name, situs = split_name_situs(rest)
        key = f"{tms}|{item_no}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Listing(
                source="counties_sc.spartanburg_delinquent_tax",
                source_url=url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Spartanburg",
                street_address=situs,
                owner_name=name,
                defendant=name,
                parcel_id=tms,
                redemption_deadline=redemption,
                foreclosure_process="tax",
                description=re.sub(r"\s+", " ", line)[:300],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "spartanburg_delinquent_tax": {
                        "item_no": item_no,
                        "tms": tms,
                        "row": line[:200],
                    }
                },
            )
        )
    return out


# Outer retry: rides out a transient host-level block (Cloudflare rate-limit/
# WAF trip) that outlasts http_client.get_bytes()'s own fast internal retry
# (~3 attempts / ~10-20s). Backoff is deliberately much longer and jittered so
# repeated waves don't look like a hammering loop. Not a CAPTCHA/WAF bypass --
# just spacing out ordinary polite re-fetches of a free public PDF.
_MAX_FETCH_ATTEMPTS = 3
_BACKOFF_BASE_S = 20.0
_BACKOFF_STEP_S = 15.0
_BACKOFF_JITTER_S = 10.0


class SpartanburgDelinquentTax(BaseScraper):
    slug = "counties_sc.spartanburg_delinquent_tax"
    name = "Spartanburg County (SC) Delinquent Real-Property Tax Sale List (PDF)"
    category = "county_tax"
    # Bumped 120 -> 180 (matches spartanburg_condemned/spartanburg_vacant) to
    # give the outer retry/backoff below genuine room within the soft timeout;
    # safe_run's asyncio.wait_for still hard-bounds this source regardless, so
    # it cannot hang the rest of a run even in a worst-case full timeout.
    timeout_s = 180.0
    expected_min_count = 1

    async def fetch(self) -> Iterable[Listing]:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
            last_exc = None
            try:
                data = await get_bytes(PDF_URL, timeout=60.0)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            else:
                if data and data[:4] == b"%PDF":
                    rows = parse_list(_pdf_text(data), PDF_URL)
                    log.info(
                        "spartanburg_delinquent.done", count=len(rows), attempt=attempt
                    )
                    return rows
                # 200 OK but not a PDF (e.g. an HTML challenge/error page some
                # WAFs return with a 2xx status) -- treat like a transient miss
                # and retry rather than silently reporting a clean zero.
                log.info("spartanburg_delinquent.not_pdf", attempt=attempt)

            if attempt < _MAX_FETCH_ATTEMPTS:
                backoff = (
                    _BACKOFF_BASE_S
                    + _BACKOFF_STEP_S * (attempt - 1)
                    + random.uniform(0, _BACKOFF_JITTER_S)
                )
                log.warning(
                    "spartanburg_delinquent.fetch_retry",
                    attempt=attempt,
                    error=str(last_exc)[:160] if last_exc else "not_pdf",
                    backoff_s=round(backoff, 1),
                )
                await asyncio.sleep(backoff)

        if last_exc is not None:
            log.warning("spartanburg_delinquent.fetch_fail", error=str(last_exc)[:160])
        else:
            log.info("spartanburg_delinquent.fetch_fail_not_pdf")
        return []
