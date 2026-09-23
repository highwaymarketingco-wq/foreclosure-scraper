"""The outer wall-clock cap on enrich_dot_ocr must never be tighter than its own budget.

MEASURED 2026-09-23: main.py called `_await_capped(enrich_dot_ocr(enriched), "dot_ocr")` with
no third argument, so it used `_await_capped`'s own default of 900s. enrich_dot_ocr's own
internal budget (FORECLOSURE_DOT_OCR_BUDGET_S) defaults to 1800s. `asyncio.wait_for` cancelled
the coroutine at 900s every run -- exactly half of the enricher's own deadline -- so it never
reached its own graceful-stop logic or logged a single stat. Every full run had zero visibility
into this enricher (docs/document_image_extraction_audit_2026-09-23.md). This reads main.py's
own source for the fix (the call now derives its cap from FORECLOSURE_DOT_OCR_BUDGET_S plus a
120s grace) rather than importing main.py, since main.py has heavy import-time side effects.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" / "main.py"


def _dot_ocr_call_site() -> str:
    src = MAIN_PY.read_text()
    i = src.index("from .enrichment_dot_ocr import enrich_dot_ocr")
    j = src.index("\n\n", i)
    return src[i:j]


def test_the_outer_cap_is_no_longer_the_bare_900s_default():
    site = _dot_ocr_call_site()
    assert "_await_capped(enrich_dot_ocr(enriched), \"dot_ocr\")" not in site, (
        "regressed to the bare call: the outer cap is back to _await_capped's 900s default, "
        "tighter than enrich_dot_ocr's own 1800s budget"
    )
    assert "default_s=" in site


def test_the_outer_cap_reads_the_same_env_var_as_the_enricher_and_adds_grace():
    site = _dot_ocr_call_site()
    assert "FORECLOSURE_DOT_OCR_BUDGET_S" in site, (
        "the outer cap must track enrich_dot_ocr's own FORECLOSURE_DOT_OCR_BUDGET_S "
        "env var, not a second, independent constant that can drift out of sync with it"
    )
    m = re.search(r'os\.environ\.get\("FORECLOSURE_DOT_OCR_BUDGET_S",\s*"(\d+)"\)\)?\s*\+\s*(\d+)', site)
    assert m, f"could not find the budget + grace expression in:\n{site}"
    inner_default, grace = int(m.group(1)), int(m.group(2))
    assert grace > 0, "no grace period: the outer cap could fire at the same instant as the inner one"
    assert inner_default == 1800, "enrich_dot_ocr's own default changed; keep this test's baseline in sync"


def test_the_computed_outer_cap_is_strictly_above_the_enrichers_own_default_budget():
    # Read enrich_dot_ocr's own default straight from its source (no import: the module has
    # network/browser-automation dependencies at import time that this test does not need).
    dot_ocr_src = (MAIN_PY.parent / "enrichment_dot_ocr.py").read_text()
    m_inner = re.search(r'budget_s\s*=\s*float\(os\.environ\.get\("FORECLOSURE_DOT_OCR_BUDGET_S",\s*"(\d+)"\)\)', dot_ocr_src)
    assert m_inner, "could not find enrich_dot_ocr's own budget_s default"
    inner_default = float(m_inner.group(1))

    site = _dot_ocr_call_site()
    m = re.search(r'"FORECLOSURE_DOT_OCR_BUDGET_S",\s*"(\d+)"\)\)?\s*\+\s*(\d+)', site)
    outer_cap = float(m.group(1)) + float(m.group(2))
    assert outer_cap > inner_default, (
        f"outer cap ({outer_cap}s) must exceed the enricher's own budget ({inner_default}s), "
        "or the enricher is cancelled before it can stop gracefully and log its stats"
    )


def test_ast_confirms_default_s_is_passed_as_a_call_argument():
    # belt and suspenders against a string match on a comment: parse the actual call
    tree = ast.parse(MAIN_PY.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", getattr(n.func, "id", None)) is None]
    found = False
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_await_capped":
            args_src = ast.dump(n)
            if "dot_ocr" in args_src:
                found = True
                kw_names = {kw.arg for kw in n.keywords}
                assert "default_s" in kw_names, "the dot_ocr _await_capped call has no default_s keyword"
    assert found, "could not find the dot_ocr _await_capped call via AST"
