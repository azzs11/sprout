# Sprout for Claude Code

This plugin connects Claude Code to [Sprout](https://github.com/azzs11/sprout), which answers "why is this code like this?" from the current repository's git history.

It adds:

- **The `sprout` MCP server**, with four read-only tools: `why`, `search_history`, `explain_commit` and `check_edit`. Answers cite commit hashes, quote the stated reason when there is one, and flag reverts; `check_edit` returns proceed, review or stop before an edit.
- **The `/sprout:why` skill**, for example `/sprout:why src/auth.py:42`. Claude also uses it on its own before changing code it did not write.
- **An edit check** before every Edit and Write, with no model and no network. An edit that undoes a past fix gets a note to the agent. One that re-applies a reverted change, or undoes a security fix, asks you first. It needs `sprout-hook` on your PATH: `uv tool install git+https://github.com/azzs11/sprout`. Without it the check does nothing.

## Install

```sh
claude plugin marketplace add azzs11/sprout
claude plugin install sprout@sprout
```

The server starts with `uvx` from this repository, so you need [uv](https://docs.astral.sh/uv/). The first start downloads Sprout and its dependencies; later starts use uv's cache.

Then, in each repository you work in, build the index once:

```sh
uvx --from git+https://github.com/azzs11/sprout sprout index
```

Line questions work without an index. Questions in words, function history and revert links need it.

Use either this plugin or `sprout init` in a repository, not both: each one registers a server named `sprout`.

## Privacy

Everything runs on your machine. Sprout makes no network calls of its own except to a local Ollama server, if one is running, for written answers. It sends code to a remote model only if you configure one with your own key.
