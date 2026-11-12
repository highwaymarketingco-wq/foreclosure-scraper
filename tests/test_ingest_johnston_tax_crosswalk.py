"""scripts/ingest_johnston_tax_crosswalk.py's board-I/O rewrite (2026-10-20): the original
version called load_board()/write_artifact() to run a scoped dedupe() pass, which still fully
materializes and re-serializes the WHOLE board -- proven impractical tonight on a real VM run
(2+ hours, 62GB of disk I/O for a 5GB dataset, killed safely). This test proves the replacement
mechanism works correctly end-to-end, without touching the real board or the network:
JohnstonDelinquentTaxCrosswalk is replaced with a small fake whose safe_run() returns canned
Listings (mimicking the real scraper's to_listing() output exactly), since a real crosswalk run
(the live file download + NC OneMap querying) is out of scope here.

Covers:
  1. _existing_johnston_keys() finds exactly the Johnston NC dedupe_key()s on the board,
     correctly normalizing a dash-formatted existing parcel_id to match a bare-digit resolved
     PIN, and does NOT collide across counties/states that happen to share the same bare PIN
     digits (the scoping safety the module docstring claims).
  2. _classify() splits resolved leads into the "merge into an existing row" (patch) group and
     the "genuinely new" (append) group by exact dedupe_key() match, and keeps the first of a
     same-run PIN collision rather than silently dropping or crashing.
  3. main() end-to-end: a lead matching an existing board row lands via patch_existing_rows()
     (merged into raw, nothing else on that row touched); genuinely new leads land via
     append_new_rows() as new board rows; rows outside both groups are completely untouched.
  4. dry-run never touches the board.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ingest_johnston_tax_crosswalk as ij  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.johnston_delinquent_tax_crosswalk import (  # noqa: E402
    RAW_KEY,
)


def _board_row(i: int, **kw) -> Listing:
    base = dict(source="counties_nc.nc_heir_estate_parcels",
               source_url=f"https://example.test/estate/{i}",
               listing_type=ListingType.ESTATE_LEAD, property_kind=PropertyKind.UNKNOWN,
               state="NC", county="Johnston", parcel_id=None,
               street_address=f"{i + 1} Main St", zip_code="27520",
               owner_name=f"Owner {i}", raw={})
    base.update(kw)
    return Listing(**base)


def _crosswalk_listing(legacy_parcel: str, pin: str, *, county="Johnston", state="NC",
                       address: str, total: float = 1234.56) -> Listing:
    """Mimics johnston_delinquent_tax_crosswalk.to_listing()'s exact output shape for one
    MATCHED legacy parcel -- a resolved PIN, a tax-lien raw block, nothing else."""
    return Listing(
        source="counties_nc.johnston_delinquent_tax_crosswalk",
        source_url="https://www.johnstonnc.gov/files/taxoffice/DelinquentTaxPublicRecordsFile1.txt",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state=state, county=county, parcel_id=pin, street_address=address,
        defendant=f"Owner of {address}", owner_name=f"Owner of {address}",
        foreclosure_process="tax",
        raw={RAW_KEY: {
            "legacy_parcel": legacy_parcel, "resolved_pin": pin,
            "years_delinquent": 2, "delinquent_by_year": {"2025": total},
            "total_delinquent": total, "crosswalk_method": "nc_onemap_owner_address_match",
            "crosswalk_confidence": "unique_address_match",
        }},
    )


class _FakeScraper:
    """Stands in for JohnstonDelinquentTaxCrosswalk() -- no network, no real BaseScraper
    machinery, just safe_run() returning canned Listings, exactly the contract _fetch_new() in
    the script relies on."""

    def __init__(self, listings: list[Listing]):
        self._listings = listings
        self.last_outcome = "ok"
        self.run_stats = {"matched": len(listings)}

    async def safe_run(self) -> list[Listing]:
        return list(self._listings)


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    """Redirect the script's own REPO to an isolated tmp tree, same convention as
    test_resolver_backfill_parcel_patch_integration.py -- nothing else needs to change since
    docs/board_lock are computed from REPO at call time inside main()."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(ij, "REPO", repo)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        # Already on the board as an estate-lead row, dash-formatted parcel_id -- the SAME
        # real PIN (bare digits "370101234567") a crosswalk lead will resolve to. Proves
        # dedupe_key()'s normalization, not a raw string compare, is what finds the match.
        _board_row(0, parcel_id="37-01-01-234-567"),
        # Another Johnston row, unrelated PIN -- must stay untouched.
        _board_row(1, parcel_id="37-02-02-999-111"),
        # Same BARE PIN digits as row 0, but a DIFFERENT county/state -- must NOT collide
        # (proves the parcel branch's key is county/state-scoped, per Listing.dedupe_key()).
        _board_row(2, parcel_id="370101234567", county="Wake", state="NC"),
        # A non-Johnston, non-NC row entirely -- obviously untouched.
        _board_row(3, parcel_id=None, county="Greenville", state="SC"),
    ]
    wa.write_artifact(rows, {"notes": "johnston ingest test seed"}, docs_dir=docs)
    return rows


def _resolved_leads() -> list[Listing]:
    return [
        # Matches seed row 0's PIN once normalized -> should PATCH, not append.
        _crosswalk_listing("08019024", "370101234567", address="100 CROSSWALK LN"),
        # Genuinely new PIN -> should APPEND.
        _crosswalk_listing("15K11023", "370109876543", address="200 NEW LEAD DR"),
        # Another genuinely new PIN -> should APPEND.
        _crosswalk_listing("09B22011", "370105551212", address="300 SECOND LEAD AVE"),
    ]


def test_existing_johnston_keys_normalizes_and_scopes_correctly(scratch_repo):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    keys = ij._existing_johnston_keys(docs)
    # Row 0's dash-formatted parcel normalizes to the same key a bare-digit PIN would produce.
    assert "parcel:NC:johnston:370101234567" in keys
    assert "parcel:NC:johnston:370202999111" in keys
    # Row 2 (Wake county, same bare digits) must NOT appear under the Johnston-keyed set.
    assert not any(k.endswith(":370101234567") and ":wake:" in k for k in keys)
    assert len(keys) == 2  # rows 0 and 1 only -- row 2 is Wake, row 3 has no parcel at all


def test_classify_splits_patch_vs_append_and_handles_self_collision(scratch_repo):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    existing_keys = ij._existing_johnston_keys(docs)
    leads = _resolved_leads()
    # Add a same-run collision: a second lead resolving to the SAME new PIN as leads[1].
    collider = _crosswalk_listing("99Z99999", "370109876543", address="200 NEW LEAD DR DUP")
    patches, appends, self_collisions = ij._classify(leads + [collider], existing_keys)

    assert len(patches) == 1
    (key,) = patches.keys()
    assert key == "parcel:NC:johnston:370101234567"
    assert patches[key]["raw"][RAW_KEY]["legacy_parcel"] == "08019024"

    assert len(appends) == 2  # the collider is dropped, not double-appended
    assert self_collisions == 1
    appended_pins = {li.parcel_id for li in appends}
    assert appended_pins == {"370109876543", "370105551212"}


def test_main_patches_matched_lead_and_appends_the_rest(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    leads = _resolved_leads()
    monkeypatch.setattr(ij, "JohnstonDelinquentTaxCrosswalk", lambda: _FakeScraper(leads))
    monkeypatch.setattr(sys, "argv", ["ingest_johnston_tax_crosswalk.py"])

    rc = ij.main()
    assert rc == 0

    rows = wa.load_board(docs)
    assert len(rows) == len(seed) + 2  # +2 appended, the 3rd lead merged into an existing row

    by_pin = {li.parcel_id: li for li in rows if li.parcel_id}
    # The matched lead's tax-lien block landed on the EXISTING row (same source/owner_name/
    # listing_type as the seed -- a patch never overwrites fields it wasn't given).
    merged = by_pin["37-01-01-234-567"]
    assert merged.source == "counties_nc.nc_heir_estate_parcels"
    assert merged.owner_name == "Owner 0"
    assert merged.listing_type == ListingType.ESTATE_LEAD
    assert merged.raw.get(RAW_KEY, {}).get("legacy_parcel") == "08019024"
    assert merged.raw.get(RAW_KEY, {}).get("total_delinquent") == 1234.56

    # The two genuinely-new leads landed as their own new rows.
    assert by_pin["370109876543"].listing_type == ListingType.TAX_LIEN
    assert by_pin["370105551212"].listing_type == ListingType.TAX_LIEN

    # Untouched rows stayed untouched.
    untouched = {li.parcel_id for li in rows} & {"37-02-02-999-111", "370101234567"}
    assert untouched == {"37-02-02-999-111", "370101234567"}
    wake_row = next(li for li in rows if li.county == "Wake")
    assert wake_row.raw == {}  # the same-PIN-different-county row was never touched


def test_dry_run_never_writes_the_board(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    before = (docs / "listings.json").read_bytes()
    leads = _resolved_leads()
    monkeypatch.setattr(ij, "JohnstonDelinquentTaxCrosswalk", lambda: _FakeScraper(leads))
    monkeypatch.setattr(sys, "argv", ["ingest_johnston_tax_crosswalk.py", "--dry-run"])

    rc = ij.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before


def test_nothing_scraped_aborts_without_touching_board(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    before = (docs / "listings.json").read_bytes()
    monkeypatch.setattr(ij, "JohnstonDelinquentTaxCrosswalk", lambda: _FakeScraper([]))
    monkeypatch.setattr(sys, "argv", ["ingest_johnston_tax_crosswalk.py"])

    rc = ij.main()
    assert rc == 1
    assert (docs / "listings.json").read_bytes() == before
