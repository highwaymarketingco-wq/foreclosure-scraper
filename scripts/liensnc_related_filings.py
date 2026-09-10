#!/usr/bin/env python3
"""Follow the LiensNC `related_filings = Yes` flag — the unread distress signal.

The liensnc scrape stores a bare Yes/No flag on every row. Measured on the live
board: 56,452 liensnc rows, **18,900 say "Yes"** and not one has ever been
followed. A "Yes" means one or more **Notice to Lien Agent** filings exist against
that project, filed by a supplier or subcontractor to preserve its lien rights.

That is a graded signal, not a binary one, and the grading matters:

  1. `Appointment of Lien Agent` alone  -> the OWNER registered a job before work
     started (NCGS 44A-11.1). Routine. Someone is building. NOT distress.
  2. `+ Notice to Lien Agent`           -> trade creditors are preserving lien
     rights on that job, and the report NAMES them. Real signal.
  3. An actual `Claim of Lien` on real property (NCGS 44A-8/12) -> the unpaid-
     contractor event. That is recorded at the county Register of Deeds, NOT here,
     so step 3 is a ROD lookup keyed off what this script collects.

The second, larger prize is contactability, which has been this engine's real
bottleneck rather than lead count. The related-filings report carries the OWNER'S
name, mailing address, PHONE and EMAIL — for up to 18,900 NC leads.

Does not touch `scripts/scrape_liensnc.py`: the login is imported from it so the
operator's staged credentials are reused and never handled here. Its checkpoint
lives at /tmp and is wiped on reboot (which is why the pool is 2026-only despite
the search being configured from 2010); this script keeps its own under logs/ so
it can actually resume across sessions.
"""
from __future__ import annotations

import argparse
import asyncio
import html as _html
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

CHECKPOINT = REPO / "logs" / "liensnc_related_checkpoint.json"
# DURABLE STORE, appended per fetch. The first 1,500-entry run wrote results only
# into raw['liensnc_related'] and web_artifact.RAW_KEEP -- an allowlist that strips
# any raw key not named in it -- silently discarded every one: a scan of the written
# board found 0 rows carrying the key. The allowlist now names it, but an expensive,
# politely-rate-limited harvest must not depend on a publish-time allowlist at all.
# This file is the source of truth; the board copy is a convenience.
SIDECAR = REPO / "logs" / "liensnc_related.jsonl"
REPORT_PATH = "/scr/filing/report/relatedFilings.html?entryNumber={entry}"

_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_PHONE_RE = re.compile(r"Phone:\s*([0-9][0-9\-().\s]{6,})")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ENTRY_RE = re.compile(r"Entry\s*#:\s*(\d+)")
_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
_PIN_RE = re.compile(r"PIN#\s*([0-9A-Za-z\-]+)")


def _clean(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _cells(row: str) -> list[str]:
    return [_clean(c) for c in _CELL_RE.findall(row)]


def parse_contact(cell: str) -> dict:
    """Split a LiensNC party cell into name / address / phone / email.

    Cells look like:
      "Kristie Richardson & Michael Richardson 139 Ball Gap Rd, Arden, NC 28704
       United States Phone: 828-551-2326 richardson.michaeld@ymail.com"
    """
    out: dict = {}
    txt = cell
    m = _EMAIL_RE.search(txt)
    if m:
        out["email"] = m.group(0)
        txt = txt.replace(m.group(0), " ")
    m = _PHONE_RE.search(txt)
    if m:
        out["phone"] = re.sub(r"[^\d]", "", m.group(1))[:10] or None
        txt = txt[: m.start()] + " " + txt[m.end():]
    txt = re.sub(r"\bUnited States\b", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" ,")
    # The name runs up to the first street-number token.
    sm = re.search(r"\b\d+\s+[A-Za-z]", txt)
    if sm:
        out["name"] = txt[: sm.start()].strip(" ,&")
        out["mailing"] = txt[sm.start():].strip(" ,")
    else:
        out["name"] = txt.strip(" ,&") or None
    return {k: v for k, v in out.items() if v}


def parse_report(page: str) -> dict:
    """Pull the appointment's owner contact + every distinct Notice to Lien Agent."""
    owner: dict = {}
    notices: dict[str, dict] = {}
    pin = None
    for tbl in _TABLE_RE.findall(page):
        rows = [_cells(r) for r in _ROW_RE.findall(tbl)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        hdr = [h.lower() for h in rows[0]]
        if any("owner" in h for h in hdr):
            for r in rows[1:]:
                if len(r) < 3:
                    continue
                if not pin:
                    pm = _PIN_RE.search(r[1])
                    pin = pm.group(1) if pm else None
                if not owner:
                    owner = parse_contact(r[2])
        elif any("claimant" in h for h in hdr):
            for r in rows[1:]:
                if len(r) < 3:
                    continue
                em = _ENTRY_RE.search(r[0])
                key = em.group(1) if em else r[0][:40]
                if key in notices:      # the report repeats each notice row
                    continue
                dm = _DATE_RE.search(r[0])
                st = re.search(r"Status:\s*([^E]+?)(?:Expires|$)", r[0])
                notices[key] = {
                    "entry_number": em.group(1) if em else None,
                    "filed_date": dm.group(1) if dm else None,
                    "status": (st.group(1).strip(" -") if st else None),
                    "claimant": parse_contact(r[2]),
                    "contracted_through": r[3] if len(r) > 3 else None,
                }
    return {
        "owner_contact": owner or None,
        "pin": pin,
        "notices": list(notices.values()),
        "notice_count": len(notices),
    }


def load_ckpt() -> dict:
    if CHECKPOINT.exists():
        try:
            return json.loads(CHECKPOINT.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"done": {}}


def save_ckpt(ck: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(ck))
    tmp.replace(CHECKPOINT)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25,
                    help="how many entries to fetch this run (default 25 — a probe)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between fetches")
    ap.add_argument("--write-board", action="store_true",
                    help="persist results onto the board (default: collect + report only)")
    args = ap.parse_args()

    import httpx
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    spec = importlib.util.spec_from_file_location("sl", REPO / "scripts" / "scrape_liensnc.py")
    sl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sl)

    print("loading board…")
    listings = load_board(REPO / "docs")
    before = len(listings)
    targets = []
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        ln = raw.get("liensnc") if isinstance(raw.get("liensnc"), dict) else {}
        if str(ln.get("related_filings") or "").strip().lower() != "yes":
            continue
        entry = str(ln.get("entry_number") or "").strip()
        if entry:
            targets.append((entry, li))
    print(f"board rows {before:,} | related_filings=Yes with an entry number: {len(targets):,}")

    ck = load_ckpt()
    # Trust the SIDECAR for what is genuinely captured. The checkpoint alone once
    # marked 1,508 entries "done" whose data had been stripped at publish, so the
    # work looked complete while nothing had been kept.
    have: set = set()
    if SIDECAR.exists():
        for line in SIDECAR.read_text(encoding="utf-8").splitlines():
            try:
                have.add(str(json.loads(line).get("entry_number")))
            except Exception:  # noqa: BLE001
                continue
    print(f"sidecar holds {len(have):,} captured entries")
    todo = [(e, li) for e, li in targets if e not in have]
    print(f"remaining to fetch: {len(todo):,}")
    todo = todo[: args.limit]
    if not todo:
        print("nothing to do.")
        return 0

    stats = Counter()
    async with httpx.AsyncClient(follow_redirects=True, headers=sl.HEADERS, timeout=40) as c:
        await c.get(sl.LOGIN_URL)
        r = await c.post(sl.AUTH_URL,
                         data={"j_username": sl.LIENSNC_USER, "j_password": sl.LIENSNC_PASS},
                         headers={"Content-Type": "application/x-www-form-urlencoded",
                                  "Origin": sl.BASE, "Referer": sl.LOGIN_URL})
        if "login" in str(r.url).lower():
            print("LOGIN FAILED — credentials may need re-staging."); return 1
        print("logged in.\n")

        for i, (entry, li) in enumerate(todo, 1):
            try:
                d = await c.get(sl.BASE + REPORT_PATH.format(entry=entry))
                if "login" in str(d.url).lower():
                    print("session expired — stopping so the checkpoint stays honest"); break
                got = parse_report(d.text)
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}/{len(todo)}] entry {entry}: ERROR {type(e).__name__}")
                stats["error"] += 1
                await asyncio.sleep(args.delay)
                continue

            # Append BEFORE anything else can drop it.
            with SIDECAR.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"entry_number": entry, **got}, default=str) + "\n")

            ck["done"][entry] = got["notice_count"]
            stats["fetched"] += 1
            stats["notices"] += got["notice_count"]
            oc = got.get("owner_contact") or {}
            if oc.get("phone"):
                stats["owner_phone"] += 1
            if oc.get("email"):
                stats["owner_email"] += 1
            if oc.get("mailing"):
                stats["owner_mailing"] += 1

            if args.write_board:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["liensnc_related"] = got
                # Contactability is the actual bottleneck — fill only what's blank.
                if oc.get("name") and not li.owner_name:
                    li.owner_name = oc["name"]

            # Checkpoint INCREMENTALLY, not just at batch end. A 3,000-entry batch
            # is ~55 minutes; the operator's laptop died mid-run once already, and
            # losing an hour of polite 1.1s fetches to recover nothing is the wrong
            # trade for one small write every 50 entries.
            if stats["fetched"] % 50 == 0:
                save_ckpt(ck)

            print(f"  [{i}/{len(todo)}] entry {entry}: {got['notice_count']} notice(s) "
                  f"| owner={ (oc.get('name') or '?')[:28] } "
                  f"phone={oc.get('phone') or '-'} email={'y' if oc.get('email') else '-'}")
            for n in got["notices"][:2]:
                cl = n.get("claimant") or {}
                print(f"        claimant: {(cl.get('name') or '?')[:34]:<34} "
                      f"via {(n.get('contracted_through') or '?')[:34]}")
            await asyncio.sleep(args.delay)

    save_ckpt(ck)
    print(f"\ncheckpoint: {CHECKPOINT} ({len(ck['done']):,} entries done)")
    print(f"stats: {dict(stats)}")

    if args.write_board and stats["fetched"]:
        with board_lock(REPO):
            assert len(listings) == before, "enrichment must not change the row count"
            write_artifact(listings, {
                "total": len(listings),
                "notes": (f"liensnc_related_filings: {stats['fetched']} entries, "
                          f"{stats['notices']} notices, {stats['owner_phone']} owner phones"),
                "off_footprint_removed": 0,
            }, docs_dir=REPO / "docs")
        print(f"wrote board: {before:,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
