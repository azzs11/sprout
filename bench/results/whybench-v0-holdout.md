# WhyBench v0 results (holdout split)

Generated 2026-11-23T11:11:07+00:00 by Sprout 0.1.0 (commit b404b3043de3, plus uncommitted changes). Models: {'embed': 'BAAI/bge-small-en-v1.5', 'rerank': 'Xenova/ms-marco-MiniLM-L-6-v2'}. No LLM was used (retrieval and ranking only).

Repositories and snapshots: werkzeug `0f43c6ebd4`, koa `a0702b923e`, chi `c64ed7d663`, regex `fde4946d4a`.

## Line questions: which commit explains `path:line`?

### All line tasks (n = 139)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.590 | 0.590 | 0.590 | 0.590 |
| git log -L order | 0.640 | 0.892 | 0.740 | 0.789 |
| git log -S (pickaxe) | 0.554 | 0.561 | 0.559 | 0.561 |
| bm25 | 0.295 | 0.561 | 0.405 | 0.458 |
| hybrid | 0.173 | 0.331 | 0.252 | 0.302 |
| hybrid + rerank | 0.266 | 0.460 | 0.349 | 0.399 |
| sprout why | **0.770** | **0.935** | **0.840** | **0.868** |
| sprout why, no rationale ranking | 0.590 | 0.899 | 0.711 | 0.768 |

### Direct: blame already points at the gold commit (n = 89)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.899 | 0.899 | 0.899 | 0.899 |
| git log -L order | **1.000** | **1.000** | **1.000** | **1.000** |
| git log -S (pickaxe) | 0.843 | 0.854 | 0.848 | 0.850 |
| bm25 | 0.427 | 0.697 | 0.535 | 0.583 |
| hybrid | 0.258 | 0.461 | 0.353 | 0.408 |
| hybrid + rerank | 0.382 | 0.573 | 0.467 | 0.518 |
| sprout why | 0.832 | **1.000** | 0.904 | 0.928 |
| sprout why, no rationale ranking | 0.899 | 0.989 | 0.932 | 0.949 |

### Buried: the gold commit is further back in the line's history (n = 50)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| git blame | 0.040 | 0.040 | 0.040 | 0.040 |
| git log -L order | 0.000 | 0.700 | 0.277 | 0.414 |
| git log -S (pickaxe) | 0.040 | 0.040 | 0.043 | 0.047 |
| bm25 | 0.060 | 0.320 | 0.174 | 0.237 |
| hybrid | 0.020 | 0.100 | 0.070 | 0.113 |
| hybrid + rerank | 0.060 | 0.260 | 0.138 | 0.186 |
| sprout why | **0.660** | **0.820** | **0.727** | **0.760** |
| sprout why, no rationale ranking | 0.040 | 0.740 | 0.317 | 0.446 |

## Natural-language questions

### All questions (n = 44)

| System | recall@1 | recall@5 | mrr@10 | ndcg@10 |
|---|---|---|---|---|
| bm25 | 0.500 | 0.727 | 0.594 | 0.643 |
| vector | 0.545 | 0.750 | 0.634 | 0.678 |
| hybrid | 0.682 | **0.864** | 0.766 | 0.806 |
| hybrid + rerank | **0.705** | **0.864** | **0.779** | **0.816** |
| sprout why | **0.705** | **0.864** | **0.779** | **0.816** |
