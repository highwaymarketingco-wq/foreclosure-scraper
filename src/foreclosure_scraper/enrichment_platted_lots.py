"""Legal-description parse for 2+ platted lots, and deeded-vs-assessor acreage
mismatch (Dirty Deeds Tier A #9).

docs/dirty_deeds_synthesis_2026-09-10.md, source #9: "Legal-description parse
for 2+ platted lots under one deed or tax parcel, and deeded vs assessor
acreage mismatch (037, 052) -- Hits roughly 1 in 20 ordinary SFR deals. A lot
bundled with a house adds $3-5k; listed separately it sells for $25-30k. One
parcel was lots 5, 6 and 7: bought $60k, resold $150k. Acreage mismatch is a
buy-side lead signal and a sell-side title-insurance claim ($110,000 recovered
in three weeks on 4 missing acres)."

TWO INDEPENDENT MECHANISMS off text already on the board -- no new scrape:

  1. multi_lot: the legal/tax-record description names 2+ platted lots under
     one deed/parcel ("LOTS 19 & 20", "LOT 22 & P/O LOTS 21 & 23", "LOTS 86
     THRU 96"). A lot bundled into a house sale this way is usually priced as
     part of the house; split off, it is its own $25-30k sale (per the
     synthesis).

  2. acreage_mismatch: a numeric acreage figure appears in the LEGAL text
     ("2.64 ACRES", ".49 AC") that disagrees with this row's own assessor
     acreage (``Listing.acreage``, already GIS/CAMA-backfilled elsewhere) by
     more than 20% and more than 0.1 acre. Recombination/subdivision-survey
     legal text is the dominant real source: the plat states the NEW tract's
     acreage, the assessor field may still carry the PRE-split total (or vice
     versa) until the roll catches up -- exactly the buy-side signal the
     synthesis names.

Reads ``Listing.legal_description`` and ``Listing.description`` (both already
populated by ~25 scrapers -- see the county tax modules under
scrapers/counties_nc, scrapers/counties_sc, scrapers/counties_generic) plus
``Listing.acreage`` (assessor/GIS figure). No network, no new fields upstream.

LIVE-VERIFIED 2026-09-28 against the published board (docs/listings.json.gz,
217,773 rows, via board_stream.iter_board_rows -- read-only, no load_board):

  multi_lot        415 rows (0.19% of the board). Concentrated in SC tax-roll
                   counties whose legal-description format is dense
                   plat-style shorthand: Sumter 130, Spartanburg 34, Lexington
                   33, Bamberg 32, Oconee 27, Florence 27, Laurens 26,
                   Colleton 16, plus Rutherford/Henderson/Guilford NC and a
                   long county tail. Real examples pulled live: parcel
                   7-16-07-335.00 (Spartanburg SC) "LOT 22 & P/O LOTS 21 & 23"
                   -> 3 lots; parcel 2500905001 (Sumter SC) "LOT
                   184,185,210,211" -> 4 lots; parcel 5019-20-90-4161 (Pickens
                   SC) "LOTS 9-12" -> 4 lots (range expanded).

  acreage_mismatch 68 rows after excluding 21 rows that hit a DIFFERENT,
                   pre-existing bug: several Bamberg SC rows carry
                   Listing.acreage at *100x* the legal text's own figure
                   (".36 AC" in the legal text against acreage=36.0 on the
                   same row) -- a decimal-placement bug in whatever populates
                   Bamberg's assessor acreage field upstream of this module,
                   not a real distress signal. Ratio-~100 rows are suppressed
                   here (see _UNIT_BUG_RATIO) rather than counted, and the bug
                   itself is out of scope for this module to fix. Genuine
                   examples: parcel 9587090114 (Henderson NC) "RECOMBINATION
                   SURVEY .49 AC TR2" against assessor acreage 6.57 (13x);
                   parcel 57131 (Cleveland NC) "0.59 ACRES" against 12.0 (20x).
                   Henderson NC's PL-number recombination/subdivision-survey
                   legal text supplies the majority of hits (27 of 68),
                   matching the mechanism description above almost exactly.

KNOWN LIMITATIONS, found live and guarded against rather than pretended away:
  * A bare comma between a lot number and its own acreage ("Lot 7, 1.11
    acres") would misread as two lots without the not-followed-by-ACRES/AC
    guard on every number token (_NUMTOK) -- hit on a real Anderson SC
    Master-in-Equity multi-case docket dump (parcel 1240901017) during
    tuning; fixed, verified clear.
  * Metes-and-bounds dimension strings ("120.85X241.3X74.54X", "50 FT") look
    like a delimited lot list under a naive comma/dash/& split -- hit on
    parcel 2650001037 (Sumter SC, "LOT 10 - 120.85X241.3X74.54X") during
    tuning; fixed via the FT/X-followed-by-digit guards on every number
    token, verified clear.
  * A ``description`` field that echoes a truncated, ellipsis-terminated copy
    of ``legal_description`` (some tax scrapers store both) can hide the
    digits that would otherwise trip the dimension-string guard above. Fixed
    by preferring ``legal_description`` alone whenever it is non-empty and
    falling back to ``description`` only when it is not (most Spartanburg/
    Florence/Sumter rows carry the legal text ONLY in ``description``, so the
    fallback is required, not optional) -- verified this specific collision
    (parcel 2650001037 again) is clear under the fallback ordering.
  * Compound acreage expressions that split the figure across two terms ("1
    &.26 AC", intended total 1.26) are read as the smaller term only. Not
    fixed -- summing arbitrary compound expressions is unbounded parsing
    effort for a handful of rows; documented instead so a future reader does
    not "fix" this into a worse regex.
  * Range parsing ("LOTS 86 THRU 96") is a plain endpoint-count
    (last-first+1); a mixed list ("LOTS 4,5,6,7") counts each named lot.
    Neither one is a legal-description parser, and nothing here should be
    mistaken for one -- it is a distress-signal regex, not a title tool.
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

_WS = r"[ \t]"

#: One lot-number token: 1-4 digits, no run-on into a longer digit group
#: (blocks matching "12" inside "120"), an optional single trailing letter
#: that is itself not followed by a digit (allows "14A" but rejects the "X"
#: in a "50X150" dimension string), and never a number that is actually an
#: acreage or a frontage/dimension figure glued onto the delimiter that
#: follows a lot reference.
_NUMTOK = (
    r"\d{1,4}(?!\d)(?:[A-Z](?!\d))?"
    rf"(?!\.?\d*{_WS}*(?:ACRES?|AC)\b)"
    rf"(?!\.?\d*{_WS}*FT\b)"
    r"(?!\.?\d*X\d)"
)

#: LOT/LOTS followed by a first number, then one or more explicitly delimited
#: further numbers (comma, &, /, AND, THRU, TO, hyphen; each may carry a
#: "P/O"/"PT" partial-lot marker and/or a repeated LOT/LOTS keyword). The
#: delimiter is REQUIRED between every pair -- a bare second number with no
#: delimiter ("LOTS 68 69 & 70") is a documented miss, not a match, because
#: without it there is no way to tell a second lot number from a house number,
#: permit ID, or other digit run sitting right after the legal text.
_LOT_LIST_RE = re.compile(
    rf"\bLOTS?\b{_WS}*(?:NOS?\.?{_WS}*)?"
    rf"(?P<first>{_NUMTOK})"
    rf"(?P<rest>(?:{_WS}*(?:,|&|/|AND|THRU|TO|-){_WS}*"
    rf"(?:P\/?O\.?{_WS}*|PT\.?{_WS}*)?(?:LOTS?{_WS}+)?{_NUMTOK})+)",
    re.I,
)
_NUM_EXTRACT_RE = re.compile(r"\d{1,4}[A-Z]?")
_RANGE_WORD_RE = re.compile(r"\b(?:THRU|TO)\b|-", re.I)

#: A deeded-acreage figure: digits immediately adjacent to ACRE(S)/AC, with no
#: leading integer required ("(?<![\d.])" instead of "\b" so ".49AC" and
#: "LO2.80AC"-style no-space county shorthand still parse -- a plain word
#: boundary cannot see a letter-to-digit transition, which is exactly where
#: this abbreviation glues digits onto "LO" for "lot").
_ACRES_NUM = r"(?:\d{1,4}\.\d{1,3}|\.\d{1,3}|\d{1,4})"
_ACREAGE_RE = re.compile(rf"(?<![\d.])({_ACRES_NUM}){_WS}*(?:ACRES?|AC)(?!\w)", re.I)

#: A row whose assessor acreage is ~100x the legal text's own figure is a
#: decimal-placement bug in the upstream acreage field (confirmed live in
#: Bamberg SC, 2026-09-28 -- see module docstring), not a real mismatch.
_UNIT_BUG_RATIO_LOW, _UNIT_BUG_RATIO_HIGH = 95.0, 105.0
#: Floors below which a "mismatch" is just rounding noise on a tiny parcel.
_MIN_ASSESSOR_ACREAGE = 0.03
_MIN_ABS_DIFF_ACRES = 0.1
_MISMATCH_PCT = 0.20


def parse_multi_lot(legal_description: str | None, description: str | None) -> dict | None:
    """2+ platted lots named in the legal text, or None.

    Prefers ``legal_description`` when present (it is the authoritative
    field); falls back to ``description`` only when there is no
    legal_description at all, which most SC tax-roll scrapers rely on (they
    fold the legal text into ``description`` alongside owner/address). Never
    both at once -- see the module docstring's ellipsis-truncation limitation
    for why concatenating them is unsafe.
    """
    text = legal_description or description or ""
    if not text:
        return None
    m = _LOT_LIST_RE.search(text)
    if not m:
        return None
    whole = m.group(0)
    seen: list[str] = []
    for tok in _NUM_EXTRACT_RE.findall(whole):
        if tok.upper() not in (s.upper() for s in seen):
            seen.append(tok)
    if len(seen) < 2:
        return None
    lot_count = len(seen)
    # "LOTS 86 THRU 96" -> 11 lots, not 2. Only for a plain two-endpoint range
    # joined by a range word/hyphen and both ends pure integers.
    if len(seen) == 2 and _RANGE_WORD_RE.search(m.group("rest")):
        try:
            a, b = int(seen[0]), int(seen[1])
            if 0 < (b - a) < 500:
                lot_count = b - a + 1
        except ValueError:
            pass
    return {"lots": seen, "lot_count": lot_count, "raw_text": whole.strip()}


def parse_acreage_mismatch(legal_description: str | None, assessor_acreage: float | None) -> dict | None:
    """Deeded acreage (from legal_description) vs assessor acreage mismatch, or None."""
    if not legal_description or not assessor_acreage or assessor_acreage <= _MIN_ASSESSOR_ACREAGE:
        return None
    vals = [float(mm.group(1)) for mm in _ACREAGE_RE.finditer(legal_description)]
    if not vals:
        return None
    deeded = max(vals)  # the largest figure in the text is the whole-tract claim
    if deeded <= 0:
        return None
    ratio = assessor_acreage / deeded
    if _UNIT_BUG_RATIO_LOW <= ratio <= _UNIT_BUG_RATIO_HIGH:
        return None  # known upstream decimal-placement bug, not a real mismatch
    pct_diff = abs(deeded - assessor_acreage) / assessor_acreage
    if pct_diff <= _MISMATCH_PCT or abs(deeded - assessor_acreage) <= _MIN_ABS_DIFF_ACRES:
        return None
    return {
        "deeded_acreage": deeded,
        "assessor_acreage": assessor_acreage,
        "pct_diff": round(pct_diff, 3),
    }


def enrich_platted_lots(listings: Iterable[Listing]) -> dict:
    """Stamp raw['platted_lots'] on rows with a multi-lot legal description
    and/or a deeded-vs-assessor acreage mismatch. Additive only -- never
    drops a lead, same contract as every enricher in this module family."""
    stats = {"checked": 0, "multi_lot": 0, "acreage_mismatch": 0, "tagged": 0}
    for li in listings:
        stats["checked"] += 1
        lots = parse_multi_lot(li.legal_description, li.description)
        mismatch = parse_acreage_mismatch(li.legal_description, li.acreage)
        if not lots and not mismatch:
            continue

        tag: dict = {"source": "legal_description_regex"}
        if lots:
            tag.update(multi_lot=True, **lots)
            stats["multi_lot"] += 1
        else:
            tag["multi_lot"] = False
        if mismatch:
            tag.update(acreage_mismatch=True, **mismatch)
            stats["acreage_mismatch"] += 1
        else:
            tag["acreage_mismatch"] = False

        li.raw["platted_lots"] = tag
        stats["tagged"] += 1

    if stats["tagged"]:
        log.info("platted_lots.done", **stats)
    return stats
