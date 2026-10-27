#!/usr/bin/env bash
set -euo pipefail

git add titles.json
if git diff --cached --quiet; then
  echo "No state changes"
  exit 0
fi
git commit -m "🔄 상태 업데이트"

# Code changes can reach main while the monitor is running. Rebase the state
# commit onto those changes; never force-push or overwrite a conflicting state.
for attempt in 1 2 3; do
  git fetch --no-tags origin main
  if ! git rebase origin/main; then
    git rebase --abort
    echo "State conflict: stopped without overwriting remote changes." >&2
    exit 1
  fi
  if git push origin HEAD:main; then
    exit 0
  fi
  echo "Remote changed during save; retry ${attempt}/3" >&2
done
echo "Could not save monitor state after three attempts." >&2
exit 1
