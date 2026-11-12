"""A GRANDFATHER-restored row must still merge with a same-property row dedupe2 already placed in
`enriched`, instead of publishing both (audit 2026-10-18, identity-no-duplicate-properties).

THE HAZARD. main.run()'s GRANDFATHER restore (docs/HANDOFF.md items 69-71, 80) only EXTENDS
`enriched` with every snapshotted row whose dedupe_key the final board lacks -- it never re-runs
dedupe() over the combined list. A restored row's dedupe_key is the snapshot's (a short, untrusted
parcel id dedupe_key() still accepts, e.g. '15876' -- below placeholder_twins.MIN_PARCEL_LEN, so
identity.pk is None and dedupe()'s pass 2 fuzzy-address match is free to fire), which routinely
differs from the live row of the SAME property dedupe2 already placed in `enriched` under its
address key. Live-confirmed on the published board (2026-10-18): a Fannie HomePath lead
(national.fannie_homepath, parcel '15876', already carrying raw['also_seen_in'] naming
national.homepath_json from an earlier successful merge) published ALONGSIDE a fresh
national.homepath_json row of the identical property (same case_number
'fannie-1e4e8692-5dd0-4089-b315-4797d01cd78b', same address, same mls_id/property_uuid) -- two rows,
one property. dedupe() merges the pair on contact (pass 2: same county+state, address score 100, no
parcel conflict since neither key is a trusted parcel); nothing calls it again after the restore.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper import dedupe as D
from foreclosure_scraper.models import Listing

NOW = datetime(2026, 10, 16, 19, 52, 0)


def _fannie_homepath_row() -> Listing:
    """The grandfather snapshot's copy: short parcel id, already merged with homepath_json once."""
    return Listing(
        source="national.fannie_homepath", source_url="https://homepath.fanniemae.com/property/1e4e8692",
        listing_type="reo", state="NC", county="Cleveland", parcel_id="15876",
        street_address="3146 Fallston Waco Rd", zip_code="28150", owner_name="CRAFT JOHN WHITNEY",
        case_number="fannie-1e4e8692-5dd0-4089-b315-4797d01cd78b",
        first_seen=NOW, last_seen=NOW,
        raw={"also_seen_in": [{"source": "national.homepath_json",
                               "url": "https://homepath.fanniemae.com/property/1e4e8692",
                               "listing_type": "reo"}],
             "homepath_json": {"mls_id": "4416264", "property_uuid": "1e4e8692"}},
    )


def _homepath_json_row() -> Listing:
    """This run's fresh re-scrape of the SAME property: no parcel, keyed by address."""
    return Listing(
        source="national.homepath_json", source_url="https://homepath.fanniemae.com/property/1e4e8692",
        listing_type="reo", state="NC", county="Cleveland", parcel_id=None,
        street_address="3146 Fallston Waco Rd", zip_code="28150", owner_name=None,
        case_number="fannie-1e4e8692-5dd0-4089-b315-4797d01cd78b",
        first_seen=NOW, last_seen=NOW,
        raw={"homepath_json": {"mls_id": "4416264", "property_uuid": "1e4e8692"}},
    )


def test_the_two_rows_key_differently_so_the_restore_cannot_see_them_as_one():
    """Why extend() alone can't catch it: the restored row's dedupe_key never matches the fresh
    row's, so the restore's own "key the final board lacks" test always treats it as missing."""
    fannie, homepath_json = _fannie_homepath_row(), _homepath_json_row()
    assert fannie.dedupe_key() != homepath_json.dedupe_key()
    assert fannie.dedupe_key().startswith("parcel:")
    assert homepath_json.dedupe_key().startswith("addr:")


def test_without_a_dedupe_pass_the_restore_publishes_both_rows():
    """Today's behaviour (the bug): plain list extension, no re-dedupe."""
    enriched = [_homepath_json_row()]
    restored = [_fannie_homepath_row()]
    enriched.extend(restored)                      # exactly what main.run()'s restore does today
    assert len(enriched) == 2


def test_rerunning_dedupe_after_the_restore_merges_the_duplicate():
    """The fix: dedupe() again over the combined list collapses the pair dedupe2 never saw
    together, the same way it already merges them when given both rows up front."""
    enriched = [_homepath_json_row()]
    restored = [_fannie_homepath_row()]
    enriched.extend(restored)
    deduped = D.dedupe(enriched)
    assert len(deduped) == 1
    survivor = deduped[0]
    assert survivor.parcel_id == "15876"            # the fuller (fannie_homepath) record wins fields
    assert survivor.owner_name == "CRAFT JOHN WHITNEY"
    sources = {d["source"] for d in (survivor.raw.get("also_seen_in") or [])}
    sources.add(survivor.source)
    assert sources == {"national.fannie_homepath", "national.homepath_json"}


def test_a_restored_row_of_a_different_property_is_left_alone():
    """The fix must not fuse unrelated leads: a restored row at a different address merges with
    nothing and survives as its own row."""
    other = _fannie_homepath_row().model_copy(update={
        "street_address": "900 Some Other Rd", "parcel_id": "9999999", "case_number": "fannie-other",
        "raw": {},
    })
    enriched = [_homepath_json_row(), other]
    deduped = D.dedupe(enriched)
    assert len(deduped) == 2
