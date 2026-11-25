"""Summarise agent-impact runs and write ``bench/results/agent-impact-v0-<model>.{json,md}``."""

from __future__ import annotations

from collections.abc import Sequence

Row = dict[str, object]


def summarise(rows: Sequence[Row], tasks: Sequence[Row]) -> dict[str, object]:
    """Counts per arm, and per task and arm."""
    arms: dict[str, dict[str, float]] = {}
    for arm in ("baseline", "sprout"):
        mine = [r for r in rows if r["arm"] == arm]
        arms[arm] = {
            "runs": len(mine),
            "reapplied": sum(bool(r["reapplied"]) for r in mine),
            "mentioned_revert": sum(bool(r["mentioned"]) for r in mine),
            "cited_revert_hash": sum(bool(r["cited_hash"]) for r in mine),
            "edited": sum(bool(r["edited"]) for r in mine),
            "errors": sum(r["exit"] != 0 for r in mine),
            "cost_usd": round(sum(float(r["cost_usd"] or 0) for r in mine), 4),  # type: ignore[arg-type]
            "used_check_edit": sum("mcp__sprout__check_edit" in r["tools"] for r in mine),  # type: ignore[operator]
        }
    per_task = [
        {
            "repo": t["repo"],
            "revert": t["revert"],
            "request": str(t["prompt"])
            .splitlines()[0]
            .removeprefix("Please make this change in this repository: "),
            **{
                f"{arm}_reapplied": sum(
                    bool(r["reapplied"])
                    for r in rows
                    if r["revert"] == t["revert"] and r["arm"] == arm
                )
                for arm in ("baseline", "sprout")
            },
            "runs_per_arm": sum(
                1 for r in rows if r["revert"] == t["revert"] and r["arm"] == "sprout"
            ),
        }
        for t in tasks
    ]
    return {"arms": arms, "tasks": per_task}


def markdown(result: dict[str, object], rows: Sequence[Row]) -> str:
    """The report."""
    arms: dict[str, dict[str, float]] = result["arms"]  # type: ignore[assignment]
    tasks: list[Row] = result["tasks"]  # type: ignore[assignment]
    out = [
        f"# Agent impact v0: {result['agent']} with model `{result['model']}`",
        "",
        f"{result['agent_version']}, Sprout {result['sprout_version']} at `{result['sprout_commit']}`,"
        f" {result['date']}, {result['machine']}. Tasks: `bench/data/agent-impact-v0/tasks.jsonl`"
        " (picked mechanically, see `bench/agent/tasks.py`).",
        "",
        "Each task asks the agent, in the reverted commit's own words, to make a change that was"
        " later reverted. The repository is a clone at the revert, with every later commit removed."
        " Both arms can read files and run read-only git. The Sprout arm also has Sprout's MCP"
        " server and its edit hook (no language model). A run **re-applied** the change when at"
        " least half of the reverted commit's added lines appear in the agent's diff. **Mentioned**"
        ' means the final answer names the revert\'s hash or uses the word "revert".',
        "",
        "| Arm | Runs | Re-applied the reverted change | Mentioned the revert | Cited the revert's hash |"
        " Edited anything | Called check_edit | Errors | Cost (USD) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, a in arms.items():
        out.append(
            f"| {name} | {a['runs']:.0f} | {a['reapplied']:.0f} | {a['mentioned_revert']:.0f} |"
            f" {a['cited_revert_hash']:.0f} | {a['edited']:.0f} | {a['used_check_edit']:.0f} |"
            f" {a['errors']:.0f} | {a['cost_usd']} |"
        )
    out += ["", "## Per task (re-applied runs out of runs per arm)", "",
            "| Repo | Revert | Request | Baseline | Sprout |", "|---|---|---|---|---|"]  # fmt: skip
    for t in tasks:
        request = str(t["request"]).replace("|", "\\|")[:90]
        out.append(
            f"| {t['repo']} | {str(t['revert'])[:9]} | {request} | {t['baseline_reapplied']}/{t['runs_per_arm']} |"
            f" {t['sprout_reapplied']}/{t['runs_per_arm']} |"
        )
    failures = [r for r in rows if r["arm"] == "sprout" and r["reapplied"]]
    out += ["", f"## Sprout runs that still re-applied the change ({len(failures)})", ""]
    out += [
        f"- {r['repo']} {str(r['revert'])[:9]} #{r['repeat']}: tools {sorted(set(r['tools']))}"  # type: ignore[arg-type]
        for r in failures
    ] or ["None."]
    return "\n".join(out) + "\n"
