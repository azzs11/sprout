# WhyBench v0

WhyBench measures whether a tool can find **the commit that explains why code is the way it is**. Each task has one or more *gold* commits: real commits whose messages state the reason, written by the project's own developers.

Status: **v0, a first public draft.** The numbers in `results/` are produced by the commands below and nowhere else.

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

Eleven permissively licensed projects across Python, JavaScript, Go and Rust, listed in `repos.toml` with their licences. Each is pinned to the snapshot in `data/whybench-v0/repos.lock.json`. Repositories are **split by repo**:

- **tune** (`click`, `httpx`, `cobra`): may be inspected while developing Sprout.
- **test** (the other eight): only reported.

No repository appears in both splits.

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

**Not measured in v0:**
- Answers written by a model, and their citation precision. These need a model, so v0 runs retrieval and ranking only.
- An LLM-only (closed-book) baseline, for the same reason.

## Reproduce

```sh
uv run python -m bench build            # clone, pin and index (downloads ~150 MB of local models once)
uv run python -m bench lines            # regenerate line tasks (deterministic per repo)
uv run python -m bench run --split test # writes results/whybench-v0-test.{json,md}
uv run python -m bench speed --split test # p50/p95 of sprout why per task -> results/whybench-v0-speed-test.{json,md}
```

Clones live in the user cache directory, or in `SPROUT_BENCH_CACHE` if set.

## Who wrote the questions

The natural-language questions in `data/whybench-v0/questions.jsonl` were written from sampled reason-stating commits. Each one is reworded rather than copied from the commit, so keyword search gets no free matches, and each is stored with the commit it was written from. They have not yet been reviewed independently. A planned v1 step is an independent review of a sample, with agreement reported.

## Known biases and limits

- **Gold labels are incomplete.** A reason can live in an issue, a pull request or a commit that does not use one of the connectives. Those commits are never gold, so a tool can be "wrong" while showing a genuinely helpful commit.
- **The gold rule favours some systems.** It selects messages with explicit causal words, and Sprout's ranking also rewards explicit reasons, so it is favoured by construction. The `no rationale ranking` ablation shows how much of its score comes from that ranking.
- **Sprout now reads the reference history too.** Since 2026-11-23, `sprout why` adds every commit from `git log -L` for the line (blame's offset mapping lost the trail on unevenly rewritten hunks). The gold commit is the newest reason-stating commit in that same history. So, for line tasks, `sprout why` is close to rebuilding the gold rule with a softer causal-word scorer. Read its line recall as "how well it ranks the right commit from the line's history", not as evidence that it discovers commits `git log -L` cannot find.
- **Questions are written from the gold commits.** They may be easier or more literal than real developer questions.
- **Projects are well known.** Pre-trained models may have seen these projects. Retrieval systems are less affected than LLM answers, and a post-cutoff slice is planned for v1.
- **Small scale.** About 40 line tasks per repository and about 12 questions per repository. Treat differences of a few points as noise.

## Tuning protocol

Ranking choices are made on the **tune** split only (61 line tasks and 34 questions from `click`, `httpx` and `cobra`). The test split is then run once per change, and both before and after numbers are kept in the commit history of `results/`. Changes so far:

| Date | Change | Chosen on tune because |
|---|---|---|
| 2026-11-23 | Questions: search relevance leads, rationale only breaks ties | the old rationale bonus never beat pure relevance on tune (R@1 0.529 either way) and let wordy commits outrank the best hit |
| 2026-11-23 | Lines: add every `git log -L` commit (up to 20); cap function history at 4 commits | tune line R@5 0.853 → 0.984, buried R@1 0.50 → 0.80; cap 4 tied cap 0 and beat 8 |
