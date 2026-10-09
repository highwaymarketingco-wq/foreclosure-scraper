"""The plumbing every NC register platform adapter shares: one reused cookie session per county,
the per-run lookup cap, the walled-county registry, a per-process result cache (so the lien
enricher and the chain enricher never search the same name twice in one run), the async
search_by_name bridge the generic ROD enricher calls, and chain().

A platform module subclasses NcRodPlatform, fills `platform`, `counties` and the two protocol
hooks (_open, _search), and exposes module-level search_by_name / chain bound to one instance.
"""
from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from . import nc_polite
from .models import RodDoc
from .nc_chain import OwnerName, SearchResult, build_chain, merge_records, parse_owner, to_rod_doc
from .nc_polite import PoliteClient, RodWalled

log = structlog.get_logger()

SESSION_TTL_S = 20 * 60


def county_key(county: str) -> str:
    return " ".join((county or "").replace("-", " ").replace("_", " ").split()).lower()


@dataclass
class _Held:
    client: PoliteClient
    ready: bool = False
    ctx: Any = None                  # whatever the platform's _open() wants to keep (a form token, a code map)


class NcRodPlatform:
    platform: str = ""
    state: str = "NC"
    #: county display name -> platform config (host, tenant path, ...)
    counties: dict[str, Any] = {}

    def __init__(self) -> None:
        self._held: dict[str, _Held] = {}
        self._cache: dict[tuple, SearchResult] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _county_lock(self, name: str) -> threading.Lock:
        with self._locks_guard:
            lk = self._locks.get(name)
            if lk is None:
                lk = self._locks[name] = threading.Lock()
            return lk

    # -- config ------------------------------------------------------------------------------
    def config(self, county: str) -> Optional[tuple[str, Any]]:
        k = county_key(county)
        for name, cfg in self.counties.items():
            if county_key(name) == k:
                return name, cfg
        return None

    def source_url(self, cfg: Any) -> str:          # the page a person opens; platform overrides
        return ""

    #: env var holding this platform's own per-run, per-county lookup cap (e.g. the headless-browser
    #: platforms, in the style of FORECLOSURE_SPARTANBURG_ROD_MAX); None = NC_ROD_MAX_LOOKUPS_PER_COUNTY
    cap_env: Optional[str] = None
    default_cap: int = nc_polite.DEFAULT_MAX_LOOKUPS_PER_COUNTY

    def max_lookups(self) -> int:
        if self.cap_env:
            try:
                return max(0, int(os.environ.get(self.cap_env, self.default_cap)))
            except ValueError:
                return self.default_cap
        return nc_polite.max_lookups_per_county()

    # -- protocol hooks ----------------------------------------------------------------------
    def _open(self, client: PoliteClient, cfg: Any) -> Any:
        """Clear the county's disclaimer / open its search; return context kept with the session."""
        return None

    def _search(self, client: PoliteClient, cfg: Any, ctx: Any, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        raise NotImplementedError

    # -- sessions ----------------------------------------------------------------------------
    def _client(self, name: str, cfg: Any) -> _Held:
        h = self._held.get(name)
        if h is not None and nc_polite.clock() - h.client.opened > SESSION_TTL_S:
            h = None
        if h is None:
            h = self._held[name] = _Held(PoliteClient(self.platform, self.state, name))
        if not h.ready:
            h.ctx = self._open(h.client, cfg)
            h.ready = True
        return h

    def drop_sessions(self) -> None:
        self._held.clear()
        self._cache.clear()

    # -- the one search everything goes through ---------------------------------------------
    def search(self, county: str, who: OwnerName, side: str = "both",
               date_thru: Optional[str] = None) -> SearchResult:
        hit = self.config(county)
        if hit is None:
            return SearchResult(status="error", reason=f"{county} is not a {self.platform} county")
        name, cfg = hit
        # One lookup at a time per county: the Lookup and Online Record System flows keep the pick
        # list and the ticked names in the server session, so two lookups interleaving their steps
        # on one session would mix their names. (The generic enricher runs several at once.)
        with self._county_lock(name):
            return self._search_locked(name, cfg, who, side, date_thru)

    def _search_locked(self, name: str, cfg: Any, who: OwnerName, side: str,
                       date_thru: Optional[str]) -> SearchResult:
        url = self.source_url(cfg)
        why = nc_polite.walled_reason(self.platform, self.state, name)
        if why:
            return SearchResult(status="walled", reason=why, url=url)
        ck = (county_key(name), who.last, who.first, who.entity, side, date_thru or "")
        if ck in self._cache:
            return self._cache[ck]
        cap = self.max_lookups()
        if not nc_polite.take_lookup(self.platform, self.state, name, cap):
            return SearchResult(status="capped", url=url,
                                reason=f"per-run cap of {cap} lookups for {name} reached")
        try:
            held = self._client(name, cfg)
            res = self._search(held.client, cfg, held.ctx, who, side, date_thru)
        except RodWalled as w:
            self._held.pop(name, None)
            return SearchResult(status="walled", reason=w.reason, url=url)
        except Exception as exc:  # noqa: BLE001 - a lookup never kills a run
            self._held.pop(name, None)          # a broken session is not reused
            log.warning("nc_rod.search_failed", platform=self.platform, county=name,
                        error=f"{type(exc).__name__}: {str(exc)[:160]}")
            return SearchResult(status="error", reason=f"{type(exc).__name__}: {str(exc)[:160]}", url=url)
        res.url = res.url or url
        res.records = merge_records(res.records)
        if res.status == "ok":
            self._cache[ck] = res
        return res

    # -- the shared interfaces ---------------------------------------------------------------
    def search_by_name_sync(self, state: str, county: str, name: str, max_docs: int = 80) -> list[RodDoc]:
        if (state or "").upper() != self.state or self.config(county) is None:
            return []
        who = parse_owner(name)
        if who is None:
            return []
        res = self.search(county, who, "both", None)
        if res.status != "ok":
            return []
        shown = self.config(county)[0]
        return [to_rod_doc(r, self.state, shown, self.platform) for r in res.records[:max_docs]]

    def search_by_name_status_sync(self, state: str, county: str, name: str,
                                   max_docs: int = 80) -> tuple[list[RodDoc], str, bool]:
        """search_by_name_sync plus why it may be empty: (docs, status, truncated), status ok | walled |
        capped | error | noname. Status ok with no docs is a checked "nothing indexed under that name"."""
        if (state or "").upper() != self.state or self.config(county) is None:
            return [], "error", False
        who = parse_owner(name)
        if who is None:
            return [], "noname", False
        res = self.search(county, who, "both", None)
        if res.status != "ok":
            return [], res.status, False
        shown = self.config(county)[0]
        return ([to_rod_doc(r, self.state, shown, self.platform) for r in res.records[:max_docs]],
                "ok", bool(getattr(res, "truncated", False)))

    async def search_by_name_status(self, state: str, county: str, name: str, max_docs: int = 80):
        return await asyncio.to_thread(self.search_by_name_status_sync, state, county, name, max_docs)

    async def search_by_name(self, state: str, county: str, name: str, max_docs: int = 80) -> list[RodDoc]:
        """The interface every rod module exposes (enrichment_generic_rod calls it). Runs the
        blocking, paced search in a worker thread; the per-host lock keeps one host serial."""
        return await asyncio.to_thread(self.search_by_name_sync, state, county, name, max_docs)

    def chain(self, county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
        hit = self.config(county)
        if (state or "").upper() != self.state or hit is None:
            return {"state": state, "county": county, "platform": self.platform, "status": "error",
                    "reason": f"{county}, {state} is not a {self.platform} county"}
        name, cfg = hit
        return build_chain(platform=self.platform, state=self.state, county=name, owner_name=owner_name,
                           search=lambda who, side, thru: self.search(name, who, side, thru),
                           depth=depth, source_url=self.source_url(cfg))
