# sprout

> **Status: early stage.** History search, cited "why" answers, warnings for people and AI agents, and an MCP server work today. Commit messages that keep the "why" are being built. Sprout is not on PyPI yet; install it from a source checkout.

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

**With a local Ollama model** (or Claude, if you opt in), the model fills in a short form instead of writing free text: which commits matter, what each one changed, and the reason copied word for word from its message. Sprout writes the sentences from that form. A reason is kept only if it comes from the commit message and states a cause, not just the subject line. A final checker drops any sentence whose commit is not in the evidence or whose words the commit does not support.

`--at` answers as of an older commit and never cites anything newer.

**Before indexing:** line questions work without an index, using git history only. `sprout index` adds function history, reverts and related commits.

### Check a change against history

```sh
sprout risk              # uncommitted changes (staged and unstaged) against HEAD
sprout risk --staged     # only what git commit would take
sprout risk --diff x.patch   # any unified diff ('-' reads stdin)
```

`sprout index` keeps the changed lines of every fix, security and revert commit, as whitespace-normalised hashes. The lines such a commit removed count as "bad" (the bug, or the change that was reverted). The lines it added count as "guards" (the fix, or the code the revert restored). `sprout risk` warns when your change re-adds a bad line or removes a guard. It cites the commit, shows the matching lines with `+`/`-` and quotes the commit's stated reason.

Some rules keep it quiet:

- When several commits touched a line, the newest one decides, so a change that was reverted and later re-landed stops warning.
- Lines that are too short, or that appear in many fix commits, are ignored.
- Code you only move or re-indent does not count.
- Matches must be in the same file, unless the line is long enough to follow a rename.

The level is a word (`low`, `review`, `high`), not a colour. `high` means undoing a security fix or re-applying most of a reverted change. With nothing to cite it stays silent.

`sprout risk` is advisory: it exits 0 unless a finding involves a past security fix (exit 2), or you pass `--strict` (exit 2 on any finding). `SPROUT_SKIP=1` skips the check. No model is called.

**Hooks.** The same check runs before a commit and before an AI agent edits a file. Neither calls a model or the network, and both stay silent in a repository with no Sprout index:

- `sprout init --git-hook` installs a git pre-commit hook (it never replaces a hook it did not write; `sprout uninstall` removes it). Findings are printed as advice and the commit goes ahead, unless it undoes a past security fix. Pre-commit framework users can use the `sprout-risk` hook from this repository's `.pre-commit-hooks.yaml`.
- The Claude Code plugin checks every Edit and Write. A review finding becomes a note to the agent, and the edit goes ahead. A high finding (re-applying a reverted change, or undoing a security fix) asks you first.
- `SPROUT_RISK_LEVEL=high` shows only high findings, `SPROUT_STRICT=1` blocks on any finding, and `SPROUT_SKIP=1` skips the check. `sprout risk --level high` does the same by hand.
- On GitHub, the action in this repository runs the same check on every pull request. It keeps one comment citing the commits, and stays silent when there is nothing to cite. See [docs/github-action.md](docs/github-action.md).
- When a warning has stopped being right, switch it off with a reason: `sprout ack <commit> -m "why"` (the risk is accepted), or `sprout supersede <commit> -m "why" --by <commit>` (a later change made that fix or revert obsolete). Entries go in `.sprout-acks.toml`; commit it so your team shares it and reviews changes to it. `sprout ack` lists the entries, and `--remove` turns a commit's warnings back on. Sprout refuses to acknowledge a commit it would never cite, so an entry is never silently useless.
- Speed: a typical check takes about 80 ms. The slowest 5% of large edits take 84 to 136 ms, depending on the repository. Without an index it takes about 24 ms ([hook latency](bench/risk/README.md#hook-latency)). High findings, the ones that interrupt, come up on about 0.4 to 0.5% of commits in repositories not used for tuning.

**Measured: revert replay v0.** Every commit in 12 repositories that were not used for tuning is replayed against only the history before it ([benchmark card](bench/risk/README.md)). A commit counts as positive if it was later reverted, or if a fix within a year removed a line it added. From [`risk-replay-v0-test.md`](bench/results/risk-replay-v0-test.md) and [`risk-replay-v0-holdout.md`](bench/results/risk-replay-v0-holdout.md):

| `risk@2` | Commits | Sprout warns on | Precision of a warning | Random at the same rate | Recent-fix file baseline (warns on) |
|---|---|---|---|---|---|
| test (8 repos) | 35,758 | 8.4% | 0.318 | 0.147 | 0.212 (37.7%) |
| holdout (4 repos) | 7,974 | 8.7% | 0.301 | 0.140 | 0.234 (35.0%) |

So a warning points at a change that later needed fixing about twice as often as chance. It rarely predicts an actual revert: it caught 22 of 155 reverts on test and 1 of 24 on holdout, where its revert precision is no better than random. At the same 5% alert budget, simply ranking commits by how many recent fixes touched their files does better on holdout (0.386 vs 0.313) and slightly worse on test (0.330 vs 0.351). The card lists the known biases, including that the "fixed later" label and Sprout's own warnings both lean on fix commits.

### Write commit messages that keep the why

```sh
git add -p
sprout commit                       # drafts a message and asks you one question about why
sprout commit --why "..." -o msg.txt && git commit -F msg.txt
git commit -F <(sprout commit --why "Card payments drop 1% of requests at peak.")
```

`sprout commit` never commits. It prints a message for your staged changes, and you commit it yourself.

- **Style:** it learns how the repository writes messages from its own recent commits (merges, reverts and bot commits are skipped). That covers Conventional Commit types and scopes, capitals, full stops, subject length and how often there is a body. Past commits to the same files are shown to the model as examples.
- **What:** a local Ollama model (or Claude, if you opt in) describes what the diff changes. Secrets are removed from the diff first. The model is told never to give a reason. Without a model, or with `--no-llm`, you get a subject guessed from the paths and past commits, to edit.
- **Why:** the model asks you one question about the change. Your answer is kept word for word in a `Why:` trailer, and `sprout why` later shows it as that commit's reason.
- **Other trailers:** `--fixes 12` adds `Fixes: #12`. An issue number in the branch name (`fix/12-retries`) adds `Refs: #12`, which closes nothing. If the staged diff undoes a recent commit by hand, the subject becomes `Revert "..."` with a `Reverts: <hash>` trailer, so Regression Memory learns about it too.

In a terminal it shows the message and the command to commit it. When its output is piped it prints only the message, and `--json` gives every part.

**Inside your own `git commit`:** `sprout init --commit-hook` adds an opt-in prepare-commit-msg hook. For a plain `git commit`, it writes the draft into the editor, with the why question as a comment. Git removes comments, so a question you don't answer leaves no trace.
- `-m`, `-F`, templates, merges, squashes and amends already have a message, so they are left alone.
- The model gets 30 seconds (`SPROUT_COMMIT_TIMEOUT`). After that, the skeleton is used.
- `SPROUT_SKIP=1` skips it, and `sprout uninstall` removes it. Pre-commit framework users can use the `sprout-commit-msg` hook instead.

### Measured: WhyBench v0

[WhyBench](bench/README.md) asks which commit explains a line or answers a "why" question. The correct answer for each is a commit whose message states a reason. The headline numbers below come from the **holdout** split: 139 line questions and 44 natural-language questions from 4 repositories (werkzeug, koa, chi, regex) that were added after the method was frozen and run once. From [`bench/results/whybench-v0-holdout.md`](bench/results/whybench-v0-holdout.md):

| Line questions, correct commit ranked first | All (139) | Buried behind later edits (50) |
|---|---|---|
| `git blame` | 0.590 | 0.040 |
| `sprout why` | **0.770** | **0.660** |

Part of this lead comes from how the benchmark is built: the correct commit is chosen from `git log -L` by looking for causal words, and `sprout why` uses `git log -L` and also rewards causal words. On natural-language questions, `sprout why` ranks exactly as hybrid search with reranking does (0.705 first, 0.864 in the top five), so it adds nothing there yet. The 8-repository test split shows the same pattern ([`whybench-v0-test.md`](bench/results/whybench-v0-test.md)).

**Written answers** with `qwen2.5-coder:7b` running locally ([`whybench-v0-answers-holdout.md`](bench/results/whybench-v0-answers-holdout.md), [`whybench-v0-faithfulness-holdout.json`](bench/results/whybench-v0-faithfulness-holdout.json)):

| Holdout | Lines | Questions |
|---|---|---|
| a kept sentence cites the correct commit | 0.856 | 0.864 |
| the same model with no git history cites it | 0.0 | 0.0 |

Of 60 sampled kept sentences, 0.767 are fully supported by the commit they cite (0.933 at least partly). Without history, the model never names the right commit but still gives a reason for 47% of lines and 96% of questions. The benchmark card lists the other baselines, the judging method and the known biases.

### Use it from an AI agent (MCP)

In Claude Code, install the plugin (MCP server plus a `/sprout:why` skill):

```sh
claude plugin marketplace add azzs11/sprout
claude plugin install sprout@sprout
```

For Cursor, VS Code and other agents, and for a snippet that tells agents when to call Sprout, see [docs/mcp.md](docs/mcp.md).

`sprout mcp serve` runs an MCP server over stdio for the repository it starts in. It offers four read-only tools:

- `why`: the same answer as `sprout why`, for a `path:line` or a question. The output is plain text under about 1,500 tokens, with 12-character hashes, the quoted reason, any reverts, and a `Basis:` line that says when no commit states a reason.
- `search_history`: ranked commits for a query.
- `explain_commit`: one commit's stated reason, the files and functions it changed, what it reverts or was reverted by, and its diff with secrets redacted.
- `check_edit`: before an edit, the same check as `sprout risk`. You pass the path and the old and new text, a diff, or nothing for the uncommitted changes. It returns proceed, review or stop with the cited commits, and calls no model.

A reason is quoted only if it passes the same check as `sprout why` answers: copied from the message body and stating a cause, so "Fixes #42." alone does not count.

`sprout mcp serve --http` serves streamable HTTP on this machine instead (`--port` picks the port). Requests whose Host or Origin header is not local are rejected. There is no authentication, so Sprout warns if you bind to another address.

The server keeps the embedding model, the reranker and the vector index loaded between calls.

**Set it up in one step** with `sprout init` in your repository:

- It indexes commits, files, functions and reverts in the foreground, then adds semantic vectors in the background. Use `--wait` to add them now, or `--no-embed` to skip them. The background job logs to `.sprout/embed.log`.
- It adds Sprout to `.mcp.json` (Claude Code). Use `-a cursor` for `.cursor/mcp.json` and `-a vscode` for `.vscode/mcp.json`. Other servers in those files are kept. A file with comments is never rewritten; you get the entry to paste instead.
- It says where written answers will come from: a local Ollama model, if it is running and pulled, otherwise facts only.
- It lists the three most recent reverts it found.

The config uses a global `sprout` if one is on your PATH (for example after `uv tool install`). Otherwise it uses this machine's Python path and warns you not to commit it that way.

`sprout uninstall` removes Sprout from all three config files (deleting any file or folder that held only Sprout) and deletes `.sprout/`. Use `--keep-index` to keep the index. Your `.sprout.toml` is kept.

To add the server by hand instead, from a source checkout:

```sh
claude mcp add sprout -- uvx --from /path/to/sprout sprout mcp serve
```

Everything below is planned and not built yet.

## Where it is going

- **Commit messages that keep the "why"**: an MCP tool for agents, and a blind comparison with diff-only messages.
- **"Time Machine" web view**: an annotated edition of a well-known open-source repository, with cited answers for any line.
- **Release**: `uv tool install` from PyPI, a docs site and a short report.
- **Local-first throughout**: everything runs offline with local models. Code is sent to a remote model only if you configure one.

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Honest README, licence, project metadata | Done |
| 1 | Foundation: Typer + Rich CLI with `--json`, pygit2 git layer, fixture-repo tests, CI on 3 OSes | Done |
| 2 | History index: commits, hunks, symbols (tree-sitter), hybrid search | Done |
| 3 | WhyBench and `sprout why` with cited answers | Done (v0) |
| 4 | MCP server for AI agents, `sprout init`, Claude Code plugin | Done |
| 5 | Regression Memory: `sprout risk`, git hooks, GitHub Action | Done |
| 6 | Commit messages with rationale: `sprout commit` | In progress |
| 7 | "Time Machine" web view | Planned |
| 8 | PyPI release, docs site, report | Planned |

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
