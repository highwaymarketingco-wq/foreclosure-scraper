"""SC public notices (scpublicnotices.com, SC Press Association) — the FREE,
legal, public-by-design route to statewide SC foreclosure / tax / estate leads.

SC foreclosure is judicial and the court Public Index is scraping-prohibited, but
legal NOTICES (foreclosure summons/sale, tax sale, delinquent-tax list, public
sale, estate/creditor) must be published and are public — this site aggregates
them for all 46 counties. This fills the SC gap where ROD-probate isn't wired
(Spartanburg/Anderson/Cherokee/Oconee) and cross-checks foreclosures.

WHAT IS AND ISN'T REACHABLE (verified live 2026-07-31)
------------------------------------------------------
* Search.aspx (the results grid) serves freely — no login, no challenge. That is
  the only surface this module reads, and robots.txt allows it for a generic
  agent.
* Details.aspx (the full notice body) is CAPTCHA-walled: it returns a Cloudflare
  Turnstile + ReCaptcha "You must complete the challenge in order to continue"
  interstitial. We do NOT fetch it and we do NOT attempt to defeat it. The
  consequence is that every row here carries the grid's TRUNCATED preview
  (~270-340 chars, ending in "... click 'view' to open the full text."), so
  fields that live deep in a notice body (full legal description, bid terms,
  most property addresses) are simply unavailable. Everything parsed below comes
  from that preview, and raw.public_notice.text_truncated records the fact.

MECHANISM (ASP.NET WebForms, cookieless session in the /(S(id))/ path)
----------------------------------------------------------------------
The grid is an AJAX UpdatePanel; a bare httpx postback returns HTTP 500, so it
must be driven in a real browser (Scrapling StealthyFetcher, mirroring
ncpublicnotices.py). The ordering below is load-bearing and was established by
probing the live form:

1. Select the category in ddlPopularSearches. This does NOT filter by type — it
   fills txtSearch with a canned OR-keyword list and flips rdoType to OR.
   Selecting a category also RESETS the county filter to "Any", which is why it
   has to happen first.
2. Click the county checkboxes. Each fires its own __doPostBack; setting
   .checked from JS does nothing, because the filter is server-side state.
3. Click btnGo. Checking a county does not re-run the search on its own — until
   Go is clicked the grid still shows the statewide set.
4. Set ddlPerPage to its max (50; options are 5/10/15/20/25/30/50 — no 100),
   then page with btnNext.

WHY WE QUERY ONE COUNTY AT A TIME
---------------------------------
Each row carries a hidden `<div class="right">City: X<br>County: Y</div>`, but
that is the county of the PUBLICATION, not of the notice. Filtering on Anderson
returns rows stamped "County: Greenville" (an Anderson matter run in The
Greenville News); filtering on Oconee returns rows stamped "County: Charleston".
Checked against each notice's own subject county — the SC judicial code inside
its case number (2026-CP-**44**-00077 -> Union) or its "COUNTY OF X" caption —
the county we FILTERED on wins every disagreement (15 for, 0 against across a
live sample). So the filter county is the property county, and the row's
County:/City: are recorded as publication metadata only.

That div is still load-bearing for a different reason: it only populates once a
county filter is actually in force — on the unfiltered statewide grid it renders
EMPTY for every row. A page whose rows have no county is therefore a page whose
filter silently failed, and stamping it with the county we *meant* to select
would invent data. `_render_category` discards such pages instead.

One county at a time is also what keeps each result set inside a page or two.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.scpublicnotices.com/Search.aspx"
# Element IDs/selectors confirmed against the live grid (2026-07-31).
_DDL_POPULAR = "select[id$='_ddlPopularSearches']"
_DDL_PERPAGE = "select[id$='_ddlPerPage']"
_BTN_GO = "input[id$='_btnGo']"
_BTN_NEXT = "input[id$='_btnNext']"
_PER_PAGE_MAX = "50"
_RENDER_TIMEOUT_MS = 300000
#: Pages to pull per (category, county), 50 rows/page. Foreclosures fits inside
#: one page for every county; the tax lane runs 2-3. This is a deliberate bound
#: on run time, so a county with a very deep backlog is truncated at 150 rows —
#: results come back newest-first, so what gets cut is the oldest.
_MAX_PAGES = 3

#: Popular-search category -> (label, default listing type, kind tag).
#: NOTE: "22 Delinquent Taxes" and "26 Tax Sales" currently ship the SAME canned
#: keyword string, so they return an identical result set. fetch() drops the
#: duplicate at runtime by comparing the harvested keywords, which means we pick
#: the split up automatically if the site ever differentiates them.
_CATEGORIES: dict[str, tuple[str, ListingType, str]] = {
    "4":  ("Foreclosures",        ListingType.LIS_PENDENS,    "foreclosure"),
    "26": ("Tax Sales",           ListingType.TAX_SALE,       "tax_sale"),
    "22": ("Delinquent Taxes",    ListingType.TAX_LIEN,       "delinquent_tax"),
    "27": ("Public sales",        ListingType.AUCTION,        "public_sale"),
    "30": ("Notice to Creditors", ListingType.PROBATE_NOTICE, "probate"),
    "23": ("Probate Notices",     ListingType.PROBATE_NOTICE, "probate"),
}

_IN_SCOPE = {"spartanburg", "anderson", "pickens", "oconee", "cherokee", "union", "laurens",
             # Coastal SC (brought into scope 2026-08-12; Horry/Myrtle Beach excluded):
             "charleston", "georgetown", "colleton", "beaufort"}
#: Title-cased county names exactly as the site's checkbox labels render them.
_COUNTIES = ("Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union", "Laurens",
             "Charleston", "Georgetown", "Colleton", "Beaufort")
#: SC judicial county codes — the middle field of a CP/ES case number.
_COUNTY_CODE = {"04": "Anderson", "11": "Cherokee", "30": "Laurens", "37": "Oconee",
                "39": "Pickens", "42": "Spartanburg", "44": "Union",
                # Coastal SC (2026-08-12):
                "10": "Charleston", "22": "Georgetown", "15": "Colleton", "07": "Beaufort"}

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_ID_RE = re.compile(r"Details\.aspx\?SID=[^&]+&(?:amp;)?ID=(\d+)")
_COUNTY_RE = re.compile(r"County:\s*([A-Za-z .'-]+?)(?:\s*City:|\s*$|\s*<)", re.I)
_CITY_RE = re.compile(r"City:\s*([A-Za-z .'-]+?)\s*County:", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b|"
                      r"\b([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b")
_PUB_STRONG_RE = re.compile(r"<strong>(.*?)</strong>", re.S)
_WEEKDAY_SPLIT_RE = re.compile(r"\b(?:Sun|Mon|Tues|Wednes|Thurs|Fri|Satur)day\b")
_TRUNCATION_RE = re.compile(r"\s*\.{2,}\s*click 'view' to open the full text\.?\s*$", re.I)

# ---------------------------------------------------------------- field parsers
# SC case numbers come hyphenated and run-together, and the source OCR sometimes
# drops spaces entirely ("DOCKETNO.2024CP100003"), so we also match a
# space-stripped copy of the text.
#: Sequence runs 4-5 digits in the wild ("2024CP100003" = 2024-CP-10-0003);
#: _case_number left-pads it to the official 5 so both spellings dedupe alike.
_CP_CASE_RE = re.compile(r"\b(20\d{2})-?(CP)-?(\d{2})-?(\d{4,5})\b", re.I)
_ES_CASE_RE = re.compile(r"\b(20\d{2})-?(ES)-?(\d{2})-?(\d{4,6})\b", re.I)
# TMS / tax-map / parcel identifiers as they appear in SC notices.
_TMS_RE = re.compile(
    r"\b(?:TMS|T\.M\.S\.|Tax\s*Map(?:\s*(?:&|and)\s*Parcel)?|Parcel)\s*"
    r"(?:No\.?|Number|#|ID)?\s*[:.]?\s*"
    r"(\d[\d\s.\-]{6,24}\d)", re.I)
# "will be sold on August 3, 2026, at 11:00 AM" / "SALE DATE: 8/4/2026"
_SALE_DATE_RE = re.compile(
    r"(?:will\s+be\s+sold|sold\s+at\s+public\s+(?:auction|sale)|sale\s+date|date\s+of\s+sale|"
    r"offered\s+for\s+sale|sell\s+(?:the\s+)?(?:said\s+)?propert\w+)"
    r"[^.]{0,80}?\b((?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+20\d{2}|\d{1,2}/\d{1,2}/20\d{2})", re.I)
_SALE_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:a\.?\s?m\.?|p\.?\s?m\.?))", re.I)
_SALE_LOC_RE = re.compile(r"\bat\s+the\s+([A-Z][A-Za-z .'-]{4,60}?(?:Courthouse|Court House|"
                          r"Judicial Center))", re.I)
# Property address, anchored on the phrasings SC notices actually use.
_ADDR_RE = re.compile(
    r"(?:propert\w+\s+(?:is\s+)?(?:located\s+at|address(?:ed)?(?:\s+as)?)|"
    r"premises\s+(?:known|located)\s+as|known\s+(?:and\s+numbered\s+)?as|"
    r"having\s+the\s+address\s+of|more\s+commonly\s+known\s+as)"
    r"[:\s]+((?:\d{1,6})\s+[A-Za-z0-9][^,.;]{4,60})", re.I)
# Fallback: a bare "123 Main St" run with a real street suffix.
_ADDR_LOOSE_RE = re.compile(
    r"\b(\d{1,6}\s+[A-Z][A-Za-z0-9.'\- ]{3,40}?\s+"
    r"(?:St|Street|Rd|Road|Dr|Drive|Ln|Lane|Ave|Avenue|Ct|Court|Cir|Circle|Blvd|Boulevard|Way|"
    r"Hwy|Highway|Pl|Place|Trl|Trail|Pkwy|Parkway|Ter|Terrace)\b\.?)")
_ZIP_RE = re.compile(r"\bSC\s*(\d{5})(?:-\d{4})?\b", re.I)

# Parties. SC captions run "<PLAINTIFF>, Plaintiff, vs <DEFENDANT>, Defendant" or
# "BY VIRTUE of a decree ... in the case of: <PLAINTIFF> vs <DEFENDANT>". Every
# such caption is preceded by boilerplate (court, county, case number, notice
# title) that a greedy left-hand match happily swallows, so we cut the notice at
# the LAST caption marker before looking for parties.
_CAPTION_MARKER_RE = re.compile(
    r"\b20\d{2}-?(?:CP|ES|DR)-?\d{2}-?\d{4,6}\b"
    r"|\(\s*Non-?\s?Jury\s*\)"
    r"|\bAMENDED\s+SUMMONS\b|\bSUMMONS\s+AND\s+NOTICES?\b|\bSUMMONS\b"
    r"|\bNOTICE\s+OF\s+SALE\b|\bLEGAL\s+NOTICE\b"
    r"|\bFORECLOSURE\s+OF\s+REAL\s+ESTATE\s+MORTGAGE\b"
    r"|\b(?:IN\s+THE\s+)?COURT\s+OF\s+COMMON\s+PLEAS\b"
    r"|\bCOUNTY\s+OF\s+[A-Z][A-Za-z]+\b|\bSTATE\s+OF\s+SOUTH\s+CAROLINA\b"
    r"|\b(?:CASE|CIVIL\s+ACTION|DOCKET)\s+NO\.?:?\s*\S*|\bC/A\s+NO\.?:?\s*\S*",
    re.I)
#: The run-up to the caption in a sale notice ("BY VIRTUE of a decree heretofore
#: granted in the case of:", "VIRTUE of the judgment granted in").
_CASE_LEADIN_RE = re.compile(
    r"^.{0,120}?\b(?:heretofore\s+)?(?:granted|issued)\s+in(?:\s+the\s+case\s+of)?\s*:?\s*", re.I)
#: Where a party name ends. Must not fire on a middle initial ("Betty M. Williams")
#: and must stop at a parenthetical ("... Williams (deceased)").
_PARTY_END = (r"(?=\s*(?:,\s*(?:Defendant|C/A|Civil\s+Action|et\s+al)|[;(]|"
              r"\s+a/?k/?a\b|\s+and\s+[A-Z]|\s+AND\s+IF\b|,?\s*$))")
_PARTIES_RE = re.compile(
    r"([A-Z][A-Za-z0-9 .,'&\-]{3,90}?)\s*,?\s*"
    r"(?:Plaintiff\(?s?\)?,?\s*)?"
    r"(?:-\s*v[s.]{1,3}\.?\s*-?|\bv[s.]{1,3}\.?\s|\bagainst\s)\s*"
    r"([A-Z][A-Za-z0-9 .,'&\-]{3,70}?)" + _PARTY_END)
_VS_RE = re.compile(
    r"(?:plaintiff[s]?,?\s+)?v[s.]{1,3}\.?\s+([A-Z][A-Za-z .,'&-]{3,60}?)" + _PARTY_END, re.I)
_ESTATE_RE = re.compile(
    r"(?:estate\s+of|in\s+re:?|decedent:?)\s+([A-Z][A-Za-z .,'-]{3,60}?)"
    r"(?:,|\s+deceased|\s+date\s+of\s+death|\s*\()", re.I)
#: Estate notices come in two shapes, and only one survives truncation:
#:   (a) one estate per notice — "Estate: <NAME> Date of Death: <DATE> Case
#:       #<ES> Personal Representative: <NAME> <ADDRESS>". Everything below
#:       parses from the preview (Pickens/Laurens run this format).
#:   (b) a county roll-up — "Case Number: <ES> All persons having claims against
#:       the following estates MUST file ... with the Probate Court of X County,
#:       the address of which is ..." and the decedent names come further down,
#:       past where the preview cuts. Those rows keep the ES docket and county
#:       but carry no decedent, and Details.aspx (which has the names) is
#:       CAPTCHA-walled. Spartanburg's Notice-to-Creditors runs this format.
_PROBATE_ESTATE = re.compile(
    r"\bEstate:\s*([A-Z][A-Za-z .,'\-]{3,60}?)\s+(?:Date of Death|Case Number|Case\s*#|a/?k/?a|aka)\b",
    re.I)
_PROBATE_DOD = re.compile(
    r"Date of Death:\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", re.I)
_PROBATE_PR = re.compile(
    r"Personal Representative:?\s*([A-Z][A-Za-z .,'\-]{3,60}?)\s+"
    r"(\d{1,5}\s+[A-Za-z0-9 .,'\-]+?\b(?:SC|NC|GA|N\.C\.|S\.C\.)\s*\d{5})", re.I)

# Notice-text classifiers.
_SALE_LANG_RE = re.compile(
    r"\b(master'?s\s+sale|notice\s+of\s+sale|will\s+be\s+sold|public\s+auction|"
    r"sold\s+at\s+public\s+sale|special\s+referee|by\s+virtue\s+of\s+a\s+decree)\b", re.I)
_TAX_SALE_LANG_RE = re.compile(
    r"\b(tax\s+sale|delinquent\s+tax\s+sale|sold\s+for\s+taxes|sale\s+for\s+delinquent)\b", re.I)
#: Is this notice about TAXES at all? The canned "Tax Sales" keyword list is
#: "...property default tax+sale..." matched with OR, so the bare words
#: "property" and "default" pull in every mortgage-foreclosure summons in the
#: county. Without this check the tax lane fills up with mortgage foreclosures
#: typed as tax liens.
_TAX_TOPIC_RE = re.compile(
    r"\b(delinquent\s+tax\w*|tax\s+sale|tax\s+collector|tax\s+lien|sold\s+for\s+taxes|"
    r"forfeited\s+land|delinquent\s+propert\w+\s+tax|unpaid\s+tax\w*)\b", re.I)
#: Mortgage-foreclosure language, used to re-home notices that rode in on a
#: different category's keywords. The truncated preview often stops before the
#: word "mortgage" ever appears, so the surrounding SC-specific forms have to
#: count too: "Master in Equity", "by virtue of a decree" (the leading "BY" is
#: frequently lost to OCR), and a Non-Jury action in the Court of Common Pleas —
#: SC's equity docket, which is where foreclosure and partition live.
_MORTGAGE_TOPIC_RE = re.compile(
    r"\b(foreclosur\w+|mortgage|deed\s+of\s+trust|master'?s\s+sale|special\s+referee|"
    r"master\s+in\s+equity|(?:by\s+)?virtue\s+of\s+(?:a|the)\s+(?:decree|judgment)|"
    r"judicial\s+sale|decree\s+of\s+sale|court\s+of\s+common\s+pleas|non-?\s?jury)\b", re.I)
_PROBATE_TOPIC_RE = re.compile(
    r"\b(notice\s+to\s+creditors|estate\s+of|decedent|personal\s+representative)\b", re.I)
#: Does the notice concern REAL property at all? The keyword bundles are loose
#: enough to return ordinary civil litigation (class actions, third-party
#: construction-defect summonses). Without a property nexus a notice is not a
#: lead, and guessing a type from the category would file litigation as a
#: foreclosure or a tax sale.
_REAL_PROPERTY_RE = re.compile(
    r"\b(real\s+(?:property|estate)|described\s+premises|"
    r"all\s+that\s+(?:certain\s+)?(?:lot|piece|parcel|tract)|"
    r"lot\s+\d+[^.]{0,25}block|TMS|tax\s+map|acres?|dwelling|"
    r"propert\w+\s+(?:located|known|described)|premises\s+known)\b", re.I)
#: Notices that are unambiguously PERSONAL property (vehicles, storage units) or
#: licence applications. They match the canned keyword lists but are pure noise
#: on a real-estate board, so they never become listings. Each alternative
#: carries its own boundaries — a trailing \b after "#" can never match, which
#: would silently let every vehicle notice through.
_NOT_REAL_PROPERTY_RE = re.compile(
    r"\bvin\s*[#:]|\bvin\s+(?:no\.?|number)\b|\bself[\s-]?storage\b|"
    r"\bstorage\s+(?:unit|facility|center)\b|\bmini[\s-]?storage\b|"
    r"\bextra\s+space\s+storage\b|\bpersonal\s+property\s+described\b|"
    r"\bsell\s+personal\s+property\b|\bunclaimed\s+vehicle\b|\babandoned\s+vehicle\b|"
    r"\bbeer\s+and\s+wine\b|\boff-premises\s+consumption\b|\balcoholic\s+liquor\b|"
    r"\bnotice\s+of\s+application\b", re.I)
#: Family-court matters (DSS child welfare, TPR, adoption) ride in on the
#: Foreclosures keyword list because it includes the word "judgment". They are
#: not property leads, and the repo has a separate divorce lane, so drop them.
_FAMILY_COURT_RE = re.compile(
    r"\b(in\s+the\s+family\s+court|20\d{2}-?DR-?\d{2}|in\s+the\s+interest\s+of|"
    r"termination\s+of\s+parental\s+rights|minor\s+child(?:ren)?\s+under)\b", re.I)
#: Ordinary civil litigation that reaches us only because it is filed in the
#: Court of Common Pleas — class actions and construction-defect impleaders run
#: service-by-publication notices that look structurally like a foreclosure
#: summons. Nothing here concerns a property we could buy.
_CIVIL_LITIGATION_RE = re.compile(
    r"\b(similarly\s+situated|class\s+action|third-?party\s+summons|"
    r"personal\s+injury|wrongful\s+death|medical\s+malpractice|"
    r"breach\s+of\s+contract|products?\s+liability)\b", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ")
                  .replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')).strip()


def _despace(s: str) -> str:
    """OCR in these notices sometimes drops every space ("CASENO.2026CP4400077").
    A space-stripped copy lets the structural regexes (case numbers) still hit."""
    return re.sub(r"\s+", "", s or "")


def _result_blocks(html: str) -> Iterable[str]:
    """Yield one HTML fragment per result. The live render wraps each result in
    its own <table class="nested"> (metadata row + a sibling row holding the
    truncated preview text); the unit-test fixtures use a flat single <tr> per
    result. Prefer nested-table blocks; fall back to per-<tr> so both shapes work."""
    blocks = re.findall(r'<table class="nested".*?</table>', html, re.S)
    if blocks:
        yield from blocks
        return
    yield from _ROW_RE.findall(html)


def _parse_results(html: str) -> list[dict]:
    """Parse the results GridView into notice dicts (publication/date/city/county/text/id)."""
    out: list[dict] = []
    for block in _result_blocks(html):
        m = _ID_RE.search(block)
        if not m:
            continue
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
        cells = [c for c in cells if c and "javascript" not in c.lower()]
        meta = next((c for c in cells if "county:" in c.lower()), "")
        # body = the longest non-metadata cell (the notice text / truncated preview).
        body = max((c for c in cells if "county:" not in c.lower()), key=len, default="")
        body = _TRUNCATION_RE.sub("", body)
        # Publication name: the live grid bolds it; the flat fixture shape doesn't,
        # so fall back to the words before the weekday.
        strong = _PUB_STRONG_RE.search(block)
        publication = (_clean(strong.group(1)) if strong
                       else _clean(_WEEKDAY_SPLIT_RE.split(meta, maxsplit=1)[0]))
        county_m = _COUNTY_RE.search(meta)
        city_m = _CITY_RE.search(meta)
        date_m = _DATE_RE.search(meta)
        out.append({
            "notice_id": m.group(1),
            "county": (county_m.group(1).strip() if county_m else ""),
            "city": (city_m.group(1).strip() if city_m else ""),
            "date_text": (date_m.group(1) or date_m.group(2)) if date_m else "",
            "publication": publication,
            "text": body,
        })
    return out


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip().rstrip(",")
    for fmt in ("%m/%d/%Y", "%A, %B %d, %Y", "%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _case_number(text: str) -> tuple[str | None, str | None]:
    """Return (normalized case number, SC judicial county code) from a CP/ES caption."""
    for rx in (_CP_CASE_RE, _ES_CASE_RE):
        for hay in (text, _despace(text)):
            m = rx.search(hay)
            if m:
                yr, kind, code, seq = m.groups()
                return f"{yr}-{kind.upper()}-{code}-{seq.zfill(5)}", code
    return None, None


def _parcel_id(text: str) -> str | None:
    m = _TMS_RE.search(text)
    if not m:
        return None
    tms = re.sub(r"\s+", "", m.group(1)).strip(".-")
    digits = re.sub(r"\D", "", tms)
    # Reject short runs / bare years that the loose prefix can pick up.
    if not 8 <= len(digits) <= 18:
        return None
    return tms


def _street_address(text: str) -> str | None:
    m = _ADDR_RE.search(text) or _ADDR_LOOSE_RE.search(text)
    return _clean(m.group(1)) if m else None


def _strip_caption(text: str) -> str:
    """Drop the court/county/case-number boilerplate that precedes the party
    caption, so a greedy plaintiff match can't absorb it."""
    head = text[:400]
    last = None
    for m in _CAPTION_MARKER_RE.finditer(head):
        last = m
    body = text[last.end():].lstrip(" ,.:;-") if last else text
    return _CASE_LEADIN_RE.sub("", body, count=1)


def _parties(text: str, kind: str) -> tuple[str | None, str | None]:
    """Return (plaintiff, defendant). Probate notices name a decedent instead."""
    if kind == "probate":
        m = _PROBATE_ESTATE.search(text) or _ESTATE_RE.search(text)
        return None, (_clean(m.group(1)) if m else None)
    body = _strip_caption(text)
    m = _PARTIES_RE.search(body) or _PARTIES_RE.search(text)
    if m:
        return (_clean(m.group(1)) or None), (_clean(m.group(2)) or None)
    m = _VS_RE.search(body) or _VS_RE.search(text)
    return None, (_clean(m.group(1)) if m else None)


def _refine_type(default: ListingType, kind: str, text: str) -> ListingType | None:
    """Type the lead from the notice's own language, not from which category
    surfaced it. Returns None when the notice is not a property matter at all,
    in which case the caller drops it.

    The popular-search categories are OR-keyword bundles, not type filters, and
    the bundles are loose: "Tax Sales" carries the bare words *property* and
    *default*, "Public sales" carries *property* and *auction*, "Foreclosures"
    carries *judgment*. Each therefore returns a large slice of the others'
    notices plus a tail of ordinary civil litigation. Typing off the category
    alone files mortgage foreclosures as tax liens and class-action summonses as
    pre-foreclosures. The probate categories are the exception — they are
    precise, and their notices legitimately mention mortgages and deceased
    owners.
    """
    if kind == "probate":
        return default
    if _TAX_TOPIC_RE.search(text):
        return ListingType.TAX_SALE if _TAX_SALE_LANG_RE.search(text) else ListingType.TAX_LIEN
    if _MORTGAGE_TOPIC_RE.search(text):
        return (ListingType.FORECLOSURE_SALE if _SALE_LANG_RE.search(text)
                else ListingType.LIS_PENDENS)
    if _PROBATE_TOPIC_RE.search(text):
        return ListingType.PROBATE_NOTICE
    if _REAL_PROPERTY_RE.search(text):
        # Real property changing hands, but none of the lanes above claimed it
        # (a county land sale, a partition sale, an HOA auction).
        return ListingType.AUCTION if kind == "public_sale" else default
    return None


def _to_listing(n: dict, cat: str, slug: str) -> Listing | None:
    # The county we FILTERED on is the notice's subject county; the row's own
    # County:/City: describe the newspaper that ran it (see module docstring).
    # Fall back to the row county only when there was no filter (unit fixtures).
    county = (n.get("filter_county") or n.get("county") or "").strip()
    if county.lower() not in _IN_SCOPE:
        return None
    label, default_type, kind = _CATEGORIES[cat]
    text = n["text"]
    if (_NOT_REAL_PROPERTY_RE.search(text) or _FAMILY_COURT_RE.search(text)
            or _CIVIL_LITIGATION_RE.search(text)):
        return None  # vehicle / storage / licence / family court / general civil suit

    lt = _refine_type(default_type, kind, text)
    if lt is None:
        return None  # ordinary civil litigation with no property nexus
    # Because the keyword bundles overlap, an estate notice can first surface
    # under the tax or public-sale category. Follow the refined TYPE, not the
    # category, so party extraction and the probate enrichment agree with it.
    kind = "probate" if lt is ListingType.PROBATE_NOTICE else kind
    plaintiff, defendant = _parties(text, kind)
    case_number, case_county_code = _case_number(text)
    parcel_id = _parcel_id(text)
    street_address = _street_address(text)

    sd = _SALE_DATE_RE.search(text)
    sale_date = _parse_date(sd.group(1)) if sd else None
    st = _SALE_TIME_RE.search(text)
    sale_time = _clean(st.group(1)) if st else None
    sl = _SALE_LOC_RE.search(text)
    sale_location = _clean(sl.group(1)) if sl else None
    zm = _ZIP_RE.search(text)
    zip_code = zm.group(1) if zm else None

    published = _parse_date(n.get("date_text", ""))
    raw: dict = {
        "public_notice": {
            "notice_id": n["notice_id"],
            "publication": n.get("publication") or None,
            "published_date": published.date().isoformat() if published else None,
            "category": cat,
            "category_label": label,
            # City/County as rendered on the row = where the paper is, not the
            # property. Kept for provenance, never used as the lead's county.
            "publication_city": n.get("city") or None,
            "publication_county": n.get("county") or None,
            "filtered_county": n.get("filter_county") or None,
            "text": text[:4000],
            # Details.aspx is CAPTCHA-walled, so this is the grid preview only.
            "text_truncated": True,
        }
    }
    # County cross-check: the SC judicial code inside the case number should agree
    # with the county we filtered on. Record disagreement rather than guessing.
    if case_county_code:
        implied = _COUNTY_CODE.get(case_county_code)
        if implied and implied.lower() != county.lower():
            raw["public_notice"]["county_code_mismatch"] = {
                "assigned": county, "case_number_implies": implied}

    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": "public_notice",
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
        prm = _PROBATE_PR.search(text)
        dod = _PROBATE_DOD.search(text)
        raw["probate"] = {
            "decedent": defendant or None,
            "date_of_death": (dod.group(1) if dod else None),
            "personal_representative": (_clean(prm.group(1)) if prm else None),
            "pr_address": (_clean(prm.group(2)) if prm else None),
            # Only a real ES docket belongs here — _case_number prefers CP, and a
            # creditor notice can name the decedent's unrelated civil case.
            "es_case_number": (case_number if (case_number or "").split("-")[1:2] == ["ES"]
                               else None),
        }
        street_address = None  # an estate notice carries no property address

    return Listing(
        source=slug,
        source_url=f"https://www.scpublicnotices.com/Details.aspx?ID={n['notice_id']}",
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state="SC", county=county.title(),
        zip_code=zip_code,
        plaintiff=plaintiff,
        defendant=defendant,
        street_address=street_address,
        parcel_id=parcel_id,
        case_number=case_number,
        sale_date=sale_date,
        sale_time=sale_time,
        sale_location=sale_location,
        # SC mortgage foreclosure is judicial; tax lanes run the tax track.
        # Keyed off the refined type so a retyped notice stays consistent.
        foreclosure_process=(
            "judicial" if lt in (ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS)
            else "tax" if lt in (ListingType.TAX_SALE, ListingType.TAX_LIEN) else None),
        description=(text[:200] or f"{label} notice"),
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


# --------------------------------------------------------------------- browser
_JS_CLICK_COUNTY = """(label) => {
  // Set the county filter to EXACTLY one county. Each click fires its own
  // __doPostBack, so the caller re-invokes this until it returns 'done'.
  for (const li of document.querySelectorAll("ul[id$='_lstCounty'] li")) {
    const lb = li.querySelector('label'), cb = li.querySelector('input[type=checkbox]');
    if (!lb || !cb) continue;
    if (cb.checked && lb.textContent.trim() !== label) { cb.click(); return 'uncheck'; }
  }
  for (const li of document.querySelectorAll("ul[id$='_lstCounty'] li")) {
    const lb = li.querySelector('label'), cb = li.querySelector('input[type=checkbox]');
    if (!lb || !cb) continue;
    if (lb.textContent.trim() === label && !cb.checked) { cb.click(); return 'check'; }
  }
  return 'done';
}"""

_JS_SELECTED_COUNTIES = """() => Array.from(
  document.querySelectorAll("ul[id$='_lstCounty'] li"))
  .filter(li => { const c = li.querySelector('input[type=checkbox]'); return c && c.checked; })
  .map(li => li.querySelector('label').textContent.trim())"""

_JS_STATE = """() => {
  const t = document.querySelector("input[id$='_txtSearch']");
  const m = document.body.innerText.match(/Page\\s+(\\d+)\\s+of\\s+([\\d,]+)\\s+Pages?/i);
  return {
    rows: document.querySelectorAll("input[id$='_btnView2']").length,
    keywords: t ? t.value : null,
    page: m ? +m[1] : null,
    pages: m ? +m[2].replace(/,/g, '') : null,
  };
}"""


async def _settle(page, quiet_ms: int = 1600) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    try:
        await page.wait_for_timeout(quiet_ms)
    except Exception:
        pass


async def _select_category(page, cat: str) -> str:
    """Pick the popular-search category and wait for its canned keywords to land.
    Returns the keyword string (used to dedupe categories that share one)."""
    await page.select_option(_DDL_POPULAR, cat, timeout=15000)
    try:
        await page.wait_for_function(
            "() => { const t = document.querySelector(\"input[id$='_txtSearch']\");"
            " return t && t.value.trim().length > 0; }", timeout=30000)
    except Exception:
        pass
    await _settle(page)
    try:
        return await page.eval_on_selector("input[id$='_txtSearch']", "e => e.value") or ""
    except Exception:
        return ""


async def _apply_county(page, county: str) -> bool:
    """Drive the checkbox postbacks until exactly `county` is selected."""
    for _ in range(len(_COUNTIES) + 3):
        try:
            action = await page.evaluate(_JS_CLICK_COUNTY, county)
        except Exception:
            return False
        if action == "done":
            break
        await _settle(page, 1100)
    try:
        return await page.evaluate(_JS_SELECTED_COUNTIES) == [county]
    except Exception:
        return False


async def _collect_pages(page) -> list[str]:
    """Snapshot page 1, then click Next up to _MAX_PAGES. Returns raw HTML pages."""
    out: list[str] = []
    try:
        out.append(await page.content())
    except Exception:
        return out
    for _ in range(_MAX_PAGES - 1):
        try:
            st = await page.evaluate(_JS_STATE)
            if st.get("page") and st.get("pages") and st["page"] >= st["pages"]:
                break
            btn = await page.query_selector(_BTN_NEXT)
            if not btn or not await btn.is_enabled():
                break
            await btn.click(timeout=12000)
            await _settle(page, 2200)
            out.append(await page.content())
        except Exception:
            break
    return out


async def harvest_category_keywords() -> dict[str, str]:
    """One cheap render that reads the canned keyword string behind each
    popular-search category. Categories that share a string return an identical
    result set, so fetch() runs only one of them."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("scpublicnotices.scrapling_missing")
        return {}
    found: dict[str, str] = {}

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        for cat in _CATEGORIES:
            try:
                kw = await _select_category(page, cat)
                if kw:
                    found[cat] = " ".join(kw.split())
            except Exception:
                continue

    try:
        await StealthyFetcher.async_fetch(
            _BASE, headless=True, network_idle=True,
            timeout=_RENDER_TIMEOUT_MS, page_action=page_action)
    except Exception as exc:
        log.warning("scpublicnotices.harvest_fail", error=str(exc)[:200])
    return found


def _distinct_categories(keywords: dict[str, str]) -> list[str]:
    """Keep one category per distinct keyword string, in _CATEGORIES order."""
    if not keywords:
        return list(_CATEGORIES)
    kept: list[str] = []
    seen: dict[str, str] = {}
    for cat in _CATEGORIES:
        kw = keywords.get(cat)
        if kw is None:          # harvest missed it — run it rather than lose it
            kept.append(cat)
            continue
        if kw in seen:
            log.info("scpublicnotices.duplicate_category", category=cat, same_as=seen[kw])
            continue
        seen[kw] = cat
        kept.append(cat)
    return kept


async def _render_category(cat: str, counties: Iterable[str] = _COUNTIES) -> list[dict]:
    """Drive one popular-search category across the footprint counties.

    One browser session per category: select the category once (it resets the
    county filter, so it must come first), then for each county toggle the
    checkbox set, click Go, max out per-page and page through. Returns notice
    dicts stamped with `filter_county`. Never raises — returns what it got.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("scpublicnotices.scrapling_missing")
        return []

    rows: list[dict] = []
    seen: set[str] = set()

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        if not await _select_category(page, cat):
            log.warning("scpublicnotices.category_no_keywords", category=cat)
            return
        for county in counties:
            try:
                if not await _apply_county(page, county):
                    # Never fall back to an unfiltered search — a statewide grid
                    # would be mis-stamped with this county.
                    log.warning("scpublicnotices.county_filter_unconfirmed",
                                category=cat, county=county)
                    continue
                await page.click(_BTN_GO, timeout=15000)
                await _settle(page, 2200)
                try:
                    await page.select_option(_DDL_PERPAGE, _PER_PAGE_MAX, timeout=12000)
                    await _settle(page, 1800)
                except Exception:
                    pass
                found = unstamped = 0
                for html in await _collect_pages(page):
                    parsed = _parse_results(html)
                    # A page whose rows carry no County: metadata was NOT filtered
                    # (the statewide grid renders those divs empty). Stamping it
                    # with the county we meant to select would invent data.
                    if parsed and not any(n["county"] for n in parsed):
                        unstamped += len(parsed)
                        continue
                    for n in parsed:
                        if not n["county"] or n["notice_id"] in seen:
                            continue
                        seen.add(n["notice_id"])
                        n["filter_county"] = county
                        rows.append(n)
                        found += 1
                if unstamped:
                    log.warning("scpublicnotices.unfiltered_page_discarded",
                                category=cat, county=county, rows=unstamped)
                log.info("scpublicnotices.county_done", category=cat, county=county, rows=found)
            except Exception as exc:
                log.warning("scpublicnotices.county_failed", category=cat, county=county,
                            error=str(exc)[:200])

    try:
        await StealthyFetcher.async_fetch(
            _BASE, headless=True, network_idle=True,
            timeout=_RENDER_TIMEOUT_MS, page_action=page_action,
        )
    except Exception as exc:
        log.warning("scpublicnotices.fetch_fail", category=cat, error=str(exc)[:200])
        return rows

    log.info("scpublicnotices.category_done", category=cat, rows=len(rows))
    return rows


class SCPublicNotices(BaseScraper):
    slug = "counties_sc.sc_public_notices"
    name = "SC Public Notices (scpublicnotices.com — foreclosure/tax/estate/public sale)"
    category = "public_notices"
    #: A live sweep returns ~600 in-scope leads; this floor only has to catch a
    #: collapse (site redesign, filter stops applying), not police normal churn.
    expected_min_count = 100
    #: Measured 2026-07-31: 42s keyword harvest + ~75s per category (7 counties
    #: x Go/perPage/paginate) = ~7 min for the 5 distinct keyword sets.
    timeout_s = 1200.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # The categories are overlapping keyword bundles, so the same notice id
        # comes back under several of them. Keep the first sighting — _CATEGORIES
        # runs most-specific-first — so one notice yields exactly one lead.
        seen_ids: set[str] = set()
        cats = _distinct_categories(await harvest_category_keywords())
        log.info("scpublicnotices.plan", categories=cats)
        for cat in cats:
            try:
                notices = await _render_category(cat)
            except Exception:
                log.warning("scpublicnotices.category_failed", category=cat)
                continue
            new = 0
            for n in notices:
                if n["notice_id"] in seen_ids:
                    continue
                seen_ids.add(n["notice_id"])
                try:
                    li = _to_listing(n, cat, self.slug)
                except Exception:
                    log.warning("scpublicnotices.parse_failed",
                                category=cat, notice_id=n.get("notice_id"))
                    continue
                if li:
                    out.append(li)
                    new += 1
            log.info("scpublicnotices.category_leads", category=cat,
                     seen=len(notices), new_leads=new)
        log.info("scpublicnotices.done", leads=len(out))
        return out
