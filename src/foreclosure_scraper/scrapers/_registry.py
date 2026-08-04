"""Auto-discover all BaseScraper subclasses across the scrapers package."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import traceback
from typing import Type

import structlog

from ..base_scraper import BaseScraper

log = structlog.get_logger()

_PACKAGES = (
    "foreclosure_scraper.scrapers.national",
    "foreclosure_scraper.scrapers.public_notices",
    "foreclosure_scraper.scrapers.law_firms",
    "foreclosure_scraper.scrapers.counties_sc",
    "foreclosure_scraper.scrapers.counties_nc",
    "foreclosure_scraper.scrapers.counties_generic",
    "foreclosure_scraper.scrapers.newspapers",
    "foreclosure_scraper.scrapers.reo",
    "foreclosure_scraper.scrapers.city_websites",
)


def _module_names(pkg_name: str):
    """Yield importable module NAMES (not modules) so discover() can import each
    one inside its own try/except. Listing names cannot fail per-module the way
    importing can, which is what keeps one bad module from hiding the rest."""
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:  # noqa: BLE001 - a dead package must not kill the others
        log.error("registry.package_import_failed", package=pkg_name,
                  traceback=traceback.format_exc())
        return
    for _, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg or name.startswith("_"):
            continue
        yield f"{pkg_name}.{name}"


def _iter_modules(pkg_name: str):
    """Back-compat shim: yields imported modules, skipping ones that fail."""
    for mod_name in _module_names(pkg_name):
        try:
            yield importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            log.error("registry.module_import_failed", module=mod_name,
                      traceback=traceback.format_exc())
            continue


def discover() -> list[Type[BaseScraper]]:
    """Return all concrete BaseScraper subclasses across the source tree.

    The try/except sits INSIDE the module loop on purpose. It used to wrap the
    whole ``for mod in _iter_modules(pkg)`` loop, so a single un-importable module
    aborted enumeration of every module after it in that package. Measured when a
    new module imported a helper that did not exist yet: discover() returned 105
    instead of 132 — 27 scrapers vanished, including sc_public_index (3,628 board
    rows), spartanburg_vacant (3,307) and spartanburg_delinquent_tax (2,095). The
    run reported no error; those sources simply were not there.

    A scraper that fails to import is the purest form of the failure this project
    keeps hitting: a dead source that looks like an absent one. So one bad module
    now costs exactly one module, and it is logged at ERROR rather than passed
    over in silence.
    """
    found: list[Type[BaseScraper]] = []
    for pkg in _PACKAGES:
        for mod_name in _module_names(pkg):
            try:
                mod = importlib.import_module(mod_name)
            except Exception:  # noqa: BLE001 - one bad module must not hide the rest
                log.error("registry.module_import_failed", module=mod_name,
                          traceback=traceback.format_exc())
                continue
            for _, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, BaseScraper)
                    and obj is not BaseScraper
                    and obj.__module__ == mod.__name__
                ):
                    found.append(obj)
    return found


def all_scrapers() -> list[BaseScraper]:
    return [cls() for cls in discover()]
