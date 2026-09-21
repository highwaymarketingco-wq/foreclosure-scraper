#!/bin/sh
# Install the 95 MiB pre-commit size gate into this clone's .git/hooks.
# .git/hooks is not versioned, so re-run this after a fresh clone.
#   sh scripts/install_size_gate.sh
set -e
ROOT="$(git rev-parse --show-toplevel)"
HOOK="$ROOT/.git/hooks/pre-commit"
if [ -e "$HOOK" ] && ! grep -q "git_size_gate.sh" "$HOOK" 2>/dev/null; then
  echo "A different pre-commit hook already exists at $HOOK. Not overwriting it." >&2
  exit 1
fi
cat > "$HOOK" <<'EOF'
#!/bin/sh
# Installed by scripts/install_size_gate.sh. The logic lives in the versioned script.
ROOT="$(git rev-parse --show-toplevel)"
[ -f "$ROOT/scripts/git_size_gate.sh" ] || exit 0
exec sh "$ROOT/scripts/git_size_gate.sh"
EOF
chmod +x "$HOOK"
echo "installed $HOOK"
