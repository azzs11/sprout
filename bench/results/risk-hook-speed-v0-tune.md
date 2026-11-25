# Hook latency v0: tune split

`sprout-hook agent`, a fresh process per event, Sprout 0.1.0 at `116f75675bada0bac2aadd93b411169f17f96fe8`, 2026-11-25T13:27:47+00:00, Darwin arm64, Python 3.11.18. Each repository: up to 30 recently modified files rewritten to their version 40 commits earlier (Write events), and 10 non-edit events. Milliseconds.

| Repo | Edits | Edit p50 | Edit p95 | Edit max | No-op p50 | Asked | Noted | Silent |
|---|---|---|---|---|---|---|---|---|
| click | 30 | 78.7 | 112.2 | 123.5 | 23.6 | 0 | 10 | 20 |
| httpx | 30 | 78.0 | 89.2 | 333.6 | 24.1 | 0 | 4 | 26 |
| cobra | 30 | 77.9 | 99.2 | 120.1 | 23.8 | 0 | 11 | 19 |

Worst per-repository edit p95: 112.2 ms.
