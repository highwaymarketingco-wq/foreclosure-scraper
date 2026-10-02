"""Spartan Weekly legal-notice parser — defendant + sale-date extraction.

Patterns are pinned to the real SC Master-in-Equity caption formats observed
live on spartanweeklyonline.com (captured 2026-06-24), so the regex tightening
that lifted the live hit rate (defendant 3/8 -> 6/8, sale-date 1/8 -> 6/8) can't
silently regress.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc import spartan_weekly_legals as sw


# ---- defendant caption variants ----

def test_defendant_handles_vs_with_and():
    body = ("...in the case of Rodger C. Jarrell Real Estate & Mortgages, Inc. v. "
            "Gurdip S. Ghataora and Jaspal K. Ghataora, I, the undersigned as Master...")
    assert sw._defendant(body, "foreclosure") == "Gurdip S. Ghataora and Jaspal K. Ghataora"


def test_defendant_stops_before_etal_on_semicolon_list():
    body = "...in the case of NewRez LLC vs. Nitikki Miller; et.al., I, the undersigned..."
    assert sw._defendant(body, "foreclosure") == "Nitikki Miller"


def test_defendant_keeps_multiple_semicolon_parties():
    body = ("...South Carolina Federal Credit Union vs. Mihail Chiosac; Elena Chiosac; "
            "et.al., I, the undersigned will sell...")
    assert sw._defendant(body, "foreclosure") == "Mihail Chiosac; Elena Chiosac"


def test_defendant_handles_against_and_master_terminator():
    body = ("...case of South Carolina State Housing Finance and Development Authority "
            "against Lori M. Martin et al., I, the Master in Equity for Spartanburg County, will sell...")
    assert sw._defendant(body, "foreclosure") == "Lori M. Martin"


# ---- sale-date variants ----

def test_saledate_skips_weekday_prefix():
    m = sw._SALEDATE_RE.search("will sell on Monday, July 6, 2026 at 11:00 AM, at the County Judicial Center")
    assert m and m.group(1) == "July 6, 2026"


def test_saledate_plain_no_weekday():
    m = sw._SALEDATE_RE.search("will sell on July 6, 2026 at 11:00 AM at Spartanburg County Court House")
    assert m and m.group(1) == "July 6, 2026"


def test_saledate_ignores_unrelated_dates():
    # A published-on date elsewhere in the body must not be mistaken for the sale date.
    assert sw._SALEDATE_RE.search("Published June 18, 2026. The property is located at 12 Main St.") is None


# ---- probate notice -> decedent (owner) + PR (contact) ----

_PROBATE_BODY = (
    "Probate Court Notice to Creditors of Estates Case Number: 2026ES4200344 All persons "
    "having claims against the following estates MUST file ... Estate: Gloria J. Dowell "
    "Date of Death: January 31, 2026 Case Number: 2026ES4200344 Personal Representative: "
    "Sherrie D. Tanner 126 Cheshire Road Lexington, SC 29072 6-18, 25, 7-2 June 18, 2026"
)


def test_probate_extracts_decedent_pr_and_case():
    # decedent (the property OWNER -> feeds owner-name address backfill)
    assert sw._PROBATE_ESTATE.search(_PROBATE_BODY).group(1).strip() == "Gloria J. Dowell"
    # personal representative + mailing address (the heir/seller contact)
    pr = sw._PROBATE_PR.search(_PROBATE_BODY)
    assert pr.group(1).strip() == "Sherrie D. Tanner"
    assert "126 Cheshire Road" in pr.group(2)
    # estate case number (ES, not the CP foreclosure pattern)
    assert sw._ES_CASE_RE.search(_PROBATE_BODY).group(1) == "2026ES4200344"
    assert sw._PROBATE_DOD.search(_PROBATE_BODY).group(1) == "January 31, 2026"


# ---- AUDITED 2026-10-01: site redesign regression tests ----
# The site went DEAD 2026-08-24 and came back with a changed template: the
# anchor "address" text is now a category restatement, and the h6 TYPE
# taxonomy collapsed so a real foreclosure notice no longer self-identifies
# by label. See the module docstring for the live evidence.

def test_category_labels_are_not_treated_as_addresses():
    """Live now, the anchor text holds things like "Summons and Notices" /
    "Abandoned vehicle" / "Notice of Hearing" / "Legal Notice" -- none of
    these may ever become street_address."""
    for label in ("Summons and Notices", "Abandoned vehicle",
                  "Notice of Hearing", "Legal Notice"):
        assert sw._looks_like_address(label) is False


def test_a_real_address_still_passes():
    assert sw._looks_like_address("142 Oak Street, Walhalla") is True


def test_reclassify_from_body_recognizes_foreclosure_under_the_generic_label():
    """Live example (case 2026-CP-42-02855): a notice the site files under
    'All Other Notices' is actually a mortgage-foreclosure summons. The body
    must drive the classification, not the now-uninformative h6 label."""
    body = (
        "STATE OF SOUTH CAROLINA COUNTY OF SPARTANBURG IN THE COURT OF COMMON "
        "PLEAS C/A No.: 2026-CP-42-02855 MidFirst Bank, Plaintiff, v. Michael "
        "Ronald Pressley; Granite St. Land Trust, Defendant(s). Summons and "
        "Notices (Non-Jury) Foreclosure of Real Estate Mortgage"
    )
    lt, kind = sw._reclassify_from_body(sw.ListingType.UNKNOWN, "other", body)
    assert kind == "foreclosure"
    assert lt == sw.ListingType.LIS_PENDENS


def test_reclassify_from_body_leaves_a_real_non_foreclosure_notice_alone():
    body = "Notice of Hearing regarding custody of a minor child in Family Court."
    lt, kind = sw._reclassify_from_body(sw.ListingType.UNKNOWN, "other", body)
    assert kind == "other"
    assert lt == sw.ListingType.UNKNOWN


def test_reclassify_from_body_never_downgrades_probate():
    body = "Foreclosure of Real Estate Mortgage mentioned only in passing."
    lt, kind = sw._reclassify_from_body(sw.ListingType.PROBATE_NOTICE, "probate", body)
    assert kind == "probate"
    assert lt == sw.ListingType.PROBATE_NOTICE
