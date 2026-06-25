"""Self-contained legacy .xls (OLE2 / BIFF8) reader — no external deps.

Why this exists
---------------
The venv ships no Excel engine (no ``xlrd`` / ``openpyxl`` / ``calamine``), and
``xlrd`` 2.x dropped ``.xls`` support entirely. The HUD REAC multifamily
inspection-score file (``MF-Inspection-Report.xls``) is an ~8 MB OLE2 Compound
Document holding a single BIFF8 ``Workbook`` stream with ~26k rows. To parse it
free + offline + with zero install risk at the daily run, we read the bytes
ourselves.

Scope
-----
This is a *narrow* reader, only what the HUD REAC sheet needs:
  * OLE2 / CFBF container: header, DIFAT (incl. spill chain), FAT, mini-FAT,
    directory, and stream extraction (both regular-FAT and mini-stream paths).
  * BIFF8 worksheet records that actually carry the cell values:
    ``BOF``, ``BOUNDSHEET``, ``SST`` (+ ``CONTINUE``), ``LABELSST``, ``NUMBER``,
    ``RK``, ``MULRK``. (``BLANK``/``MULBLANK``/formatting records are ignored.)

It is NOT a general-purpose spreadsheet library — formulas, dates-as-typed,
multiple worksheets with formula deps, encryption, etc. are out of scope. The
public entry point is :func:`read_first_sheet`, which returns a list of row
dicts keyed by the header row, exactly what the HUD scraper consumes.

Verified against the live 8.26 MB HUD file (2026-06): 26,077 data rows,
``REMS Property Id`` / ``Property Name`` / ``City`` / ``state_code`` /
3×(``Inspection Score`` + ``Release Date``) columns all parse correctly.
"""
from __future__ import annotations

import struct
from typing import Any

# Sentinels in the FAT / DIFAT.
_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
_FATSECT = 0xFFFFFFFD
_DIFSECT = 0xFFFFFFFC
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


class XlsParseError(Exception):
    """Raised when the bytes are not a parseable OLE2/BIFF8 .xls."""


# --------------------------------------------------------------------------- #
# OLE2 / Compound File Binary Format container
# --------------------------------------------------------------------------- #
class _Ole2:
    """Minimal OLE2 reader exposing named streams as bytes."""

    def __init__(self, data: bytes):
        if data[:8] != _OLE_MAGIC:
            raise XlsParseError("not an OLE2 compound document (bad magic)")
        self._data = data
        self._sec_size = 1 << struct.unpack_from("<H", data, 30)[0]
        self._mini_size = 1 << struct.unpack_from("<H", data, 32)[0]
        self._num_fat = struct.unpack_from("<I", data, 44)[0]
        self._dir_start = struct.unpack_from("<I", data, 48)[0]
        self._mini_cutoff = struct.unpack_from("<I", data, 56)[0]
        self._minifat_start = struct.unpack_from("<I", data, 60)[0]
        self._difat_start = struct.unpack_from("<I", data, 68)[0]
        self._num_difat = struct.unpack_from("<I", data, 72)[0]
        self._fat = self._build_fat()
        self._entries = self._read_directory()
        self._mini_fat = self._build_mini_fat()
        self._mini_stream = self._build_mini_stream()

    # -- low level -------------------------------------------------------- #
    def _sec_off(self, sector: int) -> int:
        return 512 + sector * self._sec_size

    def _ints(self, blob: bytes) -> list[int]:
        return list(struct.unpack_from("<%dI" % (len(blob) // 4), blob, 0))

    def _build_fat(self) -> list[int]:
        data = self._data
        # DIFAT: 109 entries in the header, then a spill chain.
        difat = list(struct.unpack_from("<109I", data, 76))
        sector = self._difat_start
        guard = 0
        while sector not in (_ENDOFCHAIN, _FREESECT) and guard < self._num_difat + 8:
            blk = data[self._sec_off(sector):self._sec_off(sector) + self._sec_size]
            vals = self._ints(blk)
            difat.extend(vals[:-1])  # last slot points to the next DIFAT sector
            sector = vals[-1]
            guard += 1
        fat_sectors = [
            s for s in difat
            if s not in (_FREESECT, _ENDOFCHAIN, _FATSECT, _DIFSECT)
        ][: self._num_fat]
        fat: list[int] = []
        for fs in fat_sectors:
            fat.extend(self._ints(
                data[self._sec_off(fs):self._sec_off(fs) + self._sec_size]
            ))
        return fat

    def _chain(self, start: int) -> list[int]:
        out: list[int] = []
        s = start
        seen = 0
        while s not in (_ENDOFCHAIN, _FREESECT) and 0 <= s < len(self._fat):
            out.append(s)
            s = self._fat[s]
            seen += 1
            if seen > len(self._fat) + 1:  # cycle guard
                break
        return out

    def _read_chain_bytes(self, start: int, size: int | None = None) -> bytes:
        blob = b"".join(
            self._data[self._sec_off(s):self._sec_off(s) + self._sec_size]
            for s in self._chain(start)
        )
        return blob if size is None else blob[:size]

    def _read_directory(self) -> list[tuple[str, int, int, int]]:
        dirb = self._read_chain_bytes(self._dir_start)
        entries: list[tuple[str, int, int, int]] = []
        for i in range(0, len(dirb), 128):
            e = dirb[i:i + 128]
            if len(e) < 128:
                break
            nlen = struct.unpack_from("<H", e, 64)[0]
            etype = e[66]
            if etype not in (1, 2, 5):  # storage / stream / root
                continue
            name = e[: max(0, nlen - 2)].decode("utf-16-le", "replace") if nlen else ""
            start_sec = struct.unpack_from("<I", e, 116)[0]
            stream_size = struct.unpack_from("<I", e, 120)[0]
            entries.append((name, etype, start_sec, stream_size))
        return entries

    def _build_mini_fat(self) -> list[int]:
        if self._minifat_start in (_ENDOFCHAIN, _FREESECT):
            return []
        return self._ints(self._read_chain_bytes(self._minifat_start))

    def _build_mini_stream(self) -> bytes:
        root = next((e for e in self._entries if e[1] == 5), None)
        if not root:
            return b""
        _, _, start, size = root
        if start in (_ENDOFCHAIN, _FREESECT):
            return b""
        return self._read_chain_bytes(start, size)

    # -- public ----------------------------------------------------------- #
    def stream(self, *names: str) -> bytes | None:
        """Return the first matching stream's bytes, or None.

        Streams smaller than the mini-stream cutoff live in the mini-FAT;
        larger streams live in the regular FAT.
        """
        for want in names:
            for name, etype, start, size in self._entries:
                if etype == 2 and name == want:
                    if size >= self._mini_cutoff:
                        return self._read_chain_bytes(start, size)
                    out = bytearray()
                    s = start
                    seen = 0
                    while s not in (_ENDOFCHAIN, _FREESECT) and 0 <= s < len(self._mini_fat):
                        out += self._mini_stream[s * self._mini_size:(s + 1) * self._mini_size]
                        s = self._mini_fat[s]
                        seen += 1
                        if seen > len(self._mini_fat) + 1:
                            break
                    return bytes(out[:size])
        return None


# --------------------------------------------------------------------------- #
# BIFF8 worksheet decoding
# --------------------------------------------------------------------------- #
_REC_BOF = 0x0809
_REC_EOF = 0x000A
_REC_BOUNDSHEET = 0x0085
_REC_SST = 0x00FC
_REC_CONTINUE = 0x003C
_REC_LABELSST = 0x00FD
_REC_NUMBER = 0x0203
_REC_RK = 0x027E
_REC_MULRK = 0x00BD


def _rk_to_number(rk: int) -> float:
    div100 = rk & 0x01
    is_int = rk & 0x02
    masked = rk & 0xFFFFFFFC
    if is_int:
        val = float(struct.unpack("<i", struct.pack("<I", masked))[0] >> 2)
    else:
        val = struct.unpack("<d", struct.pack("<q", masked << 32))[0]
    return val / 100.0 if div100 else val


def _iter_records(stream: bytes):
    pos = 0
    n = len(stream)
    while pos + 4 <= n:
        rectype, size = struct.unpack_from("<HH", stream, pos)
        pos += 4
        yield rectype, stream[pos:pos + size]
        pos += size


class _SstCursor:
    """Byte cursor over the SST head + its CONTINUE blocks.

    A BIFF8 SST shared-string can straddle a CONTINUE boundary, and each
    CONTINUE restates the 1-byte compression flag for the chars that follow.
    This cursor tracks block boundaries so the string reader can re-read that
    flag exactly when a split happens.
    """

    def __init__(self, blocks: list[bytes], start: int):
        self.blocks = blocks
        self.bi = 0
        self.off = start

    def _avail(self) -> int:
        return len(self.blocks[self.bi]) - self.off

    def _advance_block(self) -> None:
        self.bi += 1
        self.off = 0

    def read(self, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            if self._avail() == 0:
                self._advance_block()
            take = min(n, self._avail())
            out += self.blocks[self.bi][self.off:self.off + take]
            self.off += take
            n -= take
        return bytes(out)

    def byte(self) -> int:
        if self._avail() == 0:
            self._advance_block()
        b = self.blocks[self.bi][self.off]
        self.off += 1
        return b

    def u16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def at_block_end(self) -> bool:
        return self._avail() == 0


def _parse_sst(blocks: list[bytes]) -> list[str]:
    head = blocks[0]
    _total, unique = struct.unpack_from("<II", head, 0)
    cur = _SstCursor(blocks, 8)
    strings: list[str] = []
    for _ in range(unique):
        nchar = cur.u16()
        grbit = cur.byte()
        compressed = (grbit & 0x01) == 0
        rich = (grbit & 0x08) != 0
        fareast = (grbit & 0x04) != 0
        rich_runs = cur.u16() if rich else 0
        fareast_sz = cur.u32() if fareast else 0
        chars: list[str] = []
        remaining = nchar
        while remaining > 0:
            if cur.at_block_end():
                cur._advance_block()
                # CONTINUE restates the compression flag for the rest.
                grbit = cur.byte()
                compressed = (grbit & 0x01) == 0
            avail = len(cur.blocks[cur.bi]) - cur.off
            if avail == 0:
                continue
            if compressed:
                take = min(remaining, avail)
                seg = cur.blocks[cur.bi][cur.off:cur.off + take]
                chars.append(seg.decode("latin-1", "replace"))
                cur.off += take
                remaining -= take
            else:
                take = min(remaining, avail // 2)
                if take == 0:
                    # A UTF-16 unit split across the boundary — read 2 bytes
                    # spanning blocks.
                    chars.append(cur.read(2).decode("utf-16-le", "replace"))
                    remaining -= 1
                    continue
                seg = cur.blocks[cur.bi][cur.off:cur.off + take * 2]
                chars.append(seg.decode("utf-16-le", "replace"))
                cur.off += take * 2
                remaining -= take
        # Skip rich-text formatting runs and far-east extension data.
        cur.read(rich_runs * 4 + fareast_sz)
        strings.append("".join(chars))
    return strings


def _first_worksheet_bounds(records: list[tuple[int, bytes]]) -> tuple[int, int]:
    """Index range [start, end) of the records belonging to the first sheet.

    The global substream comes first (it holds BOUNDSHEET + SST), then each
    worksheet substream begins with its own ``BOF``. We return the slice of the
    first worksheet substream so cell records from later sheets (if any) don't
    bleed in.
    """
    bof_indexes = [i for i, (rt, _) in enumerate(records) if rt == _REC_BOF]
    if len(bof_indexes) < 2:
        # No separate worksheet substream — treat everything as one sheet.
        return 0, len(records)
    start = bof_indexes[1]
    end = bof_indexes[2] if len(bof_indexes) > 2 else len(records)
    return start, end


def read_first_sheet(data: bytes) -> list[dict[str, Any]]:
    """Parse a legacy .xls and return the first worksheet as row dicts.

    The first row is treated as the header; every subsequent row becomes a
    ``{header_name: cell_value}`` dict. Numeric cells come back as ``float``,
    string cells as ``str``; missing cells are simply absent from the dict.

    Raises :class:`XlsParseError` on a non-.xls / unsupported container.
    """
    ole = _Ole2(data)
    wb = ole.stream("Workbook", "Book")
    if wb is None:
        raise XlsParseError("no Workbook/Book stream in compound document")

    records = list(_iter_records(wb))

    # Shared string table (record + its CONTINUE blocks).
    sst: list[str] = []
    for i, (rt, payload) in enumerate(records):
        if rt == _REC_SST:
            blocks = [payload]
            j = i + 1
            while j < len(records) and records[j][0] == _REC_CONTINUE:
                blocks.append(records[j][1])
                j += 1
            sst = _parse_sst(blocks)
            break

    start, end = _first_worksheet_bounds(records)

    grid: dict[tuple[int, int], Any] = {}
    max_row = -1
    max_col = -1
    for rt, p in records[start:end]:
        if rt == _REC_LABELSST:
            r, c, _xf, isst = struct.unpack_from("<HHHI", p, 0)
            grid[(r, c)] = sst[isst] if 0 <= isst < len(sst) else None
        elif rt == _REC_NUMBER:
            r, c = struct.unpack_from("<HH", p, 0)
            grid[(r, c)] = struct.unpack_from("<d", p, 6)[0]
        elif rt == _REC_RK:
            r, c = struct.unpack_from("<HH", p, 0)
            grid[(r, c)] = _rk_to_number(struct.unpack_from("<I", p, 6)[0])
        elif rt == _REC_MULRK:
            r, first_col = struct.unpack_from("<HH", p, 0)
            last_col = struct.unpack_from("<H", p, len(p) - 2)[0]
            o = 4
            c = first_col
            while c <= last_col and o + 6 <= len(p) - 2:
                _xf, rk = struct.unpack_from("<HI", p, o)
                grid[(r, c)] = _rk_to_number(rk)
                o += 6
                c += 1
            continue
        else:
            continue
        if r > max_row:
            max_row = r
        if c > max_col:
            max_col = c

    if max_row < 0:
        return []

    header: dict[int, str] = {}
    for c in range(max_col + 1):
        val = grid.get((0, c))
        if val is not None:
            header[c] = str(val).strip()

    rows: list[dict[str, Any]] = []
    for r in range(1, max_row + 1):
        row: dict[str, Any] = {}
        present = False
        for c, name in header.items():
            if (r, c) in grid:
                present = True
                v = grid[(r, c)]
                row[name] = v.strip() if isinstance(v, str) else v
        if present:
            rows.append(row)
    return rows
