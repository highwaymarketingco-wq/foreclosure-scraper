"""enrichment_voter_phone.py's identity-freshness fix (2026-10-03): a match now stamps
`matched_name` and is run through enrichment_sc_phone's identity gate (the same gate
enrichment_sc_voter_xref.py already uses), so a LATER owner_name change is caught on the
next run instead of being silently treated as permanent. Offline: the voter index and the
gate's VoterIdentityIndex are both monkeypatched; nothing touches data/ncvoter or the board.
"""
from __future__ import annotations

import foreclosure_scraper.enrichment_sc_phone as G
import foreclosure_scraper.enrichment_voter_phone as V
from foreclosure_scraper.models import Listing


def _listing(owner="SMITH JOHN A", county="Wake", street="16 Cris Ln", raw=None, **kw) -> Listing:
    return Listing(source=kw.pop("source", "test"), source_url="https://example.com/x", state="NC",
                   county=county, owner_name=owner, street_address=street,
                   raw=raw if raw is not None else {}, **kw)


def _empty_index(monkeypatch):
    """Point enrich_voter_phone() at empty, hand-built indices -- no real-file build."""
    monkeypatch.setattr(V, "_INDEX", {})
    monkeypatch.setattr(V, "_NAME_COUNTY", {})
    monkeypatch.setattr(V, "_FUZZY_INDEX", {})
    monkeypatch.setattr(V, "_NAME_COUNTY_FUZZY", {})


def _gate_index(monkeypatch, *recs: "G.VoterRec"):
    idx = G.VoterIdentityIndex(voter_dir="/nonexistent-voter-dir")
    for r in recs:
        idx.add(r)
    monkeypatch.setattr(G, "_DEFAULT_INDEX", idx)
    return idx


# --------------------------------------------------------------------------------------
# a fresh match
# --------------------------------------------------------------------------------------
def test_a_new_address_match_stamps_matched_name_and_is_corroborated(monkeypatch):
    monkeypatch.setattr(V, "_NAME_COUNTY", {})
    monkeypatch.setattr(V, "_FUZZY_INDEX", {})
    monkeypatch.setattr(V, "_NAME_COUNTY_FUZZY", {})
    monkeypatch.setattr(V, "_INDEX", {("SMITH", "JOHN", "16", "CRIS"): "9195551234"})
    _gate_index(monkeypatch)
    li = _listing(owner="SMITH JOHN A", street="16 Cris Ln")

    stats = V.enrich_voter_phone([li])

    op = li.raw["owner_phone"]
    assert op["phone"] == "(919) 555-1234" and op["source"] == "ncsbe_voter"
    assert op["matched_name"] == "SMITH,JOHN"
    assert op["identity_check"] == "corroborated"
    assert "do_not_dial" not in op
    assert G.is_owner_phone_usable(op) is True
    assert stats["matched_addr"] == 1 and stats["corroborated"] == 1 and stats["regated"] == 0


def test_a_fuzzy_county_match_also_stamps_matched_name(monkeypatch):
    monkeypatch.setattr(V, "_INDEX", {})
    monkeypatch.setattr(V, "_NAME_COUNTY", {})
    monkeypatch.setattr(V, "_FUZZY_INDEX", {})
    monkeypatch.setattr(V, "_NAME_COUNTY_FUZZY",
                        {("WAKE", V._soundex("SMITH"), "JON"): "9195551234"})
    _gate_index(monkeypatch)
    li = _listing(owner="SMITH JON A", county="Wake", street=None)

    V.enrich_voter_phone([li])

    op = li.raw["owner_phone"]
    assert op["match"] == "fuzzy:soundex+county-unique"
    assert op["matched_name"] == "SMITH,JON"
    assert op["identity_check"] == "corroborated"


# --------------------------------------------------------------------------------------
# re-verifying an earlier run's own match
# --------------------------------------------------------------------------------------
def test_an_earlier_match_is_contradicted_once_owner_name_moves_on(monkeypatch):
    _empty_index(monkeypatch)
    _gate_index(monkeypatch)
    # Mirrors the live Buncombe case this fix was built from: the phone still names the
    # voter it was matched to ("BAKER,BETTY"); owner_name has since moved on.
    li = _listing(owner="MAXWELL, RONALD", raw={
        "owner_phone": {"phone": "(828) 712-9100", "source": "ncsbe_voter", "line_type": "unknown",
                        "needs_dnc_scrub": True, "match": "name+county-unique",
                        "matched_name": "BAKER,BETTY"},
    })

    stats = V.enrich_voter_phone([li])

    op = li.raw["owner_phone"]
    assert op["phone"] == "(828) 712-9100"                      # kept, never cleared
    assert op["identity_check"] == "contradicted"
    assert op["do_not_dial"] is True
    assert G.is_owner_phone_usable(op) is False
    assert stats["regated"] == 1 and stats["contradicted"] == 1 and stats["matched"] == 0


def test_an_earlier_match_stays_corroborated_when_owner_name_is_unchanged(monkeypatch):
    _empty_index(monkeypatch)
    _gate_index(monkeypatch)
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": {"phone": "(919) 555-1234", "source": "ncsbe_voter", "line_type": "unknown",
                        "needs_dnc_scrub": True, "match": "name+address",
                        "matched_name": "SMITH,JOHN"},
    })

    stats = V.enrich_voter_phone([li])

    op = li.raw["owner_phone"]
    assert op["identity_check"] == "corroborated"
    assert "do_not_dial" not in op
    assert stats["regated"] == 1 and stats["corroborated"] == 1


def test_a_legacy_block_with_no_matched_name_is_left_exactly_alone(monkeypatch):
    """Written before this fix: no matched_name, so there is nothing to re-verify against --
    same 'code-only, takes effect next run, no retroactive correction' convention every
    sibling fix in this family (owner_name/bop_federal/incarceration/jail_bookings) uses."""
    _empty_index(monkeypatch)
    _gate_index(monkeypatch)
    legacy = {"phone": "(828) 712-9100", "source": "ncsbe_voter", "line_type": "unknown",
             "needs_dnc_scrub": True, "match": "name+county-unique"}
    li = _listing(owner="MAXWELL, RONALD", raw={"owner_phone": dict(legacy)})

    stats = V.enrich_voter_phone([li])

    assert li.raw["owner_phone"] == legacy                       # byte-for-byte untouched
    assert "identity_check" not in li.raw["owner_phone"]
    assert stats["regated"] == 0


def test_a_phone_from_another_source_is_never_gated_or_clobbered(monkeypatch):
    _empty_index(monkeypatch)
    _gate_index(monkeypatch)
    li = _listing(owner="MAXWELL, RONALD", raw={
        "owner_phone": {"phone": "(828) 000-0000", "source": "liensnc_filing"},
    })

    stats = V.enrich_voter_phone([li])

    assert li.raw["owner_phone"]["phone"] == "(828) 000-0000"
    assert "identity_check" not in li.raw["owner_phone"]
    assert stats["regated"] == 0 and stats["matched"] == 0


def test_mixed_batch_only_gates_the_eligible_rows(monkeypatch):
    """One fresh match, one stale earlier match, one legacy block, one foreign-source block --
    only the first two go through the gate; the other two are untouched."""
    monkeypatch.setattr(V, "_NAME_COUNTY", {})
    monkeypatch.setattr(V, "_FUZZY_INDEX", {})
    monkeypatch.setattr(V, "_NAME_COUNTY_FUZZY", {})
    monkeypatch.setattr(V, "_INDEX", {("DOE", "JANE", "1", "ELM"): "9195550001"})
    _gate_index(monkeypatch)

    fresh = _listing(owner="DOE JANE", street="1 Elm St")
    stale = _listing(owner="NEWOWNER, PAT", raw={
        "owner_phone": {"phone": "(919) 555-0002", "source": "ncsbe_voter",
                        "match": "name+address", "matched_name": "OLDOWNER,PAT"},
    })
    legacy = _listing(owner="ANY, BODY", raw={
        "owner_phone": {"phone": "(919) 555-0003", "source": "ncsbe_voter", "match": "name+address"},
    })
    foreign = _listing(owner="ANY, BODY", raw={
        "owner_phone": {"phone": "(919) 555-0004", "source": "liensnc_filing"},
    })

    stats = V.enrich_voter_phone([fresh, stale, legacy, foreign])

    assert fresh.raw["owner_phone"]["identity_check"] == "corroborated"
    assert stale.raw["owner_phone"]["identity_check"] == "contradicted"
    assert stale.raw["owner_phone"]["do_not_dial"] is True
    assert "identity_check" not in legacy.raw["owner_phone"]
    assert "identity_check" not in foreign.raw["owner_phone"]
    assert stats["matched_addr"] == 1 and stats["regated"] == 1 and stats["contradicted"] == 1
