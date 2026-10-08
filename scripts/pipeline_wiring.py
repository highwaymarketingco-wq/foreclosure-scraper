#!/usr/bin/env python3
"""What the run actually runs: the import graph from the run's entry points, and the env flags.

WHY (audit 2026-10-09, pipeline_gate)
    Enrichers were built, tested and never wired (deed_chain sat outside the run for months; the
    10/6 petition-address parser; others). A module the run never imports is a lead field that never
    fills, and nothing says so. Env flags drift the same way: a platform switched ON in
    deploy/oracle/vm_lib.sh that no code reads any more, or a code default nobody meant to ship.

WHAT IT COMPUTES (static, no imports of the package, no network, a few seconds)
    * the import graph of src/foreclosure_scraper (every `import` / `from ... import` anywhere in a
      file, including inside functions, plus the dynamic package loads this codebase uses:
      importlib.import_module(f"foreclosure_scraper.rod.{x}") and friends load the whole package);
    * RUN-REACHABLE modules: reachable from foreclosure_scraper.main (the full run and, through
      main.run_enrich_tail/publish_tail, the checkpoint resume) plus every module the scraper
      registry auto-discovers (scrapers/_registry._PACKAGES);
    * UNWIRED modules: enrichment_* modules and scraper-package modules with a scraper class that
      no run path reaches, each with the scripts/ files that import it (script-only) or none (dead);
    * env flags: every os.environ.get / os.getenv / environ[...] name in src/ and scripts/ with its
      code default, the flags deploy/oracle/vm_lib.sh exports, and the three disagreements
      (VM on / code off, VM off / code on, a VM flag no code reads).

USAGE
    uv run python scripts/pipeline_wiring.py            # report
    uv run python scripts/pipeline_wiring.py --json     # machine-readable (counts and names only)
Exit 0 always (it reports; scripts/prerun_gate.py decides).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
PKG = "foreclosure_scraper"
VM_LIB = REPO / "deploy" / "oracle" / "vm_lib.sh"

#: packages the scraper registry auto-discovers (scrapers/_registry._PACKAGES), read from the file
#: so a new package there is picked up; this is only the fallback.
_REGISTRY_FALLBACK = ("national", "public_notices", "law_firms", "counties_sc", "counties_nc",
                      "counties_generic", "newspapers", "reo", "city_websites")

#: modules that load a whole package by name at run time (the static graph cannot see which ones):
#: verification.registry imports every verifier module; the rest use an f-string prefix the scanner
#: reads itself, listed here only when the prefix is a variable.
_DYNAMIC_PACKAGE_LOADERS = {f"{PKG}.verification.registry": f"{PKG}.verification"}

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


# ---------------------------------------------------------------------------------- import graph
def module_name(path: Path, src: Path = SRC) -> str:
    rel = path.relative_to(src).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def iter_modules(src: Path = SRC, pkg: str = PKG):
    for p in sorted((src / pkg).rglob("*.py")):
        if "__pycache__" in p.parts or "_vendor" in p.parts:
            continue
        yield module_name(p, src), p


def _resolve_from(mod: str, is_pkg: bool, level: int, target: str | None) -> str:
    base = mod.split(".") if is_pkg else mod.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join(base + ([target] if target else []))


def _joined_prefix(node) -> str | None:
    """The constant prefix of an f-string (JoinedStr), e.g. 'foreclosure_scraper.rod.'."""
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        v = node.values[0].value
        return v if isinstance(v, str) else None
    return None


def file_imports(mod: str, path: Path, known: set[str]) -> tuple[set[str], set[str]]:
    """(modules imported, packages loaded whole) by one file, as dotted names inside the package."""
    is_pkg = path.name == "__init__.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set(), set()
    out: set[str] = set()
    whole: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(PKG):
                    out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _resolve_from(mod, is_pkg, node.level, node.module)
            else:
                base = node.module or ""
            if not base.startswith(PKG):
                continue
            out.add(base)
            for a in node.names:
                sub = f"{base}.{a.name}"
                if sub in known:
                    out.add(sub)
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in ("import_module", "__import__") or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                tgt = arg.value
                if tgt.startswith("."):
                    lvl = len(tgt) - len(tgt.lstrip("."))
                    tgt = _resolve_from(mod, is_pkg, lvl, tgt.lstrip(".") or None)
                if tgt.startswith(PKG):
                    out.add(tgt)
            pre = _joined_prefix(arg)
            if pre:
                if pre.startswith("."):
                    lvl = len(pre) - len(pre.lstrip("."))
                    pre = _resolve_from(mod, is_pkg, lvl, pre.lstrip(".").rstrip(".") or None) + "."
                if pre.startswith(PKG + "."):
                    whole.add(pre.rstrip("."))
    if mod in _DYNAMIC_PACKAGE_LOADERS:
        whole.add(_DYNAMIC_PACKAGE_LOADERS[mod])
    return out, whole


def import_graph(src: Path = SRC) -> dict[str, set[str]]:
    mods = dict(iter_modules(src))
    known = set(mods)
    graph: dict[str, set[str]] = {}
    for mod, path in mods.items():
        imp, whole = file_imports(mod, path, known)
        edges = {m for m in imp if m in known}
        for pkg in whole:
            edges |= {m for m in known if m.startswith(pkg + ".")}
        # importing a.b.c runs a/__init__ and a/b/__init__
        for m in list(edges):
            parts = m.split(".")
            for i in range(1, len(parts)):
                parent = ".".join(parts[:i])
                if parent in known:
                    edges.add(parent)
        graph[mod] = edges - {mod}
    return graph


def registry_packages(src: Path = SRC) -> tuple[str, ...]:
    p = src / PKG / "scrapers" / "_registry.py"
    try:
        tree = ast.parse(p.read_text())
    except (OSError, SyntaxError):
        return tuple(f"{PKG}.scrapers.{x}" for x in _REGISTRY_FALLBACK)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_PACKAGES" for t in node.targets):
            try:
                return tuple(ast.literal_eval(node.value))
            except ValueError:
                break
    return tuple(f"{PKG}.scrapers.{x}" for x in _REGISTRY_FALLBACK)


def discovered_scraper_modules(src: Path = SRC) -> set[str]:
    """What scrapers/_registry.discover() imports: every non-underscore, non-package module
    directly inside each registry package."""
    out = set()
    for pkg in registry_packages(src):
        d = src / Path(*pkg.split("."))
        for p in sorted(d.glob("*.py")):
            if not p.name.startswith("_"):
                out.add(f"{pkg}.{p.stem}")
    return out


def reachable(graph: dict[str, set[str]], roots) -> set[str]:
    seen: set[str] = set()
    todo = [r for r in roots if r in graph]
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        todo.extend(graph.get(m, ()))
    return seen


def run_roots(src: Path = SRC) -> set[str]:
    return {f"{PKG}.main", f"{PKG}.scrapers._registry", *discovered_scraper_modules(src)}


def _has_scraper_class(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for b in node.bases:
                n = b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                if n.endswith("Scraper"):
                    return True
    return False


def _defines_enrich(path: Path) -> bool:
    """A top-level function named enrich* (an enrichment step living outside enrichment_*.py)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("enrich")
               for n in tree.body)


def script_importers(repo: Path = REPO) -> dict[str, list[str]]:
    """module -> scripts/*.py that import it (directly, `foreclosure_scraper.x` or `from
    foreclosure_scraper import x`)."""
    known = {m for m, _ in iter_modules(repo / "src")}
    out: dict[str, list[str]] = defaultdict(list)
    for p in sorted((repo / "scripts").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        imp, whole = file_imports("scripts." + p.stem, p, known)
        rel = str(p.relative_to(repo))
        for m in imp:
            if m in known:
                out[m].append(rel)
        for pkg in whole:
            for m in known:
                if m.startswith(pkg + "."):
                    out[m].append(rel)
    return out


def unwired(repo: Path = REPO) -> list[dict]:
    """enrichment_* modules and scraper-class modules that no run path reaches."""
    src = repo / "src"
    graph = import_graph(src)
    reach = reachable(graph, run_roots(src))
    importers = script_importers(repo)
    paths = dict(iter_modules(src))
    rows = []
    for mod, path in paths.items():
        short = mod[len(PKG) + 1:]
        leaf = short.rsplit(".", 1)[-1]
        if mod in reach:
            continue
        if leaf.startswith("enrichment_"):
            kind = "enrichment"
        elif _has_scraper_class(path):
            kind = "scraper"
        elif _defines_enrich(path) and not short.startswith(("scrapers.", "rod.", "verification.",
                                                              "quiet_title.", "assessor_cards.")):
            kind = "enricher"
        else:
            continue
        rows.append({"module": short, "kind": kind,
                     "scripts": sorted(set(importers.get(mod, []))),
                     "status": "script_only" if importers.get(mod) else "dead"})
    return sorted(rows, key=lambda r: (r["kind"], r["module"]))


# ---------------------------------------------------------------------------- whole-file loads
#: a file-path literal or name that is board-scale on the VM (the plain board is 4.1 GB at 350K rows;
#: a checkpoint ~0.3 GB gzipped, ~4 GB decoded)
_BOARD_SCALE = re.compile(r"listings(_part|_detail|_slim)?[^\"']*\.json|board\.json\.gz|LISTINGS|BOARD_FILE|CHECKPOINT")
_WHOLE_READ = re.compile(r"read_text|read_bytes|\.read\(\)|decompress")


def whole_file_json_loads(repo: Path = REPO, roots: set[str] | None = None) -> list[dict]:
    """json.load / json.loads of a whole file's contents inside a function that names a
    board-scale file, in every module the run reaches: the pattern that had the watchdog kill
    the 10/7 and 10/8 full runs in carryover (json.loads of the 4.1 GB prior board). Heuristic
    and deliberately broad: small files (manifests, run_meta, the high-water mark) match too and
    are allowlisted by name in deploy/oracle/run_profile.json, so a NEW hit is what fails."""
    src = repo / "src"
    graph = import_graph(src)
    reach = reachable(graph, roots if roots is not None else run_roots(src))
    paths = dict(iter_modules(src))
    out = []
    for mod in sorted(reach):
        text = paths[mod].read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        parents = {}
        for node in ast.walk(tree):
            for ch in ast.iter_child_nodes(node):
                parents[ch] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("load", "loads") and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("json", "_json", "_gj", "_j", "orjson")):
                continue
            seg = ast.get_source_segment(text, node) or ""
            if node.func.attr == "loads" and not _WHOLE_READ.search(seg):
                continue
            fn = node
            while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = parents[fn]
            body = ast.get_source_segment(text, fn) if fn is not tree else text
            if not _BOARD_SCALE.search(body or ""):
                continue
            out.append({"site": f"{mod[len(PKG) + 1:]}:{getattr(fn, 'name', '<module>')}",
                        "line": node.lineno, "call": seg[:100]})
    return out


# ------------------------------------------------------------------------------------- env flags
def _const_str(n) -> str | None:
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


def _is_environ(n) -> bool:
    # os.environ / _os.environ / environ
    return (isinstance(n, ast.Attribute) and n.attr == "environ") or getattr(n, "id", "") == "environ"


def code_flags(roots=(SRC / PKG, REPO / "scripts")) -> dict[str, list[dict]]:
    """name -> [{file, line, default}] for every env read with a literal name; default is the
    literal default when given (None = unset)."""
    out: dict[str, list[dict]] = defaultdict(list)
    for root in roots:
        for p in sorted(Path(root).rglob("*.py")):
            if "__pycache__" in p.parts or "_vendor" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            rel = str(p.relative_to(REPO))
            for node in ast.walk(tree):
                name = default = None
                if isinstance(node, ast.Call):
                    fn = node.func
                    if isinstance(fn, ast.Attribute) and fn.attr in ("get", "pop", "setdefault") \
                            and _is_environ(fn.value) and node.args:
                        name = _const_str(node.args[0])
                        if len(node.args) > 1:
                            d = node.args[1]
                            default = repr(d.value) if isinstance(d, ast.Constant) else "<expr>"
                    elif (isinstance(fn, ast.Attribute) and fn.attr == "getenv") or \
                            getattr(fn, "id", "") == "getenv":
                        if node.args:
                            name = _const_str(node.args[0])
                            if len(node.args) > 1:
                                d = node.args[1]
                                default = repr(d.value) if isinstance(d, ast.Constant) else "<expr>"
                elif isinstance(node, ast.Subscript) and _is_environ(node.value):
                    name = _const_str(node.slice)
                    default = "<required>"
                elif isinstance(node, ast.Compare) and len(node.comparators) == 1 \
                        and _is_environ(node.comparators[0]):
                    name = _const_str(node.left)
                    default = "<presence>"
                if name and _ENV_NAME.match(name):
                    out[name].append({"file": rel, "line": node.lineno, "default": default})
    return out


def literal_mentions(name: str, roots=(SRC / PKG, REPO / "scripts")) -> int:
    """How many .py files mention the name as a string (registry tables pass flag names around)."""
    n = 0
    pat = f'"{name}"'
    pat2 = f"'{name}'"
    for root in roots:
        for p in Path(root).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            if pat in t or pat2 in t:
                n += 1
    return n


_EXPORT = re.compile(r'^\s*export\s+([A-Z][A-Z0-9_]*)="?\$\{\1:-([^}]*)\}"?')
_EXPORT_PLAIN = re.compile(r'^\s*export\s+([A-Z][A-Z0-9_]*)=("?)([^"$]*)\2\s*$')


def vm_lib_flags(path: Path = VM_LIB) -> dict[str, str]:
    """name -> value vm_load_env() exports (the `${X:-default}` default, or a plain value). Secrets
    are `load`ed, never exported this way, so none appear here."""
    out: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        m = _EXPORT.match(line)
        if m:
            out[m.group(1)] = m.group(2)
            continue
        m = _EXPORT_PLAIN.match(line)
        if m:
            out[m.group(1)] = m.group(3)
    return out


def _truthy(v) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().strip("'\"").lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return None


#: flags whose value is not an on/off switch (numbers, names) are compared as text only
def flag_disagreements(vm: dict[str, str] | None = None, code: dict | None = None) -> dict:
    vm = vm_lib_flags() if vm is None else vm
    code = code_flags() if code is None else code
    vm_on_code_off, vm_off_code_on, dead, numeric = [], [], [], []
    indirect = []
    for name, val in sorted(vm.items()):
        # the run's own defaults: src/ only (a script's default is that script's business)
        sites = [s for s in code.get(name, []) if s["file"].startswith("src/")]
        if not sites:
            if literal_mentions(name) == 0:
                dead.append(name)
            else:
                indirect.append({"flag": name, "vm": val})
            continue
        defaults = sorted({s["default"] for s in sites if s["default"] is not None})
        vt = _truthy(val)
        cts = {_truthy(d) for d in defaults}
        if not defaults:
            cts = {False}       # unset in code = off
        if vt is True and cts and all(c is False for c in cts):
            vm_on_code_off.append({"flag": name, "vm": val, "code_defaults": defaults or ["unset"]})
        elif vt is False and True in cts:
            vm_off_code_on.append({"flag": name, "vm": val, "code_defaults": defaults})
        elif vt is None:
            numeric.append({"flag": name, "vm": val, "code_defaults": defaults or ["unset"]})
    for lst in (vm_on_code_off, vm_off_code_on, numeric, indirect):
        for r in lst:
            if "@" in str(r.get("vm")):
                r["vm"] = "<addresses>"      # never echo mail addresses into reports
    return {"vm_on_code_off": vm_on_code_off, "vm_off_code_on": vm_off_code_on,
            "vm_flag_never_read": dead, "valued": numeric, "read_indirectly": indirect}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    uw = unwired()
    fl = flag_disagreements()
    if a.json:
        print(json.dumps({"unwired": uw, "flags": fl}, indent=1))
        return 0
    print(f"UNWIRED modules (no run path reaches them): {len(uw)}")
    for r in uw:
        where = ", ".join(r["scripts"][:3]) + (" ..." if len(r["scripts"]) > 3 else "")
        print(f"  {r['kind']:<10} {r['status']:<11} {r['module']}" + (f"  <- {where}" if where else ""))
    print("\nFLAGS vm_lib.sh vs code defaults")
    for k in ("vm_on_code_off", "vm_off_code_on"):
        print(f"  {k}: {len(fl[k])}")
        for r in fl[k]:
            print(f"    {r['flag']}={r['vm']} (code {', '.join(r['code_defaults'])})")
    print(f"  vm_flag_never_read: {fl['vm_flag_never_read']}")
    print("  valued (not on/off): " + ", ".join(f"{r['flag']}={r['vm']}" for r in fl["valued"]))
    print("  read only through a table (registry tuples): "
          + ", ".join(f"{r['flag']}={r['vm']}" for r in fl["read_indirectly"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
