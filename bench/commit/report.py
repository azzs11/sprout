"""Summarise commit-replay rows: one block per arm, paired differences, per-repo rows."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from statistics import median
from typing import cast

from bench.commit import metrics as m
from sprout.models import CommitStyle

ARMS = ("sprout", "diff_only", "skeleton", "real")
Row = dict[str, object]
BOOTSTRAP = 2_000


def _arm(row: Row, arm: str) -> dict[str, object]:
    return cast("dict[str, dict[str, object]]", row["arms"])[arm]


def _style(row: Row) -> CommitStyle:
    return CommitStyle.model_validate(row["style"])


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _body(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def score(row: Row, arm: str) -> dict[str, float | bool | None]:
    """Every metric for one arm of one task."""
    a, real = _arm(row, arm), _arm(row, "real")
    subject, body = _text(a["subject"]), _body(a.get("body"))
    checks = m.style_checks(subject, _text(real["subject"]), _style(row)) if subject else {}
    return {
        "style": sum(checks.values()) / len(checks) if checks else 0.0,
        **{f"style_{k}": v for k, v in checks.items()},
        "type_match": m.type_match(subject, _text(real["subject"])) if subject else None,
        "rouge_l": m.rouge_l(subject, _text(real["subject"])),
        "has_body": body is not None,
        "restates": m.restates_subject(subject, body),
        "gives_reason": m.gives_reason(subject, body),
        "asks_why": m.asks_why(_text(a.get("question"))) if arm == "sprout" else None,
        "model_ok": bool(a.get("model_ok", True)),
    }


def summarise(rows: Sequence[Row]) -> dict[str, object]:
    """Pooled means per arm, paired sprout-vs-diff_only differences, and per-repo means."""
    repos = sorted({str(r["repo"]) for r in rows})
    return {
        "tasks": len(rows),
        "arms": {arm: _means(rows, arm) for arm in ARMS},
        "seconds_p50": {
            arm: round(median(float(cast("float", _arm(r, arm)["seconds"])) for r in rows), 2)
            for arm in ("sprout", "diff_only")
        }
        if rows
        else {},
        "paired": {k: _paired(rows, k) for k in ("style", "rouge_l", "restates", "gives_reason")},
        "per_repo": {
            n: {arm: _means([r for r in rows if r["repo"] == n], arm) for arm in ARMS}
            for n in repos
        },
    }


def _means(rows: Sequence[Row], arm: str) -> dict[str, float | None]:
    scored = [score(r, arm) for r in rows]
    keys = scored[0].keys() if scored else []
    return {k: m.mean([float(v) for s in scored if (v := s[k]) is not None]) for k in keys}


def _paired(rows: Sequence[Row], key: str) -> dict[str, float | None]:
    """Mean of sprout minus diff_only, with a 95% bootstrap interval over tasks."""
    diffs = [_num(score(r, "sprout")[key]) - _num(score(r, "diff_only")[key]) for r in rows]
    if not diffs:
        return {"mean": None, "low": None, "high": None}
    rng = random.Random(0)  # noqa: S311 - a seeded bootstrap, not security
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(BOOTSTRAP))
    return {
        "mean": round(sum(diffs) / len(diffs), 3),
        "low": round(means[int(0.025 * BOOTSTRAP)], 3),
        "high": round(means[int(0.975 * BOOTSTRAP)], 3),
    }


def _num(value: float | bool | None) -> float:
    return float(value or 0)


_ROWS: list[tuple[str, str, Callable[[float | None], str]]] = [
    ("style", "Subject formatted like the author's (share of 4 checks)", lambda v: _f(v)),
    ("style_prefix", "... type prefix exactly when the author used one", lambda v: _f(v)),
    ("style_capital", "... same capitalisation as the author", lambda v: _f(v)),
    ("style_period", "... full stop exactly when the author used one", lambda v: _f(v)),
    ("style_length", "... within the repo's usual length", lambda v: _f(v)),
    ("type_match", "Same Conventional Commit type as the author", lambda v: _f(v)),
    ("rouge_l", "ROUGE-L F1 with the author's subject (caveat in the card)", lambda v: _f(v)),
    ("has_body", "Has a body", lambda v: _f(v)),
    ("restates", "Body's first line repeats the subject", lambda v: _f(v)),
    ("gives_reason", "States a reason (strong causal word)", lambda v: _f(v)),
    ("asks_why", "Question asks why, not what changed", lambda v: _f(v)),
    ("model_ok", "Model reply usable", lambda v: _f(v)),
]


def _f(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def markdown(result: dict[str, object], header: str) -> str:
    """The results page."""
    arms = cast("dict[str, dict[str, float | None]]", result["arms"])
    lines = [
        header,
        "",
        "| Metric | Sprout | Diff-only | Skeleton | Author |",
        "|---|---|---|---|---|",
    ]
    for key, label, fmt in _ROWS:
        lines.append(f"| {label} | " + " | ".join(fmt(arms[a].get(key)) for a in ARMS) + " |")
    paired = cast("dict[str, dict[str, float | None]]", result["paired"])
    lines += ["", "Sprout minus diff-only, mean and 95% bootstrap interval over tasks:", ""]
    lines += [
        f"- {k}: {_f(v['mean'])} [{_f(v['low'])}, {_f(v['high'])}]" for k, v in paired.items()
    ]
    lines += ["", f"Median seconds per draft: {result['seconds_p50']}", "", "## Per repository", ""]
    lines += ["| Repo | Sprout style | Diff-only style | Sprout ROUGE-L | Diff-only ROUGE-L |"]
    lines += ["|---|---|---|---|---|"]
    per_repo = cast("dict[str, dict[str, dict[str, float | None]]]", result["per_repo"])
    for name, block in per_repo.items():
        s, d = block["sprout"], block["diff_only"]
        lines.append(
            f"| {name} | {_f(s['style'])} | {_f(d['style'])} | {_f(s['rouge_l'])} |"
            f" {_f(d['rouge_l'])} |"
        )
    return "\n".join(lines) + "\n"
