"""The county contract. A new county is one subclass of CountyAdapter.

An adapter answers primitive questions against ONE county's free public sources, through the
PoliteFetcher it is given, and records every page it reads as an Exhibit. It never decides what a
fact means for title: intake.py composes the steps (deed chain, heirs analysis, records table)
the same way for every county.

Every network method may raise fetch.Walled; intake.py records the step as walled and goes on.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from ..fetch import PoliteFetcher, Response
from ..model import (DeathSearch, Exhibit, Instrument, IntakeResult, NameSearch, OtherParcel,
                     Parcel, RecordCheck, TaxStatus)
from ..names import PersonName


class CountyAdapter(ABC):
    state: str = ""
    county: str = ""
    #: False for a county whose register this tool does not search: intake.py then runs no deed,
    #: chain, name or deaths search and the sheet says 'not fetched by the tool: use the link above'
    register_fetched: bool = True
    #: the records-table name of the parcel record
    parcel_record_label: str = "County parcel record (tax parcel layer)"

    def __init__(self, fetcher: PoliteFetcher, result: IntakeResult, stamp: str) -> None:
        self.f = fetcher
        self.result = result
        self.stamp = stamp            # yyyymmdd, part of every exhibit file name

    # -- exhibits ---------------------------------------------------------------------------
    def new_exhibit(self, label: str, source: str, url: str, *, method: str = "GET",
                    note: Optional[str] = None, shot_kind: Optional[str] = None) -> Exhibit:
        key = f"E{len(self.result.exhibits) + 1}"
        ex = Exhibit(key=key, label=label, source=source, url=url, method=method, note=note,
                     shot_kind=shot_kind)
        self.result.exhibits[key] = ex
        return ex

    def file_name(self, ex: Exhibit, slug: str, ext: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_")[:60]
        return f"{self.result.pin}_{ex.key}_{slug}_{self.stamp}.{ext}"

    def keep(self, ex: Exhibit, resp: Optional[Response], slug: str, ext: str) -> Exhibit:
        return self.f.exhibit(ex, resp, self.file_name(ex, slug, ext) if resp is not None else None)

    # -- the questions ----------------------------------------------------------------------
    @abstractmethod
    def parcel(self, pin: str) -> Parcel:
        """The county parcel record for this PIN (owner, situs, mailing, deed cited, values)."""

    @abstractmethod
    def parcels_at_mailing_number(self, parcel: Parcel) -> tuple[list[OtherParcel], str]:
        """Parcels that carry the mailing address's house number on the same road (situs vs
        mailing), and a sentence saying what was checked."""

    @abstractmethod
    def tax(self, parcel: Parcel, today: date) -> TaxStatus:
        """The tax bills: the current levy year and the three most recent completed ones read
        bill by bill; older bills from the parcel's billing list."""

    @abstractmethod
    def deed_at(self, book: str, page: str, label: Optional[str] = None) -> tuple[list[Instrument], str]:
        """Every register index entry at this book and page, and the link a person opens."""

    @abstractmethod
    def deed_detail(self, inst: Instrument) -> Optional[str]:
        """Open the register's own detail page for this entry (fills pages, parties); returns
        the detail page address, or None."""

    def plat_at(self, book: str, page: str) -> tuple[list[Instrument], str]:
        return [], ""

    @abstractmethod
    def name_search(self, purpose: str, person: PersonName | str, *, side: str = "both",
                    date_from: str = "", date_thru: str = "") -> NameSearch:
        """A register name search (real property and pre-1995 deed indexes; not deaths).
        side: grantor | grantee | both. Dates are MM/DD/YYYY or ''."""

    @abstractmethod
    def death_search(self, person: PersonName, reading: str) -> DeathSearch:
        """The register's deaths index for this surname and given name."""

    def obituary(self, people: list[PersonName]) -> dict:
        return {"run": False, "reason": "No obituary source is set up for this county.",
                "searches": []}

    # -- the words --------------------------------------------------------------------------
    @abstractmethod
    def static_records(self) -> list[RecordCheck]:
        """Rows for the records table that no fetch decides (walled courts, microfilm, ...)."""

    @abstractmethod
    def how_to(self, result: IntakeResult) -> list[tuple[str, list[str]]]:
        """'How to check it again': (record, steps a person follows)."""

    @abstractmethod
    def sources(self) -> list[tuple[str, str, str]]:
        """(source, address a person opens, access) for the sources appendix."""

    def not_established(self) -> list[str]:
        return []

    def register_link(self) -> Optional[str]:
        """The register-of-deeds address a person opens (used when register_fetched is False)."""
        return None
