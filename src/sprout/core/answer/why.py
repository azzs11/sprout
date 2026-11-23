"""``why``: cited answers about a line of code or a free-text question."""

from __future__ import annotations

from dataclasses import dataclass

from sprout.core.answer import evidence as ev
from sprout.core.answer.compose import Answerer, evidence_blocks, line_sentences, question_sentences
from sprout.core.answer.lineage import MAX_HOPS, MAX_LOG, line_history, line_log
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.embedder import Embedder
from sprout.core.index.store import Store
from sprout.core.retrieve.rerank import Reranker
from sprout.errors import ModelError
from sprout.models import AnswerMode, Evidence, EvidenceRole, LineHop, Sentence, WhyAnswer

NO_INDEX_NOTE = (
    "No index yet: run sprout index to add function history, reverts and related commits."
)


@dataclass(frozen=True)
class WhyOptions:
    """Tuning knobs; the defaults are what the CLI and MCP server use."""

    limit: int = 8
    max_hops: int = MAX_HOPS
    max_log: int = MAX_LOG  # commits taken from ``git log -L``
    symbol_limit: int = ev.SYMBOL_LIMIT  # other commits to the enclosing function or class


@dataclass(frozen=True)
class Models:
    """Optional models. With none of them, answers are retrieval-only and fully offline."""

    answerer: Answerer | None = None
    embedder: Embedder | None = None
    reranker: Reranker | None = None


def why_line(
    repo: Pygit2Repo,
    store: Store | None,
    path: str,
    line: int,
    *,
    rev: str | None = None,
    models: Models | None = None,
    options: WhyOptions | None = None,
) -> WhyAnswer:
    """Explain ``path:line`` as of ``rev`` (default HEAD)."""
    models = models or Models()
    options = options or WhyOptions()
    as_of = repo.resolve(rev)
    hops = line_history(repo, path, line, rev=as_of, max_hops=options.max_hops)
    symbol = ev.enclosing_symbol(repo, as_of, path, line)
    found = ev.EvidenceSet(repo, store, as_of)
    ev.add_line_history(found, hops)
    ev.add_line_log(found, repo, line_log(repo, path, line, rev=as_of, limit=options.max_log))
    notes: list[str] = []
    if store is None:
        notes.append(NO_INDEX_NOTE)
    else:
        if symbol:
            paths = [path, *(h.path for h in hops)]
            ev.add_symbol_history(found, store, symbol, paths, options.symbol_limit)
        ev.add_reverts(found, store, repo)
        query = ev.line_query(symbol, hops[0].text if hops else "", path)
        notes += ev.add_related(
            found, store, query, limit=3, embedder=models.embedder, reranker=models.reranker
        )
    evidence = _keep_origin(found.ranked(options.limit), found)
    target = f"{path}:{line}"
    context = f"The code is {target}" + (f", inside {symbol}" if symbol else "") + "."
    if hops:
        context += f"\nThe line is: {hops[0].text.strip()}"
    answer = WhyAnswer(
        target=target,
        as_of=as_of,
        symbol=symbol,
        line_text=hops[0].text if hops else None,
        mode=AnswerMode.RETRIEVAL,
        sentences=line_sentences(hops, evidence, line),
        history=hops,
        evidence=evidence,
        notes=notes,
    )
    question = f"Why is {target} the way it is?"
    return _with_llm(answer, repo, models.answerer, question, context, path, hops)


def why_question(
    repo: Pygit2Repo,
    store: Store,
    question: str,
    *,
    rev: str | None = None,
    models: Models | None = None,
    options: WhyOptions | None = None,
) -> WhyAnswer:
    """Answer a free-text question from the history index."""
    models = models or Models()
    options = options or WhyOptions()
    as_of = repo.resolve(rev)
    found = ev.EvidenceSet(repo, store, as_of)
    notes = ev.add_related(
        found,
        store,
        question,
        limit=options.limit,
        embedder=models.embedder,
        reranker=models.reranker,
    )
    ev.add_reverts(found, store, repo)
    evidence = found.ranked(options.limit, by_relevance=True)
    answer = WhyAnswer(
        target=question,
        as_of=as_of,
        mode=AnswerMode.RETRIEVAL,
        sentences=question_sentences(evidence),
        evidence=evidence,
        notes=notes,
    )
    return _with_llm(answer, repo, models.answerer, question, "", None, [])


def _with_llm(
    answer: WhyAnswer,
    repo: Pygit2Repo,
    answerer: Answerer | None,
    question: str,
    context: str,
    path: str | None,
    hops: list[LineHop],
) -> WhyAnswer:
    """Replace the deterministic sentences with a checked model answer when one is available."""
    if answerer is None or not answer.evidence:
        return answer
    blocks = evidence_blocks(repo, answer.evidence, path=path, hops=hops)
    try:
        main = answer.evidence[0].commit.hash if path is not None else None
        messages = {e.commit.hash: e.commit.message for e in answer.evidence}
        result = answerer.answer(question, context, blocks, repo=repo, messages=messages, main=main)
    except ModelError as exc:
        return answer.model_copy(
            update={"notes": [*answer.notes, f"Showing facts only: {exc.message}"]}
        )
    notes = list(answer.notes)
    if result.forged:
        notes.append(f"Dropped {result.forged} citation(s) to commits outside the evidence.")
    if not result.kept:
        notes.append("The model's answer failed the citation check, so only facts are shown.")
        return answer.model_copy(
            update={"dropped": result.dropped, "drop_reasons": result.reasons, "notes": notes}
        )
    return answer.model_copy(
        update={
            "mode": AnswerMode.LLM,
            "model": answerer.model_id,
            "sentences": result.kept,
            "dropped": result.dropped,
            "drop_reasons": result.reasons,
            "notes": notes,
        }
    )


def _keep_origin(ranked: list[Evidence], found: ev.EvidenceSet) -> list[Evidence]:
    """Never rank the line's own origin commit out of the evidence."""
    origin = found.first(EvidenceRole.LINE_ORIGIN)
    if origin is None or any(e.commit.hash == origin.commit.hash for e in ranked):
        return ranked
    return [*ranked[:-1], origin] if ranked else [origin]


def cited(sentences: list[Sentence]) -> set[str]:
    """Every hash cited by an answer."""
    return {h for s in sentences for h in s.citations}
