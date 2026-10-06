"""verification.registry: verifiers are auto-discovered by naming convention, contract-checked,
and a broken module never takes the others down."""
from __future__ import annotations

import sys
import textwrap

import pytest

from foreclosure_scraper.verification import registry

GOOD = """
from foreclosure_scraper.verification.core import result
SIGNAL = "{signal}"
VERSION = "v3"
TTL_DAYS = 14
GOVERNS = ("{signal}",)
def applies(row):
    return row.get("county") == "{county}"
async def verify(row, client):
    return result(SIGNAL, "wall", {{"reason": "test"}}, version=VERSION)
"""


@pytest.fixture
def fake_pkg(tmp_path, monkeypatch):
    pkg = tmp_path / "fakeverifiers_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "alpha_one.py").write_text(GOOD.format(signal="alpha", county="A"))
    (pkg / "alpha_two.py").write_text(GOOD.format(signal="alpha", county="B"))
    (pkg / "beta.py").write_text(GOOD.format(signal="beta", county="A"))
    (pkg / "_helper.py").write_text("raise RuntimeError('never imported')\n")
    (pkg / "broken_import.py").write_text("import does_not_exist_anywhere\n")
    (pkg / "broken_contract.py").write_text(textwrap.dedent("""
        SIGNAL = "gamma"
        VERSION = ""
        def applies(row): return True
        def verify(row, client): return None
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "fakeverifiers_pkg"
    for m in [m for m in sys.modules if m.startswith("fakeverifiers_pkg")]:
        del sys.modules[m]


def test_discovers_by_convention_and_skips_broken_and_private_modules(fake_pkg):
    vs = registry.discover(fake_pkg)
    assert [v.name for v in vs] == ["alpha_one", "alpha_two", "beta"]
    a1 = vs[0]
    assert (a1.signal, a1.version, a1.ttl_days, a1.governs) == ("alpha", "v3", 14.0, ("alpha",))
    assert a1.retry_days == registry.DEFAULT_RETRY_DAYS and a1.wall is False


def test_several_modules_can_share_a_signal(fake_pkg):
    vs = registry.discover(fake_pkg)
    assert {s: [v.name for v in g] for s, g in registry.by_signal(vs).items()} == {
        "alpha": ["alpha_one", "alpha_two"], "beta": ["beta"]}
    assert registry.verifier_for({"county": "B"}, vs, "alpha").name == "alpha_two"
    assert registry.verifier_for({"county": "Z"}, vs) is None


def test_contract_errors_name_what_is_missing():
    import types
    m = types.ModuleType("bad")
    m.SIGNAL, m.VERSION, m.TTL_DAYS = "Bad Signal!", "v1", -1
    m.applies = lambda r: True

    def verify(row, client):
        return None
    m.verify = verify
    with pytest.raises(registry.ContractError) as ei:
        registry.from_module(m)
    msg = str(ei.value)
    assert "SIGNAL" in msg and "TTL_DAYS" in msg and "async" in msg


def test_a_raising_applies_is_a_no():
    import types

    async def verify(row, client):
        return None
    m = types.ModuleType("raises")
    m.SIGNAL, m.VERSION, m.TTL_DAYS, m.verify = "x", "v1", 1, verify
    m.applies = lambda r: 1 / 0
    assert registry.from_module(m).safe_applies({}) is False


def test_the_real_package_holds_the_reference_verifier():
    vs = registry.discover()
    names = {v.name: v for v in vs}
    assert "tax_lien_buncombe" in names
    v = names["tax_lien_buncombe"]
    assert v.signal == "tax_lien" and v.ttl_days == 30
    assert "tax_lien:property_tax" in v.governs and "recorded_debt:tax" in v.governs


def test_the_sc_divorce_verifier_is_a_wall_that_never_fetches():
    import asyncio
    from foreclosure_scraper.verification.fetch import ReplayFetcher
    from foreclosure_scraper.verification.verifiers import divorce_sc_wall as w
    v = {x.name: x for x in registry.discover()}["divorce_sc_wall"]
    assert v.wall and v.signal == "divorce" and v.governs == ()
    row = {"state": "SC", "county": "Greenville",
           "raw": {"divorce": {"case_count": 2, "cases": [{"case_number": "2024DR2300123"}]}}}
    assert w.applies(row)
    assert not w.applies(dict(row, state="NC"))
    assert not w.applies({"state": "SC", "raw": {"divorce": {"case_count": 0, "cases": []}}})
    f = ReplayFetcher({})
    r = asyncio.run(w.verify(row, f))
    assert r.verdict == "wall" and f.asked == []
    assert r.evidence["case_numbers"] == ["2024DR2300123"] and "terms" in r.evidence["reason"]
