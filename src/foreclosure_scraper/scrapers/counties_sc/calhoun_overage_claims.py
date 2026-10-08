"""Calhoun County SC — Tax Sale Overage Claim Lists.

Calhoun County publishes YEARLY tax-sale surplus rosters, same mechanism as
counties_sc.orangeburg_overage_claims / counties_sc.york_overage_claims /
counties_sc.laurens_overage_claims / counties_sc.fairfield_overage_claims:
when a delinquent parcel sells at auction for MORE than the taxes owed, the
excess ("overage") is owed back to the FORMER owner.

  https://calhouncounty.sc.gov/departments/tax-collector
  -> "Overages" section links three per-year PDFs (verified live 2026-10-04
     via the real page HTML, not a screen summary):
       2021 -> /sites/calhouncounty/files/.../Overages/CALHOUN-TaxColOvr_2021.pdf
       2022 -> /sites/calhouncounty/files/.../Overages/CALHOUN-TaxColOvr_2022.pdf
       2023 -> /sites/calhouncounty/files/.../Overages/CALHOUN-TaxColOvr_2023.pdf

All three are TEXT-layer PDFs (pypdf extracts real characters, no OCR
needed) -- confirmed live by downloading and extracting each one directly.
One data row per line: "SALE# TAXPAYER MAP# [$]OVERAGE[$]". Map numbers are
a 4-segment TMS (3-2-2-3, e.g. "168-00-02-027", matching the format already
used by the parcel_cache.py "Calhoun" layer), optionally with a 2-digit
decimal suffix ("069-00-01-018.02").

Three cross-year quirks found live and handled here:
  * The 2021 PDF renders the dollar amount BEFORE its "$" sign with a
    trailing run of spaces ("736.47 $        ") -- the opposite order of
    2022/2023 ("$763.10"). AMOUNT_RE matches either order.
  * The 2021 PDF uses a Unicode hyphen (U+2010) in every map number instead
    of ASCII "-"; 2022/2023 use plain ASCII. Normalized before matching.
  * One 2021 row ("Heirs of Judy Hopkins & Milton Hopkins ETAL") has a stray
    space baked into the map number's own text layer -- "079-00-03-0 10"
    where the real TMS is "079-00-03-010" (same class of PDF-extraction
    artifact Orangeburg's docstring documents for its own 2021 list). TMS_RE
    tolerates one embedded space in the final segment; the match is
    whitespace-stripped before use.
  * The 2023 PDF additionally prints a "TAX SALE DATE: NOVEMBER 13, 2023"
    header line above its table; 2021/2022 have no such line, so the
    source document's own YEAR (from KNOWN_DOCS) is used as the
    tax_sale_date fallback when no explicit date line is present.

Calhoun IS cached in parcel_cache.py (data/parcel_cache/calhoun.sqlite,
AECOM-hosted ArcGIS layer, TMS key format confirmed to match this source's
output exactly) -- situs is filled in the same way
counties_sc.laurens_overage_claims and counties_sc.york_overage_claims
already do.

Calhoun County is OUTSIDE the project's narrow 18-county WNC+Upstate-SC flip
footprint but is not on SCOPE_DENY_COUNTIES either -- same admission path as
every other sibling overage scraper (TAX_SALE_OVERAGE bypasses the flip
footprint via in_scope_distressed(); confirmed by reading main.py directly).

Free, public, no login, no CAPTCHA, no disclaimer click-through.
Slug: counties_sc.calhoun_overage_claims
Category: county_tax
ListingType: TAX_SALE_OVERAGE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...parcel_cache import lookup as _parcel_lookup

log = structlog.get_logger()

#: An ordinary, complete browser User-Agent. The bare "Mozilla/5.0" this module sent
#: until 2026-10-08 is now answered 403 by the county site's Cloudflare front (measured
#: 2026-10-08 on yorkcountysc.gov and orangeburgcounty.org DocumentCenter files: bare
#: UA 403, full UA 200, same host, same minute, no challenge page either way).
_HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36")}

HUB_URL = "https://calhouncounty.sc.gov/departments/tax-collector"

#: Direct document URLs, live-verified 2026-10-04. Hub-page discovery below
#: also runs on top so a newly-posted year is picked up with no code
#: change, the same "curated + self-healing" shape counties_sc.sc_flc /
#: counties_sc.orangeburg_overage_claims use.
KNOWN_DOCS: tuple[tuple[str, str], ...] = (
    ("https://calhouncounty.sc.gov/sites/calhouncounty/files/Documents/"
     "Calhoun%20County/Departments/Tax%20Collector/Overages/CALHOUN-TaxColOvr_2021.pdf", "2021"),
    ("https://calhouncounty.sc.gov/sites/calhouncounty/files/Documents/"
     "Calhoun%20County/Departments/Tax%20Collector/Overages/CALHOUN-TaxColOvr_2022.pdf", "2022"),
    ("https://calhouncounty.sc.gov/sites/calhouncounty/files/Documents/"
     "Calhoun%20County/Departments/Tax%20Collector/Overages/CALHOUN-TaxColOvr_2023.pdf", "2023"),
)

SALE_NUMBER_RE = re.compile(r"^\d{8,9}")
#: Final segment tolerates ONE embedded space (the 2021 PDF's own text-layer
#: glitch, see module docstring) and an optional 2-digit decimal suffix. The
#: embedded-space group requires a trailing whitespace lookahead so it can
#: ONLY match the glitch shape ("...-0 10 1,234.56") and never swallows the
#: first 1-2 digits of a normal un-glitched dollar amount that immediately
#: follows the map number ("...-018 736.47" -- "73" would otherwise look
#: like a valid embedded-space continuation; the lookahead rejects it
#: because "6" follows directly with no whitespace).
TMS_RE = re.compile(r"\d{3}-\d{2}-\d{2}-\d{1,3}(?:\s\d{1,2}(?=\s))?(?:\.\d{2})?")
#: Either "$123.45" or the 2021 PDF's reversed "123.45 $".
AMOUNT_RE = re.compile(r"\$\s*([\d,]+\.\d{2})|([\d,]+\.\d{2})\s*\$")
TAX_SALE_DATE_RE = re.compile(r"^TAX\s+SALE\s+DATE:\s*(.+?)\s*$", re.I)

_HYPHEN_VARIANTS = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
})


def parse_overage_text(text: str, default_year: str) -> list[dict]:
    """Parse SALE# / TAXPAYER / MAP# / OVERAGE rows out of one year's
    single-page text-layer PDF. `default_year` is used as the tax_sale_date
    fallback for years (2021/2022) whose PDF carries no explicit
    "TAX SALE DATE:" header line."""
    records: list[dict] = []
    tax_sale_date = default_year
    for raw_line in (text or "").splitlines():
        line = raw_line.translate(_HYPHEN_VARIANTS).strip()
        if not line:
            continue
        dm = TAX_SALE_DATE_RE.match(line)
        if dm:
            tax_sale_date = dm.group(1).strip()
            continue
        sm = SALE_NUMBER_RE.match(line)
        if not sm:
            continue  # header row ("Sale# Taxpayer Map# Overage") or junk
        tm = TMS_RE.search(line, sm.end())
        if not tm:
            continue
        am = AMOUNT_RE.search(line, tm.end())
        if not am:
            continue
        name = line[sm.end():tm.start()].strip()
        if not name:
            continue
        amount_str = am.group(1) or am.group(2)
        try:
            amount = float(amount_str.replace(",", ""))
        except ValueError:
            continue
        records.append({
            "sale_number": sm.group(0),
            "name": name,
            "map_number": re.sub(r"\s+", "", tm.group(0)),
            "amount": amount,
            "tax_sale_date": tax_sale_date,
        })
    return records


async def _discover_new_docs(c: httpx.AsyncClient, have: set[str]) -> list[tuple[str, str]]:
    """Hub-page discovery: pick up a year Calhoun posts after this file is
    written, without a code change."""
    found: list[tuple[str, str]] = []
    try:
        resp = await c.get(HUB_URL, headers=_HEADERS)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("calhoun_overage.hub_fetch_fail", error=str(exc)[:160])
        return found
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(resp.text)
    except Exception:  # noqa: BLE001
        return found
    for a in tree.css("a[href]"):
        href = urljoin(str(resp.url), a.attributes.get("href", "") or "")
        title = a.attributes.get("title", "") or ""
        if not href or href in have:
            continue
        if not re.search(r"overage", title, re.I):
            continue  # skip the Agreement/Release claim form, etc.
        if re.search(r"claim\s*form|agreement|release", title, re.I):
            continue
        ym = re.search(r"(20\d{2})", title) or re.search(r"(20\d{2})", href)
        found.append((href, ym.group(1) if ym else "unknown"))
    return found


class CalhounOverageClaims(BaseScraper):
    slug = "counties_sc.calhoun_overage_claims"
    name = "Calhoun County SC Overage Claim Lists"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 40
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        docs = list(KNOWN_DOCS)

        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as c:
            have_urls = {u for u, _ in docs}
            docs.extend(await _discover_new_docs(c, have_urls))

            for url, year in docs:
                try:
                    resp = await c.get(url, headers=_HEADERS)
                    resp.raise_for_status()
                    data = resp.content
                except Exception as exc:  # noqa: BLE001
                    log.warning("calhoun_overage.doc_fetch_fail", url=url, error=str(exc)[:160])
                    continue

                if data[:4] != b"%PDF":
                    log.warning("calhoun_overage.not_pdf", url=url, head=data[:8])
                    continue
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(data))
                    text = "\n".join(p.extract_text() or "" for p in reader.pages)
                except Exception as exc:  # noqa: BLE001
                    log.warning("calhoun_overage.pdf_parse_fail", url=url, error=str(exc)[:160])
                    continue

                records = parse_overage_text(text, year)
                now = datetime.utcnow()
                added = 0
                for rec in records:
                    if rec["amount"] <= 0:
                        continue
                    key = f"{rec['map_number']}|{rec['tax_sale_date']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    added += 1

                    situs = None
                    try:
                        situs = _parcel_lookup("Calhoun", rec["map_number"], "SC")
                    except Exception:  # noqa: BLE001 — situs is a nice-to-have, never fatal
                        situs = None
                    street_address = situs.get("address") if situs else None

                    out.append(Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.TAX_SALE_OVERAGE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC",
                        county="Calhoun",
                        parcel_id=rec["map_number"],
                        owner_name=rec["name"],
                        street_address=street_address,
                        # sale_date intentionally left unset -- same
                        # reasoning as every sibling overage scraper (a
                        # standing unclaimed-funds condition, not a
                        # scheduled event). Original tax-sale date
                        # preserved in raw. See this slug's entry in
                        # main.py.DATELESS_OK_SOURCES.
                        description=(f"Tax-sale overage of ${rec['amount']:,.2f} owed to former "
                                     f"owner {rec['name']} (parcel {rec['map_number']}, "
                                     f"sale #{rec['sale_number']}, "
                                     f"{rec['tax_sale_date']} tax sale)."),
                        first_seen=now,
                        last_seen=now,
                        raw={"tax_sale_overage": {
                            "amount": rec["amount"],
                            "sale_number": rec["sale_number"],
                            "map_number": rec["map_number"],
                            "tax_sale_date": rec["tax_sale_date"],
                            "list_year": year,
                        }},
                    ))
                log.info("calhoun_overage.doc_done", url=url[-40:], year=year,
                         parsed=len(records), added=added)

        log.info("calhoun_overage.done", docs=len(docs), usable=len(out))
        return out


if __name__ == "__main__":
    # Manual smoke: uv run python -m foreclosure_scraper.scrapers.counties_sc.calhoun_overage_claims
    import asyncio

    async def _main() -> None:
        s = CalhounOverageClaims()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:20]:
            print(" -", r.parcel_id, "|", r.owner_name, "| $",
                  r.raw.get("tax_sale_overage", {}).get("amount"), "|",
                  r.raw.get("tax_sale_overage", {}).get("tax_sale_date"))

    asyncio.run(_main())
