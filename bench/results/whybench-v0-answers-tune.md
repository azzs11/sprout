# WhyBench v0 written answers (tune split)

Generated 2026-11-23T09:19:52+00:00 by Sprout 0.1.0 (commit b404b3043de3, plus uncommitted changes) with `ollama:qwen2.5-coder:7b|why_answer@3+why_line_answer@1+reasons@1` on Darwin arm64, Python 3.11.18.

Checker-based, not judged: a kept sentence cites a commit from the evidence and its quotes and most content words appear there. *answer rate*: at least one model sentence survived. *cites gold*: a kept sentence cites the gold commit.

| Tasks | n | answer rate | sentence survival | cites gold | cites gold when in evidence | mean seconds |
|---|---|---|---|---|---|---|
| line | 61 | 1.0 | 0.897 | 0.967 | 0.983 | 14.59 |
| line, direct | 41 | 1.0 | 0.882 | 0.976 | 0.976 | 14.11 |
| line, buried | 20 | 1.0 | 0.93 | 0.95 | 1.0 | 15.57 |
| question | 34 | 1.0 | 0.991 | 0.882 | 1.0 | 10.55 |

## Why sentences were dropped

| Reason | count |
|---|---|
| not supported by the cited commits | 23 |
| quote not found in the cited commits | 1 |
