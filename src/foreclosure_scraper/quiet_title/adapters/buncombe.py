"""Buncombe County NC: the county where every step of the intake is free and proven.

SOURCES (all free, no login; each read live, spaced by the PoliteFetcher)
  * County parcel layer, gis.buncombecounty.org property_bc_dis/MapServer/1 (ArcGIS JSON):
    owner, care-of, mailing address, situs, the deed the county cites (DeedBook/DeedPage/
    DeedDate/Instrument), plat and subdivision references, acreage, class, improved flag,
    values, layer update date. THE LAYER HAS NO LEGAL-DESCRIPTION FIELD (its 58 fields were
    read live on 2026-10-07); the adapter still checks the returned field list on every run and
    uses such a field if the county ever adds one. Otherwise the legal description needs the deed
    image, which the sheet links by book and page.
  * Tax Lookup, tax.buncombenc.gov: /Parcel/Details/<PIN> (every bill with its amount due) and
    /Bill/Details/<bill> (the transaction lines). The page shows a user-agreement pop-up for a
    person to accept; the content is served without any login. A bill in legal collection shows
    'See Legal' instead of an amount: kept as text, never read as zero.
  * Register of Deeds, Cott eSearch, guest session (registerofdeeds.buncombenc.gov; the searches
    are in cott_v4.py, shared with Polk):
      - Book/Page search by GET (SrchBookPage.aspx?bAutoSearch=true&bk=&pg=&idx=ALL), the link
        the county's own tax page uses for 'View Deed'. Pre-1995 deeds and deeds of trust were
        kept in separate book series, so one book/page can hold two instruments: the entry whose
        date equals the county's deed date is the one the county cites.
      - Document Details by the grid's own postback (same session).
      - Name search (SrchName.aspx, the WebForms POST a person's browser sends), index All or
        DEATHS. Results come 500 to a page; a longer list is reported as cut.
    Document IMAGES are not opened: the sheet links them for a person.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..fetch import Walled
from ..model import OtherParcel, Parcel, RecordCheck, TaxBill, TaxStatus, TaxTransaction
from ..names import PersonName
from ..taxyears import split_years
from .base import CountyAdapter
from .cott_v4 import _parties, hidden_fields, mdy_iso, parse_rod_detail, parse_rod_grid  # noqa: F401 (re-exported)
from .cott_v4 import CottV4Register

GIS_LAYER = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1"
TAX = "https://tax.buncombenc.gov"
ROD = "https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/"
ROD_NAME = ROD + "SrchName.aspx"
ROD_BOOKPAGE = ROD + "SrchBookPage.aspx"
GIS_RETRY_WAITS = (0, 5, 15, 30)
_LEGAL_FIELD = re.compile(r"legal|lgl|legdesc", re.I)
_BILL = re.compile(r"^(\d{10})-(\d{4})-(\d{4})-(\d{4})-(\d{2})$")
_TYPES = {"RD", "ROAD", "ST", "STREET", "DR", "DRIVE", "LN", "LANE", "AVE", "AVENUE", "CT", "COURT",
          "CIR", "CIRCLE", "WAY", "TRL", "TRAIL", "HWY", "HIGHWAY", "PL", "PLACE", "BLVD", "PKWY",
          "LOOP", "RUN", "TER", "TERRACE", "XING", "PT", "COVE", "CV", "EXT", "SQ"}
_DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}

SRC_GIS = "Buncombe County GIS parcel layer (property_bc_dis)"
SRC_TAX = "Buncombe County Tax Lookup (tax.buncombenc.gov)"
SRC_ROD = "Buncombe County Register of Deeds, eSearch (guest)"


# ---------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ---------------------------------------------------------------------------------------------

def money(s: Optional[str]) -> Optional[float]:
    """'$1,234.56' -> 1234.56; '($85.34)' -> -85.34; 'See Legal' -> None."""
    t = (s or "").strip()
    m = re.fullmatch(r"\(?\s*-?\$?\s*([\d,]+(?:\.\d+)?)\s*\)?", t)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return -v if t.startswith("(") or t.startswith("-") else v


def ymd(s: Optional[str]) -> Optional[str]:
    """'19800801' -> '1980-08-01'."""
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s) and s != "00000000":
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


def iso_mdy(s: Optional[str]) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return f"{m.group(2)}/{m.group(3)}/{m.group(1)}" if m else ""


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def _strip0(s: Optional[str]) -> str:
    return (s or "").strip().lstrip("0") or ("0" if (s or "").strip() else "")


def street_key(addr: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'12 EXAMPLE RIDGE RD' -> ('12', 'EXAMPLE RIDGE'): house number and the street name as the
    county layer keys it (no type, no direction). (None, None) for a PO box or no number."""
    s = re.sub(r"\s+", " ", (addr or "").upper().replace(".", " ")).strip()
    m = re.match(r"^(\d+)[A-Z]?\s+(.+)$", s)
    if not m or s.startswith("PO ") or "BOX" in s.split():
        return None, None
    words = m.group(2).split()
    if words and words[0] in _DIRS:
        words = words[1:]
    while words and (words[-1] in _TYPES or words[-1] in _DIRS):
        words = words[:-1]
    return m.group(1), " ".join(words) or None


def parse_gis(j: dict) -> tuple[list[dict], list[str]]:
    """(feature attribute dicts, the layer's field names). ValueError on an ArcGIS error body."""
    if not isinstance(j, dict) or "error" in j:
        raise ValueError(f"ArcGIS error body: {str(j.get('error') if isinstance(j, dict) else j)[:200]}")
    fields = [f.get("name") for f in j.get("fields") or [] if f.get("name")]
    return [f.get("attributes") or {} for f in j.get("features") or []], fields


def parcel_from_attrs(pin: str, a: dict, fields: list[str]) -> Parcel:
    p = Parcel(pin=pin, found=True, field_names=list(fields))
    p.owner = (a.get("owner") or "").strip() or None
    p.care_of = (a.get("CareOf") or "").strip() or None
    mail = (a.get("Address") or "").strip()
    city = " ".join(x for x in [(a.get("CityName") or "").strip(), (a.get("State") or "").strip(),
                                (a.get("Zipcode") or "").strip()] if x)
    p.mailing = ", ".join(x for x in [mail, city] if x) or None
    p.mailing_house_number, p.mailing_street = street_key(mail)
    hn = (a.get("HouseNumber") or "").strip()
    street = " ".join(x for x in [(a.get("direction") or "").strip(), (a.get("streetname") or "").strip(),
                                  (a.get("StreetType") or "").strip(), (a.get("PostDirection") or "").strip()] if x)
    p.situs_street = (a.get("streetname") or "").strip() or None
    if hn and hn.lstrip("0") and hn != "99999":
        p.situs_house_number = hn.lstrip("0")
        sfx = (a.get("NumberSuffix") or "").strip()
        p.situs = f"{p.situs_house_number}{(' ' + sfx) if sfx else ''} {street}".strip()
    else:
        p.situs = street or None
        p.situs_note = ("no house number (the county uses 99999 as a placeholder)" if hn == "99999"
                        else "no house number on the record")
    p.acreage = _num(a.get("Acreage"))
    p.land_class = (a.get("Class") or "").strip() or None
    p.improved = (a.get("Improved") or "").strip() or None
    p.tax_value = _num(a.get("TaxValue")) if _num(a.get("TaxValue")) is not None else _num(a.get("TotalMarketValue"))
    p.land_value = _num(a.get("LandValue"))
    p.building_value = _num(a.get("BuildingValue"))
    p.deed_book = _strip0(a.get("DeedBook")) or None
    p.deed_page = _strip0(a.get("DeedPage")) or None
    if p.deed_book == "0":
        p.deed_book = None
    if p.deed_page == "0":
        p.deed_page = None
    p.deed_date = ymd(a.get("DeedDate"))
    p.deed_instrument = (a.get("Instrument") or "").strip() or None
    pb, pp = _strip0(a.get("PlatBook")), _strip0(a.get("PlatPage"))
    p.plat_book = pb if pb not in ("", "0") else None
    p.plat_page = pp if pp not in ("", "0") else None
    sub = [(a.get(k) or "").strip() for k in ("SubName", "SubBlock", "SubLot", "SubSect")]
    if any(sub):
        p.subdivision = "; ".join(f"{lbl} {v}" for lbl, v in zip(("subdivision", "block", "lot", "section"), sub) if v)
    p.township = (a.get("Township") or "").strip() or None
    p.layer_updated = ymd(a.get("UpdateDate"))
    p.record_card_url = (a.get("propcard") or "").strip() or None
    for k in fields:
        if _LEGAL_FIELD.search(k or ""):
            p.legal_field = k
            v = (a.get(k) or "")
            p.legal_description = str(v).strip() or None
            break
    p.extra = {"AccountNumber": a.get("AccountNumber"), "TotalMarketValue": a.get("TotalMarketValue"),
               "Stamps": a.get("Stamps"), "SalePrice": a.get("SalePrice"), "Exempt": a.get("Exempt"),
               "NeighborhoodCode": a.get("NeighborhoodCode")}
    return p


def _soup(html: str) -> BeautifulSoup:
    s = BeautifulSoup(html or "", "lxml")
    for x in s(["script", "style", "noscript"]):
        x.decompose()
    return s


def _lines(s: BeautifulSoup) -> list[str]:
    return [ln.strip() for ln in s.get_text("\n", strip=True).split("\n") if ln.strip()]


def _after(lines: list[str], label: str) -> Optional[str]:
    for i, ln in enumerate(lines):
        if ln == label and i + 1 < len(lines):
            return lines[i + 1]
    return None


def bill_years(bill: str) -> tuple[Optional[int], Optional[int], bool]:
    m = _BILL.match(bill or "")
    if not m:
        return None, None, False
    ty, ly = int(m.group(2)), int(m.group(3))
    return ty, ly, (ty == ly and m.group(4) == "0000")


def parse_tax_parcel(html: str) -> tuple[Optional[str], list[TaxBill]]:
    """(parcel status Active/Inactive, the bills on the Billing History list)."""
    s = _soup(html)
    lines = _lines(s)
    status = None
    for i, ln in enumerate(lines):
        if ln == "Parcel Details" and i + 1 < len(lines) and lines[i + 1] in ("Active", "Inactive"):
            status = lines[i + 1]
            break
    bills: list[TaxBill] = []
    seen: set[str] = set()
    for card in s.select("div.history-card"):
        a = card.find("a", href=re.compile(r"^/Bill/Details/"))
        if a is None:
            continue
        bno = a.get_text(strip=True)
        if bno in seen:
            continue
        seen.add(bno)
        vals: dict[str, str] = {}
        for small in card.find_all("small"):
            lab = small.get_text(strip=True)
            nxt = small.find_next_sibling()
            if nxt is not None:
                vals[lab] = nxt.get_text(" ", strip=True)
        ty, ly, reg = bill_years(bno)
        amt_text = vals.get("Amount Due")
        bills.append(TaxBill(bill=bno, tax_year=ty, levy_year=ly, regular=reg, owner=vals.get("Owner"),
                             value=money(vals.get("Value")), amount_due=money(amt_text),
                             amount_due_text=amt_text, description=vals.get("Description")))
    return status, bills


_TX_HEAD = ["Type", "Date", "Receipt #", "Tax", "Late Fee", "Interest", "Cost/Fee", "Total"]


def parse_tax_bill(html: str) -> dict:
    s = _soup(html)
    lines = _lines(s)
    out: dict = {"amount_due_text": _after(lines, "Amount due:"), "owner": _after(lines, "Owner Name(s):"),
                 "levy_year": _after(lines, "Levy Year"), "status": _after(lines, "Status"),
                 "location": _after(lines, "Physical Location"), "transactions": [], "status_text": None}
    if "Paid!" in lines:
        out["status_text"] = "Paid!"
    if out["amount_due_text"] and money(out["amount_due_text"]) is None:
        out["status_text"] = out["amount_due_text"]
    for tb in s.find_all("table"):
        head = [th.get_text(" ", strip=True) for th in tb.find_all("th")]
        if head[:8] != _TX_HEAD:
            continue
        for tr in tb.find_all("tr"):
            c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(c) < 8 or not c[0]:
                continue
            out["transactions"].append(TaxTransaction(type=c[0], date=c[1], receipt=c[2], tax=money(c[3]),
                                                      late_fee=money(c[4]), interest=money(c[5]),
                                                      cost=money(c[6]), total=money(c[7])))
        break
    return out


# ---------------------------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------------------------

class BuncombeAdapter(CottV4Register, CountyAdapter):
    state = "NC"
    county = "Buncombe"
    rod_base = ROD
    src_rod = SRC_ROD
    deaths_index = True

    # -- parcel ------------------------------------------------------------------------------
    def _gis(self, where: str, label: str, slug: str) -> tuple[list[dict], list[str], object]:
        params = {"where": where, "outFields": "*", "returnGeometry": "false", "f": "json"}
        person = GIS_LAYER + "/query?" + urlencode({**params, "f": "html"})
        ex = self.new_exhibit(label, SRC_GIS, person, shot_kind="gis_json",
                              note="Opens the county's ArcGIS query page; press Query (GET) to run it.")
        last_err = None
        # the layer intermittently answers HTTP 200 with an error-500 body (HANDOFF item 80): a
        # server hiccup, not a wall. Retried with a growing pause, then reported as a failure.
        for wait in GIS_RETRY_WAITS:
            if wait:
                self.f._sleep(wait)
            resp = self.f.get(GIS_LAYER + "/query", params=params, tag="gis")
            try:
                feats, fields = parse_gis(resp.json())
                self.keep(ex, resp, slug, "json")
                return feats, fields, ex
            except ValueError as exc:
                last_err = exc
        self.keep(ex, resp, slug, "json")
        raise RuntimeError(f"the county parcel layer answered with an error {len(GIS_RETRY_WAITS)} times "
                           f"({last_err}); run the intake again later")

    def parcel(self, pin: str) -> Parcel:
        feats, fields, ex = self._gis(f"pinnum='{pin}'", f"County parcel record for PIN {pin}", "county_parcel_layer")
        if not feats:
            return Parcel(pin=pin, exhibit=ex.key, found=False, field_names=fields)
        p = parcel_from_attrs(pin, feats[0], fields)
        p.exhibit = ex.key
        if len(feats) > 1:
            p.extra["features_returned"] = len(feats)
        return p

    def parcels_at_mailing_number(self, parcel: Parcel) -> tuple[list[OtherParcel], str]:
        hn, st = parcel.mailing_house_number, parcel.mailing_street
        if not hn or not st:
            return [], "The mailing address has no house number on a road (or is a post office box); not checked."
        if parcel.situs_house_number == hn and (parcel.situs_street or "").upper() == st:
            return [], "The mailing address is the parcel's own situs."
        if (parcel.situs_street or "").upper() != st:
            return [], (f"The mailing address is on a different road ({st}) from the parcel's situs "
                        f"({parcel.situs_street or 'none'}); not checked.")
        pad = hn.zfill(5)
        where = f"HouseNumber IN ('{hn}','{pad}') AND streetname = '{st.replace(chr(39), chr(39) * 2)}'"
        feats, _, ex = self._gis(where, f"County parcel record(s) carrying house number {hn} on {st} "
                                        f"(the mailing address's number)", f"mailing_number_{hn}")
        out = []
        for a in feats:
            q = parcel_from_attrs(str(a.get("pinnum") or ""), a, [])
            deed = (f"book {q.deed_book} page {q.deed_page}, {q.deed_date}" if q.deed_book else None)
            out.append(OtherParcel(pin=q.pin, situs=q.situs or "", owner=q.owner, improved=q.improved, deed=deed))
        note = (f"Searched the county layer for house number {hn} on {st} (Exhibit {ex.key}): "
                f"{len(feats)} parcel(s) returned.")
        return out, note

    # -- tax ---------------------------------------------------------------------------------
    def tax(self, parcel: Parcel, today: date) -> TaxStatus:
        ts = TaxStatus(interest_rule=("In North Carolina a levy year's bill is due September 1 and interest "
                                      "begins January 6 of the following year. The current year's bill is "
                                      "listed apart and is not counted as late."))
        url = f"{TAX}/Parcel/Details/{parcel.pin}"
        ex = self.new_exhibit(f"County tax page for PIN {parcel.pin} (all bills)", SRC_TAX, url, shot_kind="tax_html")
        try:
            resp = self.f.get(url, tag="tax_parcel")
        except Walled as w:
            ex.walled, ex.wall_reason = True, w.reason
            ts.walled, ts.wall_reason = True, w.reason
            return ts
        self.keep(ex, resp, "tax_parcel", "html")
        ts.exhibit = ex.key
        ts.parcel_status, bills = parse_tax_parcel(resp.text)
        ts.bills = bills
        regular = [b for b in bills if b.regular and b.levy_year]
        done, pending = split_years([b.levy_year for b in regular], today, self.state)
        ts.completed_years = done
        ts.current_year = pending[0] if pending else None
        want = {y for y in done} | set(pending)
        for b in bills:
            if not (b.regular and b.levy_year in want):
                continue
            burl = f"{TAX}/Bill/Details/{b.bill}"
            bex = self.new_exhibit(f"Bill detail {b.bill}", SRC_TAX, burl, shot_kind="tax_html")
            try:
                br = self.f.get(burl, tag="tax_bill")
            except Walled as w:
                bex.walled, bex.wall_reason = True, w.reason
                continue
            self.keep(bex, br, f"tax_bill_{b.bill}", "html")
            d = parse_tax_bill(br.text)
            b.exhibit, b.detail_read = bex.key, True
            b.transactions = d["transactions"]
            b.status_text = d["status_text"]
            if d["amount_due_text"]:
                b.amount_due_text = d["amount_due_text"]
                b.amount_due = money(d["amount_due_text"])
            if d["owner"]:
                b.owner = d["owner"]
            if d.get("levy_year") and str(d["levy_year"]).isdigit():
                b.levy_year = int(d["levy_year"])
        return ts

    # -- obituaries --------------------------------------------------------------------------
    def obituary(self, people: list[PersonName]) -> dict:
        searches = []
        for p in people[:2]:
            full = " ".join(p.given + [p.last]).title()
            searches += [f'legacy.com obituary search: first name "{p.first.title()}", last name "{p.last.title()}", '
                         f'state North Carolina',
                         f'Asheville Citizen-Times obituaries (citizen-times.com/obituaries): "{full}"',
                         f'Web search: "{full}" obituary Buncombe OR Asheville OR Weaverville']
        return {"run": False,
                "reason": ("Not run by this tool. The free obituary search pages that cover Buncombe County answer "
                           "an automated request with a block: on 2026-10-07 the legacy.com search returned a "
                           "browser challenge page and the Asheville Citizen-Times obituary pages returned HTTP 402. "
                           "Memorial-index sites whose terms bar automated searching were not used. A person runs "
                           "the searches listed."),
                "searches": searches}

    # -- words -------------------------------------------------------------------------------
    def static_records(self) -> list[RecordCheck]:
        return [
            RecordCheck("Probate and estate files (Clerk of Superior Court, Estates)", "walled",
                        "NC eCourts estates search: CAPTCHA in front of the search. Not queried.",
                        "Whether an estate was opened, who qualified, any list of heirs: not known from this sheet."),
            RecordCheck("Court files: special proceedings, civil judgments, tax foreclosure (Clerk of Superior Court)",
                        "walled", "NC eCourts: CAPTCHA in front of the search. Not queried.",
                        "Whether a court action names this parcel or its owner: not known from this sheet."),
            RecordCheck("Deed images (the deeds themselves, including the legal description)", "not opened",
                        "The register shows images through its image viewer; this tool reads the index only.",
                        "The legal description must be read from the deed image (links below)."),
            RecordCheck("Microfilm, old books and maps not online", "not checked",
                        "Not reachable by this tool. Records older than about 70 years need an abstractor; some "
                        "old books and maps are not online.",
                        "Anything recorded only in those books is not covered."),
        ]

    def how_to(self, result) -> list[tuple[str, list[str]]]:
        pin = result.pin
        out = [
            ("County parcel record", [
                f"Open {GIS_LAYER}/query in a browser.",
                f"In Where type pinnum='{pin}', in Out Fields type *, and press Query (GET). Or open the query "
                f"link given for the parcel exhibit.",
                "Read owner, CareOf, Address (mailing), HouseNumber and streetname (situs), DeedBook, DeedPage, "
                "DeedDate, Instrument, Acreage, Class, Improved and TaxValue.",
            ]),
            ("Tax bills", [
                "Open https://tax.buncombenc.gov in a browser and click Accept on the county's user agreement.",
                "In the search menu choose Parcel ID, type the PIN, and press search.",
                f"Open the result (PIN {pin}). The Current Bills and Billing History lists show each year and the "
                "amount due.",
                "Click a bill number to see its transaction lines (billing date, tax, interest, costs, payments).",
            ]),
            ("Register of Deeds: the deed the county cites", [
                "Open the book/page link given in the deed section (the same link the county tax page shows "
                "as 'View Deed'). It opens the register's search as a guest, with no login.",
                "The results list every index entry at that book and page; the one whose date equals the "
                "county's deed date is the deed the county cites.",
                "Click its book/page to open Document Details (grantors, grantees, pages); click the pages link "
                "to view the deed image, which carries the legal description.",
            ]),
            ("Register of Deeds: names and the deaths index", [
                "Open https://registerofdeeds.buncombenc.gov, Indexed Records, Quick Name.",
                "Type the last name (Exactly) and first name (Begins With) shown for each search in the exhibit "
                "list; set Index Type to DEATHS for the death index or leave it on All; enter the filed-from / "
                "thru dates where given; press Search (All Matches).",
                "Bold names in the grid are the names the search matched; for a death entry the decedent is in "
                "the Grantor column and the parents in the Grantee column.",
            ]),
            ("Probate and court files (walled, done by a person)", [
                "Open the NC eCourts portal (portal-nc.tylertech.cloud), Smart Search, and pass its CAPTCHA.",
                "Search Estates in Buncombe County for each decedent name in the death-index table, and civil / "
                "special proceedings for the owner-of-record name.",
            ]),
        ]
        return out

    def sources(self) -> list[tuple[str, str, str]]:
        return [
            (SRC_GIS, GIS_LAYER, "Free public map service, no login."),
            (SRC_TAX, TAX + "/", "Free; a user-agreement pop-up for a person to accept; the page content is served "
                                 "without any login."),
            (SRC_ROD, ROD_NAME, "Free; opens as a guest user; no login. Its pages load Google's invisible reCAPTCHA v3 "
                                 "script; no challenge was presented and none was answered. Document images not "
                                 "opened."),
            ("NC eCourts (estates, special proceedings, civil)", "https://portal-nc.tylertech.cloud/",
             "CAPTCHA in front of the search: walled, not queried."),
        ]

    def not_established(self) -> list[str]:
        return ["The legal description: the free county layer carries no legal-description field, and the deed "
                "image was not opened."]
