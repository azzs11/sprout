"""Score model-written ``why`` answers: how many survive the citation check, and what they cite.

These are checker-based numbers, not judged citation precision. A kept sentence cites a
commit from the evidence and its quotes and content words appear in that commit, but it can
still misread it. Judged faithfulness is measured separately (``bench faithfulness``).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import cast

from bench.whybench.evaluate import Context
from sprout.core.answer.compose import Answerer
from sprout.core.answer.why import Models, why_line, why_question
from sprout.llm.provider import Provider
from sprout.models import AnswerMode, WhyAnswer

Task = dict[str, object]
Record = dict[str, object]


def answer_task(task: Task, ctx: Context, answerer: Answerer) -> Record:
    """Run ``sprout why`` with a model on one task and record what survived."""
    start = time.perf_counter()
    snapshot = str(task["snapshot"])
    if task["kind"] == "question":
        models = Models(answerer=answerer, embedder=ctx.embedder, reranker=ctx.reranker)
        answer = why_question(
            ctx.repo, ctx.store, str(task["question"]), rev=snapshot, models=models
        )
    else:
        answer = why_line(
            ctx.repo,
            ctx.store,
            str(task["path"]),
            int(str(task["line"])),
            rev=snapshot,
            models=Models(answerer=answerer),
        )
    return _record(task, answer, time.perf_counter() - start)


def _record(task: Task, answer: WhyAnswer, seconds: float) -> Record:
    gold = {str(g) for g in task["gold"]}  # type: ignore[union-attr]
    llm = answer.mode is AnswerMode.LLM
    kept = answer.sentences if llm else []
    cited = {h for s in kept for h in s.citations}
    return {
        "id": task["id"],
        "repo": task["repo"],
        "kind": task["kind"],
        "stratum": task.get("stratum", "question"),
        "answered": llm,
        "written": len(kept) + answer.dropped,
        "kept": len(kept),
        "drop_reasons": answer.drop_reasons,
        "cites_gold": bool(cited & gold),
        "gold_in_evidence": any(e.commit.hash in gold for e in answer.evidence),
        "sentences": [s.text for s in kept],
        "citations": [s.citations for s in kept],
        "as_of": answer.as_of,
        "notes": answer.notes,
        "seconds": round(seconds, 2),
    }


def reason_kind(reason: str) -> str:
    """The checker's reason without the sentence it was about."""
    return reason.split(":", 1)[0]


def summarise_answers(records: list[Record]) -> dict[str, float]:
    """Rates over a group of records."""
    n = len(records)
    if not n:
        return {"n": 0}
    written = sum(int(str(r["written"])) for r in records)
    kept = sum(int(str(r["kept"])) for r in records)
    reachable = [r for r in records if r["gold_in_evidence"]]
    return {
        "n": n,
        "answer_rate": round(sum(bool(r["answered"]) for r in records) / n, 3),
        "sentence_survival": round(kept / written, 3) if written else 0.0,
        "cites_gold": round(sum(bool(r["cites_gold"]) for r in records) / n, 3),
        "cites_gold_when_in_evidence": round(
            sum(bool(r["cites_gold"]) for r in reachable) / len(reachable), 3
        )
        if reachable
        else 0.0,
        "mean_seconds": round(sum(float(str(r["seconds"])) for r in records) / n, 2),
    }


def drop_counts(records: list[Record]) -> dict[str, int]:
    """How often each checker reason dropped a sentence."""
    counts: Counter[str] = Counter()
    for r in records:
        for reason in r["drop_reasons"]:  # type: ignore[union-attr]
            counts[reason_kind(str(reason))] += 1
    return dict(counts.most_common())


def summary_by_group(records: list[Record]) -> dict[str, dict[str, float]]:
    """Summaries for all line tasks, each line stratum, and questions."""
    groups: dict[str, list[Record]] = {
        "line": [r for r in records if r["kind"] != "question"],
        "line, direct": [r for r in records if r["stratum"] == "direct"],
        "line, buried": [r for r in records if r["stratum"] == "buried"],
        "question": [r for r in records if r["kind"] == "question"],
    }
    return {name: summarise_answers(rows) for name, rows in groups.items() if rows}


COLUMNS = (
    "answer_rate",
    "sentence_survival",
    "cites_gold",
    "cites_gold_when_in_evidence",
    "mean_seconds",
)


def write_answers_report(result: dict[str, object], path: Path) -> None:
    """Markdown summary of one answers run."""
    groups = result["groups"]
    drops = result["drops"]
    if not isinstance(groups, dict) or not isinstance(drops, dict):
        raise TypeError("result must contain 'groups' and 'drops'")
    out = [
        f"# WhyBench v0 written answers ({result['split']} split)",
        "",
        f"Generated {result['date']} by Sprout {result['sprout_version']} "
        f"(commit {result['sprout_commit_label']}) with `{result['model']}` on "
        f"{result['machine']}.",
        "",
        "Checker-based, not judged: a kept sentence cites a commit from the evidence and "
        "its quotes and most content words appear there. *answer rate*: at least one model "
        "sentence survived. *cites gold*: a kept sentence cites the gold commit.",
        "",
        "| Tasks | n | " + " | ".join(c.replace("_", " ") for c in COLUMNS) + " |",
        "|---|---|" + "---|" * len(COLUMNS),
    ]
    for name, stats in groups.items():
        cells = [str(stats.get(c, "")) for c in COLUMNS]
        out.append(f"| {name} | {stats['n']} | " + " | ".join(cells) + " |")
    out += ["", "## Why sentences were dropped", "", "| Reason | count |", "|---|---|"]
    out += [f"| {reason} | {count} |" for reason, count in drops.items()]
    blind = result.get("closed_book")
    if isinstance(blind, dict):
        out += [
            "",
            "## Closed-book baseline: the same model, no git history",
            "",
            "It must name the commit from memory. Any reason it gives is unsupported.",
            "",
            "| Tasks | n | cites gold | names a commit | asserts a reason |",
            "|---|---|---|---|---|",
        ]
        for name, s in cast("dict[str, dict[str, float]]", blind).items():
            if s.get("n"):
                out.append(
                    f"| {name} | {s['n']} | {s['cites_gold']} | {s['names_a_commit']} "
                    f"| {s['asserts_a_reason']} |"
                )
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ----- closed-book baseline -------------------------------------------------------------

CLOSED_BOOK_SYSTEM = (
    "You answer questions about why code in an open-source repository is the way it is. "
    "You are given no git history. If you know the commit that explains it, give its hash "
    '(at least 7 characters) as "commit", else null. Give the reason as "reason", or null if '
    "you do not know it."
)
CLOSED_BOOK_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "commit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["commit", "reason"],
    "additionalProperties": False,
}


def closed_book_prompt(task: Task) -> str:
    """The question the model sees with no evidence at all."""
    repo = str(task["repo"])
    if task["kind"] == "question":
        return f"Repository: {repo}\nQuestion: {task['question']}"
    return (
        f"Repository: {repo}\nWhy is {task['path']}:{task['line']} the way it is?\n"
        f"The line is: {str(task['line_text']).strip()}"
    )


def closed_book_task(task: Task, provider: Provider) -> Record:
    """Ask the model with no history; record whether it names the gold commit or a reason."""
    start = time.perf_counter()
    reply = provider.complete(
        system=CLOSED_BOOK_SYSTEM,
        prompt=closed_book_prompt(task),
        max_tokens=300,
        schema=CLOSED_BOOK_SCHEMA,
    )
    commit, reason = _closed_book_fields(reply)
    gold = [str(g) for g in task["gold"]]  # type: ignore[union-attr]
    named = commit.lower() if commit and len(commit) >= 7 else ""
    return {
        "id": task["id"],
        "kind": task["kind"],
        "stratum": task.get("stratum", "question"),
        "cites_gold": bool(named) and any(g.startswith(named) for g in gold),
        "names_commit": bool(named),
        "asserts_reason": bool(reason),
        "reply": reply.strip()[:500],
        "seconds": round(time.perf_counter() - start, 2),
    }


def _closed_book_fields(reply: str) -> tuple[str | None, str | None]:
    try:
        data: object = json.loads(reply)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    fields = cast("dict[str, object]", data)
    commit, reason = fields.get("commit"), fields.get("reason")
    return (
        commit.strip() if isinstance(commit, str) and commit.strip() else None,
        reason.strip() if isinstance(reason, str) and reason.strip() else None,
    )


def summarise_closed_book(records: list[Record]) -> dict[str, float]:
    """Rates for the closed-book baseline."""
    n = len(records)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "cites_gold": round(sum(bool(r["cites_gold"]) for r in records) / n, 3),
        "names_a_commit": round(sum(bool(r["names_commit"]) for r in records) / n, 3),
        "asserts_a_reason": round(sum(bool(r["asserts_reason"]) for r in records) / n, 3),
    }
