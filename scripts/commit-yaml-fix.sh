#!/usr/bin/env bash
# Git add providers/ (or given files), commit if there are changes, push.
# Usage: commit-yaml-fix.sh              Add all of providers/
#        commit-yaml-fix.sh <file1> ...   Add only the listed files

set -e
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
if [ $# -eq 0 ]; then
  git add providers/
else
  printf '%s\n' "$@" | xargs git add
fi
git diff --staged --quiet || (git commit -m "chore: fix YAML lint" && git push)
