# Commit replay v0: do Sprout's drafted messages fit the repository better than a diff-only prompt?

Real commits from the 15 WhyBench repositories are replayed one at a time. For each, the
repository is seen as it was just before the commit, with the commit's changes staged. Sprout
drafts a message, and the same model drafts one from the diff alone. Both are scored against the
repository's own style and the author's real message.

```sh
uv run python -m bench commit-replay select            # tasks are frozen; --force re-picks
uv run python -m bench commit-replay run --split tune  # also: test, holdout (run once)
```

Results: `bench/results/commit-replay-v0-<split>.md` (the JSON next to it has every number;
per-task drafts are in the bench cache).

This is not the CommitBench dataset (Schall et al., 2024). CommitBench pairs diffs with messages
but has no repository history, and Sprout's method needs the history before each commit (style,
past messages to the same files, revert candidates). The rows here come from repositories that are
cloned and pinned, so they can be rebuilt.

## Method

**Tasks** (`bench/data/commit-replay-v0/tasks.jsonl`, picked by `bench/commit/tasks.py` before
any draft was made): 20 per repository, 300 in all. They are people's single-parent commits (no
merges, reverts or bot commits) made on or after 2024-10-01, which is after qwen2.5-coder's
release, so the model is less likely to have seen the real messages. Each changes 1 to 30 files,
and not only binary ones. The sample is shuffled with a seed from the repository's name, from the
newest 5,000 commits at the pinned snapshot.

**No leakage.** Every arm reads the repository through `bench/commit/view.py`. History stops at
the commit's parent, the branch name is hidden (old branch names would hint at the answer), and
the staged diff is the commit's own diff. A unit test checks that the replayed commit and
everything after it are invisible.

**Arms.** All use the same redacted diff, capped at 12,000 characters.
- **Sprout:** `sprout commit`'s method, with the style learned from the 300 commits before, past
  messages to the same files as examples, the `commit_message` prompt, and Sprout's formatting
  of the subject.
- **Diff-only:** the same model with a plain "write a commit message for this diff" prompt
  (`bench/commit/diff_only.md`), which is how most generators work.
- **Skeleton:** Sprout with no model.
- **Author:** the real message, as a reference.

**Model.** `qwen2.5-coder:7b` through Ollama, on the machine named in the results.

**Scores** (`bench/commit/metrics.py`, all deterministic):
- **Style:** the share of 4 checks the subject passes. The first three compare it with the
  author's own subject for that commit: a type prefix exactly when the author used one, the same
  capitalisation, and a full stop exactly when the author used one. The fourth checks the length
  is within the repository's 90th percentile before the commit (at least 50 characters).
  Comparing with the author, not with the style Sprout learned, keeps Sprout from being scored
  against its own rules. (Round 1 on tune used the learned style; see the tune log below.)
- **Type match:** the same Conventional Commit type as the author, where the author used one.
- **ROUGE-L F1** between the drafted and the real subject. **Caveat:** it rewards the author's
  wording, not correctness, and a good subject can score low.
- **Body repeats the subject:** word overlap (Jaccard) of at least 0.6 between the body's first
  line and the subject.
- **States a reason:** a strong causal word ("because", "due to", "to avoid", ...), using the same
  rule as the reasons gate. Sprout tells the model never to give a reason, because a reason the
  model guessed is not the author's.
- **Question asks why:** Sprout's question contains "why" and does not ask "what changed".

**Splits.** Tune (click, httpx, cobra) may be looked at and the prompt changed on it. Test and
holdout are run once, on a clean tree, after the prompt is frozen.

## Known limits

- Automatic scores only. Whether people prefer the messages needs the blind comparison
  (8 or more raters), which is a separate step.
- In a repository whose authors are split (cobra uses a type prefix in about half of its recent
  commits), no single rule can match every author, so even a perfect follower of the majority
  misses some.
- One local model. Bigger models may close the gap, or widen it.
- 20 commits per repository is small; per-repository numbers are noisy.

## Tune log

- **Round 1** (prompt `commit_message@1`, style scored against Sprout's learned style). Sprout
  0.992 vs diff-only 0.946 style; type match 0/9 for Sprout vs 1/9 (cobra is split between plain
  and prefixed subjects). Sprout added a body to 63% of drafts, but authors wrote one for 20%.
  The cause was two bugs in style learning, not the prompt: CRLF messages (common from GitHub)
  were not split into paragraphs, so trailers and `---------` lines counted as a body, and
  GitHub's generated squash lists (`* <subject>` lines) counted as written bodies. Both are fixed.
  A shorter style window (25, 50 or 100 commits instead of 300) did not predict the author's
  prefix any better on tune (0.85 for all), so the window stays at 300.
