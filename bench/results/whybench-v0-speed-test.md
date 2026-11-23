# WhyBench v0 speed (test split)

Generated 2026-11-23T05:04:35+00:00 by Sprout 0.1.0 (commit b404b3043de3) on Darwin arm64, Python 3.11.18. One warm-up task per repository is not counted. Lines use no models; questions use the embedder and reranker {'embed': 'BAAI/bge-small-en-v1.5', 'rerank': 'Xenova/ms-marco-MiniLM-L-6-v2'}.

| Repository | kind | n | p50 ms | p95 ms | max ms |
|---|---|---|---|---|---|
| requests | line | 26 | 101.1 | 177.2 | 180.1 |
| requests | question | 12 | 355.3 | 714.2 | 714.2 |
| flask | line | 18 | 197.2 | 386.6 | 386.6 |
| flask | question | 11 | 317.3 | 596.4 | 596.4 |
| attrs | line | 19 | 90.2 | 227.4 | 227.4 |
| attrs | question | 11 | 749.1 | 763.2 | 763.2 |
| express | line | 4 | 197.3 | 239.7 | 239.7 |
| express | question | 7 | 325.2 | 349.6 | 349.6 |
| axios | line | 40 | 115.2 | 384.7 | 443.2 |
| axios | question | 12 | 594.7 | 761.1 | 761.1 |
| gin | line | 18 | 78.0 | 157.8 | 157.8 |
| gin | question | 12 | 440.2 | 723.5 | 723.5 |
| ripgrep | line | 40 | 196.6 | 251.6 | 386.6 |
| ripgrep | question | 11 | 594.9 | 646.2 | 646.2 |
| pytest | line | 40 | 337.6 | 539.4 | 699.7 |
| pytest | question | 11 | 603.0 | 762.7 | 762.7 |
| **all** | line | 205 | 179.1 | 434.8 | 699.7 |
| **all** | question | 87 | 530.0 | 756.1 | 763.2 |
