"""Shared pytest fixtures.

The ArcGIS circuit-breaker (enrichment_arcgis) keeps process-wide state in
``_WALLED_HOSTS`` / ``_HOST_FAILS`` — correct in production (one process = one
run), but it leaks BETWEEN tests: a test that trips a host (e.g. nconemap.gov)
would leave it walled and silently short-circuit a later test's _arc_query. This
autouse fixture clears that state before every test so each starts with a clean
breaker.
"""
import pytest

from foreclosure_scraper import enrichment_arcgis as _arcgis


@pytest.fixture(autouse=True)
def _reset_arcgis_breaker():
    _arcgis._WALLED_HOSTS.clear()
    _arcgis._HOST_FAILS.clear()
    yield
    _arcgis._WALLED_HOSTS.clear()
    _arcgis._HOST_FAILS.clear()
