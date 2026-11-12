"""Tests for enrichment_nc_divorce._parse_divorce_cases's caption split.

This module is gated off by default (FORECLOSURE_NC_DIVORCE=0, AWS-WAF
CAPTCHA-blocked per its own docstring) and has never produced a live board
row, so unlike enrichment_sc_divorce.py's test there is no live sample to
draw fixtures from. These use the exact text shape the module's own
docstring documents (case-number anchor + style text + date, cut from
rendered Odyssey results text) to prove the same divorce_caption.
split_divorce_caption() call that is live-verified for SC also wires
correctly into this parse path.
"""
from __future__ import annotations

from foreclosure_scraper import enrichment_nc_divorce as m


def test_parse_divorce_cases_splits_caption_into_plaintiff_defendant():
    text = "24CVD001234 JIMMIE LEE GLENN vs. JAMES L GLENN 01/15/2024\n"
    cases = m._parse_divorce_cases(text, last="GLENN", first="JIMMIE")
    assert len(cases) == 1
    case = cases[0]
    assert case["parties"] == "JIMMIE LEE GLENN vs. JAMES L GLENN"
    assert case["plaintiff"] == "JIMMIE LEE GLENN"
    assert case["defendant"] == "JAMES L GLENN"
    assert case["additional_parties"] is False


def test_parse_divorce_cases_split_is_none_without_a_separator():
    # A degenerate/truncated render where the style text never carries a
    # recognized separator must not raise or fabricate a split.
    text = "24CVD005678 JIMMIE LEE GLENN SOLE FILING 01/15/2024\n"
    cases = m._parse_divorce_cases(text, last="GLENN", first="JIMMIE")
    assert len(cases) == 1
    assert cases[0]["plaintiff"] is None
    assert cases[0]["defendant"] is None
    assert cases[0]["additional_parties"] is None
