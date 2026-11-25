"""Run revert replay over a WhyBench split and write ``bench/results/risk-replay-v0-<split>``."""

from __future__ import annotations

import json
import platform
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from bench.risk import metrics as m
from bench.risk.replay import Case, replay, to_json
from bench.whybench.common import RESULTS_DIR, cache_dir, load_lock, load_specs, repo_path
from sprout import __version__
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.lines import LINES_VERSION
from sprout.core.index.store import Store
from sprout.core.risk.check import METHOD

BENCHMARK = "risk-replay-v0"


def run_split(split: str, sprout_commit: str, echo: Callable[[str], None]) -> Path:
    """Replay every repository in ``split``; return the results stem."""
    specs = [s for s in load_specs() if split == "all" or s.split == split]
    cases: list[Case] = []
    for spec in specs:
        root = repo_path(spec.name)
        git = open_repo(root)
        with Store.open(root, create=False) as store:
            build_index(git, store)  # adds missing line fingerprints; the snapshot is pinned
            cases += replay(spec.name, git, store)
        echo(f"replayed {spec.name}")
    raw = cache_dir() / f"{BENCHMARK}-{split}.jsonl"
    raw.write_text("".join(json.dumps(to_json(c)) + "\n" for c in cases), encoding="utf-8")
    result = summarise(cases, [s.name for s in specs])
    result |= {
        "benchmark": BENCHMARK,
        "split": split,
        "method": METHOD,
        "lines_version": LINES_VERSION,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "sprout_version": __version__,
        "sprout_commit": sprout_commit,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "repos": {s.name: load_lock()[s.name] for s in specs},
        "cases_file": raw.name,
    }
    stem = RESULTS_DIR / f"{BENCHMARK}-{split}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    stem.with_suffix(".md").write_text(report(result, cases), encoding="utf-8")
    return stem


LABELS = {"reverted": m.reverted, "induced": m.induced}
_LABEL_TEXT = {
    "reverted": "later reverted (the headline label)",
    "induced": "later reverted, or fix-inducing: a fix within a year removed a line it added",
}


def summarise(cases: Sequence[Case], names: list[str]) -> dict[str, object]:
    """Metrics per label (pooled, budgets) and per repository, for Sprout and the baseline."""
    return {
        "labels": {name: _label_block(cases, truth) for name, truth in LABELS.items()},
        "per_repo": {
            n: {
                f"{who}_{label}": m.confusion([c for c in cases if c.repo == n], flag, truth)
                for who, flag in (("sprout", m.sprout_flag), ("baseline", m.baseline_flag))
                for label, truth in LABELS.items()
            }
            for n in names
        },
    }


def _label_block(cases: Sequence[Case], truth: m.Truth) -> dict[str, object]:
    rate = m.confusion(cases, m.sprout_flag, truth)["alert_rate"]
    positives = sum(truth(c) for c in cases)
    return {
        "sprout": m.with_intervals(cases, m.sprout_flag, truth)
        | {"lead_days": m.lead_days(cases, m.sprout_flag)},
        "baseline": m.with_intervals(cases, m.baseline_flag, truth)
        | {"lead_days": m.lead_days(cases, m.baseline_flag)},
        "random": {
            "alert_rate": rate,
            "precision": positives / len(cases) if cases else 0.0,
            "recall": rate,
        },
        "budgets": {
            "sprout": [m.at_budget(cases, lambda c: c.score, b, truth) for b in m.BUDGETS],
            "baseline": [m.at_budget(cases, lambda c: c.baseline, b, truth) for b in m.BUDGETS],
        },
    }


def report(result: dict[str, object], cases: Sequence[Case]) -> str:
    """The Markdown report, including every hit and the first false alarms."""
    labels: dict[str, dict[str, object]] = result["labels"]  # type: ignore[assignment]
    per_repo: dict[str, dict[str, dict[str, float]]] = result["per_repo"]  # type: ignore[assignment]
    out = [
        f"# Revert replay v0: {result['split']} split",
        "",
        f"Method `{result['method']}` (line fingerprints `{result['lines_version']}`), Sprout"
        f" {result['sprout_version']} at `{result['sprout_commit']}`, {result['date']},"
        f" {result['machine']}. Snapshots pinned in `bench/data/whybench-v0/repos.lock.json`.",
        "",
        "Each non-merge commit is checked against the history *before* it. **Sprout** flags a"
        " commit when `sprout risk` would show any finding (the default). The **baseline** flags a"
        " commit that touches a file a fix, security or revert commit touched in the previous 30"
        " days. **Random** flags as many commits as Sprout, at random. Intervals are 95% bootstrap"
        " intervals over commits. Gold labels are incomplete: a mistake fixed without a revert or"
        " a `fix` label counts as clean.",
    ]
    for name, block in labels.items():
        out += _label_section(name, block)
    out += [
        "",
        "## Per repository",
        "",
        "| Repo | Commits | Reverted | Fix-inducing or reverted | Sprout alerts | Sprout hits"
        " (reverted / induced) | Baseline alerts | Baseline hits (reverted / induced) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, row in per_repo.items():
        sr, si = row["sprout_reverted"], row["sprout_induced"]
        br, bi = row["baseline_reverted"], row["baseline_induced"]
        out.append(
            f"| {name} | {sr['commits']:.0f} | {sr['positives']:.0f} | {si['positives']:.0f} |"
            f" {sr['alerts']:.0f} | {sr['hits']:.0f} / {si['hits']:.0f} | {br['alerts']:.0f} |"
            f" {br['hits']:.0f} / {bi['hits']:.0f} |"
        )
    out += _examples(cases)
    return "\n".join(out) + "\n"


def _label_section(name: str, block: dict[str, object]) -> list[str]:
    s: dict[str, object] = block["sprout"]  # type: ignore[assignment]
    b: dict[str, object] = block["baseline"]  # type: ignore[assignment]
    r: dict[str, float] = block["random"]  # type: ignore[assignment]
    budgets: dict[str, list[dict[str, float]]] = block["budgets"]  # type: ignore[assignment]
    out = [
        "",
        f"## Positive = {_LABEL_TEXT[name]}",
        "",
        f"{s['commits']:,} commits, {s['positives']} positive.",
        "",
        "| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |",
        "|---|---|---|---|---|---|",
        _row("Sprout (default)", s),
        _row("Recent-fix file baseline", b),
        f"| Random, same alert rate | n/a | {r['alert_rate']:.3f} | {r['precision']:.3f} |"
        f" {r['recall']:.3f} | n/a |",
        "",
        "Alert budgets: at most this share of all commits is flagged, highest score first."
        " Commits with no signal are never flagged, so fewer alerts may be used.",
        "",
        "| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts |"
        " Baseline precision | Baseline recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for sb, bb in zip(budgets["sprout"], budgets["baseline"], strict=True):
        out.append(
            f"| {sb['budget']:.0%} | {sb['alerts']:.0f} | {sb['precision']:.3f} |"
            f" {sb['recall']:.3f} | {bb['alerts']:.0f} | {bb['precision']:.3f} |"
            f" {bb['recall']:.3f} |"
        )
    return out


def _row(name: str, x: dict[str, object]) -> str:
    p_ci: list[float] = x["precision_ci"]  # type: ignore[assignment]
    r_ci: list[float] = x["recall_ci"]  # type: ignore[assignment]
    lead = x["lead_days"]
    return (
        f"| {name} | {x['alerts']} | {x['alert_rate']:.3f} | {x['precision']:.3f}"
        f" [{p_ci[0]:.3f}, {p_ci[1]:.3f}] | {x['recall']:.3f} [{r_ci[0]:.3f}, {r_ci[1]:.3f}] |"
        f" {lead if lead is not None else 'n/a'} |"
    )


def _examples(cases: Sequence[Case]) -> list[str]:
    hits = [c for c in cases if c.positive and m.sprout_flag(c)]
    misses = [c for c in cases if c.positive and not m.sprout_flag(c)]
    false = [c for c in cases if not c.positive and c.level == "high"]
    out = ["", "## Every hit", ""]
    out += [_case(c) for c in hits] or ["None."]
    out += ["", f"## Misses ({len(misses)} reverted commits with no warning)", ""]
    out += [_case(c) for c in misses[:15]] or ["None."]
    out += ["", f"## High-level false alarms (first 15 of {len(false)})", ""]
    out += [_case(c) for c in false[:15]] or ["None."]
    return out


def _case(c: Case) -> str:
    revert = f", reverted by `{c.reverted_by[:9]}`" if c.reverted_by else ""
    cited = ", ".join(f"`{h[:9]}`" for h in c.cited[:3]) or "nothing"
    kinds = ", ".join(c.kinds) or "no finding"
    return f"- {c.repo} `{c.hash[:9]}`{revert}: {c.level} ({kinds}); cites {cited}"
