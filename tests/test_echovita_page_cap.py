"""echovita_obituaries: the listing page cap must not bind before the caught-up stop on a normal backlog.

Source-completeness audit 2026-10-08: the VM's first run returned 576 rows = 2 states x 12 pages x 24
cards, the old cap exactly, while the live NC listing ran past page 40. These tests fail on that cap.
Made-up names in the real Echovita card markup.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.public_notices import echovita_obituaries as ev


def _page(st: str, p: int) -> str:
    cards = []
    for i in range(24):
        slug = f"testa-person{p}x{i}-{p * 100 + i}"
        cards.append(
            f'<div class="obit-list-wrapper"><a class="text-name-obit-in-list text-color-default" '
            f'href="/us/obituaries/{st}/nowhere/{slug}" title="Read the obituary of Testa Person{p}x{i}">'
            f'Testa Person{p}x{i}</a><p class="text-info-obit-in-list"><a class="text-primary" '
            f'title="Obituaries - Nowhere, {"North" if st == "nc" else "South"} Carolina" '
            f'href="/us/obituaries/{st}/nowhere">Nowhere</a></p><p class="text-info-obit-in-list">'
            f'<span class="my-auto">2026</span></p></div>')
    return "".join(cards)


class Fake:
    def __init__(self, pages_per_state: int):
        self.n = pages_per_state
        self.calls: list[str] = []
        self.walled: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None, content_rx=None):
        self.calls.append(url)
        st = "nc" if "/obituaries/nc" in url else "sc"
        p = int(url.split("page=")[1]) if "page=" in url else 1
        return _page(st, p) if p <= self.n else "<html></html>"


def _run(monkeypatch, tmp_path, pages: int):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))     # empty private store
    monkeypatch.setattr(ev, "MAX_DETAIL", 0)
    fake = Fake(pages)
    monkeypatch.setattr(ev, "PoliteFetcher", lambda: fake)
    rows = asyncio.run(ev.EchovitaObituaries().fetch())
    return rows, fake


def test_a_two_week_backlog_is_read_past_the_old_12_page_cap(monkeypatch, tmp_path):
    rows, fake = _run(monkeypatch, tmp_path, pages=20)
    assert len(rows) == 2 * 20 * 24


def test_paging_still_ends_at_the_end_of_the_listing(monkeypatch, tmp_path):
    rows, fake = _run(monkeypatch, tmp_path, pages=3)
    assert len(rows) == 2 * 3 * 24
    assert len(fake.calls) == 2 * 4            # 3 pages with cards + 1 empty page, per state
