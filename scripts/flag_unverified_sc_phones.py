#!/usr/bin/env python3
"""Flag NC-voter-file phones that are not the owner's, and measure honest phone coverage.

enrichment_sc_voter_xref matches an SC owner to an NC voter on first + last name alone. This
script applies the identity gate in src/foreclosure_scraper/enrichment_sc_phone.py to what is
already on the board:

    contradicted   the matched voter's first and last name are not both in the current
                   owner_name, or the owner is an entity or estate (LLC, VFW post, trust ...)
    corroborated   the owner mails to an NC address that is the voter's residential street,
                   or name + middle initial + county agree (NC leads only)
    unverified     everything else

and the two lane rules: a people-search phone is do_not_dial (that lane is walled), and a
listing-agent, office, attorney or trustee phone is tagged role "agent" (never the owner's).
liensnc_filing is the owner's own phone and is kept. The phone value is never removed.

    python scripts/flag_unverified_sc_phones.py              # dry run: streams the board, counts only
    python scripts/flag_unverified_sc_phones.py --json out.json
    python scripts/flag_unverified_sc_phones.py --limit 20000   # smoke test on the first rows
    python scripts/flag_unverified_sc_phones.py --apply      # ONLY board process (about 3 GB)

The dry run reads docs/listings.json.gz through board_stream.iter_board_rows (about 8 seconds,
about 300 MB), keeps counters and the ~1,700 xref phone blocks, then scans the cached NC voter
files once for just those names. It never calls load_board or write_artifact.

--apply follows scripts/resolve_anderson_from_roll.py: board_lock, load_board, mutate,
write_artifact. Run it as the only board process, never beside another board writer.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import foreclosure_scraper.enrichment_sc_phone as G  # noqa: E402

SEGMENTS = ("SC", "SC_HOT", "SC_WARM", "NC", "NC_no_liensnc", "NC_liensnc", "NC_HOT", "NC_WARM")


def _segments(state: str, liens: bool, tier: str) -> list[str]:
    """The coverage segments a row counts in. liensnc = the lien-agent-appointment source
    (row source contains 'liensnc'), reported apart because it is 50% of NC at 100% phone."""
    if state == "SC":
        segs = ["SC"]
    elif state == "NC":
        segs = ["NC", "NC_liensnc" if liens else "NC_no_liensnc"]
    else:
        return []
    if tier in ("HOT", "WARM"):
        segs.append(f"{state}_{tier}")
    return segs


def _other_owner_phone(raw: dict) -> bool:
    """A phone on the row that is not raw.owner_phone: the lien report's owner contact, a
    skip-trace or outreach phone list, or an ingested contact. None of these is gated here."""
    rel = raw.get("liensnc_related") if isinstance(raw.get("liensnc_related"), dict) else {}
    oc = rel.get("owner_contact") if isinstance(rel.get("owner_contact"), dict) else {}
    st = raw.get("skip_trace") if isinstance(raw.get("skip_trace"), dict) else {}
    out = raw.get("outreach") if isinstance(raw.get("outreach"), dict) else {}
    ct = raw.get("contact") if isinstance(raw.get("contact"), dict) else {}
    return bool(oc.get("phone") or st.get("phone_numbers") or out.get("phones") or ct.get("phones"))


def measure(limit: int | None = None, voter_dir: str | Path | None = None) -> dict:
    """One streaming pass, then one voter-file scan. Returns plain counters.

    `voter_dir` overrides data/ncvoter (tests point it at a synthetic file)."""
    from foreclosure_scraper.board_stream import iter_board_rows

    rows_seg: Counter = Counter()
    before: Counter = Counter()             # rows with raw.owner_phone.phone
    after: Counter = Counter()              # rows with a usable owner phone once the gate is applied
    after_strict: Counter = Counter()       # ... and not a name-only NC voter fallback
    other_only: Counter = Counter()         # no usable owner_phone but another phone carrier
    any_usable: Counter = Counter()         # usable owner_phone OR another carrier
    phones_by_source: Counter = Counter()   # (state, phone source, lane)
    blocked_by: Counter = Counter()         # (state, block reason) for non-xref blocks
    xref_lite: list = []
    stamped: Counter = Counter()             # what is ALREADY on the board (verifies a past --apply)
    total = 0

    stream = iter_board_rows()
    if limit:
        stream = itertools.islice(stream, limit)
    for r in stream:
        total += 1
        state = r.get("state")
        liens = "liensnc" in str(r.get("source") or "")
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
        segs = _segments(state, liens, str(ds.get("tier") or ""))
        for s in segs:
            rows_seg[s] += 1
        if not segs:
            continue
        op = raw.get("owner_phone")
        other = _other_owner_phone(raw)
        has_op = isinstance(op, dict) and bool(op.get("phone"))
        usable = strict = False
        if has_op:
            lane = G.phone_lane(op)
            phones_by_source[(state, str(op.get("source")), lane)] += 1
            if lane == "sc_voter_xref":
                stamped["xref_phones"] += 1
                stamped["xref_identity_check"] += bool(op.get("identity_check"))
                stamped["xref_do_not_dial"] += bool(op.get("do_not_dial"))
            elif lane == "agent":
                stamped["agent_phones"] += 1
                stamped["agent_role_tagged"] += op.get("role") == "agent"
            elif lane == "people_search":
                stamped["people_search_phones"] += 1
                stamped["people_search_do_not_dial"] += bool(op.get("do_not_dial"))
            for s in segs:
                before[s] += 1
            if lane == "sc_voter_xref":
                xref_lite.append((segs, other, SimpleNamespace(
                    owner_name=r.get("owner_name"), county=r.get("county"), state=state,
                    raw={"owner_phone": op, "owner_mailing": raw.get("owner_mailing")})))
                continue                    # counted after the voter scan
            reason = G.owner_phone_block_reason(op)
            if reason is None:
                usable = True
                strict = lane != "voter_name_only"
            else:
                blocked_by[(state, reason)] += 1
        for s in segs:
            after[s] += usable
            after_strict[s] += strict
            other_only[s] += (not usable) and other
            any_usable[s] += usable or other

    # the xref phones: one voter-file scan for exactly these names
    idx = G.VoterIdentityIndex(voter_dir=voter_dir)
    lites = [li for _, _, li in xref_lite]
    gate_stats = G.flag_unverified_xref_phones(lites, apply=False, index=idx)
    verdict_by_seg: dict[str, Counter] = defaultdict(Counter)
    by_source: Counter = Counter()
    mail_state: Counter = Counter()          # where the xref phones' owners mail to
    nc_mail: Counter = Counter()             # xref rows whose owner mails to NC: (verdict, reason)
    prior_guard: Counter = Counter()         # phones the earlier NC-mailing-only script tagged
    samples: list[dict] = []
    seen_counties: set = set()
    contradicted_rows: list[dict] = []
    for segs, other, li in xref_lite:
        res = G.xref_identity_check(li, index=idx)
        v = res["verdict"]
        by_source[(li.raw["owner_phone"].get("source"), v)] += 1
        om = li.raw.get("owner_mailing")
        ms = G._mail_state(om) if isinstance(om, dict) else ""
        mail_state[ms or "no mailing"] += 1
        if ms == "NC":
            nc_mail[(v, res["reason"])] += 1
        if li.raw["owner_phone"].get("corroboration") == "nc_mailing_address":
            prior_guard[v] += 1
        for s in segs:
            verdict_by_seg[s][v] += 1
            if v == G.CORROBORATED:
                after[s] += 1
                after_strict[s] += 1
                any_usable[s] += 1
            else:
                blocked_by[(li.state, "sc_xref_identity_" + v)] += 1
                other_only[s] += other
                any_usable[s] += other
        if v == G.CONTRADICTED:
            contradicted_rows.append({
                "county": li.county, "owner_name": li.owner_name, "reason": res["reason"],
                "voter": ", ".join(res["voter"]) if res["voter"] else None,
                "mail_state": ((li.raw.get("owner_mailing") or {}).get("mail_state")
                               if isinstance(li.raw.get("owner_mailing"), dict) else None)})
    # ten contradicted rows, one per county first so the sample is not all Spartanburg
    for row in contradicted_rows:
        if len(samples) < 10 and row["county"] not in seen_counties:
            samples.append(row)
            seen_counties.add(row["county"])
    for row in contradicted_rows:
        if len(samples) >= 10:
            break
        if row not in samples:
            samples.append(row)

    return {
        "rows_read": total,
        "rows_seg": dict(rows_seg), "before": dict(before), "after": dict(after),
        "after_strict": dict(after_strict), "other_only": dict(other_only),
        "any_usable": dict(any_usable),
        "phones_by_source": {f"{a}|{b}|{c}": n for (a, b, c), n in sorted(phones_by_source.items())},
        "blocked_by": {f"{a}|{b}": n for (a, b), n in sorted(blocked_by.items())},
        "xref_verdict_by_seg": {k: dict(v) for k, v in verdict_by_seg.items()},
        "xref_verdict_by_source": {f"{a}|{b}": n for (a, b), n in sorted(by_source.items())},
        "already_stamped": dict(stamped),
        "xref_mail_state": dict(mail_state.most_common()),
        "xref_nc_mailing": {f"{a}|{b}": n for (a, b), n in sorted(nc_mail.items())},
        "xref_prior_nc_mailing_tag": dict(prior_guard),
        "gate": gate_stats, "samples": samples,
        "voter_files_scanned": idx.files_scanned, "voter_rows_scanned": idx.rows_scanned,
    }


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:5.1f}%" if d else "    - "


def _print(m: dict) -> None:
    rs = m["rows_seg"]
    print(f"rows read: {m['rows_read']:,}   voter files scanned: {m['voter_files_scanned']}"
          f" ({m['voter_rows_scanned']:,} rows)\n")

    print("PHONES ON THE BOARD, by state / phone source / lane")
    for k, n in sorted(m["phones_by_source"].items(), key=lambda kv: (kv[0].split("|")[0], -kv[1])):
        st, src, lane = k.split("|")
        print(f"  {st}  {src:26} {lane:20} {n:>7,}")

    g = m["gate"]
    print(f"\nNC-VOTER-XREF PHONES: {g['xref_phones']:,}   "
          f"corroborated {g['corroborated']:,}   unverified {g['unverified']:,}   "
          f"contradicted {g['contradicted']:,}   would flag do_not_dial: {g['do_not_dial']:,}")
    print("  reasons:", ", ".join(f"{k}={v:,}" for k, v in sorted(g["reasons"].items(), key=lambda kv: -kv[1])))
    print("  by county (corroborated / unverified / contradicted):")
    for c, v in sorted(g["by_county"].items(), key=lambda kv: -sum(kv[1].values())):
        print(f"    {c:16} {v.get('corroborated', 0):>5,} {v.get('unverified', 0):>6,} {v.get('contradicted', 0):>6,}")
    print("  by phone source:", m["xref_verdict_by_source"])
    print("  owner mails to (state):", m["xref_mail_state"])
    print("  owner mails to NC, by verdict|reason:", m["xref_nc_mailing"])
    print("  phones the earlier NC-mailing-only script tagged corroboration=nc_mailing_address:",
          m["xref_prior_nc_mailing_tag"])

    st = m["already_stamped"]
    print("\nALREADY STAMPED ON THE BOARD (all zero before the first --apply; equal to the totals after it)")
    print(f"  xref phones {st.get('xref_phones', 0):,}: identity_check {st.get('xref_identity_check', 0):,},"
          f" do_not_dial {st.get('xref_do_not_dial', 0):,}   agent phones {st.get('agent_phones', 0):,}:"
          f" role tagged {st.get('agent_role_tagged', 0):,}   people-search phones"
          f" {st.get('people_search_phones', 0):,}: do_not_dial {st.get('people_search_do_not_dial', 0):,}")

    print("\nNON-XREF PHONES BLOCKED (would not be offered as the owner's number)")
    for k, n in sorted(m["blocked_by"].items()):
        if "sc_xref_identity" not in k:
            print(f"  {k:40} {n:>7,}")

    print("\nHONEST OWNER-PHONE COVERAGE (rows)          rows    before(any)  after gate   strict    +other carriers")
    for s in SEGMENTS:
        n = rs.get(s, 0)
        print(f"  {s:16} {n:>9,}   {m['before'].get(s, 0):>9,} {_pct(m['before'].get(s, 0), n)}"
              f"  {m['after'].get(s, 0):>8,} {_pct(m['after'].get(s, 0), n)}"
              f"  {m['after_strict'].get(s, 0):>8,} {_pct(m['after_strict'].get(s, 0), n)}"
              f"  {m['any_usable'].get(s, 0):>8,} {_pct(m['any_usable'].get(s, 0), n)}")
    print("  before = raw.owner_phone present. after gate = a phone that may be offered as the OWNER's number.")
    print("  strict = after gate, minus NC name-only voter fallbacks. +other = or a phone from the lien report,")
    print("  skip trace, outreach or ingested contact (not gated here).")

    print("\n10 CONTRADICTED ROWS (owner_name vs the voter the phone was matched to)")
    for s in m["samples"]:
        print(f"  {str(s['county']):12} owner={str(s['owner_name'])[:34]:36} voter={str(s['voter']):24}"
              f" mail={s['mail_state']}  {s['reason']}")


def _apply() -> int:
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    with board_lock(REPO, owner="flag_unverified_sc_phones"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        print(f"board rows: {n:,}", flush=True)
        xref = G.flag_unverified_xref_phones(rows, apply=True)
        lane = G.flag_lane_phones(rows, apply=True)
        print("xref gate:", {k: v for k, v in xref.items() if k not in ("by_county", "reasons")}, flush=True)
        print("lane rules:", lane, flush=True)
        assert len(rows) == n, "row count changed, refusing to write"
        write_artifact(rows, {"flag_unverified_sc_phones": {
            "xref_phones": xref["xref_phones"], "corroborated": xref["corroborated"],
            "unverified": xref["unverified"], "contradicted": xref["contradicted"],
            "walled_flagged": lane["walled_flagged"], "agent_tagged": lane["agent_tagged"]}},
            docs_dir=REPO / "docs")
        print(f"wrote board: {n:,} rows; {xref['do_not_dial']:,} xref phones flagged do_not_dial, "
              f"{lane['agent_tagged']:,} agent phones tagged")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="stamp the board (board_lock + load_board + write_artifact)")
    ap.add_argument("--json", metavar="PATH", help="also write the dry-run counters as JSON")
    ap.add_argument("--limit", type=int, help="dry run on only the first N rows (smoke test)")
    ap.add_argument("--voter-dir", metavar="DIR", help="NC voter files to check against (default data/ncvoter)")
    args = ap.parse_args()
    if args.apply:
        return _apply()
    m = measure(args.limit, args.voter_dir)
    _print(m)
    if args.json:
        Path(args.json).write_text(json.dumps(m, indent=2, default=str))
    print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
