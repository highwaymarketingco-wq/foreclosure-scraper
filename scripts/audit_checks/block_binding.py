"""Block-binding invariants (audit 2026-10-09, area block_binding): every raw[...] block on a row
describes THAT row's property, owner or case. docs/audit_2026-10-09/block_binding.md has the
measurements; src/foreclosure_scraper/block_binding.py holds the rules (one verdict per block, the
same code the pipeline's scrub uses) and tax_binding.py the county property-tax half.

One check per block FAMILY (violations: rows where a block of the family is another property's
record by a per-row verdict: foreign_county, other_parcel, other_address, other_person,
fallback_point):
  block-binding-family-gis           gis, gis_attrs_full and the county-layer bags, lrcpwa,
                                     assessor card, CAMA
  block-binding-family-owner-contact owner_mailing, owner_phone, owner_email, skip_trace, sos_agent
  block-binding-family-deed-sale     deed_chain, last_sale, rod, nod
  block-binding-family-photo         images, zillow, vision, assessor_photo, footprint
  block-binding-family-court-lien    court, lien, notice, probate, estate, divorce, bankruptcy blocks
  block-binding-family-person-match  jail, incarceration, BOP, obituary, state tax lien
  block-binding-family-code-site     code enforcement, permits, vacancy, septic, contamination,
                                     tanks, REAC
  block-binding-family-resolution    parcel_from_address / _geo, situs_road_only, parcel_resolution,
                                     resolved_from_name
  block-binding-family-other         every other property or person block
and one per DEFECT CLASS (rows):
  block-binding-a-shared-copy        an identifying block identical on rows of 2+ different
                                     properties (parcel or numbered address) where it does not
                                     bind (its parcel or situs is not the row's, the owner it
                                     names is not the row's owner) and the owners differ
  block-binding-b-foreign-county     a block names another county or state than the row's
  block-binding-c-other-parcel       a block names a parcel id (same numbering system) or a situs
                                     that is not the row's
  block-binding-d-other-person       a person-matched block names someone who shares no name
                                     with the row's owner (roll-aware: block_binding.block_verdict)
  block-binding-e-fused-rows         the row's blocks name two different parcels of one numbering
                                     system (two properties merged into one row), or the row's
                                     own source record names a parcel the row does not carry
  block-binding-e-parcel-two-counties one parcel id (8+ characters) on rows of two counties of one
                                     state
  block-binding-fallback-point       a block looked up by the row's point on a row whose point is a
                                     flagged fallback and which has no parcel or numbered address
County property-tax blocks are excluded (tax_binding's; the tax area has its own checks).

Memory: counters, capped parcel-id samples, and for the two cross-row checks one fixed-size
record per identifying block (fingerprint, property key, flags: 26 bytes; about 1.1 M on 10/7)
and one int pair per parcel id. No names or addresses leave the process.
"""
from __future__ import annotations

import sys
from array import array
from collections import Counter
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from foreclosure_scraper import block_binding as bb  # noqa: E402
from foreclosure_scraper import tax_binding as tb  # noqa: E402
from foreclosure_scraper.verification.core import address_key  # noqa: E402

SAMPLE = 8
#: the CAMA and vision reports live in the lazy-detail sidecar; the runner merges them into raw
DETAIL_KEYS = ("cama", "vision")

FAMILIES: dict[str, frozenset] = {
    "gis": frozenset({"gis", "gis_attrs_full", "gaston_gis", "lincoln_vacant", "transylvania_vacant",
                      "lrcpwa", "assessor_card", "cama", "cama_specs", "condition_cama",
                      "lexington_assessment", "platted_lots", "rollback_exposure", "gis_exempt"}),
    "owner-contact": frozenset({"owner_mailing", "owner_phone", "owner_email", "skip_trace", "sos_agent",
                                "notice_contact", "liensnc_related", "owner_cluster"}),
    "deed-sale": frozenset({"deed_chain", "last_sale", "rod", "nod", "rod_docs", "nc_rod", "rod_chain"}),
    "photo": frozenset({"images", "zillow", "vision", "assessor_photo", "footprint"}),
    "court-lien": frozenset({"nc_ecourts", "court", "court_record", "sc_public_index", "public_notice",
                             "column", "liensnc", "bankruptcy", "courtlistener", "bankruptcy_stay",
                             "divorce", "probate", "sc_probate_notice", "sc_probate_net",
                             "mcdowell_probate", "heir_estate", "heir_candidates", "lis_pendens_resolution",
                             "townnews_legal", "ncnotices", "court_bid", "documents"}),
    "person-match": frozenset({"jail_booking", "jail_booking_new", "incarceration", "incarceration_check",
                               "bop_check", "bop_federal", "obituary", "sc_state_tax_lien",
                               "marriage_license", "resolved_from_name"}),
    "code-site": frozenset({"code_enforcement", "charlotte_code_enforcement", "lincoln_code", "vacancy",
                            "vacant", "septic", "state_contamination", "sc_ust_registry", "epa_frs",
                            "reac", "str_permit_lapsed", "arcgis_distress", "nc_deq_dsca",
                            "sc_des_brownfield"}),
    "resolution": frozenset({"parcel_from_address", "parcel_from_geo", "situs_road_only",
                             "parcel_resolution", "name_resolution"}),
}
_PER_ROW = ("foreign_county", "other_parcel", "other_address", "other_person", "fallback_point")

#: allowed violations once the scrub (block_binding.scrub_unbound_blocks, wired in main.py after the
#: prior merge) has run: replay of the scrub over the 10/7 board left these residuals (see the
#: report); a regression above them fails the gate. A board published before the scrub fails.
MAX = {
    "block-binding-a-shared-copy": 25,
    "block-binding-b-foreign-county": 0,
    "block-binding-c-other-parcel": 0,
    "block-binding-d-other-person": 0,
    "block-binding-fallback-point": 0,
    "block-binding-e-fused-rows": 1400,
    "block-binding-e-parcel-two-counties": 400,
    "block-binding-e-row-county-vs-source": 20,
}


class _RowCache:
    """block_binding.row_verdicts() once per row for all of this module's checks (they are fed the
    same row object one after another)."""

    def __init__(self) -> None:
        # the cached row itself is held, so its id can never be reused by the next row while cached
        self._row: Any = None
        self.verdicts: list = []

    def get(self, row: dict) -> list:
        if row is not self._row:
            self._row = row
            try:
                self.verdicts = bb.row_verdicts(row, None)
            except Exception:  # noqa: BLE001 - an unreadable row is not evidence
                self.verdicts = []
        return self.verdicts


_CACHE = _RowCache()


def _county(row: dict) -> str:
    return f"{row.get('state') or ''}:{tb.county_key(row.get('county'))}"


class _Check:
    name = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.by = Counter()
        self.samples: list = []

    def _bad(self, row: dict, what: str) -> None:
        self.violations += 1
        self.by[what] += 1
        if len(self.samples) < SAMPLE:
            self.samples.append(f"{_county(row)}:{row.get('parcel_id') or '-'}:{what}")

    def finish(self) -> dict:
        mx = MAX.get(self.name, 0)
        top = ", ".join(f"{k} {v}" for k, v in self.by.most_common(6))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": mx, "ok": self.violations <= mx,
                "detail": f"{top}; e.g. {'; '.join(self.samples)}" if self.violations else "none"}


class FamilyCheck(_Check):
    def __init__(self, family: str, blocks: frozenset | None) -> None:
        super().__init__()
        self.name = f"block-binding-family-{family}"
        self.blocks = blocks

    def _mine(self, name: str) -> bool:
        if self.blocks is not None:
            return name in self.blocks
        return not any(name in b for b in FAMILIES.values())

    def feed(self, row: dict) -> None:
        vs = [(n, v) for n, v, _fp, _named in _CACHE.get(row) if self._mine(n)]
        if not vs:
            return
        self.checked += 1
        bad = [f"{n}:{v}" for n, v in vs if v in _PER_ROW]
        if bad:
            self._bad(row, bad[0])
            for b in bad[1:]:
                self.by[b] += 1


class VerdictCheck(_Check):
    """Rows where some checked block has one of `verdicts`."""

    def __init__(self, name: str, verdicts: tuple) -> None:
        super().__init__()
        self.name = name
        self.verdicts = verdicts

    def feed(self, row: dict) -> None:
        vs = _CACHE.get(row)
        if not vs:
            return
        self.checked += 1
        bad = [n for n, v, _fp, _named in vs if v in self.verdicts]
        if bad:
            self._bad(row, bad[0])


class SharedCopy(_Check):
    """block-binding-a-shared-copy: the scrub's own shared test (block_binding.shared_unbound) over
    the whole board, in fixed-width arrays: per identifying block (fingerprint, row number, bound
    flag, names-an-owner flag) and per row (up to 3 property-key hashes, up to 3 owner-token
    hashes). A copy the scrub would remove is a violation."""
    name = "block-binding-a-shared-copy"
    W = 6

    def __init__(self) -> None:
        super().__init__()
        self.fp = array("q")
        self.row = array("i")
        self.flag = array("b")    # 1 bound / own source, 0 not
        self.named = array("b")
        self.keys = array("q")    # W per row, 0 padded
        self.toks = array("q")    # W per row, 0 padded
        self.where: dict[int, str] = {}
        self.n = 0

    def _pad(self, vals) -> list:
        vals = [v or 1 for v in list(vals)[: self.W]]
        return vals + [0] * (self.W - len(vals))

    def feed(self, row: dict) -> None:
        i = self.n
        self.n += 1
        vs = [(v, fp, named) for _n, v, fp, named in _CACHE.get(row) if fp is not None]
        # a deterministic subset when a row has more than W keys or tokens (hash() of a str is
        # salted per process, so choose by the key's text, then hash)
        try:
            keys = [hash(k) for k in sorted(tb.property_keys(row, i), key=repr)]
        except Exception:  # noqa: BLE001
            keys = [hash(("r", i))]
        self.keys.extend(self._pad(keys))
        toks = sorted(bb.name_tokens(row.get("owner_name")), key=lambda t: (-len(t), t))
        self.toks.extend(self._pad(hash(t) for t in toks))
        if not vs:
            return
        self.checked += 1
        for v, fp, named in vs:
            self.fp.append(fp)
            self.row.append(i)
            self.flag.append(1 if v in ("bound", "own_source") else 0)
            self.named.append(1 if named else 0)
        if len(self.where) < 50_000:
            self.where[i] = f"{_county(row)}:{row.get('parcel_id') or '-'}"

    def finish(self) -> dict:
        import numpy as np
        if len(self.fp):
            F = np.frombuffer(self.fp, dtype=np.int64)
            R = np.frombuffer(self.row, dtype=np.int32)
            B = np.frombuffer(self.flag, dtype=np.int8)
            N = np.frombuffer(self.named, dtype=np.int8)
            K = np.frombuffer(self.keys, dtype=np.int64).reshape(-1, self.W)
            T = np.frombuffer(self.toks, dtype=np.int64).reshape(-1, self.W)
            order = np.argsort(F, kind="stable")
            F, R, B, N = F[order], R[order], B[order], N[order]
            brk = np.flatnonzero(np.diff(F) != 0) + 1
            starts = np.concatenate(([0], brk))
            ends = np.concatenate((brk, [len(F)]))
            for s, e in zip(starts, ends):
                if e - s < 2:
                    continue
                members = []
                for j in range(s, e):
                    r = int(R[j])
                    members.append((r, "bound" if B[j] else "unknown",
                                    frozenset(int(k) for k in K[r] if k),
                                    frozenset(int(t) for t in T[r] if t)))
                bad = bb.shared_unbound(members, bool(N[s]))
                for r in bad:
                    self.violations += 1
                    self.by["copies"] += 1
                    if len(self.samples) < SAMPLE and r in self.where:
                        self.samples.append(self.where[r])
        return super().finish()


class FusedRows(_Check):
    name = "block-binding-e-fused-rows"

    def feed(self, row: dict) -> None:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        if not raw:
            return
        self.checked += 1
        distinct: list[str] = []
        for name, blk in raw.items():
            # county property-tax blocks are tax_binding's (its scrub removes the other parcels')
            if not isinstance(blk, dict) or bb.block_kind(name) != "property" or tb.is_property_tax_block(name, blk):
                continue
            for x in bb.probe(name, blk)["ids"]:
                cx = tb.canon_id(x)
                if not any(tb.same_id(cx, d) for d in distinct):
                    distinct.append(cx)
        for a in range(len(distinct)):
            for b in range(a + 1, len(distinct)):
                if tb.comparable(distinct[a], distinct[b]) and not tb.same_id(distinct[a], distinct[b]):
                    self._bad(row, "blocks_name_two_parcels")
                    return
        # the row's own source record names a parcel the row does not carry
        for name, blk in raw.items():
            if isinstance(blk, dict) and bb.own_source_block(row, name, blk) and not tb.is_property_tax_block(name, blk):
                p = bb.probe(name, blk)
                if p["ids"] and tb.row_ids(row) and tb.id_relation(p["ids"], tb.row_ids(row)) == "different":
                    self._bad(row, "own_source_names_other_parcel")
                    return


class ParcelTwoCounties(_Check):
    name = "block-binding-e-parcel-two-counties"

    def __init__(self) -> None:
        super().__init__()
        self.seen: dict[int, int] = {}
        self.multi: set[int] = set()

    def feed(self, row: dict) -> None:
        pid = row.get("parcel_id")
        if not pid or not tb.usable_id(tb.norm_id(pid)):
            return
        c = tb.canon_id(pid)
        if len(c) < 8:
            return
        self.checked += 1
        k = hash((row.get("state"), c))
        cty = hash(tb.county_key(row.get("county")))
        prev = self.seen.setdefault(k, cty)
        if prev != cty and k not in self.multi:
            self.multi.add(k)
            self._bad(row, "parcel_in_two_counties")


def _county_sets() -> dict:
    from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES
    return {"NC": {tb.county_key(c) for c in NC_COUNTIES}, "SC": {tb.county_key(c) for c in SC_COUNTIES}}


def county_of_slug(src: Any, state: Any, sets: dict) -> str | None:
    """The county a county-specific source slug names ('counties_nc.lincoln_vacant',
    'counties_generic.arcgis_distress.lincoln_code_violations'), or None."""
    import re
    parts = re.split(r"[._]", str(src or "").lower())
    names = sets.get(str(state or "").upper(), set())
    for i in range(len(parts)):
        for j in (3, 2, 1):
            cand = "".join(parts[i:i + j])
            if len(cand) >= 4 and cand in names:
                return cand
    return None


class RowCountyVsSource(_Check):
    """block-binding-e-row-county-vs-source: a row whose own county-specific source names another
    county than the row carries (a Lincoln code case published as a Buncombe lead): every block on
    it is judged against the wrong county."""
    name = "block-binding-e-row-county-vs-source"

    def __init__(self) -> None:
        super().__init__()
        self.sets = _county_sets()

    def feed(self, row: dict) -> None:
        sc = county_of_slug(row.get("source"), row.get("state"), self.sets)
        if not sc:
            return
        self.checked += 1
        rc = tb.county_key(row.get("county"))
        if rc and not tb.same_county(sc, rc):
            self._bad(row, f"{sc}->{rc}")


def make_checks() -> list:
    checks: list = [FamilyCheck(f, b) for f, b in FAMILIES.items()]
    checks.append(FamilyCheck("other", None))
    checks += [
        SharedCopy(),
        VerdictCheck("block-binding-b-foreign-county", ("foreign_county",)),
        VerdictCheck("block-binding-c-other-parcel", ("other_parcel", "other_address")),
        VerdictCheck("block-binding-d-other-person", ("other_person",)),
        VerdictCheck("block-binding-fallback-point", ("fallback_point",)),
        FusedRows(),
        ParcelTwoCounties(),
        RowCountyVsSource(),
    ]
    for c in checks:
        if c.name.startswith("block-binding-family-"):
            MAX.setdefault(c.name, 0)
    return checks
