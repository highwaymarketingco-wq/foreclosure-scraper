"""Hard-fail guard for sources that harvest a DECLARED SET of layers/endpoints.

WHY THIS EXISTS (the failure family it closes):
    A source that loops over N layers and does ``except Exception: continue``
    ships N-1 layers' worth of leads and logs a WARNING nobody reads. The run
    report sees a plausible number, ``expected_min_count`` is a floor rather
    than a contract, and the loss is indistinguishable from the real-world
    shrinkage these sources legitimately show week to week.

    Measured instances:
      * ``counties_sc.pickens_delinquent_parcels`` emitted 1,977 instead of
        2,161 because ONE of its 8 GIS services 404'd. ``expected_min_count``
        was 1500, so a 184-lead hole sailed through.
      * The Helene damage enricher stamped 476 on one run and 521 on two
        others — one of its five layers flaked, and the only trace was a
        ``helene.fetch_fail`` line.

    This is the same shape as the two outages that cost the most: the upset-bid
    source that went dead and looked merely empty for months, and the SCDOT
    token wall that answers HTTP 200 with an error body.

THE RULE THIS ENFORCES:
    A partial harvest is a HARD FAILURE, not a quiet one.

    ``BaseScraper.safe_run`` already classifies a RAISED error correctly
    (OUTCOME_ERROR, with the reason in the run report). It cannot classify a
    SHORT RETURN at all — 1,977 rows and 2,161 rows are both just "some rows".
    So the guard converts "a declared layer did not come back" from a return
    value into an exception, which the existing machinery already reports.

USAGE (the whole API):

    from ..layer_guard import LayerHarvest

    guard = LayerHarvest(MyScraper.slug, [layer.service for layer in LAYERS])
    with guard:                                   # verify() runs on clean exit
        for layer in LAYERS:
            rows = await guard.harvest(layer.service, fetch_layer(http, layer))
            ...

Three distinct losses are caught, all of which currently return quietly:

    failed        the layer raised (404, WAF, timeout, error body, parse blowup)
    never run     the layer was declared but never attempted — this is what an
                  early ``break``/``return`` out of the harvest loop looks like
    short         the layer answered but returned fewer rows than its declared
                  floor (opt in per layer by passing a mapping, see below)

RETIRING A LAYER IS A CODE CHANGE, NOT A LOG LINE:
    These county services genuinely do get renamed and retired between cycles.
    When that happens the fix is to delete the layer from the declared set (or
    name it in ``tolerate=``) in a reviewed commit — NOT to let the source
    silently shrink. That is the entire point: the loss becomes a decision
    somebody made, instead of a number nobody compared.
"""
from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Iterable, Mapping, Sequence

import structlog

log = structlog.get_logger()

__all__ = [
    "LayerHarvest",
    "PartialHarvest",
    "arcgis_error",
    "raise_for_arcgis_error",
]


class PartialHarvest(RuntimeError):
    """A source finished with fewer live layers than it declared.

    Raised (never returned) so ``BaseScraper.safe_run`` records OUTCOME_ERROR
    with the failing layer names, instead of shipping a short harvest that
    reads as ordinary shrinkage.
    """


def arcgis_error(payload: Any) -> str | None:
    """The error message inside an ArcGIS JSON body, or None if it is clean.

    ArcGIS answers a dead/renamed/token-walled layer with **HTTP 200** and
    ``{"error": {...}}`` — no features key at all. Any caller that does
    ``data.get("features") or []`` therefore reads a dead layer as an empty
    one. Route every hand-rolled ArcGIS response through here.
    """
    if not isinstance(payload, dict):
        return None
    err = payload.get("error")
    if not err:
        return None
    if isinstance(err, dict):
        code = err.get("code")
        msg = err.get("message") or err.get("description") or ""
        details = err.get("details")
        if isinstance(details, (list, tuple)) and details:
            msg = f"{msg}: {'; '.join(str(d) for d in details)}"
        return f"ArcGIS error {code}: {msg}"[:300] if code else str(msg)[:300]
    return str(err)[:300]


def raise_for_arcgis_error(url: str, payload: Any) -> None:
    """Turn an HTTP-200-with-error-body into an exception.

    Kept here (rather than only inside ``arcgis_webmap.query_features``) so the
    hand-rolled ``httpx.get(.../query)`` call sites can adopt it without taking
    on the full paginator.
    """
    msg = arcgis_error(payload)
    if msg:
        from .arcgis_webmap import ArcGisError

        raise ArcGisError(f"{url} -> {msg}")


class LayerHarvest:
    """Declare the layer set up front; every declared layer must report back.

    Args:
        source: slug of the owning scraper/enricher, used in the error text.
        layers: the declared layer names. Either an iterable of names, or a
            mapping ``{name: min_rows}`` to also assert a per-layer floor
            (``0`` = no floor, which is the default for the iterable form).
            A floor is worth setting only where a genuine 0 is impossible;
            a historical roll that is allowed to empty out should stay at 0.
        tolerate: layer names whose failure is a KNOWN, accepted loss. Use this
            to keep a decaying layer's code in place while its absence stops
            failing the run — an explicit, reviewable exemption rather than a
            blanket ``except: continue``.
        attempts: tries per layer before it counts as dead. The shared
            ``http_client`` is built with ``retries=0`` ("callers already wrap
            their own AsyncRetrying"), so without this a one-off ReadError would
            fail the whole source — trading a silent shortfall for a noisy
            flake. Retrying needs a re-callable unit of work, so pass a zero-arg
            callable to :meth:`harvest` (a bare coroutine can only be awaited
            once and is therefore capped at one attempt).
        retry_delay_s: base linear backoff between attempts.

    The instance is also a context manager: leaving the ``with`` block without
    an exception calls :meth:`verify`, so an early ``return``/``break`` out of
    the harvest loop cannot skip the check.
    """

    def __init__(
        self,
        source: str,
        layers: Iterable[str] | Mapping[str, int],
        *,
        tolerate: Iterable[str] = (),
        attempts: int = 2,
        retry_delay_s: float = 2.0,
    ) -> None:
        if isinstance(layers, Mapping):
            declared = {str(k): int(v or 0) for k, v in layers.items()}
        else:
            names = [str(n) for n in layers]
            dupes = {n for n in names if names.count(n) > 1}
            if dupes:
                raise ValueError(
                    f"{source}: duplicate declared layer names {sorted(dupes)} — "
                    "layer names are the guard's keys and must be unique")
            declared = {n: 0 for n in names}
        if not declared:
            raise ValueError(f"{source}: LayerHarvest needs at least one declared layer")

        self.source = source
        self._declared: dict[str, int] = declared
        self.attempts = max(1, int(attempts))
        self.retry_delay_s = float(retry_delay_s)
        self._tolerate = {str(t) for t in tolerate}
        unknown = self._tolerate - set(declared)
        if unknown:
            raise ValueError(
                f"{source}: tolerate names {sorted(unknown)} are not declared layers")
        self._rows: dict[str, int] = {}
        self._failed: dict[str, str] = {}

    # -- recording ---------------------------------------------------------

    def _assert_declared(self, layer: str) -> None:
        if layer not in self._declared:
            raise ValueError(
                f"{self.source}: layer {layer!r} was reported but never declared "
                f"(declared: {sorted(self._declared)}) — the declared set is the "
                "contract, so an undeclared layer is a wiring bug")

    def ok(self, layer: str, rows: int = 0) -> None:
        """Record that ``layer`` was read end-to-end, yielding ``rows`` rows."""
        self._assert_declared(layer)
        self._failed.pop(layer, None)
        self._rows[layer] = int(rows)

    def failed(self, layer: str, reason: str) -> None:
        """Record that ``layer`` could not be read. Does not raise on its own —
        :meth:`verify` reports every loss at once so one run diagnoses the
        whole outage rather than only its first layer."""
        self._assert_declared(layer)
        self._rows.pop(layer, None)
        self._failed[layer] = str(reason)[:300]
        log.warning("layer_harvest.layer_failed", source=self.source,
                    layer=layer, reason=self._failed[layer],
                    tolerated=layer in self._tolerate)

    async def harvest(self, layer: str, work: Any, *,
                      attempts: int | None = None) -> list[Any]:
        """Run one layer's fetch, recording success or (final) failure.

        ``work`` is either a zero-arg callable returning an awaitable — the
        retryable form, use this — or a bare coroutine, which can only be
        awaited once and so gets a single attempt. It must resolve to a
        sequence (the layer's rows).

        On failure this returns ``[]`` so the caller's loop body stays simple.
        The loss is NOT hidden: it is banked and re-raised by :meth:`verify`.
        """
        self._assert_declared(layer)
        tries = self.attempts if attempts is None else max(1, int(attempts))
        if not callable(work):
            if tries > 1 and attempts is not None:
                raise ValueError(
                    f"{self.source}/{layer}: attempts>1 needs a zero-arg callable — "
                    "a coroutine object cannot be awaited twice")
            tries = 1

        for i in range(tries):
            try:
                result = await (work() if callable(work) else work)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — banked, re-raised by verify()
                if i + 1 < tries:
                    log.info("layer_harvest.retry", source=self.source, layer=layer,
                             attempt=i + 1, of=tries,
                             error=f"{type(exc).__name__}: {exc}"[:200])
                    await asyncio.sleep(self.retry_delay_s * (i + 1))
                    continue
                self.failed(layer, f"{type(exc).__name__}: {exc}")
                return []
            rows: Sequence[Any] = result if result is not None else []
            try:
                n = len(rows)
            except TypeError:  # a non-sized payload still counts as one live layer
                n = 1
            self.ok(layer, n)
            return list(rows) if not isinstance(rows, list) else rows
        return []

    # -- reporting ---------------------------------------------------------

    @property
    def live(self) -> int:
        return len(self._rows)

    @property
    def declared(self) -> int:
        return len(self._declared)

    @property
    def rows(self) -> int:
        return sum(self._rows.values())

    def stats(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "declared": self.declared,
            "live": self.live,
            "rows": self.rows,
            "failed": sorted(self._failed),
            "never_run": sorted(self._never_run()),
        }

    def _never_run(self) -> list[str]:
        return [n for n in self._declared
                if n not in self._rows and n not in self._failed]

    def _short(self) -> list[str]:
        return [f"{n} returned {self._rows[n]} rows (floor {self._declared[n]})"
                for n in self._declared
                if self._declared[n] and n in self._rows
                and self._rows[n] < self._declared[n]]

    def verify(self) -> None:
        """Raise :class:`PartialHarvest` unless every declared layer came back.

        Tolerated layers are exempt from all three checks.
        """
        dead = {n: r for n, r in self._failed.items() if n not in self._tolerate}
        never = [n for n in self._never_run() if n not in self._tolerate]
        short = [s for s in self._short() if s.split()[0] not in self._tolerate]

        if not dead and not never and not short:
            log.info("layer_harvest.ok", **self.stats())
            return

        # The lost layer NAMES lead the message. BaseScraper.safe_run truncates
        # last_reason to 160 chars for the run report, and "which layer died" is
        # the only part of this that is immediately actionable — it must not be
        # what falls off the end.
        lost = sorted(set(dead) | set(never) | {s.split()[0] for s in short})

        parts: list[str] = []
        if dead:
            parts.append("failed [" + "; ".join(
                f"{n}: {r}" for n, r in sorted(dead.items())) + "]")
        if never:
            parts.append("never attempted [" + ", ".join(sorted(never)) + "]")
        if short:
            parts.append("short [" + "; ".join(sorted(short)) + "]")

        raise PartialHarvest(
            f"{self.source}: partial harvest, lost {', '.join(lost)} "
            f"({self.live}/{self.declared} declared layers alive; {self.rows} rows "
            f"discarded rather than shipped as a smaller harvest). "
            + " | ".join(parts))

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "LayerHarvest":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        # Only verify on a clean exit: an in-flight exception is already a hard
        # failure and must not be masked by the partial-harvest one.
        if exc_type is None:
            self.verify()
        return False
