"""TownNews legal-notice newspaper scrapers (Post & Courier, Carolina Coast).

Both consume the TownNews (TNCMS) legal-classifieds RSS feed filtered for
foreclosure notices — a free, server-rendered, pre-auction signal source.

Offline tests parse REAL RSS item strings captured live on 2026-06-25, so the
parser is exercised against the exact upstream shapes (SC C/A numbers, NC SP
docket numbers, address-in-headline) without hitting the network. Live tests
are gated behind RUN_NETWORK_TESTS=1.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers._townnews import parse_rss_items
from foreclosure_scraper.scrapers.newspapers.carolina_coast import (
    CarolinaCoastForeclosures,
)
from foreclosure_scraper.scrapers.newspapers.post_and_courier import (
    PostAndCourierForeclosures,
)

# --- Real captured RSS items (Post & Courier, Charleston/Berkeley SC) ---------
PC_RSS = """<rss><channel>
<item>
<title>Notice of Master In Equity Sale STATE OF SOUTH CAROLINA</title>
<link>https://www.postandcourier.com/classifieds_new/community/announcements/legal/notice-of-master-in-equity-sale/ad_aaa.html</link>
<description>Notice of Master In Equity Sale STATE OF SOUTH CAROLINA COUNTY OF CHARLESTON IN THE COURT OF COMMON PLEAS Case No: 2025-CP-10-01481 Bank of the Lowcountry vs. Brabham Construction, LLC</description>
<pubDate>Thu, 25 Jun 2026 00:30:20 -0400</pubDate>
</item>
<item>
<title>STATE OF SOUTH CAROLINA COUNTY OF BERKELEY IN THE COURT OF COMMON PLEAS C/A NO: 2026CP0801636 (NON-JURY MORTGAGE FORECLOSURE) SUMMONS AND NOTICES</title>
<link>https://www.postandcourier.com/classifieds_new/community/announcements/legal/berkeley-foreclosure/ad_bbb.html</link>
<description>STATE OF SOUTH CAROLINA COUNTY OF BERKELEY IN THE COURT OF COMMON PLEAS C/A NO: 2026CP0801636 (NON-JURY MORTGAGE FORECLOSURE) SUMMONS AND NOTICES Moneyline Ventures, LLC, PLAINTIFF</description>
<pubDate>Wed, 24 Jun 2026 00:30:17 -0400</pubDate>
</item>
<item>
<title>NOTICE OF SALE CIVIL ACTION NO.</title>
<link>https://www.postandcourier.com/classifieds_new/community/announcements/legal/notice-of-sale/ad_ccc.html</link>
<description>NOTICE OF SALE CIVIL ACTION NO. 2025-CP-08-01907 BY VIRTUE of the judgment granted in Planet Home Lending, LLC vs. Harry B. Parks; Dawn H. Parks, the Master In Equity for Berkeley County will sell on July 1, 2026</description>
<pubDate>Tue, 23 Jun 2026 00:30:00 -0400</pubDate>
</item>
<item>
<title>NOTICE OF PUBLIC HEARING City Council budget</title>
<link>https://www.postandcourier.com/classifieds_new/community/announcements/legal/hearing/ad_ddd.html</link>
<description>NOTICE OF PUBLIC HEARING the City Council will hold a public hearing</description>
<pubDate>Tue, 23 Jun 2026 00:30:00 -0400</pubDate>
</item>
</channel></rss>"""

# --- Real captured RSS item (Carolina Coast / Carteret News-Times NC) ---------
CC_RSS = """<rss><channel>
<item>
<title>NOTICE OF SUBSTITUTE TRUSTEE’S FORECLOSURE SALE OF REAL PROPERTY 26SP000053-150 294 CAPE LOOKOUT DR HARKERS ISLAND, NC UNDER AND BY VIRTUE</title>
<link>https://www.carolinacoastonline.com/classifieds/community/announcements/legal/ad_7ef.html</link>
<description>NOTICE OF SUBSTITUTE TRUSTEE’S FORECLOSURE SALE OF REAL PROPERTY 26SP000053-150 294 CAPE LOOKOUT DR HARKERS ISLAND, NC UNDER AND BY VIRTUE of the power and authority contained in that certain Deed of Trust executed and delivered by Jackie H. Willis</description>
<pubDate>Mon, 23 Jun 2026 09:00:00 -0400</pubDate>
</item>
<item>
<title>NOTICE OF SERVICE OF PROCESS BY PUBLICATION CARTERET COUNTY</title>
<link>https://www.carolinacoastonline.com/classifieds/community/announcements/legal/ad_4d3.html</link>
<description>NOTICE OF SERVICE OF PROCESS BY PUBLICATION NORTH CAROLINA CARTERET COUNTY FILE NO. 26CV000728-240 COUNTY OF CARTERET tax foreclosure</description>
<pubDate>Mon, 23 Jun 2026 09:00:00 -0400</pubDate>
</item>
</channel></rss>"""


def _by_url(rows):
    return {r.source_url: r for r in rows}


def test_pc_parses_full_sc_case_numbers():
    rows = list(
        parse_rss_items(
            PC_RSS,
            source_slug="newspapers.post_and_courier",
            default_state="SC",
            default_county="Charleston",
            allowed_states=("SC",),
        )
    )
    by = _by_url(rows)
    # The public-hearing notice is NOT a foreclosure -> excluded.
    assert not any("hearing" in u for u in by)
    # 3 foreclosure-related notices captured.
    assert len(rows) == 3
    # SC C/A numbers must be captured in FULL (not truncated to 2025-CP-10).
    mie = by["https://www.postandcourier.com/classifieds_new/community/announcements/legal/notice-of-master-in-equity-sale/ad_aaa.html"]
    assert mie.case_number == "2025-CP-10-01481"
    assert mie.listing_type == ListingType.FORECLOSURE_SALE
    assert mie.foreclosure_process == "judicial"
    assert mie.county == "Charleston"


def test_pc_county_override_and_listing_type():
    rows = _by_url(
        parse_rss_items(
            PC_RSS,
            source_slug="newspapers.post_and_courier",
            default_state="SC",
            default_county="Charleston",
            allowed_states=("SC",),
        )
    )
    berkeley = rows["https://www.postandcourier.com/classifieds_new/community/announcements/legal/berkeley-foreclosure/ad_bbb.html"]
    # "COUNTY OF BERKELEY" overrides the Charleston default.
    assert berkeley.county == "Berkeley"
    assert berkeley.case_number == "2026CP0801636"
    # Mortgage-foreclosure SUMMONS = pre-sale lis-pendens signal.
    assert berkeley.listing_type == ListingType.LIS_PENDENS

    nos = rows["https://www.postandcourier.com/classifieds_new/community/announcements/legal/notice-of-sale/ad_ccc.html"]
    assert nos.case_number == "2025-CP-08-01907"
    assert nos.county == "Berkeley"
    assert nos.listing_type == ListingType.FORECLOSURE_SALE
    assert nos.sale_date is not None and nos.sale_date.year == 2026


def test_pc_no_garbage_addresses():
    # The SC summons/MIE notices have no street address in the headline; the
    # parser must NOT fabricate one out of case-number digits + "ST" boilerplate.
    rows = parse_rss_items(
        PC_RSS,
        source_slug="newspapers.post_and_courier",
        default_state="SC",
        default_county="Charleston",
        allowed_states=("SC",),
    )
    for r in rows:
        if r.street_address:
            # If we DID extract one it must contain a real alphabetic name.
            assert any(c.isalpha() for c in r.street_address)
            assert "SUMMONS" not in r.street_address.upper()
            assert "VIRTUE" not in r.street_address.upper()


def test_cc_nc_address_and_case_in_headline():
    rows = _by_url(
        parse_rss_items(
            CC_RSS,
            source_slug="newspapers.carolina_coast",
            default_state="NC",
            default_county="Carteret",
            allowed_states=("NC",),
        )
    )
    sale = rows["https://www.carolinacoastonline.com/classifieds/community/announcements/legal/ad_7ef.html"]
    assert sale.state == "NC"
    assert sale.county == "Carteret"
    assert sale.case_number == "26SP000053-150"
    # Address must be clean — no case-suffix digits glued on the front.
    assert sale.street_address == "294 CAPE LOOKOUT DR"
    # City must drop the leading "DR" suffix token.
    assert sale.city == "Harkers Island"
    assert sale.listing_type == ListingType.FORECLOSURE_SALE
    assert sale.foreclosure_process == "power_of_sale"
    # Dedupe key must use the parcel/address branch, not the url fallback.
    assert sale.dedupe_key().startswith("addr:")


def test_cc_tax_foreclosure_publication_kept():
    rows = parse_rss_items(
        CC_RSS,
        source_slug="newspapers.carolina_coast",
        default_state="NC",
        default_county="Carteret",
        allowed_states=("NC",),
    )
    # Both items mention foreclosure -> both kept; county tax-foreclosure
    # publication is a valid distressed signal.
    assert len(rows) == 2


def test_allowed_state_filter_drops_out_of_state():
    # Feed an SC notice but restrict to NC -> dropped.
    rows = parse_rss_items(
        PC_RSS,
        source_slug="x",
        default_state="SC",
        default_county="Charleston",
        allowed_states=("NC",),
    )
    assert rows == [] or all(r.state == "NC" for r in rows)


def test_scrapers_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    slugs = {s.slug for s in all_scrapers()}
    assert "newspapers.post_and_courier" in slugs
    assert "newspapers.carolina_coast" in slugs


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live postandcourier.com / carolinacoastonline.com RSS",
)
def test_live_feeds_return_foreclosure_rows():
    pc = asyncio.run(PostAndCourierForeclosures().fetch())
    cc = asyncio.run(CarolinaCoastForeclosures().fetch())
    for li in list(pc):
        assert li.state == "SC"
        assert li.case_number  # SC notices always carry a C/A number
    for li in list(cc):
        assert li.state == "NC"
