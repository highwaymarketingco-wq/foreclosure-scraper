"""dedupe() must still merge a roll record's two copies when one has been aliased to a DIFFERENT
numbering system's parcel_id and the other's own short id was nulled by validation (regressions-
roll-records-kept, 2026-10-18).

THE DEFECT. A roll scraper publishes a short, source-native id both as the row's own parcel_id
and in its raw block (e.g. raw['nc_ptscloud_delinquent_tax']['parcel']). Two independent things
can happen to two different scrapes of the SAME roll record: parcel_alias.apply() may overwrite
one copy's parcel_id with a GIS-resolved PIN from a different numbering system (never touching
raw); and validation may null the OTHER copy's parcel_id as too short, leaving it with no field
value at all, address-less, case-less -- reachable by nothing in dedupe() except the raw block
both copies still share. Confirmed live 2026-10-18: Madison county "1644"/"REDMON, J. H." -- one
copy parcel_id=8795000000 (an aliased PIN), the other parcel_id=None, both carrying
raw.nc_ptscloud_delinquent_tax.parcel=="1644" -- published as two permanent rows.

THE FIX (dedupe.py): `_strong_sigs()` gains a source-parcel ("sp") signature read from the row's
own raw block directly (`_own_source_parcel_value()`), independent of what parcel_id currently
holds -- the address-less, parcel-less nulled copy previously had ZERO signatures in any pass.
`identity_of()`'s own `sp` (what identity_conflict()'s different_source_parcels() compares) now
prefers that same raw-block value over parcel_id for any _SOURCE_PARCEL_FIELDS source, since
parcel_alias.apply() never touches raw: without this, the aliased copy's identity.sp falsely
claimed the SOURCE itself published the GIS PIN, and different_source_parcels() read the two
copies as two DIFFERENT accounts of one roll (the correct behavior for a genuinely different id)
and refused the merge.

Fixtures are invented (owners, ids, URLs); the shape matches the real Madison pair exactly.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper import dedupe as D
from foreclosure_scraper.models import Listing, ListingType

T = datetime(2026, 10, 8, 2, 0)
PORTAL = "https://example.invalid/ptscloud/"
SOURCE = "counties_nc.nc_ptscloud_delinquent_tax"


def roll_row(parcel_id, roll_id, owner, *, county="Madison", **kw) -> Listing:
    raw = {"nc_ptscloud_delinquent_tax": {"parcel": roll_id, "owner": owner}}
    base = dict(source=SOURCE, source_url=PORTAL, listing_type=ListingType.TAX_LIEN, state="NC",
                county=county, parcel_id=parcel_id, street_address=None, owner_name=owner, raw=raw,
                first_seen=T, last_seen=T)
    base.update(kw)
    return Listing(**base)


def test_an_aliased_copy_and_its_nulled_sibling_still_merge():
    aliased = roll_row("8795000000", "1644", "REDMON, J. H.")       # parcel_alias overwrote this one
    nulled = roll_row(None, "1644", "REDMON, J. H.")                # validation nulled this one
    out = D.dedupe([aliased, nulled])
    assert len(out) == 1, [li.parcel_id for li in out]
    # the merge keeps the more useful (aliased, resolved) id, not the bare roll number
    assert out[0].parcel_id == "8795000000"


def test_the_merge_works_whichever_row_comes_first():
    aliased = roll_row("8795000000", "1644", "REDMON, J. H.")
    nulled = roll_row(None, "1644", "REDMON, J. H.")
    assert len(D.dedupe([nulled, aliased])) == 1


def test_own_source_parcel_value_reads_the_raw_block_not_the_field():
    aliased = roll_row("8795000000", "1644", "REDMON, J. H.")
    assert D.own_source_parcel_value(aliased.raw, aliased.source) == "1644"
    no_block = roll_row("8795000000", "1644", "REDMON, J. H.", source="counties_nc.rutherford_tax")
    assert D.own_source_parcel_value(no_block.raw, no_block.source) is None


def test_identity_sp_prefers_the_raw_block_over_an_aliased_parcel_id():
    aliased = roll_row("8795000000", "1644", "REDMON, J. H.")
    ident = D.identity(aliased)
    assert ident.sp == frozenset({("NC|madison|1644", SOURCE)})
    # the resolved PIN still wins as the row's own match key (pk) -- only sp (source-published
    # identity) changes; a BETTER key for matching other sources is exactly what aliasing is for
    assert ident.pk == "NC|8795000000"


def test_two_genuinely_different_roll_accounts_still_stay_apart():
    """The sibling case this fix must NOT break: two DIFFERENT roll entries of one taxpayer are
    two different properties, aliased or not."""
    a = roll_row("8795000001", "1644", "REDMON, J. H.")
    b = roll_row("8795000002", "1645", "REDMON, J. H.")             # a different account, same owner
    assert len(D.dedupe([a, b])) == 2


def test_the_same_roll_id_in_two_counties_still_stays_apart():
    """The exact cross-county fusion test_dedupe_roll_url_keys.py's fix already covers, re-checked
    against the raw-block-based sp path specifically: the ref is "ST|county|parcel", so a shared
    roll id can never fuse two counties through this path any more than through the field-based
    "p" signature already protects against."""
    a = roll_row("8795000000", "1644", "REDMON, J. H.", county="Madison")
    b = roll_row(None, "1644", "REDMON, J. H.", county="Beaufort")
    assert len(D.dedupe([a, b])) == 2


def test_two_nulled_siblings_with_no_alias_involved_still_merge_as_before():
    """Neither copy ever got aliased (both parcel_id None): this already worked via the roll-URL-
    keys fix (pass 1's url bucket); confirms this change does not disturb that path."""
    a = roll_row(None, "1644", "REDMON, J. H.")
    b = roll_row(None, "1644", "REDMON, J. H.")
    assert len(D.dedupe([a, b])) == 1
