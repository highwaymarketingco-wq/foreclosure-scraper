"""Every source in the code must be findable in the source docs.

The register exists to answer "what do we read, at what URL, and what can we not
do". It drifts silently: a source gets built, the doc does not get the host, and
the gap is invisible until somebody asks.

That happened on 2026-08-12 — eleven register-of-deeds hosts were named in prose
while only two of their domains were actually written down, and
fastpeoplesearch.com was in no doc at all despite costing 10.5 hours of a run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def _register_text() -> str:
    """The register is split across two files; either counts as documented."""
    out = []
    for name in ("SOURCE_REGISTER.md", "net_new_source_register.md"):
        p = DOCS / name
        if p.exists():
            out.append(p.read_text())
    assert out, "no source register found at all"
    return "\n".join(out)


def test_every_registered_scraper_appears_in_the_register():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    body = _register_text()
    missing = sorted(s.slug for s in all_scrapers() if s.slug not in body)
    assert not missing, (
        f"{len(missing)} source(s) exist in code but are absent from the source "
        f"register: {missing[:10]}"
    )


@pytest.mark.parametrize("module,attr", [
    ("foreclosure_scraper.enrichment_rod_lookup", "LOOKUP_HOSTS"),
    ("foreclosure_scraper.enrichment_rod_name_index", "NAME_INDEX_HOSTS"),
])
def test_every_rod_host_url_is_written_down(module, attr):
    """Naming the county in prose is not enough — the host is the thing a person
    needs, and it is the thing that was missing."""
    import importlib
    from urllib.parse import urlparse

    hosts = getattr(importlib.import_module(module), attr)
    body = _register_text()
    missing = sorted(urlparse(h).netloc for h in hosts.values()
                     if urlparse(h).netloc not in body)
    assert not missing, f"{attr} hosts absent from the register: {missing}"


def test_the_expensive_walls_are_documented():
    """A wall that fails slowly costs more than one that fails fast. These three
    accounted for 16 of the 23 hours in the 2026-08-11 run."""
    body = _register_text()
    for host in ("portal-nc.tylertech.cloud", "publicindex.sccourts.org",
                 "fastpeoplesearch.com"):
        assert host in body, f"{host} burns run time and is not in the register"


def test_handoff_exists_and_points_at_the_register():
    """CLAUDE.md sends a cold session to HANDOFF.md; HANDOFF.md has to lead on
    from there or the chain breaks."""
    handoff = DOCS / "HANDOFF.md"
    assert handoff.exists(), "docs/HANDOFF.md is the documented session entry point"
    body = handoff.read_text()
    assert "SOURCE_REGISTER.md" in body
    claude_md = REPO / "CLAUDE.md"
    assert claude_md.exists()
    assert "HANDOFF.md" in claude_md.read_text()
