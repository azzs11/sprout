# WhyBench v0 written answers (test split)

Generated 2026-11-23T10:50:57+00:00 by Sprout 0.1.0 (commit b404b3043de3, plus uncommitted changes) with `ollama:qwen2.5-coder:7b|why_answer@3+why_line_answer@1+reasons@1` on Darwin arm64, Python 3.11.18.

Checker-based, not judged: a kept sentence cites a commit from the evidence and its quotes and most content words appear there. *answer rate*: at least one model sentence survived. *cites gold*: a kept sentence cites the gold commit.

| Tasks | n | answer rate | sentence survival | cites gold | cites gold when in evidence | mean seconds |
|---|---|---|---|---|---|---|
| line | 205 | 0.995 | 0.957 | 0.805 | 0.817 | 15.62 |
| line, direct | 96 | 1.0 | 0.976 | 0.979 | 0.979 | 15.42 |
| line, buried | 109 | 0.991 | 0.941 | 0.651 | 0.67 | 15.79 |
| question | 87 | 1.0 | 0.986 | 0.977 | 1.0 | 11.85 |

## Why sentences were dropped

| Reason | count |
|---|---|
| not supported by the cited commits | 31 |
| quote not found in the cited commits | 3 |
| unreadable reply | 1 |

## Closed-book baseline: the same model, no git history

It must name the commit from memory. Any reason it gives is unsupported.

| Tasks | n | cites gold | names a commit | asserts a reason |
|---|---|---|---|---|
| line | 205 | 0.0 | 0.0 | 0.405 |
| question | 87 | 0.0 | 0.241 | 0.966 |
