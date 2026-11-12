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
<description>Notice of Master In Equity Sale STATE OF SOUTH CAROLINA COUNTY OF CHARLESTON IN THE COURT OF COMMON PLEAS Case No: 2025-CP-10-09481 Bank of the Lowcountry vs. Brabham Construction, LLC</description>
<pubDate>Thu, 25 Jun 2026 00:30:20 -0400</pubDate>
</item>
<item>
<title>STATE OF SOUTH CAROLINA COUNTY OF BERKELEY IN THE COURT OF COMMON PLEAS C/A NO: 2026CP0809636 (NON-JURY MORTGAGE FORECLOSURE) SUMMONS AND NOTICES</title>
<link>https://www.postandcourier.com/classifieds_new/community/announcements/legal/berkeley-foreclosure/ad_bbb.html</link>
<description>STATE OF SOUTH CAROLINA COUNTY OF BERKELEY IN THE COURT OF COMMON PLEAS C/A NO: 2026CP0809636 (NON-JURY MORTGAGE FORECLOSURE) SUMMONS AND NOTICES Moneyline Ventures, LLC, PLAINTIFF</description>
<pubDate>Wed, 24 Jun 2026 00:30:17 -0400</pubDate>
</item>
<item>
<title>NOTICE OF SALE CIVIL ACTION NO.</title>
<link>https://www.postandcourier.com/classifieds_new/community/announcements/legal/notice-of-sale/ad_ccc.html</link>
<description>NOTICE OF SALE CIVIL ACTION NO. 2025-CP-08-09907 BY VIRTUE of the judgment granted in Planet Home Lending, LLC vs. Harold B. Sampleton; Dana H. Sampleton, the Master In Equity for Berkeley County will sell on July 1, 2026</description>
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
<title>NOTICE OF SUBSTITUTE TRUSTEE’S FORECLOSURE SALE OF REAL PROPERTY 26SP009953-150 294 SAMPLE POINT DR HARKERS ISLAND, NC UNDER AND BY VIRTUE</title>
<link>https://www.carolinacoastonline.com/classifieds/community/announcements/legal/ad_7ef.html</link>
<description>NOTICE OF SUBSTITUTE TRUSTEE’S FORECLOSURE SALE OF REAL PROPERTY 26SP009953-150 294 SAMPLE POINT DR HARKERS ISLAND, NC UNDER AND BY VIRTUE of the power and authority contained in that certain Deed of Trust executed and delivered by Jamie H. Examplar</description>
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
    assert mie.case_number == "2025-CP-10-09481"
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
    assert berkeley.case_number == "2026CP0809636"
    # Mortgage-foreclosure SUMMONS = pre-sale lis-pendens signal.
    assert berkeley.listing_type == ListingType.LIS_PENDENS

    nos = rows["https://www.postandcourier.com/classifieds_new/community/announcements/legal/notice-of-sale/ad_ccc.html"]
    assert nos.case_number == "2025-CP-08-09907"
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
    assert sale.case_number == "26SP009953-150"
    # Address must be clean — no case-suffix digits glued on the front.
    assert sale.street_address == "294 SAMPLE POINT DR"
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


def test_county_name_glued_to_next_word_is_recovered():
    """Regression 2026-09-15: the Index-Journal's (Greenwood, SC) RSS
    description read "...COUNTY OF GREENWOODIN THE COURT OF COMMON
    PLEAS..." with no space before "IN". COUNTY_OF_RE has no delimiter to
    stop on, so it captured "Greenwoodin" whole -- which then failed
    validation.py's county-membership check and got silently NULLED,
    losing the row's county entirely even though the notice clearly names
    a real one. The parser must recover "Greenwood" itself rather than
    relying on downstream validation to catch (and only ever discard) it."""
    xml = """<rss><channel><item>
<title>STATE OF SOUTH CAROLINA</title>
<link>https://www.indexjournal.com/classifieds/community/announcements/legal/ad_glued.html</link>
<description>STATE OF SOUTH CAROLINACOUNTY OF GREENWOODIN THE COURT OF COMMON PLEASC/A NO: 2026CP2400848SUMMONS AND NOTICES(Non-Jury)FORECLOSUREOF REAL ESTATEMORTGAGEROCKET MORTGAGE, LLC, Plaintiff</description>
<pubDate>Fri, 04 Sep 2026 00:00:00 -0400</pubDate>
</item></channel></rss>"""
    rows = list(parse_rss_items(
        xml, source_slug="newspapers.index_journal",
        default_state="SC", default_county="Greenwood", allowed_states=("SC",),
    ))
    assert len(rows) == 1
    assert rows[0].county == "Greenwood"


def test_county_glue_falls_back_to_default_when_no_known_county_matches():
    """If the glued text doesn't start with any real county name at all
    (a garbled or unrecognizable capture), fall back to the paper's own
    default county rather than a bogus value or None."""
    xml = """<rss><channel><item>
<title>Foreclosure notice</title>
<link>https://x/ad_unknown.html</link>
<description>STATE OF SOUTH CAROLINA COUNTY OF ZZZNOTAREALCOUNTYXX foreclosure sale by virtue</description>
<pubDate>Fri, 04 Sep 2026 00:00:00 -0400</pubDate>
</item></channel></rss>"""
    rows = list(parse_rss_items(
        xml, source_slug="x", default_state="SC", default_county="Greenwood",
        allowed_states=("SC",),
    ))
    assert len(rows) == 1
    assert rows[0].county == "Greenwood"


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


# --- Regressions found live 2026-10-01 on newspapers.aiken_standard / --------
# --- newspapers.carolina_coast (HERMES sec 8 per-source audit, newspaper tier)

# Real captured item (Aiken Standard, "master in equity" query): TownNews
# repeats the ENTIRE title as the first sentence of its own <description>, so
# the case number appears TWICE in the combined title+description text. The
# parser used to strip only the FIRST occurrence before scanning for a street
# address/ZIP, leaving the second, un-stripped copy of "2026-CP-02-09967" for
# ZIP_RE to mistake for a ZIP code ("01967").
DUP_CASE_RSS = """<rss><channel>
<item>
<title>STATE OF SOUTH CAROLINA IN THE COURT OF COMMON PLEAS COUNTY OF AIKEN SUMMONS AND NOTICE OF FILING OF COMPLAINT (NON-JURY MORTGAGE FORECLOSURE) C/A NO: 2026-CP-02-09967 DEFICIENCY WAIVED</title>
<link>https://www.postandcourier.com/aikenstandard/classifieds/community/announcements/legal/ad_dupcase.html</link>
<description>STATE OF SOUTH CAROLINA IN THE COURT OF COMMON PLEAS COUNTY OF AIKEN SUMMONS AND NOTICE OF FILING OF COMPLAINT (NON-JURY MORTGAGE FORECLOSURE) C/A NO: 2026-CP-02-09967 DEFICIENCY WAIVED Onity Mortgage Corporation f/k/a PHH Mortgage Corporation, PLAINTIFF, vs. Lara J Testhorst, Defendant(s)</description>
<pubDate>Tue, 29 Sep 2026 01:00:08 -0400</pubDate>
</item>
</channel></rss>"""

# Real captured item (Aiken Standard, "master in equity" query): a SC "NOTICE
# OF SALE" (post-judgment, Master-in-Equity) caption, which uses PERIODS, not
# hyphens, in the C/A number, and never says the literal word "Plaintiff" or
# "Defendant" at all -- it names the parties as "...in the case of: <Plaintiff>
# vs./against <Defendant>...". Before the fix: case_number was dropped
# entirely (the hyphen-only regex didn't match), the un-stripped period-form
# case number got mistaken for a ZIP ("00605"), owner_name/defendant was
# always None for this caption shape, and the plaintiff lender's own name got
# mislabeled as "trustee" (TRUSTEE_RE matches anything ending "...LLC").
NOTICE_OF_SALE_RSS = """<rss><channel>
<item>
<title>NOTICE OF SALE C/A</title>
<link>https://www.postandcourier.com/aikenstandard/classifieds/community/announcements/legal/ad_notice_of_sale.html</link>
<description>NOTICE OF SALE C/A No. 2026.CP.02.09605 BY VIRTUE of a decree heretofore granted in the case of: Pennymac Loan Services, LLC vs. Alana Testerman; Powderhouse Landing Property Owners' Association, Inc.; The United States of America acting by and through its agency</description>
<pubDate>Mon, 28 Sep 2026 01:00:08 -0400</pubDate>
</item>
</channel></rss>"""


def test_duplicated_case_number_does_not_leak_into_zip():
    rows = list(
        parse_rss_items(
            DUP_CASE_RSS,
            source_slug="newspapers.aiken_standard",
            default_state="SC",
            default_county="Aiken",
            allowed_states=("SC",),
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.case_number == "2026-CP-02-09967"
    # The case-number suffix ("01967") must NOT be read as a ZIP code.
    assert row.zip_code is None


def test_notice_of_sale_period_case_number_and_parties():
    rows = list(
        parse_rss_items(
            NOTICE_OF_SALE_RSS,
            source_slug="newspapers.aiken_standard",
            default_state="SC",
            default_county="Aiken",
            allowed_states=("SC",),
        )
    )
    assert len(rows) == 1
    row = rows[0]
    # Period-separated C/A number is now captured (previously dropped).
    assert row.case_number == "2026.CP.02.09605"
    # The un-stripped case digits must NOT be read as a ZIP code.
    assert row.zip_code is None
    # The owner/defendant is wired from the "in the case of: X vs. Y" caption.
    assert row.plaintiff == "Pennymac Loan Services, LLC"
    assert row.defendant == "Alana Testerman"
    assert row.owner_name == "Alana Testerman"
    # The plaintiff lender must NOT be mislabeled as the trustee -- SC has no
    # substitute-trustee role at all (judicial-only foreclosure state).
    assert row.trustee is None


# Real captured item (Carolina Coast / Carteret NC): the owner is named only
# as the grantor of the foreclosed Deed of Trust ("...executed by Jodi O.
# Exampleson dated..."), never via a "PRESENT RECORD OWNER(S):" label. Before the
# fix, owner_name/defendant was always None for this (very common) NC
# power-of-sale shape.
GRANTOR_RSS = """<rss><channel>
<item>
<title>NOTICE OF FORECLOSURE SALE NORTH CAROLINA, CARTERET COUNTY 26SP009915-150 135 SAMPLE LN BEAUFORT, NC</title>
<link>https://www.carolinacoastonline.com/classifieds/community/announcements/legal/ad_grantor.html</link>
<description>NOTICE OF FORECLOSURE SALE NORTH CAROLINA, CARTERET COUNTY 26SP009915-150 135 SAMPLE LN BEAUFORT, NC Under and by virtue of a Power of Sale contained in that certain Deed of Trust executed by Jodi O. Exampleson dated August 15, 2017, recorded in the office of the Register of Deeds</description>
<pubDate>Mon, 28 Sep 2026 09:00:00 -0400</pubDate>
</item>
</channel></rss>"""


def test_grantor_fallback_fills_owner_when_no_record_owner_label():
    rows = list(
        parse_rss_items(
            GRANTOR_RSS,
            source_slug="newspapers.carolina_coast",
            default_state="NC",
            default_county="Carteret",
            allowed_states=("NC",),
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.owner_name == "Jodi O. Exampleson"
    assert row.defendant == "Jodi O. Exampleson"


def test_trailing_ellipsis_does_not_block_end_anchored_capture():
    """Regression: TownNews appends a literal "…" when it truncates a
    title/description. Left in place, it sits between the real content and
    the string's true end, breaking any regex here that relies on `$` to
    terminate a capture for a name that is the very last thing before the
    cutoff (found live on newspapers.carolina_coast: "...executed by DARREN
    G. SAMPLER…" failed to capture the surname at all before this fix)."""
    xml = """<rss><channel><item>
<title>NOTICE OF SALE Deed of Trust executed by DARREN G.</title>
<link>https://x/ad_ellipsis.html</link>
<description>NOTICE OF SALE IN THE GENERAL COURT OF JUSTICE Deed of Trust executed by DARREN G. SAMPLER…</description>
<pubDate>Mon, 28 Sep 2026 09:00:00 -0400</pubDate>
</item></channel></rss>"""
    rows = list(parse_rss_items(
        xml, source_slug="newspapers.carolina_coast",
        default_state="NC", default_county="Onslow", allowed_states=("NC",),
    ))
    assert len(rows) == 1
    assert rows[0].owner_name == "DARREN G. SAMPLER"
