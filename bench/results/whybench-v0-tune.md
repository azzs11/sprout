# WhyBench v0 results (tune split)

Generated 2026-11-23T04:55:39+00:00 by Sprout 0.1.0 (commit 228b7dd385ef). Models: {'embed': 'BAAI/bge-small-en-v1.5', 'rerank': 'Xenova/ms-marco-MiniLM-L-6-v2'}. No LLM was used (retrieval and ranking only).

Repositories and snapshots: click `08b803cf32`, httpx `7cff5f79bc`, cobra `adbc881390`.

## Line questions: which commit explains `path:line`?

### All line tasks (n = 61)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.607 | 0.607 | 0.607 | 0.607 |
| git log -L order | 0.672 | 0.918 | 0.772 | 0.813 |
| git log -S (pickaxe) | 0.492 | 0.557 | 0.515 | 0.526 |
| bm25 | 0.164 | 0.525 | 0.329 | 0.429 |
| hybrid | 0.098 | 0.311 | 0.184 | 0.245 |
| hybrid + rerank | 0.180 | 0.459 | 0.304 | 0.382 |
| sprout why | **0.885** | **0.984** | **0.932** | **0.945** |
| sprout why, no rationale ranking | 0.607 | 0.967 | 0.749 | 0.807 |

### Direct: blame already points at the gold commit (n = 41)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.878 | 0.878 | 0.878 | 0.878 |
| git log -L order | **1.000** | **1.000** | **1.000** | **1.000** |
| git log -S (pickaxe) | 0.732 | 0.829 | 0.766 | 0.782 |
| bm25 | 0.244 | 0.610 | 0.405 | 0.510 |
| hybrid | 0.122 | 0.439 | 0.246 | 0.332 |
| hybrid + rerank | 0.244 | 0.537 | 0.370 | 0.454 |
| sprout why | 0.927 | **1.000** | 0.959 | 0.970 |
| sprout why, no rationale ranking | 0.878 | 0.976 | 0.926 | 0.945 |

### Buried: the gold commit is further back in the line's history (n = 20)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.050 | 0.050 | 0.050 | 0.050 |
| git log -L order | 0.000 | 0.750 | 0.306 | 0.430 |
| git log -S (pickaxe) | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 0.000 | 0.350 | 0.174 | 0.264 |
| hybrid | 0.050 | 0.050 | 0.058 | 0.068 |
| hybrid + rerank | 0.050 | 0.300 | 0.169 | 0.235 |
| sprout why | **0.800** | **0.950** | **0.875** | **0.895** |
| sprout why, no rationale ranking | 0.050 | **0.950** | 0.385 | 0.526 |

## Natural-language questions

### All questions (n = 34)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| bm25 | 0.500 | 0.676 | 0.584 | 0.627 |
| vector | 0.353 | 0.500 | 0.408 | 0.443 |
| hybrid | 0.412 | 0.735 | 0.528 | 0.586 |
| hybrid + rerank | **0.529** | **0.853** | **0.655** | **0.711** |
| sprout why | **0.529** | **0.853** | **0.655** | **0.711** |
