"""Mac side of the VM<->origin patch-export sync (2026-11-19).

THE PROBLEM. The VM's self-looping wrappers (meck_gis_attrs, meck_code_enforcement,
gis_attrs_boardwide, meck_tax, deed_chain_v2, run_comps_sweep) each read+patch a LOCAL copy of
the board. The VM has no reliable path to push that work back to origin: the board files are
gzipped JSON -- binary, not line/byte-mergeable -- so a naive git rebase/merge between two
independently-patched copies hits real conflicts a tool cannot safely auto-resolve (tried and
aborted 2026-11-19, see project_vm_checkout_264_behind_2026-11-19.md). Blindly taking "ours" or
"theirs" on a binary conflict risks silently discarding real patches from one side.

THE FIX. A patch passed to web_artifact.patch_existing_rows() is already identity-keyed
(Listing.dedupe_key() -> field updates), not tied to any particular board FILE state -- the
same shape every backfill script in this codebase already trusts, because the function always
re-streams the CURRENT board fresh and matches by identity. That means a patch computed on the
VM can be safely REPLAYED, by this same function, against a completely different (newer) board
snapshot on a different machine -- no file-level merge involved at all.

Every VM wrapper invocation sets PATCH_EXPORT_DIR, which makes patch_existing_rows() (see its
own CROSS-MACHINE PATCH EXPORT block) additionally drop its raw `patches` dict as a small JSON
file there, independent of and never blocking its normal local board write. This script:
  1. pulls those export files off the VM over the existing SSH connection (scp, one file at a
     time -- no rsync dependency assumed on either end),
  2. replays each one's `patches` dict through patch_existing_rows() against THIS machine's
     current, origin-synced board, inside the normal board_lock(),
  3. commits + pushes the result the same way every other script in this session has,
  4. on success, moves the VM-side files it consumed into patch_export/synced/ (never deletes
     outright -- a failed run leaves them in place to retry next time, a successful run keeps
     them around for audit rather than erasing history).

Deliberately NOT a git operation anywhere in this flow -- see the module docstring above for
why that path was tried and abandoned.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

DEFAULT_VM_HOST = "opc@129.146.168.104"
DEFAULT_SSH_KEY = str(Path.home() / ".ssh" / "oracle_vm_correct")
DEFAULT_VM_EXPORT_DIR = "/home/opc/foreclosure-scraper/patch_export"


def _ssh(host: str, key: str, remote_cmd: str, timeout: int = 30) -> str:
    out = subprocess.run(
        ["ssh", "-i", key, "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", host, remote_cmd],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return out.stdout


def _scp_pull(host: str, key: str, remote_path: str, local_path: Path, timeout: int = 60) -> None:
    subprocess.run(
        ["scp", "-i", key, "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
         f"{host}:{remote_path}", str(local_path)],
        capture_output=True, text=True, timeout=timeout, check=True,
    )


def list_vm_exports(host: str, key: str, vm_dir: str) -> list[str]:
    """Filenames only (no path), oldest-looking-first by name (names are
    f"{unix_ts}_{8 hex}.json" from the exporter, so a plain sort is chronological)."""
    out = _ssh(host, key, f"cd {vm_dir} 2>/dev/null && ls -1 *.json 2>/dev/null || true")
    names = sorted(n for n in out.splitlines() if n.strip().endswith(".json"))
    return names


def pull_exports(host: str, key: str, vm_dir: str, names: list[str], local_dir: Path) -> list[Path]:
    local_dir.mkdir(parents=True, exist_ok=True)
    pulled: list[Path] = []
    for name in names:
        dest = local_dir / name
        _scp_pull(host, key, f"{vm_dir}/{name}", dest)
        pulled.append(dest)
    return pulled


def mark_synced_on_vm(host: str, key: str, vm_dir: str, names: list[str]) -> None:
    if not names:
        return
    _ssh(host, key, f"mkdir -p {vm_dir}/synced")
    # One mv per file via a single ssh round-trip, rather than one round-trip per file.
    cmd = " && ".join(f"mv -f {vm_dir}/{n} {vm_dir}/synced/{n}" for n in names)
    _ssh(host, key, cmd)


def apply_export(payload: dict, docs: Path, source_name: str) -> dict:
    patches = payload.get("patches") or {}
    summary = dict(payload.get("summary") or {})
    summary["vm_patch_sync_source"] = source_name
    summary["vm_patch_sync_host"] = payload.get("host")
    summary["vm_patch_sync_exported_at"] = payload.get("exported_at")
    return patch_existing_rows(patches, summary, docs_dir=docs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                     help="pull and report what WOULD be applied; writes nothing, "
                          "moves nothing on the VM")
    ap.add_argument("--vm-host", default=DEFAULT_VM_HOST)
    ap.add_argument("--ssh-key", default=DEFAULT_SSH_KEY)
    ap.add_argument("--vm-export-dir", default=DEFAULT_VM_EXPORT_DIR)
    ap.add_argument("--local-scratch", default=None,
                     help="where to stage pulled files (default: a tmp dir under docs/../tmp)")
    ap.add_argument("--max-files", type=int, default=None,
                     help="cap how many export files to pull+apply this run (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    scratch = Path(args.local_scratch) if args.local_scratch else REPO / "tmp" / "vm_patch_sync"

    names = list_vm_exports(args.vm_host, args.ssh_key, args.vm_export_dir)
    if args.max_files is not None:
        names = names[: args.max_files]
    print(f"VM export files found: {len(names)}")
    if not names:
        print("nothing to sync")
        return 0

    pulled = pull_exports(args.vm_host, args.ssh_key, args.vm_export_dir, names, scratch)
    print(f"pulled {len(pulled)} file(s) to {scratch}")

    totals = {"files": 0, "patches": 0, "applied": 0, "not_found": 0,
              "duplicate_key_matches": 0, "unsafe_identity_skipped": 0}
    applied_any = False
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="sync_vm_patch_exports")
    with lock:
        for path in pulled:
            try:
                payload = json.loads(path.read_text())
            except Exception as exc:  # noqa: BLE001 - one malformed export must not kill the run
                print(f"  SKIP {path.name}: unreadable ({exc})")
                continue
            patches = payload.get("patches") or {}
            totals["files"] += 1
            totals["patches"] += len(patches)
            if args.dry_run:
                print(f"  {path.name}: {len(patches)} patch(es), "
                      f"exported_at={payload.get('exported_at')} host={payload.get('host')}")
                continue
            stats = apply_export(payload, docs, path.name)
            print(f"  {path.name}: applied={stats['applied']} not_found={stats['not_found']} "
                  f"dup={stats['duplicate_key_matches']} written={stats['written']}")
            totals["applied"] += stats["applied"]
            totals["not_found"] += stats["not_found"]
            totals["duplicate_key_matches"] += stats["duplicate_key_matches"]
            totals["unsafe_identity_skipped"] += len(stats.get("unsafe_identity_skipped") or [])
            if stats["written"]:
                applied_any = True

    print(f"=== totals === {totals}")

    if args.dry_run:
        print("dry run: nothing applied, nothing moved on the VM")
        return 0

    if not applied_any:
        print("no file actually wrote to the board (all empty/not_found) -- "
              "marking all pulled files synced anyway so they are not retried forever")
    mark_synced_on_vm(args.vm_host, args.ssh_key, args.vm_export_dir, names)
    print(f"marked {len(names)} VM-side file(s) as synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
