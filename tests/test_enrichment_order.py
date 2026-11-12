"""Standing guard: data-quality is computed AFTER the valuation, everywhere.

WHY THIS TEST EXISTS
--------------------
`enrichment_data_quality` reads `raw['calc']`. Every ARV caveat it publishes —
`arv_unreliable`, `arv_bid_and_roi_withheld`, `arv_no_independent_check`,
`arv_sanity_flag`, `arv_outlier`, the `data_quality.summary` prose and the CSV's
`data_quality_note` column — is derived from that block. If it runs before the
calc/grade pass, it captions the board off the PREVIOUS run's valuation.

That bug produces no error, no log line and no empty field. It shipped in
src/foreclosure_scraper/main.py (data-quality at line ~1929, valuation ~350
lines below it) and in scripts/patch_listings.py, while
scripts/regenerate_dashboard.py had it right — so a manual regenerate rendered
the correct board and the automated run shipped the wrong one. Measured on the
live board by replaying both orders through the shipping code, the wrong order
emitted arv_unreliable / arv_bid_and_roi_withheld / arv_sanity_flag /
arv_no_independent_check 0 / 0 / 0 / 0 times against 3,049 / 3,049 / 20,443 /
16,310 from the right one: thousands of leads that should carry the loud
warning rendered quiet, and a smaller set carried a false one.

Nothing in the output distinguishes the two orders, so nothing but a test can
hold the line. Hence a SOURCE-ORDER assertion rather than a behavioural one:
the invariant is about where a call sits in a pipeline, and that is a property
of the source, not of any single function's return value.

HOW "AFTER" IS RESOLVED
-----------------------
Not by raw line number. A call inside a helper does not execute where it is
written, it executes where the helper is INVOKED — `scripts/daily_api_refresh.py`
computes the valuation at line 62 inside `_regrade()` and invokes `_regrade()`
at line 271, and `src/foreclosure_scraper/main.py` runs its whole pipeline
inside `run()`, which is invoked once at the bottom of the file.

So each interesting call is resolved to a CALL PATH: the list of (scope, line)
frames from the outermost driver down to the call itself, walking up the
module's local call graph. Two paths are then compared frame by frame, and the
first frame where the lines differ decides the order — exactly how the
interpreter would reach them.

The first version of this file collapsed a path to a single line instead, which
resolved both calls in main.py to line 2815 (`sys.exit(asyncio.run(run()))`)
and asserted `2819 > 2819`. It failed on regenerate_dashboard.py, the file its
own message names as the correct reference. A guard that cries wolf gets
deleted, and deleting it puts the bug straight back, so the resolution has to
be right and not merely strict.

Ambiguity is never resolved in the code's favour: where a helper is invoked
from several sites, data-quality is scored at its EARLIEST possible frame and
the valuation at its LATEST, and a path that cannot be resolved at all fails
loudly rather than passing quietly.

WHAT IT CHECKS
--------------
1. Every module that calls `enrich_data_quality` is discovered automatically
   (no allowlist to forget to update), and in each one the data-quality call
   must come after the last call that writes `raw['calc']`.
2. The discovery itself is sane: main.py and the known publishers must be among
   the modules found, so a deletion is as loud as an inversion.
3. The resolver is tested against a module with a known-inverted order, so a
   future "simplification" that makes it vacuous is caught.
4. `enrichment_data_quality` still actually reads `raw['calc']` — if that ever
   stops being true, this whole test is obsolete and should be deleted rather
   than left passing for the wrong reason.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from foreclosure_scraper.enrichment_data_quality import NO_CAVEATS_SUMMARY

REPO = Path(__file__).resolve().parent.parent
SEARCH_DIRS = (REPO / "src", REPO / "scripts")

DQ_FUNC = "enrich_data_quality"
# Names that (re)write raw['calc']. `grade` is the one that matters — it is
# where valuation.grading.apply_arv_trust_gate runs — but a module that only
# called compute() would still be replacing the block afterwards, so both
# count, as does anything on a valuation module whose name contains either
# word (that is what catches valuation_rentcast.update_grade_with_rentcast,
# the LAST writer of raw['calc'] in main.py).
CALC_WORDS = ("compute", "grade")
VALUATION_ALIAS_HINTS = ("calc", "grad", "valuation", "rentcast")
# Module-local wrappers need no listing here; they are resolved through the
# call graph. This is only about calls made directly on an imported module.

MODULE_SCOPE = "<module>"


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for d in SEARCH_DIRS:
        if d.exists():
            out += [p for p in d.rglob("*.py") if "__pycache__" not in p.parts]
    return sorted(out)


def _called_name(node: ast.Call) -> str:
    """`f(...)` -> 'f'; `mod.f(...)` -> 'f'."""
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _calc_call(node: ast.Call) -> bool:
    """True for a valuation call that (re)writes raw['calc'].

    `compute` and `grade` are ordinary words, so an attribute call only counts
    when the object it hangs off is a valuation module alias — in this repo
    `valuation_calc.compute`, `vgrade.grade`, `valuation_rentcast.
    update_grade_with_rentcast`. A bare call must be one of the exact names,
    which is what a `from ... import compute` would produce.
    """
    fn = node.func
    name = _called_name(node)
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        mod = fn.value.id.lower()
        if not any(k in mod for k in VALUATION_ALIAS_HINTS):
            return False
        return any(w in name.lower() for w in CALC_WORDS)
    if isinstance(fn, ast.Name):
        return name in CALC_WORDS
    return False


class _Scan:
    """Call-graph inventory of one module, enough to order two calls in it."""

    def __init__(self, tree: ast.Module):
        # every def, innermost-first so a nested def wins over its parent
        spans: list[tuple[str, int, int]] = [
            (n.name, n.lineno, n.end_lineno or n.lineno)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self._spans = sorted(spans, key=lambda t: (t[2] - t[1], t[1]))
        self._names = {n for n, _, _ in spans}
        # a name defined more than once cannot be resolved to a single body;
        # recorded so the ordering can widen its site list conservatively
        self._ambiguous = {n for n, _, _ in spans if sum(1 for m, _, _ in spans if m == n) > 1}

        self.dq_calls: list[int] = []
        self.calc_calls: list[int] = []
        # module-local function name -> lines where it is invoked. Bare-name
        # calls only: `asyncio.run(...)` must not register as a call to a
        # module-level `run()`, which is precisely what collapsed main.py's two
        # call paths onto the same line in the first version of this file.
        self.invocations: dict[str, list[int]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if name == DQ_FUNC:
                self.dq_calls.append(node.lineno)
            elif _calc_call(node):
                self.calc_calls.append(node.lineno)
            if isinstance(node.func, ast.Name) and name in self._names:
                self.invocations.setdefault(name, []).append(node.lineno)

    def enclosing(self, lineno: int) -> str:
        """Innermost def containing this line, or MODULE_SCOPE."""
        for name, start, end in self._spans:
            if start <= lineno <= end:
                return name
        return MODULE_SCOPE

    def path(self, lineno: int, *, earliest: bool) -> list[tuple[str, int]]:
        """Frames from the outermost driver down to `lineno`.

        Each frame is (scope, line): the line at which control enters the next
        frame down. Walking stops at a function nobody calls (an entry point)
        or at module scope.

        `earliest` picks which invocation site to use when a helper is called
        from several places: the earliest is the soonest data-quality could
        run, the latest is the last moment the valuation could. Scoring each
        side against the other means an inversion can never hide behind a
        second call site.
        """
        pick = min if earliest else max
        out: list[tuple[str, int]] = [(self.enclosing(lineno), lineno)]
        seen: set[str] = set()
        while True:
            scope = out[0][0]
            if scope == MODULE_SCOPE or scope in seen:
                break
            seen.add(scope)
            all_sites = self.invocations.get(scope, [])
            # a recursive call is not where the function is entered
            sites = [ln for ln in all_sites if self.enclosing(ln) != scope]
            if not sites:
                break  # entry point: nothing in this module calls it
            if scope in self._ambiguous:
                # two defs share this name, so some of these sites may belong to
                # the other one; widen back out and keep the conservative extreme
                sites = list(all_sites)
            site = pick(sites)
            out.insert(0, (self.enclosing(site), site))
        return out


def _scan(path: Path) -> _Scan | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
        return None
    return _Scan(tree)


def _runs_before(a: list[tuple[str, int]], b: list[tuple[str, int]]) -> bool | None:
    """Does call path `a` execute before call path `b`? None = unresolvable."""
    for (scope_a, line_a), (scope_b, line_b) in zip(a, b):
        if scope_a != scope_b:
            return None  # diverged into unrelated scopes
        if line_a != line_b:
            return line_a < line_b
    return None  # identical, or one path is a prefix of the other


def _fmt(p: list[tuple[str, int]]) -> str:
    return " -> ".join(f"{scope}:{line}" for scope, line in p)


def _dq_modules() -> list[tuple[Path, _Scan]]:
    """Every module that CALLS enrich_data_quality (not merely imports it)."""
    out = []
    for p in _iter_py_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        if f"{DQ_FUNC}(" not in text:
            continue
        if p.name == "enrichment_data_quality.py":
            continue  # the definition itself
        sc = _scan(p)
        if sc and sc.dq_calls:
            out.append((p, sc))
    return out


def test_discovery_finds_the_real_pipeline():
    """A rename that empties the search would make every check below vacuous."""
    mods = _dq_modules()
    names = {p.relative_to(REPO).as_posix() for p, _ in mods}
    assert "src/foreclosure_scraper/main.py" in names, (
        "the main pipeline no longer appears to call enrich_data_quality — "
        f"found only: {sorted(names)}"
    )
    # every known publisher, so a deletion is as loud as an inversion
    for expected in (
        "scripts/regenerate_dashboard.py",
        "scripts/patch_listings.py",
        "scripts/patch_run_scrapers.py",
        "scripts/merge_today_sources.py",
        "scripts/daily_api_refresh.py",
        "scripts/ingest_fresh_court_leads.py",
    ):
        assert expected in names, f"{expected} stopped calling {DQ_FUNC}()"


@pytest.mark.parametrize(
    "rel",
    [p.relative_to(REPO).as_posix() for p, _ in _dq_modules()],
)
def test_data_quality_runs_after_the_valuation(rel: str):
    """The invariant, per publishing pipeline."""
    path = REPO / rel
    sc = _scan(path)
    assert sc is not None and sc.dq_calls

    if not sc.calc_calls:
        pytest.skip(f"{rel} never recomputes the valuation")

    # data-quality at its earliest, the valuation at its latest
    dq_paths = [sc.path(ln, earliest=True) for ln in sc.dq_calls]
    calc_paths = [sc.path(ln, earliest=False) for ln in sc.calc_calls]

    for dq in dq_paths:
        for calc in calc_paths:
            before = _runs_before(dq, calc)
            assert before is not None, (
                f"{rel}: cannot resolve whether {DQ_FUNC}() [{_fmt(dq)}] runs "
                f"before or after the valuation [{_fmt(calc)}] — they do not "
                "share a call path. This guard is only meaningful when it can "
                "order the two; make the pipeline's order explicit rather than "
                "loosening the check."
            )
            assert before is False, (
                f"{rel}: {DQ_FUNC}() runs at {_fmt(dq)}, BEFORE the valuation "
                f"at {_fmt(calc)}.\n"
                "Every ARV caveat it writes (arv_unreliable, "
                "arv_bid_and_roi_withheld, arv_no_independent_check, "
                "arv_sanity_flag, arv_outlier and the data_quality.summary / "
                "data_quality_note prose) is read out of raw['calc']. From "
                "there it describes the PREVIOUS run's valuation, which "
                "publishes a clean bill of health over a number that has since "
                "been flagged. Move the call after the last calc/grade pass. "
                "scripts/regenerate_dashboard.py is the reference order."
            )


# --------------------------------------------------------------------------
# The resolver itself. Without these, a future simplification that makes
# _runs_before() always return False would leave every check above green.
# --------------------------------------------------------------------------

_INVERTED = '''
import valuation_calc as vcalc
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality

def _regrade(rows):
    for li in rows:
        vcalc.compute(li)

def main():
    rows = load()
    enrich_data_quality(rows)
    _regrade(rows)

main()
'''

_CORRECT = '''
import valuation_calc as vcalc
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality

def _regrade(rows):
    for li in rows:
        vcalc.compute(li)

def main():
    rows = load()
    _regrade(rows)
    enrich_data_quality(rows)

main()
'''


def _order_of(src: str) -> bool | None:
    sc = _Scan(ast.parse(textwrap.dedent(src)))
    assert sc.dq_calls and sc.calc_calls, "fixture did not register its calls"
    return _runs_before(
        sc.path(sc.dq_calls[0], earliest=True),
        sc.path(sc.calc_calls[0], earliest=False),
    )


def test_resolver_catches_an_inversion_hidden_in_a_helper():
    """The valuation is written at line 7 and the data-quality call at line 12,
    but the valuation EXECUTES at line 13. A line-number comparison calls this
    file correct; the resolver must not."""
    assert _order_of(_INVERTED) is True  # dq runs first — inverted


def test_resolver_accepts_the_correct_order():
    assert _order_of(_CORRECT) is False


def test_resolver_is_not_confused_by_a_stdlib_call_of_the_same_name():
    """`asyncio.run(run())` must not read as a call to the local `run()` from
    inside `run()` itself. It did, and it collapsed both call paths in main.py
    onto that one line, which is how the first version of this guard came to
    assert `2819 > 2819` and fail on every pipeline including the correct one."""
    src = '''
    import asyncio
    import valuation_calc as vcalc
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality

    async def run():
        rows = load()
        vcalc.compute(rows)
        enrich_data_quality(rows)

    asyncio.run(run())
    '''
    sc = _Scan(ast.parse(textwrap.dedent(src)))
    dq = sc.path(sc.dq_calls[0], earliest=True)
    calc = sc.path(sc.calc_calls[0], earliest=False)
    assert [s for s, _ in dq] == ["<module>", "run"], _fmt(dq)
    assert dq[-1][1] != calc[-1][1], f"{_fmt(dq)} vs {_fmt(calc)}"
    assert _runs_before(dq, calc) is False


def test_resolver_scores_the_valuations_last_call_site():
    """A helper invoked twice must be scored at its LAST site, or a
    data-quality call wedged between the two would read as correct."""
    src = '''
    import valuation_calc as vcalc
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality

    def _regrade(rows):
        vcalc.compute(rows)

    def main():
        _regrade(all_rows)
        enrich_data_quality(all_rows)
        _regrade(touched_rows)

    main()
    '''
    sc = _Scan(ast.parse(textwrap.dedent(src)))
    assert _runs_before(
        sc.path(sc.dq_calls[0], earliest=True),
        sc.path(sc.calc_calls[0], earliest=False),
    ) is True  # inverted: a re-grade lands after the caption


def test_resolver_sees_the_rentcast_regrade():
    """valuation_rentcast.update_grade_with_rentcast is the LAST writer of
    raw['calc'] in main.py and matches neither 'compute' nor 'grade' exactly."""
    src = '''
    import valuation_rentcast
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality

    def main():
        enrich_data_quality(rows)
        valuation_rentcast.update_grade_with_rentcast(rows)

    main()
    '''
    sc = _Scan(ast.parse(textwrap.dedent(src)))
    assert sc.calc_calls, "the rentcast re-grade was not recognised as a calc write"


def test_data_quality_still_reads_raw_calc():
    """If this stops being true the ordering no longer matters and this whole
    file should be deleted rather than left passing for the wrong reason."""
    src = (REPO / "src" / "foreclosure_scraper" / "enrichment_data_quality.py").read_text()
    assert 'raw.get("calc")' in src
    assert "gate_calc_dict" in src


def test_missing_calc_is_not_reported_as_ok():
    """The `if calc else "ok"` short-circuit: a lead with no valuation block
    used to fall through every ARV branch and be summarised as healthy."""
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
    from foreclosure_scraper.models import Listing, PropertyKind

    li = Listing(
        source="test", source_url="https://example.test/1",
        street_address="1 Test St", city="Asheville", state="NC",
        county="Buncombe", living_sqft=1200,
        property_kind=PropertyKind.SINGLE_FAMILY, raw={},
    )
    enrich_data_quality([li])
    dq = li.raw["data_quality"]
    assert "arv_not_computed" in dq["flags"]
    assert NO_CAVEATS_SUMMARY not in dq["summary"]
    assert "NOT VALUED" in dq["summary"]


def test_a_computed_calc_does_not_get_the_not_computed_flag():
    """The normal case must stay silent — this guard adds no wallpaper."""
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
    from foreclosure_scraper.models import Listing, PropertyKind

    li = Listing(
        source="test", source_url="https://example.test/2",
        street_address="2 Test St", city="Asheville", state="NC",
        county="Buncombe", living_sqft=1200,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"calc": {"arv_expected": 250000.0, "arv_confidence": "HIGH"}},
    )
    enrich_data_quality([li])
    dq = li.raw["data_quality"]
    assert "arv_not_computed" not in dq["flags"]
    assert dq["summary"] == NO_CAVEATS_SUMMARY


def test_stale_calc_would_be_captioned__the_defect_in_miniature():
    """The behaviour the ordering protects, stated without any pipeline.

    Same listing, two orders. Order A captions a valuation that is about to be
    replaced; order B captions the one that ships. Only B names the flag.
    """
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
    from foreclosure_scraper.models import Listing, PropertyKind

    def _lead() -> Listing:
        return Listing(
            source="test", source_url="https://example.test/3",
            street_address="3 Test St", city="Spartanburg", state="SC",
            county="Spartanburg", living_sqft=1000,
            property_kind=PropertyKind.SINGLE_FAMILY,
            # what the PREVIOUS run left behind: a clean, unflagged valuation
            raw={"calc": {"arv_expected": 780300.0, "arv_confidence": "MEDIUM"}},
        )

    # this run's valuation: same lead, now contradicted
    fresh = {"arv_expected": 121100.0, "arv_confidence": "MEDIUM",
             "arv_flags": ["comp_kind_mismatch"], "max_bid_70": 84770.0,
             "roi_pct": 120.0, "deal_status": "GREAT"}

    stale_first = _lead()
    enrich_data_quality([stale_first])            # A: data-quality, then...
    published_a = dict(stale_first.raw["data_quality"])
    stale_first.raw["calc"] = dict(fresh)         # ...the valuation lands

    calc_first = _lead()
    calc_first.raw["calc"] = dict(fresh)          # B: valuation, then...
    enrich_data_quality([calc_first])             # ...data-quality
    published_b = calc_first.raw["data_quality"]

    assert "arv_unreliable" not in published_a["flags"]
    assert published_a["summary"] == NO_CAVEATS_SUMMARY

    assert "arv_unreliable" in published_b["flags"]
    assert "arv_bid_and_roi_withheld" in published_b["flags"]
    # and the gate stripped the money the contradicted ARV cannot support
    assert "max_bid_70" not in calc_first.raw["calc"]
    assert "roi_pct" not in calc_first.raw["calc"]
    assert "deal_status" not in calc_first.raw["calc"]
