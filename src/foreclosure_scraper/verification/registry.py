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
    WALL: bool                 True for a ToS/CAPTCHA-walled signal whose verify() never
                               touches the network and always returns "wall"
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Optional

import structlog

log = structlog.get_logger()

PACKAGE = "foreclosure_scraper.verification.verifiers"
DEFAULT_RETRY_DAYS = 7.0


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
    if problems:
        raise ContractError(f"{name}: " + "; ".join(problems))
    return Verifier(name=name, signal=sig, version=ver, ttl_days=float(ttl), applies=ap,
                    verify=vf, governs=tuple(gov), source=str(getattr(mod, "SOURCE", "") or ""),
                    retry_days=float(getattr(mod, "RETRY_DAYS", DEFAULT_RETRY_DAYS)),
                    wall=bool(getattr(mod, "WALL", False)), module=mod)


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
