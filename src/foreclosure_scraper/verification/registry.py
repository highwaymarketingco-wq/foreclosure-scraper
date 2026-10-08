"""Auto-discovery of verifier modules. There is no registry file to edit: dropping a module into
verification/verifiers/ that follows the contract below is all it takes, so agents adding
verifiers in parallel never touch a shared file.

THE CONTRACT (module-level names; checked here, a module that breaks it is logged and skipped,
it never takes the other verifiers down with it):

    SIGNAL: str        the claim it checks; also the ledger file name
                       (docs/handoff/verification/<SIGNAL>.json). Several modules may share a
                       SIGNAL (one per county/vendor: tax_lien_buncombe, tax_lien_ptscloud...);
                       their applies() must not overlap.
    VERSION: str       bump it when the verdict logic changes: every ledger entry checked by
                       an older version becomes due again.
    TTL_DAYS: float    how long a verdict stays good; past it the sweep re-checks and the
                       scorer stops honouring it.
    applies(row: dict) -> bool
                       pure, no I/O: does this verifier cover this board row? `row` is a board
                       dict exactly as board_stream.iter_board_rows() yields it.
    async verify(row: dict, client) -> core.VerificationResult
                       the live check. `client` is a verification.fetch.Fetcher (get_text /
                       get_json through http_client's per-host throttle). Return a result for
                       every outcome, including failures (verdict "unconfirmed"); raising is
                       treated as unconfirmed by the sweep.

Optional:
    GOVERNS: tuple[str, ...]   scorer signal names a refuted/stale verdict removes (default ())
    SOURCE: str                default `source` for the ledger summary
    RETRY_DAYS: float          when an `unconfirmed` answer is retried (default 7)
    TRANSIENT_REASONS: tuple   `unconfirmed` reasons that are about the SOURCE's health at check
                               time (an HTTP 503, an error page, a timeout), not about the row:
                               such an answer is retried after TRANSIENT_RETRY_DAYS instead of
                               RETRY_DAYS, and the sweep re-queues it once at the end of its run
                               (ledger.is_due, scripts/verification_sweep.py). The sweep's own
                               "verifier_error" (a crash or a per-row timeout) is always one
                               (ledger.SWEEP_TRANSIENT_REASONS).
    TRANSIENT_RETRY_DAYS: float  default 0.25 (6 hours)
    WALL: bool                True for a ToS/CAPTCHA-walled signal whose verify() never
                               touches the network and always returns "wall"
    ROW_SUMMARY_EXCLUDE: tuple core.row_summary() fields the sweep leaves out of this signal's
                               ledger entries (the ledger is pushed to a PUBLIC repo; e.g.
                               jail_booking drops owner_name)
    IDENTITY: str              "property" (default) or "case". Property: the ledger is keyed by
                               the row's property (core.row_keys), and every row of a parcel
                               shares one verdict: right for a fact about the property (a tax
                               bill, a code case, an exemption). Case: the claim is about a
                               CASE the row ties to a property (a bankruptcy filing, a jail
                               booking, a lis pendens), so the ledger is keyed by case id +
                               property (core.scoped_keys): two cases on one parcel get two
                               verdicts, the same case on two rows of one property shares one,
                               and a case on two parcels is two entries. Requires:
    case_identity(row) -> str | None
                               pure, no I/O: the row's case id, built with core.case_id(kind,
                               *parts) (e.g. case_id("bk", court, docket_number)). It must
                               accept a board dict AND a models.Listing (the VM's apply step
                               calls it on Listings; read fields with getattr when the row is
                               not a dict). None when the row names no case: the sweep then
                               keys that row by its own fingerprint (never shared), the apply
                               step attaches nothing of this verifier to it.
    case_identity_of_record(record) -> str | None
                               optional, only for ledger.migrate_to_case_scope(): the case a
                               stored ledger record's evidence names (e.g. bankruptcy
                               confirmed/stale publish court + docket number).
    governs_for(record: dict) -> tuple[str, ...]
                               optional, pure: the scorer signal names THIS answer's
                               refuted/stale verdict removes, from the stored record
                               ({verdict, evidence, ...}); GOVERNS is the default for an answer it
                               returns nothing for. A verdict about the claim "this property is
                               delinquent now" must not take away a signal the same evidence
                               confirms (tax_lien: a chronic late payer keeps tax_lien_chronic
                               when its current claim is refuted). The sweep stores the result in
                               the ledger entry's `governs`; the apply step recomputes it from the
                               record, so it never needs a ledger rewrite.
    DETAIL_KEYS: tuple         lazy-detail raw keys the verifier reads (e.g. ("comps",)). The
                               published board keeps comps/vision/cama/rent_comps/
                               foreclosure_sold_comps in the index-aligned sidecar
                               (docs/listings_detail.json.gz), not in the rows board_stream
                               yields; when a selected verifier names any, the sweep streams
                               the sidecar alongside (board_stream.iter_board_rows_with_detail)
                               and merges just those keys into each row's raw before applies().
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Optional

import structlog

from .core import row_fingerprint_case, row_keys, scoped_keys

log = structlog.get_logger()

PACKAGE = "foreclosure_scraper.verification.verifiers"
DEFAULT_RETRY_DAYS = 7.0
DEFAULT_TRANSIENT_RETRY_DAYS = 0.25


@dataclass(frozen=True)
class Verifier:
    name: str                      # module name, e.g. "tax_lien_buncombe"
    signal: str
    version: str
    ttl_days: float
    applies: Callable[[dict], bool]
    verify: Callable[..., Any]
    governs: tuple[str, ...] = ()
    source: str = ""
    retry_days: float = DEFAULT_RETRY_DAYS
    wall: bool = False
    module: Any = None
    identity: str = "property"     # or "case" (see IDENTITY in the module docstring)
    case_identity: Optional[Callable[[Any], Optional[str]]] = None
    detail_keys: tuple[str, ...] = ()   # lazy-detail raw keys it reads (DETAIL_KEYS)
    governs_fn: Optional[Callable[[dict], Any]] = None   # per-record governs (module governs_for)
    transient_reasons: tuple[str, ...] = ()   # TRANSIENT_REASONS (source health, not the row)
    transient_retry_days: float = DEFAULT_TRANSIENT_RETRY_DAYS

    def is_transient(self, record: Any) -> bool:
        """True for an `unconfirmed` answer whose reason is about the source's health at check
        time: this verifier's TRANSIENT_REASONS, or the sweep's own verifier_error."""
        from .ledger import SWEEP_TRANSIENT_REASONS    # lazy: ledger imports nothing from here
        if not isinstance(record, dict) or record.get("verdict") != "unconfirmed":
            return False
        ev = record.get("evidence")
        reason = ev.get("reason") if isinstance(ev, dict) else None
        return bool(reason) and (reason in self.transient_reasons
                                 or reason in SWEEP_TRANSIENT_REASONS)

    def governs_of(self, record: Any) -> tuple[str, ...]:
        """The scorer signals this record's refuted/stale verdict removes: the module's
        governs_for(record) when it has one, else GOVERNS. Never raises."""
        if self.governs_fn is None or not isinstance(record, dict):
            return self.governs
        try:
            out = self.governs_fn(record)
            return tuple(str(g) for g in out)
        except Exception as exc:  # noqa: BLE001 - the module's GOVERNS is the safe default
            log.warning("verification.governs_for_failed", verifier=self.name,
                        error=f"{type(exc).__name__}: {str(exc)[:160]}")
            return self.governs

    def case_of(self, row: Any) -> Optional[str]:
        """The row's case id (case-scoped verifiers), None for a property-scoped one or when
        the row names no case. Never raises."""
        if self.identity != "case" or self.case_identity is None:
            return None
        try:
            return self.case_identity(row) or None
        except Exception as exc:  # noqa: BLE001 - an odd row names no case
            log.warning("verification.case_identity_failed", verifier=self.name,
                        error=f"{type(exc).__name__}: {str(exc)[:160]}")
            return None

    def ledger_keys(self, row: Any) -> list[str]:
        """The keys this verifier's ledger knows the row by: core.row_keys() for a
        property-scoped verifier; for a case-scoped one the same keys scoped by the row's case
        id, or by the row's own fingerprint when it names no case (never shared)."""
        keys = row_keys(row)
        if self.identity != "case":
            return keys
        return scoped_keys(keys, self.case_of(row) or row_fingerprint_case(row))

    def safe_applies(self, row: dict) -> bool:
        try:
            return bool(self.applies(row))
        except Exception as exc:  # noqa: BLE001 - one bad row never stops a sweep
            log.warning("verification.applies_failed", verifier=self.name,
                        error=f"{type(exc).__name__}: {str(exc)[:160]}")
            return False


class ContractError(ValueError):
    pass


def from_module(mod: Any, name: Optional[str] = None) -> Verifier:
    """A Verifier from a module object, or ContractError saying what is missing."""
    name = name or mod.__name__.rsplit(".", 1)[-1]
    sig = getattr(mod, "SIGNAL", None)
    ver = getattr(mod, "VERSION", None)
    ttl = getattr(mod, "TTL_DAYS", None)
    ap = getattr(mod, "applies", None)
    vf = getattr(mod, "verify", None)
    problems = []
    if not isinstance(sig, str) or not sig or not sig.replace("_", "").isalnum():
        problems.append("SIGNAL must be a non-empty [a-z0-9_] string")
    if not isinstance(ver, str) or not ver:
        problems.append("VERSION must be a non-empty string")
    if not isinstance(ttl, (int, float)) or ttl <= 0:
        problems.append("TTL_DAYS must be a positive number")
    if not callable(ap):
        problems.append("applies(row) is missing")
    if not inspect.iscoroutinefunction(vf):
        problems.append("verify(row, client) must be an async function")
    gov = getattr(mod, "GOVERNS", ())
    if not isinstance(gov, (tuple, list)) or not all(isinstance(g, str) for g in gov):
        problems.append("GOVERNS must be a tuple of scorer signal names")
    ident = getattr(mod, "IDENTITY", "property")
    cid = getattr(mod, "case_identity", None)
    if ident not in ("property", "case"):
        problems.append('IDENTITY must be "property" or "case"')
    elif ident == "case" and not callable(cid):
        problems.append('IDENTITY = "case" needs case_identity(row)')
    dk = getattr(mod, "DETAIL_KEYS", ())
    if not isinstance(dk, (tuple, list)) or not all(isinstance(k, str) and k for k in dk):
        problems.append("DETAIL_KEYS must be a tuple of raw key names")
    gf = getattr(mod, "governs_for", None)
    if gf is not None and not callable(gf):
        problems.append("governs_for must be a function of the stored record")
    tr = getattr(mod, "TRANSIENT_REASONS", ())
    if not isinstance(tr, (tuple, list, frozenset, set)) or not all(isinstance(x, str) and x for x in tr):
        problems.append("TRANSIENT_REASONS must be a tuple of reason strings")
    trd = getattr(mod, "TRANSIENT_RETRY_DAYS", DEFAULT_TRANSIENT_RETRY_DAYS)
    if not isinstance(trd, (int, float)) or trd < 0:
        problems.append("TRANSIENT_RETRY_DAYS must be a number >= 0")
    if problems:
        raise ContractError(f"{name}: " + "; ".join(problems))
    return Verifier(name=name, signal=sig, version=ver, ttl_days=float(ttl), applies=ap,
                    verify=vf, governs=tuple(gov), source=str(getattr(mod, "SOURCE", "") or ""),
                    retry_days=float(getattr(mod, "RETRY_DAYS", DEFAULT_RETRY_DAYS)),
                    wall=bool(getattr(mod, "WALL", False)), module=mod, identity=ident,
                    case_identity=cid if ident == "case" else None, detail_keys=tuple(dk),
                    governs_fn=gf, transient_reasons=tuple(sorted(tr)),
                    transient_retry_days=float(trd))


def discover(package: str = PACKAGE) -> list[Verifier]:
    """Every verifier module in `package`, sorted by module name. Modules whose name starts
    with "_" are skipped; a module that fails to import or breaks the contract is logged
    (verification.verifier_skipped) and skipped."""
    try:
        pkg = importlib.import_module(package)
    except Exception as exc:  # noqa: BLE001
        log.error("verification.package_unimportable", package=package,
                  error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return []
    out: list[Verifier] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_") or info.ispkg:
            continue
        try:
            mod = importlib.import_module(f"{package}.{info.name}")
            out.append(from_module(mod, info.name))
        except Exception as exc:  # noqa: BLE001
            log.warning("verification.verifier_skipped", module=info.name,
                        error=f"{type(exc).__name__}: {str(exc)[:300]}")
    return out


def by_signal(verifiers: list[Verifier]) -> dict[str, list[Verifier]]:
    out: dict[str, list[Verifier]] = {}
    for v in verifiers:
        out.setdefault(v.signal, []).append(v)
    return out


def verifier_for(row: dict, verifiers: list[Verifier], signal: Optional[str] = None
                 ) -> Optional[Verifier]:
    """The first verifier (by module name) of `signal` (or any signal) that applies to `row`."""
    for v in verifiers:
        if signal is not None and v.signal != signal:
            continue
        if v.safe_applies(row):
            return v
    return None
