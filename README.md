# sprout

> **Status: early stage.** Sprout is being rebuilt from scratch. Only basic git commands work so far. This README describes where it is going and what works today.

Sprout is meant to be your codebase's memory. It will answer "why is this code like this?" from git history, cite the commits that prove each answer, and warn people and AI coding agents before they repeat a past mistake.

## What works today

Three read-only commands for exploring a repository from the terminal:

```sh
sprout status              # branch, HEAD, staged / unstaged / untracked files
sprout diff [--staged]     # changes with a per-file summary (--stat for summary only)
sprout history [PATH]      # recent commits, optionally only those touching PATH
```

Every command accepts `--json` for scripts and agents, and `-C <dir>` to run against another repository. They work in a brand-new repository with no commits yet.

Everything below is planned and not built yet.

## Where it is going

- **`sprout why <file>:<line>`**: explains why a line exists. Every claim cites a commit hash, and a claim without a citation is left out.
- **`sprout search "<question>"`**: hybrid keyword and semantic search over the repository's commit history.
- **Regression Memory (`sprout risk`)**: before you commit a change, Sprout checks that code's history for reverts, bug fixes and security fixes, then gives a short risk card with the commits that matter.
- **MCP server**: AI agents such as Claude Code and Cursor can ask the same questions and run the same risk check before they edit code.
- **Commit messages that keep the "why"**: Sprout learns the repository's message style and asks you one question about the reason for a change.
- **Local-first**: the full pipeline is designed to run offline with local models. Code is sent to a remote model only if you configure one.
- **WhyBench**: an open benchmark of real "why" questions with gold-standard commits, so Sprout's accuracy can be measured and published.

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Honest README, licence, project metadata | Done |
| 1 | Foundation: Typer + Rich CLI with `--json`, pygit2 git layer, fixture-repo tests, CI on 3 OSes | Done |
| 2 | History index: commits, hunks, symbols (tree-sitter), hybrid search | Planned |
| 3 | WhyBench and `sprout why` with cited answers | Planned |
| 4 | MCP server for AI agents | Planned |
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
uv run ruff check . && uv run ruff format --check .
uv run pyright               # strict mode for src/
```

Test repositories are built by script with fixed dates, so commit hashes are the same on every machine. To inspect them, run `uv run python -m tests.fixtures.builder /tmp/sprout-fixtures`.

## Licence

[MIT](LICENSE)
