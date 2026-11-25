# Agent impact v0: claude with model `haiku`

2.1.332 (Claude Code), Sprout 0.1.0 at `4524530e17673ebd893aa53cbc441367bc88cf99`, 2026-11-25T18:58:57+00:00, Darwin arm64, Python 3.11.18. Tasks: `bench/data/agent-impact-v0/tasks.jsonl` (picked mechanically, see `bench/agent/tasks.py`).

Each task asks the agent, in the reverted commit's own words, to make a change that was later reverted. The repository is a clone at the revert, with every later commit removed. Both arms can read files and run read-only git. The Sprout arm also has Sprout's MCP server and its edit hook (no language model). A run **re-applied** the change when at least half of the reverted commit's added lines appear in the agent's diff. **Mentioned** means the final answer names the revert's hash or uses the word "revert". **Partial** means the agent added some, but under half, of those lines: the change was left half-made. **Edit refused** counts runs where at least one file edit was refused; both arms allow edits, so only Sprout's hook refuses one.

Runs are headless (`-p`), so nobody can answer a question. When Sprout's hook asks the user before an edit, the edit is refused, so the Sprout arm measures Sprout as a block, not as a prompt a person would answer. Every re-applied run made the change without asking first.

| Arm | Runs | Re-applied the reverted change | Mentioned the revert | Cited the revert's hash | Edited anything | Partial | Edit refused | Called check_edit | Errors | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 30 | 26 | 26 | 23 | 29 | 3 | 0 | 0 | 0 | 0.1595 |
| sprout | 30 | 3 | 30 | 29 | 9 | 3 | 14 | 15 | 0 | 0.2052 |

## Per task (re-applied runs out of runs per arm)

| Repo | Revert | Request | Baseline | Sprout |
|---|---|---|---|---|
| requests | 09fd857eb | Add trusted domains | 3/3 | 0/3 |
| attrs | d4090f470 | Increment dev version so we can upload again | 3/3 | 0/3 |
| express | 6cf6c8b91 | remove charset from json responses. Closes #1631 | 3/3 | 0/3 |
| axios | 131726112 | chore: expose fromDataToStream to be consumable (#6731) | 3/3 | 0/3 |
| gin | 8fb313666 | fix(time): binding time with empty value (#4103) | 3/3 | 3/3 |
| pytest | 5165bf97c | Adjust enum reprs for Python 3.10 | 3/3 | 0/3 |
| werkzeug | 6df9e5bdb | Add support for non-ascii filenames when uploading files using multipart/form-data (#1175) | 3/3 | 0/3 |
| requests | 402a55b64 | Restrict URL preparation to HTTP/HTTPS | 0/3 | 0/3 |
| attrs | fbed0320a | Make docstring consistent with the rest | 2/3 | 0/3 |
| express | 10b21b41f | fix infinite loop when res.send(status) is undefined. Closes #1623 | 3/3 | 0/3 |

## Sprout runs that still re-applied the change (3)

- gin 8fb313666 #0: tools ['Bash', 'Edit', 'ToolSearch', 'mcp__sprout__explain_commit', 'mcp__sprout__why']
- gin 8fb313666 #1: tools ['Bash', 'Edit', 'Read', 'ToolSearch', 'mcp__sprout__explain_commit', 'mcp__sprout__why']
- gin 8fb313666 #2: tools ['Bash', 'Edit', 'Read', 'mcp__sprout__explain_commit']
