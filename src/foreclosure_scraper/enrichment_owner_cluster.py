"""Same-owner parcel clustering — one death/owner touching many parcels.

Direct implementation of Dirty Deeds Tier A #2 (docs/dirty_deeds_synthesis_
2026-09-10.md): "One death touching 25 parcels is worth more than 25
unrelated leads. First deal in ep 038 was six houses under one dead owner,
$730k. Ep 067's $163k came from the parcels *behind* the name, not the lead
parcel. Ep 069's $1.9M portfolio was one elderly multi-parcel owner."
Rated free, trivial build (GROUP BY + name normalize) — this module is that
GROUP BY, built on the existing name_normalize.py matching primitives rather
than reinventing name comparison.

WHY county+state IS PART OF THE CLUSTER KEY, NOT JUST THE NAME
    A bare (surname, given-name) key clusters every "SMITH JOHN" on the
    entire board into one group, which is exactly the false-positive class
    name_normalize.py's own docstring warns about (two unrelated "Michael
    Crowe"s). Scoping to county+state trades some cross-county recall (a
    person who inherited parcels in two different counties won't cluster)
    for a much lower false-positive rate -- the right trade for a SIGNAL
    that a human reviews before acting, not an auto-mailer.

WHY ENTITIES ARE EXCLUDED
    is_entity() (TRUST, LLC, bank, etc.) is dropped before clustering. A
    property-management LLC legitimately holding 40 parcels is not a death
    signal; it is an ordinary business, and including it would drown every
    real person-cluster in noise.

WHAT COUNTS AS A DISTINCT PROPERTY
    Two board rows for the same owner at the same parcel_id (or, lacking
    one, the same street_address) are the same property seen through two
    source tags (e.g. liensnc vs counties_generic.liensnc) -- deduped before
    counting cluster size, so a duplicate-ingestion artifact can never look
    like a multi-parcel owner.

CONFIDENCE
    "high" when every member's parsed given-name tokens agree wherever both
    carry a spelled-out middle name (no name_normalize.middle_conflict-style
    disagreement across the cluster); "low" otherwise -- same-surname/
    same-first-name people ARE sometimes different individuals (father/son,
    unrelated), and the confidence flag rides along so a human reviewing the
    cluster can see the doubt, per name_normalize.py's own stated policy of
    never silently upgrading a shaky name match.

100% offline. No network calls; pure re-organization of owner_name + county
+ state + parcel_id/street_address, all already on the board.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

import structlog

from .models import Listing
from .name_normalize import is_entity, person_orderings

log = structlog.get_logger()

# name_normalize.is_entity() only catches formal corporate/fiduciary suffixes
# (LLC, INC, TRUST, ...). Live-checked against a real dry-run of this
# enricher on the full board 2026-09-16: the two biggest "clusters" it
# produced were 'MERITAGE HOMES' (264 parcels) and 'LENNAR HOMES' (189
# parcels) -- both national homebuilders, parsed as PersonName(surname=
# 'HOMES', given=('MERITAGE',)) / similar, since neither contains a token
# is_entity() recognizes. A third, 'LINCOLN COUNTY' (130 parcels), is a
# government entity -- is_entity() has no government check at all (that
# logic lives in a different, unrelated module). These would have shipped
# as false "one dead person owns hundreds of parcels" signals.
_NOT_A_PERSON = re.compile(
    r"\b(?:HOMES?|BUILDERS?|BUILDING|CONSTRUCTION|DEVELOPERS?|DEVELOPMENT|"
    r"REALTY|REAL\s*ESTATE|HOUSING|COMMUNITIES|COMMUNITY|VILLAGE|ESTATES?|"
    r"CROSSING|LANDING|RIDGE|FALLS|PLANTATION|PRESERVE|COUNTY|CITY\s+OF|"
    r"TOWN\s+OF|STATE\s+OF|AUTHORITY|COMMISSION|DEPARTMENT|SCHOOL|DISTRICT|"
    r"HOSPITAL|UNIVERSITY|COLLEGE|CHURCH|MINISTRIES|CEMETERY|ASSOCIATION|"
    r"HOA)\b",
    re.I,
)

# Above this many distinct properties under one "person" name in one county,
# a real individual owning that much personal-name real estate is
# implausible (the Dirty Deeds corpus's own largest cited individual
# multi-parcel case was ~6 houses under one dead owner) -- far more likely
# an HOA/community name, a builder name missed by _NOT_A_PERSON, or a very
# common name shared by many unrelated people. Never dropped, just marked
# for a human to sanity-check rather than presented as a clean signal.
_SANITY_CAP = 15


def _surname_first_reading(owner_name: str):
    """Board owner_name is overwhelmingly county-GIS SURNAME-FIRST, no comma
    ('BYRD SANDRA D', 'BOBO RALPH F' -- verified live against board data
    2026-09-16). person_orderings() returns [FIRST_MIDDLE_LAST,
    LAST_FIRST_MIDDLE] when a name has no comma (both are plausible in
    general), and just [the comma-parsed reading] when it does. Picking
    orderings[0] unconditionally silently assumes FIRST_MIDDLE_LAST, which
    is backwards for this board and was caught by
    test_owner_cluster.py -- two real board-shaped names ('SMITH JOHN
    ROBERT' / 'SMITH JOHN MICHAEL') clustered as 0 instead of 1 because
    'ROBERT'/'MICHAEL' were read as the surname. Prefer the LAST_FIRST_
    MIDDLE reading (index 1) when both exist; fall back to the only
    reading when the name was comma-parsed (a single, authoritative
    reading either way)."""
    orderings = person_orderings(owner_name)
    if not orderings:
        return None
    return orderings[1] if len(orderings) > 1 else orderings[0]


def _cluster_key(li: Listing) -> tuple[str, str, str, str] | None:
    if not li.owner_name or not li.county or not li.state:
        return None
    if is_entity(li.owner_name) or _NOT_A_PERSON.search(li.owner_name):
        return None
    person = _surname_first_reading(li.owner_name)
    if person is None or not person.given:
        return None  # a bare single-token name is too weak to cluster on
    county = li.county.replace(" County", "").strip().upper()
    return (person.surname, person.given[0], county, li.state.upper())


def _property_key(li: Listing) -> str:
    if li.parcel_id:
        return f"pid:{li.parcel_id.strip().upper()}"
    if li.street_address:
        return f"addr:{li.street_address.strip().upper()}"
    return f"src:{li.source_url}"


def _given_tokens(li: Listing) -> tuple[str, ...]:
    person = _surname_first_reading(li.owner_name)
    return person.given if person else ()


def enrich_owner_cluster(listings: Iterable[Listing]) -> dict:
    """Stamp raw['owner_cluster'] on every member of a same-owner,
    2+-distinct-property cluster within one county. Never drops a lead."""
    listings = list(listings)
    stats = {"clusters": 0, "tagged_rows": 0, "high_confidence_clusters": 0,
             "low_confidence_clusters": 0, "max_cluster_size": 0}

    groups: dict[tuple[str, str, str, str], list[Listing]] = defaultdict(list)
    for li in listings:
        key = _cluster_key(li)
        if key is not None:
            groups[key].append(li)

    for key, members in groups.items():
        # Dedupe to distinct properties before judging cluster size.
        by_property: dict[str, list[Listing]] = defaultdict(list)
        for li in members:
            by_property[_property_key(li)].append(li)
        if len(by_property) < 2:
            continue  # one property under this name -- not a cluster

        # Confidence: any two DIFFERENT properties whose members both carry a
        # spelled-out (len>1) middle/given token beyond the first, and those
        # tokens disagree, drags the whole cluster to low confidence.
        middle_sets = []
        for prop_members in by_property.values():
            mids = set()
            for li in prop_members:
                toks = _given_tokens(li)
                mids |= {t for t in toks[1:] if len(t) > 1}
            if mids:
                middle_sets.append(mids)
        conflict = False
        for i in range(len(middle_sets)):
            for j in range(i + 1, len(middle_sets)):
                if middle_sets[i] and middle_sets[j] and not (middle_sets[i] & middle_sets[j]):
                    conflict = True
                    break
            if conflict:
                break
        cluster_size = len(by_property)
        oversized = cluster_size > _SANITY_CAP
        confidence = "low" if (conflict or oversized) else "high"
        surname, given, county, state = key
        cluster_id = f"{surname}|{given}|{county}|{state}"
        total_value = 0.0
        parcel_ids = []
        sources = []
        for prop_members in by_property.values():
            li0 = prop_members[0]
            v = li0.market_value or li0.assessed_value or li0.tax_value
            if v:
                total_value += v
            if li0.parcel_id:
                parcel_ids.append(li0.parcel_id)
            sources.append(li0.source)

        block = {
            "cluster_id": cluster_id,
            "cluster_size": cluster_size,
            "confidence": confidence,
            "low_confidence_reason": ("oversized" if oversized else "name_conflict" if conflict else None),
            "county": county,
            "state": state,
            "total_value": round(total_value, 2) if total_value else None,
            "parcel_ids": parcel_ids,
            "member_sources": sources,
        }
        for li in members:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["owner_cluster"] = block

        stats["clusters"] += 1
        stats["tagged_rows"] += len(members)
        stats["max_cluster_size"] = max(stats["max_cluster_size"], cluster_size)
        stats[f"{confidence}_confidence_clusters"] += 1

    if stats["clusters"]:
        log.info("owner_cluster.done", **stats)
    return stats
