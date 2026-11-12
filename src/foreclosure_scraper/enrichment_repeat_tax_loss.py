"""Repeat tax/foreclosure-sale loser — owner who lost a parcel before and
still holds another one now.

Direct implementation of Dirty Deeds Tier A #34 (docs/dirty_deeds_synthesis_
2026-09-10.md): "Match tax-deed grantors back to the current owner index. A
proven non-payer with proven capitulation. Ep 032's $350k-spread seller had
already lost one inherited property; ep 034's decedent lost parcels in 2016
and 'still got like three properties in her name.'" Rated free, easy build.

Built on top of enrichment_deed_chain.py's distress_transfers, which as of
2026-09-17 recognizes tax-sale/foreclosure-sale conveyances (TAX DEED,
SHERIFF'S DEED, TRUSTEE'S DEED/SUBSTITUTE TRUSTEE, MASTER IN EQUITY,
CLERK'S DEED) as a distress-type class -- this enricher is the cross-parcel
JOIN the synthesis says is the only missing piece, not a new scraper.

TWO PASSES, same shape as enrichment_owner_cluster.py:
  1. Index the parties who LOST a parcel to a forced sale, by (surname, given,
     county, state), the same scoping owner_cluster.py uses and for the same
     reason: a bare name match nationwide is noise, county+state keeps it
     plausible. Two sources feed the index:
       a. every listing's deed_chain distress_transfers (a loss on a parcel that
          is on the board), and
       b. the deed-index sidecar (data/deed_index.db, built by
          scripts/backfill_deed_index.py from a county-wide register-of-deeds
          sweep). This is the source that matters: a county sweep finds losers on
          parcels that were never board leads, which (a) can never see.
  2. For every CURRENT listing on the board, check whether its owner_name
     matches a name in that loser index (same county/state) on a DIFFERENT
     property than the one they lost. A match means this owner has already
     lost real estate to a tax/foreclosure sale and is still holding
     property today -- a proven non-payer, proven capitulation signal.

Self-match guard: a listing whose OWN deed_chain shows itself being
reacquired via tax deed by the same person who lost it (a redemption/
buy-back) must not flag as "repeat loser elsewhere" -- excluded by property
key, not just row identity.

FIRST LIVE RUN 2026-09-17: losses_indexed=0, tagged_rows=0. Traced across
all 5 of deed_chain's sources (1,069 distress_transfers total): 812 have no
doc_type at all (flagged purely by a $0/$1/$10/$100 sale price); the
doc_type values that DO exist are GIS/CAMA sale-VALIDITY codes ("IMPROVED",
"VACANT", "0: VALID ARMS-LENGTH", "DEED, QUIT CLAIM") from gis.last_sale/
assessor_card/county_sales, not real ROD deed-instrument classifications;
and rod_docs (162 rows, source=*_dot_ocr) only covers Deed-of-Trust/
Mortgage OCR, never sale-conveyance types. No board source records a forced-
sale deed, so the signal stayed at 0 until a deed-index sweep exists.

DEFECTS FIXED 2026-09-20 (docs/deed_index_scoping_2026-09-20.md, F1 to F5):
  * F1, F2: a loss deed is recognized by rod.inst_class.classify_instrument, not
    by substring lists. The vendor codes TR/D, COM/D and SHF/D, the spelling
    TRUSTEES DEED (no apostrophe) and COMMISSIONER'S DEED all matched nothing
    here, and normalize_doc_type had turned TAX DEED into a bare DEED.
  * F3: the loser's name comes from the transfer itself. The old fallback to
    summary.prior_owner is gone: it is the grantor of the newest transfer that
    has one, rarely the person who lost THAT parcel.
  * F5: pass 1 also reads the deed-index sidecar.
  * F4 (rod/cchs.py _SOLD_TYPES) is fixed in the adapter, not here.

KNOWN LIMIT. The join is a name string inside one county, and common surnames
collide. Expect false positives to dominate until a second key (mailing address
or an adjacent parcel) is added. The self-match guard for a sidecar loss compares
the parcel key and the deed's book/page against the listing's own chain. The
vendor's parcel key (CCHS serves values like 1-3405501) has not been mapped to the
board's parcel_id, so until it is, the book/page test is the one that can decide.

No network. Reads the board rows in hand plus one local SQLite file.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

import structlog

from .deed_index import Party, derive_loss, load_loss_rows
from .models import Listing
from .name_normalize import is_entity, person_orderings
from .rod.inst_class import LOSS_CLASSES, classify_instrument

log = structlog.get_logger()

_EVIDENCE_MAX = 5


def _surname_first_reading(owner_name: str):
    """Board owner_name is SURNAME-FIRST (see enrichment_owner_cluster.py's
    identical helper, live-verified against real board data)."""
    orderings = person_orderings(owner_name)
    if not orderings:
        return None
    return orderings[1] if len(orderings) > 1 else orderings[0]


def _name_key(owner_name: str) -> tuple[str, str] | None:
    if not owner_name or is_entity(owner_name):
        return None
    person = _surname_first_reading(owner_name)
    if person is None or not person.given:
        return None
    return (person.surname, person.given[0])


def _property_key(li: Listing) -> str:
    if li.parcel_id:
        return f"pid:{li.parcel_id.strip().upper()}"
    if li.street_address:
        return f"addr:{li.street_address.strip().upper()}"
    return f"src:{li.source_url}"


def _county_key(county: str) -> str:
    return county.replace(" County", "").strip().upper()


def _pid_norm(pid) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(pid or "").upper()).lstrip("0")


def _bp_norm(book, page) -> str | None:
    b, p = str(book or "").strip().lstrip("0"), str(page or "").strip().lstrip("0")
    return f"{b}/{p}" if b and p else None


def _listing_book_pages(li: Listing) -> set[str]:
    """Book/page of every deed on this listing's own chain. A loss whose book/page
    is among them is a loss of THIS property, whatever the parcel keys say."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    dc = raw.get("deed_chain")
    out: set[str] = set()
    for t in (dc.get("transfers") or []) if isinstance(dc, dict) else []:
        bp = _bp_norm(t.get("book"), t.get("page")) if isinstance(t, dict) else None
        if bp:
            out.add(bp)
    return out


def _same_property(property_key: str, pid: str, book_pages: set[str], loss: dict) -> bool:
    if loss["lost_property_key"] == property_key:
        return True
    if pid and loss.get("lost_pid_norm") and pid == loss["lost_pid_norm"]:
        return True
    bp = _bp_norm(loss.get("book"), loss.get("page"))
    return bool(bp and bp in book_pages)


def _loss_identity(loss: dict) -> tuple:
    bp = _bp_norm(loss.get("book"), loss.get("page"))
    if bp:
        return ("bp", loss.get("date"), bp)
    return ("doc", loss.get("date"), loss.get("doc_type"), loss["lost_property_key"])


def count_candidate_owners(board_rows: Iterable[dict], deed_index_rows: list[dict]) -> dict:
    """Read-only preview for a streamed board (board_stream.iter_board_rows dicts):
    how many rows carry an owner name that equals an indexed loser in the same
    county and state. An upper bound, since the self-match guard is not applied.
    Lets a caller skip the heavy board load when nothing can match."""
    keys: set[tuple] = set()
    for row in deed_index_rows:
        county, state = _county_key(row.get("county") or ""), (row.get("state") or "").upper()
        for name in row.get("loser_names") or []:
            k = _name_key(name)
            if k:
                keys.add((k[0], k[1], county, state))
    scanned = candidates = 0
    for rec in board_rows:
        scanned += 1
        if not keys or not rec.get("county") or not rec.get("state"):
            continue
        k = _name_key(rec.get("owner_name") or "")
        if k and (k[0], k[1], _county_key(rec["county"]), rec["state"].upper()) in keys:
            candidates += 1
    return {"rows_scanned": scanned, "loser_keys": len(keys), "candidate_rows": candidates}


def enrich_repeat_tax_loss(listings: Iterable[Listing],
                           deed_index_rows: list[dict] | None = None) -> dict:
    """Stamp raw['repeat_tax_loss'] (and the matched instruments in
    raw['deed_index']) on any listing whose current owner has a tax-sale or
    foreclosure-sale loss on a DIFFERENT property. Never drops a lead; additive
    only.

    deed_index_rows are loss instruments from the sidecar (deed_index.load_loss_rows).
    None reads the default sidecar, [] means none; a missing sidecar is [], so the
    enricher behaves as before until the first sweep."""
    listings = list(listings)
    if deed_index_rows is None:
        deed_index_rows = load_loss_rows()
    stats = {"losses_indexed": 0, "tagged_rows": 0, "index_rows": len(deed_index_rows)}

    # Pass 1: index loser names by (surname, given, county, state) -> the
    # property they lost + when + how.
    losers: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    seen: set[tuple] = set()

    def add(name: str, county: str, state: str, loss: dict) -> None:
        key = _name_key(name)
        if key is None:
            return
        ident = (key, county, state, _loss_identity(loss))
        if ident in seen:                 # the same deed reached us by two routes
            return
        seen.add(ident)
        losers[(key[0], key[1], county, state)].append(loss)
        stats["losses_indexed"] += 1

    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        dc = raw.get("deed_chain")
        if not isinstance(dc, dict):
            continue
        transfers = (dc.get("summary") or {}).get("distress_transfers") or []
        if not transfers:
            continue
        if not li.county or not li.state:
            continue
        county = _county_key(li.county)
        state = li.state.upper()
        for t in transfers:
            if not isinstance(t, dict):
                continue
            inst_class = t.get("inst_class") or classify_instrument(t.get("doc_type"))
            if inst_class not in LOSS_CLASSES:
                continue
            # Only the transfer's OWN grantors. Falling back to summary.prior_owner
            # named the grantor of the newest transfer that had one, which is
            # rarely the person who lost THIS parcel.
            grantors = t.get("grantors") or ([t["grantor"]] if t.get("grantor") else [])
            _kind, names = derive_loss(inst_class, [Party(str(g)) for g in grantors],
                                       str(t.get("description") or ""))
            for name in names:
                add(name, county, state, {
                    "date": t.get("date"),
                    "doc_type": t.get("doc_type"),
                    "inst_class": inst_class,
                    "book": t.get("book"),
                    "page": t.get("page"),
                    "lost_property_key": _property_key(li),
                    "lost_pid_norm": _pid_norm(li.parcel_id),
                    "lost_parcel_id": li.parcel_id,
                    "lost_source": li.source,
                })

    for row in deed_index_rows:
        if not row.get("county") or not row.get("state"):
            continue
        county = _county_key(row["county"])
        state = row["state"].upper()
        pid = _pid_norm(row.get("parcel_id"))
        for name in row.get("loser_names") or []:
            add(name, county, state, {
                "date": row.get("recorded_date"),
                "doc_type": row.get("inst_code") or row.get("inst_class"),
                "inst_class": row.get("inst_class"),
                "book": row.get("book"),
                "page": row.get("page"),
                "lost_property_key": f"pid:{pid}" if pid else f"doc:{row.get('doc_key')}",
                "lost_pid_norm": pid,
                "lost_parcel_id": row.get("parcel_id"),
                "lost_source": "deed_index",
            })

    if not losers:
        return stats

    # Pass 2: match every CURRENT owner against the loser index, excluding
    # the property they lost (a redemption/buy-back of the same parcel is
    # not "still holds ANOTHER property").
    for li in listings:
        if not li.owner_name or not li.county or not li.state:
            continue
        key = _name_key(li.owner_name)
        if key is None:
            continue
        county = _county_key(li.county)
        state = li.state.upper()
        candidates = losers.get((key[0], key[1], county, state))
        if not candidates:
            continue
        this_property = _property_key(li)
        this_pid = _pid_norm(li.parcel_id)
        book_pages = _listing_book_pages(li)
        other_losses = [c for c in candidates
                        if not _same_property(this_property, this_pid, book_pages, c)]
        if not other_losses:
            continue
        other_losses.sort(key=lambda c: c.get("date") or "", reverse=True)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["repeat_tax_loss"] = {
            "prior_losses": len(other_losses),
            "most_recent_loss_date": other_losses[0]["date"],
            "most_recent_loss_doc_type": other_losses[0]["doc_type"],
            "most_recent_loss_class": other_losses[0].get("inst_class"),
            "county": county,
            "state": state,
        }
        # The instruments behind the tag: what a caller checks at the recorder.
        li.raw["deed_index"] = [
            {"inst_class": c.get("inst_class"), "date": c.get("date"), "book": c.get("book"),
             "page": c.get("page"), "role": "grantor", "county": county}
            for c in other_losses[:_EVIDENCE_MAX]
        ]
        stats["tagged_rows"] += 1

    if stats["tagged_rows"]:
        log.info("repeat_tax_loss.done", **stats)
    return stats
