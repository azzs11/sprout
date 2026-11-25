#!/usr/bin/env bash
# Keeps one Sprout comment per pull request: creates it, updates it in place, or deletes it when
# the change is clean. Only comments written by a bot and starting with the marker are touched.
set -euo pipefail
body=$1
: "${GITHUB_REPOSITORY:?}" "${SPROUT_PR:?}"
marker='<!-- sprout-risk -->'
api="repos/$GITHUB_REPOSITORY/issues"

existing=$(gh api --paginate "$api/$SPROUT_PR/comments" \
  --jq ".[] | select(.user.type == \"Bot\" and (.body | startswith(\"$marker\"))) | .id" | head -n 1)

if [ ! -s "$body" ]; then
  if [ -n "$existing" ]; then gh api -X DELETE "$api/comments/$existing" >/dev/null; fi
  exit 0
fi
if [ -n "$existing" ]; then
  gh api -X PATCH "$api/comments/$existing" -F "body=@$body" >/dev/null
else
  gh api -X POST "$api/$SPROUT_PR/comments" -F "body=@$body" >/dev/null
fi
