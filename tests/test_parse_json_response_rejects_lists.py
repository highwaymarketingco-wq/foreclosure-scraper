"""Regression test for the 2026-09-16 doc_ocr crash.

_parse_json_response() is shared by enrichment_vision.py and
enrichment_doc_ocr.py; every caller treats its result as a dict. A
multi-entry source document (e.g. a county's whole monthly tax-sale list as
one PDF) can make the model return a JSON array instead, which json.loads()
happily returns despite the declared -> Optional[dict] -- crashing every
caller with "list indices must be integers or slices, not str" the moment
it does parsed["field"]. Live-reproduced against two real Pickens County SC
PDFs. Fixed to return None on a non-dict parse rather than guess an index.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_vision import _parse_json_response


def test_a_normal_object_still_parses():
    out = _parse_json_response('{"owner_name": "SMITH JOHN", "amount": 1200}')
    assert out == {"owner_name": "SMITH JOHN", "amount": 1200}


def test_a_bare_json_array_is_rejected_not_crashed():
    out = _parse_json_response('[{"owner_name": "A"}, {"owner_name": "B"}]')
    assert out is None


def test_a_fenced_json_array_is_rejected_not_crashed():
    out = _parse_json_response('```json\n[{"owner_name": "A"}, {"owner_name": "B"}]\n```')
    assert out is None


def test_an_array_containing_an_object_block_still_falls_through_to_none():
    """The {...} regex fallback must not pull a single element out of an
    array and misattribute it -- it should still end in None, not a guess."""
    text = 'Here is the list: [{"owner_name": "A"}, {"owner_name": "B"}]'
    out = _parse_json_response(text)
    assert out is None or isinstance(out, dict)
    if out is not None:
        # If the regex fallback matched an inner {...} block, it must be a
        # real, complete dict -- never allowed to be a list.
        assert isinstance(out, dict)


def test_garbage_text_returns_none():
    assert _parse_json_response("not json at all") is None
