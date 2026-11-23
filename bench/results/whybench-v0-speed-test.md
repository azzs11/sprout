# WhyBench v0 speed (test split)

Generated 2026-11-23T05:02:16+00:00 by Sprout 0.1.0 (commit 68e7f7da83f9) on Darwin arm64, Python 3.11.18. One warm-up task per repository is not counted. Lines use no models; questions use the embedder and reranker {'embed': 'BAAI/bge-small-en-v1.5', 'rerank': 'Xenova/ms-marco-MiniLM-L-6-v2'}.

| Repository | kind | n | p50 ms | p95 ms | max ms |
|---|---|---|---|---|---|
| requests | line | 26 | 99.4 | 178.5 | 182.5 |
| requests | question | 12 | 329.9 | 660.7 | 660.7 |
| flask | line | 18 | 197.3 | 388.5 | 388.5 |
| flask | question | 11 | 316.4 | 586.7 | 586.7 |
| attrs | line | 19 | 88.9 | 229.5 | 229.5 |
| attrs | question | 11 | 727.6 | 750.0 | 750.0 |
| express | line | 4 | 217.8 | 270.6 | 270.6 |
| express | question | 7 | 335.6 | 389.9 | 389.9 |
| axios | line | 40 | 158.1 | 468.2 | 646.1 |
| axios | question | 12 | 788.1 | 1151.4 | 1151.4 |
| gin | line | 18 | 95.6 | 185.6 | 185.6 |
| gin | question | 12 | 696.8 | 1140.9 | 1140.9 |
| ripgrep | line | 40 | 273.5 | 341.2 | 402.3 |
| ripgrep | question | 11 | 702.4 | 1076.5 | 1076.5 |
| pytest | line | 40 | 505.7 | 923.7 | 1130.7 |
| pytest | question | 11 | 886.7 | 1184.4 | 1184.4 |
| **all** | line | 205 | 198.3 | 615.2 | 1130.7 |
| **all** | question | 87 | 663.0 | 1076.5 | 1184.4 |
