"""Spartanburg MIE: the manual lane reads PDFs a person saved when the county site blocks scripts.

Audit 2026-10-08: www.spartanburgcounty.gov answers both document URLs with Cloudflare's
"you have been blocked" page (403) to the VM and the residential Mac alike, so the source
returned 0 for 2 runs. The walls card "spartanburg_site" has a person save the PDFs in a normal
browser; nothing read them. Fixture rows are invented.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc import spartanburg_master_in_equity as sp


class _Resp:
    status_code = 403
    content = b"<!DOCTYPE html>blocked"


def _patch_blocked(monkeypatch, parsed_urls):
    class _Client:
        async def get(self, url, **_kw):
            return _Resp()

    @asynccontextmanager
    async def _client(**_kw):
        yield _Client()

    def _parse(data, url):
        parsed_urls.append(url)
        return [Listing(source=sp.SpartanburgMasterInEquity.slug, source_url=url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN, state="SC", county="Spartanburg",
                        case_number="26-0001", sale_date=datetime(2026, 11, 2),
                        raw={"spartanburg_pdf": {"status": ""}})]

    monkeypatch.setattr(sp, "client", _client)
    monkeypatch.setattr(sp, "_parse_pdf_tables", _parse)


def test_saved_pdfs_are_read_when_the_site_blocks(monkeypatch, tmp_path):
    (tmp_path / "spartanburg_sc_mie_2026-10-01.pdf").write_bytes(b"%PDF-1.4 roster")
    (tmp_path / "spartanburg_sc_deficiency_2026-10-01.pdf").write_bytes(b"%PDF-1.4 deficiency")
    (tmp_path / "unrelated.pdf").write_bytes(b"%PDF-1.4 other")
    monkeypatch.setenv("SPARTANBURG_MIE_PDF_DIR", str(tmp_path))
    parsed: list[str] = []
    _patch_blocked(monkeypatch, parsed)
    out = list(asyncio.run(sp.SpartanburgMasterInEquity().fetch()))
    assert sorted(parsed) == sorted(sp.PDF_URLS[:2])     # each saved file parsed as its URL
    assert len(out) == 2
    assert all(li.raw["spartanburg_pdf"].get("from_saved_pdf") is True for li in out)


def test_no_folder_set_reads_nothing(monkeypatch, tmp_path):
    (tmp_path / "spartanburg_sc_mie_2026-10-01.pdf").write_bytes(b"%PDF-1.4 roster")
    monkeypatch.delenv("SPARTANBURG_MIE_PDF_DIR", raising=False)
    parsed: list[str] = []
    _patch_blocked(monkeypatch, parsed)
    assert list(asyncio.run(sp.SpartanburgMasterInEquity().fetch())) == []
