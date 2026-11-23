# WhyBench v0 written answers (holdout split)

Generated 2026-11-23T12:14:41+00:00 by Sprout 0.1.0 (commit b404b3043de3, plus uncommitted changes) with `ollama:qwen2.5-coder:7b|why_answer@3+why_line_answer@1+reasons@1` on Darwin arm64, Python 3.11.18.

Checker-based, not judged: a kept sentence cites a commit from the evidence and its quotes and most content words appear there. *answer rate*: at least one model sentence survived. *cites gold*: a kept sentence cites the gold commit.

| Tasks | n | answer rate | sentence survival | cites gold | cites gold when in evidence | mean seconds |
|---|---|---|---|---|---|---|
| line | 139 | 0.993 | 0.92 | 0.856 | 0.902 | 15.15 |
| line, direct | 89 | 1.0 | 0.966 | 0.955 | 0.955 | 14.22 |
| line, buried | 50 | 0.98 | 0.836 | 0.68 | 0.791 | 16.8 |
| question | 44 | 1.0 | 0.973 | 0.864 | 0.927 | 13.11 |

## Why sentences were dropped

| Reason | count |
|---|---|
| not supported by the cited commits | 32 |
| quote not found in the cited commits | 11 |
| unreadable reply | 1 |
| copied evidence, not prose | 1 |

## Closed-book baseline: the same model, no git history

It must name the commit from memory. Any reason it gives is unsupported.

| Tasks | n | cites gold | names a commit | asserts a reason |
|---|---|---|---|---|
| line | 139 | 0.0 | 0.0 | 0.468 |
| question | 44 | 0.0 | 0.045 | 0.955 |
