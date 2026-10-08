"""Every raw key an enricher writes must survive the publish slim.

`web_artifact._slim_raw()` copies only the keys named in `RAW_KEEP`. Anything else
is dropped at write time, silently, with no error and no log line -- so an
enricher can run perfectly, cost hours of politely rate-limited fetching, and
leave nothing on the board.

That is not hypothetical. On 2026-09-10 the LiensNC related-filings enricher wrote
`raw['liensnc_related']` for 1,500 entries -- owner phone, email and mailing
address, the exact contactability the engine had been short of -- and a scan of
the resulting board found the key on ZERO rows. RAW_KEEP had never named it. The
run reported success the whole way.

This test walks the enrichment modules for literal `raw[...] = ` assignments and
asserts each key is either in RAW_KEEP or explicitly listed below as intentionally
internal. It is deliberately a source scan rather than a runtime check: the point
is to fail in CI the moment someone adds a new enricher, not after a long harvest.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from foreclosure_scraper.web_artifact import RAW_KEEP

SRC = Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper"

# Keys deliberately NOT published: scratch state, provenance the dashboard never
# reads, or values folded into another published key before the write.
INTENTIONALLY_INTERNAL = {
    "_seen_this_run", "_from_prior_board", "_idx", "_merged_idxs",
    "_partial", "_tmp", "_scratch", "_debug",
    # Redundant with something already published — verified 2026-09-10, not guessed:
    # `living_sqft_estimated` is a top-level Listing FIELD and ships in the row itself.
    "living_sqft_estimated",
    # `gis_attrs` is a summary of `gis_attrs_full`, which IS in RAW_KEEP.
    "gis_attrs",
    # `property_kind_reclassified` is provenance; `property_kind` is a published field.
    "property_kind_reclassified",
    # `vision_unscored` is DELIBERATELY unpublished, and this one bit me: I added it
    # to RAW_KEEP during the 2026-09-10 dropped-key audit and broke
    # test_ungraded_report_never_reaches_the_published_board. An ungraded vision
    # report on the board is indistinguishable from a real grade to anything reading
    # raw['vision*'], so the dashboard would present a failed model call as a
    # condition assessment. The diagnostic stays in-process via the
    # vision.listing_ungraded log line.
    "vision_unscored",
    # PRIVACY, 2026-10-07 (enrichment_obituary_match): the whole obituary survivor list (in-laws,
    # grandchildren, ages). Not published; the publishable subset of those names reaches the board
    # through raw['heir_candidates'] (enrichment_heir_candidates.PUBLISHABLE_HEIR_RELATIONS).
    "obituary_match",
}


def _raw_keys_written(path: Path) -> set[str]:
    """Literal string keys assigned into a `raw`-ish dict in this module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Subscript):
                continue
            if not isinstance(tgt.slice, ast.Constant) or not isinstance(tgt.slice.value, str):
                continue
            base = tgt.value
            # li.raw["x"] = ...  /  raw["x"] = ...
            name = None
            if isinstance(base, ast.Attribute) and base.attr == "raw":
                name = "raw"
            elif isinstance(base, ast.Name) and base.id in ("raw", "_raw"):
                name = "raw"
            if name:
                found.add(tgt.slice.value)
    return found


def _enrichment_modules() -> list[Path]:
    return sorted(
        p for p in SRC.glob("enrich*.py")
        if p.is_file() and not p.name.startswith("_")
    )


def test_there_are_enrichment_modules_to_check():
    """Guard the guard: a glob that silently matches nothing would pass forever."""
    mods = _enrichment_modules()
    assert len(mods) > 20, f"only found {len(mods)} enrichment modules — glob is wrong"


@pytest.mark.parametrize("module", _enrichment_modules(), ids=lambda p: p.name)
def test_enricher_raw_keys_survive_the_publish_slim(module):
    written = _raw_keys_written(module)
    unpublished = {
        k for k in written
        if k not in RAW_KEEP and k not in INTENTIONALLY_INTERNAL and not k.startswith("_")
    }
    assert not unpublished, (
        f"{module.name} writes raw keys that _slim_raw() will silently DROP at "
        f"publish: {sorted(unpublished)}. Either add them to RAW_KEEP in "
        f"web_artifact.py, or add them to INTENTIONALLY_INTERNAL in this test with "
        f"a reason. Do not leave them unlisted — that is how 1,500 owner phone "
        f"numbers were harvested and thrown away on 2026-09-10."
    )


def test_the_two_keys_that_were_actually_lost_are_now_covered():
    """Direct regression pin for the 2026-09-10 loss."""
    assert "liensnc_related" in RAW_KEEP
    assert "fullmer" in RAW_KEEP


# ===========================================================================
# SCRAPER raw keys. The tests above cover ENRICHERS only, and that blind spot is
# exactly what let this through: on 2026-09-10 they all passed while 160 of the
# 191 raw keys written by the 219 scrapers were absent from RAW_KEEP, and a scan
# of the live 94,384-row board found ZERO rows carrying ANY key outside the
# allowlist. _slim_raw drops an unlisted key at write with no error and no log,
# so the symptom was "the source runs, the row is there, the detail is empty".
#
# Confirmed at 0 rows each on the live board before the fix: absentee_owner,
# heir_estate, nc_ecourts_divorce, upset_bid_deadline, tax_sale_status, obituary,
# sc_public_index, mcdowell_probate.
# ===========================================================================

import re as _re
from pathlib import Path as _Path

_SCRAPER_DIR = _Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" / "scrapers"

#: Keys a scraper writes that are deliberately NOT published, each with its reason.
#: Add here only with a reason -- an entry without one is how a real signal gets
#: quietly reclassified as noise.
SCRAPER_KEYS_INTENTIONALLY_INTERNAL = {
    # 2026-10-07: surfaced when the scan learned the annotated `raw: dict = {...}` form.
    # Each is a bare True provenance flag beside the published raw['rod'] block; the
    # row's own source (sc_rod_acclaim / sc_rod_cott / nc_rod_logan) already names the
    # vendor, so no data is lost.
    "acclaim_rod": "provenance flag (True) beside the published raw['rod'] block",
    "cott_rod": "provenance flag (True) beside the published raw['rod'] block",
    "logan_rod": "provenance flag (True) beside the published raw['rod'] block",
    "source_url": "duplicates the Listing.source_url column; a raw copy shadowing a "
                  "real field invites the two disagreeing",
    "documents": "generic bag already carried by the document_links / doc_ocr keys",
    "obituary_private": "PRIVACY (2026-10-07): the parsed survivor list of an obituary -- private "
                        "people's names -- carried from the obituary scrapers to "
                        "enrichment_obituary_match in-process only; the public board gets the "
                        "decedent block (raw['obituary']) and counts, the names go to the gitignored "
                        "data/heirs/ store",
    # 2026-10-04: surfaced by extending the scraper scan to walk raw={...} dict-literal
    # ASTs directly (see _scraper_raw_dict_literal_keys) instead of a regex that could
    # only ever see a literal's first key. Each of these, verified against its own
    # scraper source, assigns the exact same variable to both raw[...] and an
    # already-published top-level Listing field -- a real duplicate, not a dropped
    # signal, so it belongs here rather than in RAW_KEEP.
    "city": "national.fdic_failed_banks writes the same `city` variable into both "
            "raw['city'] and the top-level Listing.city field",
    "state": "national.fdic_failed_banks writes the same `state` variable into both "
             "raw['state'] and the top-level Listing.state field",
    "description": "counties_sc.cherokee_delinquent_tax writes the same `desc` variable "
                    "into both raw['description'] and street_address (the parsed legal "
                    "description IS the situs text for this source)",
    "parcel": "counties_sc.abbeville_delinquent_tax writes the same `parcel` variable "
              "into both raw['parcel'] and the top-level Listing.parcel_id field",
    "price": "national.va_acquired writes the same `price` variable into both "
             "raw['price'] and the top-level Listing.opening_bid field",
    "source": "national.nc_sos_ucc hardcodes raw['source']='nc_sos_ucc', identical to "
              "the top-level Listing.source field (self.slug) on every row it emits",
}


def _scraper_raw_dict_literal_keys(path: _Path) -> set[str]:
    """Every literal string key of a `raw={...}` dict, found by walking the real
    AST dict node rather than regexing around it.

    This exists because of a confirmed gap in the regex scan just below: its
    dict-literal pattern is anchored on `raw\\s*=\\s*\\{\\s*["\\']...` and can
    only ever capture the ONE key immediately following the opening brace --
    a plain regex has no notion of matching braces, so it cannot tell where
    that dict ends, let alone walk its other comma-separated siblings. Every
    key after the first in a multi-key literal is therefore invisible to it,
    silently, which is exactly the shape of the bug this whole test file
    exists to catch.

    Live-confirmed 2026-10-04 against reo/vrm_va_reo.py's pre-fix literal --
    `raw={"vrm_id": ..., "beds": ..., "baths": ..., "sqft": ..., "list_price":
    ..., "images": ...}` -- where the regex scan below finds only `vrm_id`;
    `beds`/`baths`/`sqft`/`list_price`/`images` (items 2-6) do not appear in
    its output at all, so registering or un-registering them in RAW_KEEP had
    zero effect on `test_every_scraper_raw_key_survives_publish`'s result.
    This AST pass walks the dict node directly, so every key is seen
    regardless of its position in the literal.

    Covers both shapes the codebase uses:
      - `Listing(..., raw={"a": ..., "b": ...})`  -- a dict literal passed as
        a keyword argument to any call (not just `Listing` by name, since
        scrapers alias/wrap the constructor in a few places).
      - `raw = {"a": ..., "b": ...}` / `li.raw = {...}` -- a plain assignment
        of a dict literal to a `raw`-named target.
    Only the dict's own top-level keys are collected -- a nested dict VALUE
    (e.g. `"images": {"real": photos}`) is left alone, since `RAW_KEEP`
    entries are namespaces ("*") covering their whole subtree, not individual
    subkeys.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()

    found: set[str] = set()

    def _collect(dict_node: ast.Dict) -> None:
        for k in dict_node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                found.add(k.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "raw" and isinstance(kw.value, ast.Dict):
                    _collect(kw.value)
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Dict)
              and isinstance(node.target, ast.Name) and node.target.id in ("raw", "_raw")):
            # `raw: dict = {...}` / `raw: dict[str, Any] = {...}` -- the annotated form
            # was invisible to this scan, which is how spartanburg_condemned's
            # condemned_signal and henderson_foreclosure_parcels' tax_foreclosure went
            # unregistered (found by the 2026-10-07 extraction audit).
            _collect(node.value)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for tgt in node.targets:
                is_raw = (
                    (isinstance(tgt, ast.Attribute) and tgt.attr == "raw")
                    or (isinstance(tgt, ast.Name) and tgt.id in ("raw", "_raw"))
                )
                if is_raw:
                    _collect(node.value)
    return found


def _scraper_raw_keys() -> dict[str, set[str]]:
    """Every key any scraper writes into Listing.raw, mapped to the modules doing it."""
    out: dict[str, set[str]] = {}
    for f in sorted(_SCRAPER_DIR.rglob("*.py")):
        t = f.read_text()
        keys = set(_re.findall(r'raw\s*=\s*\{\s*["\']([A-Za-z0-9_]+)["\']', t))
        keys |= set(_re.findall(r'\braw\[\s*["\']([A-Za-z0-9_]+)["\']\s*\]\s*=', t))
        keys |= set(_re.findall(r'\braw\.setdefault\(\s*["\']([A-Za-z0-9_]+)["\']', t))
        keys |= _scraper_raw_dict_literal_keys(f)
        for k in keys:
            out.setdefault(k, set()).add(f.stem)
    return out


def test_the_audit_actually_finds_scraper_keys():
    """Guards the guard. If the regexes stop matching -- someone builds raw a new
    way -- this test would pass vacuously and stop protecting anything."""
    keys = _scraper_raw_keys()
    assert len(keys) > 150, f"only found {len(keys)} scraper raw keys; the scan broke"
    assert "liensnc" in keys


def test_dict_literal_scan_catches_every_sibling_key(tmp_path):
    """Regression pin for the gap this audit found in `reo/vrm_va_reo.py`
    (2026-10-04, commit f7c57c0d): the regex dict-literal pattern only ever
    captures the FIRST key of a `raw={...}` literal. Reproduces that file's
    exact pre-fix shape -- a `Listing(..., raw={...})` call with SIX keys --
    and asserts both halves of the regression:
      1. the plain regex alone (what shipped before this fix) really does
         miss every key but the first, proving the gap was real and not
         hypothetical;
      2. `_scraper_raw_dict_literal_keys()` (the new AST pass) finds all six,
         so the combined `_scraper_raw_keys()` scan no longer has this
         blind spot.
    """
    synthetic = tmp_path / "synthetic_vrm_shape.py"
    synthetic.write_text(
        "def _parse_card(card):\n"
        "    return Listing(\n"
        "        source_url=url,\n"
        "        raw={\n"
        "            \"vrm_id\": listing_id,\n"
        "            \"beds\": beds,\n"
        "            \"baths\": baths,\n"
        "            \"sqft\": sqft,\n"
        "            \"list_price\": price,\n"
        "            \"images\": {\"real\": photos} if photos else {},\n"
        "        },\n"
        "    )\n"
    )
    text = synthetic.read_text()
    regex_only = set(re.findall(r'raw\s*=\s*\{\s*["\']([A-Za-z0-9_]+)["\']', text))
    assert regex_only == {"vrm_id"}, (
        f"expected the bare regex to see only the first key (the historical bug), "
        f"got {sorted(regex_only)} -- if this changed, the rest of this pin may be stale"
    )

    ast_keys = _scraper_raw_dict_literal_keys(synthetic)
    expected = {"vrm_id", "beds", "baths", "sqft", "list_price", "images"}
    assert ast_keys == expected, (
        f"AST dict-literal scan should see every sibling key, got {sorted(ast_keys)}, "
        f"expected {sorted(expected)}"
    )


def test_every_scraper_raw_key_survives_publish():
    """THE test. A scraper that writes a key RAW_KEeP does not name is doing work
    that is discarded at publish, and nothing anywhere reports it."""
    from foreclosure_scraper.web_artifact import RAW_KEEP
    keys = _scraper_raw_keys()
    missing = {k: sorted(v) for k, v in sorted(keys.items())
               if k not in RAW_KEEP and k not in SCRAPER_KEYS_INTENTIONALLY_INTERNAL}
    assert not missing, (
        f"{len(missing)} scraper raw key(s) are dropped at publish with no error:\n"
        + "\n".join(f"    {k!r:<34} written by {', '.join(v[:3])}"
                    for k, v in list(missing.items())[:25])
        + "\n\nAdd each to RAW_KEEP in web_artifact.py, or to "
          "SCRAPER_KEYS_INTENTIONALLY_INTERNAL above WITH A REASON."
    )


def test_the_internal_list_states_a_reason_for_every_entry():
    for key, reason in SCRAPER_KEYS_INTENTIONALLY_INTERNAL.items():
        assert reason and len(reason) > 20, (
            f"{key!r} is excluded from publish without a real reason. An unexplained "
            f"exclusion is how a working signal gets reclassified as noise."
        )


def test_the_new_qpaybill_roll_key_is_published():
    """Pins the specific key this audit was triggered by."""
    from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw
    assert "qpaybill_roll" in RAW_KEEP
    kept = _slim_raw({"qpaybill_roll": {"balance_owed": 130.55, "is_two_year_plus": True}})
    assert kept["qpaybill_roll"]["balance_owed"] == 130.55


# ===========================================================================
# EVERY MODULE (audit 2026-10-09, drops_lineage). The two scans above read enrich*.py and
# scrapers/ only, and only `raw["k"] = ...` / `raw={...}`. Measured on the 2026-10-08 gated run's
# dot_ocr checkpoint (383,373 rows, full raw): keys written by main.py (situs_nulled 8,606 rows,
# coastal_county 6,207, oceanfront ...), board_persist.py (mailing_address_not_inherited 683),
# parcel_alias.py (parcel_id_alias 680, read back by tax_binding), nc_lincoln_bulk.py (14,893),
# nc_burke_spine.py (533, read back by enrichment_lrcpwa_parcel), enrichment_prior_correction
# (withdrawn_case_type_other 260) were all dropped at publish, along with enrichers that build a
# `raw_update` dict and merge it (`li.raw = {**li.raw, **raw_update}`), `setdefault`/`update`
# writes, and a conditional `raw={...} if ... else None` literal (law_firms.mcmichael_taylor_gray's
# sp_case). This scan covers all of them, in every module.
# ===========================================================================

#: Keys some module writes into Listing.raw that are deliberately NOT published, each with its reason.
MODULE_KEYS_INTENTIONALLY_INTERNAL = {
    "_equity_amortization": "enrichment_equity's in-run scratch detail, popped by its own caller "
                            "before the row is stored",
    "detail_page": "PRIVACY: enrichment_judgment_detail keeps up to 5,000 characters of a court "
                   "page's text (parties' names, notice wording); the repo and board are public",
    "downtown_charleston_pending": "main._in_scope's provisional tag, resolved in the same run by "
                                   "_resolve_coastal_pending (kept rows get downtown_charleston)",
    "oceanfront_pending": "main._in_scope's provisional tag, resolved in the same run by "
                          "_resolve_coastal_pending (kept rows get oceanfront)",
    "latitude": "enrichment_census_geocoder copies its point into raw as well as the top-level "
                "Listing.latitude field, which is what publishes",
    "longitude": "enrichment_census_geocoder copies its point into raw as well as the top-level "
                 "Listing.longitude field, which is what publishes",
    "opening_bid": "enrichment_ocr's raw.setdefault copy of an OCR'd bid shadows the top-level "
                   "Listing.opening_bid field; a raw twin of a real field invites disagreement",
}
_RAW_NAMES = {"raw", "_raw", "raw_update", "new_raw"}


def _is_raw_target(node) -> bool:
    return ((isinstance(node, ast.Attribute) and node.attr == "raw")
            or (isinstance(node, ast.Name) and node.id in _RAW_NAMES))


def _literal_keys(node) -> list[str]:
    """String keys of a dict literal, or of either branch of `{...} if c else {...}/None`."""
    if isinstance(node, ast.Dict):
        return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if isinstance(node, ast.IfExp):
        return _literal_keys(node.body) + _literal_keys(node.orelse)
    return []


def _call_name(fn) -> str:
    return fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")


def _module_raw_keys(path: Path) -> set[str]:
    """Every literal key a module writes into a listing's raw: `X.raw[k] = / += / : T =`, the same
    on a local named raw / _raw / raw_update / new_raw, `.setdefault(k, ...)`, `.update({...})` /
    `.update(k=...)`, a dict literal (or conditional literal) assigned to one of those, and
    `Listing(..., raw={...})`. A key given by a module-level string constant counts too."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    consts = {t.id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
              and isinstance(n.value.value, str) for t in n.targets if isinstance(t, ast.Name)}

    def key(sl):
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return sl.value
        return consts.get(sl.id) if isinstance(sl, ast.Name) else None

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Subscript) and _is_raw_target(t.value):
                    k = key(t.slice)
                    if k:
                        found.add(k)
                if _is_raw_target(t) and getattr(node, "value", None) is not None:
                    found.update(_literal_keys(node.value))
        elif isinstance(node, ast.Call):
            if _call_name(node.func).endswith("Listing"):
                for kw in node.keywords:
                    if kw.arg == "raw":
                        found.update(_literal_keys(kw.value))
            fn = node.func
            if isinstance(fn, ast.Attribute) and _is_raw_target(fn.value):
                if fn.attr == "setdefault" and node.args:
                    k = key(node.args[0])
                    if k:
                        found.add(k)
                elif fn.attr == "update":
                    for a in node.args:
                        found.update(_literal_keys(a))
                    found.update(kw.arg for kw in node.keywords if kw.arg)
    return found


#: rod/ register readers build RodDoc records whose own `.raw` (one recorded instrument) is not a
#: listing's raw; only these rod/ modules write into Listing.raw.
_ROD_LISTING_WRITERS = {"rod/enrich.py"}


def _all_module_raw_keys() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(SRC.rglob("*.py")):
        rel = str(f.relative_to(SRC))
        if rel.startswith("rod/") and rel not in _ROD_LISTING_WRITERS:
            continue
        for k in _module_raw_keys(f):
            out.setdefault(k, set()).add(str(f.relative_to(SRC)))
    return out


def test_the_module_scan_finds_the_forms_that_hid_keys(tmp_path):
    """Guards the guard: each write form the 2026-10-09 audit found keys hiding behind."""
    f = tmp_path / "shapes.py"
    f.write_text(
        "KEY = 'const_key'\n"
        "def a(li, listing):\n"
        "    raw_update = {'marker': True}\n"
        "    raw_update['later'] = 1\n"
        "    listing.raw = {**listing.raw, **raw_update}\n"
        "    li.raw.setdefault('set_default', {})\n"
        "    li.raw.update({'upd_lit': 1}, upd_kw=2)\n"
        "    li.raw[KEY] = 3\n"
        "    return Listing(raw={'cond_a': 1} if li else None)\n"
        "def b(doc):\n"
        "    return RodDoc(raw={'not_a_listing': 1})\n")
    assert _module_raw_keys(f) == {"marker", "later", "set_default", "upd_lit", "upd_kw",
                                   "const_key", "cond_a"}


def test_every_module_raw_key_survives_publish():
    """THE all-module test: a key any module writes into Listing.raw is in RAW_KEEP, or listed
    as internal (here, or in the two lists above) with a reason."""
    internal = (set(MODULE_KEYS_INTENTIONALLY_INTERNAL) | set(SCRAPER_KEYS_INTENTIONALLY_INTERNAL)
                | INTENTIONALLY_INTERNAL)
    keys = _all_module_raw_keys()
    assert len(keys) > 400, f"only {len(keys)} keys found; the scan broke"
    missing = {k: sorted(v) for k, v in sorted(keys.items()) if k not in RAW_KEEP and k not in internal}
    assert not missing, (
        f"{len(missing)} raw key(s) are dropped at publish with no error:\n"
        + "\n".join(f"    {k!r:<34} written by {', '.join(v[:3])}" for k, v in list(missing.items())[:30])
        + "\n\nAdd each to RAW_KEEP in web_artifact.py, or to MODULE_KEYS_INTENTIONALLY_INTERNAL "
          "above WITH A REASON.")


def test_module_internal_reasons_are_real():
    for key, reason in MODULE_KEYS_INTENTIONALLY_INTERNAL.items():
        assert reason and len(reason) > 20, key
        assert key not in RAW_KEEP, f"{key!r} is both published and listed as internal"


def test_the_keys_the_pipeline_reads_back_are_published():
    """Pins the keys a later step or the next run reads off a reloaded board."""
    from foreclosure_scraper.web_artifact import _slim_raw
    for k in ("parcel_id_alias", "burke_spine", "withdrawn_case_type_other",
              "_land_buildability_checked", "situs_nulled", "lincoln_bulk"):
        assert k in RAW_KEEP, k
    kept = _slim_raw({"gis": {"owner": "X", "absentee": True, "vacant": False, "queried": 1},
                      "parcel_id_alias": {"short": "12345", "long": "1234567890"}})
    assert kept["gis"] == {"owner": "X", "absentee": True, "vacant": False}
    assert kept["parcel_id_alias"]["short"] == "12345"
