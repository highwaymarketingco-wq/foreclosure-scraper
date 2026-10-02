"""Tests for divorce_caption.split_divorce_caption.

Fixtures are real caption strings pulled live off the published board
2026-10-02 via board_stream.iter_board_rows() (read-only), from
raw['divorce']['cases'][]['parties'] -- see that module's docstring for the
full live-verification writeup (9,887/9,923 role-field cross-check agreement
on caption order, zero non-'vs.' separators observed in 14,741 live
captions).
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.divorce_caption import split_divorce_caption


@pytest.mark.parametrize("caption,plaintiff,defendant,additional", [
    # Plain ALL-CAPS, the dominant live shape.
    ("JIMMIE LEE GLENN vs. JAMES L GLENN", "JIMMIE LEE GLENN", "JAMES L GLENN", False),
    ("MICKIE MOORE vs. GEORGE MOORE", "MICKIE MOORE", "GEORGE MOORE", False),
    # "vs" with no trailing period also appears live.
    ("JAMES GLENN JR vs GEORGE MOORE", "JAMES GLENN JR", "GEORGE MOORE", False),
    # Title Case, also real.
    ("Irina Popov vs. Zhenia Popov", "Irina Popov", "Zhenia Popov", False),
    ("Linda Esmeralda Lorenzo Ignacio vs. Jose Alfredo Alvarez Hernandez",
     "Linda Esmeralda Lorenzo Ignacio", "Jose Alfredo Alvarez Hernandez", False),
    # "et al." on the defendant side only.
    ("LUDOVIC FRANCOIS CHOURAKI vs. CARRIE ANN COURTNEY CHOURAKI, et al.",
     "LUDOVIC FRANCOIS CHOURAKI", "CARRIE ANN COURTNEY CHOURAKI", True),
    # "et al." on BOTH sides.
    ("TERESA COLLINS STILWELL, et al. vs. WILLIAM PATRICK STILWELL, et al.",
     "TERESA COLLINS STILWELL", "WILLIAM PATRICK STILWELL", True),
    # a bare "AND" folding a second name onto one side, no further delimiter --
    # kept whole rather than guessed apart.
    ("WALTER L NIX vs. PEARL T AND ROGER NIX", "WALTER L NIX", "PEARL T AND ROGER NIX", True),
    # comma + generational suffix ("Sr") on the defendant must survive --
    # it is not "et al." and must not be stripped.
    ("Sarah Elizabeth Robinson, et al. vs. Charles Christopher Robinson, Sr",
     "Sarah Elizabeth Robinson", "Charles Christopher Robinson, Sr", True),
])
def test_real_live_caption_shapes(caption, plaintiff, defendant, additional):
    out = split_divorce_caption(caption)
    assert out == {
        "plaintiff": plaintiff,
        "defendant": defendant,
        "additional_parties": additional,
    }


def test_bare_v_dot_separator_supported_defensively():
    # Zero live rows use this (SC's CaseDescription always writes "vs."), but
    # enrichment_nc_divorce.py's own text-cut parse window is not guaranteed
    # to match that shape, so a bare "v." is supported as a fallback.
    out = split_divorce_caption("JOHN DOE v. JANE DOE")
    assert out == {"plaintiff": "JOHN DOE", "defendant": "JANE DOE", "additional_parties": False}


def test_unpunctuated_middle_initial_v_is_not_mistaken_for_a_separator():
    # A bare, unpunctuated "V" is how this board's own name convention writes
    # a middle initial (see name_normalize.py) -- it must never be treated as
    # the plaintiff/defendant separator. Only "vs"/"vs." or "v." (WITH the
    # period) count.
    out = split_divorce_caption("MARY V SMITH vs. JOHN DOE")
    assert out == {"plaintiff": "MARY V SMITH", "defendant": "JOHN DOE", "additional_parties": False}


@pytest.mark.parametrize("bad", [None, "", "   ", "SMITH JOHN SOLE FILING NO SEPARATOR"])
def test_no_separator_or_empty_returns_none(bad):
    assert split_divorce_caption(bad) is None


def test_whitespace_and_trailing_comma_are_trimmed():
    out = split_divorce_caption("  JOHN SMITH   vs.   JANE SMITH,  ")
    assert out == {"plaintiff": "JOHN SMITH", "defendant": "JANE SMITH", "additional_parties": False}
