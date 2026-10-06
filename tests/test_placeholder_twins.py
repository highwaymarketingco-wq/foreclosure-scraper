"""Placeholder twins: the 2026-10-05 duplicate class (placeholder_twins.py).

The 10/5 VM run kept ~380 parcels twice. Every fixture row below is a REAL pair from that run's
inputs (the source's live scrape on 2026-10-05 vs the published board's prior copy): the fresh row
carries the county's "no house number" sentinel ("0 PATCH DR", "99999 GREEN TREE LN"), the prior
copy carries the numbered situs the parcel cache backfilled, and the house-number guard read
0 vs 499 as two houses.

Covers both callers:
  * board_persist.merge_prior_board()  (future runs): folds the twin, keeps the numbered situs,
    and still refuses every shape that could fuse two properties;
  * placeholder_twins.plan_collapse()/apply_collapse() and scripts/resume_from_checkpoint.py
    (the opt-in clean-up of the 10/5 pre_publish checkpoint): read-only dry run, default off,
    digest-pinned apply, and board_selfcheck's duplicate invariant before/after.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper import checkpoint as C
from foreclosure_scraper import placeholder_twins as PT
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _to_dict

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 5, 12)
FRESH_T = datetime(2026, 10, 5, 2)
PRIOR_T = datetime(2026, 9, 22, 15)

SPBG_VACANT = ("counties_sc.spartanburg_vacant",
               "https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
               "City_Owned_and_Vacant_Properties/FeatureServer/0", ListingType.UNKNOWN, "SC", "Spartanburg")
SPBG_CONDEMNED = ("counties_sc.spartanburg_condemned",
                  "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0",
                  ListingType.UNKNOWN, "SC", "Spartanburg")
BUNCOMBE_DT = ("counties_nc.buncombe_delinquent_tax",
               "https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf",
               ListingType.TAX_LIEN, "NC", "Buncombe")
RUTHERFORD = ("counties_nc.rutherford_tax",
              "https://www.rutherfordcountync.gov/TR-452%20Delinquent%20Bills%20Report%20w%20Parcel%20Id.xlsx",
              ListingType.TAX_LIEN, "NC", "Rutherford")

# (source, parcel_id, fresh 10/5 situs, prior 9/22 published situs) -- real rows.
REAL_PAIRS = [
    (SPBG_VACANT, "714252203123", "0 PATCH DR SPARTANBURG", "499 PATCH DR SPARTANBURG"),
    (SPBG_VACANT, "712249389566", "0 OWENS ST SPARTANBURG", "109 OWENS ST SPARTANBURG"),
    (SPBG_VACANT, "712442037349", "0 ARCHER RD SPARTANBURG", "140 GREER DR SPARTANBURG"),
    (SPBG_CONDEMNED, "7037-51-0954.56", "0 BLACKSTOCK RD PAULINE", "1312 BLACKSTOCK RD PAULINE"),
    (BUNCOMBE_DT, "879362599800000", "99999 PINEY KNOB RD", "560 PINEY KNOB RD"),
    (BUNCOMBE_DT, "973247423600000", "99999 ALPINE WAY", "164 PINEBROOK RD"),
    (RUTHERFORD, "1647690", "0 COBB RD", "212 COBB RD"),
]


def _row(src, parcel, addr, *, when=FRESH_T, **kw) -> Listing:
    source, url, lt, st, county = src
    base = dict(source=source, source_url=url, listing_type=lt, state=st, county=county,
                parcel_id=parcel, street_address=addr, first_seen=when, last_seen=when)
    base.update(kw)
    return Listing(**base)


def _prior(src, parcel, addr, **kw) -> Listing:
    kw.setdefault("raw", {"situs_address_source": "parcel_cache:exact"})
    return _row(src, parcel, addr, when=PRIOR_T, **kw)


def _write_board(docs: Path, rows: list[Listing]) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "listings.json").write_text(json.dumps([li.model_dump(mode="json") for li in rows]))


@pytest.fixture(autouse=True)
def _allow_board(monkeypatch):
    monkeypatch.delenv("FULLRUN_PERSIST_PLACEHOLDER_TWINS", raising=False)


# ------------------------------------------------------------------------------ field rules
@pytest.mark.parametrize("addr,real", [
    ("0 PATCH DR SPARTANBURG", ""), ("00 X RD", ""), ("99999 GREEN TREE LN", ""), ("9999 A ST", ""),
    ("499 PATCH DR", "499"), ("000141 LEVI DR", "141"), ("999 MAIN ST", "999"),
    ("PATCH DR", ""), (None, ""), ("", ""), ("0\xa0MEADOW RD", ""),
])
def test_real_house_no(addr, real):
    assert PT.real_house_no(addr) == real


@pytest.mark.parametrize("pid,ok", [
    ("714252203123", True), ("7037-51-0954.56", True), ("1647690", True),
    ("0000000", False), ("9999999999999", False), ("12345", False), ("ehurst", False),
    ("B123P456", False), ("Book 1234 Page 5", False), (None, False), ("", False),
])
def test_parcel_key_validity(pid, ok):
    assert (PT.parcel_key("SC", "Spartanburg", pid) is not None) is ok


# ------------------------------------------------------------- merge_prior_board (future runs)
@pytest.mark.parametrize("src,parcel,fresh_addr,prior_addr", REAL_PAIRS,
                         ids=[p[1] for p in REAL_PAIRS])
def test_real_pair_folds_into_one_row_and_keeps_the_numbered_situs(tmp_path, src, parcel,
                                                                   fresh_addr, prior_addr):
    _write_board(tmp_path, [_prior(src, parcel, prior_addr)])
    fresh = [_row(src, parcel, fresh_addr, owner_name="CURRENT OWNER")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert len(out) == 1, [li.street_address for li in out]
    li = out[0]
    assert stats["matched"] == 1 and stats["matched_placeholder_twin"] == 1
    assert stats["prior_only_kept"] == 0 and stats["fresh_only"] == 0
    # the address the board was publishing survives (the sentinel would be nulled on publish)
    assert li.street_address == prior_addr
    assert _to_dict(li)["street_address"] == prior_addr
    assert li.owner_name == "CURRENT OWNER"                       # fresh wins
    assert li.first_seen == PRIOR_T                               # earliest sighting kept
    assert li.raw.get("situs_address_source") == "parcel_cache:exact"
    assert "pulled_sale" not in li.raw and li.auction_status is None


def test_strict_only_behaviour_without_the_rule_is_the_10_5_duplicate(tmp_path, monkeypatch):
    """The kill switch reproduces exactly what the 10/5 run did with these rows."""
    monkeypatch.setenv("FULLRUN_PERSIST_PLACEHOLDER_TWINS", "0")
    src, parcel, fresh_addr, prior_addr = REAL_PAIRS[0]
    _write_board(tmp_path, [_prior(src, parcel, prior_addr)])
    out, stats = merge_prior_board([_row(src, parcel, fresh_addr)], docs_dir=tmp_path, now=NOW)
    assert len(out) == 2 and stats["prior_only_kept"] == 1 and stats["matched"] == 0
    published = sorted(str(_to_dict(li)["street_address"]) for li in out)
    assert published == ["499 PATCH DR SPARTANBURG", "None"]      # what selfcheck counted


def test_all_old_copies_with_the_same_number_fold(tmp_path):
    """714252203123 really had two prior copies (7/22 '499 PATCH DR', 9/22 '499 PATCH DR
    SPARTANBURG'): both are the same house and both fold."""
    _write_board(tmp_path, [
        _prior(SPBG_VACANT, "714252203123", "499 PATCH DR",
               raw={"pulled_sale": {"consecutive_misses": 2, "presumed_withdrawn": True}},
               auction_status="presumed_withdrawn"),
        _prior(SPBG_VACANT, "714252203123", "499 PATCH DR SPARTANBURG"),
    ])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "714252203123", "0 PATCH DR SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert len(out) == 1 and stats["matched_placeholder_twin"] == 2
    assert out[0].street_address.startswith("499 PATCH DR")
    assert "pulled_sale" not in out[0].raw and out[0].auction_status is None


def test_two_different_real_numbers_on_one_parcel_are_not_folded(tmp_path):
    """711295579416 (real): prior copies '120 KALMIA ST SPARTANBURG' and '921 LOGAN ST'. The
    parcel names two numbered addresses, so nobody can say which one the sentinel row is."""
    _write_board(tmp_path, [_prior(SPBG_VACANT, "711295579416", "120 KALMIA ST SPARTANBURG"),
                            _prior(SPBG_VACANT, "711295579416", "921 LOGAN ST")])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "711295579416", "0 KALMIA ST SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert len(out) == 3
    assert stats["placeholder_twin_ambiguous"] == 2 and stats["matched_placeholder_twin"] == 0
    assert stats["prior_only_kept"] == 2 and stats["fresh_only"] == 1


def test_real_different_house_numbers_still_blocked(tmp_path):
    """Rutherford 1624499 (real, prior last seen 8/16): '191 DOGWOOD LN' fresh vs '199 DOGWOOD
    LN' prior. Two real numbers: the guard stays in charge."""
    _write_board(tmp_path, [_prior(RUTHERFORD, "1624499", "199 DOGWOOD LN")])
    out, stats = merge_prior_board([_row(RUTHERFORD, "1624499", "191 DOGWOOD LN")],
                                   docs_dir=tmp_path, now=NOW)
    assert len(out) == 2 and stats["matched"] == 0 and stats["matched_placeholder_twin"] == 0


def test_different_source_is_not_folded(tmp_path):
    _write_board(tmp_path, [_prior(SPBG_CONDEMNED, "714252203123", "499 PATCH DR SPARTANBURG")])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "714252203123", "0 PATCH DR SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert len(out) == 2 and stats["matched_placeholder_twin"] == 0


def test_shared_source_via_also_seen_in_is_folded(tmp_path):
    prior = _prior(SPBG_CONDEMNED, "714252203123", "499 PATCH DR SPARTANBURG",
                   raw={"also_seen_in": [{"source": SPBG_VACANT[0], "url": SPBG_VACANT[1]}]})
    _write_board(tmp_path, [prior])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "714252203123", "0 PATCH DR SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert len(out) == 1 and stats["matched_placeholder_twin"] == 1


def test_units_sharing_a_parcel_are_never_folded(tmp_path):
    """A condo building listed under one parcel: unit rows keep their own identity."""
    _write_board(tmp_path, [_prior(SPBG_VACANT, "712204145906", "202 NORTH ST UNIT 4")])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "712204145906", "0 NORTH ST UNIT 2")],
                                   docs_dir=tmp_path, now=NOW)
    assert len(out) == 2 and stats["matched_placeholder_twin"] == 0


def test_parcel_listed_twice_in_the_fresh_scrape_gets_no_relaxed_rule(tmp_path):
    """Two fresh rows under one parcel key (the guard split them, or a master-tract PIN): the
    rule cannot tell which one an old copy belongs to, so it stays out."""
    _write_board(tmp_path, [_prior(SPBG_VACANT, "712204145906", "202 NORTH ST SPARTANBURG")])
    fresh = [_row(SPBG_VACANT, "712204145906", "0 NORTH ST SPARTANBURG"),
             _row(SPBG_VACANT, "712204145906", "300 NORTH ST SPARTANBURG",
                  source_url=SPBG_VACANT[1] + "?b")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert stats["matched_placeholder_twin"] == 0 and len(out) == 3


@pytest.mark.parametrize("pid", ["0000000", "9999999999999", "123456"])
def test_placeholder_or_short_parcel_ids_get_no_relaxed_rule(tmp_path, pid):
    _write_board(tmp_path, [_prior(SPBG_VACANT, pid, "499 PATCH DR SPARTANBURG")])
    out, stats = merge_prior_board([_row(SPBG_VACANT, pid, "0 PATCH DR SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert stats["matched_placeholder_twin"] == 0 and len(out) == 2


@pytest.mark.parametrize("key", PT.RESOLVER_PARCEL_KEYS)
def test_resolver_derived_parcel_gets_no_relaxed_rule(tmp_path, key):
    _write_board(tmp_path, [_prior(SPBG_VACANT, "714252203123", "499 PATCH DR SPARTANBURG",
                                   raw={key: {"source": "x"}})])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "714252203123", "0 PATCH DR SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert stats["matched_placeholder_twin"] == 0 and len(out) == 2


def test_too_many_old_copies_are_left_alone(tmp_path):
    copies = [_prior(SPBG_VACANT, "714252203123", f"499 PATCH DR {s}".strip(),
                     source_url=SPBG_VACANT[1] + f"?{i}")
              for i, s in enumerate(["", "SPARTANBURG", "SPARTANBURG SC", "SC"])]
    _write_board(tmp_path, copies)
    out, stats = merge_prior_board([_row(SPBG_VACANT, "714252203123", "0 PATCH DR SPARTANBURG")],
                                   docs_dir=tmp_path, now=NOW)
    assert stats["matched_placeholder_twin"] == 0 and stats["placeholder_twin_ambiguous"] == 4


def test_terminal_twin_still_drops_when_ambiguous(tmp_path):
    """An ambiguous twin goes down the ordinary aging path, terminal checks included."""
    _write_board(tmp_path, [
        _prior(SPBG_VACANT, "711295579416", "120 KALMIA ST", raw={"sold_confirmed": True}),
        _prior(SPBG_VACANT, "711295579416", "921 LOGAN ST"),
    ])
    out, stats = merge_prior_board([_row(SPBG_VACANT, "711295579416", "0 KALMIA ST")],
                                   docs_dir=tmp_path, now=NOW)
    assert stats["aged_out_terminal"] == 1 and stats["prior_only_kept"] == 1 and len(out) == 2


# ---------------------------------------------------- full-board clean-up (10/5 pre_publish)
def _aging(li: Listing, misses: int = 1) -> Listing:
    li.raw = {**li.raw, "pulled_sale": {"consecutive_misses": misses, "presumed_withdrawn": True,
                                        "first_missed_at": "2026-10-05T02:21:13Z"}}
    if not li.auction_status:
        li.auction_status = "presumed_withdrawn"
    return li


def _checkpoint_like() -> list[Listing]:
    """What the 10/5 pre_publish checkpoint holds for these parcels: the fresh row (live, no
    pulled_sale) beside the aging prior copy, plus shapes that must NOT collapse."""
    rows = []
    for src, parcel, fresh_addr, prior_addr in REAL_PAIRS:
        rows.append(_aging(_prior(src, parcel, prior_addr)))
        rows.append(_row(src, parcel, fresh_addr, raw={"distress_stack": {"tier": "WARM"}}))
    # ambiguous (711295579416, real): two real numbers on the parcel
    rows += [_aging(_prior(SPBG_VACANT, "711295579416", "120 KALMIA ST SPARTANBURG")),
             _aging(_prior(SPBG_VACANT, "711295579416", "921 LOGAN ST")),
             _row(SPBG_VACANT, "711295579416", "0 KALMIA ST SPARTANBURG")]
    # other source's aging copy: not this rule's business
    rows += [_aging(_prior(SPBG_CONDEMNED, "712204052233", "239 WOODLAWN AVE")),
             _row(SPBG_VACANT, "712204052233", "0 WOODLAWN AVE")]
    # two live rows from one source (a dedupe2 miss, not a merge leftover)
    rows += [_row(RUTHERFORD, "1603396", "1798 LAUGHTER RD"),
             _row(RUTHERFORD, "1603396", "0 LAUGHTER RD", source_url=RUTHERFORD[1] + "?2")]
    # an unrelated, ordinary row
    rows.append(_row(RUTHERFORD, "1640084", "55 MAIN ST"))
    return rows


def test_plan_finds_exactly_the_merge_leftovers():
    rows = _checkpoint_like()
    plan = PT.plan_collapse(lambda: rows)
    assert plan.rows_scanned == len(rows)
    assert len(plan.groups) == len(REAL_PAIRS) and plan.rows_dropped == len(REAL_PAIRS)
    assert {g["keep"].source for g in plan.groups} == {p[0][0] for p in REAL_PAIRS}
    for g in plan.groups:
        assert g["keep"].live and not g["keep"].real_hn
        assert all(not v.live and v.real_hn for v in g["drop"])
    assert plan.skipped["ambiguous_house_numbers"] == 1
    assert plan.skipped["no_same_source_twin"] == 1
    assert plan.skipped["live_twin_same_source"] == 1
    s = plan.summary(sample=3)
    assert s["groups"] == len(REAL_PAIRS) and len(s["sample"]) == 3 and s["digest"] == plan.digest()


def test_plan_from_the_checkpoint_file_matches_the_plan_from_listings(tmp_path):
    """The dry run streams the checkpoint FILE as dicts; the apply plans from the loaded
    Listings. Same groups, same digest, or a reviewed digest could never be applied."""
    from foreclosure_scraper.board_parts import iter_gz_rows
    rows = _checkpoint_like()
    p = tmp_path / "board.json.gz"
    import gzip
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump([li.model_dump(mode="json") for li in rows], fh)
    from_file = PT.plan_collapse(lambda: iter_gz_rows(p))
    loaded = [Listing.model_validate(d) for d in iter_gz_rows(p)]
    from_mem = PT.plan_collapse(lambda: loaded)
    assert from_file.digest() == from_mem.digest() == PT.plan_collapse(lambda: rows).digest()
    assert len(from_file.groups) == len(REAL_PAIRS)


def test_apply_collapses_in_place_and_keeps_the_address():
    rows = _checkpoint_like()
    n = len(rows)
    plan = PT.plan_collapse(lambda: rows)
    res = PT.apply_collapse(rows, plan)
    assert res["rows_dropped"] == len(REAL_PAIRS) == res["groups"] and len(rows) == n - len(REAL_PAIRS)
    assert res["addresses_restored"] == len(REAL_PAIRS)
    for src, parcel, _fresh_addr, prior_addr in REAL_PAIRS:
        mine = [li for li in rows if li.parcel_id == parcel and li.source == src[0]]
        assert len(mine) == 1
        li = mine[0]
        assert li.street_address == prior_addr and _to_dict(li)["street_address"] == prior_addr
        assert "pulled_sale" not in li.raw and li.auction_status is None
        # neither row names an owner, so the copy's earlier first_seen is not taken
        # (placeholder_twins.COPY_ALLOWLIST: only when same_owner())
        assert li.first_seen == FRESH_T and li.last_seen == FRESH_T
    # what must not collapse is untouched
    assert sum(1 for li in rows if li.parcel_id == "711295579416") == 3
    assert sum(1 for li in rows if li.parcel_id == "1603396") == 2
    assert PT.plan_collapse(lambda: rows).groups == []          # idempotent


def test_apply_refuses_a_plan_that_no_longer_matches():
    rows = _checkpoint_like()
    plan = PT.plan_collapse(lambda: rows)
    rows.insert(0, _row(RUTHERFORD, "1640085", "1 A ST"))
    before = [li.model_dump(mode="json") for li in rows]
    with pytest.raises(PT.CollapsePlanMismatch):
        PT.apply_collapse(rows, plan)
    assert [li.model_dump(mode="json") for li in rows] == before


def _selfcheck():
    spec = importlib.util.spec_from_file_location("board_selfcheck", REPO / "scripts" / "board_selfcheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_board_selfcheck_duplicate_invariant_before_and_after():
    sc = _selfcheck()

    def dupes(rows):
        inv = {e["name"]: e for e in sc.invariants([_to_dict(li) for li in rows])}
        return inv["no duplicate identifiable properties"]["count"]
    rows = _checkpoint_like()
    before = dupes(rows)
    PT.apply_collapse(rows, PT.plan_collapse(lambda: rows))
    after = dupes(rows)
    # 7 real pairs gone; what is left is the ambiguous parcel (3 rows -> 2 dupes), the
    # cross-source pair and the live pair, which this rule deliberately does not touch.
    assert before - after == len(REAL_PAIRS)
    assert after == 2 + 1 + 1


# --------------------------------------------------------------- resume script integration
def _script():
    spec = importlib.util.spec_from_file_location("resume_from_checkpoint",
                                                  REPO / "scripts" / "resume_from_checkpoint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pre_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHECKPOINT_DIR", tmp_path / "data" / "checkpoint")
    monkeypatch.setattr(C, "ENABLED", True)
    monkeypatch.delenv("RESUME_COLLAPSE_PLACEHOLDER_TWINS", raising=False)
    monkeypatch.delenv("RESUME_SEEN_SINCE", raising=False)
    C.save(_checkpoint_like(), "pre_publish")
    (C.CHECKPOINT_DIR / "resume_state.json").write_text(json.dumps(
        {"summary": {"notes": "x"}, "enrichment_stats": {}, "errors": [], "scoring_failed": None}))
    return tmp_path


def _run(monkeypatch, *argv):
    import contextlib
    from foreclosure_scraper import main as M
    from foreclosure_scraper import web_artifact as wa

    @contextlib.contextmanager
    def fake_lock(*a, **k):
        yield "lock"
    monkeypatch.setattr(wa, "board_lock", fake_lock)
    got = {}

    def fake_publish(st, summary):
        got["rows"], got["summary"] = list(st.enriched), summary
        return M.EXIT_OK
    monkeypatch.setattr(M, "publish_tail", fake_publish)
    monkeypatch.setattr(M, "run_enrich_tail", lambda st: pytest.fail("must not re-run the tail"))
    mod = _script()
    monkeypatch.setattr(mod.os, "chdir", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["resume_from_checkpoint.py", *argv])
    return mod.main(), got


def test_dry_run_prints_the_plan_and_changes_nothing(pre_publish, monkeypatch, capsys, tmp_path):
    board = C.CHECKPOINT_DIR / C.BOARD_FILE
    before = (board.read_bytes(), (C.CHECKPOINT_DIR / C.MANIFEST_FILE).read_text())
    out_file = tmp_path / "plan.json"
    rc, got = _run(monkeypatch, "--collapse-dry-run", "--plan-out", str(out_file), "--sample", "2")
    assert rc == 0 and got == {}                                   # nothing published
    assert (board.read_bytes(), (C.CHECKPOINT_DIR / C.MANIFEST_FILE).read_text()) == before
    text = capsys.readouterr().out
    payload = json.loads(text[text.index("{"):text.index("\nfull plan")])
    assert payload["groups"] == len(REAL_PAIRS) and payload["rows_dropped"] == len(REAL_PAIRS)
    assert payload["by_source"]["counties_sc.spartanburg_vacant"] == 3
    assert len(payload["sample"]) == 2
    assert f"RESUME_COLLAPSE_PLACEHOLDER_TWINS={payload['digest']}" in text
    assert len(json.loads(out_file.read_text())["sample"]) == len(REAL_PAIRS)


def test_publish_only_does_not_collapse_by_default(pre_publish, monkeypatch):
    rc, got = _run(monkeypatch, "--publish-only")
    assert rc == 0 and len(got["rows"]) == len(_checkpoint_like())
    assert "placeholder-twin" not in got["summary"]["notes"]


def test_publish_only_collapses_with_the_reviewed_digest(pre_publish, monkeypatch):
    rows = C.load()
    digest = PT.plan_collapse(lambda: rows).digest()
    monkeypatch.setenv("RESUME_COLLAPSE_PLACEHOLDER_TWINS", digest)
    rc, got = _run(monkeypatch, "--publish-only")
    assert rc == 0 and len(got["rows"]) == len(_checkpoint_like()) - len(REAL_PAIRS)
    assert f"plan {digest}" in got["summary"]["notes"]


def test_publish_only_with_a_stale_digest_publishes_uncollapsed(pre_publish, monkeypatch):
    monkeypatch.setenv("RESUME_COLLAPSE_PLACEHOLDER_TWINS", "0123456789abcdef")
    rc, got = _run(monkeypatch, "--publish-only")
    assert rc == 0 and len(got["rows"]) == len(_checkpoint_like())


def test_cli_flag_applies_too(pre_publish, monkeypatch):
    rc, got = _run(monkeypatch, "--publish-only", "--collapse-placeholder-twins")
    assert rc == 0 and len(got["rows"]) == len(_checkpoint_like()) - len(REAL_PAIRS)


def test_digest_handles_a_copy_with_no_street_address(tmp_path):
    """Found 2026-10-05 replaying the planner over the whole published board: a group whose
    copies include one with no street address made digest() raise (None vs str in sorted())."""
    from foreclosure_scraper.board_parts import iter_gz_rows
    import gzip
    src = SPBG_VACANT
    rows = [_aging(_prior(src, "714252203123", "499 PATCH DR SPARTANBURG")),
            _aging(_prior(src, "714252203123", None)),
            _row(src, "714252203123", "0 PATCH DR SPARTANBURG")]
    plan = PT.plan_collapse(lambda: rows)
    assert len(plan.groups) == 1 and plan.rows_dropped == 2
    p = tmp_path / "board.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump([li.model_dump(mode="json") for li in rows], fh)
    assert PT.plan_collapse(lambda: iter_gz_rows(p)).digest() == plan.digest()
    assert plan.summary()["digest"] == plan.digest()
