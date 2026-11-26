"""Draft each task's message in every arm and record the raw outputs (resumable).

Arms: ``sprout`` (style, same-file examples, ``commit_message`` prompt, Sprout's formatting),
``diff_only`` (the same model and redacted diff with a plain prompt: the usual generator),
``skeleton`` (no model) and ``real`` (the author's message, as a reference).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from bench.commit.view import AtCommit
from bench.whybench.common import repo_path
from sprout.core.commit.message import diff_text, draft_message
from sprout.core.commit.style import learn_style, trailer_keys
from sprout.core.commit.writer import CommitWriter
from sprout.core.git import open_repo
from sprout.errors import ModelError
from sprout.llm.prompts import parse_prompt
from sprout.llm.provider import JsonSchema, Provider

BASELINE = parse_prompt((Path(__file__).parent / "diff_only.md").read_text("utf-8"), "diff_only")
_SCHEMA: JsonSchema = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


def run_tasks(
    tasks: list[dict[str, object]],
    provider: Provider,
    out: Path,
    echo: Callable[[str], None],
) -> list[dict[str, object]]:
    """Rows for ``tasks``, reusing any already in ``out`` (one JSON line per task)."""
    done = {r["hash"]: r for r in _read(out)}
    writer = CommitWriter(provider)
    with out.open("a", encoding="utf-8") as sink:
        for i, task in enumerate(tasks, 1):
            if task["hash"] in done:
                continue
            row = run_task(task, writer, provider)
            sink.write(json.dumps(row, sort_keys=True) + "\n")
            sink.flush()
            done[row["hash"]] = row
            echo(f"[{i}/{len(tasks)}] {task['repo']} {str(task['hash'])[:8]}")
    return [done[t["hash"]] for t in tasks if t["hash"] in done]


def run_task(
    task: dict[str, object], writer: CommitWriter, provider: Provider
) -> dict[str, object]:
    """Every arm for one task."""
    repo = open_repo(repo_path(str(task["repo"])))
    view = AtCommit(repo, str(task["hash"]))
    diff = view.diff(staged=True)
    style = learn_style(view)
    started = time.perf_counter()
    draft = draft_message(view, diff, style=style, writer=writer)
    sprout_s = time.perf_counter() - started
    skeleton = draft_message(view, diff, style=style)
    subject, _, rest = str(task["message"]).strip().partition("\n")
    return task | {
        "style": style.model_dump(mode="json"),
        "examples": len(draft.examples),
        "diff_truncated": draft.diff_truncated,
        "arms": {
            "sprout": {
                "subject": draft.subject,
                "body": draft.body,
                "question": draft.question,
                "model_ok": draft.model is not None,
                "seconds": round(sprout_s, 2),
                "reverts": any(t.key == "Reverts" for t in draft.trailers),
            },
            "diff_only": _diff_only(provider, diff_text(diff)[0]),
            "skeleton": {"subject": skeleton.subject, "body": None},
            "real": {"subject": subject.strip(), "body": _real_body(rest)},
        },
    }


def _diff_only(provider: Provider, diff: str) -> dict[str, object]:
    started = time.perf_counter()
    try:
        reply = provider.complete(
            system=BASELINE.system, prompt=BASELINE.render(diff=diff), max_tokens=400,
            schema=_SCHEMA,
        )  # fmt: skip
        data = json.loads(reply)
    except (ModelError, json.JSONDecodeError):
        data = None
    seconds = round(time.perf_counter() - started, 2)
    if not isinstance(data, dict) or not str(data.get("subject") or "").strip():
        return {"subject": "", "body": None, "model_ok": False, "seconds": seconds}
    body = data.get("body")
    return {
        "subject": " ".join(str(data["subject"]).split()),
        "body": body.strip() or None if isinstance(body, str) else None,
        "model_ok": True,
        "seconds": seconds,
    }


def _real_body(rest: str) -> str | None:
    """The real message's body without its trailer block."""
    text = rest.strip()
    if trailer_keys(f"x\n\n{text}") and "\n\n" in text:
        text = text.rpartition("\n\n")[0]
    elif trailer_keys(f"x\n\n{text}"):
        text = ""
    return text.strip() or None


def _read(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
