# Using Sprout from AI agents (MCP)

Sprout's MCP server gives an agent four read-only tools for the repository it runs in:

| Tool | Use it to |
|---|---|
| `why` | Explain a line (`src/auth.py:42`) or answer a "why" question, citing commits |
| `search_history` | Find commits by topic |
| `explain_commit` | Read one commit: stated reason, files and functions changed, reverts, redacted diff |
| `check_edit` | Before an edit: proceed, review or stop, citing the past fixes and reverts it would undo (no model) |

The output is plain text under about 1,500 tokens. Every claim carries a 12-character commit hash. A `Basis:` line says whether a commit message states the reason or not. When none does, the message text is shown as written and labelled as not checked.

Everything runs on your machine. Sprout calls no model unless a local Ollama server is running, or you configure a remote provider with your own key.

## Claude Code

**Plugin** (recommended). It adds the MCP server and a `/sprout:why` skill:

```sh
claude plugin marketplace add azzs11/sprout
claude plugin install sprout@sprout
```

The plugin starts the server with `uvx` from GitHub, so you need [uv](https://docs.astral.sh/uv/). Build the index once in each repository:

```sh
uvx --from git+https://github.com/azzs11/sprout sprout index
```

**Project config** instead of the plugin, written by `sprout init` (it also builds the index):

```sh
sprout init
```

This adds Sprout to `.mcp.json`. Claude Code asks you to approve project servers the first time it sees them. Use the plugin or `sprout init`, not both: each one registers a server named `sprout`.

## Cursor

```sh
sprout init -a cursor
```

This writes `.cursor/mcp.json`. Restart Cursor, or reload its MCP servers, to pick it up.

## VS Code

```sh
sprout init -a vscode
```

This writes `.vscode/mcp.json`. If that file has comments, Sprout leaves it unchanged and prints the entry to paste instead.

## Other agents

Point any MCP client at this command, started in the repository's folder:

```sh
sprout mcp serve
```

To use HTTP instead of stdio, run `sprout mcp serve --http`, which serves `http://127.0.0.1:8765/mcp` (pick another port with `--port`). Requests whose Host or Origin header is not local are rejected. There is no authentication, so only bind to another address on a network you trust.

## The edit check (Claude Code plugin)

The plugin also runs `sprout-hook agent` before every Edit, MultiEdit and Write. It compares the edit with past fix, security and revert commits, the same way `sprout risk` does (no model, no network):

- **Nothing found**, or no Sprout index in the repository: no output, and the edit goes ahead.
- **Review finding** (the edit undoes most of a past fix, or changes code a revert restored): the edit goes ahead, and the agent gets a note citing the commit.
- **High finding** (it re-applies a reverted change, or undoes a security fix): Claude Code asks you first and shows the cited commits.

The check needs `sprout-hook` on your PATH. Install it once with `uv tool install git+https://github.com/azzs11/sprout`. Without it the hook does nothing: it never blocks an edit because of missing setup, and it never uses the network.

| Variable | Effect |
|---|---|
| `SPROUT_RISK_LEVEL=high` | Only high findings (no notes for review findings) |
| `SPROUT_STRICT=1` | High findings are refused, not asked about |
| `SPROUT_SKIP=1` | No check |
| `SPROUT_DEBUG=1` | Print hook errors (normally a failing check stays silent) |

## Tell the agent when to use it

The server's instructions already ask agents to call `why` before changing code they did not write. To make it a project rule, add this to your `AGENTS.md` or `CLAUDE.md`:

```markdown
## Git history (Sprout)
Before changing or deleting code you did not write, call the `why` tool with its `path:line`,
especially for checks, retries, timeouts and workarounds. Cite the commit hashes it returns.
If a cited commit was reverted, or the change would undo a past fix, say so before editing.
If Sprout says no commit states a reason, say that instead of guessing one.
```

## Removing it

```sh
sprout uninstall              # MCP configs and .sprout/
claude plugin uninstall sprout
```

## Troubleshooting

- **"No Sprout index found"**: run `sprout index` (or `sprout init`) in the repository. Line questions work without an index; questions in words need one.
- **The server does not appear**: restart the agent. Claude Code lists servers and their status under `/mcp`.
- **Answers are facts only**: start Ollama and pull the model `sprout init` names, or set `SPROUT_LLM_PROVIDER`.
- **The first start is slow**: `uvx` downloads Sprout and its dependencies once, then uses uv's cache.
