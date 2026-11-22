"""Turn evidence into sentences: deterministic ones, and model-written ones that pass checks."""

from __future__ import annotations

from sprout.core.answer.citations import CheckResult, check
from sprout.core.answer.rationale import RationaleScore, score_message
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.redact import redact
from sprout.llm.prompts import load_prompt
from sprout.llm.provider import Provider
from sprout.models import Evidence, EvidenceRole, Label, LineHop, Sentence

MAX_MESSAGE_CHARS = 1_500
MAX_PATCH_CHARS = 1_500


def line_sentences(hops: list[LineHop], evidence: list[Evidence], line: int) -> list[Sentence]:
    """Facts about a line, each quoting a commit message verbatim and citing it."""
    out: list[Sentence] = []
    if hops:
        last = hops[0].commit
        out.append(
            Sentence(
                text=f"Line {line} was last changed in {last.short_hash} on "
                f'{last.authored_at:%Y-%m-%d}: "{last.summary}".',
                citations=[last.hash],
            )
        )
        first = hops[-1].commit
        if first.hash != last.hash and hops[-1].introduced:
            out.append(
                Sentence(
                    text=f"It was first written in {first.short_hash} on "
                    f'{first.authored_at:%Y-%m-%d}: "{first.summary}".',
                    citations=[first.hash],
                )
            )
    out += _common_sentences(evidence)
    return out


def question_sentences(evidence: list[Evidence]) -> list[Sentence]:
    """The most relevant commits for a question, quoted and cited."""
    out = [
        Sentence(
            text=f'{e.commit.short_hash} ({e.commit.authored_at:%Y-%m-%d}): "{e.commit.summary}".',
            citations=[e.commit.hash],
        )
        for e in evidence[:3]
    ]
    return out + _common_sentences(evidence)


def _common_sentences(evidence: list[Evidence]) -> list[Sentence]:
    out: list[Sentence] = []
    # Among the most relevant few, the one whose message states its reason most clearly.
    candidates = [e for e in evidence[:3] if _excerpt(e) and _rationale(e).score > 0.5]
    best = max(candidates, key=lambda e: _rationale(e).score, default=None)
    if best is not None:
        out.append(
            Sentence(
                text=f"The clearest stated reason is in {best.commit.short_hash}: "
                f'"{(_excerpt(best) or "").rstrip(".")}"'
                + ("…" if _rationale(best).clipped else "")
                + ".",
                citations=[best.commit.hash],
            )
        )
    reverted = next((e for e in evidence if e.reverted_by), None)
    if reverted is not None:
        out.append(
            Sentence(
                text=f"{reverted.commit.short_hash} was later reverted: "
                f'"{reverted.commit.summary}".',
                citations=[reverted.commit.hash, *reverted.reverted_by[:1]],
            )
        )
    revert = next((e for e in evidence if Label.REVERT in e.labels), None)
    if revert is not None and (reverted is None or revert.commit.hash not in reverted.reverted_by):
        out.append(
            Sentence(
                text=f"{revert.commit.short_hash} reverted an earlier change: "
                f'"{revert.commit.summary}".',
                citations=[revert.commit.hash],
            )
        )
    issues = {
        f"#{r.number}": e.commit.hash
        for e in evidence
        if e.role is not EvidenceRole.RELATED
        for r in e.refs
        if r.repo is None
    }
    if issues:
        out.append(
            Sentence(
                text="Linked issues: " + ", ".join(sorted(issues, key=lambda s: int(s[1:]))) + ".",
                citations=list(dict.fromkeys(issues.values())),
            )
        )
    return out


def _rationale(evidence: Evidence) -> RationaleScore:
    return score_message(evidence.commit.message, labels=evidence.labels, refs=len(evidence.refs))


def _excerpt(evidence: Evidence) -> str | None:
    return _rationale(evidence).excerpt


def evidence_blocks(
    repo: Pygit2Repo, evidence: list[Evidence], *, path: str | None, hops: list[LineHop]
) -> dict[str, str]:
    """What the model sees for each commit (secrets redacted). Also used to check citations."""
    line_at = {h.commit.hash: h.text for h in hops}
    blocks: dict[str, str] = {}
    for e in evidence:
        c = e.commit
        meta = [f"[{c.short_hash}] {e.role.value}, {c.authored_at:%Y-%m-%d}, {c.author.name}"]
        if e.labels:
            meta.append("labels: " + ", ".join(label.value for label in e.labels))
        if e.refs:
            meta.append("issues: " + ", ".join(f"#{r.number}" for r in e.refs))
        if e.reverted_by:
            meta.append("reverted by: " + ", ".join(h[:7] for h in e.reverted_by))
        if c.hash in line_at:
            meta.append(f"the line at this commit: {line_at[c.hash].strip()}")
        message, _ = redact(c.message.strip()[:MAX_MESSAGE_CHARS])
        patch = repo.file_patch(c.hash, path, max_chars=MAX_PATCH_CHARS) if path else ""
        patch, _ = redact(patch)
        body = "\n".join(meta) + f"\nmessage:\n{message}"
        if patch:
            body += f"\ndiff of {path}:\n{patch}"
        blocks[c.hash] = body
    return blocks


class Answerer:
    """Asks a model for a cited answer and keeps only sentences that pass the checks."""

    def __init__(self, provider: Provider, *, max_tokens: int = 2_048) -> None:
        self.provider = provider
        self.prompt = load_prompt("why_answer")
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        """Provider and prompt version, recorded with each answer."""
        return f"{self.provider.name}|{self.prompt.id}"

    def answer(
        self,
        question: str,
        context: str,
        blocks: dict[str, str],
        *,
        repo: Pygit2Repo,
    ) -> CheckResult:
        """Model answer, filtered by the citation checker."""
        reply = self.provider.complete(
            system=self.prompt.system,
            prompt=self.prompt.render(
                question=question, context=context, evidence="\n\n".join(blocks.values())
            ),
            max_tokens=self._max_tokens,
        )
        return check(reply, blocks, exists=repo.has_commit)
