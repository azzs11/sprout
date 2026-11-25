# Hook latency v0: holdout split

`sprout-hook agent`, a fresh process per event, Sprout 0.1.0 at `116f75675bada0bac2aadd93b411169f17f96fe8`, 2026-11-25T13:30:03+00:00, Darwin arm64, Python 3.11.18. Each repository: up to 30 recently modified files rewritten to their version 40 commits earlier (Write events), and 10 non-edit events. Milliseconds.

| Repo | Edits | Edit p50 | Edit p95 | Edit max | No-op p50 | Asked | Noted | Silent |
|---|---|---|---|---|---|---|---|---|
| werkzeug | 30 | 81.8 | 92.9 | 106.1 | 24.3 | 1 | 10 | 19 |
| koa | 30 | 80.9 | 87.9 | 153.5 | 24.3 | 4 | 20 | 6 |
| chi | 30 | 80.2 | 84.1 | 88.2 | 24.2 | 4 | 9 | 17 |
| regex | 30 | 82.1 | 99.4 | 104.3 | 24.5 | 1 | 4 | 25 |

Worst per-repository edit p95: 99.4 ms.
