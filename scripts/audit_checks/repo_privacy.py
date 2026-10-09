"""Repo privacy invariant (audit 2026-10-09, additions_verify; public-repo rule in the audit BRIEF):
no real person's phone number, e-mail address or 'ESTATE OF <name>' notice text in the tracked code,
tests, fixtures and docs. The published board files carry owners' names and phones by the owner's
decision and are out of scope here (they are data the dashboard serves, not repo text).

  repo-privacy-phones       a NANP phone shape ('(828) 555-0142', '828-555-0142', '828.555.0142')
                            that could be real: area and exchange start 2-9 and neither is 555
  repo-privacy-emails       an e-mail address outside the fake domains (example.com/.org/.net/.gov,
                            *.test, *.invalid, no-reply) and the configuration allow-list
  repo-privacy-estate-names 'ESTATE OF <Name Name>' with a name that carries none of the made-up
                            markers fixtures use (Doe, Roe, Sample, Example, Test...)

Each check fails on any hit and reports COUNTS ONLY (per top-level directory), never the value.
Allowed on purpose (real configuration the code or the owner's manual needs; listed so a new one
is a decision): the owner's own digest sender / recipient addresses in configuration, the land-buyer
directory the buyer matching reads (src/foreclosure_scraper/data/land_buyers.json), and the
government-office contacts in the owner-manual inputs (docs/walls_register.json,
docs/OWNER_MANUAL_LANES.md, docs/county_records/).

No board pass: feed() does nothing; the scan runs once in finish(). CLI:
    uv run python scripts/audit_checks/repo_privacy.py        # counts per check and directory
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

_REPO = Path(__file__).resolve().parents[2]

PHONE = re.compile(r"(?:\((\d{3})\) ?|(?<![\d\w.-])(\d{3})[-.])(\d{3})[-.]\d{4}(?![\d])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ESTATE = re.compile(r"\b[Ee][Ss][Tt][Aa][Tt][Ee] [Oo][Ff],? ([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]*){1,3})")

FAKE_EMAIL = re.compile(r"@(?:[\w.-]+\.)?example\.(?:com|org|net|gov)$|\.test$|\.invalid$|no-?reply|"
                        r"^[a-z]@[a-z]\.com$|@github\.com$|@sentry\.io$|^%s@", re.I)
FAKE_NAME = re.compile(r"\b(?:doe|roe|\w*sample\w*|\w*example\w*|\w*test\w*|fake|placeholder|public|person|decedent|"
                       r"tandry|quimby|imaginary|pretend|fictional|nobody|someone|the|said|a|an|owner|deceased|"
                       r"name|x|y|z|al|llc|inc|corp)\b", re.I)
#: invented names the fixtures use (generic placeholders and made-up ones), whole-name match
PLACEHOLDER_NAMES = frozenset(n.lower() for n in (
    "John Smith", "Jane Smith", "John Q Smith", "John Albert Smith", "Mary Smith", "Mary R Smith",
    "Mary Jones", "William Brown", "Ray Douglas", "Oswin Larkspur Tate", "Rosalind Vale", "Xavia Plum",
    "Otis Bramblewood", "Rosalind M Quillfeather C", "Maris Raleigh", "Maris Pike", "Velma Juno Crisp",
    "Ansel Pike", "Gerald Alvin McCrack-"))

#: configuration values the code needs as real (each one a decision)
ALLOW_EMAILS = frozenset({
    "highwaymarketingco@gmail.com",   # the digest sender (vm_lib.sh GMAIL_SENDER, config.py)
    "greghhigh@gmail.com",            # digest recipient (vm_lib.sh EMAIL_RECIPIENTS, config.py)
    "cashrandolphhigh@gmail.com",     # digest recipient
    "you@gmail.com",                  # a usage placeholder in scripts/foia_vacant_demolition.py
})
ALLOW_PATHS = re.compile(r"^(?:(?:src/foreclosure_scraper/data|docs)/land_buyers\.json|docs/walls_register\.json|"
                         r"docs/OWNER_MANUAL_LANES\.md|docs/county_records/|"
                         # generated pseudonyms (tests/test_verification_probate_heir.py builds them)
                         r"tests/fixtures/verification/probate_heir_cases\.json)")
#: board data and generated outputs (owner decision: the board publishes owners' names and phones)
SKIP_PATHS = re.compile(r"^(?:docs/(?:listings|board|outreach|gap_matrix/|handoff/|data/|parcel_photos/|"
                        r"run_meta|run_health|sold_pool|foreclosure_sold_pool|dashboard_data)|data/)")
TEXT_EXT = re.compile(r"\.(?:py|md|txt|html?|xml|json|csv|js|sh|ya?ml|toml|cfg|ini)$", re.I)
MAX_BYTES = 5_000_000


def tracked_files(repo: Path = _REPO) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.split()
    return [f for f in out if TEXT_EXT.search(f) and not SKIP_PATHS.match(f)]


def scan_text(text: str) -> Counter:
    """{'phones': n, 'emails': n, 'estate_names': n} of real-looking values in one file's text."""
    c: Counter = Counter()
    for m in PHONE.finditer(text):
        area, exch = m.group(1) or m.group(2), m.group(3)
        digits = re.sub(r"\D", "", m.group(0))
        # a real NANP number has area and exchange starting 2-9; 555 is the fictional exchange
        if area[0] in "01" or exch[0] in "01" or "555" in (area, exch) or len(set(digits)) <= 2:
            continue
        c["phones"] += 1
    for m in EMAIL.finditer(text):
        e = m.group(0).lower().lstrip("-._%+")
        if e not in ALLOW_EMAILS and not FAKE_EMAIL.search(e):
            c["emails"] += 1
    for m in ESTATE.finditer(text):
        nm = m.group(1).rstrip("'\".,;:")
        if nm.lower() not in PLACEHOLDER_NAMES and not FAKE_NAME.search(nm):
            c["estate_names"] += 1
    return c


def scan(repo: Path = _REPO, files: Optional[Iterable[str]] = None) -> dict[str, Counter]:
    """{kind: Counter(top-level dir -> hits)} over the tracked files (allow-listed paths skipped)."""
    out: dict[str, Counter] = {"phones": Counter(), "emails": Counter(), "estate_names": Counter()}
    for f in (tracked_files(repo) if files is None else files):
        if ALLOW_PATHS.match(f):
            continue
        p = repo / f
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for kind, n in scan_text(text).items():
            out[kind][f.split("/", 1)[0] if "/" in f else "."] += n
    return out


class _RepoCheck:
    def __init__(self, kind: str, result: dict) -> None:
        self.kind = kind
        self.name = f"repo-privacy-{kind.replace('_', '-')}"
        self._result = result

    def feed(self, row: dict) -> None:
        return None

    def finish(self) -> dict:
        if "c" not in self._result:
            self._result["c"] = scan()
        c = self._result["c"][self.kind]
        n = sum(c.values())
        return {"name": self.name, "checked": len(c), "violations": n, "max_violations": 0, "ok": n == 0,
                "detail": ", ".join(f"{d} {k}" for d, k in c.most_common()) or "none"}


def make_checks() -> list:
    shared: dict = {}
    return [_RepoCheck(k, shared) for k in ("phones", "emails", "estate_names")]


def main() -> int:
    res = scan()
    bad = 0
    for kind, c in res.items():
        n = sum(c.values())
        bad += n
        print(f"{kind:13s} {n:5d}  " + ", ".join(f"{d} {k}" for d, k in c.most_common()))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
