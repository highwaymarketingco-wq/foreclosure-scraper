"""Unit tests for the lrcpwa photo enricher helpers (no network)."""
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper import enrichment_lrcpwa_photo as m


def _li(**kw):
    base = dict(source="s", source_url="x", listing_type=ListingType.TAX_LIEN,
                state="NC", county="Henderson", parcel_id="10007200")
    base.update(kw); return Listing(**base)


def test_slug():
    assert m._slug("Henderson", "10007200") == "henderson_10007200.jpg"
    assert m._slug("Burke", "079-01-02") == "burke_0790102.jpg"


def test_worth_photo():
    hot = _li(); hot.raw = {"distress_stack": {"tier": "HOT"}}
    graded = _li(); graded.raw = {"grade": {"overall": "C"}}
    cold = _li(); cold.raw = {"distress_stack": {"tier": "COLD"}, "grade": {"overall": None}}
    assert m._worth_photo(hot) and m._worth_photo(graded)
    assert not m._worth_photo(cold)


def test_is_img():
    assert m._is_img(b"\xff\xd8\xff\xe0jfif")
    assert m._is_img(b"\x89PNG\r\n")
    assert not m._is_img(b'{"error"')


def test_set_image_writes_all_aliases():
    li = _li()
    m._set_image(li, "henderson_10007200.jpg")
    assert li.raw["images"]["real"] == ["parcel_photos/henderson_10007200.jpg"]
    assert li.raw["images"]["primary"] == "parcel_photos/henderson_10007200.jpg"
    assert li.raw["zillow"]["photo"] == "parcel_photos/henderson_10007200.jpg"
    assert li.raw["images"]["source"] == "lrcpwa_assessor_photo"
