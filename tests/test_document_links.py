"""Unit tests for the document-artifact harvester (deed/notice/instrument capture)."""
from foreclosure_scraper.document_links import harvest_document_links, stamp_documents
from foreclosure_scraper.models import Listing, PropertyKind, ListingType


HTML = '''
<a href="/DocumentView.aspx?id=123">deed</a>
<a href="https://rod.gov/instruments/DT-0456.pdf">recorded instrument</a>
<a href="/notices/notice-of-sale-789.pdf">notice</a>
<a href="/privacy-policy.pdf">privacy</a>
<a href="/recycling.pdf">recycling</a>
<img src="/scans/deed_00123.tif"/>
<a href="mailto:x@y.com">email</a><a href="#top">top</a>
'''


def _li():
    return Listing(source="t", source_url="https://x", state="NC",
                   property_kind=PropertyKind.UNKNOWN, listing_type=ListingType.FORECLOSURE_SALE)


def test_harvest_filters_junk_and_ranks_deed_first():
    urls = harvest_document_links(HTML, base_url="https://rod.gov/search/results")
    # junk (privacy, recycling) excluded, mailto/# excluded
    assert not any("privacy" in u or "recycling" in u or "mailto" in u for u in urls)
    # instrument/deed ranked ahead of the generic DocumentView
    assert urls[0].endswith("DT-0456.pdf")
    # relative urls absolute-ized against base
    assert all(u.startswith("https://rod.gov/") for u in urls)
    assert any(u.endswith("deed_00123.tif") for u in urls)


def test_harvest_empty_on_no_html():
    assert harvest_document_links("", base_url="https://x") == []
    assert harvest_document_links("<a href='/about.html'>about</a>") == []   # no doc-ish links


def test_stamp_is_idempotent_and_sets_primary():
    li = _li()
    urls = harvest_document_links(HTML, base_url="https://rod.gov/x")
    added = stamp_documents(li, urls)
    assert added == len(li.raw["documents"]) > 0
    assert li.raw["document_url"] == li.raw["documents"][0]
    # re-stamping adds nothing (idempotent)
    assert stamp_documents(li, urls) == 0


def test_walled_rod_image_vendors_excluded():
    # recorded-document image viewers are handled ONLY by the robots-gated rod/doc_images.py;
    # this general harvester must NOT capture them (would bypass the compliance gate).
    html = (
        '<a href="https://spartanburgdeeds.com/view_image.php?key=a&type=pdf">img</a>'
        '<a href="https://us5.courthousecomputersystems.com/GenerateSingleImageForPrint.asp?id=1">t</a>'
        '<a href="https://buncombe.cotthosting.com/Cart?doc=5">cart</a>'
        '<a href="https://county.gov/notices/notice-of-sale-1.pdf">ok</a>'
    )
    urls = harvest_document_links(html, base_url="https://x")
    assert urls == ["https://county.gov/notices/notice-of-sale-1.pdf"]


def test_stamp_respects_existing_doc_field():
    li = _li()
    li.raw = {"deed_url": "https://already/set.pdf"}
    stamp_documents(li, ["https://rod.gov/instruments/DT-1.pdf"])
    # primary scalar NOT overwritten because a doc field already exists
    assert "document_url" not in li.raw
    assert "https://rod.gov/instruments/DT-1.pdf" in li.raw["documents"]
