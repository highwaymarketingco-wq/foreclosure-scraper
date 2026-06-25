"""HUD Multifamily Assistance & Section 8 Contracts — owner-contact apartment leads.

This is the FIRST source in the pipeline that emits multifamily apartment
complexes WITH a verified owner phone + email already attached. Crexi
(national.crexi_multifamily) gives MF for-sale listings but no owner contact;
this fills that gap with HUD's own subsidized-housing registry, which publishes
the owner organization name, main phone, and contact email for every
project-based Section 8 / assistance property.

Source (HUD "Multifamily Assistance & Section 8 Contracts Database", refreshed
monthly, free + public, no login):
  https://www.hud.gov/hud-partners/multifamily-assist-section8-database
Two Excel files, joined on ``property_id``:
  * PROPERTY file (~23.6k rows) — address, county, units, owner org + phone +
    email. The owner-contact columns we rely on:
        property_id, property_name_text, address_line1_text, city_name_text,
        state_code, zip_code, county_name_text, property_total_unit_count,
        owner_organization_name, owner_main_phone_number_text,
        owner_contact_email_text
    NOTE: owner_individual_full_name is ~0% populated in practice — we use
    owner_organization_name as the owner_name and never depend on the
    individual-name columns.
  * CONTRACT file (~24.3k rows) — carries the project-based subsidy contract's
    ``tracs_current_expiration_date`` / ``tracs_overall_expiration_date``. A
    contract expiring soon = opt-out / preservation risk = the distress signal
    for this source (owner may convert to market-rate or sell).

Footprint scoping: HUD rows carry an explicit county_name + state, so we gate
on ``config.in_scope`` (the strict 18-county upstate-SC / WNC allow-list) plus
the oceanfront-county set (Charleston / Horry / Beaufort / Georgetown / coastal
NC) — those ride the orchestrator's existing oceanfront re-pass since we always
emit a street address. Live-verified 2026-06-25: 174 in the strict 18-county
footprint, all 174 with a phone, 172/174 with an email, 174/174 with a contract
expiration date; +60 in oceanfront counties.

xlsx parsing: openpyxl is NOT a project dependency, so we read the .xlsx with the
stdlib only — a .xlsx is a zip of XML, and we stream sharedStrings + the single
worksheet with ``xml.etree.ElementTree.iterparse`` (constant memory, no pandas /
openpyxl). Dates come through as Excel 1900-system serials and are converted.

Free, no auth, no Apify, no CAPTCHA/WAF. Plain HTTPS download of two public
government Excel files.
"""
from __future__ import annotations

import datetime
import re
import zipfile
from io import BytesIO
from typing import Iterable
from xml.etree.ElementTree import iterparse

import structlog

from ...base_scraper import BaseScraper
from ...config import COUNTY_BY_KEY, in_scope
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PROPERTY_URL = (
    "https://www.hud.gov/sites/dfiles/Housing/documents/"
    "MF-Properties-with-Assistance-Sec8-Contracts1.xlsx"
)
CONTRACT_URL = (
    "https://www.hud.gov/sites/dfiles/Housing/documents/"
    "MF-Assistance-Sec8-Contracts1.xlsx"
)

# Oceanfront / coastal counties the orchestrator admits via its near-beach
# re-pass (mirrors main.OCEANFRONT_COASTAL_COUNTIES). HUD rows in these counties
# carry a street address, so they enter the pipeline provisionally and the
# post-geocode oceanfront test decides. Kept here (not imported) so the scraper
# never imports the orchestrator module (main.py is off-limits to edit and
# importing it would pull the whole run graph).
_OCEANFRONT_COUNTIES: frozenset[tuple[str, str]] = frozenset({
    ("Currituck", "NC"), ("Dare", "NC"), ("Hyde", "NC"), ("Carteret", "NC"),
    ("Onslow", "NC"), ("Pender", "NC"), ("New Hanover", "NC"), ("Brunswick", "NC"),
    ("Horry", "SC"), ("Georgetown", "SC"), ("Charleston", "SC"),
    ("Beaufort", "SC"), ("Colleton", "SC"),
})

# A contract expiring within this many days is the "opt-out risk" distress
# signal — flagged in raw.section8.expiring_soon. (Everything still emits; this
# just marks the hot ones.)
_EXPIRING_SOON_DAYS = 365

# Excel 1900 date system epoch (Excel's 1900-leap-year bug means day 0 is
# 1899-12-30, so serial N -> epoch + N days lands on the right calendar date).
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"([A-Z]+)")


def _col_to_idx(cell_ref: str) -> int:
    """'AB12' -> 27 (0-based column index)."""
    letters = _COL_RE.match(cell_ref).group(1)  # type: ignore[union-attr]
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """Stream xl/sharedStrings.xml -> ordered list of strings."""
    out: list[str] = []
    if "xl/sharedStrings.xml" not in zf.namelist():
        return out
    with zf.open("xl/sharedStrings.xml") as fh:
        cur: list[str] = []
        in_si = False
        for ev, el in iterparse(fh, events=("start", "end")):
            if el.tag == _NS + "si":
                if ev == "start":
                    cur = []
                    in_si = True
                else:
                    out.append("".join(cur))
                    in_si = False
                    el.clear()
            elif el.tag == _NS + "t" and ev == "end" and in_si:
                cur.append(el.text or "")
    return out


def _first_worksheet(zf: zipfile.ZipFile) -> str:
    sheets = sorted(
        n for n in zf.namelist()
        if n.startswith("xl/worksheets/") and n.endswith(".xml")
    )
    if not sheets:
        raise ValueError("no worksheet found in xlsx")
    return sheets[0]


def _iter_rows(zf: zipfile.ZipFile, sheet: str, shared: list[str]):
    """Yield each row as {col_idx: value_str_or_None}, streaming (low memory)."""
    with zf.open(sheet) as fh:
        row_cells: dict[int, str | None] = {}
        for ev, el in iterparse(fh, events=("start", "end")):
            tag = el.tag
            if tag == _NS + "row" and ev == "end":
                yield row_cells
                row_cells = {}
                el.clear()
            elif tag == _NS + "c" and ev == "end":
                ref = el.get("r")
                if not ref:
                    el.clear()
                    continue
                ctype = el.get("t")
                v_el = el.find(_NS + "v")
                val: str | None = None
                if ctype == "s":  # shared-string index
                    if v_el is not None and v_el.text is not None:
                        try:
                            val = shared[int(v_el.text)]
                        except (ValueError, IndexError):
                            val = None
                elif ctype == "inlineStr":
                    is_el = el.find(_NS + "is")
                    if is_el is not None:
                        val = "".join(t.text or "" for t in is_el.iter(_NS + "t"))
                else:
                    val = v_el.text if v_el is not None else None
                row_cells[_col_to_idx(ref)] = val
                el.clear()


def _parse_xlsx(data: bytes) -> tuple[list[str], "Iterable[dict[int, str | None]]"]:
    """Return (header_names, row_iterator) for the first sheet of an xlsx blob."""
    zf = zipfile.ZipFile(BytesIO(data))
    shared = _read_shared_strings(zf)
    sheet = _first_worksheet(zf)
    rows = _iter_rows(zf, sheet, shared)
    try:
        header_row = next(rows)
    except StopIteration:
        return [], iter(())
    ncols = (max(header_row) + 1) if header_row else 0
    header = [(header_row.get(i) or "").strip() for i in range(ncols)]
    return header, rows


def _clean(v: str | None) -> str | None:
    """HUD pads fixed-width text fields with trailing spaces — collapse + trim."""
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _excel_serial_to_iso(v: str | None) -> str | None:
    """Convert an Excel 1900-system date serial (e.g. '46295') to 'YYYY-MM-DD'.

    Some refreshes may already carry an ISO/US date string instead of a serial;
    pass those through if they don't look like a bare integer."""
    s = _clean(v)
    if not s:
        return None
    if re.fullmatch(r"\d+(\.0+)?", s):
        try:
            serial = int(float(s))
        except ValueError:
            return None
        if serial <= 0 or serial > 80000:  # sanity window (~year 2089)
            return None
        try:
            return (_EXCEL_EPOCH + datetime.timedelta(days=serial)).isoformat()
        except (OverflowError, ValueError):
            return None
    # Already a date-ish string — keep as-is (best effort).
    return s


def _to_int(v: str | None) -> int | None:
    s = _clean(v)
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _idx(header: list[str], name: str) -> int | None:
    try:
        return header.index(name)
    except ValueError:
        return None


def _in_footprint(county: str | None, state: str | None) -> tuple[bool, bool]:
    """(emit, is_oceanfront_county). Strict 18-county allow-list OR an
    oceanfront county (the latter rides the orchestrator's near-beach re-pass)."""
    if not county or not state:
        return False, False
    norm = county.replace(" County", "").strip().title()
    st = state.strip().upper()
    if in_scope(county, st):
        return True, False
    if (norm, st) in _OCEANFRONT_COUNTIES:
        return True, True
    return False, False


async def _load_contract_expirations() -> dict[str, str]:
    """property_id -> earliest contract expiration ISO date.

    Prefer tracs_current_expiration_date, fall back to
    tracs_overall_expiration_date. When a property has multiple contracts we
    keep the SOONEST expiration (the nearest opt-out / preservation event)."""
    out: dict[str, str] = {}
    try:
        data = await get_bytes(CONTRACT_URL, timeout=120.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("hud_section8.contract_fetch_failed", error=str(exc)[:200])
        return out
    header, rows = _parse_xlsx(data)
    i_pid = _idx(header, "property_id")
    i_cur = _idx(header, "tracs_current_expiration_date")
    i_overall = _idx(header, "tracs_overall_expiration_date")
    if i_pid is None or (i_cur is None and i_overall is None):
        log.warning("hud_section8.contract_columns_missing", header=header[:12])
        return out
    for r in rows:
        pid = _clean(r.get(i_pid))
        if not pid:
            continue
        iso = None
        if i_cur is not None:
            iso = _excel_serial_to_iso(r.get(i_cur))
        if not iso and i_overall is not None:
            iso = _excel_serial_to_iso(r.get(i_overall))
        if not iso:
            continue
        prev = out.get(pid)
        if prev is None or iso < prev:
            out[pid] = iso
    log.info("hud_section8.contracts_loaded", pids=len(out))
    return out


class HudSection8Contracts(BaseScraper):
    slug = "national.hud_section8_contracts"
    name = "HUD Multifamily Section-8 Contracts (owner contact)"
    category = "national_multifamily"
    expected_min_count = 100  # live-verified ~174 in-footprint (18-county strict)
    requires_apify = False
    requires_render = False
    # Two large xlsx downloads (~11 MB + ~4.7 MB) + a full stream-parse each.
    timeout_s = 300.0

    async def fetch(self) -> Iterable[Listing]:
        expirations = await _load_contract_expirations()

        try:
            data = await get_bytes(PROPERTY_URL, timeout=180.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("hud_section8.property_fetch_failed", error=str(exc)[:200])
            return []

        header, rows = _parse_xlsx(data)
        cols = {
            name: _idx(header, name)
            for name in (
                "property_id", "property_name_text", "address_line1_text",
                "city_name_text", "state_code", "zip_code", "county_name_text",
                "property_total_unit_count", "owner_organization_name",
                "owner_main_phone_number_text", "owner_contact_email_text",
            )
        }
        required = ("property_id", "state_code", "county_name_text",
                    "owner_organization_name")
        if any(cols[c] is None for c in required):
            log.warning("hud_section8.property_columns_missing",
                        header=header[:14])
            return []

        today = datetime.date.today()
        out: list[Listing] = []
        seen: set[str] = set()
        total = in_foot = with_phone = with_email = with_exp = 0

        for r in rows:
            total += 1
            state = _clean(r.get(cols["state_code"]))
            county = _clean(r.get(cols["county_name_text"]))
            emit, is_oceanfront = _in_footprint(county, state)
            if not emit:
                continue
            in_foot += 1
            # HUD county casing is inconsistent ("HORRY" vs "Horry") and naive
            # title-casing mangles "McDowell" -> "Mcdowell". Resolve to the
            # canonical config spelling for strict-footprint counties (so it
            # matches every other source's county text exactly); fall back to
            # Title Case for oceanfront counties not in the allow-list.
            if county:
                norm = county.replace(" County", "").strip()
                canon = COUNTY_BY_KEY.get(f"{(state or '').upper()}-{norm.lower()}")
                county = canon.name if canon else norm.title()

            pid = _clean(r.get(cols["property_id"]))
            if not pid or pid in seen:
                continue
            seen.add(pid)

            name = _clean(r.get(cols["property_name_text"]))
            street = _clean(r.get(cols["address_line1_text"]))
            city = _clean(r.get(cols["city_name_text"]))
            zip_code = _clean(r.get(cols["zip_code"]))
            if zip_code:
                zip_code = zip_code[:5]
            units = _to_int(r.get(cols["property_total_unit_count"]))
            owner_org = _clean(r.get(cols["owner_organization_name"]))
            phone = _clean(r.get(cols["owner_main_phone_number_text"]))
            email = _clean(r.get(cols["owner_contact_email_text"]))
            if phone:
                with_phone += 1
            if email:
                with_email += 1

            contract_exp = expirations.get(pid)
            expiring_soon = False
            if contract_exp:
                with_exp += 1
                try:
                    exp_date = datetime.date.fromisoformat(contract_exp[:10])
                    days_left = (exp_date - today).days
                    expiring_soon = 0 <= days_left <= _EXPIRING_SOON_DAYS
                except ValueError:
                    pass

            # street_address is required for the row to display + dedupe and for
            # the oceanfront-county provisional admission path. Fall back to the
            # property name when HUD omits the street (rare).
            street_address = street or name
            if not street_address:
                continue

            desc_bits = ["HUD project-based Section 8 / assisted multifamily"]
            if units:
                desc_bits.append(f"{units} units")
            if contract_exp:
                desc_bits.append(f"contract expires {contract_exp}")
                if expiring_soon:
                    desc_bits.append("(opt-out risk — expiring soon)")
            description = " — ".join(desc_bits)

            li = Listing(
                source=self.slug,
                source_url=(
                    "https://www.hud.gov/hud-partners/"
                    "multifamily-assist-section8-database"
                ),
                listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.MULTI_FAMILY,
                street_address=street_address,
                city=city,
                county=county,
                state=(state or "").upper() or None,
                zip_code=zip_code,
                owner_name=owner_org,
                description=description,
                case_number=f"hud-mf-{pid}",
                raw={
                    "hud_property_id": pid,
                    "property_name": name,
                    "units": units,
                    "owner_contact": {
                        "organization": owner_org,
                        "phone": phone,
                        "email": email,
                    },
                    "section8": {
                        "contract_expiration": contract_exp,
                        "expiring_soon": expiring_soon,
                    },
                    "oceanfront_candidate": is_oceanfront,
                },
            )
            out.append(li)

        log.info(
            "hud_section8.done",
            total_props=total, in_footprint=in_foot, emitted=len(out),
            with_phone=with_phone, with_email=with_email, with_exp=with_exp,
        )
        return out
