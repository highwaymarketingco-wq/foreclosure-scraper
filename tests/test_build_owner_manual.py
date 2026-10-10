"""scripts/build_owner_manual.py on tiny fixtures (made-up counties, no network, no git)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_owner_manual as B  # noqa: E402


def _card(cid, wall_class="captcha", scope=None, **kw):
    c = {"id": cid, "group": "county", "state": "NC", "county": "Wallton", "place": "Wallton County, NC",
         "name": f"Card {cid}", "kind": "A", "wall": "A CAPTCHA on the search.", "url": "https://example.invalid/",
         "what": "Deeds.", "steps": ["Open the page.", "Pass the check yourself."], "pull": "Deeds.", "save": "Notes.",
         "lane": "None.", "time": "5 minutes.", "often": "Weekly.", "gain": "Deeds.", "others": "The office.",
         "minutes_month": 10, "leads": "a few", "signal_columns": ["lt_foreclosure_sale"],
         "scope": scope or [["NC", "Wallton"]], "short": cid, "loads": "small", "wall_class": wall_class}
    c.update(kw)
    return c


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "county_records").mkdir(parents=True)
    (tmp_path / "docs" / "gap_matrix").mkdir(parents=True)
    (tmp_path / "src" / "foreclosure_scraper").mkdir(parents=True)
    reg = {
        "what_changed": ["First build."], "kind_def": {"A": "<b>A</b> a person.", "B": "<b>B</b> paid.", "C": "<b>C</b> allowed."},
        "decisions": [["Click-throughs are allowed.", "A plain click is not a wall."]],
        "built_static": [{"title": "Thing.", "text": "Built.", "evidence": [{"path": "docs/walls_register.json"}]}],
        "manual_intro": "Only real walls.", "appendix_c_intro": "Not walls.",
        "cards": [_card("wallton_deeds"), _card("clickton_terms", wall_class="click", county="Clickton", scope=[["NC", "Clickton"]])],
        "foia": {"text": "Send requests.", "minutes": "15 minutes"},
        "top15": [{"cards": ["wallton_deeds"], "task": "Check Wallton deeds", "minutes": 10, "often": "weekly"}],
        "appendix_c": [["A site", "Terms only.", "Buildable."]], "paid": [["PACER", "$0.10 a page", "Dockets", "CourtListener"]],
        "does_not_exist": [["Payoff", "Servicer only."]], "stop": [["Old saves", "Automatic."]], "gaps": ["None."],
        "sources_static": ["Fixtures."], "saving_md": ["Save pages."], "saving_html": ["<p>Save pages.</p>"],
        "file_map": {"intro": "Where files go.", "rows": [], "small_row": {"what": "Saved pages", "from": "x", "save": "x", "where": "~/Downloads", "next": "Tell Claude", "board": "Nothing"},
                     "crm_row": {"what": "Notes", "from": "x", "save": "x", "where": "CRM", "next": "Nothing", "board": "Nothing"}},
        "unknown_bullets": ["Nothing."],
    }
    (tmp_path / "docs" / "walls_register.json").write_text(json.dumps(reg))

    def county(name, rod_access):
        return {"county": name, "state": "NC", "rod": {"access": rod_access, "url": f"https://{name.lower()}.invalid/"},
                "probate": {"access": "captcha"}, "tax": {"access": "open"}, "manual_lane": None}
    matrix = {"counties": [county("Wallton", "captcha"), county("Clickton", "disclaimer_click"),
                           county("Builtton", "open"), county("Guestville", "login")]}
    (tmp_path / "docs" / "county_records" / "county_records_matrix.json").write_text(json.dumps(matrix))
    (tmp_path / "docs" / "county_records" / "nc_rod_platform_clusters.md").write_text(
        "# NC\n\n## Person needed\n\n| county | platform | what stops a script | seen |\n|---|---|---|---|\n"
        "| Guestville | Cott eSearch | the search URL lands on the 'Account Sign In' page (username and password form plus a 'Sign in as a Guest' button) | live |\n"
        "| Wallton | CCHS | Cloudflare challenge | live |\n\n## Next\n")
    (tmp_path / "src" / "foreclosure_scraper" / "enrichment_generic_rod.py").write_text(
        'ROD_CONFIG = {\n    ("NC", "Builtton"): ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),\n}\n')
    (tmp_path / "docs" / "gap_matrix" / "county_signal_coverage_2026-10-07.csv").write_text(
        "State,County,Rows,lt_foreclosure_sale\nNC,Wallton,2000,0.0\nNC,Clickton,500,0.0\nNC,Builtton,800,5.0\nNC,Guestville,100,0.0\n")
    (tmp_path / "run_meta.json").write_text(json.dumps({"run_time": "2026-10-07T00:00:00Z", "source_status": {
        "national.locked": "DORMANT — disabled: login-gated since the search moved behind an account",
        "national.gone": "DORMANT — disabled: dead endpoint (404), redundant",
        "national.fine": "OK (5)",
        "counties_nc.walled_today": "🔴 ALARM — BLOCKED: HTTP 403 (blocked/forbidden)"}}))
    return tmp_path


def _model(repo: Path):
    return B.build_model(repo, offline=True, run_meta_path=repo / "run_meta.json")


def _build(repo: Path, *extra):
    return B.main(["--repo", str(repo), "--run-meta", str(repo / "run_meta.json"), "--no-pdf",
                   "--md", str(repo / "out.md"), "--html", str(repo / "out.html"), *extra])


def test_click_through_and_guest_button_are_never_walls(repo):
    assert B.classify_access("disclaimer_click") == B.ALLOWED
    assert B.classify_text("disclosure popup (checkbox + Submit)") == B.ALLOWED
    assert B.classify_text("'Account Sign In' page with a password form plus a 'Sign in as a Guest' button") == B.ALLOWED
    m = _model(repo)
    rod = {c["county"]: c["sys"]["rod"]["class"] for c in m["counties"]}
    assert rod["Clickton"] == B.ALLOWED
    assert rod["Guestville"] == B.ALLOWED  # the cluster doc's guest button overrides the matrix's 'login'


def test_walled_county_needs_a_person(repo):
    m = _model(repo)
    rod = {c["county"]: c["sys"]["rod"]["class"] for c in m["counties"]}
    assert rod["Wallton"] == B.BOT  # the live cluster check wins over the matrix
    n = B.counts(m)
    assert n["county_A"] == 1 and n["county_B"] == 0
    assert m["tally"]["nc_estates"] == 4  # the one statewide eCourts CAPTCHA, kept apart


def test_built_adapter_is_computed_from_the_registry(repo):
    m = _model(repo)
    assert m["tally"]["built"] == 1
    assert any(b["title"] == "Deed reader nc_cott_v4." and "off by default" in b["text"] for b in m["built"])
    md = B.build_md(m)
    assert "Reader: nc_cott_v4 (FORECLOSURE_NC_COTT_ROD, off)" in md


def test_dormant_scraper_is_classified(repo):
    m = _model(repo)
    d = {x["source"]: x["class"] for x in m["dormant"]}
    assert d == {"national.gone": B.NONE, "national.locked": B.LOGIN}
    assert [b["source"] for b in m["blocked"]] == ["counties_nc.walled_today"]
    md = B.build_md(m)
    assert "| national.locked |" in md and "yes: Login" in md


def test_click_card_moves_to_appendix_c(repo):
    m = _model(repo)
    md = B.build_md(m)
    assert "#### Card clickton_terms" not in md
    assert "| Card clickton_terms |" in md
    assert B.counts(m)["A"] == 1


def test_check_detects_stale_inputs(repo, capsys):
    assert _build(repo) == 0
    assert (repo / "docs" / "owner_manual_inputs.json").exists()
    assert (repo / "out.md").read_text().startswith("# What you can do by hand")
    capsys.readouterr()
    assert _build(repo, "--check") == 0
    p = repo / "src" / "foreclosure_scraper" / "enrichment_generic_rod.py"
    p.write_text(p.read_text().replace("}\n", '    ("NC", "Wallton"): ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),\n}\n'))
    mp = repo / "docs" / "county_records" / "county_records_matrix.json"
    mp.write_text(mp.read_text().replace('"open"', '"captcha"', 1))
    assert _build(repo, "--check") == 1
    out = capsys.readouterr().out
    assert "registered deed adapter added: NC|Wallton|nc_lookup" in out
    assert "input file changed: docs/county_records/county_records_matrix.json" in out


def test_file_map_section_covers_every_card(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bom_fm", Path(__file__).resolve().parent.parent / "scripts" / "build_owner_manual.py")
    bom = importlib.util.module_from_spec(spec); spec.loader.exec_module(bom)
    reg = json.loads((Path(__file__).resolve().parent.parent / "docs" / "walls_register.json").read_text())
    rows = bom.file_map(reg)
    named = {n for r in rows for n in r["names"]}
    assert named == {c["short"] for c in reg["cards"]}
    text = " ".join(" ".join(bom._fm_cells(r)) for r in rows)
    for must in ("dnc_registry.csv", "internal_dnc.csv", "Records_Requests/Received", "owner_inputs", "Court Pages (drop here)"):
        assert must in text
