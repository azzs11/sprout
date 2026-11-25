# Revert replay v0: tune split

Method `risk@2` (line fingerprints `1`), Sprout 0.1.0 at `116f75675bada0bac2aadd93b411169f17f96fe8`, 2026-11-25T13:27:38+00:00, Darwin arm64, Python 3.11.18. Snapshots pinned in `bench/data/whybench-v0/repos.lock.json`.

Each non-merge commit is checked against the history *before* it. **Sprout** flags a commit when `sprout risk` would show any finding (the default). The **baseline** flags a commit that touches a file a fix, security or revert commit touched in the previous 30 days. **Random** flags as many commits as Sprout, at random. Intervals are 95% bootstrap intervals over commits. Gold labels are incomplete: a mistake fixed without a revert or a `fix` label counts as clean.

## Positive = later reverted (the headline label)

4,668 commits, 14 positive.

| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |
|---|---|---|---|---|---|
| Sprout (default) | 259 | 0.055 | 0.008 [0.000, 0.021] | 0.143 [0.000, 0.364] | 31.8 |
| Sprout, high only (agent hook asks) | 9 | 0.002 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | n/a |
| Recent-fix file baseline | 1475 | 0.316 | 0.004 [0.001, 0.007] | 0.429 [0.154, 0.700] | 0.1 |
| Random, same alert rate | n/a | 0.055 | 0.003 | 0.055 | n/a |

Alert budgets: at most this share of all commits is flagged, highest score first. Commits with no signal are never flagged, so fewer alerts may be used.

| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts | Baseline precision | Baseline recall |
|---|---|---|---|---|---|---|
| 5% | 234 | 0.009 | 0.143 | 234 | 0.009 | 0.143 |
| 10% | 259 | 0.008 | 0.143 | 467 | 0.009 | 0.286 |
| 50% | 259 | 0.008 | 0.143 | 1475 | 0.004 | 0.429 |

## Positive = later reverted, or fix-inducing: a fix within a year removed a line it added

4,668 commits, 578 positive.

| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |
|---|---|---|---|---|---|
| Sprout (default) | 259 | 0.055 | 0.236 [0.183, 0.287] | 0.106 [0.080, 0.132] | 31.8 |
| Sprout, high only (agent hook asks) | 9 | 0.002 | 0.111 [0.000, 0.375] | 0.002 [0.000, 0.005] | n/a |
| Recent-fix file baseline | 1475 | 0.316 | 0.197 [0.178, 0.218] | 0.503 [0.463, 0.543] | 0.1 |
| Random, same alert rate | n/a | 0.055 | 0.124 | 0.055 | n/a |

Alert budgets: at most this share of all commits is flagged, highest score first. Commits with no signal are never flagged, so fewer alerts may be used.

| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts | Baseline precision | Baseline recall |
|---|---|---|---|---|---|---|
| 5% | 234 | 0.231 | 0.093 | 234 | 0.355 | 0.144 |
| 10% | 259 | 0.236 | 0.106 | 467 | 0.287 | 0.232 |
| 50% | 259 | 0.236 | 0.106 | 1475 | 0.197 | 0.503 |

## Per repository

| Repo | Commits | Reverted | Fix-inducing or reverted | Sprout alerts | Sprout hits (reverted / induced) | Baseline alerts | Baseline hits (reverted / induced) |
|---|---|---|---|---|---|---|---|
| click | 2190 | 7 | 339 | 137 | 2 / 38 | 938 | 5 / 216 |
| httpx | 1486 | 3 | 120 | 73 | 0 / 11 | 337 | 1 / 43 |
| cobra | 992 | 4 | 119 | 49 | 0 / 12 | 200 | 0 / 32 |

## Every hit

- click `e798f64ff`, reverted by `0d1b8eab4`: review (removes_fix); cites `0135331c7`
- click `8bc912710`, reverted by `e25243731`: review (removes_fix); cites `a1235aacb`, `e37cad2a8`, `3155dcac0`

## Misses (12 reverted commits with no warning)

- click `4470adc1d`, reverted by `5eca206e7`: low (no finding); cites nothing
- click `c291543d9`, reverted by `48b4cf5fd`: low (no finding); cites nothing
- click `6c4a77ba2`, reverted by `bb7be1f6a`: low (no finding); cites nothing
- click `fbdd43402`, reverted by `8ee83ddbf`: low (no finding); cites nothing
- click `e2bddbc80`, reverted by `d03688179`: low (no finding); cites nothing
- httpx `71cbde8ba`, reverted by `86a0eb026`: low (no finding); cites nothing
- httpx `939f3ce7c`, reverted by `631ba9763`: low (no finding); cites nothing
- httpx `4cbf13ece`, reverted by `bddd774ce`: low (no finding); cites nothing
- cobra `1e1d5137b`, reverted by `f06ae19d9`: low (no finding); cites nothing
- cobra `b655df6ce`, reverted by `3d7bff8a3`: low (no finding); cites nothing
- cobra `23a6174c7`, reverted by `ff416ad43`: low (no finding); cites nothing
- cobra `d1e9d85fc`, reverted by `40b5bc143`: low (no finding); cites nothing

## High-level false alarms (first 15 of 9)

- click `f0cc87d49`: high (reapplies_reverted); cites `48b4cf5fd`
- click `21f714dcb`: high (removes_fix); cites `543358a66`
- click `cc2345ae6`: high (removes_fix); cites `543358a66`
- click `d2145fdfe`: high (removes_fix, removes_restored); cites `564753db4`, `5eca206e7`
- click `e25243731`: high (reapplies_reverted); cites `8bc912710`
- click `c653ec820`: high (reapplies_reverted); cites `bb7be1f6a`
- click `c2ed41490`: high (reapplies_reverted); cites `8ee83ddbf`
- click `b90faad17`: high (reapplies_reverted); cites `d03688179`
- httpx `a33c87852`: high (reapplies_reverted); cites `adbcd0e0e`
