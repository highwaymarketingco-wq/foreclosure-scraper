"""Driver script to run all foreclosure scrapers and write a combined JSON output.

This script:
* Instantiates the sheriff‑sale scraper (full NC/SC county list).
* Instantiates the upset‑bid scraper (the URLs we discovered).
* Executes both scrapers (their .run() methods return a list of Listing objects).
* Serialises the Listing objects to plain dicts and writes them to
  `docs/listings.json` (overwrites any existing file).
* Logs any 403/429/503 responses – those will appear on stdout; you can open
  the offending URL in a browser, solve the CAPTCHA/TOS, and re‑run.

Usage (from the repo root)::

    PYTHONPATH=~/foreclosure-scraper/src:$PYTHONPATH \
    ~/foreclosure-scraper/.venv/bin/python3.12 src/run_foreclosure.py
"""

import json
import sys
from pathlib import Path

# Ensure the repository's `src` directory is on sys.path (safety net).
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# ---------------------------------------------------------------------
# Directly load the scraper modules from their absolute file locations.
# This avoids any other `foreclosure_scraper` package that might be present
# on the system and shadow the one in this repository.
# ---------------------------------------------------------------------
import importlib.util

def _load_module(module_name: str, file_path: Path) -> object:
    """Load a module from an absolute file path.

    Args:
        module_name: Fully qualified module name to register.
        file_path:   Path to the .py source file.
    Returns:
        The loaded module object.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

# Resolve the directory that contains the national scrapers. `PROJECT_ROOT`
# points at the repository's `src` folder, so the scrapers live under
# `<repo>/src/foreclosure_scraper/scrapers/national`.
SCRAPERS_ROOT = PROJECT_ROOT / "foreclosure_scraper" / "scrapers" / "national"

# ---------------------------------------------------------------------
# Load the sheriff‑sale scraper. The original repository provides a file
# `sheriff_sales.py` that defines a class `SheriffSales`. We load that file
# and dynamically locate the concrete subclass of `BaseScraper` so we do
# not need to know the exact class name.
# ---------------------------------------------------------------------
Sheriff_mod = _load_module(
    "foreclosure_scraper.scrapers.national.sheriff_sales",
    SCRAPERS_ROOT / "sheriff_sales.py",
)

# Dynamically discover the scraper class inside the module.
from foreclosure_scraper.base_scraper import BaseScraper

SheriffSalesAllScraper = next(
    getattr(Sheriff_mod, name)
    for name in dir(Sheriff_mod)
    if isinstance(getattr(Sheriff_mod, name), type)
    and issubclass(getattr(Sheriff_mod, name), BaseScraper)
    and getattr(Sheriff_mod, name) is not BaseScraper
)

# ---------------------------------------------------------------------
# Load the upset‑bid scraper. The repo contains a file `nc_upset_bids.py`
# (and potentially other upset‑bid modules). We attempt to load that file
# first; if it does not exist we fall back to any file in the directory
# whose name contains "upset".
# ---------------------------------------------------------------------
try:
    Upset_mod = _load_module(
        "foreclosure_scraper.scrapers.national.nc_upset_bids",
        SCRAPERS_ROOT / "nc_upset_bids.py",
    )
except FileNotFoundError:
    # Scan for an alternative file containing "upset" in its name.
    upset_files = [p for p in SCRAPERS_ROOT.iterdir() if "upset" in p.name.lower() and p.suffix == ".py"]
    if not upset_files:
        raise FileNotFoundError("No upset‑bid scraper module found in the national scrapers directory")
    # Use the first candidate.
    upset_path = upset_files[0]
    Upset_mod = _load_module(
        f"foreclosure_scraper.scrapers.national.{upset_path.stem}",
        upset_path,
    )

# Dynamically discover the upset‑bid scraper class (any subclass of BaseScraper).
UpsetBidsAllScraper = next(
    getattr(Upset_mod, name)
    for name in dir(Upset_mod)
    if isinstance(getattr(Upset_mod, name), type)
    and issubclass(getattr(Upset_mod, name), BaseScraper)
    and getattr(Upset_mod, name) is not BaseScraper
)


def main() -> None:
    # Instantiate scrapers.
    sheriff_scraper = SheriffSalesAllScraper()
    upset_scraper = UpsetBidsAllScraper()

    # Run them – each scraper implements an async ``fetch`` method that yields
    # an iterable of ``Listing`` objects. We invoke it via ``asyncio.run`` to
    # obtain a concrete list.
    import asyncio
    sheriff_results = list(asyncio.run(sheriff_scraper.fetch()))
    upset_results = list(asyncio.run(upset_scraper.fetch()))

    # Combine results.
    all_results = sheriff_results + upset_results

    # Convert Pydantic models (or dataclasses) to plain dicts for JSON.
    serialisable = [listing.dict() for listing in all_results]

    # Write to the standard board location.
    # Write to a *separate* output file so the production board is untouched.
    out_path = PROJECT_ROOT.parent / "docs" / "run_foreclosure_output.json"
    out_path.write_text(json.dumps(serialisable, indent=2, default=str))
    print(f"Wrote {len(serialisable)} listings to {out_path}")


if __name__ == "__main__":
    main()
