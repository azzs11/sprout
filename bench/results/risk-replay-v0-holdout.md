# Revert replay v0: holdout split

Method `risk@2` (line fingerprints `1`), Sprout 0.1.0 at `2f1c58682abdfa6c7ca5ebca2cbc830d75206f22`, 2026-11-25T13:11:49+00:00, Darwin arm64, Python 3.11.18. Snapshots pinned in `bench/data/whybench-v0/repos.lock.json`.

Each non-merge commit is checked against the history *before* it. **Sprout** flags a commit when `sprout risk` would show any finding (the default). The **baseline** flags a commit that touches a file a fix, security or revert commit touched in the previous 30 days. **Random** flags as many commits as Sprout, at random. Intervals are 95% bootstrap intervals over commits. Gold labels are incomplete: a mistake fixed without a revert or a `fix` label counts as clean.

## Positive = later reverted (the headline label)

7,974 commits, 24 positive.

| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |
|---|---|---|---|---|---|
| Sprout (default) | 697 | 0.087 | 0.001 [0.000, 0.005] | 0.042 [0.000, 0.151] | 20.4 |
| Recent-fix file baseline | 2791 | 0.350 | 0.002 [0.001, 0.004] | 0.250 [0.087, 0.440] | 1.2 |
| Random, same alert rate | n/a | 0.087 | 0.003 | 0.087 | n/a |

Alert budgets: at most this share of all commits is flagged, highest score first. Commits with no signal are never flagged, so fewer alerts may be used.

| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts | Baseline precision | Baseline recall |
|---|---|---|---|---|---|---|
| 5% | 399 | 0.000 | 0.000 | 399 | 0.003 | 0.042 |
| 10% | 697 | 0.001 | 0.042 | 798 | 0.004 | 0.125 |
| 50% | 697 | 0.001 | 0.042 | 2791 | 0.002 | 0.250 |

## Positive = later reverted, or fix-inducing: a fix within a year removed a line it added

7,974 commits, 1117 positive.

| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |
|---|---|---|---|---|---|
| Sprout (default) | 697 | 0.087 | 0.301 [0.270, 0.335] | 0.188 [0.166, 0.215] | 20.4 |
| Recent-fix file baseline | 2791 | 0.350 | 0.234 [0.219, 0.248] | 0.584 [0.558, 0.612] | 1.2 |
| Random, same alert rate | n/a | 0.087 | 0.140 | 0.087 | n/a |

Alert budgets: at most this share of all commits is flagged, highest score first. Commits with no signal are never flagged, so fewer alerts may be used.

| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts | Baseline precision | Baseline recall |
|---|---|---|---|---|---|---|
| 5% | 399 | 0.313 | 0.112 | 399 | 0.386 | 0.138 |
| 10% | 697 | 0.301 | 0.188 | 798 | 0.318 | 0.227 |
| 50% | 697 | 0.301 | 0.188 | 2791 | 0.234 | 0.584 |

## Per repository

| Repo | Commits | Reverted | Fix-inducing or reverted | Sprout alerts | Sprout hits (reverted / induced) | Baseline alerts | Baseline hits (reverted / induced) |
|---|---|---|---|---|---|---|---|
| werkzeug | 4554 | 10 | 837 | 496 | 0 / 159 | 2145 | 4 / 538 |
| koa | 1164 | 5 | 120 | 87 | 1 / 26 | 333 | 1 / 55 |
| chi | 774 | 3 | 73 | 42 | 0 / 8 | 118 | 0 / 14 |
| regex | 1482 | 6 | 87 | 72 | 0 / 17 | 195 | 1 / 45 |

## Every hit

- koa `94413b1bd`, reverted by `b1f0abd16`: review (reintroduces_fixed); cites `0be144211`

## Misses (23 reverted commits with no warning)

- werkzeug `b05387384`, reverted by `e1c3e3e95`: low (no finding); cites nothing
- werkzeug `502b780de`, reverted by `87eb4a2b3`: low (no finding); cites nothing
- werkzeug `c92679347`, reverted by `d867a3ad7`: low (no finding); cites nothing
- werkzeug `0cd2da5d5`, reverted by `56d1127ce`: low (no finding); cites nothing
- werkzeug `10a211e74`, reverted by `bec82a8b6`: low (no finding); cites nothing
- werkzeug `1581b8d77`, reverted by `1eb4912ee`: low (no finding); cites nothing
- werkzeug `032c2c78b`, reverted by `1fa017c06`: low (no finding); cites nothing
- werkzeug `eb7b4255d`, reverted by `6df9e5bdb`: low (no finding); cites nothing
- werkzeug `5dcb2b652`, reverted by `38ec0b242`: low (no finding); cites nothing
- werkzeug `2c2cc69bd`, reverted by `f999d8f65`: low (no finding); cites nothing
- koa `70c1905f5`, reverted by `a6efc790a`: low (no finding); cites nothing
- koa `c161c0f2e`, reverted by `86ab4ae84`: low (no finding); cites nothing
- koa `d2b09439b`, reverted by `a0148c1f0`: low (no finding); cites nothing
- koa `14aef5f11`, reverted by `7e16b3154`: low (no finding); cites nothing
- chi `e135f36c8`, reverted by `ea7f7b5bb`: low (no finding); cites nothing

## High-level false alarms (first 15 of 43)

- werkzeug `f9755f9bd`: high (removes_fix); cites `514275a91`, `745aa7d70`, `189e6562a`
- werkzeug `48d8a7737`: high (reapplies_reverted); cites `bec82a8b6`
- werkzeug `7c7386081`: high (reapplies_reverted); cites `1eb4912ee`
- werkzeug `16fdd66c0`: high (removes_fix); cites `3c5e31fbd`
- werkzeug `94ea3ecd0`: high (removes_fix); cites `dccbdda90`
- werkzeug `b9d90090d`: high (reintroduces_fixed); cites `cdf680222`
- werkzeug `f6ce5a4b3`: high (reintroduces_fixed); cites `94ea3ecd0`
- werkzeug `3245e585e`: high (reintroduces_fixed); cites `1034edc7f`
- werkzeug `5a8d14426`: high (reintroduces_fixed, removes_fix); cites `94ea3ecd0`, `6439d90af`
- werkzeug `ab6150fa4`: high (reapplies_reverted, removes_fix, removes_restored); cites `2cf689725`, `2b2d921ee`, `f999d8f65`
- werkzeug `81e10efbf`: high (removes_fix, removes_restored); cites `6953c0f17`, `f999d8f65`, `ba3e59846`
- werkzeug `43f75e3d9`: high (removes_fix); cites `012d44b9b`, `b40a78fc8`, `957847aaf`
- werkzeug `dd3a2b23d`: high (removes_fix); cites `750da24a1`
- werkzeug `f38aaa4b8`: high (removes_fix); cites `168f57685`
- werkzeug `01eb6ae4b`: high (removes_fix); cites `26572f775`
