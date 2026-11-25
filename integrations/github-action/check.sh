#!/usr/bin/env bash
# Checks a pull request's diff against the base branch's history, writes the job summary and
# the PR comment, and fails only as `fail-on` says. Inputs arrive as environment variables.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
: "${SPROUT_BASE:?}" "${SPROUT_HEAD:?}" "${SPROUT_FAIL_ON:=security}" "${SPROUT_COMMENT:=true}"
tmp=${RUNNER_TEMP:-$(mktemp -d)}

case "$SPROUT_FAIL_ON" in security | any | never) ;; *)
  echo "::error::fail-on must be security, any or never (got '$SPROUT_FAIL_ON')."
  exit 1 ;;
esac
if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  echo "::error::Sprout needs the full history. Use actions/checkout with fetch-depth: 0."
  exit 1
fi

# Only the base branch's history counts: the pull request's own commits are not evidence.
sprout index --rev "$SPROUT_BASE" --no-embed --json >/dev/null
git diff "$SPROUT_BASE...$SPROUT_HEAD" >"$tmp/sprout.diff"

strict=()
[ "$SPROUT_FAIL_ON" = any ] && strict=(--strict)
set +e
sprout risk --diff "$tmp/sprout.diff" --markdown ${strict[@]+"${strict[@]}"} >"$tmp/sprout.md"
code=$?
set -e
if [ "$code" -ne 0 ] && [ "$code" -ne 2 ]; then
  exit "$code"
fi

if [ -s "$tmp/sprout.md" ]; then
  cat "$tmp/sprout.md" >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
else
  echo "Sprout history check: no past fix, revert or security commit warns against this change." >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
fi
if [ "$SPROUT_COMMENT" = true ]; then
  bash "$here/comment.sh" "$tmp/sprout.md" ||
    echo "::warning::Sprout could not update the pull request comment (pull requests from forks get a read-only token). The job summary has the result."
fi
if [ "$code" -eq 2 ] && [ "$SPROUT_FAIL_ON" != never ]; then
  echo "::error::Sprout: this change undoes a past fix that fail-on=$SPROUT_FAIL_ON does not allow. See the summary."
  exit 1
fi
