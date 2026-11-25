# WhyBench v0

WhyBench measures whether a tool can find **the commit that explains why code is the way it is**. Each task has one or more *gold* commits: real commits whose messages state the reason, written by the project's own developers.

Status: **v0, a first public draft.** The numbers in `results/` are produced by the commands below and nowhere else.

The Regression Memory benchmark (revert replay for `sprout risk`) has its own card: [`risk/README.md`](risk/README.md).

## Tasks

| Kind | Input | Gold | How it is built |
|---|---|---|---|
| **line** | a repository snapshot, `path`, `line` | the most recent commit in the line's history whose message states a reason | sampled lines whose `git log -L` history contains such a commit |
| **question** | a repository snapshot and a natural-language "why" question | the commit the question was written from | written from sampled reason-stating commits (see *Who wrote the questions*) |

Line tasks are split into two strata:

- **direct**: plain `git blame` already points at the gold commit.
- **buried**: the gold commit is further back, behind later edits such as refactors, renames or tweaks.

A **reason-stating commit** is a non-merge, non-revert, non-bot commit whose message contains an explicit causal connective. The connectives are: *because, so that, in order to, to avoid, to prevent, otherwise, due to, caused by, as a result, the reason, without this, this fixes/prevents/avoids/ensures*. See `whybench/select.py`.

The reference line history comes from **git's own `git log -L`**, not from Sprout's code, so Sprout is not scored against itself.

## Repositories

Fifteen permissively licensed projects across Python, JavaScript, Go and Rust, listed in `repos.toml` with their licences. Each is pinned to the snapshot in `data/whybench-v0/repos.lock.json`. Repositories are **split by repo**:

- **tune** (`click`, `httpx`, `cobra`): may be inspected while developing Sprout.
- **test** (`requests`, `flask`, `attrs`, `pytest`, `express`, `axios`, `gin`, `ripgrep`): only reported, run once per change.
- **holdout** (`werkzeug`, `koa`, `chi`, `regex`): added on 2026-11-23 after the answer method was frozen, and run once. Nothing about Sprout was chosen by looking at it. It has 139 line tasks and 44 questions.

No repository appears in more than one split.

## Systems compared

| System | Line tasks | Questions |
|---|---|---|
| `git blame` | last commit to touch the line | none |
| `git log -L` order | the line's history, newest first | none |
| `git log -S` (pickaxe) | commits that added or removed the exact line text | none |
| BM25 / vector / hybrid / hybrid + rerank | Sprout's index queried with the line's symbol, identifiers and file name | the question text |
| `sprout why` | blame walk + `git log -L` + function history + reverts + related commits, ranked by stated rationale | hybrid + rerank + reverts, relevance first, rationale breaks ties |
| `sprout why`, no rationale ranking | ablation: the same evidence in history order | none |

**Metrics:** Recall@1, Recall@5, MRR@10 and nDCG@10 for the gold commit.

## Written answers

With a model, `sprout why` asks it to fill a fixed form rather than write free prose. For a line, Sprout's top-ranked commit is fixed as the main commit, and the model may add one more. For a question, it picks up to two commits from the evidence. For each commit it gives a short "what changed" clause and, optionally, a reason copied word for word from the commit message. Sprout writes the sentences itself, then:

- a **reason check** keeps a quoted reason only if it is copied from the commit *message* (not the diff), and is more than the subject line or an issue number, unless it states a cause ("because", "due to", "to avoid"…). Otherwise Sprout uses its own causal-sentence excerpt from the message, if there is one. It says "no commit message states why" only when the message has no body;
- the **citation checker** drops any sentence whose citation is outside the evidence, whose quote is not in the cited commit, or whose words the commit does not support.

Model: `qwen2.5-coder:7b` through Ollama, on an M-series Mac. Results: `results/whybench-v0-answers-<split>.{json,md}`.

| Metric | Meaning |
|---|---|
| answer rate | at least one model sentence survived the checks |
| sentence survival | kept sentences / written sentences |
| cites gold | a kept sentence cites the gold commit |
| closed-book | the same model with no git history: can it name the gold commit, and does it still assert a reason? |
| citation precision | share of sampled kept sentences that their cited commit fully supports, judged against the full commit message |

**Results so far** (from the files named; *cites gold* is the share of tasks where a kept sentence cites the gold commit):

| Run | Lines: cites gold | Buried lines | Questions: cites gold | Citation precision | Closed-book: cites gold |
|---|---|---|---|---|---|
| test, round 1 (`answers-test-round1`, `faithfulness-test-round1`) | 0.780 | 0.606 | 0.977 | 0.65 (n = 60) | 0.0 |
| test, round 2 (`answers-test`, `faithfulness-test`) | 0.805 | 0.651 | 0.977 | 0.85 (n = 60) | 0.0 |
| tune, round 1 replayed (`faithfulness-tune-round1`) | | | | 0.675 (n = 40) | |
| tune, round 2 (`answers-tune`, `faithfulness-tune`) | 0.967 | 0.950 | 0.882 | 0.90 (n = 40) | |
| **holdout** (`answers-holdout`, `faithfulness-holdout`) | **0.856** | **0.680** | **0.864** | **0.767** (n = 60) | 0.0 |

Without history, the same model never names the gold commit, yet it still asserts a reason for 47% of holdout lines and 96% of holdout questions. On the holdout, the new failure is pull-request template text ("I have rebased all commits…") offered as a reason; it was not seen on tune or test.

**Faithfulness judging.** `bench faithfulness` draws a seeded random sample of kept sentences. Each is judged *supported*, *partly* (true but weak: for example the subject line offered as "the reason") or *unsupported*. Verdicts, with a short note each, are in `data/whybench-v0/faithfulness-<split>*.jsonl`. They come from a single judge during development and have not yet been checked by a second reviewer.

## Reproduce

```sh
uv run python -m bench build            # clone, pin and index (downloads ~150 MB of local models once)
uv run python -m bench lines            # regenerate line tasks (deterministic per repo)
uv run python -m bench run --split test # writes results/whybench-v0-test.{json,md}
uv run python -m bench speed --split test # p50/p95 of sprout why per task -> results/whybench-v0-speed-test.{json,md}
uv run python -m bench answers --model qwen2.5-coder:7b --split test  # needs Ollama; also runs the closed-book baseline
uv run python -m bench faithfulness --model qwen2.5-coder:7b --split test  # exports a sample to judge, or scores the saved verdicts
```

Clones live in the user cache directory, or in `SPROUT_BENCH_CACHE` if set.

## Who wrote the questions

The natural-language questions in `data/whybench-v0/questions.jsonl` were written from sampled reason-stating commits. Each one is reworded rather than copied from the commit, so keyword search gets no free matches, and each is stored with the commit it was written from. They have not yet been reviewed independently. A planned v1 step is an independent review of a sample, with agreement reported.

## Known biases and limits

- **Gold labels are incomplete.** A reason can live in an issue, a pull request or a commit that does not use one of the connectives. Those commits are never gold, so a tool can be "wrong" while showing a genuinely helpful commit.
- **The gold rule favours some systems.** It selects messages with explicit causal words, and Sprout's ranking also rewards explicit reasons, so it is favoured by construction. The `no rationale ranking` ablation shows how much of its score comes from that ranking.
- **Sprout now reads the reference history too.** Since 2026-11-23, `sprout why` adds every commit from `git log -L` for the line (blame's offset mapping lost the trail on unevenly rewritten hunks). The gold commit is the newest reason-stating commit in that same history. So, for line tasks, `sprout why` is close to rebuilding the gold rule with a softer causal-word scorer. Read its line recall as "how well it ranks the right commit from the line's history", not as evidence that it discovers commits `git log -L` cannot find.
- **Questions are written from the gold commits.** They may be easier or more literal than real developer questions.
- **Projects are well known.** Pre-trained models may have seen these projects. Retrieval systems are less affected than model-written answers, and a post-cutoff slice is planned for v1.
- **Small scale.** About 40 line tasks per repository and about 12 questions per repository. Treat differences of a few points as noise.
- **Answer checks are word-level.** The reason check and the citation checker test where words come from, not meaning. Known misses on the judged samples: bullets from squash-merge messages, pull-request template text and side remarks offered as reasons, and an issue list such as "Fixes #1, Closes #2" passing as a reason.
- **One judge.** Citation precision rests on one development-time judge per sample (40–60 sentences), so it carries several points of sampling error.

## Tuning protocol

Ranking choices are made on the **tune** split only (61 line tasks and 34 questions from `click`, `httpx` and `cobra`). The test split is then run once per change, and both before and after numbers are kept in the commit history of `results/`. The holdout split is run once per frozen method. Changes so far:

| Date | Change | Chosen on tune because |
|---|---|---|
| 2026-11-23 | Questions: search relevance leads, rationale only breaks ties | the old rationale bonus never beat pure relevance on tune (R@1 0.529 either way) and let wordy commits outrank the best hit |
| 2026-11-23 | Lines: add every `git log -L` commit (up to 20); cap function history at 4 commits | tune line R@5 0.853 → 0.984, buried R@1 0.50 → 0.80; cap 4 tied cap 0 and beat 8 |
| 2026-11-23 | Answers: the model fills a form (commit, what, reason quote) and Sprout writes the sentences; for lines the top-ranked commit is fixed | on a tune subset with the same model it kept more sentences and cited the gold commit more often than free prose (exploratory runs, not kept in `results/`); the full tune run is in `results/whybench-v0-answers-tune.md` |
| 2026-11-23 | Answers: reason check (`reasons@1`) | citation precision on judged samples: test 0.65 → 0.85, tune 0.675 → 0.90. See the note below |

**How the reason check was chosen.** The failure (subject lines, code and wrong "no reason" claims offered as reasons) was first seen in a judged **test** sample, so that split was looked at while designing the check. To keep the method honest: the round-1 method was then replayed on tune and judged, and it shows the same failures (citation precision 0.675). The check's rules are generic, with no repository-specific cases. The **holdout** split was added only after the method was frozen, so its numbers are the clean measure of the answer method.
