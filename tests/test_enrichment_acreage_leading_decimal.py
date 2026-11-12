r"""THE BUG THIS PINS: `_infer_acreage`'s regex silently truncated a leading-dot
acreage figure to its fractional digits, turning 0.36 acres into 36 acres.

Root cause, confirmed live 2026-09-29 against Bamberg County SC's own qPayBill
portal (bambergcountytreasurer.qpaybill.com, parcel 0072-07-02-016., notice
003861253, owner GAMBLE JOSEPH): the detail page's dedicated "Acres:" field is
".00" (the county records no acreage there at all -- see
qpaybill_delinquent_roll._acres(), which correctly maps ".00" to None), so
enrichment.enrich() falls back to parsing acreage out of the legal-description
text via `_ACRES_RE`. That text reads ".36 AC" -- no leading zero, which is
Bamberg's own legal-text convention (also seen live as ".46 AC AD#26-00350",
".5 AC AD#26-00414", ".75 AC SURVIVORSH AD#26-00534", "LOT 5 BLK 3 .11 AC").

The old pattern, r"(\d+(?:\.\d+)?)\s*(?:acre|ac\b)", requires at least one
digit BEFORE the decimal point and has no anchor stopping re.search from
starting its match after the ".". So it skipped the dot entirely and captured
only the digits that followed it, reading them as a whole number:

    ".36 AC"              -> captured "36" -> 36.0   (should be 0.36)
    ".46 AC AD#26-00350"  -> captured "46" -> 46.0   (should be 0.46)
    ".5 AC AD#26-00414"   -> captured "5"  -> 5.0    (should be 0.5)
    ".75 AC SURVIVORSH.." -> captured "75" -> 75.0   (should be 0.75)
    "LOT 5 BLK 3 .11 AC"  -> captured "11" -> 11.0   (should be 0.11)

Note the scale of the error tracks the COUNT OF DIGITS after the dot (2
digits -> ~100x, 1 digit -> ~10x) -- NOT a uniform 100x multiplier, which is
why the ".5 AC" -> 5.0 row is a 10x error, not 100x. A hypothesis of "the
source returns hundredths-of-an-acre" does not explain that row; this
text-parsing bug does.

This module's fix does NOT touch enrichment_platted_lots.py, which already has
its own, unrelated, and still-needed workaround (_UNIT_BUG_RATIO_LOW/HIGH) for
rows that already carry the bad value on the board.
"""
from foreclosure_scraper.enrichment import _ACRES_RE, _infer_acreage
from foreclosure_scraper.models import Listing


def _listing(legal_description: str | None = None, description: str | None = None,
             acreage: float | None = None) -> Listing:
    return Listing(
        source="test",
        source_url="https://example.test",
        legal_description=legal_description,
        description=description,
        acreage=acreage,
    )


def test_bare_leading_dot_acreage_parses_as_a_fraction_not_a_whole_number():
    # Real Bamberg qPayBill legal-description text, verified live 2026-09-29.
    cases = {
        ".36 AC": 0.36,
        ".46 AC AD#26-00350": 0.46,
        ".5 AC AD#26-00414": 0.5,
        ".75 AC SURVIVORSH AD#26-00534": 0.75,
        "LOT 5 BLK 3 .11 AC": 0.11,
    }
    for text, expected in cases.items():
        m = _ACRES_RE.search(text)
        assert m is not None, text
        assert float(m.group(1)) == expected, (text, m.group(1))


def test_infer_acreage_end_to_end_on_real_bamberg_rows():
    for text, expected in {
        ".36 AC": 0.36,
        ".46 AC AD#26-00350": 0.46,
        ".5 AC AD#26-00414": 0.5,
        ".75 AC SURVIVORSH AD#26-00534": 0.75,
        "LOT 5 BLK 3 .11 AC": 0.11,
    }.items():
        li = _listing(legal_description=text, acreage=None)
        result = _infer_acreage(li)
        assert result == expected, (text, result)
        # A normal residential parcel, not the 5-90 "acre" range the bug produced.
        assert result < 5.0


def test_leading_zero_and_whole_number_acreage_still_parse_correctly():
    # Regression guard: formats that were already correct must stay correct.
    assert float(_ACRES_RE.search("0.36 AC").group(1)) == 0.36
    assert float(_ACRES_RE.search("2.64 ACRES").group(1)) == 2.64
    assert float(_ACRES_RE.search("12 acres").group(1)) == 12.0
    assert float(_ACRES_RE.search("0.59 ACRES").group(1)) == 0.59


def test_infer_acreage_falls_back_to_description_when_legal_description_has_no_match():
    li = _listing(legal_description="LOTS 5 & 6", description="TRACT .25 AC")
    assert _infer_acreage(li) == 0.25


def test_infer_acreage_returns_existing_value_when_no_text_match():
    li = _listing(legal_description="LOTS 5 & 6", acreage=3.5)
    assert _infer_acreage(li) == 3.5


def test_infer_acreage_returns_none_when_nothing_to_parse():
    li = _listing(legal_description=None, description=None, acreage=None)
    assert _infer_acreage(li) is None
