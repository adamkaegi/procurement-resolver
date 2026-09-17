#!/usr/bin/env bash
# Build demo/register.html from the current warehouse and publish it as
# index.html on the gh-pages branch (served at
# https://adamkaegi.github.io/procurement-resolver/).
#
# This is the whole republish procedure -- run it after any warehouse
# rebuild whose data should reach the site. Deliberately manual (see
# docs/DECISIONS.md, "Data browser: a static snapshot, not a live backend").
set -euo pipefail

cd "$(dirname "$0")/.."

uv run python scripts/build_register.py

PARENT="$(mktemp -d)"
WORKTREE="$PARENT/gh-pages"
git worktree add "$WORKTREE" gh-pages
trap 'git worktree remove --force "$WORKTREE" 2>/dev/null; rm -rf "$PARENT"' EXIT

cp demo/register.html "$WORKTREE/index.html"

if git -C "$WORKTREE" diff --quiet; then
  echo "site already matches the current build -- nothing to publish"
else
  git -C "$WORKTREE" add index.html
  git -C "$WORKTREE" commit -m "publish register"
  git -C "$WORKTREE" push origin gh-pages
  echo "published to gh-pages"
fi
