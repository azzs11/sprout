# WhyBench v0 written answers (test split, round 1: before the reason check)

Generated 2026-11-23T08:55:42+00:00 by Sprout 0.1.0 (commit b404b3043de3, plus uncommitted changes) with `ollama:qwen2.5-coder:7b|why_answer@3+why_line_answer@1` on Darwin arm64, Python 3.11.18.

Checker-based, not judged: a kept sentence cites a commit from the evidence and its quotes and most content words appear there. *answer rate*: at least one model sentence survived. *cites gold*: a kept sentence cites the gold commit.

| Tasks | n | answer rate | sentence survival | cites gold | cites gold when in evidence | mean seconds |
|---|---|---|---|---|---|---|
| line | 205 | 0.971 | 0.922 | 0.78 | 0.792 | 17.01 |
| line, direct | 96 | 1.0 | 0.964 | 0.979 | 0.979 | 17.21 |
| line, buried | 109 | 0.945 | 0.885 | 0.606 | 0.623 | 16.83 |
| question | 87 | 1.0 | 0.964 | 0.977 | 1.0 | 12.19 |

## Why sentences were dropped

| Reason | count |
|---|---|
| quote not found in the cited commits | 43 |
| not supported by the cited commits | 31 |
| unreadable reply | 1 |

## Closed-book baseline: the same model, no git history

It must name the commit from memory. Any reason it gives is unsupported.

| Tasks | n | cites gold | names a commit | asserts a reason |
|---|---|---|---|---|
| line | 205 | 0.0 | 0.0 | 0.405 |
| question | 87 | 0.0 | 0.241 | 0.966 |
