"""Greenville County SC — Delinquent Tax Sale roster (real estate + personal property).

Greenville is SC's largest county by population and, before this scraper, had
only 584 board rows (greenville_hard_distress + greenville_mie_adverts — no
delinquent-tax source at all). Found 2026-09-14 while chasing a mailing-data
lead for Greenville: its property-tax page links a disclaimer gate to
`/appsAS400/Taxsale/` (a legacy IBM AS/400 web front end, hence the path) —
but the page itself is a plain, clean, uniform HTML table, not the mainframe
green-screen the URL suggests.

  https://www.greenvillecounty.org/appsAS400/Taxsale/

Verified live 2026-09-14: one <table>, header row `Item # | Map # | Name |
Amount Due`, 2,338 data rows. Two distinct row shapes share the same table,
distinguished ONLY by whether Map # is populated:

  Real estate  : Item#, Map# (13-digit, or an alpha-prefixed condo/mobile-
                 home-park code + digits e.g. "WG02060100500" -- 383 of
                 2,112 real-estate rows use this alt format), Name, $Amount
  Personal property / vehicle : Item#, "" (blank Map#), Name, $Amount

The personal-property rows (~50 of them, high item numbers e.g. 96068+) have
no parcel to join to — they are NOT run through counties_sc._sc_tax_table's
is_usable_row() gate (which deliberately requires a parcel; see that module's
own docstring for why that is the right call for a property-acquisition
lead). They are kept anyway, parcel_id=None, as NAME-keyed distress signals —
the same "tax-delinquent person, not tax-delinquent parcel" shape this
engine already treats as a lead source via counties_sc.sc_dew_lien_registry.

The page shows "Tax Sale date: November 3 and 4, 2025" — in the past
relative to any run of this scraper — but carries no visible last-updated
timestamp and no per-row status (paid/redeemed/sold). Treated as a STANDING
roster like every other SC county delinquent-tax source in this codebase
(Fairfield/York/Saluda/Lancaster/Newberry/Darlington), not a scheduled
future event: sale_date is deliberately left unset and this source is in
main.py's DATELESS_OK_SOURCES.

Free, public, no login, no CAPTCHA.
Slug: counties_sc.greenville_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._sc_tax_table import is_label_row

log = structlog.get_logger()

PAGE_URL = "https://www.greenvillecounty.org/appsAS400/Taxsale/"

_AMOUNT_RE = re.compile(r"^\$[\d,]+\.\d{2}$")


class GreenvilleDelinquentTax(BaseScraper):
    slug = "counties_sc.greenville_delinquent_tax"
    name = "Greenville County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 500
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("greenville_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        now = datetime.utcnow()
        real_estate = personal_property = skipped = 0

        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if len(clean) != 4 or is_label_row(clean):
                continue

            item_no, map_no, name, amount_str = clean
            if not name or not _AMOUNT_RE.match(amount_str):
                skipped += 1
                continue
            # Map# is blank for personal-property/vehicle rows and populated for
            # real estate -- but NOT always purely numeric: verified live, 383 of
            # 2,112 real-estate rows use an alpha-prefixed format (e.g.
            # "WG02060100500", a condo/mobile-home-park code + digits). An earlier
            # digits-only regex here silently reclassified all 383 as parcel-less
            # personal property, which is what live output caught before this
            # shipped. Blank-vs-non-blank is the only signal this table actually
            # carries; any non-empty value is a real parcel identifier.
            parcel = map_no or None
            amount = float(amount_str.replace("$", "").replace(",", ""))

            if parcel:
                real_estate += 1
            else:
                personal_property += 1

            out.append(Listing(
                source=self.slug,
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Greenville",
                parcel_id=parcel,
                # Every row on this page shares one source_url and the
                # personal-property rows have no street_address either, so
                # without a per-row case_number, Listing.dedupe_key() falls
                # through to `url:{source_url}` for ALL of them -- verified
                # live this collapsed all 226 personal-property rows into a
                # single board row before this was added. Item# is unique
                # per row in the county's own table; reused here as the
                # dedupe differentiator (harmless on real-estate rows, which
                # already get a stronger parcel: key first).
                case_number=item_no,
                owner_name=name,
                defendant=name,
                description=(f"Delinquent tax of ${amount:,.2f} owed by {name}"
                             + (f" (parcel {parcel})" if parcel else " (personal property/vehicle, no parcel)")),
                first_seen=now,
                last_seen=now,
                raw={"greenville_delinquent_tax": {
                    "item_number": item_no,
                    "total_due": amount,
                    "map_number": parcel,
                }},
            ))

        log.info("greenville_tax.done", real_estate=real_estate,
                  personal_property=personal_property, skipped=skipped, total=len(out))
        return out
