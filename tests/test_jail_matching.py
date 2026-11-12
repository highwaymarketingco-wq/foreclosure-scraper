"""jail_matching: the neutral pure module the pipeline's jail stamp and the jail_booking verifier
share (2026-10-06, HANDOFF 79).

What these pin:
  * the module's API (first_name_variant, spelling_variants, stay_days, long_stay, norm_key) and the
    60-day line;
  * the rules live in ONE place: the verifier and the pipeline module expose the SAME objects, and
    the literal threshold is assigned once in the source tree (the verifier's name for it is an
    alias, which tests/test_verification_jail_recheck_defects.py pins);
  * the dependency points the right way: jail_matching imports only signal_freshness, and the
    enrichment never imports verification/*.
Placeholder names only; no network.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_jail_bookings as jb
from foreclosure_scraper import jail_matching as jm
from foreclosure_scraper.verification.verifiers import jail_booking as v

SRC = Path(jm.__file__).resolve().parent
TODAY = date(2026, 10, 6)


def _imports(path: Path) -> set[str]:
    """Every module a source file imports, as the dotted name relative imports resolve to inside
    the foreclosure_scraper package (the file's own package taken from its path)."""
    pkg = ".".join(path.relative_to(SRC.parent).with_suffix("").parts[:-1])
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg.split(".")
                parts = parts[:len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            out.add(base)
            out |= {f"{base}.{a.name}" for a in node.names}
    return out


# --------------------------------------------------------------------------- #
# the rules                                                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("a,b,d", [
    ("PATRIK", "PATRICK", 1), ("JONATHON", "JONATHAN", 1), ("STEPHANIE", "STEPHANY", 2),
    ("ROB", "ROBERT", 3), ("BETH", "ELIZABETH", None), ("JOHN", "JAKE", None),
    ("AL", "ALAN", None), ("PATRICK", "PATRICK", None), ("", "PATRICK", None),
])
def test_first_name_variant(a, b, d):
    assert jm.first_name_variant(a, b) == d


def test_norm_key_is_letters_only_upper_case():
    assert jm.norm_key("o'Neil-Smith", "mary ann") == ("ONEILSMITH", "MARYANN")
    assert jm.norm_key(None, None) == ("", "")


def test_the_line_is_sixty_days_and_the_stay_ends_at_the_last_sighting():
    assert jm.JAIL_LONG_STAY_DAYS == 60 and jm.POSSIBLE_TRANSFER == "possible_transfer_to_prison"
    assert jm.long_stay({"arrest_date": "2026-08-08"}, TODAY) is None            # 59 days
    assert jm.long_stay({"arrest_date": "2026-08-07"}, TODAY) == 60              # 60 days
    seen = {"arrest_date": "2026-06-01", "last_confirmed_on_roster": "2026-06-20"}
    assert jm.stay_days(seen, TODAY) == 19 and jm.long_stay(seen, TODAY) is None
    assert jm.stay_days({"arrest_date": "2026-06-01"}, TODAY) == 127             # no sighting: today
    assert jm.stay_days({"arrest_date": "2026-10-09"}, TODAY) == 0               # never negative
    assert jm.stay_days({}, TODAY) is None and jm.long_stay({"arrest_date": "junk"}, TODAY) is None


def test_spelling_variants_needs_the_stamps_booking_date_and_is_not_vacuous():
    idx = jb.RosterIndex()
    idx.add({"last": "TESTOWNER", "first": "PATRICK", "dob": "1980-04-12",
             "arrest_date": "2026-09-01T00:00:00.000Z"})
    stamp = {"arrest_date": "2026-09-01", "roster_dob": "1980-04-12"}
    got = jm.spelling_variants(idx, stamp, ("TESTOWNER", "PATRIK"))
    assert [(g["distance"], g["basis"]) for g in got] == [(1, "dob")]
    assert jm.variant_candidate(got[0], ("TESTOWNER", "PATRIK"))["first"] == "PATRIK"
    assert got[0]["record"]["first"] == "PATRICK"                  # the roster's record is not mutated
    assert jm.spelling_variants(idx, {"roster_dob": "1980-04-12"}, ("TESTOWNER", "PATRIK")) == []
    assert jm.spelling_variants(idx, stamp, ("OTHERLAST", "PATRIK")) == []
    assert jm.spelling_variants({}, stamp, ("TESTOWNER", "PATRIK")) == []
    # a plain dict index (an older caller) works as well as a RosterIndex
    plain = {("TESTOWNER", "PATRICK"): {"last": "TESTOWNER", "first": "PATRICK",
                                         "dob": "1980-04-12", "arrest_date": "2026-09-01"}}
    assert len(jm.spelling_variants(plain, stamp, ("TESTOWNER", "PATRIK"))) == 1


# --------------------------------------------------------------------------- #
# one place, and the dependency points the right way                          #
# --------------------------------------------------------------------------- #

def test_the_verifier_and_the_pipeline_use_the_shared_objects():
    assert v.first_name_variant is jm.first_name_variant
    assert v.spelling_variants is jm.spelling_variants
    assert v.stay_days is jm.stay_days
    assert v.JAIL_LONG_STAY_DAYS == jm.JAIL_LONG_STAY_DAYS
    assert jb._norm_key is jm.norm_key
    assert jb.jail_matching is jm


def test_the_threshold_is_assigned_as_a_literal_in_one_file_only():
    literal = re.compile(r"^\s*JAIL_LONG_STAY_DAYS\s*=\s*\d+\s*(#.*)?$", re.M)
    hits = [p.relative_to(SRC.parent).as_posix() for p in SRC.rglob("*.py")
            if literal.search(p.read_text())]
    assert hits == ["foreclosure_scraper/jail_matching.py"]
    # no second copy of the edit-distance or stay arithmetic either
    for name in ("enrichment_jail_bookings.py", "verification/verifiers/jail_booking.py"):
        src = (SRC / name).read_text()
        assert "def first_name_variant" not in src and "def spelling_variants" not in src
        assert "def stay_days" not in src and "def _lev" not in src


def test_jail_matching_imports_only_the_leaf_signal_freshness():
    mine = {m for m in _imports(SRC / "jail_matching.py") if m.startswith("foreclosure_scraper")}
    assert mine <= {"foreclosure_scraper.signal_freshness",
                    "foreclosure_scraper.signal_freshness.to_date"}, mine


def test_the_enrichment_never_imports_the_verification_package():
    mods = _imports(SRC / "enrichment_jail_bookings.py")
    assert not [m for m in mods if "verification" in m], sorted(m for m in mods if "verification" in m)
    assert "foreclosure_scraper.jail_matching" in mods
