# Revert replay v0: would `sprout risk` have warned in time?

Revert replay asks whether `sprout risk` would have warned about a commit before history showed
it was a mistake. It uses the 15 WhyBench repositories and the same splits (`bench/repos.toml`),
pinned to the snapshots in `bench/data/whybench-v0/repos.lock.json`.

```sh
uv run python -m bench risk --split tune      # or test, holdout, all
```

Results: [`tune`](../results/risk-replay-v0-tune.md), [`test`](../results/risk-replay-v0-test.md),
[`holdout`](../results/risk-replay-v0-holdout.md). The JSON next to each report has every number.
The per-commit cases are written to the bench cache (`risk-replay-v0-<split>.jsonl`).

## Method

Every non-merge commit is checked, oldest first, as `sprout risk` would check it. Only line
fingerprints of commits made *before* it are used (`check_changes(before=...)`); a test checks
that no warning ever cites a later commit.

**Labels.** Both are incomplete: a mistake fixed without a revert or a `fix`-style message counts
as clean.

- **Reverted** (headline): a later commit reverts it, by hash or by quoting its subject.
- **Fix-inducing or reverted** (SZZ-lite): it was reverted, or a fix or security commit within
  365 days removed a line it added (same file, whitespace-normalised). This counts mistakes that
  were fixed rather than reverted.

**Flags compared.**

- **Sprout**: any finding, which is what `sprout risk` shows by default.
- **Recent-fix file baseline**: a fix, security or revert commit touched one of the same files in
  the previous 30 days.
- **Random**: as many commits as Sprout flags, chosen at random (precision = base rate).

**Alert budgets** flag at most 5%, 10% or 50% of all commits, highest score first. Sprout's score
is its level, then its matched lines. The baseline's score is how many recent fix commits touched
the files.

Intervals are 95% bootstrap intervals over commits (1,000 resamples, fixed seed).

## How the rules were chosen

`risk@1` was run on the **tune** split (click, httpx, cobra) only. It warned on 17.1% of commits,
and nearly all of its alerts were edits near a fix. `risk@2` changed one rule, still looking at
tune only: removing a fix's lines counts only when the change removes at least half of them (and
at least two, unless the fix added one line). `risk@2` was then frozen and run once on **test** and
once on **holdout**, at commit `2f1c586`.

## Results (risk@2)

| Split | Commits | Sprout alert rate | Precision, fix-inducing or reverted (random / baseline) | Reverts caught |
|---|---|---|---|---|
| tune | 4,668 | 0.055 | 0.236 (0.124 / 0.197) | 2 of 14 |
| test | 35,758 | 0.084 | 0.318 (0.147 / 0.212) | 22 of 155 |
| holdout | 7,974 | 0.087 | 0.301 (0.140 / 0.234) | 1 of 24 |

The baseline flags 32-38% of commits. At the same 5% alert budget, the baseline is more precise on
the wider label than Sprout on tune (0.355 vs 0.231) and holdout (0.386 vs 0.313), and slightly
less precise on test (0.330 vs 0.351).

## What this shows, and what it does not

- Sprout's warnings point at changes that later needed a fix about twice as often as random, on
  12 repositories it was not tuned on. It warns on about 1 in 12 commits.
- It rarely anticipates an actual revert. On holdout it caught 1 of 24 reverts, and its revert
  precision (0.001) is no better than random (0.003). Most reverts undo a new mistake, which no
  earlier fix or revert in the history describes.
- Ranking by how many fixes recently touched a file is a strong signal. Sprout does not use it
  yet.

## Known biases

- **Shared mechanism.** Sprout warns about lines past fixes touched, and the SZZ-lite label
  counts lines future fixes touch. Part of the precision on that label reflects that fixed code
  keeps needing fixes. The file-level baseline controls for some of this, not all.
- **SZZ-lite is noisy.** It blames the last commit that added an identical line in the same file.
  Refactors and moved code are blamed wrongly; renamed files are not followed.
- **Few reverts.** 14 (tune), 155 (test) and 24 (holdout), so the revert intervals are wide.
- **Timestamps.** Commits are ordered by committer time. Rebased histories can share timestamps;
  commits made in the same second do not see each other.
- **Not yet included:** the MSR 2026 agent-revert set, and the agent-impact test (Claude Code with
  and without Sprout on known reverts).
