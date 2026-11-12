#!/usr/bin/env bash
# One-shot setup for the weekly automated run.
# Refreshes gh auth scope, pushes 2 missing secrets to the repo, then commits
# + pushes the updated workflow file.
#
# Usage:
#   cd /Users/cashhigh/Desktop/foreclosure-scraper
#   bash scripts/setup_weekly.sh
#
# After this completes:
#   - ANTHROPIC_API_KEY + COURTLISTENER_TOKEN are set as GitHub Actions secrets
#   - .github/workflows/weekly.yml is updated to use them + auto-publish data
#   - You can manually trigger via:
#       gh workflow run "Weekly Foreclosure Scrape"
#     or via Actions tab in browser
#
set -euo pipefail

REPO="highwaymarketingco-wq/foreclosure-scraper"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Refreshing gh auth with workflow scope (browser will open)..."
gh auth refresh -s workflow --hostname github.com

echo ""
echo "==> Adding ANTHROPIC_API_KEY to repo secrets..."
if [[ -f "$ROOT/.secrets/anthropic_api_key.txt" ]]; then
  gh secret set ANTHROPIC_API_KEY \
    --repo "$REPO" \
    --body "$(cat "$ROOT/.secrets/anthropic_api_key.txt")"
  echo "  ANTHROPIC_API_KEY set"
else
  echo "  WARN: .secrets/anthropic_api_key.txt missing — skipped"
fi

echo ""
echo "==> Adding COURTLISTENER_TOKEN to repo secrets..."
if [[ -f "$ROOT/.secrets/courtlistener_token.txt" ]]; then
  gh secret set COURTLISTENER_TOKEN \
    --repo "$REPO" \
    --body "$(cat "$ROOT/.secrets/courtlistener_token.txt")"
  echo "  COURTLISTENER_TOKEN set"
else
  echo "  WARN: .secrets/courtlistener_token.txt missing — skipped"
fi

echo ""
echo "==> Committing + pushing workflow update..."
cd "$ROOT"
git add .github/workflows/weekly.yml
if git diff --staged --quiet; then
  echo "  Workflow file already up-to-date; nothing to push"
else
  git commit -m "weekly workflow: full pipeline + Vision + BK + auto-publish"
  git push
  echo "  Pushed."
fi

echo ""
echo "==> DONE. Trigger a test run:"
echo "    gh workflow run 'Weekly Foreclosure Scrape' --repo $REPO"
echo ""
echo "    Or watch the next scheduled run (Tuesday 09:00 UTC)."
