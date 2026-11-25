---
name: why
description: Explain why code is the way it is from this repository's git history, citing the commits that prove it. Use when asked "why does this code do X", "why was this added", "is it safe to remove this check, retry or timeout", and before changing or deleting code you did not write.
---

# Why is this code like this?

Input from the user, if any: $ARGUMENTS

1. Pick the target: a `path:line` (the line the user points at, or the line you are about to change) or a question in their words.
2. Call the `why` tool from the `sprout` MCP server with that target. If you are about to edit the code, call it before the edit.
3. To read one cited commit in full, call `explain_commit`. To find commits by topic, call `search_history`.
4. Answer in two to five sentences. Name the commit hash behind every claim, as the tool printed it. Quote a reason only where Sprout quoted one.
5. If a cited commit was REVERTED, or the change would undo a fix, say that first: it is the main risk of changing this code.
6. If the `Basis:` line says no commit states a reason, say so plainly. Describe what changed and when, and do not invent the intent.
7. If the tool says there is no Sprout index, line questions still work. For questions and revert links, tell the user to run `sprout init` (or `sprout index`) in the repository.
