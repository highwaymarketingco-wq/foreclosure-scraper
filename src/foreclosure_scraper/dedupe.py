"""Listing deduplication. Same property from multiple sources merges into one row."""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from typing import NamedTuple, Optional

import structlog
from rapidfuzz import fuzz

from .models import Listing

log = structlog.get_logger()


_SUFFIX = {
    "avenue": "ave", "ave": "ave", "street": "st", "st": "st", "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr", "lane": "ln", "ln": "ln", "boulevard": "blvd", "blvd": "blvd",
    "court": "ct", "ct": "ct", "circle": "cir", "cir": "cir", "place": "pl", "pl": "pl",
    "trail": "trl", "trl": "trl", "way": "way", "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy", "terrace": "ter", "ter": "ter", "loop": "loop", "run": "run",
    "cove": "cv", "cv": "cv", "path": "path", "pike": "pike", "point": "pt", "pt": "pt",
    "crossing": "xing", "square": "sq", "ridge": "rdg",
}


def _canon_street(a: str) -> str:
    """House# + street name through the standardized suffix, dropping any trailing city/unit
    ('19 gosnell avenue inman' -> '19 gosnell ave'). '' if no leading house# or no known suffix."""
    if not a:
        return ""
    toks = a.split()
    if not toks or not re.match(r"^\d", toks[0]):
        return ""
    for i in range(1, len(toks)):
        base = re.sub(r"[^a-z]", "", toks[i])
        if base in _SUFFIX:
            return " ".join(toks[:i] + [_SUFFIX[base]])
    return ""


def _strong_sigs(li: Listing) -> set:
    """Strong same-property signatures for union-merge. Excludes placeholder /
    bankruptcy 'addresses' so name-only rows never collapse together."""
    out: set = set()
    st = (li.state or "")
    z = (li.zip_code or "").strip()
    a = _norm_addr(li.street_address)
    lt = li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type or "")
    if a.startswith(("lis pendens", "property in", "vacant")) or lt == "bankruptcy":
        a = ""
    pn = re.sub(r"[^a-z0-9]", "", (li.parcel_id or "").lower())
    # Same digitless-parcel rejection as models._normalize_parcel. This signature is
    # scoped to the STATE, not the county, so a bogus alpha "parcel" fuses strangers
    # across the whole state -- 'ehurst' linked 122 Pinehurst properties.
    if pn and not any(c.isdigit() for c in pn):
        pn = ""
    if pn and len(pn) >= 4 and st:          # guard: whitespace/degenerate parcel -> no sig
        out.add(("p", pn, st))
        # Buncombe (and similar) write the same PIN two ways: a 15-digit zero-padded form
        # (9678774126 -> 967877412600000) and the bare 10-digit. Emit the 10-digit form too so
        # the padded + bare copies of one parcel union-merge (they otherwise split, esp. on
        # bankruptcy rows that have no address signature to fall back on).
        if len(pn) == 15 and pn.endswith("00000"):
            out.add(("p", pn[:10], st))
    cn = (li.case_number or "").strip()
    if cn and a:                            # require a real case# AND a real address
        out.add(("c", cn, (li.county or ""), a))
    if a and z:
        out.add(("a", a, z))
    # Canonical street + county + state — merges the SAME street address across sources even when
    # one copy lacks a zip or jams the city into the street field (the '19 Gosnell Ave' dup class).
    cs = _canon_street(a)
    cty = re.sub(r"[^a-z0-9]", "", (li.county or "").lower())
    if cs and cty and st:
        out.add(("s", cs, cty, st))
    return out


def _norm_addr(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.lower().replace(",", " ").split())


def _house_no_of(addr: str | None) -> str:
    """Leading house number of a street address, '' when there isn't one."""
    m = re.match(r"\s*(\d+)\b", (addr or "").strip())
    return m.group(1) if m else ""


def _provably_different_property(a: Listing, b: Listing) -> bool:
    """True when two rows are provably NOT the same property.

    A DIFFERENT HOUSE NUMBER is a different house, essentially always. Measured on the
    live board 2026-09-11: rows were merging like

        '306 fountain way'           + '346 fountain way'            parcel 9698372180
        '545 dillingham panoview rd' + '562 dillingham panoview rd'

    -- two separate houses fused because one carries the other's parcel id. A wrong
    parcel does not fail loudly, it silently deletes a property. This guard cannot repair
    the bad parcel; it stops the MERGE, which is the half that loses data.

    Deliberately narrow: it fires only when BOTH rows carry a house number and the two
    differ. Suffix and punctuation variants ('318 fairfax ave' vs '318 fairfax ave.',
    '11 carefree lane' vs '11 carefree ln') share a house number and still merge -- that
    is 93% of real merge groups and must not be lost.
    """
    ha, hb = _house_no_of(a.street_address), _house_no_of(b.street_address)
    return bool(ha and hb and ha != hb)


# ---------------------------------------------------------------- identity evidence (2026-10-06)
# THE DEFECT. dedupe() merged DIFFERENT properties whenever their addresses looked alike and the
# house-number guard above had nothing to compare. Measured on a fresh four-source scrape
# (spartanburg_vacant, spartanburg_condemned, buncombe_delinquent_tax, rutherford_tax; 16,932
# records): 755 output rows had absorbed 2,596 records of other properties (2,339 distinct valid
# parcels gone). On 56 sources scraped fresh together (185,178 rows after main.run()'s filters,
# about 70% of a full run's rows): 6,992 rows had absorbed 32,720 records (26,410 valid parcels),
# and pass 1 deleted 72 rows outright (see the overwrite note in dedupe()). The rules that did it:
#   * pass 2 (fuzzy): token_set_ratio >= 92 in the same zip or county. A county roll's "no house
#     number" sentinel ("0 SOUTHPORT RD", "99999 US 70 HWY") reads as house number "0"/"99999" on
#     both sides, so the guard saw EQUAL numbers: 33 different "0 SOUTHPORT RD" lots, 33 parcels,
#     became one row; "0 HIGH ST" took "0 HUGH ST" and "0 S HIGH POINT RD". A numberless street
#     ("LOOKOUT RD", "BANKS TOWN RD") has no number at all, so it matched every numbered house on
#     its road ("328 LOOKOUT RD"), and the merged row kept the numberless address, so it went on
#     absorbing. Same-number different-street pairs scored >= 92 too ('128 GEORGE ST' + '128
#     GEORGIA ST', '209 BUTLER ST' + '209 BUNKER ST'), each with its own parcel.
#   * pass 3 (signatures): the canonical-street signature ("0 southport rd", county, state) joined
#     the ROEBUCK lots to the SPARTANBURG ones; union-find then chains through any member.
# THE RULE (identity_conflict below; every merge in all three passes goes through it, against the
# whole group already merged, not just the row that matched):
#   * two different REAL house numbers: different properties (the old guard, except that a
#     sentinel is not a real number: placeholder_twins.real_house_no);
#   * two different VALID parcels: different properties, whatever the addresses say. Valid =
#     placeholder_twins.parcel_key() (state + county + normalized parcel of 7+ chars, not one
#     repeated digit, not a book/page pattern; digitless garbage like the PIN_RE 'ehurst' is already
#     rejected) and not attached by a resolver (placeholder_twins.resolver_parcel: a geocoded or
#     road-centroid guess proves nothing either way). The same parcel number in two counties is
#     two parcels; one county spelled two ways ('Rutherford' / 'Rutherfordton') is one;
#   * a row with no real house number (none, or a sentinel) matches a numbered row only when their
#     valid parcels agree, and matches another unnumbered row on ADDRESS evidence only when their
#     valid parcels agree. A shared case number or source URL is not address evidence and still
#     merges as before.
# When a merge does join an unnumbered row to a numbered one (same valid parcel), the merged row
# takes the numbered address (placeholder_twins.fold() does the same): a sentinel is nulled on
# publish, and a numberless base must not go on matching other houses on its road.

def _pt():
    """placeholder_twins, imported on first use (it imports this module at load time)."""
    from . import placeholder_twins
    return placeholder_twins


class Identity(NamedTuple):
    """What a row (or an already-merged group) can PROVE about which property it is."""
    hn: str                    # real house number; '' = no address, no leading number, or a sentinel
    pk: Optional[str] = None   # 'ST|parcel' of a validated parcel; None when absent / invalid /
                               # resolver-derived
    cty: str = ""              # the county that parcel was given under (lowercased)


#: Evidence that made two rows candidates. Only ADDRESS evidence needs a real house number.
ADDRESS, PARCEL, CASE, URL = "address", "parcel", "case", "url"
_KEY_EVIDENCE = {"addr": ADDRESS, "parcel": PARCEL, "case": CASE, "url": URL}
_SIG_EVIDENCE = {"a": ADDRESS, "s": ADDRESS, "p": PARCEL, "c": CASE}


def key_evidence(key: str) -> str:
    """Evidence behind a dedupe_key() ('parcel:..', 'addr:..', 'case:..', 'url:..')."""
    return _KEY_EVIDENCE.get(str(key).split(":", 1)[0], ADDRESS)


def sig_evidence(sig: tuple) -> str:
    """Evidence behind a _strong_sigs() signature, or a ('k', dedupe_key) one."""
    if sig and sig[0] == "k":
        return key_evidence(sig[1])
    return _SIG_EVIDENCE.get(sig[0] if sig else "", ADDRESS)


def identity_of(state, county, parcel_id, street_address, raw) -> Identity:
    """Validity is placeholder_twins.parcel_key()'s (which also needs a known county)."""
    pt = _pt()
    hn = pt.real_house_no(street_address)
    if pt.resolver_parcel(raw):
        return Identity(hn)
    k = pt.parcel_key(state, county, parcel_id)
    if k is None:
        return Identity(hn)
    st, rest = k.split("|", 1)
    cty, parcel = rest.rsplit("|", 1)
    return Identity(hn, f"{st}|{parcel}", cty)


def _same_county(a: str, b: str) -> bool:
    """One county written two ways: the board carries 'Rutherford' / 'Rutherfordton' for one
    parcel (test_digitless_parcel_guard). Two counties are not: an Oconee heir parcel and a Berkeley
    tax bill both carry 097-00-02-002."""
    return a == b or a.startswith(b) or b.startswith(a)


def identity(li) -> Identity:
    """Identity of a Listing or of a board row dict."""
    if isinstance(li, dict):
        return identity_of(li.get("state"), li.get("county"), li.get("parcel_id"),
                           li.get("street_address"), li.get("raw"))
    return identity_of(li.state, li.county, li.parcel_id, li.street_address, li.raw)


def _union(x: Identity, y: Identity) -> Identity:
    p = x if x.pk else y
    return Identity(x.hn or y.hn, p.pk, p.cty)


def different_valid_parcels(x: Identity, y: Identity) -> bool:
    """Both carry a valid parcel and they are not the same parcel."""
    return bool(x.pk and y.pk and (x.pk != y.pk or not _same_county(x.cty, y.cty)))


def identity_conflict(x: Identity, y: Identity, evidence: str = ADDRESS) -> Optional[str]:
    """Why two rows (or merged groups) must NOT be merged, or None when they may be.

    'house_number': two different real house numbers. 'parcel': two different valid parcels.
    'unnumbered': one side has no real house number and the valid parcels do not agree (or, on
    address evidence, neither side has one and the valid parcels do not agree)."""
    if x.hn and y.hn and x.hn != y.hn:
        return "house_number"
    if x.pk and y.pk:
        return "parcel" if different_valid_parcels(x, y) else None
    if x.hn != y.hn:                       # exactly one side carries a real house number
        return "unnumbered"
    if evidence == ADDRESS and not x.hn:   # neither does, and only the address says "same"
        return "unnumbered"
    return None


def _merge(a: Listing, b: Listing) -> Listing:
    """merge_rows(), and an unnumbered merged row takes the numbered member's address (the
    merge was allowed only because their valid parcels agree). An AGED member's number counts
    only when the county wrote it (placeholder_twins.county_situs): on the 10/5 board most numbers
    on aged copies of unnumbered parcels were the owner's mailing address (placeholder_twins'
    ADDRESS RULE), and a live member that has no number must not take one of those, neither over
    its sentinel nor into its empty address (Listing.merge() backfills that)."""
    out = merge_rows(a, b)
    pt = _pt()
    if is_aged(a) != is_aged(b):
        live, aged = (b, a) if is_aged(a) else (a, b)
        if (pt.real_house_no(aged.street_address) and not pt.real_house_no(live.street_address)
                and not pt.county_situs(aged)):
            out.street_address = live.street_address
            return out
    if not pt.real_house_no(out.street_address):
        for li in (a, b):
            if pt.real_house_no(li.street_address):
                out.street_address = li.street_address
                break
    return out


def is_aged(li) -> bool:
    """A carried-forward row the run AGED: merge_prior_board() (or enrich_with_pulled_sales())
    kept it because the scrape did NOT see it, and tagged raw['pulled_sale']. Every other row in
    the run's list (fresh, matched, or created by an enricher) was seen this run."""
    raw = getattr(li, "raw", None)
    return isinstance(raw, dict) and bool(raw.get("pulled_sale"))


def drop_withdrawn_tags(merged: Listing, *, keep_stale_case: bool = False) -> None:
    """A row this run saw cannot be presumed withdrawn. After a live row absorbed aged copies,
    drop what Listing.merge() carried over from them: the pulled_sale miss counter, the
    'presumed_withdrawn' status _age() wrote, and board_quality's derived raw['stale_case'] flag
    (kept only when the live row carried it itself). merge_prior_board() clears the first two
    on a matched row the same way."""
    raw = merged.raw if isinstance(merged.raw, dict) else {}
    if raw.pop("pulled_sale", None) is not None and merged.auction_status == "presumed_withdrawn":
        merged.auction_status = None
    if not keep_stale_case:
        raw.pop("stale_case", None)
    merged.raw = raw


def merge_rows(a: Listing, b: Listing) -> Listing:
    """``a.merge(b)``, except across a live row and an aged one (is_aged()): the LIVE row is the
    base and the result is not presumed withdrawn (drop_withdrawn_tags()). That is exactly
    merge_prior_board()'s fresh.merge(prior): the live row's top-level fields win and the aged
    copy backfills the empty ones; inside raw, Listing.merge() lets the aged copy win leaf
    collisions (how prior enrichment is carried), and the tags are then dropped.

    Why (2026-10-05). main.run()'s second dedupe() runs over merge_prior_board()'s output, which
    holds this run's rows AND the prior rows it aged, and since the 2026-10-04 streaming rewrite
    the aged rows come FIRST. Every pass of dedupe() keeps the earlier row as the merge base, so a
    live row that met an aged row there took the aged row's parcel, address, owner, source and
    status, and Listing.merge()'s raw deep-merge carried raw['pulled_sale'] onto it in either
    order. board_quality then demoted a lead the run had just scraped. merge_prior_board() itself
    merges fresh-first and clears the tag; this keeps dedupe() to the same rule. Two live rows,
    or two aged rows, merge exactly as before."""
    a_aged, b_aged = is_aged(a), is_aged(b)
    if a_aged == b_aged:
        return a.merge(b)
    live, aged = (b, a) if a_aged else (a, b)
    out = live.merge(aged)
    live_raw = live.raw if isinstance(live.raw, dict) else {}
    drop_withdrawn_tags(out, keep_stale_case=bool(live_raw.get("stale_case")))
    return out


def addresses_per_dedupe_key(listings) -> dict[str, set]:
    """dedupe_key() -> the set of distinct normalized street addresses that key covers.

    Pulled out of dedupe() (2026-09-22) so the same "how many real properties does this
    key actually cover" computation used to detect a fused parcel id is available to
    callers that never run dedupe() itself -- the scorer's parcel grouping and the
    parcel-cache join both trust dedupe_key()'s parcel branch the same way dedupe() does,
    and both need to know when it is lying before they act on it."""
    out: dict[str, set] = {}
    for li in listings:
        a = _norm_addr(li.street_address)
        if a:
            out.setdefault(li.dedupe_key(), set()).add(a)
    return out


def suspicious_parcel_keys(listings, min_addresses: int = 4) -> frozenset[str]:
    """dedupe_key()s whose PARCEL branch is shared by min_addresses or more distinct real
    addresses -- the same threshold and computation dedupe.suspicious_primary_key logs.

    A key this broad is not describing one property. The liensnc lien-agent-appointment
    source is the repeat offender: a subdivision's lots share one master-tract PIN until
    the county assigns individual PINs, so a filing batch can cite the SAME PIN for
    dozens to hundreds of different houses (audit 2026-09-22: Pender County parcel
    3208-90-5620-0000 covered 216 distinct addresses in one run). dedupe()'s
    house_number_guard already stops that from deleting rows during a MERGE; this lets
    the scorer's per-parcel grouping and the parcel-cache join refuse to trust the key
    too, instead of silently stacking 216 unrelated properties' signals together or
    copying one property's owner and value onto the other 215."""
    per_key = addresses_per_dedupe_key(listings)
    return frozenset(k for k, addrs in per_key.items()
                      if k.startswith("parcel:") and len(addrs) >= min_addresses)


def dedupe(listings: list[Listing]) -> list[Listing]:
    """Merge listings that point to the same property.

    Strategy:
    1. Bucket by primary dedupe_key (parcel/address/case)
    2. Within each bucket, merge using Listing.merge
    3. Cross-bucket fuzzy address match for stragglers

    Every merge goes through merge_rows(): when a live row meets a row the run aged (raw
    ['pulled_sale']), the live row is the base and the result is not presumed withdrawn,
    whatever order the two arrived in.

    Every candidate merge is checked with identity_conflict() against the WHOLE group merged so
    far (see the block comment above it): two different real house numbers or two different
    valid parcels never merge, and a row with no real house number needs agreeing valid parcels.
    A refused row stays its own row; nothing is dropped.
    """
    if not listings:
        return []

    blocked: Counter = Counter()          # (pass, reason) -> merges refused

    buckets: dict[str, Listing] = {}
    # Identity of each bucket that has absorbed a row (a single row's is read off the row).
    # Holds one small tuple per MERGE, never one per row.
    bucket_ids: dict[str, Identity] = {}
    # Track the DISTINCT street addresses absorbed by each primary key. This is
    # pass 1, where the bulk of merging happens -- and where a bad parcel_id does
    # its damage, because dedupe_key's parcel branch trusts the value with no
    # sanity check. Measured: `scrape_liensnc.py`'s PIN_RE
    # (`(?:pin|tms|parcel|tax\s*map)` IGNORECASE, no word boundary) captured
    # 'ehurst' from "Pinehurst" and 'number' from "PIN number:", so 122 distinct
    # Pinehurst properties shared one key and collapsed into a single row. The run
    # logged nothing. Now it does.
    _addrs_per_key = addresses_per_dedupe_key(listings)
    for li in listings:
        k = li.dedupe_key()
        if k not in buckets:
            buckets[k] = li
            continue
        # Same primary key. A refused row is NOT dropped: it goes on to the next bucket under
        # this key ('<key>\x002', '\x003', ...; no real key contains NUL) it does not conflict
        # with, or opens a new one. (The old guard parked it under '<key>#hn<number>', and a
        # second row with that number OVERWROTE the first one there, deleting it.)
        ev = key_evidence(k)
        li_id = identity(li)
        kk, n = k, 1
        while kk in buckets:
            b_id = bucket_ids.get(kk) or identity(buckets[kk])
            why = identity_conflict(b_id, li_id, ev)
            if why is None:
                buckets[kk] = _merge(buckets[kk], li)
                bucket_ids[kk] = _union(b_id, li_id)
                break
            if kk == k:
                blocked[(1, why)] += 1
            n += 1
            kk = f"{k}\x00{n}"
        else:
            buckets[kk] = li

    _p1 = {r: c for (p, r), c in blocked.items() if p == 1}
    if _p1:
        log.info("dedupe.house_number_guard_pass1", blocked_merges=sum(_p1.values()),
                 reasons=_p1,
                 note="rows sharing a primary key that are provably different properties "
                      "(different house numbers or valid parcels, or an unnumbered row without "
                      "an agreeing valid parcel); merging would have deleted one of them")

    _fused = [(len(v), k) for k, v in _addrs_per_key.items() if len(v) >= 4]
    if _fused:
        _fused.sort(reverse=True)
        log.warning("dedupe.suspicious_primary_key",
                    keys=len(_fused),
                    addresses_fused=sum(n - 1 for n, _ in _fused),
                    worst=[{"key": k, "distinct_addresses": n} for n, k in _fused[:10]])

    merged = list(buckets.values())
    merged_ids: list[Optional[Identity]] = [bucket_ids.get(k) for k in buckets]
    del buckets, bucket_ids

    # Pass 2: fuzzy address merge — across listings that have addresses.
    # Original required zip on both sides; now also matches when both have
    # same county+state (catches the 73 cross-source dups where one source
    # had zip and the other didn't).
    #
    # BLOCKING OPTIMIZATION (2026-08-27): Pre-index by zip and (county, state)
    # so we only compare listings within the same geographic block. This cuts
    # O(n²) on 116K listings (6.7B comparisons) down to ~67M — 100x faster.
    # Without this, merge_prior_board on 94K+22K hangs for hours and the
    # try/except in main.py silently swallows the failure, dropping 72K leads.
    #
    # Each index list is in ascending order, so "every j > i" is a bisect + slice rather than a
    # Python-level filter over the whole block; and each row's normalized address is computed
    # once (merged[j] is never modified before its own turn), not once per candidate pair.
    # Same candidates, same order, same scores: only faster, which matters because the
    # identity rule leaves more rows unconsumed to run their own candidate loops.
    norm_addrs = [_norm_addr(li.street_address) for li in merged]
    # Each row's validated parcel ('ST|parcel', or None). Two rows whose parcels differ can never
    # merge (identity_conflict), so such a pair is skipped before the fuzzy score: without this,
    # every lot of a county's vacant roll (21,767 Gaston rows, each its own parcel) scores against
    # every other one, now that they are no longer folded away. Same merges as scoring them; only
    # the refusal counts logged below no longer include these pairs.
    row_pks = [(merged_ids[j] or identity(merged[j])).pk for j in range(len(merged))]
    by_zip: dict[str, list[int]] = {}
    by_locale: dict[tuple, list[int]] = {}
    for idx, li in enumerate(merged):
        z = (li.zip_code or "").strip()[:5]
        if z:
            by_zip.setdefault(z, []).append(idx)
        cty = (li.county or "").strip().lower()
        st = (li.state or "").strip().lower()
        if cty and st:
            by_locale.setdefault((cty, st), []).append(idx)

    final: list[Listing] = []
    final_ids: list[Optional[Identity]] = []
    consumed: set[int] = set()
    for i, a in enumerate(merged):
        if i in consumed:
            continue
        addr_a = norm_addrs[i]
        if not addr_a:
            final.append(a)
            final_ids.append(merged_ids[i])
            continue
        a_id = merged_ids[i]
        a_merged = a_id is not None
        a_pk = row_pks[i]
        county_a = (a.county or "").strip().lower()
        state_a = (a.state or "").strip().lower()
        zip_a = (a.zip_code or "").strip()[:5]

        # Build candidate set from blocking indexes — NOT all j > i
        candidates: set[int] = set()
        if zip_a and zip_a in by_zip:
            blk = by_zip[zip_a]
            candidates.update(blk[bisect_right(blk, i):])
        locale_key = (county_a, state_a)
        if county_a and state_a and locale_key in by_locale:
            blk = by_locale[locale_key]
            candidates.update(blk[bisect_right(blk, i):])

        for j in candidates:
            if j in consumed:
                continue
            pj = row_pks[j]
            if pj is not None and a_pk is not None and pj != a_pk:
                continue
            b = merged[j]
            if not b.street_address:
                continue
            # Must be same county+state OR same zip (guaranteed by blocking,
            # but keep the check for safety on edge cases)
            zip_b = (b.zip_code or "").strip()[:5]
            county_b = (b.county or "").strip().lower()
            state_b = (b.state or "").strip().lower()
            same_zip = zip_a and zip_b and zip_a == zip_b
            same_locale = (county_a == county_b and state_a == state_b
                           and county_a and state_a)
            if not (same_zip or same_locale):
                continue
            score = fuzz.token_set_ratio(addr_a, norm_addrs[j])
            if score >= 92:
                # A fuzzy score is ADDRESS evidence only, and it is where the damage was done:
                # '306 Fountain Way' vs '346 Fountain Way' score ~97, '0 SOUTHPORT RD' vs
                # '0 SOUTHPORT RD' (two lots) and 'LOOKOUT RD' vs '328 LOOKOUT RD' score 100.
                # Checked against everything `a` has absorbed so far, so a merged group can
                # never collect two houses one member at a time.
                #
                # The check sits AFTER the score test on purpose. Placed before it, it
                # counted every candidate pair it skipped -- 99,875,342 of them on one
                # board -- which is a true number of comparisons and a useless number to
                # log. Here it counts merges actually prevented.
                if a_id is None:
                    a_id = identity(a)
                b_id = merged_ids[j] or identity(b)
                why = identity_conflict(a_id, b_id, ADDRESS)
                if why is not None:
                    blocked[(2, why)] += 1
                    continue
                a = _merge(a, b)
                a_id = _union(a_id, b_id)
                a_pk = a_id.pk
                a_merged = True
                consumed.add(j)
        final.append(a)
        final_ids.append(a_id if a_merged else None)
    del merged, merged_ids, norm_addrs, row_pks, by_zip, by_locale, consumed

    _p2 = {r: c for (p, r), c in blocked.items() if p == 2}
    if _p2:
        log.info("dedupe.house_number_guard_pass2", blocked_merges=sum(_p2.values()),
                 reasons=_p2,
                 note="fuzzy address match refused: different house numbers or valid parcels, "
                      "or an unnumbered address without an agreeing valid parcel")

    # Pass 3 (2026-06-19): signature union-merge. dedupe_key is parcel>addr>case>
    # url, so the SAME property with a parcel_id on one copy and only a case# on
    # another splits into two keys and never merges (verified leak: ~19 rows).
    # Union any rows sharing a strong signature, then merge each group.
    parent = list(range(len(final)))
    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    # root -> identity of the group, for groups of 2+ rows only (union-find chains through any
    # member, so a union is checked group against group, not just row against row).
    group_ids: dict[int, Identity] = {}

    def _row_id(x: int) -> Identity:
        return final_ids[x] or identity(final[x])

    def _group_id(r: int) -> Identity:
        return group_ids.get(r) or _row_id(r)

    sigmap: dict = {}
    for i, li in enumerate(final):
        for s in _strong_sigs(li):
            if s in sigmap:
                j = sigmap[s]
                ri, rj = _find(i), _find(j)
                if ri == rj:
                    continue
                ev = sig_evidence(s)
                why = (identity_conflict(_row_id(i), _row_id(j), ev)
                       or identity_conflict(_group_id(ri), _group_id(rj), ev))
                if why is not None:
                    blocked[(3, why)] += 1
                    continue
                gid = _union(_group_id(ri), _group_id(rj))
                parent[rj] = ri
                group_ids.pop(rj, None)
                group_ids[ri] = gid
            else:
                sigmap[s] = i
    del group_ids
    _p3 = {r: c for (p, r), c in blocked.items() if p == 3}
    if _p3:
        log.info("dedupe.house_number_guard", blocked_merges=sum(_p3.values()), reasons=_p3,
                 note="rows sharing a signature that are provably different properties "
                      "(different house numbers or valid parcels, or an unnumbered row without "
                      "an agreeing valid parcel); a merge here would delete one of them")
    groups: dict = {}
    for i in range(len(final)):
        groups.setdefault(_find(i), []).append(i)
    out: list[Listing] = []
    # SUSPICIOUS-FUSION REPORT. A wrong signature does not fail, it silently
    # deletes properties -- which is how `scrape_liensnc.py`'s PIN_RE
    # (`(?:pin|tms|parcel|tax\s*map)` with IGNORECASE and no word boundary)
    # turned "Pinehurst" into parcel_id 'ehurst' and fused 122 distinct
    # Pinehurst properties into one row, plus 'eville' (130), 'number' (247).
    # Nothing in any log said so. Union groups that swallow many DISTINCT
    # street addresses are the signature of that class of bug, so they are now
    # reported at WARNING with the shared key named.
    _suspicious: list[tuple[int, int, str]] = []
    for idxs in groups.values():
        m = final[idxs[0]]
        for j in idxs[1:]:
            m = _merge(m, final[j])
        out.append(m)
        if len(idxs) >= 5:
            addrs = {_norm_addr(final[j].street_address) for j in idxs}
            addrs.discard("")
            # Same property from many sources is normal and fine. Many DIFFERENT
            # street addresses under one signature is not.
            if len(addrs) >= 4:
                shared = [s for s, first in sigmap.items()
                          if _find(first) == _find(idxs[0])]
                key = str(sorted(shared, key=lambda x: (x[0], str(x)))[:2])
                _suspicious.append((len(idxs), len(addrs), key))
    if _suspicious:
        _suspicious.sort(reverse=True)
        log.warning("dedupe.suspicious_fusion",
                    groups=len(_suspicious),
                    rows_fused=sum(n - 1 for n, _, _ in _suspicious),
                    worst=[{"rows": n, "distinct_addresses": a, "shared_signature": k}
                           for n, a, k in _suspicious[:10]])
    return out
