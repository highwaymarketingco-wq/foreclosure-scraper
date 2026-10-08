"""Parcel-id aliases: one property, a county's SHORT id and its 10-digit PIN, one row key.

WHY (owner decision 2026-10-07). Two sources published a short county id as parcel_id:

  counties_nc.lincoln_vacant   PARCELID, the county's 5-6 character internal id
  counties_nc.rutherford_tax   the 6-7 digit county Parcel_Number from the TR-452 roll

validation.py nulls an id under 7 characters as too weak to be unique, so ~15.9k Lincoln and
~2.6k Rutherford rows published with no parcel at all, while the 10-digit NC PIN every other NC
source keys on was available (Lincoln: on the same layer row; Rutherford: on the county parcel
layer, Parcel_Number -> PIN). Both scrapers now publish the PIN as parcel_id and keep the short
id in their raw block. Switching an identity is only safe when the board merge and dedupe treat
the old short-id row and the new PIN row as ONE property; otherwise board_persist refuses the fold
("two different ids from one source in one county") and every row is published twice.

HOW. The alias TABLE is built from the rows that carry both ids (the fresh scrape of an alias
source: parcel_id = PIN, raw[block][short_key] = short id) and is keyed by (state, county,
normalized short id) -> PIN. It is applied:

  * in dedupe.dedupe(): any row in that county whose parcel_id is a short id in the table (another
    Rutherford source using the same county Parcel_Number) takes the PIN, so cross-source parcel
    matching keeps working after the switch (raw['parcel_id_alias'] records the original);
  * in board_persist.merge_prior_board(): a PRIOR board row whose parcel_id, or whose nulled short
    id (raw['parcel_id_nulled'] / the source block), is in the table is matched under the PIN, and
    its old key is recorded as folded so the GRANDFATHER snapshot does not restore it a second
    time. The reverse case (the fresh scrape could not get the PIN and fell back to the short id,
    the prior row has the PIN) is matched under the short id the prior row also carries.

A short id that maps to two different PINs in one county is ambiguous and left out of the table.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

#: Sources whose rows carry BOTH ids: parcel_id is the PIN, raw[block][short_key] the short id.
ALIAS_SOURCES: dict[str, tuple[str, str]] = {
    "counties_nc.lincoln_vacant": ("lincoln_vacant", "PARCELID"),
    "counties_nc.rutherford_tax": ("rutherford_tax", "parcel"),
    # 2026-10-09 (audit source_completeness): the Sturgis/Wildfire roll's 6-7 digit Parcel_Number
    # (896 ids nulled by validation in the 10/8 run, 893 with a PIN); the scraper publishes the PIN
    # only once this entry exists (rutherford_wildfire_tax._pins_enabled).
    "counties_nc.rutherford_wildfire_tax": ("rutherford_wildfire", "parcel"),
}

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _norm(pid: Any) -> str:
    return _NON_ALNUM.sub("", str(pid or "").lower())


def _cty(county: Any) -> str:
    return str(county or "").strip().lower()


def _get(row: Any, name: str):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def short_id_of(row: Any) -> Optional[str]:
    """The short id an alias source's row carries in its own raw block, or None."""
    spec = ALIAS_SOURCES.get(str(_get(row, "source") or ""))
    raw = _get(row, "raw")
    if not spec or not isinstance(raw, dict):
        return None
    blk = raw.get(spec[0])
    v = blk.get(spec[1]) if isinstance(blk, dict) else None
    return str(v).strip() or None if v not in (None, "") else None


_NC_PIN = re.compile(r"^\d{10}$")


def is_pin(pid: Any) -> bool:
    """An NC 10-digit PIN (punctuation ignored): the only id the table may map a short id TO.
    On the 10/8 checkpoint carried Rutherford rows whose parcel_id was ANOTHER 7-digit county
    number entered the table as 'PINs', and 53 rows were given a different property's id
    (audit 2026-10-09, additions_verify)."""
    return bool(_NC_PIN.match(_norm(pid)))


def build(rows: Iterable[Any]) -> dict[tuple[str, str, str], str]:
    """{(state, county, normalized short id): PIN} from alias-source rows carrying both ids.
    A row whose parcel_id is not a 10-digit PIN (a carried row that still holds a short id of
    its own) adds nothing."""
    table: dict[tuple[str, str, str], str] = {}
    bad: set[tuple[str, str, str]] = set()
    for row in rows:
        short = short_id_of(row)
        long_ = str(_get(row, "parcel_id") or "").strip()
        if not short or not long_ or _norm(short) == _norm(long_) or not is_pin(long_):
            continue
        key = (str(_get(row, "state") or ""), _cty(_get(row, "county")), _norm(short))
        if key in table and _norm(table[key]) != _norm(long_):
            bad.add(key)
        table.setdefault(key, long_)
    for key in bad:
        table.pop(key, None)
    return table


def fresh_short_keys(rows: Iterable[Any]) -> set[tuple[str, str, str, str]]:
    """{(source, state, county, normalized short id)} of alias-source rows whose parcel_id IS the
    short id (the PIN could not be read this run): the reverse match in canonical_prior()."""
    out = set()
    for row in rows:
        short = short_id_of(row)
        pid = _get(row, "parcel_id")
        if short and pid and _norm(short) == _norm(pid):
            out.add((str(_get(row, "source") or ""), str(_get(row, "state") or ""),
                     _cty(_get(row, "county")), _norm(short)))
    return out


def lookup(table: dict, state: Any, county: Any, pid: Any) -> Optional[str]:
    if not table or not pid:
        return None
    return table.get((str(state or ""), _cty(county), _norm(pid)))


def apply(rows: Iterable[Any], table: dict) -> int:
    """Give every Listing whose parcel_id is a short id in `table` the PIN (in place). Returns
    how many changed. The original id is kept in raw['parcel_id_alias']."""
    if not table:
        return 0
    n = 0
    for li in rows:
        pid = getattr(li, "parcel_id", None)
        long_ = lookup(table, getattr(li, "state", None), getattr(li, "county", None), pid)
        if not long_ or _norm(long_) == _norm(pid):
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("parcel_id_alias", {"short": str(pid), "long": long_})
        li.parcel_id = long_
        n += 1
    return n


def canonical_prior(rec: dict, table: dict, short_keys: set, nulled_id: Optional[str]):
    """A prior board row dict under the id the fresh scrape uses for the same property.

    Returns (rec, how): `how` is None when nothing changed, else 'pin' (the prior's short id, or
    nulled short id, maps to a PIN in `table`) or 'short' (the prior carries a PIN and its source's
    short id, and the fresh scrape published that short id this run). The input dict is never
    modified; a changed row is a shallow copy with a new parcel_id (and no parcel_id_nulled)."""
    if not isinstance(rec, dict):
        return rec, None
    state, county, src = rec.get("state"), rec.get("county"), str(rec.get("source") or "")
    pid = rec.get("parcel_id") or nulled_id
    long_ = lookup(table, state, county, pid)
    new_pid, how = None, None
    if long_ and _norm(long_) != _norm(rec.get("parcel_id")):
        new_pid, how = long_, "pin"
    else:
        short = short_id_of(rec)
        if (short and rec.get("parcel_id") and _norm(short) != _norm(rec.get("parcel_id"))
                and (src, str(state or ""), _cty(county), _norm(short)) in short_keys):
            new_pid, how = short, "short"
    if not new_pid:
        return rec, None
    out = dict(rec)
    out["parcel_id"] = new_pid
    raw = rec.get("raw")
    if isinstance(raw, dict) and "parcel_id_nulled" in raw:
        raw = dict(raw)
        raw.pop("parcel_id_nulled", None)
        out["raw"] = raw
    return out, how
