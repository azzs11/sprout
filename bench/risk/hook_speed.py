"""Hook latency: how long ``sprout-hook agent`` takes per edit, as a separate process each time.

For each repository, up to 30 recently modified files are "rewritten" to their version 40 commits
earlier (a Write event, the largest kind of edit). Each event starts a fresh interpreter, as an
agent hook does. A non-edit event measures the cost when nothing needs checking.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

FILES = 30
BACK = 40
NOOP = {"tool_name": "Read", "tool_input": {"file_path": "x"}}


def time_repo(root: Path) -> dict[str, object]:
    """Edit and no-op timings for one repository, in milliseconds."""
    edits = [_run(event) for event in _write_events(root)]
    noops = [_run(NOOP) for _ in range(10)]
    edit_ms = [ms for ms, _ in edits]
    decisions = [d for _, d in edits]
    return {
        "edits": len(edits),
        "edit": summarise(edit_ms),
        "noop": summarise([ms for ms, _ in noops]),
        "decisions": {k: decisions.count(k) for k in ("ask", "allow", "deny", "none")},
    }


def summarise(values: list[float]) -> dict[str, float]:
    """p50, p95 and max."""
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "p50": round(statistics.median(ordered), 1),
        "p95": round(p95, 1),
        "max": round(ordered[-1], 1),
    }


def _write_events(root: Path) -> list[dict[str, object]]:
    log = _git(root, "log", "-200", "--format=", "--name-only", "--diff-filter=M")
    events: list[dict[str, object]] = []
    for name in dict.fromkeys(line for line in log.splitlines() if line):
        old = _git(root, "show", f"HEAD~{BACK}:{name}")
        if old and (root / name).is_file():
            content = {"file_path": str(root / name), "content": old}
            events.append({"tool_name": "Write", "cwd": str(root), "tool_input": content})
        if len(events) == FILES:
            break
    return events


def _run(event: dict[str, object]) -> tuple[float, str]:
    start = time.perf_counter()
    done = subprocess.run(
        [sys.executable, "-m", "sprout.hook", "agent"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
    )
    ms = (time.perf_counter() - start) * 1000
    if not done.stdout.strip():
        return ms, "none"
    return ms, str(json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"])


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else ""
