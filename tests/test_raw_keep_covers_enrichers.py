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
    # `parcel_from_geo` is provenance for the resolve; `parcel_resolution` IS published.
    "parcel_from_geo",
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
    "source_url": "duplicates the Listing.source_url column; a raw copy shadowing a "
                  "real field invites the two disagreeing",
    "documents": "generic bag already carried by the document_links / doc_ocr keys",
}


def _scraper_raw_keys() -> dict[str, set[str]]:
    """Every key any scraper writes into Listing.raw, mapped to the modules doing it."""
    out: dict[str, set[str]] = {}
    for f in sorted(_SCRAPER_DIR.rglob("*.py")):
        t = f.read_text()
        keys = set(_re.findall(r'raw\s*=\s*\{\s*["\']([A-Za-z0-9_]+)["\']', t))
        keys |= set(_re.findall(r'\braw\[\s*["\']([A-Za-z0-9_]+)["\']\s*\]\s*=', t))
        keys |= set(_re.findall(r'\braw\.setdefault\(\s*["\']([A-Za-z0-9_]+)["\']', t))
        for k in keys:
            out.setdefault(k, set()).add(f.stem)
    return out


def test_the_audit_actually_finds_scraper_keys():
    """Guards the guard. If the regexes stop matching -- someone builds raw a new
    way -- this test would pass vacuously and stop protecting anything."""
    keys = _scraper_raw_keys()
    assert len(keys) > 150, f"only found {len(keys)} scraper raw keys; the scan broke"
    assert "liensnc" in keys


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
