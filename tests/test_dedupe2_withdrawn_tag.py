"""dedupe2 and the withdrawn tag (2026-10-05).

main.run() runs dedupe() a second time after enrichment (dedupe2), over merge_prior_board()'s
output: this run's rows AND the prior rows it aged (raw['pulled_sale'], status
'presumed_withdrawn'), aged rows first since the 10/4 streaming rewrite. Every dedupe() pass keeps
the earlier row as the merge base, so a live row folded into an aged one: the result showed the
aged row's parcel/address/owner, and Listing.merge() carried the tag across (in either order).
board_quality then flagged stale_case and down-ranked a HOT stack.

Every pair below is REAL: the four-source replay (live scrape 2026-10-06 vs the board the 10/5 VM
run merged) produced 23 such rows; all joined two different parcels that dedupe()'s fuzzy pass
matched (a numberless street against a numbered one, or GEORGE vs GEORGIA), and every parcel the
row ended up showing was in that run's scrape.

Covers: the mechanism (as shipped), the fix (dedupe.merge_rows), an end-to-end merge ->
enrichment -> dedupe2 -> board_quality replay, and the opt-in pre-publish repair
(placeholder_twins.plan_collapse(seen_since=...) / repair_reseen / apply_collapse and
scripts/resume_from_checkpoint.py --seen-since / RESUME_SEEN_SINCE, digest-gated).
"""
from __future__ import annotations

import contextlib
import gzip
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from foreclosure_scraper import checkpoint as C
from foreclosure_scraper import dedupe as D
from foreclosure_scraper import placeholder_twins as PT
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
RUN_START = "2026-10-05T01:27:29Z"          # orchestrator.start of the 10/5 VM run
FRESH_T = datetime(2026, 10, 5, 2, 5)
PRIOR_FIRST = datetime(2026, 9, 22, 15, 36)
PRIOR_T = datetime(2026, 10, 2, 15, 52)     # the newest last_seen any aged row had
TODAY = date(2026, 10, 6)

BUNCOMBE = ("counties_nc.buncombe_delinquent_tax",
            "https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf",
            ListingType.TAX_LIEN, "NC", "Buncombe")
SPBG_VACANT = ("counties_sc.spartanburg_vacant",
               "https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
               "City_Owned_and_Vacant_Properties/FeatureServer/0", ListingType.UNKNOWN, "SC", "Spartanburg")

# (source, AGED prior row: parcel, address, owner), (LIVE row: parcel, address, owner) -- real.
REAL_FUSIONS = [
    (BUNCOMBE, ("072005966600000", "328 LOOKOUT RD", "HINSON-BAROODY REVOCABLE TRUSTE"),
     ("072025785900000", "LOOKOUT RD", "BLANTON, LEENETA")),
    (BUNCOMBE, ("970342539500000", "84 OLD TURKEY CREEK RD", "BRALEY, NOAH EVERETT"),
     ("878059826700000", "S TURKEY CREEK RD", "BOZA, ELLEN C")),
    (SPBG_VACANT, ("712249981468", "128 GEORGIA ST SPARTANBURG", "ANTHONY L MATHIS REV TRUST"),
     ("712249498152", "128 GEORGE ST SPARTANBURG", "B I G BARBRY INVESTING GROUP LLC")),
]
IDS = [f[1][1] for f in REAL_FUSIONS]

HOT_STACK = {"tier": "HOT", "stack": 3, "score": 90.0, "categories": ["TAX", "LEGAL", "PROPERTY"],
             "signals": ["tax_delinquent"]}


def _row(src, parcel, addr, owner, *, first, last, **kw) -> Listing:
    source, url, lt, st, county = src
    return Listing(source=source, source_url=url, listing_type=lt, state=st, county=county,
                   parcel_id=parcel, street_address=addr, owner_name=owner, first_seen=first,
                   last_seen=last, **kw)


def _live(src, ident, **kw) -> Listing:
    raw = {src[0].rsplit(".", 1)[-1]: {"pin": ident[0], "owner": ident[2]}, **kw.pop("raw", {})}
    return _row(src, *ident, first=FRESH_T, last=FRESH_T, raw=raw, **kw)


def _aged(src, ident, **kw) -> Listing:
    """What merge_prior_board()._age() makes of a prior row the scrape did not match, carrying
    what the prior board already had on it (stale_case and a down-ranked stack from last run)."""
    raw = {"pulled_sale": {"first_missed_at": "2026-10-05T02:21:13Z", "consecutive_misses": 1,
                           "presumed_withdrawn": True, "last_seen_source": src[0],
                           "last_seen_sale_date": None},
           "stale_case": True, "vision": {"condition": "fair"},
           "distress_stack": {**HOT_STACK, "tier": "WARM", "downranked_stale": True,
                              "downranked_reason": "pulled_sale_presumed_withdrawn"},
           **kw.pop("raw", {})}
    kw.setdefault("auction_status", "presumed_withdrawn")
    return _row(src, *ident, first=PRIOR_FIRST, last=PRIOR_T, raw=raw, **kw)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RESUME_COLLAPSE_PLACEHOLDER_TWINS", "RESUME_SEEN_SINCE",
              "FULLRUN_PERSIST_PLACEHOLDER_TWINS"):
        monkeypatch.delenv(k, raising=False)


@contextlib.contextmanager
def _old_matching():
    """dedupe()'s matching before the 2026-10-06 identity rule (test_dedupe_identity_evidence.py):
    the house-number guard alone (_house_no_of on both rows; a sentinel '0' is a number, a parcel
    is no evidence), and a merged row keeps its base row's own address. Emulated by swapping the
    identity hooks, which is exact for the two- and three-row fixtures here."""
    saved = (D.identity, D.identity_conflict, D._union, D._merge)
    D.identity = lambda li: D.Identity(D._house_no_of(li.street_address), None)
    D.identity_conflict = lambda x, y, evidence=None: (
        "house_number" if x.hn and y.hn and x.hn != y.hn else None)
    D._union = lambda x, y: x
    D._merge = lambda a, b: D.merge_rows(a, b)
    try:
        yield
    finally:
        D.identity, D.identity_conflict, D._union, D._merge = saved


def _shipped_dedupe(rows):
    """dedupe() exactly as it ran on 10/5: the old matching, and every merge plain
    Listing.merge(), earlier row first."""
    real = D.merge_rows
    D.merge_rows = lambda a, b: a.merge(b)
    try:
        with _old_matching():
            return D.dedupe(rows)
    finally:
        D.merge_rows = real


# --------------------------------------------------------------------------------- mechanism
@pytest.mark.parametrize("src,aged,live", REAL_FUSIONS, ids=IDS)
def test_as_shipped_the_live_row_takes_the_aged_identity_and_the_tag(src, aged, live):
    out = _shipped_dedupe([_aged(src, aged), _live(src, live)])     # aged first, as on 10/5
    assert len(out) == 1, "dedupe2 matches these two rows (fuzzy pass, one side numberless)"
    li = out[0]
    assert (li.parcel_id, li.street_address, li.owner_name) == aged   # the aged row's fields won
    assert li.raw["pulled_sale"]["presumed_withdrawn"] is True
    assert li.auction_status == "presumed_withdrawn" and li.raw["stale_case"] is True
    assert li.last_seen == FRESH_T                                    # the only trace of the live row


@pytest.mark.parametrize("src,aged,live", REAL_FUSIONS, ids=IDS)
def test_as_shipped_the_tag_survives_even_live_first(src, aged, live):
    """Order decides whose fields win; the tag rides Listing.merge()'s raw deep-merge and status
    backfill either way, which is why fixing the order alone would not have been enough."""
    li = _shipped_dedupe([_live(src, live), _aged(src, aged)])[0]
    assert (li.parcel_id, li.street_address, li.owner_name) == live
    assert li.raw.get("pulled_sale") and li.auction_status == "presumed_withdrawn"


# ---------------------------------------------------------------------------------- the fix
@pytest.mark.parametrize("aged_first", [True, False], ids=["aged_first", "live_first"])
@pytest.mark.parametrize("src,aged,live", REAL_FUSIONS, ids=IDS)
def test_dedupe_no_longer_matches_these_pairs(src, aged, live, aged_first):
    """2026-10-06: every one of these pairs is two DIFFERENT valid parcels (and one side has no
    real house number), so dedupe()'s identity rule keeps them apart: the live row is untouched
    and untagged, and the aged neighbour stays its own (aged) row."""
    rows = [_aged(src, aged), _live(src, live)]
    out = D.dedupe(rows if aged_first else rows[::-1])
    assert len(out) == 2
    by_parcel = {li.parcel_id: li for li in out}
    li = by_parcel[live[0]]
    assert (li.parcel_id, li.street_address, li.owner_name) == live
    assert "pulled_sale" not in li.raw and "stale_case" not in li.raw and li.auction_status is None
    assert li.last_seen == FRESH_T and li.first_seen == FRESH_T
    old = by_parcel[aged[0]]
    assert (old.street_address, old.owner_name) == aged[1:] and old.raw["pulled_sale"]


@pytest.mark.parametrize("aged_first", [True, False], ids=["aged_first", "live_first"])
@pytest.mark.parametrize("src,aged,live", REAL_FUSIONS, ids=IDS)
def test_merge_rows_keeps_the_live_row_and_drops_the_tag(src, aged, live, aged_first):
    """Item 64's merge_rows() fix on its own: had the old matching joined these rows, the live row
    is the base and the result is not presumed withdrawn."""
    rows = [_aged(src, aged), _live(src, live)]
    with _old_matching():
        out = D.dedupe(rows if aged_first else rows[::-1])
    assert len(out) == 1                                     # the old matching joins them
    li = out[0]
    assert (li.parcel_id, li.street_address, li.owner_name) == live
    assert li.source_url == src[1]
    assert "pulled_sale" not in li.raw and "stale_case" not in li.raw
    assert li.auction_status is None
    assert li.first_seen == PRIOR_FIRST and li.last_seen == FRESH_T
    assert li.raw["vision"] == {"condition": "fair"}         # aged enrichment still backfills


def test_same_parcel_old_copy_folds_into_the_live_row():
    """The case the merge was meant for: the live row's key only lines up with its own aged copy
    after enrichment filled the parcel (pass 1, parcel key)."""
    ident = ("963904572600000", "193 BRICKYARD RD", "HOSTABLE LLC")
    aged = _aged(BUNCOMBE, ident, raw={"grade": {"overall_score": 61}})
    live = _live(BUNCOMBE, ident, auction_status="active")
    li = D.dedupe([aged, live])[0]
    assert li.auction_status == "active" and "pulled_sale" not in li.raw
    assert li.raw["grade"] == {"overall_score": 61}


def test_two_aged_rows_stay_aged_and_two_live_rows_merge_as_before():
    a1 = _aged(BUNCOMBE, ("963904572600000", "193 BRICKYARD RD", "HOSTABLE LLC"))
    a2 = _aged(BUNCOMBE, ("963904572600000", "193 BRICKYARD RD", "OTHER"))
    li = D.dedupe([a1, a2])[0]
    assert li.raw["pulled_sale"] and li.auction_status == "presumed_withdrawn"
    assert li.owner_name == "HOSTABLE LLC"
    l1 = _live(BUNCOMBE, ("963904572600000", "193 BRICKYARD RD", "FIRST"))
    l2 = _live(BUNCOMBE, ("963904572600000", "193 BRICKYARD RD", "SECOND"))
    assert D.dedupe([l1, l2])[0].owner_name == "FIRST"            # earlier row is still the base
    assert D.merge_rows(l1, l2).model_dump() == l1.merge(l2).model_dump()


def test_the_live_rows_own_stale_case_and_status_are_kept():
    ident = ("963904572600000", "193 BRICKYARD RD", "HOSTABLE LLC")
    live = _live(BUNCOMBE, ident, auction_status="active", raw={"stale_case": True})
    li = D.merge_rows(_aged(BUNCOMBE, ident), live)
    assert li.raw["stale_case"] is True and li.auction_status == "active"


def test_a_group_of_aged_live_aged_takes_the_live_row_as_base():
    ident = ("963904572600000", "193 BRICKYARD RD", "HOSTABLE LLC")
    rows = [_aged(BUNCOMBE, ident[:2] + ("OLD 1",)), _live(BUNCOMBE, ident),
            _aged(BUNCOMBE, ident[:2] + ("OLD 2",))]
    out = D.dedupe(rows)
    assert len(out) == 1 and out[0].owner_name == "HOSTABLE LLC"
    assert "pulled_sale" not in out[0].raw


def test_merge_then_enrichment_then_dedupe2_then_board_quality(tmp_path):
    """End to end on the shapes of a real run. The live court row cannot match its prior copy in
    merge_prior_board() (no parcel, no address yet), so the prior copy is aged; enrichment then
    fills the parcel and address; dedupe2 meets the two. As shipped the lead comes out presumed
    withdrawn and board_quality takes it off HOT; fixed, it stays HOT and live."""
    ident = ("962655612200000", "171 STRADLEY MOUNTAIN RD", "STRADLEY, JO")
    prior = _row(BUNCOMBE, *ident, first=PRIOR_FIRST, last=PRIOR_T, raw={"vision": {"x": 1}})
    (tmp_path / "listings.json").write_text(json.dumps([prior.model_dump(mode="json")]))
    court = Listing(source="counties_nc.nc_ecourts_lis_pendens", source_url="https://ec/26SP1",
                    state="NC", county="Buncombe", case_number="26SP001",
                    first_seen=FRESH_T, last_seen=FRESH_T)
    merged, st = merge_prior_board([court], docs_dir=tmp_path, now=datetime(2026, 10, 5, 2, 21))
    assert st["prior_only_kept"] == 1 and st["fresh_only"] == 1
    assert [bool(li.raw.get("pulled_sale")) for li in merged] == [True, False]    # aged first
    merged[1].parcel_id, merged[1].street_address = ident[0], ident[1]          # enrichment

    def board(rows):
        for li in rows:
            li.raw["distress_stack"] = dict(HOT_STACK)                         # the scorer
        enrich_board_quality(rows, today=TODAY)
        return rows

    shipped = board(_shipped_dedupe([li.model_copy(deep=True) for li in merged]))
    assert len(shipped) == 1 and shipped[0].raw["stale_case"]
    assert shipped[0].raw["distress_stack"]["tier"] == "WARM"
    assert shipped[0].source.endswith("buncombe_delinquent_tax")       # the aged row's source

    fixed = board(D.dedupe([li.model_copy(deep=True) for li in merged]))
    assert len(fixed) == 1 and fixed[0].source == "counties_nc.nc_ecourts_lis_pendens"
    assert fixed[0].raw["distress_stack"]["tier"] == "HOT" and "stale_case" not in fixed[0].raw
    assert fixed[0].raw["vision"] == {"x": 1}                          # prior enrichment carried


# ------------------------------------------------------- the 10/5 pre_publish clean-up (opt-in)
def _scored(li: Listing, tier="HOT", intent=100) -> Listing:
    li.raw = {**li.raw, "grade": {"overall_score": 100}}
    if tier == "WARM_BY_TAG":
        li.raw["distress_stack"] = {**HOT_STACK, "tier": "WARM", "downranked_stale": True,
                                    "downranked_reason": "pulled_sale_presumed_withdrawn"}
        li.raw["intent_score"], li.raw["intent_band"] = 69, "warm"
    else:
        li.raw["distress_stack"] = {**HOT_STACK, "tier": tier}
        li.raw["intent_score"], li.raw["intent_band"] = intent, "hot"
    return li


def _checkpoint_like() -> list[Listing]:
    """What the 10/5 pre_publish checkpoint holds: as-shipped dedupe2 output (the three real
    fusions, scored and demoted by the tag), a genuinely aged row, a live row, and an aged
    carryover row (whose last_seen says nothing about this run)."""
    rows = []
    for src, aged, live in REAL_FUSIONS:
        rows.append(_scored(_shipped_dedupe([_aged(src, aged), _live(src, live)])[0],
                            tier="WARM_BY_TAG"))
    rows.append(_scored(_aged(BUNCOMBE, ("969932107600000", "575 OLD US 70 HWY", "GONE LLC")),
                        tier="WARM_BY_TAG"))
    rows.append(_scored(_live(BUNCOMBE, ("973428476700000", "934 JUPITER RD", "LIVE LLC"))))
    rows.append(_aged(BUNCOMBE, ("060910321200000", "224 DOC SNYDER DR", "CARRIED"),
                      raw={"carryover": {"stale": True}}))
    return rows


def _write(rows, p: Path) -> Path:
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump([li.model_dump(mode="json") for li in rows], fh)
    return p


def test_plan_finds_exactly_the_rows_this_run_saw(tmp_path):
    from foreclosure_scraper.board_parts import iter_gz_rows
    rows = _checkpoint_like()
    plan = PT.plan_collapse(lambda: rows, seen_since=RUN_START)
    assert sorted(v.idx for v in plan.reseen) == [0, 1, 2]
    assert all(v.status == "presumed_withdrawn" and v.hot_demoted for v in plan.reseen)
    ev = plan.evidence
    assert ev["newest_tagged_last_seen_before_cutoff"] == PRIOR_T.isoformat()
    assert ev["oldest_tagged_last_seen_at_or_after_cutoff"] == FRESH_T.isoformat()
    # The carryover count is gone (raw['carryover'] is sticky across runs, so it measured nothing
    # about this run); the newest days of untouched tagged rows show where the cutoff sits.
    assert "tagged_carryover_rows_before_cutoff_not_judged" not in ev
    assert ev["tagged_rows_before_cutoff_newest_days"] == {PRIOR_T.date().isoformat(): 2}
    assert ev["stale_case_only_rows_at_or_after_cutoff"] == 0
    p = _write(rows, tmp_path / "board.json.gz")
    from_file = PT.plan_collapse(lambda: iter_gz_rows(p), seen_since=RUN_START)
    assert from_file.digest() == plan.digest()                    # dry run == apply
    s = plan.summary(sample=2)["reseen"]
    assert s["rows_repaired"] == 3 and s["hot_demoted_by_tag"] == 3 and len(s["sample"]) == 2
    assert s["by_source"] == {BUNCOMBE[0]: 2, SPBG_VACANT[0]: 1}


def test_without_seen_since_the_plan_and_digest_are_the_twins_only_ones():
    rows = _checkpoint_like()
    off = PT.plan_collapse(lambda: rows)
    assert off.seen_since is None and off.reseen == [] and "reseen" not in off.summary()
    assert off.digest() == PT.CollapsePlan(groups=off.groups).digest()
    assert PT.plan_collapse(lambda: rows, seen_since=RUN_START).digest() != off.digest()
    # a different run start is a different plan
    assert (PT.plan_collapse(lambda: rows, seen_since="2026-10-05T01:00:00Z").digest()
            != PT.plan_collapse(lambda: rows, seen_since=RUN_START).digest())
    with pytest.raises(ValueError):
        PT.plan_collapse(lambda: rows, seen_since="yesterday")


def test_apply_repairs_the_tag_restores_hot_and_recomputes_intent():
    rows = _checkpoint_like()
    plan = PT.plan_collapse(lambda: rows, seen_since=RUN_START)
    res = PT.apply_collapse(rows, plan, today=TODAY)
    assert res["reseen_repaired"] == 3 and res["reseen"]["hot_restored"] == 3
    for li in rows[:3]:
        assert "pulled_sale" not in li.raw and "stale_case" not in li.raw
        assert li.auction_status is None
        ds = li.raw["distress_stack"]
        assert ds["tier"] == "HOT" and "downranked_stale" not in ds and "downranked_reason" not in ds
        assert li.raw["intent_score"] == 100 and li.raw["intent_band"] == "hot"
    # the genuinely aged row, the live row and the carryover row are untouched
    assert rows[3].raw["pulled_sale"] and rows[3].raw["distress_stack"]["tier"] == "WARM"
    assert rows[4].raw["intent_score"] == 100 and rows[5].raw["pulled_sale"]


def test_repair_still_downranks_a_sale_date_that_has_passed():
    li = _checkpoint_like()[0]
    li.raw.update(sale_date_passed=True, sale_date_passed_days=40)
    li.sale_date = datetime(2026, 8, 27)
    li.listing_type = ListingType.FORECLOSURE_SALE
    stats = PT.repair_reseen([li], today=TODAY)
    assert stats["hot_restored"] == 1 and stats["hot_downranked"] == 1
    assert li.raw["distress_stack"]["downranked_reason"] == "sale_date_passed"
    assert "stale_case" not in li.raw and li.raw["intent_score"] == 100   # intent runs first


def test_apply_refuses_when_a_reseen_row_changed():
    rows = _checkpoint_like()
    plan = PT.plan_collapse(lambda: rows, seen_since=RUN_START)
    rows[1].raw.pop("pulled_sale")
    before = [li.model_dump() for li in rows]
    with pytest.raises(PT.CollapsePlanMismatch):
        PT.apply_collapse(rows, plan, today=TODAY)
    assert [li.model_dump() for li in rows] == before


def test_a_repaired_placeholder_row_counts_as_live_for_the_twin_rule():
    """dedupe2 also tagged live placeholder rows ('0 PATCH DR'); the twin rule starts from a LIVE
    placeholder, so without the repair such a parcel is never considered, with it it collapses."""
    src = SPBG_VACANT
    tagged_live = _shipped_dedupe([
        _aged(src, ("712249389999", "OWENS ST SPARTANBURG", "X")),
        _live(src, ("714252203123", "0 PATCH DR SPARTANBURG", "OWNER"))])
    assert len(tagged_live) == 2                       # these two do not match each other
    live = tagged_live[1]
    live.raw["pulled_sale"] = {"presumed_withdrawn": True, "consecutive_misses": 1}  # as dedupe2 left it
    live.auction_status = "presumed_withdrawn"
    # The real 714252203123 copy got its number from the county record (parcel cache); only such
    # a number may replace the sentinel (placeholder_twins' ADDRESS RULE).
    twin = _aged(src, ("714252203123", "499 PATCH DR SPARTANBURG", "OWNER"),
                 raw={"situs_address_source": "parcel_cache:exact"})
    rows = [twin, live]
    off = PT.plan_collapse(lambda: rows)
    assert off.groups == [] and not off.skipped
    on = PT.plan_collapse(lambda: rows, seen_since=RUN_START)
    assert len(on.groups) == 1 and [v.idx for v in on.reseen] == [1]
    PT.apply_collapse(rows, on, today=TODAY)
    assert len(rows) == 1 and rows[0].street_address == "499 PATCH DR SPARTANBURG"
    assert "pulled_sale" not in rows[0].raw and rows[0].auction_status is None


def test_twin_collapse_keeps_the_live_rows_own_scores_and_drops_the_copys_stale_case():
    src = SPBG_VACANT
    keep = _scored(_live(src, ("714252203123", "0 PATCH DR SPARTANBURG", "OWNER")), intent=88)
    copy_ = _scored(_aged(src, ("714252203123", "499 PATCH DR SPARTANBURG", "OWNER")),
                    tier="WARM_BY_TAG")
    rows = [copy_, keep]
    plan = PT.plan_collapse(lambda: rows)
    PT.apply_collapse(rows, plan, today=TODAY)
    (li,) = rows
    assert li.raw["distress_stack"]["tier"] == "HOT" and "downranked_stale" not in li.raw["distress_stack"]
    assert li.raw["intent_score"] == 88 and "stale_case" not in li.raw
    assert "vision" not in li.raw                     # the copy's vision is not the live row's


# ------------------------------------------------------------------ resume script (VM entry)
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
    C.save(_checkpoint_like(), "pre_publish")
    (C.CHECKPOINT_DIR / "resume_state.json").write_text(json.dumps(
        {"summary": {"notes": "x"}, "enrichment_stats": {}, "errors": [], "scoring_failed": None}))
    return tmp_path


def _run(monkeypatch, *argv):
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


def _tagged(rows):
    return sum(1 for li in rows if (li.raw or {}).get("pulled_sale"))


def test_dry_run_with_seen_since_prints_both_parts_and_changes_nothing(pre_publish, monkeypatch,
                                                                       capsys, tmp_path):
    board = C.CHECKPOINT_DIR / C.BOARD_FILE
    before = board.read_bytes()
    out_file = tmp_path / "plan.json"
    rc, got = _run(monkeypatch, "--collapse-dry-run", "--seen-since", RUN_START,
                   "--plan-out", str(out_file))
    assert rc == 0 and got == {} and board.read_bytes() == before
    text = capsys.readouterr().out
    payload = json.loads(text[text.index("{"):text.index("\nfull plan")])
    assert payload["reseen"]["rows_repaired"] == 3
    assert payload["reseen"]["seen_since"] == "2026-10-05T01:27:29"
    assert (f"RESUME_COLLAPSE_PLACEHOLDER_TWINS={payload['digest']} "
            f"RESUME_SEEN_SINCE={RUN_START}") in text
    assert len(json.loads(out_file.read_text())["reseen"]["sample"]) == 3


def test_dry_run_rejects_a_bad_timestamp(pre_publish, monkeypatch):
    rc, _ = _run(monkeypatch, "--collapse-dry-run", "--seen-since", "last tuesday")
    assert rc == 1


def test_publish_only_repairs_with_the_reviewed_digest_and_run_start(pre_publish, monkeypatch):
    rows = C.load()
    digest = PT.plan_collapse(lambda: rows, seen_since=RUN_START).digest()
    monkeypatch.setenv("RESUME_COLLAPSE_PLACEHOLDER_TWINS", digest)
    monkeypatch.setenv("RESUME_SEEN_SINCE", RUN_START)
    rc, got = _run(monkeypatch, "--publish-only")
    assert rc == 0 and len(got["rows"]) == len(rows)
    assert _tagged(got["rows"]) == _tagged(rows) - 3
    assert "removed the presumed-withdrawn tag from 3 rows" in got["summary"]["notes"]


@pytest.mark.parametrize("seen", [None, "2026-10-04T00:00:00Z"], ids=["no_run_start", "other_start"])
def test_publish_only_without_the_reviewed_run_start_changes_nothing(pre_publish, monkeypatch, seen):
    rows = C.load()
    digest = PT.plan_collapse(lambda: rows, seen_since=RUN_START).digest()
    monkeypatch.setenv("RESUME_COLLAPSE_PLACEHOLDER_TWINS", digest)
    if seen:
        monkeypatch.setenv("RESUME_SEEN_SINCE", seen)
    rc, got = _run(monkeypatch, "--publish-only")
    assert rc == 0 and _tagged(got["rows"]) == _tagged(rows)


def test_publish_only_is_unchanged_by_default(pre_publish, monkeypatch):
    rows = C.load()
    rc, got = _run(monkeypatch, "--publish-only")
    assert rc == 0 and [li.model_dump() for li in got["rows"]] == [li.model_dump() for li in rows]
