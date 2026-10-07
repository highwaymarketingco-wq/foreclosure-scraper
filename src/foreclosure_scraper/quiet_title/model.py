"""Data the county adapters fill and the renderer reads. Plain dataclasses, no I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt_both(dt: Optional[datetime]) -> str:
    """'2026-10-07 12:32:26 EDT (16:32:26 UTC)': the sheet's one way to print a fetch time."""
    if dt is None:
        return "not fetched"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    loc = dt.astimezone(EASTERN)
    utc = dt.astimezone(timezone.utc)
    return f"{loc:%Y-%m-%d %H:%M:%S} {loc.tzname()} ({utc:%H:%M:%S} UTC)"


def fmt_local_date(dt: datetime) -> str:
    return dt.astimezone(EASTERN).strftime("%Y-%m-%d")


@dataclass
class Exhibit:
    """One fetched page, saved beside the sheet."""
    key: str                         # E1, E2, ...
    label: str                       # what it is, in words
    source: str                      # the publisher, in words
    url: str                         # an address a person can open (GET), or the form page
    method: str = "GET"
    fetched: Optional[datetime] = None
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    files: list[str] = field(default_factory=list)       # saved copies, relative to exhibits/
    screenshot: Optional[str] = None                      # relative to exhibits/
    shot_kind: Optional[str] = None                       # gis_json | tax_html | rod_grid | rod_detail
    note: Optional[str] = None                            # e.g. the form fields a person enters
    walled: bool = False
    wall_reason: Optional[str] = None
    sha256: Optional[str] = None
    nbytes: int = 0


@dataclass
class Parcel:
    pin: str
    exhibit: Optional[str] = None
    found: bool = False
    owner: Optional[str] = None
    care_of: Optional[str] = None
    mailing: Optional[str] = None
    mailing_house_number: Optional[str] = None
    mailing_street: Optional[str] = None
    situs: Optional[str] = None
    situs_house_number: Optional[str] = None           # None when the county has no number
    situs_street: Optional[str] = None                  # street name as the layer keys it
    situs_note: Optional[str] = None
    acreage: Optional[float] = None
    land_class: Optional[str] = None
    improved: Optional[str] = None
    tax_value: Optional[float] = None
    land_value: Optional[float] = None
    building_value: Optional[float] = None
    deed_book: Optional[str] = None
    deed_page: Optional[str] = None
    deed_date: Optional[str] = None                     # ISO date
    deed_instrument: Optional[str] = None
    plat_book: Optional[str] = None
    plat_page: Optional[str] = None
    subdivision: Optional[str] = None
    township: Optional[str] = None
    layer_updated: Optional[str] = None                 # ISO date
    field_names: list[str] = field(default_factory=list)
    legal_description: Optional[str] = None
    legal_field: Optional[str] = None
    #: None: a legal-description field on the county's own layer. "assessor_short": the short
    #: legal on the assessor's roll (NC OneMap legdecfull), which is NOT the deed's full legal
    legal_kind: Optional[str] = None
    record_card_url: Optional[str] = None
    #: where the parcel record came from, in words (None: the county's own parcel layer)
    layer_label: Optional[str] = None
    value_note: Optional[str] = None                    # how the layer labels its value
    deed_ref_text: Optional[str] = None                 # the deed reference exactly as the layer writes it
    deed_date_text: Optional[str] = None                # the deed date exactly as the layer writes it
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OtherParcel:
    """A parcel that carries the mailing address's house number (situs vs mailing check)."""
    pin: str
    situs: str
    owner: Optional[str]
    improved: Optional[str]
    deed: Optional[str]


@dataclass
class Instrument:
    """One register-of-deeds index entry."""
    date: str                                    # as indexed (deaths are masked to the year)
    date_iso: Optional[str] = None
    year: Optional[int] = None
    index_code: str = ""                         # DEE, DTR, CRP, DTH, ...
    kind: str = ""                               # the index's type column (DEED, DEED OF TRUST, ...)
    grantors: list[str] = field(default_factory=list)
    grantees: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)       # the parties the search matched (bold)
    matched_side: Optional[str] = None                     # grantor | grantee | both
    description: str = ""
    book: str = ""
    page: str = ""
    pages: Optional[int] = None
    link_target: Optional[str] = None            # the grid's postback target (Document Details)
    exhibit: Optional[str] = None
    detail_exhibit: Optional[str] = None         # the register's Document Details page, when opened
    tie: Optional[str] = None                    # how a chain entry ties to the one after it
    name_fit: Optional[str] = None               # full | compatible (chain name filter)

    @property
    def book_page(self) -> str:
        return f"{self.book} / {self.page}" if self.book else ""


@dataclass
class TaxTransaction:
    type: str
    date: str
    receipt: str
    tax: Optional[float]
    late_fee: Optional[float]
    interest: Optional[float]
    cost: Optional[float]
    total: Optional[float]


@dataclass
class TaxBill:
    bill: str
    tax_year: Optional[int] = None
    levy_year: Optional[int] = None
    regular: bool = True
    owner: Optional[str] = None
    value: Optional[float] = None
    amount_due: Optional[float] = None
    amount_due_text: Optional[str] = None
    description: Optional[str] = None
    exhibit: Optional[str] = None
    detail_read: bool = False
    transactions: list[TaxTransaction] = field(default_factory=list)
    status_text: Optional[str] = None            # e.g. Paid! / See Legal

    @property
    def billed_on(self) -> Optional[str]:
        for t in self.transactions:
            if t.type.upper() == "BILL":
                return t.date
        return None

    def component(self, name: str) -> Optional[float]:
        """Sum of one money column over the BILL lines (tax, late_fee, interest, cost, total)."""
        vals = [getattr(t, name) for t in self.transactions if t.type.upper() == "BILL"]
        vals = [v for v in vals if v is not None]
        return round(sum(vals), 2) if vals else None

    @property
    def payments(self) -> list[TaxTransaction]:
        return [t for t in self.transactions if t.type.upper() != "BILL"]


@dataclass
class TaxStatus:
    exhibit: Optional[str] = None
    parcel_status: Optional[str] = None          # Active / Inactive
    bills: list[TaxBill] = field(default_factory=list)
    current_year: Optional[int] = None
    completed_years: list[int] = field(default_factory=list)    # the three shown
    interest_rule: str = ""
    walled: bool = False
    wall_reason: Optional[str] = None
    #: False: the tool does not read this county's tax bills (the sheet points to the tax site)
    fetched: bool = True
    note: Optional[str] = None


@dataclass
class DeathEntry:
    year: Optional[int]
    date: str
    book_page: str
    decedent_names: list[str]
    parents: list[str]
    matched_as: str                      # decedent | parent
    fit: str                             # fit | candidate | parent_only | other_person
    reasons: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)


@dataclass
class DeathSearch:
    person: str                          # the name searched, LAST, FIRST MIDDLE
    reading: str                         # how the name was read and from where
    last: str
    first: str
    exhibit: Optional[str] = None
    valid_from: Optional[str] = None
    valid_thru: Optional[str] = None
    total: Optional[int] = None
    entries: list[DeathEntry] = field(default_factory=list)
    walled: bool = False
    wall_reason: Optional[str] = None


@dataclass
class NameSearch:
    """A register name search the chain or the after-vesting step ran."""
    purpose: str
    last: str
    first: str
    side: str
    date_from: str = ""
    date_thru: str = ""
    exhibit: Optional[str] = None
    total: Optional[int] = None
    shown: int = 0
    rows: list[Instrument] = field(default_factory=list)
    walled: bool = False
    wall_reason: Optional[str] = None


@dataclass
class RecordCheck:
    record: str
    status: str                          # checked | checked in part | walled | not run | not checked
    what: str
    result: str


@dataclass
class IntakeResult:
    county: str
    state: str
    pin: str
    started: datetime
    finished: Optional[datetime] = None
    parcel: Optional[Parcel] = None
    mailing_parcels: list[OtherParcel] = field(default_factory=list)
    mailing_check_note: Optional[str] = None
    tax: Optional[TaxStatus] = None
    deed_rows: list[Instrument] = field(default_factory=list)   # every entry at the cited book/page
    vesting: Optional[Instrument] = None
    vesting_note: Optional[str] = None
    vesting_detail_url: Optional[str] = None
    deed_link: Optional[str] = None
    plat_rows: list[Instrument] = field(default_factory=list)
    plat_link: Optional[str] = None
    chain: list[Instrument] = field(default_factory=list)
    chain_note: Optional[str] = None
    searches: list[NameSearch] = field(default_factory=list)
    after_vesting: list[NameSearch] = field(default_factory=list)
    roll_markers: list[str] = field(default_factory=list)
    owner_people: list[dict] = field(default_factory=list)
    death_searches: list[DeathSearch] = field(default_factory=list)
    obituary: dict = field(default_factory=dict)
    records: list[RecordCheck] = field(default_factory=list)
    exhibits: dict[str, Exhibit] = field(default_factory=dict)
    walls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    how_to: list[tuple[str, list[str]]] = field(default_factory=list)
    not_established: list[str] = field(default_factory=list)
    sources: list[tuple[str, str, str]] = field(default_factory=list)
    #: False: the tool does not search this county's register; the sheet gives the register link
    register_fetched: bool = True
    register_link: Optional[str] = None

    def to_json(self) -> dict:
        def conv(o: Any) -> Any:
            if isinstance(o, datetime):
                return o.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if isinstance(o, dict):
                return {k: conv(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [conv(v) for v in o]
            return o
        return conv(asdict(self))
