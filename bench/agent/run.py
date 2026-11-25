"""Run agent-impact tasks: the same request, with and without Sprout, several times each.

Each run gets a fresh copy of a clone pinned at the revert, pruned of every later commit, branch,
tag and reflog entry, so the agent cannot read the future. Both arms may read the repository and
run read-only git (``log``, ``show``, ``blame``, ``diff``): an agent checking history itself is
the real alternative to Sprout. The Sprout arm adds Sprout's MCP server and its edit hook, with
no language model (facts only) and no embedding model.

Scoring does not use Sprout: a run *re-applied* the reverted change when at least half of the
reverted commit's added lines (whitespace-normalised) appear in the agent's diff.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.whybench.common import cache_dir, repo_path
from sprout.core.index.lines import normalize

ARMS = ("baseline", "sprout")
TOOLS = [
    "Read", "Edit", "Write", "Grep", "Glob",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)", "Bash(git diff:*)",
]  # fmt: skip
REAPPLIED = 0.5
WORK = "agent-impact-v0"


def run_all(
    tasks: list[dict[str, object]],
    *,
    agent: str,
    model: str,
    repeats: int,
    workers: int,
    echo: Callable[[str], None],
) -> Path:
    """Run every (task, arm, repeat) not already in the runs file; return that file."""
    work = cache_dir() / WORK
    work.mkdir(parents=True, exist_ok=True)
    runs_file = work / f"runs-{model}.jsonl"
    done = {(r["revert"], r["arm"], r["repeat"]) for r in _read(runs_file)}
    jobs = [
        (task, arm, rep)
        for task in tasks
        for rep in range(repeats)
        for arm in ARMS
        if (task["revert"], arm, rep) not in done
    ]
    bases = {str(t["revert"]): prepare(t, work) for t in tasks}
    echo(f"{len(jobs)} runs to do ({len(done)} already done)")

    def one(job: tuple[dict[str, object], str, int]) -> dict[str, object]:
        task, arm, rep = job
        return run_once(task, arm, rep, bases[str(task["revert"])], agent=agent, model=model)

    with ThreadPoolExecutor(max_workers=workers) as pool, runs_file.open("a") as out:
        for row in pool.map(one, jobs):
            out.write(json.dumps(row) + "\n")
            out.flush()
            echo(f"{row['repo']} {str(row['revert'])[:8]} {row['arm']} #{row['repeat']}:"
                 f" reapplied={row['reapplied']} mentioned={row['mentioned']}")  # fmt: skip
    return runs_file


def prepare(task: dict[str, object], work: Path) -> dict[str, Path]:
    """Pruned clones at the revert: one plain, one with a Sprout index (built once)."""
    folder = work / f"{task['repo']}-{str(task['revert'])[:10]}"
    plain, indexed = folder / "plain", folder / "sprout"
    if not (plain / ".git").exists():
        _pruned_clone(repo_path(str(task["repo"])), str(task["revert"]), plain)
    if not (indexed / ".sprout" / "index.db").exists():
        shutil.rmtree(indexed, ignore_errors=True)
        shutil.copytree(plain, indexed, symlinks=True)
        _sh([sys.executable, "-m", "sprout", "index", "-C", str(indexed), "--no-embed", "--json"])
    return {"baseline": plain, "sprout": indexed}


def run_once(
    task: dict[str, object], arm: str, rep: int, bases: dict[str, Path], *, agent: str, model: str
) -> dict[str, object]:
    """One agent session in a fresh copy; returns the scored result."""
    run_dir = bases[arm].parent / f"run-{arm}-{rep}"
    shutil.rmtree(run_dir, ignore_errors=True)
    shutil.copytree(bases[arm], run_dir, symlinks=True)
    command = [agent, "-p", str(task["prompt"]), "--model", model, *_flags(arm, run_dir)]
    start = time.monotonic()
    done = subprocess.run(
        command, cwd=run_dir, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900
    )
    result, tools, cost, turns, denied = _parse(done.stdout)
    _sh(["git", "-C", str(run_dir), "add", "-A", "-N"])
    diff = _sh(["git", "-C", str(run_dir), "diff"])
    share = _share(task, diff)
    revert = str(task["revert"])
    row: dict[str, object] = {
        "repo": task["repo"], "revert": revert, "reverted": task["reverted"], "arm": arm,
        "repeat": rep, "model": model, "exit": done.returncode, "seconds": round(time.monotonic() - start, 1),
        "reapplied": share >= REAPPLIED, "share": round(share, 3), "edited": bool(diff.strip()),
        "mentioned": revert[:7] in result or "revert" in result.lower(),
        "cited_hash": revert[:7] in result, "denied_tools": denied, "tools": tools, "cost_usd": cost, "turns": turns,
        "result": result[:2000],
    }  # fmt: skip
    shutil.rmtree(run_dir, ignore_errors=True)
    return row


def _flags(arm: str, run_dir: Path) -> list[str]:
    flags = [
        "--output-format", "stream-json", "--verbose", "--max-turns", "25",
        "--setting-sources", "project", "--strict-mcp-config", "--no-session-persistence",
    ]  # fmt: skip
    tools = list(TOOLS)
    if arm == "sprout":
        config = run_dir.parent / "sprout-agent.json"
        hooks = run_dir.parent / "sprout-hooks.json"
        _write_agent_config(config, hooks)
        flags += ["--mcp-config", str(config), "--settings", str(hooks)]
        tools.append("mcp__sprout")
    return [*flags, "--allowedTools", *tools]


def _write_agent_config(config: Path, hooks: Path) -> None:
    quiet = {
        "SPROUT_LLM_PROVIDER": "none",
        "SPROUT_EMBED_MODEL": "none",
        "SPROUT_RERANK_MODEL": "none",
    }
    server = {"command": sys.executable, "args": ["-m", "sprout", "mcp", "serve"], "env": quiet}
    config.write_text(json.dumps({"mcpServers": {"sprout": server}}))
    hook = f"{Path(sys.executable).parent / 'sprout-hook'} agent"
    entry = {"matcher": "Edit|MultiEdit|Write", "hooks": [{"type": "command", "command": hook}]}
    hooks.write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}))


def _parse(stream: str) -> tuple[str, list[str], float | None, int | None, list[str]]:
    """Final answer, tool calls, cost, turns, and tool calls refused (by a hook or permissions)."""
    result, tools, cost, turns, denied = "", [], None, None, list[str]()
    for line in stream.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("type") == "assistant":
            for part in message.get("message", {}).get("content", []):
                if part.get("type") == "tool_use":
                    tools.append(str(part.get("name")))
        elif message.get("type") == "result":
            result = str(message.get("result") or "")
            cost, turns = message.get("total_cost_usd"), message.get("num_turns")
            denied = [str(d.get("tool_name")) for d in message.get("permission_denials") or []]
    return result, tools, cost, turns, denied


def _share(task: dict[str, object], diff: str) -> float:
    """Share of the reverted commit's added lines that the agent's diff adds."""
    wanted = set(task["added"])  # type: ignore[arg-type]
    added = {
        n
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++") and (n := normalize(line[1:]))
    }
    return len(wanted & added) / len(wanted) if wanted else 0.0


def _pruned_clone(source: Path, revert: str, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    _sh(["git", "clone", "--quiet", "--no-local", "--no-checkout", str(source), str(target)])
    git = ["git", "-C", str(target)]
    _sh([*git, "checkout", "--quiet", "--detach", revert])
    for ref in _sh([*git, "for-each-ref", "--format=%(refname)"]).split():
        _sh([*git, "update-ref", "-d", ref])
    _sh([*git, "remote", "remove", "origin"])
    _sh([*git, "reflog", "expire", "--expire=now", "--all"])
    _sh([*git, "gc", "--quiet", "--prune=now"])


def _sh(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def _read(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
