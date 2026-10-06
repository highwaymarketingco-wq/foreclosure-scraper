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
row_key()'s docstring for the measurement on real boards that chose it.
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
    if a and (st or co) and _house_numbered(a):
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


def row_summary(row: Any) -> dict:
    """The few fields a ledger entry keeps so a human can read it without the board."""
    out = {k: _get(row, k) for k in ("state", "county", "parcel_id", "street_address",
                                     "listing_type", "source", "owner_name")}
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
