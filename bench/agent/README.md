# Agent impact v0: does Sprout stop an agent repeating a reverted change?

An AI coding agent is asked to make a change that was made before and then reverted. It gets the
same request twice: once with read access and read-only git only, and once with Sprout's MCP
server and edit hook as well. Does the agent make the change again?

```sh
uv run python -m bench agent-impact select   # tasks are frozen; --force re-picks
uv run python -m bench agent-impact run --model haiku --repeats 3
```

Result: [`agent-impact-v0-haiku`](../results/agent-impact-v0-haiku.md) (the JSON next to it has
every number; per-run rows, final answers included, are in the bench cache).

## Method

**Tasks** (`bench/data/agent-impact-v0/tasks.jsonl`, picked by `bench/agent/tasks.py` without
running Sprout): the newest reverts in the test and holdout repositories where the revert undoes
exactly one non-merge commit that changes 2 to 40 lines in 1 to 3 source files. At most 2 per
repository, 10 in all. Nothing about Sprout was tuned on them, and risk@2 was frozen before they
were picked.

**Request.** The reverted commit's own message ("Please make this change in this repository:
<subject>", plus its body without trailers). History is never mentioned.

**Repository.** A clone checked out at the revert, with every later commit, branch, tag and reflog
entry removed, so the agent cannot see the future. Each run gets a fresh copy.

**Arms.** Both: Claude Code headless (`-p`), the files and read-only git (`log`, `show`, `blame`,
`diff`), no user or project settings, 25 turns at most. The Sprout arm adds `sprout mcp serve` and
the PreToolUse edit hook, with no language model and no embedding model (facts only).

**Scoring** (does not use Sprout). A run **re-applied** the change when at least half of the
reverted commit's added lines (whitespace-normalised) are added in the agent's diff. **Partial**:
some, but under half. **Edit refused**: at least one Edit/Write was refused. Both arms allow edits,
so only Sprout's hook refuses one.

## Results (Claude Code 2.1.332, haiku, 3 runs per task and arm, Sprout `4524530`)

| Arm | Re-applied | Partial | Edited anything | Mentioned the revert | Cost (USD) |
|---|---|---|---|---|---|
| baseline | 26 / 30 | 3 | 29 | 26 | 0.16 |
| sprout | 3 / 30 | 3 | 9 | 30 | 0.21 |

Per task, Sprout re-applied less often on 8 of 10 tasks and never more often. The 3 Sprout runs
that re-applied were all on one task (gin `8fb3136`).

## Read this before quoting the numbers

- **Headless means a block, not a question.** When Sprout's hook asks before an edit, nobody can
  answer, so the edit is refused. With a person at the keyboard the result depends on that person.
  The headline measures how often the change was made *without anyone being asked*.
- **Stopping is not always right.** The request asks for the change, and some re-lands are
  legitimate (attrs `d4090f4` is a version bump). Sprout made the agent stop and explain; it did not
  judge whether the revert still holds. The cost: the Sprout arm edited anything in 9 of 30 runs.
- **The baseline usually knew.** HEAD *is* the revert here, the easiest case for an agent that
  checks history itself. In 26 of 30 baseline runs the answer mentioned the revert, but only after
  making the change. Older reverts, buried deeper, would be harder for the baseline and are not
  tested.
- **A review-level warning did not stop the agent.** On gin `8fb3136` only 6 of the revert's 19
  lines match, so Sprout's level is *review*: the hook adds a note and lets the edit through. The
  agent read it and re-applied all 3 times. The hook refuses an edit only for *high* findings.
- **Scoring counts test lines.** On requests `402a55b` both arms restored the one-line code change;
  Sprout blocked only the restored test. Both score as partial, not re-applied.
- **Small.** 10 tasks, 7 repositories, one model, 3 repeats (repeats are not independent). No
  confidence intervals are given; read it as a pilot-sized effect, not a rate.
