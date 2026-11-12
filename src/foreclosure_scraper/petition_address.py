"""Debtor residence + county from a bankruptcy petition that CourtListener already holds for free.

WHY THIS EXISTS (feasibility study, 2026-10-06). The board carries thousands of
national.courtlistener_bankruptcy rows with NO county, street address or parcel:
a bankruptcy docket names the debtor and nothing else. CourtListener's party
objects carry no address (measured: 0 of 280 sampled dockets had a party address;
the party rows that exist are U.S. Trustee / trustee / chapter 11 debtors with an
empty extra_info), and a name alone is not identity evidence (the project's own
verification ledger refuted most name-only property matches).

The one identity-grade source is the debtor's own sworn petition. For an
individual that is Official Form 101, whose item 5 ("Where you live") prints the
street, city, state, ZIP and COUNTY. When some RECAP user has already bought the
petition from PACER and donated it, CourtListener serves it for free at
https://storage.courtlistener.com/<filepath_local> (is_available=True). Fetching
that is within CourtListener's public terms; PACER itself is OFF LIMITS and this
module never touches it. A petition that is NOT already archived is simply
skipped, never bought, never requested.

The petition PDFs filed through CM/ECF carry a real text layer, so the address is
read locally with pdfplumber and a regex: no OCR, no Gemini call, no API cost.
(The generic enrichment_doc_ocr prompt is written for foreclosure notices; on a
petition it would file the debtor's RESIDENCE as the "subject property" with no
county, which is the wrong claim, see parse_form101_text.)

WHAT THE RESULT MEANS. The address is where the debtor LIVES. It is not proof the
debtor OWNS it. It is identity-grade for "this debtor lives in this county", and
the county plus street is exactly what is needed to resolve the parcel and check
the assessor's owner of record (see enrichment_bankruptcy_property). Callers must
treat it as a residence, not as a confirmed owned property.

This module is pure parsing and selection: it performs no network I/O and never
writes the board. `apply_petition_address` mutates only the Listing it is handed.
"""
from __future__ import annotations

import io
import re
from typing import Any, Iterable, Optional

STORAGE_BASE = "https://storage.courtlistener.com/"

# Lines of the Form 101 "Where you live" block that are printed labels, not values.
_LABEL = re.compile(
    r"^(number[, ]+(p\.?o\.? box[, ]+)?street|city\s+state|p\.?o\.? box\b|"
    r"if your mailing address|above, fill it in|notices to you|if debtor 2|about debtor|"
    r"your employer|identification number|ein\b|\(ein\)|county\b)",
    re.I,
)
_CITY_ST_ZIP = re.compile(
    r"^(?P<city>[A-Za-z][A-Za-z .'\-]*?),?\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?\b"
)
_COUNTY_LABEL = re.compile(r"^County(\s+County)?\s*$", re.I)
_WHERE = re.compile(r"where\s+you\s+live", re.I)
_RULE = re.compile(r"^[_\-\s]{5,}$")
_COUNTY_SAME_LINE = re.compile(r"^(?P<county>[A-Za-z][A-Za-z .'\-]*?)\s+County(?:\s+County)?\s*$")
_COUNTY_VALUE = re.compile(r"[A-Za-z][A-Za-z .'\-]{1,30}")
_LABEL_WORDS = re.compile(r"\b(city|zip|code|state|street|number|county|box)\b", re.I)
_DEBTOR1 = re.compile(r"Debtor\s*1\s+(?P<name>[A-Z][A-Za-z.'\- ]{2,60}?)\s+Case\s+number", re.I)

# Documents that mention a voluntary petition without being the petition.
_NOT_THE_PETITION = re.compile(
    r"plan|means\s+test|schedule|statement|valuation|exhibit|amend|notice|order|"
    r"objection|motion|certificate|application", re.I)
_PETITION_DESC = re.compile(r"voluntary\s+petition", re.I)
# A docket entry's text trails off into fee amounts, attachment lists and clerk notes
# ("SEE DEFECTIVE NOTICE", "Attachments: Exhibit ..."). Only the leading title says what it is.
_DESC_TAIL = re.compile(r"\s-\s|\(Attachments|Modified on|\(Entered|\([A-Z][a-z]+, [A-Z][a-z]+\)")


def parse_form101_text(text: str | None) -> Optional[dict[str, Any]]:
    """Debtor 1's residence from the text of an Official Form 101 petition.

    Returns {street, city, state, zip, county, debtor_name} (any value may be
    None) or None when the text is not an individual petition (Form 201 for
    non-individuals has no "Where you live" item). Only the LEFT column (Debtor 1)
    and only the residence block are read: the separate mailing-address block that
    follows it is a different address and is cut off first.
    """
    if not text:
        return None
    m = _WHERE.search(text)
    if not m:
        return None
    seg = text[m.end(): m.end() + 1100]
    stop = re.search(r"why\s+you\s+are\s+choosing", seg, re.I)
    if stop:
        seg = seg[: stop.start()]
    mail = re.search(r"if\s+your\s+mailing\s+address", seg, re.I)
    if mail:
        seg = seg[: mail.start()]
    # form-filled petitions print an underscore rule under every value; drop those lines
    lines = [ln.strip() for ln in seg.splitlines() if ln.strip() and not _RULE.match(ln.strip())]

    county = county_idx = None
    for i, ln in enumerate(lines):
        if _COUNTY_LABEL.match(ln) and i > 0:
            county, county_idx = lines[i - 1], i - 1
            break
        sm = _COUNTY_SAME_LINE.match(ln)  # "Horry County" with the value on the label's own line
        if sm:
            county, county_idx = sm.group("county"), i
            break
    city = state = zipc = None
    for i, ln in enumerate(lines):
        cm = _CITY_ST_ZIP.match(ln)
        if cm and i != county_idx:
            city, state, zipc = cm.group("city").strip(), cm.group("state"), cm.group("zip")
            break
    street = None
    for ln in lines:
        if _LABEL.match(ln) or _CITY_ST_ZIP.match(ln):
            continue
        if re.match(r"^\d[\w\-/]*\s", ln) and re.search(r"[A-Za-z]{3}", ln):
            street = ln
            break
    if county and not _COUNTY_VALUE.fullmatch(county):
        county = None
    if county and _LABEL_WORDS.search(county):
        county = None
    if not (street or city):
        return None
    dm = _DEBTOR1.search(text)
    return {
        "street": street, "city": city, "state": state, "zip": zipc,
        "county": county, "debtor_name": dm.group("name").strip() if dm else None,
    }


def pick_petition_doc(recap_documents: Iterable[dict] | None) -> Optional[dict]:
    """The already-archived voluntary-petition document among a docket's recap docs.

    Requires is_available AND a filepath_local (CourtListener holds the bytes);
    anything else would mean buying it from PACER and is never selected. Plans,
    schedules, means tests and notices that merely mention the petition are
    excluded.
    """
    for rd in recap_documents or []:
        if not isinstance(rd, dict):
            continue
        desc = rd.get("short_description") or rd.get("description") or ""
        if not (rd.get("is_available") and rd.get("filepath_local")):
            continue
        title = _DESC_TAIL.split(desc)[0]
        if _PETITION_DESC.search(title) and not _NOT_THE_PETITION.search(
                _PETITION_DESC.sub("", title)):
            return rd
    return None


def petition_pdf_url(recap_doc: dict) -> str:
    return STORAGE_BASE + str(recap_doc["filepath_local"]).lstrip("/")


def candidate_from_search_hit(hit: dict, court: str | None = None) -> Optional[dict]:
    """{docket_id, court, doc_url, description} for a /search/?type=r hit whose
    voluntary petition is already archived, else None."""
    doc = pick_petition_doc(hit.get("recap_documents"))
    if not doc or not hit.get("docket_id"):
        return None
    return {
        "docket_id": hit["docket_id"],
        "court": hit.get("court_id") or court,
        "doc_url": petition_pdf_url(doc),
        "description": doc.get("short_description") or doc.get("description") or "",
    }


def petition_text(pdf_bytes: bytes, max_pages: int = 5) -> Optional[str]:
    """Text layer of the first pages of a petition PDF; None if it is image-only."""
    try:
        import pdfplumber

        chunks: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:max_pages]:
                chunks.append(page.extract_text() or "")
        text = "\n".join(chunks)
        return text if len(text.strip()) >= 200 else None
    except Exception:
        return None


def parse_petition_pdf(pdf_bytes: bytes) -> Optional[dict[str, Any]]:
    return parse_form101_text(petition_text(pdf_bytes))


_NAME_TOKEN = re.compile(r"[^A-Z]")


def _name_tokens(s: str | None) -> list[str]:
    return [t for t in (_NAME_TOKEN.sub("", w.upper()) for w in (s or "").split()) if len(t) > 1]


def debtor_name_agrees(case_name: str | None, petition_name: str | None) -> bool:
    """The petition's Debtor 1 name must share its surname and given name with the
    docket's case name, so a misfiled or mis-attributed document is never applied."""
    cn, pn = _name_tokens(case_name), _name_tokens(petition_name)
    if len(pn) < 2 or not cn:
        return False
    return pn[0] in cn and pn[-1] in cn


def debtor_name_conflicts(case_name: str | None, petition_name: str | None) -> bool:
    """True only when the petition names a Debtor 1 AND that name disagrees with the
    docket's case name. A petition whose layout hides the name line (about 1 in 5
    of the 85 measured) is not treated as a conflict: it came from the same docket."""
    if not petition_name:
        return False
    return not debtor_name_agrees(case_name, petition_name)


def apply_petition_address(li: Any, parsed: dict[str, Any], *, document_url: str,
                           court_state: str | None = None,
                           case_name: str | None = None) -> list[str]:
    """Record the petition evidence on `li.raw["bankruptcy_petition"]` and fill
    BLANK county/street/city/state/zip. Never overwrites a value already set.

    Returns the names of the fields filled (empty, and nothing recorded, when the
    petition's Debtor 1 name conflicts with `case_name`). The caller decides when to
    run this; nothing here persists or publishes anything.
    """
    if case_name is not None and debtor_name_conflicts(case_name, parsed.get("debtor_name")):
        return []
    raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
    li.raw = raw
    state = parsed.get("state")
    raw["bankruptcy_petition"] = {
        "form": "101",
        "residence_street": parsed.get("street"),
        "residence_city": parsed.get("city"),
        "residence_state": state,
        "residence_zip": parsed.get("zip"),
        "residence_county": parsed.get("county"),
        "document_url": document_url,
        "kind": "residence_not_proof_of_ownership",
        "state_differs_from_court": bool(state and court_state and state != court_state),
    }
    filled: list[str] = []
    for src, attr in (("county", "county"), ("street", "street_address"),
                      ("city", "city"), ("state", "state"), ("zip", "zip_code")):
        val = parsed.get(src)
        if val and not (getattr(li, attr, None) or ""):
            setattr(li, attr, str(val).strip())
            filled.append(attr)
    return filled
