"""SC divorce accuracy fix (2026-10-02): 0% real matches at population scale.

A live population-scale check against SC's own court index found 0% real
matches at n=58/5,052 -- the FULL previously-flagged population. Two distinct,
confirmed bugs, both fixed here:

1. ROLE BUG (structural, not a confidence judgment): `_owner_in_case`'s
   namesake trim checked a blob of `parties` (the case caption) PLUS
   `PersonName` (the row's own matched-person field). PersonName, by
   construction, always contains the searched last/first name -- it is
   literally who matched the query -- so for a non-party row (Attorney,
   Mediator, Guardian Ad Litem, ...) the trim was a no-op. Live-verified
   2026-10-02: searching the common surname "DAVIS" returns
   "Davis, Davis, Joy C C" / ParticipantRole="Attorney" for ~30 unrelated
   divorce cases (a real SC family-law attorney with many clients), none of
   whose captions mention "Davis" at all -- the OLD code matched every one.
   `_is_party_role` now rejects any row whose role is not a real party
   (Plaintiff/Defendant/Petitioner/Respondent) before it ever reaches
   `_owner_in_case` or raw['divorce']['cases'].

2. WEAK-MATCH GATE (confidence-based, same name_normalize.party_middle_verdict
   convention `jail_booking_new` uses for its own common-name problem):
   party_middle_verdict was already computed for every hit (since
   2026-09-21) but only ever stored as advisory metadata -- an 'unverified'
   verdict (no middle initial on one side, 46% of all hits) passed straight
   through to distress_stack.categories uncorroborated. `_apply` now only
   adds the 'divorce' category when the verdict is 'agrees'. raw['divorce']
   itself (cases + the verdict) is still written for EVERY hit regardless of
   verdict -- never silent -- only the ACTIONABLE category is gated.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_sc_divorce as m
from foreclosure_scraper.models import Listing, ListingType


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = [] if payload is None else payload

    def json(self):
        return self._payload


class _FakeSession:
    """Scripted async session: script(payload) -> _Resp, keyed off nothing but
    the call order (one divorce category at a time, per `_search_one`)."""

    def __init__(self, script):
        self.script = script

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _Resp()

    async def post(self, url, json=None, **k):
        await asyncio.sleep(0)
        return self.script(json)


def _lead(owner="BYRD SANDRA D"):
    li = Listing(source="x", source_url="u1", listing_type=ListingType.TAX_LIEN,
                 state="SC", county="Spartanburg", owner_name=owner, parcel_id="P1")
    li.raw = {"distress_stack": {"categories": []}}   # so a category-append is observable
    return li


def _run(monkeypatch, listing, rows_for_divorce_category):
    """Serve `rows_for_divorce_category` on the 110-Divorce category call,
    empty lists on the other two categories (Separate Support / Other)."""
    def script(payload):
        if payload and any(d.get("PACaseCategoryId") == 1062 for d in payload if isinstance(d, dict)):
            return _Resp(payload=rows_for_divorce_category)
        return _Resp(payload=[])

    fake = _FakeSession(script)
    monkeypatch.setattr(m, "AsyncSession", lambda **k: fake)

    async def _hs(session):
        return "tok"
    monkeypatch.setattr(m, "_handshake", _hs)
    monkeypatch.setattr(m, "_CONCURRENCY", 1)
    return asyncio.run(m.enrich_sc_divorce([listing], max_lookups=1))


def _row(case_id, description, role, person_name="", filed="2026-06-01T00:00:00"):
    return {"CaseId": case_id, "CaseDescription": description, "ParticipantRole": role,
            "PersonName": person_name, "CaseInitialFilingDate": filed,
            "CaseCategory": "110 - Divorce"}


# ---- role bug: an attorney echo must never become a divorce hit -----------------

def test_attorney_role_echo_is_rejected_even_though_personname_matches(monkeypatch):
    """The exact live incident: owner is BYRD; the only "hit" is an attorney
    named Byrd who represents two unrelated people. CaseDescription never
    mentions Byrd at all -- the old PersonName-inclusive blob let this through."""
    li = _lead("BYRD SANDRA D")
    row = _row("2022DR4200999", "JOHN SMITH vs. MARY SMITH", role="Attorney",
               person_name="Byrd, Byrd, Sandra D D")
    stats = _run(monkeypatch, li, [row])
    assert stats["with_divorce"] == 0
    assert li.raw["divorce"]["case_count"] == 0
    assert li.raw["divorce"]["cases"] == []
    assert "divorce" not in li.raw["distress_stack"]["categories"]


def test_guardian_ad_litem_role_is_also_rejected(monkeypatch):
    li = _lead("BYRD SANDRA D")
    row = _row("2022DR4200998", "SOMEONE ELSE vs. ANOTHER PERSON", role="Guardian Ad Litem",
               person_name="Byrd, Byrd, Sandra D D")
    stats = _run(monkeypatch, li, [row])
    assert stats["with_divorce"] == 0
    assert li.raw["divorce"]["cases"] == []


def test_a_real_party_row_is_kept_by_the_role_filter(monkeypatch):
    li = _lead("BYRD SANDRA D")
    row = _row("2022DR4200001", "SANDRA D BYRD vs. ROBERT BYRD", role="Defendant")
    stats = _run(monkeypatch, li, [row])
    assert stats["with_divorce"] == 1
    assert li.raw["divorce"]["case_count"] == 1
    assert li.raw["divorce"]["cases"][0]["case_number"] == "2022DR4200001"


def test_a_missing_role_is_conservatively_kept(monkeypatch):
    """The portal does not always populate ParticipantRole; an unpopulated
    role is not evidence the row is NOT a party (same policy
    distress_score._divorce_signal already used for its own role check)."""
    li = _lead("BYRD SANDRA D")
    row = _row("2022DR4200002", "SANDRA D BYRD vs. ROBERT BYRD", role=None)
    stats = _run(monkeypatch, li, [row])
    assert stats["with_divorce"] == 1


# ---- weak-match gate: only an AGREEING middle initial reaches the category ------

def test_common_name_with_no_middle_corroboration_is_not_categorized(monkeypatch):
    """A real PARTY row (role is correct), common first+last name, but the
    owner carries no middle initial at all -- 'unverified', the dominant
    bucket (46% of all hits) that used to pass straight through. The hit is
    still recorded (never silent) but must not reach distress_stack."""
    li = _lead("BYRD SANDRA")                                    # no middle at all
    row = _row("2022DR4200003", "SANDRA LEE BYRD vs. ROBERT BYRD", role="Plaintiff")
    stats = _run(monkeypatch, li, [row])
    assert stats["with_divorce"] == 1                            # recorded...
    assert li.raw["divorce"]["case_count"] == 1
    assert li.raw["divorce"]["match"] == "unverified"
    assert "divorce" not in li.raw["distress_stack"]["categories"]   # ...but not actionable


def test_conflicting_middle_initial_is_not_categorized(monkeypatch):
    """Same first+last name, a DIFFERENT real middle name on the matched
    party -- a different person (41% of comparable hits, audit 2026-09-21)."""
    li = _lead("BYRD SANDRA D")
    row = _row("2022DR4200004", "SANDRA LEE BYRD vs. ROBERT BYRD", role="Plaintiff")
    stats = _run(monkeypatch, li, [row])
    assert li.raw["divorce"]["match"] == "conflict"
    assert "divorce" not in li.raw["distress_stack"]["categories"]


def test_agreeing_middle_initial_is_categorized(monkeypatch):
    """The real corroborating match: same first+last+middle initial."""
    li = _lead("BYRD SANDRA D")
    row = _row("2022DR4200005", "SANDRA D BYRD vs. ROBERT BYRD", role="Defendant")
    stats = _run(monkeypatch, li, [row])
    assert li.raw["divorce"]["match"] == "agrees"
    assert "divorce" in li.raw["distress_stack"]["categories"]
