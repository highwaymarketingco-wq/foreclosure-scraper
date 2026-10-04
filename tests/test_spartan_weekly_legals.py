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


# ---- AUDITED 2026-10-04: three more real sub-types the collapsed "All Other
# Notices" bucket hides, found live. ----

def test_clean_decodes_html_entities_not_just_the_old_three():
    """Live bug: _clean() used to hand-roll only &nbsp;/&amp;/&#39; and leave
    every other named entity -- notably the CMS's own &rsquo; for an
    apostrophe in a name -- as the literal 7-char string "&rsquo;", which
    broke every [A-Za-z .,'-]-shaped name regex outright. Confirmed live on 3
    real decedents: "Ahsad U&rsquo;Real Logan", "La&rsquo;Shauna Davette
    Long", "Marquise Asant&rsquo;e Browning" -- none matched _PROBATE_ESTATE
    before this fix."""
    assert sw._clean("Estate: Ahsad U&rsquo;Real Logan<br/>Date of Death:") == \
        "Estate: Ahsad U'Real Logan Date of Death:"
    # _PROBATE_ESTATE runs on the ALREADY-_clean()'d body in real use (the
    # raw HTML is cleaned once, up front, in _row_to_listing) -- clean it
    # here too rather than feed the regex raw, un-decoded HTML.
    raw = "Estate: Ahsad U&rsquo;Real Logan Date of Death: July 8, 2026"
    m = sw._PROBATE_ESTATE.search(sw._clean(raw))
    assert m and m.group(1).strip() == "Ahsad U'Real Logan"


def test_defendant_falls_back_to_will_deposit_phrasing():
    """Live: SC's "deposit of will" probate filing carries no "Estate:" or
    "estate of" label at all -- 12 of 72 probate notices in one live run were
    this exact shape, every one shipping defendant=None before this fix."""
    body = ("Case Number: 2026ES4201509 2026ES4201509 The Will of Charles D. "
            "Mayes, Deceased, was delivered to me and filed September 3, "
            "2026. No proceedings for the probate of said Will have begun.")
    assert sw._defendant(body, "probate") == "Charles D. Mayes"


def test_defendant_falls_back_to_matter_of_decedent_caption():
    """Live: a Notice of Hearing ("Application for Successor Personal
    Representative") captions the decedent as "IN THE MATTER OF: X
    (Decedent)", a third probate phrasing _ESTATE_RE never matches."""
    body = "IN THE MATTER OF: JOE ALAN JOINER (Decedent) Case Number: 2019ES4200707"
    assert sw._defendant(body, "probate") == "JOE ALAN JOINER"


def test_reclassify_from_body_recognizes_a_probate_hearing_under_the_generic_label():
    """Live: a real Notice of Hearing (successor-PR application, full
    decedent + petitioner name/address/phone/email) was filed under the same
    uninformative "All Other Notices" label as a foreclosure summons and
    shipped as ListingType.UNKNOWN with every field None."""
    body = ("IN THE MATTER OF: JOE ALAN JOINER (Decedent) Notice of Hearing "
            "Purpose of Hearing: Application for Successor Personal "
            "Representative ... Relationship to Decedent/Estate: Son")
    lt, kind = sw._reclassify_from_body(sw.ListingType.UNKNOWN, "other", body)
    assert kind == "probate"
    assert lt == sw.ListingType.PROBATE_NOTICE


def test_petitioner_contact_extracted_from_hearing_notice():
    body = (
        "IN THE MATTER OF: JOE ALAN JOINER (Decedent) Case Number: 2019ES4200707 "
        "Notice of Hearing Purpose of Hearing: Application for Successor "
        "Personal Representative Executed this 15th day of September, 2026. "
        "s/ Marrin Joiner MARRIN JOINER 1250 Mimosa Lake Road Spartanburg, SC "
        "29302 Phone: 864.541.9160 Email: mpj20000@gmail.com Relationship to "
        "Decedent/Estate: Son"
    )
    assert sw._PETITIONER_SIGNATURE_RE.search(body).group(1).strip() == "Marrin Joiner"
    addr = sw._PETITIONER_ADDR_RE.search(body)
    assert addr and "1250 Mimosa Lake Road" in addr.group(1)
    phone = sw._PETITIONER_PHONE_RE.search(body)
    assert phone and "864.541.9160" in phone.group(1)
    email = sw._PETITIONER_EMAIL_RE.search(body)
    assert email and email.group(1) == "mpj20000@gmail.com"


def test_reclassify_from_body_recognizes_quiet_title_heir_action():
    """Live: a quiet-title action against "all known and unknown heirs" of
    prior owners is a real-property civil action -- the exact tangled-title/
    heir-property shape this project's motivated-seller engine targets
    elsewhere -- but shipped as ListingType.UNKNOWN before this fix."""
    body = (
        "Tiawana S. Browning, Plaintiff, vs. WSU Endeavors, Georgia Street "
        "Realty LLC, and all known and unknown heirs of any named or unnamed "
        "Defendant's and all other persons known or unknown claiming any "
        "right, title, estate interest or lien upon the real estate herein, "
        "Defendants. Amended Summons and Notice (Quiet Title)"
    )
    lt, kind = sw._reclassify_from_body(sw.ListingType.UNKNOWN, "other", body)
    assert kind == "quiet_title"
    assert lt == sw.ListingType.LIS_PENDENS
    # The generic caption parser (built for foreclosure captions) must still
    # recover the plaintiff/first-named defendant from this caption shape.
    assert sw._defendant(body, kind) == "WSU Endeavors, Georgia Street Realty LLC"


def test_vehicle_junk_detected_and_not_misfiled_as_quiet_title():
    body = ("Make: Baodiao (moped) Model: 9 Lines Year: 2025 Vin: "
            "L2BB9NCC5SB127197 Cost Due: $1,763.00 Vehicle Location: Too "
            "Transport LLC, 8926 Asheville Hwy, Boiling Springs, SC 29316")
    assert sw._VEHICLE_JUNK_RE.search(body)
    lt, kind = sw._reclassify_from_body(sw.ListingType.UNKNOWN, "other", body)
    assert kind == "other"  # confirmed junk is filtered in _row_to_listing, not reclassified
