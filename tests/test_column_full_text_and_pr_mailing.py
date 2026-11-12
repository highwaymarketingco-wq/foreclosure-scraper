"""Column legal notices, 2026-10-07 extraction audit.

1. The full notice text is kept (up to 8,000 characters) in raw['column']['text'];
   only an 800-character snippet used to survive, which cut the personal
   representative's address and the attorney block off most notices.
2. Owner decision 2026-10-07: a personal representative's mailing address, when the
   public notice prints it, is captured (raw['probate']['pr_mailing']) the same way an
   owner mailing address is. An address reached through counsel ("c/o", a firm) is kept
   apart as pr_mailing_care_of; the court's address and the decedent's own are never it.

All names and addresses below are made up.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.newspapers.column_legal_notices as m

SC_NOTICE = (
    "NOTICE TO CREDITORS OF ESTATES All persons having claims against the following "
    "estates are required to deliver or mail their claims to the Personal Representative, "
    "appointed to administer these estates, and to file their claims on Form #371PC with "
    "the Probate Court of Sample County, the address of which is P.O. Box 100, Sampleton, "
    "SC 29000, within eight (8) months after the date of the first publication. "
    "Estate: Pat Example Date of Death: 01/02/2026 Case Number: 2026ES0000001 "
    "Personal Representative: Lee Sample Address: 12 Test Lane, Sampleton, SC 29001"
)
NC_NOTICE = (
    "NOTICE TO CREDITORS Having qualified as Administrator of the Estate of Jordan Example, "
    "late of 9 Decedent Road, Testville, NC 28000, this is to notify all persons having claims "
    "against the estate to present them on or before January 1, 2027. This the 1st day of "
    "October, 2026. Robin Sample, Administrator 44 Mail Street, Testville, NC 28001"
)
NC_VIA_COUNSEL = (
    "NOTICE TO CREDITORS Having qualified as Executor of the Estate of Casey Example, "
    "this is to notify all persons to present claims on or before January 1, 2027. "
    "Terry Sample, Executor c/o Dana Counsel, Sample & Counsel, PLLC, 100 Court Square, "
    "Testville, NC 28002"
)


def test_sc_pr_address_is_the_one_after_the_pr_not_the_courts():
    p = m._parse_sc_probate(SC_NOTICE)
    out = m._pr_mailing(SC_NOTICE, p.get("personal_representative"))
    assert out == {"pr_mailing": "12 Test Lane, Sampleton, SC 29001"}


def test_nc_pr_address_after_the_signature_not_the_decedents():
    p = m._parse_nc_estate(NC_NOTICE)
    assert p["personal_representative"] == "Robin Sample"
    out = m._pr_mailing(NC_NOTICE, p["personal_representative"], p.get("pr_role"))
    assert out == {"pr_mailing": "44 Mail Street, Testville, NC 28001"}


def test_an_address_through_counsel_is_kept_apart():
    p = m._parse_nc_estate(NC_VIA_COUNSEL)
    out = m._pr_mailing(NC_VIA_COUNSEL, p["personal_representative"], p.get("pr_role"))
    assert set(out) == {"pr_mailing_care_of"}
    assert out["pr_mailing_care_of"].endswith("Testville, NC 28002")


def test_no_address_means_no_key():
    assert m._pr_mailing("Personal Representative: Lee Sample", "Lee Sample") == {}
    assert m._pr_mailing("no representative here", None) == {}


def _item(text, nt="Notice to Creditors", state="North Carolina", county="Buncombe"):
    return {"id": "n-1", "text": text, "noticetype": nt, "state": state, "county": county,
            "publishedtimestamp": 1790000000000, "newspapername": "Sample Times"}


def test_listing_carries_full_text_and_pr_mailing():
    s = m.ColumnLegalNotices()
    li = s._nc_estate_listing(_item(NC_NOTICE), "Buncombe")
    assert li.raw["column"]["text"] == m._norm(NC_NOTICE)
    assert li.raw["column"]["text_len"] == len(m._norm(NC_NOTICE))
    assert "text_truncated" not in li.raw["column"]
    assert li.raw["column"]["snippet"] == m._norm(NC_NOTICE)[:800]
    assert li.raw["probate"]["pr_mailing"] == "44 Mail Street, Testville, NC 28001"
    assert li.street_address is None          # never the property's address


def test_full_text_is_capped_at_8000_and_flagged():
    long_text = NC_NOTICE + " filler" * 2000
    raw = m.ColumnLegalNotices()._common_raw(_item(long_text))
    assert len(raw["column"]["text"]) == m._TEXT_CAP == 8000
    assert raw["column"]["text_truncated"] is True
    assert raw["column"]["text_len"] > 8000


def test_the_phone_payload_carries_no_column_text():
    from foreclosure_scraper.web_artifact import RAW_KEEP, _SLIM_RAW
    assert RAW_KEEP.get("column") == "*" and RAW_KEEP.get("probate") == "*"
    assert "column" not in _SLIM_RAW
