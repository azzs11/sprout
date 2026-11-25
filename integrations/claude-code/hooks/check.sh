#!/bin/sh
# Runs Sprout's edit check when sprout-hook is installed (uv tool install git+https://github.com/azzs11/sprout).
# Without it, prints nothing and exits 0: an edit is never blocked or slowed by missing setup,
# and the check never touches the network.
[ "$SPROUT_SKIP" = 1 ] && exit 0
if command -v sprout-hook >/dev/null 2>&1; then exec sprout-hook agent; fi
cat >/dev/null
exit 0
