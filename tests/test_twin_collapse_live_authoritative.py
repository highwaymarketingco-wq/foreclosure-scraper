"""The placeholder-twin collapse publishes the LIVE row (2026-10-06 dress rehearsal: NO-GO).

The full dress rehearsal of the 10/5 publish on the VM found that apply_collapse() filled
everything the live row lacked from its aged copy, and in 208 of 325 groups that copy names
another owner: the published rows carried other people's outreach letters, skip-trace, phones,
divorce, deed chain, owner cluster and CRM blocks, and 9 rows carried a max bid / MAO / equity
the live row had withheld on a contradicted ARV (three board_selfcheck money rules broken). With
the collapse fixed, write_artifact()'s cross-run sidecar backfill would have done the same
through the detail file: the prior board's row for the parcel IS the aged copy.

Fixture: tests/fixtures/placeholder_twins_10_5_groups.json.gz, 14 REAL groups (28 rows, the
live row and its aged copy, in checkpoint order) read from the VM's 10/5 pre_publish checkpoint
on 2026-10-06; phone numbers replaced by (555) 010-NNNN, nothing else changed:
  * the 9 groups whose published money broke the selfcheck (SC|spartanburg|713272200834: live
    ARV $300 flagged arv_land_sqft_mismatch, copy ARV $271,600 and a $121,200 max bid;
    NC|buncombe|0605597303, ...);
  * NC|rutherford|1616705: live FOSTER, TAMMIE; the copy's letter is "Dear Francis," to WALSH,
    FRANCIS ROBERT;
  * 9 groups whose copy names HALLIDAY Q STANFORD IV (one name on ~180 parcels' copies), two
    with skip-trace phones (713257724562, 711450945969);
  * SC|spartanburg|714252203123 (live BURNETT, copy NOWAK) and NC|buncombe|8793625998 (same
    owner DONELLY): copies whose numbered address IS the county situs (parcel_cache:exact).
"""
from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import re
from pathlib import Path

import pytest

from foreclosure_scraper import main as M
from foreclosure_scraper import placeholder_twins as PT
from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.dedupe import drop_withdrawn_tags
from foreclosure_scraper.models import Listing, _deep_merge_dict
from foreclosure_scraper.web_artifact import LAZY_DETAIL_KEYS, _to_dict

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures" / "placeholder_twins_10_5_groups.json.gz"
SEEN = "2026-10-04T19:34:31Z"          # the 10/5 publish's RESUME_SEEN_SINCE
MONEY_GROUPS = {"NC|buncombe|0605597303", "SC|spartanburg|710282175854",
                "SC|spartanburg|713272200834", "SC|spartanburg|714220577298",
                "SC|spartanburg|712495972398", "SC|spartanburg|711362129228",
                "SC|spartanburg|712300652169", "SC|spartanburg|710277400186",
                "SC|spartanburg|710450435692"}
MONEY_RULES = ("no max_bid_70 on a contradicted ARV", "no roi_pct on a contradicted ARV",
               "no estimated_profit on a contradicted ARV", "no wholesale_mao on a contradicted ARV",
               "no deal verdict on a contradicted ARV", "no equity on a contradicted ARV",
               "no max bid on an ARV over $2M", "every ARV over $2M carries a flag")


def _records() -> list[dict]:
    return json.loads(gzip.decompress(FIX.read_bytes()).decode("utf-8"))


def _rows() -> list[Listing]:
    return [Listing.model_validate(r["row"]) for r in _records()]


def _by_key() -> dict:
    """parcel key -> {"keep": Listing, "drop": [Listing]} straight from the fixture."""
    out: dict = {}
    for r in _records():
        g = out.setdefault(r["key"], {"keep": None, "drop": []})
        li = Listing.model_validate(r["row"])
        if r["role"] == "keep":
            g["keep"] = li
        else:
            g["drop"].append(li)
    return out


def _plan(rows):
    return PT.plan_collapse(lambda: rows, seen_since=SEEN)


def _published(li: Listing) -> tuple[dict, dict]:
    """(listings.json record, listings_detail.json entry) exactly as write_artifact splits them."""
    rec = json.loads(json.dumps(_to_dict(li.model_copy(deep=True)), default=str))
    det = {k: rec["raw"].pop(k) for k in LAZY_DETAIL_KEYS if k in rec["raw"]}
    return rec, det


def _text(*objs) -> str:
    return json.dumps(objs, default=str).upper()


def _selfcheck():
    spec = importlib.util.spec_from_file_location("board_selfcheck", REPO / "scripts" / "board_selfcheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _money(rows) -> dict:
    inv = {e["name"]: e["count"] for e in _selfcheck().invariants([_published(li)[0] for li in rows])}
    return {k: inv[k] for k in MONEY_RULES}


def _as_shipped(listings: list[Listing], plan) -> None:
    """apply_collapse()'s merge as it shipped in c3cba6ed (the code the rehearsal ran): fold()
    every copy in, lay the live raw back on top (the live row wins only where BOTH rows have a
    value), drop the tags, restore the live scores. Kept here to prove the fixture reproduces
    the defect."""
    for g in plan.groups:
        merged = listings[g["keep"].idx]
        own = merged.raw
        keep_stale = bool(own.get("stale_case"))
        scored = {k: copy.deepcopy(own[k]) for k in ("distress_stack", "signal_stack",
                                                      "intent_score", "intent_band") if k in own}
        own_raw = copy.deepcopy(own)
        for v in g["drop"]:
            merged = PT.fold(merged, listings[v.idx])
        merged.raw = _deep_merge_dict(merged.raw, own_raw)
        drop_withdrawn_tags(merged, keep_stale_case=keep_stale)
        merged.raw.update(scored)
        listings[g["keep"].idx] = merged
    dropped = {v.idx for g in plan.groups for v in g["drop"]}
    listings[:] = [li for i, li in enumerate(listings) if i not in dropped]


def _collapsed():
    rows = _rows()
    plan = _plan(rows)
    kept: dict = {}
    res = PT.apply_collapse(rows, plan, kept_out=kept)
    return rows, plan, res, kept


def _diff_paths(a: dict, b: dict, pre: str = "") -> set:
    out = set()
    for k in set(a) | set(b):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            out |= _diff_paths(va, vb, f"{pre}{k}.")
        elif va != vb or (k in a) != (k in b):
            out.add(pre + k)
    return out


def _other_party_tokens(live: Listing, copy_: Listing) -> set:
    """Identity tokens of every person the COPY's personal blocks name (owner, letter addressee,
    skip-trace / outreach / mailing names, phone match) that appear nowhere on the live row."""
    raw = copy_.raw or {}
    names = [copy_.owner_name]
    for blk, field in (("outreach", "owner"), ("skip_trace", "owner_name"), ("owner_mailing", "name"),
                       ("owner_mailing", "owner"), ("gis", "owner"), ("owner_phone", "match")):
        b = raw.get(blk)
        if isinstance(b, dict) and isinstance(b.get(field), str):
            names.append(b[field])
    letter = (raw.get("outreach") or {}).get("letter") if isinstance(raw.get("outreach"), dict) else None
    if isinstance(letter, str):
        m = re.match(r"Dear ([^,\n]+),", letter)
        if m:
            names.append(m.group(1))
    live_text = _text(live.model_dump(mode="json"))
    toks = set()
    for n in names:
        toks |= {t for t in PT.owner_tokens(n) if len(t) >= 4 and t not in live_text}
    return toks


# ----------------------------------------------------------------------------------- the plan
def test_the_fixture_is_the_real_plan_shape():
    rows = _rows()
    plan = _plan(rows)
    groups = _by_key()
    assert len(plan.groups) == len(groups) == 14 and plan.rows_dropped == 14
    assert {g["key"] for g in plan.groups} == set(groups)
    assert plan.reseen == []          # none of these 28 rows is a reseen row (as on the VM)
    differs = [k for k, g in groups.items() if not PT.same_owner(g["keep"], g["drop"][0])]
    assert len(differs) == 11         # all but 0605597303 (BORGES), 710282175854, 8793625998


def test_the_fixture_reproduces_the_rehearsal_failure_on_the_shipped_merge():
    """Guard the guard: the c3cba6ed merge over these real rows breaks the three money rules
    and publishes the other owners' data, exactly as the rehearsal measured."""
    rows = _rows()
    _as_shipped(rows, _plan(rows))
    money = _money(rows)
    assert money["no max_bid_70 on a contradicted ARV"] == 9
    assert money["no wholesale_mao on a contradicted ARV"] == 4
    assert money["no equity on a contradicted ARV"] == 9
    by_parcel = {li.parcel_id: li for li in rows}
    rec, det = _published(by_parcel["713272200834"])
    assert rec["raw"]["calc"]["max_bid_70"] == 121200.0 and "HALLIDAY" in _text(rec, det)
    rec, _ = _published(by_parcel["1616705"])
    assert rec["raw"]["outreach"]["letter"].startswith("Dear Francis,")


# ------------------------------------------------------------------------------- the fix
def test_the_published_row_is_the_live_row_plus_only_the_allowlist():
    groups = _by_key()
    rows, plan, res, _ = _collapsed()
    assert res["groups"] == 14 and res["rows_dropped"] == 14 and len(rows) == 14
    by_key = {PT.parcel_key(li.state, li.county, li.parcel_id): li for li in rows}
    for key, g in groups.items():
        live, out = g["keep"], by_key[key]
        diff = _diff_paths(live.model_dump(mode="json"), out.model_dump(mode="json"))
        allowed = set()
        if (PT.county_situs(g["drop"][0]) and PT.real_house_no(g["drop"][0].street_address)
                and not PT.real_house_no(live.street_address)):
            allowed |= {"street_address", "raw.situs_address_source"}
        if PT.same_owner(live, g["drop"][0]) and g["drop"][0].first_seen < live.first_seen:
            allowed.add("first_seen")
        assert diff == allowed, (key, sorted(diff))
    assert res["addresses_restored"] == 4 and res["first_seen_taken"] == 3
    assert res["groups_copy_owner_differs"] == 11


def test_the_money_rules_are_zero_and_the_flagged_arv_keeps_its_bid_withheld():
    rows, *_ = _collapsed()
    assert all(v == 0 for v in _money(rows).values()), _money(rows)
    li = next(li for li in rows if li.parcel_id == "713272200834")
    rec, _ = _published(li)
    calc = rec["raw"]["calc"]
    assert calc["arv_expected"] == 300.0 and "arv_land_sqft_mismatch" in calc["arv_flags"]
    assert "max_bid_70" not in calc and "wholesale_mao" not in calc
    assert not (rec["raw"].get("equity") or {}).get("value")
    # nor the copy's house: the live row is a vacant HOA lot
    assert rec["bedrooms"] is None and rec["bathrooms"] is None and rec["year_built"] is None
    assert rec["owner_name"] == "MISTYBROOK HOME OWNERS ASSN"


def test_no_published_row_names_another_owner():
    """For every group: no identity token of a person the copy's personal blocks name (and the
    live row does not) appears anywhere in the published record or its detail entry."""
    groups = _by_key()
    rows, *_ = _collapsed()
    by_key = {PT.parcel_key(li.state, li.county, li.parcel_id): li for li in rows}
    checked = 0
    for key, g in groups.items():
        toks = set().union(*(_other_party_tokens(g["keep"], c) for c in g["drop"]))
        text = _text(*_published(by_key[key]))
        assert not {t for t in toks if re.search(rf"\b{t}\b", text)}, key
        checked += bool(toks)
    assert checked >= 11


def test_dear_francis_and_halliday_are_gone():
    rows, *_ = _collapsed()
    texts = {li.parcel_id: _text(*_published(li)) for li in rows}
    assert "DEAR FRANCIS" not in texts["1616705"] and "WALSH" not in texts["1616705"]
    assert not any("HALLIDAY" in t for t in texts.values())
    # nor a phone only a copy carried (the fixture's phones are redacted to (555) 010-NNNN)
    groups = _by_key()
    live_phones = set(re.findall(r"\(555\) 010-\d{4}", _text(*(g["keep"].model_dump(mode="json")
                                                                for g in groups.values()))))
    copy_phones = set(re.findall(r"\(555\) 010-\d{4}", _text(*(c.model_dump(mode="json")
                                                                for g in groups.values()
                                                                for c in g["drop"])))) - live_phones
    assert copy_phones and not any(p in t for p in copy_phones for t in texts.values())


def test_a_county_situs_is_still_restored_and_nothing_else_comes_with_it():
    rows, *_ = _collapsed()
    groups = _by_key()
    by_pid = {li.parcel_id: li for li in rows}
    nowak = by_pid["714252203123"]
    assert nowak.street_address == "499 PATCH DR SPARTANBURG"
    assert nowak.raw["situs_address_source"] == "parcel_cache:exact"
    assert nowak.owner_name == "BURNETT PAUL A JR TRUSTEE" and "NOWAK" not in _text(*_published(nowak))
    assert nowak.first_seen == groups["SC|spartanburg|714252203123"]["keep"].first_seen   # owner differs
    donelly = by_pid["879362599800000"]
    g = groups["NC|buncombe|8793625998"]
    assert donelly.street_address == "560 PINEY KNOB RD"
    assert donelly.first_seen == g["drop"][0].first_seen < g["keep"].first_seen          # same owner
    assert set(donelly.raw) == set(g["keep"].raw) | {"situs_address_source"}


def test_absorb_copies_changes_neither_input_and_refuses_an_unlisted_field(monkeypatch):
    g = _by_key()["NC|rutherford|1616705"]
    before = (g["keep"].model_dump(mode="json"), g["drop"][0].model_dump(mode="json"))
    merged, taken = PT.absorb_copies(g["keep"], g["drop"])
    assert (g["keep"].model_dump(mode="json"), g["drop"][0].model_dump(mode="json")) == before
    assert taken == [] and merged.model_dump(mode="json") == before[0]
    monkeypatch.setattr(PT, "COPY_ALLOWLIST", {"first_seen": "x"})
    g2 = _by_key()["SC|spartanburg|714252203123"]
    with pytest.raises(AssertionError, match="outside COPY_ALLOWLIST"):
        PT.absorb_copies(g2["keep"], g2["drop"])


@pytest.mark.parametrize("a,b,same", [
    ("DONELLY, SHANNON P", "DONELLY, SHANNON P", True),
    ("ALLISON, WAYNE L ALLISON, L MARLENE", "ALLISON, WAYNE", True),
    ("TOLEDANO, JOHN OSWALD HALL III", "TOLEDANO, JOHN OSWALD", True),
    ("FOSTER, TAMMIE", "WALSH, FRANCIS ROBERT", False),
    ("MISTYBROOK HOME OWNERS ASSN", "HALLIDAY Q STANFORD IV", False),
    ("SMITH JOHN", "SMITH MARY", False),
    (None, "ALEXANDER WILLIAM & ALEXANDER LAURA", False),
    ("", "", False),
])
def test_same_owner(a, b, same):
    assert PT.same_owner({"owner_name": a}, {"owner_name": b}) is same


# ------------------------------------------------------------------ the detail sidecar path
def _prior_board(docs: Path, copies: list[Listing]) -> None:
    """The board the 10/5 run merged, as far as these parcels go: the aged copies as the prior
    run published them (no withdrawn tag yet), vision/comps/cama in the sidecar."""
    prior = []
    for c in copies:
        p = c.model_copy(deep=True)
        p.raw.pop("pulled_sale", None)
        p.raw.pop("stale_case", None)
        p.auction_status = None
        prior.append(p)
    wa.write_artifact(prior, {"notes": "prior"}, docs_dir=docs)


def _details(docs: Path) -> dict:
    recs = wa.read_board_json(docs / "listings.json")
    dets = wa.read_board_json(docs / "listings_detail.json")
    return {r["parcel_id"]: d for r, d in zip(recs, dets)}


def test_kept_rows_publish_their_own_detail_not_the_prior_boards_copy(tmp_path):
    groups = _by_key()
    copies = [c for g in groups.values() for c in g["drop"]]
    own = {g["keep"].parcel_id: _published(g["keep"])[1] for g in groups.values()}

    leak = tmp_path / "without"
    _prior_board(leak, copies)
    rows, _plan_, _res, kept = _collapsed()
    wa.write_artifact(rows, {"notes": "no exclusions"}, docs_dir=leak)
    got = _details(leak)
    leaked = {pid for pid, d in got.items() if set(d) - set(own[pid])}
    assert len(leaked) >= 10       # the path is real: the copy's vision/comps/cama come back

    docs = tmp_path / "with"
    _prior_board(docs, copies)
    rows, _plan_, _res, kept = _collapsed()
    wa.write_artifact(rows, {"notes": "fixed"}, docs_dir=docs,
                      no_prior_detail_rows=kept["rows"], no_prior_detail_keys=kept["keys"])
    got = _details(docs)
    assert got == {pid: json.loads(json.dumps(d, default=str)) for pid, d in own.items()}
    # and the derivatives are projections of exactly that
    shard = json.loads(gzip.decompress((docs / "detail_shards" / "00000.json.gz").read_bytes()))
    slim = json.loads((docs / "listings_slim.json").read_text())
    assert not any("HALLIDAY" in _text(x) or "DEAR FRANCIS" in _text(x) for x in shard + slim)


def test_a_dropped_copys_key_does_not_join_another_row_to_the_prior_board(tmp_path):
    """713272200834's copy published '100 MISTYBROOK DR' (the HOA's mailing address). A live row
    AT that address (here: the HOA's own lot) shared that key with the copy, so it had no
    backfill; dropping the copy makes the key unique and would hand it the copy's prior vision."""
    g = _by_key()["SC|spartanburg|713272200834"]
    copy_ = g["drop"][0]
    assert copy_.street_address == "100 MISTYBROOK DR"
    neighbour = Listing(source="counties_sc.spartanburg_vacant", source_url="https://example.invalid/x",
                        state="SC", county="Spartanburg", street_address="100 MISTYBROOK DR",
                        parcel_id="713272299999", owner_name="MISTYBROOK HOME OWNERS ASSN",
                        first_seen=g["keep"].first_seen, last_seen=g["keep"].last_seen)

    def board():
        return [copy_.model_copy(deep=True), g["keep"].model_copy(deep=True), neighbour.model_copy(deep=True)]

    def run(docs, exclude):
        _prior_board(docs, [copy_])
        rows = board()
        kept: dict = {}
        PT.apply_collapse(rows, _plan(rows), kept_out=kept)
        kw = {"no_prior_detail_rows": kept["rows"], "no_prior_detail_keys": kept["keys"]} if exclude else {}
        wa.write_artifact(rows, {"notes": "x"}, docs_dir=docs, **kw)
        return _details(docs)

    assert "vision" in run(tmp_path / "without", False)["713272299999"]
    assert run(tmp_path / "with", True)["713272299999"] == {}


def test_write_artifact_refuses_a_kept_row_that_is_not_on_the_board(tmp_path):
    docs = tmp_path / "docs"
    rows, _plan_, _res, kept = _collapsed()
    stray = kept["rows"][0].model_copy(deep=True)       # equal, but not the object on the board
    with pytest.raises(ValueError, match="not on the board"):
        wa.write_artifact(rows, {"notes": "x"}, docs_dir=docs, no_prior_detail_rows=[stray])
    assert not (docs / "listings.json").exists()


# --------------------------------------------------------------------- resume script wiring
def _script():
    spec = importlib.util.spec_from_file_location("resume_from_checkpoint",
                                                  REPO / "scripts" / "resume_from_checkpoint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_resume_collapse_hands_write_artifact_the_exclusions(monkeypatch):
    mod = _script()
    monkeypatch.setattr(mod, "_mark", lambda *a, **k: None)
    monkeypatch.setenv("RESUME_SEEN_SINCE", SEEN)
    rows = _rows()
    digest = _plan(rows).digest()
    st = M.TailState(enriched=rows, enrichment_stats={}, errors=[], cfg=None)
    summary = {"notes": "x"}
    mod._collapse(st, summary, digest)
    kw = st.write_artifact_kwargs
    assert len(st.enriched) == 14 and f"plan {digest}" in summary["notes"]
    assert {id(li) for li in kw["no_prior_detail_rows"]} == {id(li) for li in st.enriched}
    assert "p:713272200834" in kw["no_prior_detail_keys"]
    assert "a:100 mistybrook dr|spartanburg" in kw["no_prior_detail_keys"]


def test_publish_tail_passes_the_exclusions_to_write_artifact(monkeypatch):
    got = {}

    def fake_write(listings, summary, **kw):
        got.update(kw)
    monkeypatch.setattr(M, "write_artifact", fake_write)
    monkeypatch.setattr(M.checkpoint, "clear", lambda: None)
    cfg = type("Cfg", (), {"sheet_id": "s", "google_service_account_json": "{}", "gmail_app_password": "p",
                           "gmail_sender": "a@b", "email_recipients": ["c@d"]})()
    rows = _rows()[:2]
    st = M.TailState(enriched=rows, enrichment_stats={}, errors=[], cfg=cfg, update_source_health=False,
                     write_sold_pool=False, write_run_health=False, export_and_email=False,
                     write_artifact_kwargs={"no_prior_detail_rows": rows[:1],
                                            "no_prior_detail_keys": frozenset({"p:x"})})
    assert M.publish_tail(st, {"total": 2}) == M.EXIT_OK
    assert got == {"no_prior_detail_rows": rows[:1], "no_prior_detail_keys": frozenset({"p:x"})}
