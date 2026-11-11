"""Orangeburg County SC Register of Deeds — legacy "SCROD" remote-access platform.

Platform: https://orangeburgscrod.org/ (classic ASP, frameset-based, NOT GovOS
CountyFusion despite sc_countyfusion_rod.py's COUNTIES dict listing Orangeburg
as a countyfusion14.govos.com tenant -- that assumption is wrong. Confirmed live
2026-11-11: countyfusion14.govos.com/countyweb/loginDisplay.action?countyname=
OrangeburgSC returns a 200 with an EMPTY (0-byte) body for Orangeburg (and for
Greenville/Greenwood/Allendale too), identical to the "login_failed, no_token"
symptom Hermes diagnosed -- but Orangeburg's real, working public-facing portal
is this entirely different host/vendor. Greenville separately confirmed (web
search) to run its own viewer.greenvillecounty.org with account registration,
a third platform. Greenwood/Allendale not yet re-sourced.

Login: classic ASP form POST to LoginAction.asp (txtUserName/txtPassword/
cmdSubmit=Login, no CSRF token, no CAPTCHA) -- confirmed live with real
credentials, redirects through to welcome.asp with a Logout link on success.
Credentials: .secrets/orangeburg_scrod/username.txt, password.txt.

Search: GET InstrumentsIndex.asp?Table={Table}&BaseSearch=RecordedDate&
InputBeginDate=MM/DD/YYYY&InputEndDate=MM/DD/YYYY -- no POST, no token,
confirmed live. Two adverse-signal tables with CONFIRMED-LIVE real data
(2026-11-11): FederalLiens (174 rows in a ~2yr window, each with taxpayer
name + full street address + city/state/zip + tax amount + an optional
Discharge Date marking a satisfied lien) and MechLiens (224 rows, doc-type
abbreviations MECH LIEN/MECH REL/MECH AFFID/MECH NTCE). StateLiens returned 0
rows in the same window (checked, not a bug -- just no recent filings).
MainMenu.asp also lists Deeds/Mortgages/Plats/Ordinances/Resolutions/Mental
Health/Official Actions/Proclamations, none of them adverse-document tables.

Two DIFFERENT row shapes confirmed live, parsed separately below:
  - MechLiens-style: two party names "Plaintiff | Defendant" in one cell, a
    short doc-type abbreviation cell (REL/AFFID/NTCE suffixes mark non-liens).
  - FederalLiens-style: ONE taxpayer name + address block + "Tax:$amount" +
    an optional "Discharge Date:" (present only once the lien is satisfied).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://orangeburgscrod.org/"
_SECRETS = Path(__file__).resolve().parents[4] / ".secrets" / "orangeburg_scrod"
_LOOKBACK_DAYS = 730

# MechLiens doc-type suffixes that are NOT a new/active lien.
_MECH_SKIP = ("REL", "AFFID")


async def _login(client: httpx.AsyncClient) -> bool:
    user_path, pass_path = _SECRETS / "username.txt", _SECRETS / "password.txt"
    if not user_path.exists() or not pass_path.exists():
        log.error("orangeburg_scrod.missing_credentials", path=str(_SECRETS))
        return False
    username, password = user_path.read_text().strip(), pass_path.read_text().strip()
    await client.get(_BASE)
    resp = await client.post(f"{_BASE}LoginAction.asp", data={
        "txtUserName": username, "txtPassword": password, "cmdSubmit": "Login",
    })
    ok = "welcome.asp" in str(resp.url).lower() or "Logout1.asp" in resp.text
    if not ok:
        log.warning("orangeburg_scrod.login_failed", url=str(resp.url))
    return ok


async def _search_table(client: httpx.AsyncClient, table: str,
                         from_str: str, to_str: str) -> str:
    resp = await client.get(f"{_BASE}InstrumentsIndex.asp", params={
        "Table": table, "BaseSearch": "RecordedDate",
        "InputBeginDate": from_str, "InputEndDate": to_str,
    })
    return resp.text if resp.status_code == 200 else ""


_INST_RE = re.compile(r"Instrument=(?P<inst>\d+)&FileDate=(?P<filedate>[^']+)")


def _clean(s: str) -> str:
    """BS4 already turns &nbsp; into a real U+00A0 char (not literal text) -- normalize
    that plus any run of whitespace to single spaces."""
    return re.sub(r"[\s\xa0]+", " ", s or "").strip()


def _cell_lines(cell) -> list[str]:
    """A <td>'s text, split on <br> (replaced with real newlines first so BS4's
    get_text() -- which does NOT treat <br> as a separator on its own -- respects
    the row's actual line breaks instead of concatenating everything together).
    Blank lines (whitespace-only text nodes between tags in the source HTML) are
    dropped so the remaining lines can be indexed positionally (name, address,
    city/zip, ...) without the real content's position shifting per row."""
    for br in cell.find_all("br"):
        br.replace_with("\n")
    return [c for c in (_clean(ln) for ln in cell.get_text().split("\n")) if c]


def _parse_mech(cell) -> dict:
    """First line is 'Plaintiff(claimant) | Defendant(property owner)', highlighted
    name is the claimant. No address on this table."""
    lines = _cell_lines(cell)
    name_tag = cell.find("font", color="#800000")
    primary = _clean(name_tag.get_text()) if name_tag else ""
    first_line = lines[0] if lines else ""
    secondary = ""
    if "|" in first_line:
        secondary = _clean(first_line.split("|", 1)[1])
    return {"primary": primary, "secondary": secondary, "address": None,
            "city": None, "zip_code": None, "tax_amount": None, "discharge_date": None}


def _parse_federal(cell) -> dict:
    """Single taxpayer name, then address/city-state-zip/Tax:/Discharge Date lines."""
    lines = _cell_lines(cell)
    name_tag = cell.find("font", color="#800000")
    primary = _clean(name_tag.get_text()) if name_tag else (lines[0] if lines else "")
    address = lines[1] if len(lines) > 1 and lines[1] else None
    city_zip = lines[2] if len(lines) > 2 and lines[2] else None
    zip_m = re.search(r"(\d{5})\s*$", city_zip or "")
    full_text = " ".join(lines)
    tax_m = re.search(r"Tax:\s*([\d,.]+)", full_text)
    disch_m = re.search(r"Discharge Date:\s*([\d/]+)", full_text)
    return {"primary": primary, "secondary": None, "address": address,
            "city": city_zip, "zip_code": zip_m.group(1) if zip_m else None,
            "tax_amount": tax_m.group(1) if tax_m else None,
            "discharge_date": disch_m.group(1) if disch_m else None}


def _parse_rows(html: str, table: str) -> list[dict]:
    from bs4 import BeautifulSoup
    # lxml, not html.parser: stdlib html.parser mishandles a bare (non-self-closed)
    # <br> in deeply nested <font> markup like this site's -- it can synthesize a
    # bogus </br> that silently truncates the rest of a cell's text. Confirmed live
    # 2026-11-11 against a real row (reproduced with a hand-written fixture too).
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for radio in soup.find_all("input", attrs={"name": "detail"}):
        onclick = radio.get("onclick") or radio.get("onClick") or ""
        m = _INST_RE.search(onclick)
        if not m:
            continue
        row = radio.find_parent("tr")
        if row is None:
            continue
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        rec = {
            "instrument": m.group("inst"),
            "filedate": m.group("filedate"),
            "rolecode": _clean(cells[2].get_text()),
            "recorded": _clean(cells[4].get_text()),
            "doctype": _clean(cells[5].get_text()),
        }
        parsed = _parse_federal(cells[3]) if table == "FederalLiens" else _parse_mech(cells[3])
        rec.update(parsed)
        out.append(rec)
    return out


def _dedupe_mech_rows(rows: list[dict]) -> list[dict]:
    """MechLiens indexes each instrument once per party (confirmed live: instrument
    2026000018 appears as two rows, one role-coded 'J' one 'K', same two names just
    swapped which is `primary`) -- keep exactly one row per instrument so
    _to_listing() doesn't emit the same lien twice. Prefers the 'K' (defendant/
    owner-is-primary) row since _to_listing() reads owner_name straight off
    `primary` in that case; falls back to whichever row came first otherwise."""
    by_inst: dict[str, dict] = {}
    for r in rows:
        inst = r["instrument"]
        if inst not in by_inst or r.get("rolecode") == "K":
            by_inst[inst] = r
    return list(by_inst.values())


def _is_active(table: str, rec: dict) -> bool:
    """True = a current, un-released adverse filing worth keeping."""
    if table == "FederalLiens":
        return not rec.get("discharge_date")
    if table == "MechLiens":
        dt = (rec.get("doctype") or "").upper()
        return not any(dt.endswith(sfx) or sfx in dt for sfx in _MECH_SKIP)
    return True


def _to_listing(rec: dict, table: str, slug: str) -> Listing | None:
    """Party-role mapping, confirmed against live sample rows (2026-11-11):
    FederalLiens has ONE name -- the taxpayer/debtor -- which IS the distressed
    party (owner_name/defendant).

    MechLiens indexes EACH instrument once per party, so the SAME instrument
    appears as two separate rows, one with `primary` (the colored name) =
    the plaintiff/claimant and `rolecode` 'J', the other with `primary` =
    the defendant/property-owner and `rolecode` 'K' -- confirmed by checking
    both rows of a real duplicate pair (instrument 2026000018: the 'J' row's
    primary was the claimant, the 'K' row's primary was the owner, in both
    directions). So `rolecode` -- not position -- decides who is who; using
    `primary` as "the claimant" unconditionally (an earlier version of this
    function did) tags the actual property owner as the claimant on exactly
    half of all rows. `_dedupe_mech_rows()` then drops the second, redundant
    row for the same instrument before this function ever sees it."""
    if not _is_active(table, rec):
        return None
    if table == "FederalLiens":
        owner, plaintiff = rec.get("primary"), None
    elif rec.get("rolecode") == "K":
        owner, plaintiff = rec.get("primary"), rec.get("secondary")
    else:
        owner, plaintiff = rec.get("secondary") or rec.get("primary"), rec.get("primary")
    if not owner:
        return None
    desc = f"{table} instrument {rec['instrument']} recorded {rec.get('recorded') or 'unknown date'}: {owner}"
    raw = {
        "rod": {
            "table": table, "instrument": rec["instrument"], "doc_type": rec.get("doctype"),
            "role_code": rec.get("rolecode"), "primary_party": rec.get("primary"),
            "secondary_party": rec.get("secondary"), "recorded": rec.get("recorded"),
            "tax_amount": rec.get("tax_amount"),
        },
        "orangeburg_scrod": True,
    }
    return Listing(
        source=slug,
        source_url=f"{_BASE}InstrumentsIndex.asp?Table={table}&Instrument={rec['instrument']}",
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Orangeburg",
        owner_name=owner,
        defendant=owner,
        plaintiff=plaintiff,
        street_address=rec.get("address"),
        zip_code=rec.get("zip_code"),
        case_number=rec["instrument"],
        description=desc,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


class OrangeburgSCROD(BaseScraper):
    slug = "counties_sc.orangeburg_scrod"
    name = "Orangeburg County SC Register of Deeds (legacy SCROD portal)"
    category = "register_of_deeds"
    expected_min_count = 0
    requires_render = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        to_date = datetime.utcnow()
        from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
        from_str, to_str = from_date.strftime("%m/%d/%Y"), to_date.strftime("%m/%d/%Y")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            if not await _login(client):
                log.error("orangeburg_scrod.login_failed_aborting")
                return []
            for table in ("FederalLiens", "MechLiens"):
                html = await _search_table(client, table, from_str, to_str)
                if not html:
                    log.warning("orangeburg_scrod.empty_response", table=table)
                    continue
                rows = _parse_rows(html, table)
                if table == "MechLiens":
                    rows = _dedupe_mech_rows(rows)
                log.info("orangeburg_scrod.rows_parsed", table=table, count=len(rows))
                for rec in rows:
                    li = _to_listing(rec, table, self.slug)
                    if li:
                        out.append(li)

        log.info("orangeburg_scrod.done", total=len(out))
        return out
