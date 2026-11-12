"""Per-listing verification: the result type, the verdict vocabulary, row identity, and the
read side the scorer uses. Stdlib-only at import time (the scorer imports this module).

A verification record is one live, re-checkable answer to "is THIS claim on THIS row true",
from the claim's authoritative source (docs/validation_2026-10-02/VERIFICATION_PIPELINE_SPEC.md
section 1). The schema is the spec's, plus two stamps the apply step adds:

    {"signal": "tax_lien",                       # the claim checked (a verifier's SIGNAL)
     "verdict": "confirmed",                     # see VERDICTS below
     "evidence": {...},                          # what the source actually said, structured
     "source": "tax.buncombenc.gov",
     "checked_at": "2026-10-05T23:59:00Z",       # UTC
     "verifier_version": "v1",                   # the verifier module's VERSION
     "verifier": "tax_lien_buncombe",            # the verifier module's name
     # added by verification.apply when it attaches the record to a row:
     "expires_at": "2026-11-04T23:59:00Z",       # checked_at + the verifier's TTL_DAYS
     "governs": ["tax_lien", ...]}               # scorer signal names this verdict governs

VERDICTS (precise, so every verifier means the same thing):
  confirmed    the source shows the claim is true today.
  refuted      the source shows the claim is false, with no sign it was ever true.
  stale        the source shows the claim WAS true but no longer is (a delinquent bill paid
               late, a case since closed). Not "an old record": an aged record is handled by
               expires_at, never by rewriting its verdict.
  unconfirmed  checked, and the source could not decide (page unreadable, parcel not found,
               ambiguous match). Says nothing about the claim.
  wall         cannot be checked by code at all (CAPTCHA, WAF, login, or ToS-restricted
               automated querying). Labelled honestly; never queried.

WHAT SCORING DOES WITH THEM (distress_score._collect, enrichment_lead_signals._facet_signals,
both through suppressed_scorer_signals()): a non-expired `refuted` or `stale` verdict removes
the scorer signals its record governs. `confirmed` changes no weight; it is there for the
dashboard badge (verdict_badges()). `unconfirmed` and `wall` change nothing.

ROW IDENTITY (row_key): Listing.dedupe_key()'s property identity, parcel first -- see
row_key()'s docstring for the measurement on real boards that chose it. A verifier whose claim
is about a CASE on the property (IDENTITY = "case": bankruptcy, jail) keys its ledger by case id
+ property instead (case_id(), scoped_keys(); see "case-scoped identity" below).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

VERDICTS = ("confirmed", "refuted", "stale", "unconfirmed", "wall")
#: verdicts that settle the claim one way or the other
DECISIVE = frozenset({"confirmed", "refuted", "stale"})
#: verdicts that take the governed signal out of scoring (while not expired)
SUPPRESSING = frozenset({"refuted", "stale"})

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    """UTC ISO with a Z, second precision: '2026-10-05T23:59:00Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(v: Any) -> Optional[datetime]:
    """A UTC datetime from an ISO string ('...Z', '+00:00', or a bare date), else None."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def expires_at(checked_at: Any, ttl_days: Optional[float]) -> Optional[str]:
    """checked_at + ttl_days as an ISO-Z string; None when either is missing."""
    t = parse_ts(checked_at)
    if t is None or ttl_days is None:
        return None
    return iso_z(t + timedelta(days=float(ttl_days)))


def is_expired(record: dict, now: Optional[datetime] = None) -> bool:
    """A record past its expires_at. A record with no expires_at never expires here (the
    sweep's TTL check is what re-verifies it); the apply step always stamps one."""
    exp = parse_ts(record.get("expires_at"))
    return exp is not None and (now or utc_now()) >= exp


# ---------------------------------------------------------------------------
# the result
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    signal: str
    verdict: str
    evidence: dict = field(default_factory=dict)
    source: str = ""
    checked_at: str = ""
    verifier_version: str = ""
    verifier: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}, got {self.verdict!r}")
        if not self.signal:
            raise ValueError("a verification result needs a signal")
        if not self.checked_at:
            self.checked_at = iso_z(utc_now())
        if not isinstance(self.evidence, dict):
            raise ValueError("evidence must be a dict")

    @property
    def decisive(self) -> bool:
        return self.verdict in DECISIVE

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VerificationResult":
        """From a stored record (ledger or raw['verification']); unknown keys are ignored."""
        return cls(signal=str(d.get("signal") or ""), verdict=str(d.get("verdict") or ""),
                   evidence=dict(d.get("evidence") or {}), source=str(d.get("source") or ""),
                   checked_at=str(d.get("checked_at") or ""),
                   verifier_version=str(d.get("verifier_version") or ""),
                   verifier=str(d.get("verifier") or ""))


def result(signal: str, verdict: str, evidence: Optional[dict] = None, *, source: str = "",
           version: str = "", verifier: str = "", now: Optional[datetime] = None
           ) -> VerificationResult:
    """Shorthand a verifier uses to build its answer, stamped now (UTC)."""
    return VerificationResult(signal=signal, verdict=verdict, evidence=dict(evidence or {}),
                              source=source, checked_at=iso_z(now or utc_now()),
                              verifier_version=version, verifier=verifier)


# ---------------------------------------------------------------------------
# row identity
# ---------------------------------------------------------------------------

_IDENTITY_FIELDS = ("source", "source_url", "listing_type", "street_address", "city", "state",
                    "zip_code", "county", "parcel_id", "case_number", "plaintiff", "defendant",
                    "trustee", "sale_date", "sale_time", "sale_location", "opening_bid",
                    "judgment_amount", "legal_description")


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


#: Text that appears in a foreclosure NOTICE and never in a street address. Some sources put the
#: first sentence of a notice in street_address ("Under and by virtue of the power of sale
#: contained in a certain Deed of Trust made by <names> ..."), and a ledger key or row summary
#: built from it would publish those people's names in the public ledger (found 2026-10-06:
#: 5 foreclosure_rod entries; two named private individuals).
_NOTICE_TEXT = re.compile(
    r"deed of trust|power of sale|made by|in the matter|virtue of|pursuant to|substitute trustee|"
    r"notice of (?:sale|foreclosure)|foreclos|"
    # the NC PTS Cloud roll scraper's stand-in for a missing address ("Parcel - <OWNER> - Orange NC
    # delinquent tax $200 owed (parcel 9..."): it names the owner (2 ledger entries, 2026-10-07)
    r"^\s*parcel\s+[\u2014\u2013-]\s|delinquent tax \$", re.I)
MAX_ADDRESS_CHARS = 90


def looks_like_address(value: Any) -> bool:
    """True when `value` can be a street address: non-empty, short, and not notice text."""
    s = str(value or "").strip()
    return bool(s) and len(s) <= MAX_ADDRESS_CHARS and not _NOTICE_TEXT.search(s)


def has_notice_text(value: Any) -> bool:
    """True when `value` (a ledger key, a row summary field) carries notice text."""
    return bool(_NOTICE_TEXT.search(str(value or "")))


def row_keys(row: Any) -> list[str]:
    """Every property-identity key the row has, strongest first; the first is row_key().

      parcel:<STATE>:<county>:<parcel>   Listing.dedupe_key()'s parcel branch, as normalized
                                         there ("8772-95-9699-00000" == "877295969900000")
      addr:<STATE>:<county>:<address>    models._normalize_addr(), state+county qualified,
                                         WITHOUT the zip (a geocoder filling zip_code later
                                         must not move the key); only for an address with a
                                         real house number (_house_numbered)
      case:<STATE>:<county>:<case>       models._normalize_case()
      row:<fingerprint>                  only when none of the above applies

    The ledger is keyed by the first and stores the rest, and the apply step matches a row
    on any of its keys that exactly one ledger entry claims, so a verdict follows its row
    when a resolver backfills the parcel later (measured: 19,928 rows went addr -> parcel
    between the 2026-09-21 and 2026-10-05 boards)."""
    from ..models import _normalize_addr, _normalize_case, _normalize_parcel  # lazy (scorer)
    st = str(_get(row, "state") or "").strip().upper()
    co = str(_get(row, "county") or "").strip().lower()
    out: list[str] = []
    p = _normalize_parcel(_get(row, "parcel_id"))
    if p and (st or co):
        out.append(f"parcel:{st}:{co}:{p}")
    a = _normalize_addr(_get(row, "street_address"))
    if a and (st or co) and _house_numbered(a) and looks_like_address(_get(row, "street_address")):
        out.append(f"addr:{st}:{co}:{a}")
    c = _normalize_case(_get(row, "case_number"))
    if c and co:
        out.append(f"case:{st}:{co}:{c}")
    if not out:
        out.append("row:" + _fingerprint(row))
    return out


_HOUSE_NO = re.compile(r"(\d+)")


def _house_numbered(addr: str) -> bool:
    """An address identifies a property only with a real house number: a bare road name ("old
    trull rd", "nc 9 hwy") is shared by every vacant lot on the road, and "0 ..." is a county
    placeholder. Measured on the 2026-10-06 sweep: unnumbered road names on Buncombe vacant-land
    rows tied up to four different parcels to one ledger entry before this rule."""
    m = _HOUSE_NO.match(addr)
    return bool(m) and int(m.group(1)) > 0


def row_key(row: Any) -> str:
    """The ledger key for a board row: its parcel identity when it has a parcel, else its
    address, else its case number (row_keys()), else a fingerprint of the as-scraped fields.

    WHY (measured 2026-10-05 with board_stream on three real boards: the current one, and the
    committed boards of 2026-10-01 and 2026-09-21; full numbers in docs/HANDOFF.md item 66):
      * source_url ("u:" in web_artifact._identity_keys) is unique for under half the rows (a
        county roll URL covers every lead in the file): it cannot identify a row.
      * a bare parcel_id ("p:" there) carries no county; this key is state+county qualified
        and normalized the way dedupe_key() normalizes it.
      * Listing.dedupe_key() as a single string is unstable over weeks: of rows matched by a
        unique address across 2026-09-21 -> 2026-10-05, 31,292 changed dedupe_key (19,928
        addr -> parcel when a parcel was backfilled, 4,211 parcel -> addr when a bad parcel
        was cleared, 7,153 parcel -> parcel). So the ledger keeps every key of the row and the
        apply step matches on any of them (see row_keys()); the address key here drops the
        zip so a later zip fill does not move it either.
      * the identity is the PROPERTY, which is what every verifier checks (a tax bill, a ROD
        record, a code case all hang off the parcel or the address), so two board rows on the
        same parcel share a verdict, correctly: a parcel's taxes are paid or not, whichever
        source's row asks.
    A row with none of the three gets "row:<fingerprint>" (row_identity_hash's as-scraped
    fields), never its source_url: a shared URL must never join unrelated leads."""
    return row_keys(row)[0]


def _fingerprint(row: Any) -> str:
    vals = {k: _get(row, k) for k in _IDENTITY_FIELDS if k != "parcel_id"}
    blob = json.dumps(vals, sort_keys=True, separators=(",", ":"),
                      default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# address identity: does a parcel / account carry the ROW's address? (moved here from the tax
# verifiers' common module: the ledger's address-aware lookup uses it too)
# ---------------------------------------------------------------------------
#
# WHY (2026-10-06 recheck of all 103 stale verdicts, 7 of them wrong): a row's parcel id and its
# street address can belong to DIFFERENT parcels (a retired / recombined PIN, a roll block merged
# into another parcel's row, a resolver that matched a road name). A stale or refuted verdict
# removes the claim from the lead's score, so it may only be issued from the parcel that carries
# the row's address. address_relation() is the shared yes / no / cannot-tell; each verifier
# decides what to do with a "conflict" (follow the address, or answer unconfirmed).

_ADDR_ALIAS = {
    "ROAD": "RD", "STREET": "ST", "DRIVE": "DR", "TERRACE": "TER", "TERR": "TER",
    "AVENUE": "AVE", "BOULEVARD": "BLVD", "LANE": "LN", "COURT": "CT", "CIRCLE": "CIR",
    "TRAIL": "TRL", "HIGHWAY": "HWY", "EXTENSION": "EXT", "PLACE": "PL", "PARKWAY": "PKWY",
    "MOUNTAIN": "MTN", "POINT": "PT", "COVE": "CV", "RIDGE": "RDG", "HEIGHTS": "HTS",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
    "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
    "CRESCENT": "CRES",         # "5 ALL SOULS CRES" is the county's spelling of "5 All Souls Crescent"
    # Mecklenburg's roll abbreviations ("10 SAMPLE AV", "10 SAMPLE BV", "10 SAMPLE CR",
    # "10 SAMPLE WY", "10 SAMPLE PY"; audit 2026-10-09 phones_lost)
    "AV": "AVE", "BV": "BLVD", "CR": "CIR", "WY": "WAY", "PY": "PKWY", "TR": "TRL",
    "LP": "LOOP", "HY": "HWY",
}
#: route prefixes: "NC 200", "HWY 64", "US HWY 117" (the number that follows is the street name)
_ADDR_ROUTE = frozenset({"HWY", "NC", "SC", "US", "SR", "RT", "ROUTE"})
#: a state token or a zip after the street: the start of a comma-less "CITY ST ZIP" tail
_ADDR_TAIL_ANCHOR = re.compile(r"^(NC|SC|\d{5}(\d{4})?)$")
_ADDR_SUFFIXES = frozenset({"CRES", "RD", "ST", "DR", "TER", "AVE", "BLVD", "LN", "CT", "CIR", "TRL",
                            "HWY", "EXT", "PL", "PKWY", "WAY", "LOOP", "PT", "CV", "RDG", "HTS",
                            "PIKE", "ALY", "SQ", "XING", "TRCE", "RUN", "PATH", "BND", "CRK"})
_ADDR_DIRECTIONS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})
_ADDR_UNIT = frozenset({"APT", "UNIT", "STE", "SUITE", "LOT", "TRLR", "BLDG", "BUILDING", "SPC",
                        "SPACE", "FL", "FLOOR", "RM", "ROOM"})
#: words the counties append that are not part of the street ("242 P GIBBS RD UNINCORPORATED")
_ADDR_NOISE = frozenset({"UNINCORPORATED", "UNINCORPORAT", "UNINC", "NC", "SC", "USA", "UNITED",
                         "STATES", "COUNTY"})


def _drop_city_tail(toks: list[str]) -> list[str]:
    """Street tokens (after the house number, aliases applied) without a comma-less city / state /
    zip tail: "SAMPLE RD CHARLOTTE NC 28207" -> "SAMPLE RD". Only when a state token or a zip
    follows the street AND a suffix (after at least one name token) comes before it; the suffix and
    the suffix / direction tokens right after it stay ("MAIN ST EXT", "CHURCH ST NE"). Without a
    suffix the city cannot be told from the street and nothing is dropped.
    WHY (audit 2026-10-09, phones_lost): "10 SAMPLE RD CHARLOTTE NC 28207" kept CHARLOTTE as a
    street word, so a LiensNC filing for "10 Sample Rd" read as another house (other_address) and
    block_binding removed the filing with the owner's own phone (164 filings among the rows whose
    phone the 10/9 comparison lost; 28 of those phones were the owner's)."""
    j = next((k for k, t in enumerate(toks) if k >= 2 and _ADDR_TAIL_ANCHOR.match(t)), None)
    if j is None:
        return toks
    i = next((k for k in range(1, j) if toks[k] in _ADDR_SUFFIXES
              or (toks[k].isdigit() and toks[k - 1] in _ADDR_ROUTE)), None)
    if i is None:
        return toks
    if toks[i] in _ADDR_ROUTE and i + 1 < j and toks[i + 1].isdigit():
        i += 1                          # "US HWY 70 SAMPLE CITY NC": the route number stays
    end = i + 1
    while end < j and (toks[end] in _ADDR_SUFFIXES or toks[end] in _ADDR_DIRECTIONS):
        end += 1
    return toks[:end]


_UNIT_TOKEN = re.compile(r"^(\d{1,5}[A-Z]?|[A-Z]\d{0,4})$")


def _drop_unit_tail(toks: list[str]) -> list[str]:
    """Street tokens without a unit written after the street's suffix (and direction):
    "SAMPLE ST 14", "SAMPLE RD W C", "SAMPLE BLVD 3C", "SAMPLE PKWY M1100". Not after HWY
    ("HWY 64" names the road) nor after "STATE RD" / "SR" ("STATE RD 1001"); a direction letter
    (N, E, ...) is a direction, not a unit."""
    k = len(toks)
    if k < 3 or not _UNIT_TOKEN.match(toks[-1]) or toks[-1] in _ADDR_DIRECTIONS:
        return toks
    i = k - 2
    while i > 0 and toks[i] in _ADDR_DIRECTIONS:
        i -= 1
    if toks[i] not in _ADDR_SUFFIXES or toks[i] == "HWY" or i == 0:
        return toks
    if toks[i] == "RD" and toks[i - 1] in ("STATE", "SR", "CO"):
        return toks
    return toks[:-1]


def address_key(addr: Any) -> tuple[Optional[str], frozenset, frozenset]:
    """(house number or None, street name tokens, suffix + direction tokens) of an address.
    The city / state / zip after the first comma are dropped (a Nominatim style "804, Trailwinds
    Drive, Oconee County, ..." keeps its second part), "1/2" and a unit tail are dropped, leading
    zeros are stripped ("000399 OAKHILL DRIVE" == "399 OAKHILL DR"), suffixes are normalized
    (ROAD == RD). A placeholder number (all nines, zero) is no number."""
    s = str(addr or "").upper()
    parts = [p.strip() for p in s.split(",")]
    head = parts[0] if parts else ""
    if re.fullmatch(r"\d+[A-Z]?", head) and len(parts) > 1:
        head = f"{head} {parts[1]}"
    head = re.sub(r"\b\d+\s*/\s*\d+\b", " ", head)
    toks = re.findall(r"[A-Z0-9]+", head)
    for i, t in enumerate(toks):
        if i > 0 and t in _ADDR_UNIT:
            toks = toks[:i]
            break
    number = None
    if toks:
        m = re.fullmatch(r"(\d+)([A-Z]?)", toks[0])
        if m:
            digits_ = m.group(1).lstrip("0")
            if digits_ and not (len(digits_) >= 4 and set(digits_) == {"9"}):
                number = digits_ + m.group(2)
            toks = toks[1:]
    toks = _drop_city_tail([_ADDR_ALIAS.get(t, t) for t in toks])
    toks = [t for t in toks if t not in _ADDR_NOISE and not re.fullmatch(r"\d{5}(\d{4})?", t)]
    toks = _drop_unit_tail(toks)
    name = frozenset(t for t in toks if t not in _ADDR_SUFFIXES and t not in _ADDR_DIRECTIONS)
    tail = frozenset(t for t in toks if t in _ADDR_SUFFIXES or t in _ADDR_DIRECTIONS)
    return number, name, tail


def _tails_compatible(ta: frozenset, tb: frozenset) -> bool:
    """Suffix tokens (RD, ST ...) and direction tokens (N, E ...) are each equal or missing on one
    side: "AZALEA RD E" carries "AZALEA RD" (the lien filing left the direction off), "ST EXT" is
    not "ST", and "RD E" is not "RD W"."""
    if ta == tb or not ta or not tb:
        return True
    da, db = ta & _ADDR_DIRECTIONS, tb & _ADDR_DIRECTIONS
    xa, xb = ta - _ADDR_DIRECTIONS, tb - _ADDR_DIRECTIONS
    return (xa == xb or not xa or not xb) and (da == db or not da or not db)


def address_relation(a: Any, b: Any) -> str:
    """'match' | 'conflict' | 'unknown' between a row's address and the one on a county record.
    unknown: either side has no usable house number or street name (a road name alone, a
    placeholder number): nothing is claimed either way. match: same house number, same street
    name tokens, and suffix / direction tokens equal or missing on one side (_tails_compatible).
    conflict: anything else (a different number or street: the record is another property's)."""
    na, sa, ta = address_key(a)
    nb, sb, tb = address_key(b)
    if not na or not nb or not sa or not sb:
        return "unknown"
    if na == nb and sa == sb and _tails_compatible(ta, tb):
        return "match"
    return "conflict"


def address_query(addr: Any) -> Optional[str]:
    """The house number and street NAME of a row's address as a search string ("810 ROBINSON"
    for "810 ROBINSON TERRACE"), or None when the row has no house-numbered address (a road name
    alone cannot identify a parcel). The suffix is left off on purpose: the portals' address
    searches match text as THEY write it (Henderson's "807 ROBINSON TER" is not found by
    "807 ROBINSON TERRACE"); address_relation() then keeps only the exact matches."""
    s = str(addr or "")
    parts = [p.strip() for p in s.split(",")]
    head = parts[0].upper() if parts else ""
    if re.fullmatch(r"\d+[A-Z]?", head) and len(parts) > 1:
        head = f"{head} {parts[1].upper()}"
    head = re.sub(r"\b\d+\s*/\s*\d+\b", " ", head)
    toks = re.findall(r"[A-Z0-9]+", head)
    if not toks or not re.fullmatch(r"\d+[A-Z]?", toks[0]):
        return None
    number, name, _ = address_key(s)
    if not number or not name:
        return None
    stem = [toks[0].lstrip("0") or toks[0]]
    for t in toks[1:]:
        if t in _ADDR_UNIT or t in _ADDR_NOISE:
            break
        a = _ADDR_ALIAS.get(t, t)
        if (a in _ADDR_SUFFIXES or a in _ADDR_DIRECTIONS) and len(stem) > 1 and stem[-1] not in _ADDR_DIRECTIONS:
            break
        stem.append(t)
    return " ".join(stem)




# ---------------------------------------------------------------------------
# case-scoped identity (a verifier with IDENTITY = "case")
# ---------------------------------------------------------------------------
#
# WHY. row_key() is the PROPERTY, right for a fact about the property (a tax bill, a code case,
# an exemption). Some claims are about a CASE that a row ties to a property: a bankruptcy
# filing, a jail booking. Keyed by property, every filing on one parcel shared one verdict, and
# placeholder parcels hold many unrelated ones (2026-10-06 board: about 37 unrelated
# bankruptcy filings on one geo-snapped Anderson SC parcel, 3 on one Lincoln parcel; 91
# Anderson court-case jail rows on one city-owned parcel), so one filing's verdict was attached
# to, and scored on, all of them.
#
# HOW. A case-scoped key is "<case id>@<property key>", for every property key of the row: two
# cases on one parcel are two entries; the same case on two rows of one property is one entry
# (found by any shared property key, as before); the same case on two different parcels is two
# entries (Ledger.find never matches an entry holding a different parcel).
#
# The case id is "<kind>:<hash>", the first 16 hex of a sha256 over the kind and the
# normalized parts (court + docket number; state + county + booking id). Hashed because the
# ledger is pushed to a PUBLIC repo and a refuted verdict means the case belongs to someone
# else: the bankruptcy verifier publishes no docket identifiers on a refuted record, so the key
# must not either. The hash is a pseudonym, not a secret (docket numbers are enumerable).

CASE_SEP = "@"
#: the property-key prefixes row_keys() emits; a case kind can never be one of them
PROPERTY_PREFIXES = ("parcel", "addr", "case", "row")
_KIND = re.compile(r"^[a-z][a-z0-9_]*$")


def case_id(kind: str, *parts: Any) -> Optional[str]:
    """A case identity: f"{kind}:{sha256(kind|parts)[:16]}" over the parts lowercased and cut to
    [a-z0-9] ("3:26-bk-10161" and "326BK10161" are the same part). None when no part has any
    content. `kind` is a short [a-z0-9_] word that is not a property-key prefix."""
    if not _KIND.match(str(kind or "")) or kind in PROPERTY_PREFIXES:
        raise ValueError(f"case kind must be [a-z][a-z0-9_]* and not one of {PROPERTY_PREFIXES}")
    norm = [re.sub(r"[^a-z0-9]", "", str(p if p is not None else "").lower()) for p in parts]
    if not any(norm):
        return None
    return f"{kind}:" + hashlib.sha256("|".join([kind, *norm]).encode("utf-8")).hexdigest()[:16]


def scoped_keys(keys: list[str], case: Optional[str]) -> list[str]:
    """The keys of a row for a case-scoped ledger: "<case>@<key>" for each property key."""
    return [f"{case}{CASE_SEP}{k}" for k in keys] if case else list(keys)


def split_key(key: Any) -> tuple[Optional[str], str]:
    """(case id or None, property key) of a ledger key."""
    k = str(key)
    if k.split(":", 1)[0] in PROPERTY_PREFIXES:
        return None, k
    head, sep, tail = k.partition(CASE_SEP)
    return (head, tail) if sep else (None, k)


def property_part(key: Any) -> str:
    return split_key(key)[1]


def row_fingerprint_case(row: Any) -> str:
    """The case id of last resort for a row a case-scoped verifier applies to but cannot name
    a case for: unique to the row, so it never shares a verdict with another row."""
    return case_id("rowfp", _fingerprint(row)) or "rowfp:none"


def row_summary(row: Any) -> dict:
    """The few fields a ledger entry keeps so a human can read it without the board."""
    out = {k: _get(row, k) for k in ("state", "county", "parcel_id", "street_address",
                                     "listing_type", "source", "owner_name")}
    if not looks_like_address(out.get("street_address")):
        out["street_address"] = None   # notice text in the address field: never published
    return {k: v for k, v in out.items() if v not in (None, "")}


def tier_of(row: Any) -> str:
    """HOT/WARM/COLD (or '') off the row's distress_stack, falling back to grade."""
    raw = _get(row, "raw")
    raw = raw if isinstance(raw, dict) else {}
    tier = ((raw.get("distress_stack") or {}).get("tier")
            or (raw.get("grade") or {}).get("tier") or "")
    return str(tier).upper()


def tier_rank(row: Any) -> int:
    return {"HOT": 0, "WARM": 1, "COLD": 2}.get(tier_of(row), 3)


# ---------------------------------------------------------------------------
# the read side: what a row's raw['verification'] says (scorer, lead signals, dashboard)
# ---------------------------------------------------------------------------

def records_of(raw: Any) -> list[dict]:
    """raw['verification'] as a list of record dicts (tolerates absence and junk)."""
    v = raw.get("verification") if isinstance(raw, dict) else None
    if isinstance(v, dict):
        v = list(v.values())
    if not isinstance(v, list):
        return []
    return [r for r in v if isinstance(r, dict) and r.get("signal")]


def active_records(raw: Any, now: Optional[datetime] = None) -> list[dict]:
    """The row's records that have not expired."""
    t = now or utc_now()
    return [r for r in records_of(raw) if not is_expired(r, t)]


def suppressed_scorer_signals(raw: Any, today: Any = None) -> set[str]:
    """Scorer signal names a non-expired refuted/stale verdict takes out of scoring.

    `today` may be a date (the scorer's reference day) or a datetime; a record expiring
    during that day still counts for the whole day. Names follow each record's `governs`
    list; a "<signal>:<qualifier>" name is a partial rule its reader implements (e.g.
    "recorded_debt:tax": the recorded_debt credit only where the debt is a tax balance)."""
    recs = records_of(raw)
    if not recs:
        return set()
    if today is None:
        now = utc_now()
    elif isinstance(today, datetime):
        now = today if today.tzinfo else today.replace(tzinfo=timezone.utc)
    else:
        now = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    out: set[str] = set()
    for r in recs:
        if r.get("verdict") not in SUPPRESSING or is_expired(r, now):
            continue
        gov = r.get("governs")
        if isinstance(gov, (list, tuple)):
            out.update(str(g) for g in gov if g)
    return out


def qualifiers(drop: Any, signal: str) -> set[str]:
    """The qualifiers a suppressed set holds for `signal`: {"x", ...} for its "<signal>:x"
    entries. For code_enforcement and vacant_structure the qualifier is the raw block's
    `source` (e.g. "code_enforcement:henderson_ordinance_violations_tracking"): the reader ends
    that signal's credit only where the row's block came from that source, so a verdict about
    one source's case never ends another source's block on the same parcel."""
    p = f"{signal}:"
    return {str(d)[len(p):] for d in (drop or ()) if str(d).startswith(p) and len(str(d)) > len(p)}


def block_suppressed(block: Any, sources: set[str]) -> bool:
    """A raw block (code_enforcement, vacancy) whose `source` is in `sources`."""
    return bool(sources) and isinstance(block, dict) and block.get("source") in sources


def verdict_badges(raw: Any, now: Optional[datetime] = None) -> dict[str, str]:
    """{signal: verdict} over the row's non-expired records -- what a dashboard badge shows
    ("tax_lien: confirmed"). Expired records are omitted, never shown as current."""
    return {str(r["signal"]): str(r.get("verdict")) for r in active_records(raw, now)}


def compact(evidence: Any, *, max_items: int = 40) -> Any:
    """Bound an evidence value's size (lists/dicts trimmed) so a ledger line stays small."""
    if isinstance(evidence, dict):
        items = list(evidence.items())[:max_items]
        return {str(k): compact(v, max_items=max_items) for k, v in items}
    if isinstance(evidence, (list, tuple)):
        return [compact(v, max_items=max_items) for v in list(evidence)[:max_items]]
    if isinstance(evidence, str) and len(evidence) > 500:
        return evidence[:500] + "..."
    return evidence


_DIGITS = re.compile(r"\D")


def digits(s: Any) -> str:
    return _DIGITS.sub("", str(s or ""))
