"""THE BUG THIS PINS. The vision pass logged `error=str(exc)[:160]`, and several
client libraries raise exceptions whose __str__ is blank. The 2026-09-13 daily run
produced 143 warning lines reading `error=` with nothing after it, against a 76%
miss rate (866 attempts, 259 scored).

An error line that names no error cannot be acted on: the run looks slow rather
than failing, which is why project_vision_pool_repair's "already fixed, do not
re-diagnose" note went unchallenged while errors kept happening at volume.
"""
from foreclosure_scraper.enrichment_vision import _exc_label


class _Bare(Exception):
    pass


def test_a_message_less_exception_still_names_itself():
    assert _exc_label(_Bare(), 160) == "_Bare"
    assert _exc_label(TimeoutError(), 160) == "TimeoutError"


def test_a_message_is_kept_and_prefixed_with_the_type():
    assert _exc_label(ValueError("boom"), 160) == "ValueError: boom"


def test_the_limit_applies_to_the_message_only():
    out = _exc_label(ValueError("x" * 500), 20)
    assert out.startswith("ValueError: ")
    assert len(out) == len("ValueError: ") + 20


def test_whitespace_only_message_is_treated_as_empty():
    assert _exc_label(_Bare("   "), 160) == "_Bare"
