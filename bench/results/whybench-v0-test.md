# WhyBench v0 results (test split)

Generated 2026-11-23T04:54:16+00:00 by Sprout 0.1.0 (commit d65de1ed05e5). Models: {'embed': 'BAAI/bge-small-en-v1.5', 'rerank': 'Xenova/ms-marco-MiniLM-L-6-v2'}. No LLM was used (retrieval and ranking only).

Repositories and snapshots: requests `3c7baaa05a`, flask `49943b5a94`, attrs `f830e60f9c`, express `43fca52d28`, axios `9f0f4ddfe7`, gin `0f09c3a9b4`, ripgrep `0856f3971e`, pytest `7189292654`.

## Line questions: which commit explains `path:line`?

### All line tasks (n = 205)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.459 | 0.459 | 0.459 | 0.459 |
| git log -L order | 0.468 | 0.805 | 0.613 | 0.694 |
| git log -S (pickaxe) | 0.361 | 0.376 | 0.370 | 0.376 |
| bm25 | 0.234 | 0.468 | 0.338 | 0.397 |
| hybrid | 0.166 | 0.371 | 0.246 | 0.294 |
| hybrid + rerank | 0.210 | 0.366 | 0.277 | 0.319 |
| sprout why | **0.717** | **0.981** | **0.825** | **0.865** |
| sprout why, no rationale ranking | 0.459 | 0.863 | 0.620 | 0.708 |

### Direct: blame already points at the gold commit (n = 96)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.906 | 0.906 | 0.906 | 0.906 |
| git log -L order | **1.000** | **1.000** | **1.000** | **1.000** |
| git log -S (pickaxe) | 0.750 | 0.771 | 0.765 | 0.776 |
| bm25 | 0.375 | 0.708 | 0.526 | 0.602 |
| hybrid | 0.240 | 0.510 | 0.349 | 0.408 |
| hybrid + rerank | 0.323 | 0.500 | 0.398 | 0.442 |
| sprout why | 0.896 | **1.000** | 0.948 | 0.962 |
| sprout why, no rationale ranking | 0.906 | **1.000** | 0.950 | 0.963 |

### Buried: the gold commit is further back in the line's history (n = 109)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.064 | 0.064 | 0.064 | 0.064 |
| git log -L order | 0.000 | 0.633 | 0.272 | 0.424 |
| git log -S (pickaxe) | 0.018 | 0.028 | 0.023 | 0.024 |
| bm25 | 0.110 | 0.257 | 0.172 | 0.215 |
| hybrid | 0.101 | 0.248 | 0.155 | 0.194 |
| hybrid + rerank | 0.110 | 0.248 | 0.170 | 0.211 |
| sprout why | **0.560** | **0.963** | **0.717** | **0.781** |
| sprout why, no rationale ranking | 0.064 | 0.743 | 0.329 | 0.483 |

## Natural-language questions

### All questions (n = 87)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| bm25 | 0.644 | 0.828 | 0.718 | 0.753 |
| vector | 0.552 | 0.839 | 0.662 | 0.709 |
| hybrid | 0.678 | 0.897 | 0.774 | 0.818 |
| hybrid + rerank | **0.839** | **0.977** | **0.899** | **0.919** |
| sprout why | **0.839** | **0.977** | **0.899** | **0.919** |
