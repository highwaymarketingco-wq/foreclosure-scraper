"""Condominium units in Buncombe County's parcel layer: the id a lead is keyed by, and the one-time
migration of the rows the board holds under the building's pin.

THE FACT (live 2026-10-06, gis.buncombecounty.org property_bc_dis/MapServer/1). Every parcel carries
`pin` (10 digits) and `pinext` (5 characters); `pinnum` = pin + pinext. A plain parcel has pinext
'00000'. A condominium building's units all share the building's `pin` and each has its own pinext
('C0102', 'CA102', 'C00H5'): pin 9627023924 is the common area ('00000') plus 225 units, 9658735582
is 202 parcels. 5,299 of the layer's parcels have a pinext other than '00000'.

THE DEFECT. counties_nc.buncombe_elderly wrote parcel_id = `pin`, so every elderly-exempt unit of a
building was keyed to ONE property: Listing.dedupe_key() and verification.core.row_key() read them as
one row, anything padding the pin to '<pin>00000' (tax_lien_buncombe.pin_of,
enrichment_assessor_photo.buncombe_pin_variants) looked up the common area, and the parcel cache
answered with the unit owners' association. Measured on the 10/5 board: 100 Buncombe rows of all
sources carry a 10-digit parcel_id whose pin covers more than one layer parcel; 91 are
buncombe_elderly rows (33 buildings), the other 9 are building-level rows of three other sources.
The other 5,809 rows with a 10-digit Buncombe parcel_id are on single-parcel pins.

THE FIX AT THE SOURCE. A unit is keyed by its own pinnum (board_parcel_id); every other parcel keeps
the pin, because a '<pin>00000' pinnum has the SAME dedupe key (models._normalize_parcel strips a
pure-zero pad) and the same string the operator's dashboard keys its saved notes by
(docs/dashboard.js crmKey: 'parcel:<state>:<parcel_id>'). Only the units change key.

THE MIGRATION (what this module is for). merge_prior_board matches a fresh row to its published row
by dedupe_key. A unit's key is new, so without more the published row (key = the bare pin) would not
match: the run would add the unit's row AND age the old one as presumed withdrawn, dropping the
carried enrichment (owner phone, skip trace, images, ...). match_units() pairs a published bare-pin
row with the unit that is the same lead: the owner (name_normalize.core_tokens, tolerating a
life-estate '(LE)' marker or an added co-owner), the unit's own situs breaking a tie. On the real
10/5 rows against the live layer: 90 of 91 rows pair on an exact owner, the 91st on a life-estate
marker the county added on 2026-10-01. A row that pairs with no unit is left to the ordinary aging
(its owner no longer holds the exemption on a unit of that building).
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional, Sequence

#: pinnum = 10-digit pin + 5-character pinext
_PINNUM_RE = re.compile(r"^(\d{10})([0-9A-Z]{5})$")
_PLAIN_EXT = "00000"

#: name tokens that say how an owner holds title, not who the owner is ('DEANNA HOLCOMBE (LE)' on
#: the board, 'HOLCOMBE DEANNA' in the county layer after the 2026-10-01 deed)
_TITLE_TOKENS = frozenset({"LE", "LF", "ETAL", "EST", "ESTATE", "HEIRS", "HEIR"})


def _alnum(v) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(v or "")).upper()


def unit_parts(parcel_id) -> Optional[tuple[str, str]]:
    """(pin, pinext) when `parcel_id` is the pinnum of a unit, i.e. its pinext is not '00000'
    ('9627023924C0102' -> ('9627023924', 'C0102')); None for a bare pin, a '<pin>00000' pinnum or
    anything that is not 15 alphanumerics starting with 10 digits."""
    m = _PINNUM_RE.match(_alnum(parcel_id))
    if not m or m.group(2) == _PLAIN_EXT:
        return None
    return m.group(1), m.group(2)


def board_parcel_id(pin, pinnum) -> str:
    """The parcel_id a lead built from a layer row carries: the unit's own pinnum for a
    condominium unit (so each unit is its own property), the pin for every other parcel (a
    '<pin>00000' pinnum is the same dedupe key and the same string the board has always held)."""
    pin_s = str(pin or "").strip()
    pn = _alnum(pinnum)
    parts = unit_parts(pn)
    if parts and (not pin_s or parts[0] == pin_s):
        return pn
    return pin_s


def _is_buncombe(state, county) -> bool:
    return (str(state or "").strip().upper() == "NC"
            and str(county or "").replace("County", "").strip().lower() == "buncombe")


def unit_pin_key(state, county, parcel_id) -> Optional[tuple[str, str]]:
    """('buncombe', pin) for a Buncombe NC row keyed by a unit's pinnum, else None."""
    if not _is_buncombe(state, county):
        return None
    parts = unit_parts(parcel_id)
    return ("buncombe", parts[0]) if parts else None


def bare_pin_key(state, county, parcel_id) -> Optional[tuple[str, str]]:
    """('buncombe', pin) for a Buncombe NC row keyed by a bare 10-digit pin (the form the elderly
    scraper wrote for every unit), else None. A '<pin>00000' pinnum is the same key
    (models._normalize_parcel) and counts as bare; a unit's pinnum does not."""
    if not _is_buncombe(state, county):
        return None
    s = _alnum(parcel_id)
    if re.fullmatch(r"\d{10}", s) or re.fullmatch(r"\d{10}0{5}", s):
        return ("buncombe", s[:10])
    return None


# ---------------------------------------------------------------------------------- owner / situs

def _tokens(owner) -> set[str]:
    from .name_normalize import core_tokens
    return {t for t in core_tokens(owner) if t not in _TITLE_TOKENS}


def owner_tier(a, b) -> int:
    """How surely two owner strings of one layer are the same lead: 3 = the same identity tokens
    (any order), 2 = one holds the other's tokens and they share at least a surname and a first
    name (a co-owner added, a title marker), 0 = otherwise (including either side empty)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0
    if ta == tb:
        return 3
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return 2 if len(small) >= 2 and small <= big else 0


def _house_no(addr) -> str:
    m = re.match(r"\s*(\d+)\b", str(addr or ""))
    return m.group(1).lstrip("0") if m else ""


def same_situs(a, b) -> bool:
    """Both carry a real house number and the same normalized street address (units included)."""
    from .models import _normalize_addr
    if not a or not b or not _house_no(a) or _house_no(a) != _house_no(b):
        return False
    return _normalize_addr(str(a)) == _normalize_addr(str(b))


class View(NamedTuple):
    """What the matcher compares: a row's owner and street, whichever shape the row has."""
    owner: Optional[str]
    street: Optional[str]


def match_units(priors: Sequence[View], units: Sequence[View]) -> list[Optional[int]]:
    """For each published bare-pin row, the index of the unit (of the same building) that is the
    same lead, or None. A pair needs an owner tier of 2 or more; the best (owner tier, same situs)
    wins, and a tie for the best leaves the row unmatched (it ages as before). Several rows may
    take one unit (a published duplicate of one lead folds in with it, as merge_prior_board
    already folds every prior row that matches one fresh row)."""
    out: list[Optional[int]] = []
    for p in priors:
        best: tuple = ()
        winners: list[int] = []
        for j, u in enumerate(units):
            tier = owner_tier(p.owner, u.owner)
            if tier < 2:
                continue
            score = (tier, same_situs(p.street, u.street))
            if score > best:
                best, winners = score, [j]
            elif score == best:
                winners.append(j)
        out.append(winners[0] if len(winners) == 1 else None)
    return out
