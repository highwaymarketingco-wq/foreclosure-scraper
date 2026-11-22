#!/usr/bin/env python3
"""Streaming fast-export filter: keep every commit, every message, every code diff, exactly as
they are -- but for a fixed set of frequently-rewritten compressed board-data paths, replace the
blob content in every commit EXCEPT the one that currently defines that path's live content with
a zero-byte placeholder. The live (HEAD) content of every target path is untouched.

Usage (on the repo whose history is being rewritten, from its root):
    git fast-export --show-original-ids --signed-tags=strip --tag-of-filtered-object=drop main \
      | python3 strip_old_shard_blobs.py \
      | git fast-import --force

Then: point main at whatever fast-import reports, verify, gc --prune=now.
"""
import subprocess
import sys

PLACEHOLDER_MARK = ":900000000"
TARGET_EXACT = {"docs/listings_detail.json.gz", "docs/listings_slim.json.gz"}


def is_target(path: str) -> bool:
    if path in TARGET_EXACT:
        return True
    return path.startswith("docs/listings_part_") and path.endswith(".json.gz")


def final_commit_map() -> dict:
    """path -> original commit hash (on main) that currently defines its live content."""
    paths = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD", "--name-only"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    targets = [p for p in paths if is_target(p)]
    out = {}
    for p in targets:
        h = subprocess.run(
            ["git", "log", "--format=%H", "-1", "--", p],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        out[p] = h
    return out


def main() -> int:
    final_for = final_commit_map()
    print(f"# {len(final_for)} target paths; placeholder mark {PLACEHOLDER_MARK}", file=sys.stderr)

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    stdout.write(f"blob\nmark {PLACEHOLDER_MARK}\ndata 0\n".encode())

    current_oid = None
    stripped = 0
    kept = 0

    def readline():
        return stdin.readline()

    line = readline()
    while line:
        if line.startswith(b"original-oid "):
            current_oid = line[len(b"original-oid "):].strip().decode()
            stdout.write(line)
        elif line.startswith(b"M ") and b" " in line[2:]:
            parts = line.rstrip(b"\n").split(b" ", 3)
            if len(parts) == 4:
                _, mode, mark, path = parts
                path_s = path.decode()
                if is_target(path_s):
                    if final_for.get(path_s) == current_oid:
                        kept += 1
                        stdout.write(line)
                    else:
                        stripped += 1
                        stdout.write(b"M " + mode + b" " + PLACEHOLDER_MARK.encode() + b" " + path + b"\n")
                else:
                    stdout.write(line)
            else:
                stdout.write(line)
        elif line.startswith(b"commit "):
            current_oid = None
            stdout.write(line)
        else:
            stdout.write(line)
        line = readline()

    print(f"# kept {kept} live M-lines, stripped {stripped} historical M-lines", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
