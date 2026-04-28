"""Auto-discover all BaseScraper subclasses across the scrapers package."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Type

from ..base_scraper import BaseScraper

_PACKAGES = (
    "foreclosure_scraper.scrapers.national",
    "foreclosure_scraper.scrapers.public_notices",
    "foreclosure_scraper.scrapers.law_firms",
    "foreclosure_scraper.scrapers.counties_sc",
    "foreclosure_scraper.scrapers.counties_nc",
    "foreclosure_scraper.scrapers.newspapers",
    "foreclosure_scraper.scrapers.reo",
)


def _iter_modules(pkg_name: str):
    pkg = importlib.import_module(pkg_name)
    for _, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg or name.startswith("_"):
            continue
        yield importlib.import_module(f"{pkg_name}.{name}")


def discover() -> list[Type[BaseScraper]]:
    """Return all concrete BaseScraper subclasses across the source tree."""
    found: list[Type[BaseScraper]] = []
    for pkg in _PACKAGES:
        try:
            for mod in _iter_modules(pkg):
                for _, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(obj, BaseScraper)
                        and obj is not BaseScraper
                        and obj.__module__ == mod.__name__
                    ):
                        found.append(obj)
        except ModuleNotFoundError:
            continue
    return found


def all_scrapers() -> list[BaseScraper]:
    return [cls() for cls in discover()]
