# Hook latency v0: test split

`sprout-hook agent`, a fresh process per event, Sprout 0.1.0 at `116f75675bada0bac2aadd93b411169f17f96fe8`, 2026-11-25T13:29:35+00:00, Darwin arm64, Python 3.11.18. Each repository: up to 30 recently modified files rewritten to their version 40 commits earlier (Write events), and 10 non-edit events. Milliseconds.

| Repo | Edits | Edit p50 | Edit p95 | Edit max | No-op p50 | Asked | Noted | Silent |
|---|---|---|---|---|---|---|---|---|
| requests | 30 | 80.3 | 94.8 | 98.5 | 24.1 | 0 | 5 | 25 |
| flask | 30 | 80.3 | 98.6 | 99.7 | 24.2 | 0 | 10 | 20 |
| attrs | 30 | 79.9 | 105.2 | 123.9 | 24.4 | 0 | 4 | 26 |
| express | 30 | 80.3 | 97.3 | 137.0 | 24.0 | 1 | 3 | 26 |
| axios | 30 | 80.8 | 136.4 | 414.3 | 24.1 | 2 | 8 | 20 |
| gin | 30 | 80.8 | 110.9 | 114.6 | 24.7 | 2 | 9 | 19 |
| ripgrep | 30 | 80.7 | 85.4 | 217.8 | 24.5 | 0 | 6 | 24 |
| pytest | 30 | 82.5 | 108.3 | 2643.7 | 24.4 | 0 | 11 | 19 |

Worst per-repository edit p95: 136.4 ms.
