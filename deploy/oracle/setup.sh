#!/usr/bin/env bash
# One-time provisioning for the free Oracle Cloud Always-Free VM.
#
# Target: Ampere ARM (aarch64), Ubuntu 22.04 or 24.04, the default "ubuntu" user.
# Idempotent — safe to re-run after a repo update or a partial run.
#
# Auth: this repo is private, so clone/push need a GitHub token. Provide a
# fine-grained PAT with "Contents: read and write" on the repo, either as
# $GITHUB_TOKEN or staged at ~/github_token.txt BEFORE running this.
#
#   export GITHUB_TOKEN=github_pat_xxx
#   bash deploy/oracle/setup.sh          # if you already cloned the repo, or:
#   curl -fsSL <raw setup.sh url> | bash # bootstrap from nothing
set -euo pipefail

REPO_SLUG="${REPO_SLUG:-highwaymarketingco-wq/foreclosure-scraper}"
DIR="${DIR:-$HOME/foreclosure-scraper}"
TOKEN="${GITHUB_TOKEN:-$(cat "$HOME/github_token.txt" 2>/dev/null || true)}"

echo "==> [1/6] system packages"
sudo apt-get update -y
# git + build tools; the browser system libs are handled by playwright
# --with-deps below, but a couple are listed here so `scrapling install`
# (camoufox) also has what it needs if an enricher ever renders.
sudo apt-get install -y git curl ca-certificates build-essential \
  fonts-liberation libnss3 libatk-bridge2.0-0 libgbm1 libasound2 2>/dev/null \
  || sudo apt-get install -y git curl ca-certificates build-essential \
     fonts-liberation libnss3 libatk-bridge2.0-0 libgbm1 libasound2t64

echo "==> [2/6] git auth (private repo)"
if [[ -n "$TOKEN" ]]; then
  git config --global credential.helper store
  printf 'https://x-access-token:%s@github.com\n' "$TOKEN" > "$HOME/.git-credentials"
  chmod 600 "$HOME/.git-credentials"
  echo "    credential store configured from token"
else
  echo "    no token found — assuming the repo is already cloned and authed"
fi

echo "==> [3/6] uv (Python toolchain manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || \
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

echo "==> [4/6] clone / update repo"
if [[ -d "$DIR/.git" ]]; then
  git -C "$DIR" pull --ff-only || git -C "$DIR" pull --rebase --autostash
else
  git clone "https://github.com/${REPO_SLUG}.git" "$DIR"
fi
cd "$DIR"

echo "==> [5/6] Python 3.12 + dependencies"
uv python install 3.12
uv sync --frozen || uv sync

echo "==> [6/6] stealth browser for any rendering enricher (best-effort)"
# The VM runs only datacenter-safe SOURCES, but a few enrichers may render a
# page; chromium covers those. camoufox (scrapling) is best-effort — the run
# degrades gracefully if it is missing on ARM.
uv run python -m playwright install --with-deps chromium \
  || uv run python -m playwright install chromium || true
uv run scrapling install || true

mkdir -p "$DIR/.secrets" "$DIR/logs" "$DIR/docs/handoff"

echo ""
echo "==> setup complete."
echo "    Next:"
echo "      1. Copy your secrets to $DIR/.secrets/  (see deploy/oracle/secrets_checklist.md)"
echo "      2. Test one run:   cd $DIR && bash deploy/oracle/vm_run.sh"
echo "      3. Install the daily timer:  bash deploy/oracle/install_timer.sh"
