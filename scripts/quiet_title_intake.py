"""Write a private quiet-title intake sheet (HTML + PDF + exhibits) for ONE parcel, fetched live.

  uv run python scripts/quiet_title_intake.py --pin <PIN> [--county Buncombe] [--out DIR]

Default output: ~/Desktop/Lawyer_Review/intake/<PIN>/ (private; never in this repo). The folder
gets the sheet (QuietTitle_Intake_<County>_<PIN>.html and .pdf), a facts JSON, the fetch log and
exhibits/ (the saved copy of every page read, and a picture of each).

Polite by construction (quiet_title/fetch.py): >= 1.6 s between requests to one host, an ordinary
browser User-Agent, and a CAPTCHA, login or block page stops that step, which the sheet records
as walled. This tool sends nothing to anyone: no email, no upload, no external service.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.quiet_title.adapters import adapter_class  # noqa: E402
from foreclosure_scraper.quiet_title.fetch import PoliteFetcher  # noqa: E402
from foreclosure_scraper.quiet_title.intake import run_intake  # noqa: E402
from foreclosure_scraper.quiet_title.model import EASTERN, IntakeResult, utc_now  # noqa: E402
from foreclosure_scraper.quiet_title.render import write_sheet  # noqa: E402

DEFAULT_ROOT = Path.home() / "Desktop" / "Lawyer_Review" / "intake"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pin", required=True, help="the county's parcel number (Buncombe: the 15-digit pinnum)")
    ap.add_argument("--county", default="Buncombe")
    ap.add_argument("--state", default="NC")
    ap.add_argument("--out", help="output folder (default ~/Desktop/Lawyer_Review/intake/<PIN>/)")
    ap.add_argument("--max-chain", type=int, default=3, help="earlier deeds to follow (default 3)")
    ap.add_argument("--no-pictures", action="store_true", help="skip the exhibit pictures")
    ap.add_argument("--no-pdf", action="store_true", help="skip the PDF")
    a = ap.parse_args(argv)

    pin = "".join(ch for ch in a.pin if ch.isalnum())
    out = Path(a.out).expanduser() if a.out else DEFAULT_ROOT / pin
    try:
        out.resolve().relative_to(REPO)
        print("Refusing to write an intake sheet inside the repository (it holds private facts).", file=sys.stderr)
        return 2
    except ValueError:
        pass
    out.mkdir(parents=True, exist_ok=True)
    cls = adapter_class(a.county, a.state)
    started = utc_now()
    res = IntakeResult(county=cls.county, state=cls.state, pin=pin, started=started)
    fetcher = PoliteFetcher(out)
    adapter = cls(fetcher, res, started.astimezone(EASTERN).strftime("%Y%m%d"))
    today = started.astimezone(EASTERN).date()
    print(f"intake {cls.county} {cls.state} PIN {pin} -> {out}", flush=True)
    run_intake(adapter, pin, today, max_chain=a.max_chain)
    paths = write_sheet(res, out, pictures=not a.no_pictures, pdf=not a.no_pdf)
    print(f"requests by host: {fetcher.requests_by_host}")
    print(f"exhibits: {len(res.exhibits)}; walls: {len(res.walls)}; notes: {len(res.notes)}")
    print(f"sheet: {paths['html']}")
    print(f"pdf:   {paths['pdf'] or 'not written'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
