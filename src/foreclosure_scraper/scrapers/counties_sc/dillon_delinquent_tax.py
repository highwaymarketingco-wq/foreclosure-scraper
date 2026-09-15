"""Dillon County SC — Delinquent Tax Sale List (custom tagged-binary export).

Dillon was a genuine zero-row county. Its treasurer page has a "Delinquent
Tax Sale List" link buried in body prose (not in any nav menu — found only
by rendering the page with a real browser and reading its text, not just
scanning for <table>/.pdf links) pointing at `PAPER.XLS`.

THAT FILE IS NOT A REAL .XLS. It fails the OLE2/BIFF8 magic-byte check
this codebase's `_vendor.xls` reader (used by horry_flc.py and the HUD REAC
scraper) requires — it's some OTHER proprietary tagged-binary export from
whatever legacy county tax software produced it, merely given an `.xls`
extension. Reverse-engineered live 2026-09-14 against the real file
(273,128 bytes, 987 records, only 2 of ~15,800 field-tokens malformed):

FORMAT
  A flat stream of repeating (length-prefixed ASCII string) + (11-byte
  metadata) pairs. No container, no compression, no OLE2/zip wrapper --
  read the raw bytes directly.

    [1-byte length][ASCII string][11 bytes: 04 00 <u16 len+8, redundant>
        <u16 row_index, 1-based> <u16 col_index, 0-based> 27 00 00]

  The first 16 tokens (row_index effectively 0, before any data starts) are
  the column HEADERS themselves, in col_index order 0..15:
    Item Number, Owner Name, Owner Name 2, District, Map Number,
    Description, Acres, Buildings, Lots, New Owner Name,
    New Owner Name 2, Real / MH (R,M), Notice 01 Number, Comment,
    Notice 02 Number, Total Tax Due

  BLANK CELLS ARE OMITTED ENTIRELY -- no token, no placeholder. This is why
  a positional parser (assume field N is always the Nth token in a record)
  is unsafe: "Owner Name 2", "New Owner Name", "Comment", etc. are exactly
  the fields real rows leave blank, at unpredictable positions. This parser
  decodes row_index/col_index from each token's own metadata instead of
  assuming position, so it's correct regardless of which fields a given row
  omits.

  A tiny number of records (2 of 987 seen live) have one field's metadata
  boundary shift by a few bytes -- believed caused by trailing whitespace in
  that one field's own string content confusing the "is this a valid
  length-prefixed ASCII run" scan. The scan is self-resynchronizing (the
  very next token parses correctly), so the practical effect is at most one
  missing field on one row, never a wrong-row attribution -- verified live:
  row indices still ran cleanly 1..987 with no gaps or duplicates despite
  the 2 malformed tokens.

Map Number is the same dashed-TMS format every other SC county source in
this codebase already uses (e.g. "104-16-12-018").

DATELESS: a delinquent-tax balance is a standing condition, not a scheduled
event -- same reasoning as every other SC delinquent-tax source here. In
main.py's DATELESS_OK_SOURCES.

Free, public, no login. The document itself needs no impersonation (plain
httpx 200s it), unlike the rest of dilloncountysc.org's HTML pages, which
needed get_text(impersonate=True) just to render the link to it.

Slug: counties_sc.dillon_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
import struct
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.dilloncountysc.org/departments/treasurer.php"

_HEADERS = ["Item Number", "Owner Name", "Owner Name 2", "District", "Map Number",
            "Description", "Acres", "Buildings", "Lots", "New Owner Name",
            "New Owner Name 2", "Real / MH (R,M)", "Notice 01 Number", "Comment",
            "Notice 02 Number", "Total Tax Due"]
_MONEY = re.compile(r"[\d,]+\.\d{2}")


def _extract_tokens(data: bytes) -> list[tuple[int, int, str]]:
    """Every (offset, length, text) length-prefixed printable-ASCII run."""
    pos = 0
    tokens: list[tuple[int, int, str]] = []
    n = len(data)
    while pos < n:
        length = data[pos]
        if 0 < length < 200 and pos + 1 + length <= n:
            candidate = data[pos + 1:pos + 1 + length]
            if all(32 <= b < 127 for b in candidate):
                tokens.append((pos, length, candidate.decode("ascii")))
                pos = pos + 1 + length
                continue
        pos += 1
    return tokens


def parse_paper_xls(data: bytes) -> list[dict]:
    """Decode the tagged-binary record stream into {header_name: value} dicts,
    one per row_index, using each token's own metadata (never position)."""
    tokens = _extract_tokens(data)
    if len(tokens) < len(_HEADERS) or [t[2] for t in tokens[:len(_HEADERS)]] != _HEADERS:
        return []  # not the expected layout — refuse to guess

    rows: dict[int, dict[str, str]] = {}
    for i in range(len(_HEADERS), len(tokens)):
        prev_end = tokens[i - 1][0] + 1 + tokens[i - 1][1]
        this_start = tokens[i][0]
        gap = data[prev_end:this_start]
        if len(gap) != 11 or gap[0:2] != b"\x04\x00":
            continue  # malformed boundary (rare) — skip this one field, not the row
        _, _blen, row_idx, col_idx = struct.unpack_from("<HHHH", gap, 0)
        if col_idx >= len(_HEADERS):
            continue
        rows.setdefault(row_idx, {})[_HEADERS[col_idx]] = tokens[i][2]

    return [rows[k] for k in sorted(rows)]


class DillonDelinquentTax(BaseScraper):
    slug = "counties_sc.dillon_delinquent_tax"
    name = "Dillon County SC Delinquent Tax Sale List"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 100
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("dillon_tax.fetch_fail", error=str(exc)[:160])
            return out
        if not html:
            return out

        # The live page's own markup has a stray space before the quote
        # ("href= \"...\"") -- tolerate optional whitespace rather than
        # requiring the well-formed "href=\"" this regex started with.
        m = re.search(r'href=\s*"([^"]*PAPER\.XLS[^"]*)"', html, re.I)
        if not m:
            log.warning("dillon_tax.no_list_link_found")
            return out
        doc_url = m.group(1)
        if not doc_url.startswith("http"):
            doc_url = "https://www.dilloncountysc.org/" + doc_url.lstrip("/")

        try:
            data = await get_bytes(doc_url, timeout=60.0)
        except Exception as exc:
            log.warning("dillon_tax.download_fail", url=doc_url, error=str(exc)[:160])
            return out

        try:
            records = parse_paper_xls(data)
        except Exception as exc:
            log.warning("dillon_tax.parse_fail", error=str(exc)[:160])
            return out
        if not records:
            log.warning("dillon_tax.unexpected_layout", bytes=len(data))
            return out

        now = datetime.utcnow()
        for rec in records:
            parcel = (rec.get("Map Number") or "").strip() or None
            owner = (rec.get("Owner Name") or "").strip()
            owner2 = (rec.get("Owner Name 2") or "").strip()
            full_owner = f"{owner} {owner2}".strip() if owner2 else owner
            if not full_owner:
                continue
            situs = (rec.get("Description") or "").strip() or None
            amt = None
            m2 = _MONEY.search(rec.get("Total Tax Due") or "")
            if m2:
                try:
                    amt = float(m2.group(0).replace(",", ""))
                except ValueError:
                    amt = None

            out.append(Listing(
                source=self.slug,
                source_url=doc_url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Dillon",
                parcel_id=parcel,
                owner_name=full_owner,
                defendant=full_owner,
                street_address=situs,
                case_number=rec.get("Item Number"),
                description=(f"Delinquent tax" + (f" of ${amt:,.2f}" if amt else "")
                             + f" owed by {full_owner}"
                             + (f" (parcel {parcel})" if parcel else "")),
                first_seen=now,
                last_seen=now,
                raw={"dillon_delinquent_tax": {
                    "total_due": amt,
                    "district": rec.get("District"),
                    "real_or_mh": rec.get("Real / MH (R,M)"),
                    "notice_01_number": rec.get("Notice 01 Number"),
                    "notice_02_number": rec.get("Notice 02 Number"),
                }},
            ))

        log.info("dillon_tax.done", parsed=len(records), usable=len(out))
        return out
