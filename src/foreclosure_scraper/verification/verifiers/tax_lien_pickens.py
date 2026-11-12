"""tax_lien, Pickens County SC: is this parcel on the county's CURRENT published delinquent-tax list?

The fourth tax_lien adapter (same SIGNAL, GOVERNS and verdict meanings as tax_lien_buncombe,
tax_lien_ptscloud and tax_lien_qpaybill), for the one SC footprint county with no per-parcel bill
lookup a verifier may read.

WHY A LIST AND NOT A BILL (checked 2026-10-08). Pickens' treasurer portal (pickenscountysctax.us,
the Catalis / Sturgis "Avalon" app) reads its bills from d1ebsyxxbc7tep.cloudfront.net/data/<GUID>;
that API answered HTTP 403 "The request could not be satisfied" (CloudFront) to one plain GET on
2026-10-08, as it has since it escalated 429 -> 403 against a roll sweep on 2026-09-11. A 403 block
is a wall: it is not retried or worked around. Pickens is not on qPayBill (five subdomain guesses
NXDOMAIN, 2026-09-29). What the county DOES publish, free and anonymous, is its delinquent-tax
list itself: one ArcGIS FeatureServer per publication on its org services1.arcgis.com/
59960rq18IxUcAVI (the layers counties_sc.pickens_delinquent_parcels reads). The current cycle,
read live 2026-10-08:
    DELQ_TAX_WEEK1_2026   801 rows, 779 distinct PINs (18 PINs carry 2+ unit accounts), edited
                          2026-09-18, fields GISADMIN_P (PIN), T_WEEK_1_1 (owner), T_WEEK_1_2
                          (AMOUNT DUE)
    WeekOne2027           781 rows, one per PIN, edited 2026-09-21, fields MAP_PARCEL, OWNER__NOW,
                          AMOUNT_DUE ("Amount Due As of 9/17/2026"); the same list (779 PINs in
                          both, every shared amount equal), the name notwithstanding
Older publications (2020-2025, the scraper's LAYERS) give the parcel's listing history and, for
2020-2024, its situs address.

WHAT A LIST CAN AND CANNOT SAY.
  confirmed    the row's own PIN is on the current list with an amount due, and the list was
               edited within MAX_LIST_AGE_DAYS: the county published it as delinquent (amount as
               of the list date). TTL_DAYS is short because a payment after the list date is not
               on it.
  unconfirmed  everything else. Absence from the current list is NOT a payment record: a parcel
               drops off because its owner paid, because it was sold at the tax sale and sits in
               redemption, or because it was never listed; the list cannot tell which, so this
               verifier never answers stale or refuted (a wrong one would hide a real lead).
               Reasons: not_on_current_list (with the cycles it WAS listed in), sold_at_tax_sale
               (not on the current list and the row carries the county's tax-sale results block),
               parcel_unresolvable (no 12-digit Pickens PIN), list_too_old, newer_list_unread (the
               org has a delinquent-looking service edited after the lists this module reads: a
               new publication nobody wired in, which may have dropped the parcel),
               layer_unavailable (transient), shared_pin_accounts (the PIN carries several unit
               accounts on the list and the board owner matches none of them),
               no_amount_on_list, address_parcel_mismatch (the county's own situs for the PIN is another house number
               on the row's street, or the PIN came from a resolver and the owner differs: the
               list entry may be a neighbor's).
The chronic claim (tax_lien_chronic: listed in 3+ cycles, the scraper's own `chronic` rule) is
judged on the same lists: confirmed at CHRONIC_MIN_LATE_YEARS cycles, else unknown (a cycle the
parcel is missing from is not proof it paid on time).

Evidence (public ledger: no names, no addresses): the list services and their edit dates, the
cycles the PIN was listed in, the amount due on the current list, the owner-match CATEGORY, the
address relation to the county's situs.
"""
from __future__ import annotations

import asyncio
import re
import weakref
from datetime import date, datetime, timezone
from typing import Any, NamedTuple, Optional

from ..core import VerificationResult, parse_ts, result
from . import _arcgis_layer as ag
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 7
TRANSIENT_REASONS = ("layer_unavailable",)
TRANSIENT_RETRY_DAYS = 0.25
SOURCE = "services1.arcgis.com/59960rq18IxUcAVI (Pickens County delinquent tax lists)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority     # the "2+ years and $500" rows first within a tier
ROW_SUMMARY_EXCLUDE = ("owner_name",)

ORG = "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services"
COUNTY = "pickens"
MAX_LIST_AGE_DAYS = 120
_NAME = __name__.rsplit(".", 1)[-1]


class ListLayer(NamedTuple):
    service: str
    cycle: int
    current: bool
    pin: str
    owner: Optional[str] = None
    amount: Optional[str] = None
    situs: Optional[str] = None

    @property
    def url(self) -> str:
        return f"{ORG}/{self.service}/FeatureServer/0"

    @property
    def out_fields(self) -> str:
        return ",".join(["FID"] + [f for f in (self.pin, self.owner, self.amount, self.situs) if f])


#: current-cycle publications this module knows beyond the scraper's LAYERS (module doc)
EXTRA_CURRENT = (ListLayer("WeekOne2027", 2026, True, pin="MAP_PARCEL", owner="OWNER__NOW",
                           amount="AMOUNT_DUE"),)
#: a service on the org that looks like a delinquent-tax publication
_LIST_NAME = re.compile(r"(?i)(?:^|_)(?:del|dq|delq|delinq|posting|week)")


def layers() -> list[ListLayer]:
    """The scraper's LAYERS (2020 on) plus EXTRA_CURRENT, by service name, oldest first."""
    from ...scrapers.counties_sc.pickens_delinquent_parcels import LAYERS
    out: dict[str, ListLayer] = {}
    for L in LAYERS:
        if L.current:
            out[L.service] = ListLayer(L.service, L.cycle, True, pin=L.pin, owner=L.owner,
                                       amount=L.amount)
        else:       # an older list: only the PIN and the situs are read (no owner, no amount)
            out[L.service] = ListLayer(L.service, L.cycle, False, pin=L.pin, situs=L.situs)
    for L in EXTRA_CURRENT:
        out.setdefault(L.service, L)
    return sorted(out.values(), key=lambda x: (x.cycle, x.service))


# ---------------------------------------------------------------------------
# which rows (pure)
# ---------------------------------------------------------------------------

_OWN_BLOCKS = ("pickens_delinquent", "multi_year_delinquent_tax", "catalis_roll", "pickens_tax_sale")


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "SC":
        return False
    if str(tc.g(row, "county") or "").strip().lower() != COUNTY:
        return False
    raw = tc.raw_of(row)
    own = any(isinstance(raw.get(k), dict) for k in _OWN_BLOCKS)
    return tc.claims_property_tax(row, own)


def norm_pin(v: Any) -> Optional[str]:
    """The dashed Pickens PIN NNNN-NN-NN-NNNN, else None."""
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) != 12 or set(d) == {"0"}:
        return None
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}-{d[8:12]}"


def row_pin(row: Any) -> Optional[str]:
    return norm_pin(tc.g(row, "parcel_id"))


def _money(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d.]", "", str(v or ""))
    try:
        f = float(s) if s and s != "." else None
    except ValueError:
        return None
    return f if f and f > 0 else None


# ---------------------------------------------------------------------------
# the lists, once per sweep run
# ---------------------------------------------------------------------------

class Lists:
    def __init__(self) -> None:
        self.current: dict[str, list[dict]] = {}     # pin -> [{service, amount, owner}]
        self.cycles: dict[str, set[int]] = {}        # pin -> cycles listed in
        self.situs: dict[str, str] = {}              # pin -> newest situs on an older list
        self.current_services: list[dict] = []       # [{service, data_last_edit, rows}]
        self.missing: list[str] = []                 # older services that did not load
        self.error: Optional[str] = None             # a current list did not load
        self.newer_unread: list[str] = []


_RUNS: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()


async def _services(client: Any) -> list[str]:
    data = await client.get_json(f"{ORG}?f=json")
    return [str(s.get("name")) for s in (data or {}).get("services") or [] if s.get("name")]


async def _load(client: Any) -> Lists:
    out = Lists()
    known = layers()
    newest = None
    for L in known:
        snap = await ag.layer_for(client, L.url, out_fields=L.out_fields, order_by="FID")
        if not snap.complete:
            if L.current:
                out.error = f"{L.service}: {snap.health} {snap.error or ''}".strip()
            else:
                out.missing.append(L.service)
            continue
        for a in snap.rows:
            pin = norm_pin(a.get(L.pin))
            if not pin:
                continue
            out.cycles.setdefault(pin, set()).add(L.cycle)
            if L.current:
                out.current.setdefault(pin, []).append(
                    {"service": L.service, "amount": _money(a.get(L.amount)) if L.amount else None,
                     "owner": a.get(L.owner) if L.owner else None})
            elif L.situs and a.get(L.situs) and str(a.get(L.situs)).strip():
                out.situs[pin] = str(a.get(L.situs)).strip()        # oldest -> newest: newest wins
        if L.current:
            out.current_services.append({"service": L.service, "data_last_edit": snap.data_last_edit,
                                         "rows": len(snap.rows)})
            t = parse_ts(snap.data_last_edit)
            if t and (newest is None or t > newest):
                newest = t
    # a delinquent-looking publication the module does not read, edited after the newest list
    try:
        names = {L.service for L in known}
        for name in await _services(client):
            if name in names or not _LIST_NAME.search(name):
                continue
            meta = await client.get_json(ag.meta_url(f"{ORG}/{name}/FeatureServer/0"))
            edited = parse_ts(ag.epoch_iso(((meta or {}).get("editingInfo") or {})
                                           .get("dataLastEditDate")))
            if edited and newest and edited > newest:
                out.newer_unread.append(name)
    except Exception:  # noqa: BLE001 - the discovery check is a guard, not the data
        pass
    return out


async def lists_for(client: Any) -> Lists:
    try:
        per = _RUNS.get(client)
    except TypeError:
        per = None
    if isinstance(per, Lists):
        return per
    loop = asyncio.get_running_loop()
    if not (isinstance(per, asyncio.Task) and per.get_loop() is loop):
        per = loop.create_task(_load(client))
        try:
            _RUNS[client] = per
        except TypeError:
            pass

        def _done(t: asyncio.Task, client=client) -> None:
            if not t.cancelled() and t.exception() is None:
                try:
                    _RUNS[client] = t.result()
                except TypeError:
                    pass
        per.add_done_callback(_done)
    return await asyncio.shield(per)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "pin", "on_current_list", "list_services", "list_as_of", "list_age_days",
         "amount_due", "total_delinquent", "under_500", "de_minimis", "accounts_on_list",
         "list_cycles", "chronic_claim", "owner_match", "address_relation", "situs_source",
         "history_layers_missing", "newer_list_unread", "layer_error", "note")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION,
                  verifier=_NAME)


def _sold_block(row: Any) -> bool:
    b = tc.raw_of(row).get("pickens_tax_sale")
    if not isinstance(b, dict):
        return False
    return str(b.get("bidder") or "").strip().upper() not in ("PBO",)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    pin = row_pin(row)
    ev: dict[str, Any] = {"pin": pin}
    if not pin:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    try:
        lists = await lists_for(client)
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="layer_unavailable",
                                        layer_error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    if lists.error or not lists.current_services:
        return _res("unconfirmed", dict(ev, reason="layer_unavailable", layer_error=lists.error))
    edits = [parse_ts(s["data_last_edit"]) for s in lists.current_services if s["data_last_edit"]]
    as_of = max(edits).date() if edits else None
    cycles = sorted(lists.cycles.get(pin, set()))
    ev.update(list_services=[s["service"] for s in lists.current_services],
              list_as_of=as_of.isoformat() if as_of else None,
              list_age_days=(today - as_of).days if as_of else None,
              list_cycles=cycles,
              chronic_claim=tc.history_claims(cycles, False))
    if lists.missing:
        ev["history_layers_missing"] = lists.missing
    if lists.newer_unread:
        return _res("unconfirmed", dict(ev, reason="newer_list_unread",
                                        newer_list_unread=lists.newer_unread))
    if as_of is None or (today - as_of).days > MAX_LIST_AGE_DAYS:
        return _res("unconfirmed", dict(ev, reason="list_too_old"))
    entries = lists.current.get(pin) or []
    ev["on_current_list"] = bool(entries)
    if not entries:
        why = "sold_at_tax_sale" if _sold_block(row) else "not_on_current_list"
        return _res("unconfirmed", dict(ev, reason=why))

    owner = row.get("owner_name")
    ev["owner_match"] = tc.owner_category(owner, [e.get("owner") for e in entries])
    # DELQ_TAX_WEEK1_2026 lists each unit account under its parent PIN (18 PINs, 2026-10-08):
    # read the list with the most accounts for this PIN; several accounts are the row's only when
    # the board owner matches one (never another unit's balance)
    by_service: dict[str, list[dict]] = {}
    for e in entries:
        by_service.setdefault(e["service"], []).append(e)
    accounts = max(by_service.values(), key=len)
    ev["accounts_on_list"] = len(accounts)
    if len(accounts) > 1:
        cats = [(e, tc.owner_category(owner, [e.get("owner")])) for e in accounts]
        best = "same" if any(c == "same" for _, c in cats) else "partial"
        accounts = [e for e, c in cats if c == best]
        if not accounts:
            return _res("unconfirmed", dict(ev, reason="shared_pin_accounts"))
    # the row's address against the county's own situs for this PIN (older lists)
    addr = row.get("street_address")
    situs = lists.situs.get(pin)
    if situs and tc.address_query(addr):
        rel = tc.address_relation(addr, situs)
        ev.update(address_relation=rel, situs_source="older_delinquent_list")
        if tc.other_number_same_street(addr, situs):
            return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch"))
    if tc.parcel_resolved(row) and ev["owner_match"] == "different":
        return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch",
                                        note="the PIN was attached by a resolver and the list "
                                             "names another owner"))
    amounts = [e["amount"] for e in accounts if e.get("amount")]
    if not amounts:
        return _res("unconfirmed", dict(ev, reason="no_amount_on_list"))
    total = round(sum(amounts), 2)
    ev.update(amount_due=total, total_delinquent=total, under_500=total < 500,
              de_minimis=total < tc.DE_MINIMIS)
    return _res("confirmed", ev)
