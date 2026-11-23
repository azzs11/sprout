# sprout

> **Status: early stage.** Sprout is being rebuilt from scratch. History search and cited "why" answers work; warnings for people and agents are next. This README describes where it is going and what works today.

Sprout is meant to be your codebase's memory. It will answer "why is this code like this?" from git history, cite the commits that prove each answer, and warn people and AI coding agents before they repeat a past mistake.

## What works today

Three read-only commands for exploring a repository from the terminal:

```sh
sprout status              # branch, HEAD, staged / unstaged / untracked files
sprout diff [--staged]     # changes with a per-file summary (--stat for summary only)
sprout history [PATH]      # recent commits, optionally only those touching PATH
```

Every command accepts `--json` for scripts and agents, and `-C <dir>` to run against another repository. They work in a brand-new repository with no commits yet.

### Search your history

```sh
sprout index                          # build or update the index in .sprout/ (safe to stop and resume)
sprout search "why do we retry payments"
sprout search "verify_token" --mode bm25
```

`sprout index` reads every commit and records:
- the files it changed;
- the functions and classes it touched, using tree-sitter in 12 languages;
- the identifiers it changed;
- issue references (`fixes #12`);
- reverts, linked to the commit they undid.

Results combine keyword search (SQLite FTS5, BM25 ranking) with semantic search (local [fastembed](https://github.com/qdrant/fastembed) models, downloaded once), then a local reranker re-orders them. A result that was later reverted says so. Re-running `sprout index` only adds new commits, and the index stays out of `git status`.

- `--no-embed` skips semantic vectors.
- `--since 2y` limits history.
- `--rebuild` starts over.

**Privacy:** indexing and search run entirely on your machine, with no API key and no telemetry.

**Optional LLM summaries:** `sprout index --summarise` adds one-paragraph summaries using a local [Ollama](https://ollama.com) model by default. Secrets are removed from diffs before any model sees them. To use Claude instead, install `sprout[anthropic]`, then set `SPROUT_LLM_PROVIDER=anthropic` and your own `ANTHROPIC_API_KEY`. Diffs are sent to Anthropic only in that case.

**Settings:** `SPROUT_*` environment variables or a `.sprout.toml` in the repository root, for example `embed_model = "none"`.

### Ask why

```sh
sprout why src/_pytest/assertion/rewrite.py:300     # why is this line the way it is?
sprout why "why do fixtures tear down in reverse order"
sprout why src/app.py:42 --at v1.2 --json           # as of an older version, for scripts and agents
```

**For a line,** Sprout works out which commits explain it, newest first:
- it walks the line's history with `git blame`, following moved, renamed and re-indented code;
- it adds every commit `git log -L` finds for the line, in case the blame walk lost the trail;
- it adds the most recent commits that changed the same function or class;
- it adds reverts and related commits from the index.

For a line, it ranks them by how clearly each message states a reason. For a free-text question, search relevance comes first and the stated reason only breaks ties. It then prints an answer with the commit hash behind every sentence.

**Facts-only mode:** without a language model (or with `--no-llm`), the answer is built only from quoted commit messages.

**With a local Ollama model** (or Claude, if you opt in), the model writes the answer, but a checker keeps only sentences that cite commits from the evidence. Quoted words must appear in the cited commit, and the rest of the sentence must be supported by it.

`--at` answers as of an older commit and never cites anything newer.

**Before indexing:** line questions work without an index, using git history only. `sprout index` adds function history, reverts and related commits.

### Measured: WhyBench v0

[WhyBench](bench/README.md) asks which commit explains a line or answers a "why" question. The correct answer for each is a commit whose message states a reason. The benchmark covers 205 line questions and 87 natural-language questions from 8 open-source repositories that were not used during development. From [`bench/results/whybench-v0-test.md`](bench/results/whybench-v0-test.md):

| Line questions, correct commit ranked first | All (205) | Buried behind later edits (109) |
|---|---|---|
| `git blame` | 0.459 | 0.064 |
| `sprout why` | **0.717** | **0.560** |

Part of this lead comes from how the benchmark is built: the correct commit is chosen from `git log -L` by looking for causal words, and `sprout why` uses `git log -L` and also rewards causal words. On natural-language questions, `sprout why` currently ranks exactly as hybrid search with reranking does (0.839 first, 0.977 in the top five), so it adds nothing there yet. The benchmark card lists the other baselines and the known biases.

Everything below is planned and not built yet.

## Where it is going

- **Regression Memory (`sprout risk`)**: before you commit a change, Sprout checks that code's history for reverts, bug fixes and security fixes, then gives a short risk card with the commits that matter.
- **MCP server**: AI agents such as Claude Code and Cursor can ask the same questions and run the same risk check before they edit code.
- **Commit messages that keep the "why"**: Sprout learns the repository's message style and asks you one question about the reason for a change.
- **Local-first**: the full pipeline is designed to run offline with local models. Code is sent to a remote model only if you configure one.

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Honest README, licence, project metadata | Done |
| 1 | Foundation: Typer + Rich CLI with `--json`, pygit2 git layer, fixture-repo tests, CI on 3 OSes | Done |
| 2 | History index: commits, hunks, symbols (tree-sitter), hybrid search | Done |
| 3 | WhyBench and `sprout why` with cited answers | Done (v0) |
| 4 | MCP server for AI agents, `sprout init`, Claude Code plugin | Planned |
| 5 | Regression Memory: `sprout risk`, git hooks, GitHub Action | Planned |
| 7 | "Time Machine" web view | Planned |
| 6 | Commit messages with rationale | Planned |
| 8 | PyPI release, docs site, report | Planned |

Phases 6 and 7 run in this order on purpose: the web view comes before commit messages.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```sh
git clone https://github.com/azzs11/sprout.git
cd sprout
uv sync
uv run pre-commit install   # ruff, pyright and lockfile checks on every commit
uv run sprout status
```

Run the checks by hand:

```sh
uv run pytest -n auto --cov  # tests, with coverage (must stay at 85% or more)
SPROUT_TEST_MODELS=1 uv run pytest -m models  # opt-in: real local models (~150 MB download)
uv run ruff check . && uv run ruff format --check .
uv run pyright               # strict mode for src/
```

Test repositories are built by script with fixed dates, so commit hashes are the same on every machine. To inspect them, run `uv run python -m tests.fixtures.builder /tmp/sprout-fixtures`.

## Licence

[MIT](LICENSE)
