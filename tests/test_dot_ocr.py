"""Unit tests for enrichment_dot_ocr — Spartanburg records-grid parsing, DOT-row
selection, eligibility gating, and the equity-feed wiring (no network).

The HTML fixtures are REAL Spartanburg Logan `copyToClipboard(...)` calls captured
live 2026-07-01 (search.spartanburgdeeds.com) — a DEED row (SMITH JOHN EARL) and a
MORTGAGE row (GARRETT JAMES), each embedding a free view_image.php?key=<hash>.
"""
import asyncio

from foreclosure_scraper.models import Listing
from foreclosure_scraper import enrichment_dot_ocr as dm


# --- real records-grid rows (verbatim structure from the live site) ----------
_DEED_ROW = (
    "<a href=\"javascript: copyToClipboard('1960000087', '01/08/1960', "
    "'DEE 25-O  495 ', 'DEED', 'LOTS 68 &amp; 69 JOHN B CLEVELAND PLAT 2 SWANEE ST&lt;br&gt;', "
    "'Party 1', 'SMITH JOHN EARL  &lt;br&gt;', ' JENNINGS LEROY GORDON  &lt;br&gt;', '', '',"
    "'&lt;a href=\\'view_image.php?key=9613291fc04ac56eca643dfce09264bd\\' target=\\'_blank\\'"
    "&gt;View Image&lt;/a&gt; &nbsp;');\">Copy to Clipboard</a>"
)
_MORTGAGE_ROW = (
    "<a href=\"javascript: copyToClipboard('1992038402', '10/05/1992', "
    "'MTG 1515  960', 'MORTGAGE', 'LOT 12 KENMATT SUB&lt;br&gt;', "
    "'Party 1', 'GARRETT JAMES V  &lt;br&gt;', ' FIRST FEDERAL  &lt;br&gt;', '', '',"
    "'&lt;a href=\\'view_image.php?key=deadbeefcafef00d1234567890abcdef\\' target=\\'_blank\\'"
    "&gt;View Image&lt;/a&gt; &nbsp;');\">Copy to Clipboard</a>"
)
_OLDER_MORTGAGE_ROW = (
    "<a href=\"javascript: copyToClipboard('1985010101', '03/01/1985', "
    "'MTG 900  100', 'MORTGAGE', 'LOT 12 KENMATT SUB&lt;br&gt;', "
    "'Party 1', 'GARRETT JAMES V  &lt;br&gt;', ' OLD BANK  &lt;br&gt;', '', '',"
    "'&lt;a href=\\'view_image.php?key=00001111222233334444555566667777\\' target=\\'_blank\\'"
    "&gt;View Image&lt;/a&gt; &nbsp;');\">Copy to Clipboard</a>"
)


def _li(**kw):
    base = dict(source="test", source_url="https://x/y", state="SC", county="Spartanburg")
    base.update(kw)
    return Listing(**base)


def _hot(**kw):
    li = _li(**kw)
    li.raw = dict(li.raw or {})
    li.raw["distress_stack"] = {"tier": "HOT"}
    return li


# --- parsing -----------------------------------------------------------------
def test_parse_image_rows_extracts_type_and_key():
    rows = dm._parse_image_rows(_DEED_ROW + _MORTGAGE_ROW)
    assert len(rows) == 2
    d, m = rows
    assert d["doc_type"] == "DEED"
    assert d["key"] == "9613291fc04ac56eca643dfce09264bd"
    assert m["doc_type"] == "MORTGAGE"
    assert m["key"] == "deadbeefcafef00d1234567890abcdef"
    assert "GARRETT JAMES" in m["grantor"]


def test_parse_skips_rows_without_image_key():
    no_key = (
        "<a href=\"javascript: copyToClipboard('1','01/01/2000','B 1 1','DEED',"
        "'L','P1','A','B','','','no image here');\">Copy to Clipboard</a>")
    assert dm._parse_image_rows(no_key) == []


# --- DOT-row selection -------------------------------------------------------
def test_pick_dot_row_prefers_mortgage_over_deed():
    rows = dm._parse_image_rows(_DEED_ROW + _MORTGAGE_ROW)
    row = dm._pick_dot_row(rows, "GARRETT", "JAMES")
    assert row is not None
    assert row["doc_type"] == "MORTGAGE"


def test_pick_dot_row_returns_none_when_no_dot():
    rows = dm._parse_image_rows(_DEED_ROW)  # only a DEED, no mortgage
    assert dm._pick_dot_row(rows, "SMITH", "JOHN") is None


def test_pick_dot_row_picks_newest_note():
    rows = dm._parse_image_rows(_OLDER_MORTGAGE_ROW + _MORTGAGE_ROW)
    row = dm._pick_dot_row(rows, "GARRETT", "JAMES")
    assert row["instrument_no"] == "1992038402"  # 1992 note beats 1985 note


_SATISFACTION_ROW = (
    "<a href=\"javascript: copyToClipboard('2022061107', '12/13/2022', "
    "'MTG 6505  543', 'MORTGAGE SATISFACTION', 'LOT 12 KENMATT SUB&lt;br&gt;', "
    "'Party 1', 'GARRETT JAMES V  &lt;br&gt;', ' SOME BANK  &lt;br&gt;', '', '',"
    "'&lt;a href=\\'view_image.php?key=36864fb0c820aaaabbbbccccddddeeee\\' target=\\'_blank\\'"
    "&gt;View Image&lt;/a&gt; &nbsp;');\">Copy to Clipboard</a>"
)


def test_pick_dot_row_excludes_satisfaction():
    """A MORTGAGE SATISFACTION (newest, but no loan amount) must be skipped in
    favor of the actual original mortgage note — the real-world bug found live."""
    rows = dm._parse_image_rows(_SATISFACTION_ROW + _MORTGAGE_ROW)
    row = dm._pick_dot_row(rows, "GARRETT", "JAMES")
    assert row is not None
    assert "SATISF" not in row["doc_type"].upper()
    assert row["instrument_no"] == "1992038402"  # the 1992 note, not the 2022 SAT


def test_pick_dot_row_none_when_only_satisfaction():
    rows = dm._parse_image_rows(_SATISFACTION_ROW)
    assert dm._pick_dot_row(rows, "GARRETT", "JAMES") is None


def test_owner_row_matching():
    rows = dm._parse_image_rows(_MORTGAGE_ROW)
    assert dm._owner_row(rows[0], "GARRETT", "JAMES") is True
    assert dm._owner_row(rows[0], "NOBODY", "") is False


# --- equity-feed wiring (_apply) --------------------------------------------
def test_apply_writes_loan_amount_and_rod_docs():
    li = _hot(owner_name="GARRETT, JAMES")
    row = dm._parse_image_rows(_MORTGAGE_ROW)[0]
    dm._apply(li, 56097.80, row, {"owner_name": "James V. Garrett",
                                  "property_address": "120 Kenmatt Drive",
                                  "_provider": "gemini"})
    # top-level scalar the equity task names
    assert li.raw["loan_amount"] == 56097.80
    # detail block
    assert li.raw["dot_ocr"]["loan_amount"] == 56097.80
    assert li.raw["dot_ocr"]["image_key"] == "deadbeefcafef00d1234567890abcdef"
    assert li.raw["dot_ocr"]["recorded_date"] == "1992-10-05"
    # equity engine reads rod_docs[].{doc_type,amount,recorded_date}
    docs = li.raw["rod_docs"]
    assert isinstance(docs, list) and len(docs) == 1
    assert docs[0]["amount"] == 56097.80
    assert "MORT" in docs[0]["doc_type"].upper()
    assert docs[0]["recorded_date"].startswith("1992-10-05")


def test_apply_appends_to_existing_rod_docs():
    li = _hot(owner_name="GARRETT, JAMES")
    li.raw["rod_docs"] = [{"doc_type": "LIEN", "amount": None}]
    row = dm._parse_image_rows(_MORTGAGE_ROW)[0]
    dm._apply(li, 100000.0, row, {})
    assert len(li.raw["rod_docs"]) == 2  # existing lien preserved + DOT appended


def test_apply_feeds_equity_engine_recorded_dt():
    """End-to-end: the appended rod_docs entry is the one enrichment_equity
    picks up as the amortization basis."""
    from foreclosure_scraper.enrichment_equity import _recorded_dt
    li = _hot(owner_name="GARRETT, JAMES")
    row = dm._parse_image_rows(_MORTGAGE_ROW)[0]
    dm._apply(li, 56097.80, row, {})
    amt, dt = _recorded_dt(li.raw)
    assert amt == 56097.80
    assert dt is not None


def test_apply_round_trips_all_the_way_to_an_equity_payoff():
    """The regression the live Burke run exposed: `_apply` writes rod_docs with
    the county-native doc code ('D/T') and an ISO DATETIME recorded_date, and
    BOTH of those used to be silently unreadable by the equity engine — 10
    harvested principals produced 0 recorded_deed_of_trust payoffs. Assert the
    whole chain, not just that rod_docs was written."""
    from foreclosure_scraper.enrichment_equity import enrich_equity
    from foreclosure_scraper.rod.models import RodDoc
    from datetime import datetime as _dt
    li = _burke(owner_name="WYKLE, JASON CHAD")
    li.raw["calc"] = {"arv_expected": 250000.0}
    li.opening_bid = 180000.0     # the weaker proxy the bug used to fall back to
    doc = RodDoc(county="Burke", state="NC", doc_type="D/T",
                 recorded_date=_dt(2020, 6, 23), book="2612", page="1203",
                 instrument_no="2020007777", raw={"vendor": "cchs"})
    dm._apply(li, 109000.0, dm._row_from_doc(doc), {})
    assert li.raw["rod_docs"][0]["recorded_date"] == "2020-06-23T00:00:00"
    assert li.raw["rod_docs"][0]["doc_type"] == "D/T"
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_source"] == "recorded_deed_of_trust"
    assert eq["amortization"]["original_principal"] == 109000.0
    assert eq["payoff_is_estimate"] is True


# --- eligibility gating ------------------------------------------------------
# NOTE: Spartanburg is no longer an eligible county — search.spartanburgdeeds.com
# publishes `Allow: /$` + `Disallow: /`, so rod/doc_images gates it out. The
# leads below therefore use NC Burke, a verified free + robots-clean county.
from foreclosure_scraper.rod import doc_images as di  # noqa: E402
from foreclosure_scraper.rod.models import RodDoc      # noqa: E402
from datetime import datetime                          # noqa: E402


def _burke(**kw):
    """A Burke NC lead — free CCHS image, robots-clean, so it IS eligible."""
    base = dict(source="test", source_url="https://x/y", state="NC", county="Burke")
    base.update(kw)
    li = Listing(**base)
    li.raw = dict(li.raw or {})
    return li


def _dot_doc(inst: str, amount_hint: str, when="2019-04-12") -> RodDoc:
    return RodDoc(county="Burke", state="NC", doc_type="D/T",
                  recorded_date=datetime.fromisoformat(when),
                  book="2749", page="358", instrument_no=inst,
                  grantor="GARRETT JAMES V", grantee="FIRST FEDERAL",
                  raw={"image_key": amount_hint, "vendor": "cchs"})


def test_eligible_requires_registered_county():
    disabled = asyncio.run(dm.enrich_dot_ocr([]))  # empty -> no targets
    assert disabled.get("targets", 0) == 0


def test_walled_and_unregistered_counties_are_never_targeted(monkeypatch):
    """Spartanburg (robots Disallow) and Buncombe (vendor cart) must both be
    skipped even at HOT tier — the compliance gate is not a grade gate."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    spartanburg = _hot(owner_name="GARRETT, JAMES")           # robots-disallowed
    buncombe = _hot(county="Buncombe", state="NC", owner_name="SMITH, JOHN")  # paywalled
    stats = asyncio.run(dm.enrich_dot_ocr([spartanburg, buncombe]))
    assert stats["targets"] == 0
    assert "SC:Spartanburg" in stats["walled_counties"]
    assert "NC:Buncombe" in stats["walled_counties"]


def test_cold_lead_is_targeted_grade_gate_is_gone(monkeypatch):
    """The old HOT/WARM-only gate hid equity from exactly the leads whose grade
    was low BECAUSE equity was unknown. A COLD lead must now be a target."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")

    async def _noop(state, county, owner, **kw):
        return []

    monkeypatch.setattr(di, "owner_dot_documents", _noop)
    li = _burke(owner_name="GARRETT, JAMES")   # no distress_stack at all
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert stats["targets"] == 1
    assert stats["searched"] == 1
    assert stats["loan_found"] == 0


def test_tier_env_can_re_narrow(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    monkeypatch.setenv("FORECLOSURE_DOT_OCR_TIERS", "HOT,WARM")
    cold = _burke(owner_name="GARRETT, JAMES")
    stats = asyncio.run(dm.enrich_dot_ocr([cold]))
    assert stats["targets"] == 0


def test_cap_is_env_tunable_and_bounds_the_run(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    monkeypatch.setenv("FORECLOSURE_DOT_OCR_MAX", "2")
    seen = []

    async def _count(state, county, owner, **kw):
        seen.append(owner)
        return []

    monkeypatch.setattr(di, "owner_dot_documents", _count)
    leads = [_burke(owner_name=f"OWNER{i}, X") for i in range(6)]
    stats = asyncio.run(dm.enrich_dot_ocr(leads))
    assert len(seen) == 2 and stats["searched"] == 2
    assert stats["budget_exhausted"] is True


def test_disabled_env(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_DOT_OCR", "0")
    out = asyncio.run(dm.enrich_dot_ocr([_burke(owner_name="X, Y")]))
    assert "skipped" in out


def test_no_gemini_key_skips(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 61):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("FORECLOSURE_DOT_OCR", "1")
    out = asyncio.run(dm.enrich_dot_ocr([_burke(owner_name="X, Y")]))
    assert "skipped" in out and "Gemini" in out["skipped"]


def test_mortgage_signal_gate_skips_no_mortgage_leads(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    li = _burke(owner_name="GARRETT, JAMES")
    li.raw["rod"] = {"has_mortgage": False}  # ROD says no mortgage -> skip
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert stats["targets"] == 0


def test_multi_candidate_skips_satisfaction_falls_through_to_note(monkeypatch):
    """The real-world fix: candidate[0] is a satisfaction (OCR -> null amount),
    candidate[1] is the real note (OCR -> $56,097.80). The loop must skip the
    first and stamp the second."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    from foreclosure_scraper import enrichment_doc_ocr as ocr

    async def _two_candidates(state, county, owner, **kw):
        return [(b"%PDF-sat", "application/pdf", _dot_doc("SAT1", "k1")),
                (b"%PDF-note", "application/pdf", _dot_doc("NOTE1", "k2"))]

    async def _fake_gemini(key, parts, is_text):
        if parts[0][0] == b"%PDF-sat":
            # nominal $10 consideration on the satisfaction -> below the loan floor
            return {"amount": 10.0, "doc_type": "mortgage_satisfaction", "_provider": "gemini"}
        return {"amount": 56097.80, "doc_type": "deed_of_trust", "_provider": "gemini"}

    monkeypatch.setattr(di, "owner_dot_documents", _two_candidates)
    monkeypatch.setattr(ocr, "_gemini_call", _fake_gemini)

    li = _burke(owner_name="GARRETT, JAMES")
    li.raw["rod"] = {"has_mortgage": True}
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert stats["loan_found"] == 1
    assert li.raw["loan_amount"] == 56097.80
    assert li.raw["dot_ocr"]["instrument_no"] == "NOTE1"


def test_trustees_deed_is_rejected_even_when_the_index_mislabels_it(monkeypatch):
    """A trustee's deed's dollar figure is the AUCTION SALE PRICE, the opposite
    of a loan principal. Live-caught on Burke bk2847/pg826. The OCR-side
    backstop must refuse it rather than feed equity an inverted number."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    from foreclosure_scraper import enrichment_doc_ocr as ocr

    async def _one(state, county, owner, **kw):
        return [(b"%PDF-trd", "application/pdf", _dot_doc("TRD1", "k"))]

    async def _gemini(key, parts, is_text):
        return {"amount": 170640.0, "doc_type": "trustees_deed", "_provider": "gemini"}

    monkeypatch.setattr(di, "owner_dot_documents", _one)
    monkeypatch.setattr(ocr, "_gemini_call", _gemini)
    li = _burke(owner_name="GARRETT, JAMES")
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert stats["loan_found"] == 0
    assert stats["rejected_not_note"] == 1
    assert li.raw.get("loan_amount") is None


def test_absurd_amount_is_rejected(monkeypatch):
    """An OCR misread of a parcel id / book+page concatenation must not become a
    billion-dollar principal."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    from foreclosure_scraper import enrichment_doc_ocr as ocr

    async def _one(state, county, owner, **kw):
        return [(b"%PDF-x", "application/pdf", _dot_doc("X1", "k"))]

    async def _gemini(key, parts, is_text):
        return {"amount": 934000000.0, "doc_type": "deed_of_trust", "_provider": "gemini"}

    monkeypatch.setattr(di, "owner_dot_documents", _one)
    monkeypatch.setattr(ocr, "_gemini_call", _gemini)
    li = _burke(owner_name="GARRETT, JAMES")
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert stats["loan_found"] == 0
    assert li.raw.get("loan_amount") is None


def test_all_candidates_null_leaves_lead_unstamped(monkeypatch):
    """If every candidate OCRs to null (all satisfactions / releases), the lead is
    left untouched so it retries next run — no bogus zero written."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-gate")
    from foreclosure_scraper import enrichment_doc_ocr as ocr

    async def _one_candidate(state, county, owner, **kw):
        return [(b"%PDF-sat", "application/pdf", _dot_doc("SAT1", "k"))]

    async def _null_gemini(key, parts, is_text):
        # $10 nominal consideration on a satisfaction -> below floor -> rejected
        return {"amount": 10.0, "doc_type": "deed_of_trust", "_provider": "gemini"}

    monkeypatch.setattr(di, "owner_dot_documents", _one_candidate)
    monkeypatch.setattr(ocr, "_gemini_call", _null_gemini)
    li = _burke(owner_name="GARRETT, JAMES")
    li.raw["rod"] = {"has_mortgage": True}
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert stats["image_ok"] == 1
    assert stats["loan_found"] == 0
    assert li.raw.get("loan_amount") is None


def test_apply_stamps_labelled_estimated_balance():
    """The recorded principal is a FACT; the current balance is an ESTIMATE and
    must be labelled as such — never presented as a payoff."""
    li = _burke(owner_name="GARRETT, JAMES")
    dm._apply(li, 165000.0, dm._row_from_doc(_dot_doc("N1", "k", "2019-04-12")), {})
    d = li.raw["dot_ocr"]
    assert d["loan_amount"] == 165000.0 and d["is_original_principal"] is True
    assert 0 < d["estimated_balance"] < 165000.0     # amortized down, not a payoff
    assert d["estimated_balance_confidence"] in ("medium", "low")
    assert d["estimated_balance_detail"]["is_estimate"] is True
    assert "TILA" in d["not_a_payoff"]
