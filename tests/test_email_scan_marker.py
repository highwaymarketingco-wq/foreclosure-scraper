"""THE BUG THIS PINS. enrichment_email_extract writes an EMPTY owner_email block
explicitly to "mark as scanned so we don't re-scan". The idempotence guard tested
`existing.get("emails")` — and `[]` is falsy, so the marker never stopped anything.

On 2026-09-14 the board carried 79,158 empty markers and re-scanned every one on
every run: the storage cost of a marker AND the work it was meant to prevent.

The guard now tests for the KEY, not its contents.
"""
from foreclosure_scraper.enrichment_email_extract import enrich_extract_emails


class _L:
    def __init__(self, raw, source_url=None):
        self.raw = raw
        self.source_url = source_url
        self.description = ""


def test_an_empty_marker_counts_as_scanned():
    marked = _L({"owner_email": {"emails": [], "best_email": None}})
    before = dict(marked.raw["owner_email"])
    enrich_extract_emails([marked], fetch_pages=False)
    # untouched: no rescan, no rewritten timestamp
    assert marked.raw["owner_email"] == before


def test_a_populated_block_still_counts_as_scanned():
    hit = _L({"owner_email": {"emails": [{"email": "a@b.com",
                                          "classification": "owner"}],
                              "best_email": "a@b.com"}})
    before = dict(hit.raw["owner_email"])
    enrich_extract_emails([hit], fetch_pages=False)
    assert hit.raw["owner_email"] == before


def test_an_unscanned_row_still_gets_a_marker():
    fresh = _L({})
    enrich_extract_emails([fresh], fetch_pages=False)
    assert "owner_email" in fresh.raw
    assert "emails" in fresh.raw["owner_email"]
