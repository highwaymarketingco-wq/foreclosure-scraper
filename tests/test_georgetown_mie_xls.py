"""Georgetown County (SC) CivicEngage — Master-in-Equity monthly .xls rosters.

AUDITED 2026-10-03 (batch 10). Live-confirmed 2 of the "top 4" most-recent
MIE dockets (the ones MAX_MIE_ROSTERS actually parses) are uploaded as .xls,
not PDF: "July 2026" and the doc the page LABELS "September 2026" (internal
filename "September 2027 foreclosure sale.xls" -- a county-side clerical
mismatch, harmless since sale_date comes from the link label, not the
filename). These were previously skipped ENTIRELY by the magic-byte guard
that only accepted "%PDF". Fixed via a new `_REC_LABEL` branch in the shared
`_vendor/xls` reader (Georgetown's export writes every cell as a classic
LABEL record, unlike the SST+LABELSST-based HUD REAC file that reader was
built for) plus a new `parse_mie_xls()` that reads the file's own separate
Plaintiff/Defendant columns -- something the PDF path (`parse_mie`) never
had (it only has a best-effort, un-split party blob).

See tests/test_hud_reac_address.py for the HUD REAC regression check that
the new LABEL-record branch doesn't disturb (that file uses LABELSST, a
different record type, so is structurally unreachable by this change).
"""
from __future__ import annotations

from foreclosure_scraper._vendor.xls import read_first_sheet
from foreclosure_scraper.scrapers.counties_sc.georgetown_civicengage import (
    parse_mie_xls,
)

# Row shape copied verbatim from the live July 2026 roster (see module
# docstring for the byte-level record dump this was reverse-engineered from).
_ROWS = [
    {
        "Case Number": "2025-1105", "Plaintiff": "NewRez, LLC",
        "Defendant": "Deric Hood", "TMS": "41-0182F-101-11-04",
        "Address": "4589 Painted Fern Ct., Unit#11C30 days",
        "Interest Rate": "in Note", "Deficiency": "No",
    },
    {
        "Case Number": "2025-706", "Plaintiff": "Triad Financial Services",
        "Defendant": "Cementhia Davis", "TMS": "03-0416-016-05-00",
        "Address": "375 Hicks Dr., Hway", "Date of Compliance": "30 days",
        "Interest Rate": "in Note", "Deficiency": "No",
        "Included with Sale": "03-0416-016-05-00.001/2023 FLEE MH",
    },
    {
        "Case Number": "2026-295", "Plaintiff": "U. S. Bank Trust Comp.",
        "Defendant": "Brownstone Prop.", "TMS": "05-0003-012-00-00",
        "Address": "1105 Merriman Rd., Gtown", "Date of Compliance": "20 days",
        "Interest Rate": "in Note", "Deficiency": "Yes",
        "Included with Sale": "CANCELLED FOR SEPTEMBER SALE",
    },
]


def test_parse_mie_xls_splits_plaintiff_and_defendant():
    """The real, measured value of this fix: unlike the PDF path's best-
    effort unsplit party blob, the .xls rosters carry these as separate
    cells -- no splitting heuristic needed at all."""
    out = parse_mie_xls(_ROWS, "http://x/doc", label="July 2026")
    r = next(li for li in out if li.parcel_id == "41-0182F-101-11-04")
    assert r.plaintiff == "NewRez, LLC"
    assert r.defendant == "Deric Hood"
    assert r.case_number == "2025-1105"
    assert r.sale_date.year == 2026 and r.sale_date.month == 7


def test_parse_mie_xls_captures_deficiency_and_included_with_sale():
    out = parse_mie_xls(_ROWS, "http://x/doc", label="July 2026")
    r = next(li for li in out if li.parcel_id == "03-0416-016-05-00")
    raw = r.raw["georgetown_civicengage"]
    assert raw["deficiency"] == "No"
    assert raw["included_with_sale"] == "03-0416-016-05-00.001/2023 FLEE MH"
    assert raw["doc"] == "mie_xls"


def test_parse_mie_xls_flags_cancelled_auction_status():
    """A 'CANCELLED...' note in Included with Sale (live-seen on the
    mislabeled Sept-2027-filename doc) must not ship as an active auction."""
    out = parse_mie_xls(_ROWS, "http://x/doc", label="September 2026")
    r = next(li for li in out if li.parcel_id == "05-0003-012-00-00")
    assert r.auction_status == "cancelled"
    other = next(li for li in out if li.parcel_id == "41-0182F-101-11-04")
    assert other.auction_status == "active"


def test_parse_mie_xls_dedupes_by_tms():
    out = parse_mie_xls(_ROWS + [_ROWS[0]], "http://x/doc", label="July 2026")
    assert len(out) == len(_ROWS)


# ---------------------------------------------------------------------------
# Vendored .xls reader: the live file's own LABEL-record (0x0204) encoding,
# built via pypdf-free raw OLE2/BIFF8 bytes (same low-level assembly style as
# this repo's other binary-format tests, e.g. test_dillon_delinquent_tax.py).
# ---------------------------------------------------------------------------

def _ole2_label_xls(cells: list[tuple[int, int, str]]) -> bytes:
    """Build a minimal, genuinely valid OLE2 compound document holding one
    BIFF8 Workbook stream with a single worksheet whose cells are all
    classic LABEL records (r, c, xf, cch, ASCII bytes -- NO grbit flag byte,
    Georgetown's own convention, confirmed live). This is a narrower, from-
    scratch builder (not real Excel output) -- just enough structure for
    `_Ole2`/`_iter_records`/`_first_worksheet_bounds` to find it, mirroring
    how `_vendor/xls/__init__.py`'s own module docstring describes the
    format it reads."""
    import struct as _struct

    def rec(rt: int, payload: bytes) -> bytes:
        return _struct.pack("<HH", rt, len(payload)) + payload

    def label(r: int, c: int, text: str) -> bytes:
        b = text.encode("ascii")
        return rec(0x0204, _struct.pack("<HHHH", r, c, 0, len(b)) + b)

    # Global substream: BOF, BOUNDSHEET (pointing at the worksheet BOF
    # offset -- the reader's own _first_worksheet_bounds only counts BOFs,
    # it never follows the BOUNDSHEET offset, so this can be a placeholder),
    # EOF.
    global_bof = rec(0x0809, b"\x00\x06\x05\x00" + b"\x00" * 12)
    boundsheet = rec(0x0085, _struct.pack("<I", 0) + b"\x00\x06Sheet1")
    global_eof = rec(0x000A, b"")

    ws_bof = rec(0x0809, b"\x00\x06\x10\x00" + b"\x00" * 12)
    ws_cells = b"".join(label(r, c, t) for r, c, t in cells)
    ws_eof = rec(0x000A, b"")

    workbook_stream = global_bof + boundsheet + global_eof + ws_bof + ws_cells + ws_eof

    # Minimal single-sector-FAT OLE2 container with one stream named
    # "Workbook" holding workbook_stream, padded to a sector boundary.
    sec_size = 512
    pad = (-len(workbook_stream)) % sec_size
    data_sectors = workbook_stream + b"\x00" * pad
    n_sectors = len(data_sectors) // sec_size

    # Directory sector: root entry + "Workbook" stream entry (both padded to
    # 128 bytes each, as CFBF requires).
    def dir_entry(name: str, obj_type: int, start_sector: int, size: int, child: int = 0xFFFFFFFF) -> bytes:
        name_utf16 = name.encode("utf-16-le") + b"\x00\x00"
        name_utf16 = name_utf16 + b"\x00" * (64 - len(name_utf16))
        return (name_utf16 + _struct.pack("<H", len(name.encode("utf-16-le")) + 2)
                + bytes([obj_type, 0])  # type, color
                + _struct.pack("<III", 0xFFFFFFFF, 0xFFFFFFFF, child)
                + b"\x00" * 16  # CLSID
                + _struct.pack("<I", 0)  # state bits
                + b"\x00" * 8 + b"\x00" * 8  # create/modify time
                + _struct.pack("<I", start_sector)
                + _struct.pack("<I", size) + b"\x00" * 4)

    root = dir_entry("Root Entry", 5, 0xFFFFFFFE, 0, child=1)
    wb_entry = dir_entry("Workbook", 2, 0, len(workbook_stream))
    dir_sector = root + wb_entry
    dir_sector += b"\x00" * (sec_size - len(dir_sector) % sec_size if len(dir_sector) % sec_size else 0)

    # Sector layout: [0..n_sectors-1] = stream data, [n_sectors] = directory,
    # [n_sectors+1] = FAT.
    dir_sec_idx = n_sectors
    fat_sec_idx = n_sectors + 1

    fat = []
    for i in range(n_sectors - 1):
        fat.append(i + 1)
    fat.append(0xFFFFFFFE)  # end of stream chain
    fat.append(0xFFFFFFFE)  # directory sector (single, end of chain)
    fat.append(0xFFFFFFFD)  # FAT sector itself
    fat_bytes = b"".join(_struct.pack("<I", v) for v in fat)
    fat_bytes += b"\xff" * (sec_size - len(fat_bytes))

    header = (
        bytes.fromhex("d0cf11e0a1b11ae1")
        + b"\x00" * 16  # CLSID
        + _struct.pack("<HH", 0x003E, 0x0003)  # minor, major version
        + _struct.pack("<H", 0xFFFE)  # byte order
        + _struct.pack("<H", 9)  # sector shift (512-byte sectors)
        + _struct.pack("<H", 6)  # mini sector shift
        + b"\x00" * 6  # reserved
        + _struct.pack("<I", 0)  # num directory sectors (0 for major version 3)
        + _struct.pack("<I", 1)  # num FAT sectors
        + _struct.pack("<I", dir_sec_idx)  # dir start sector
        + _struct.pack("<I", 0)  # transaction signature
        # Mini-stream cutoff = 0 so this tiny test stream is read via the
        # REGULAR FAT chain, not the mini-FAT (which this minimal builder
        # doesn't construct at all -- real files always have a mini-FAT,
        # but it's dead weight for a from-scratch test fixture).
        + _struct.pack("<I", 0)
        + _struct.pack("<I", 0xFFFFFFFE)  # mini FAT start
        + _struct.pack("<I", 0)  # num mini FAT sectors
        + _struct.pack("<I", 0xFFFFFFFE)  # DIFAT start (no spill chain)
        + _struct.pack("<I", 0)  # num DIFAT sectors
        + _struct.pack("<I", fat_sec_idx)  # DIFAT[0]: where the FAT sector lives
        + b"\xff" * (109 * 4 - 4)  # DIFAT[1..108]: unused (FREESECT)
    )

    return header + data_sectors + dir_sector + fat_bytes


def test_vendored_xls_reader_decodes_label_records_end_to_end():
    """Builds a REAL OLE2/BIFF8 byte stream (not a mock) and confirms
    read_first_sheet() recovers the header-keyed rows via the new LABEL path."""
    data = _ole2_label_xls([
        (0, 0, "Case Number"), (0, 1, "Plaintiff"), (0, 2, "Defendant"),
        (1, 0, "2025-1105"), (1, 1, "NewRez, LLC"), (1, 2, "Deric Hood"),
    ])
    rows = read_first_sheet(data)
    assert len(rows) == 1
    assert rows[0]["Case Number"] == "2025-1105"
    assert rows[0]["Plaintiff"] == "NewRez, LLC"
    assert rows[0]["Defendant"] == "Deric Hood"
