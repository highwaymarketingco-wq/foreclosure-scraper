"""newspapers.daily_courier — trustee/attorney contact-extraction parity fix.

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 2):
this module reads the same full per-notice body text (up to 6 KB) its 3
sibling newspaper scrapers (hendersonville_lightning.py / shelby_star.py /
tryon_bulletin.py) already pass through the shared
`column_legal_notices._notice_email()` helper to capture the trustee/
attorney's published phone + email -- a real reachable case contact -- but
this module never called it. Live-confirmed 2026-10-04 the helper correctly
extracts real contact info from this exact site's real notice bodies (2 of 2
live-fetched current cards produced a hit: a Rutherford County notice with
phone "(828) 286-8222" / name "Alayna P. English Law Office", and a DEQ
consent-order notice with phone + email). Wired identically to the 3 sibling
scrapers.

This test uses a notice body shaped like real NC substitute-trustee notices
(closing trustee/attorney contact block) to verify the wiring end to end.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.newspapers.daily_courier import parse_notice

NOTICE_HTML = """<html><head>
<title>NORTH CAROLINA RUTHERFORD COUNTY | Classifieds</title>
</head><body><h1>NORTH CAROLINA RUTHERFORD COUNTY</h1>
<div itemprop="description">
<p>NORTH CAROLINA RUTHERFORD COUNTY</p><p>Special Proceedings</p><p>No. 26SP000901-800</p>
<p>Substitute Trustee: Pat E. Trustee</p>
<p>NOTICE OF FORECLOSURE SALE</p><p>Date of Sale: September 22, 2026</p>
<p>Time of Sale: 1:00 p.m.</p><p>Place of Sale: Rutherford County Courthouse</p>
<p>Record Owners: Sample T. Ownerperson</p>
<p>Address of Property: 100 Example Road Rutherfordton, NC 28139</p>
<p>Deed of Trust: Book 2001 Page: 1234 Dated: January 5, 2022</p>
<p>Any questions regarding this sale should be directed to Pat E. Trustee Law Office,
Substitute Trustee, at (828) 286-8222.</p>
</div></body></html>"""


def test_contact_is_captured_from_the_notice_body():
    li = parse_notice(NOTICE_HTML, "https://example.com/ad_x.html")
    assert li is not None
    assert "notice_contact" in li.raw
    assert li.raw["notice_contact"]["phone"] == "(828) 286-8222"


def test_contact_absent_when_body_has_none():
    html_no_contact = NOTICE_HTML.replace(
        "<p>Any questions regarding this sale should be directed to Pat E. Trustee Law Office,\n"
        "Substitute Trustee, at (828) 286-8222.</p>",
        "",
    )
    assert "286-8222" not in html_no_contact  # guard: the replace actually matched
    li = parse_notice(html_no_contact, "https://example.com/ad_y.html")
    assert li is not None
    assert "notice_contact" not in li.raw
