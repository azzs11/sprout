# Revert replay v0: test split

Method `risk@2` (line fingerprints `1`), Sprout 0.1.0 at `116f75675bada0bac2aadd93b411169f17f96fe8`, 2026-11-25T13:29:07+00:00, Darwin arm64, Python 3.11.18. Snapshots pinned in `bench/data/whybench-v0/repos.lock.json`.

Each non-merge commit is checked against the history *before* it. **Sprout** flags a commit when `sprout risk` would show any finding (the default). The **baseline** flags a commit that touches a file a fix, security or revert commit touched in the previous 30 days. **Random** flags as many commits as Sprout, at random. Intervals are 95% bootstrap intervals over commits. Gold labels are incomplete: a mistake fixed without a revert or a `fix` label counts as clean.

## Positive = later reverted (the headline label)

35,758 commits, 155 positive.

| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |
|---|---|---|---|---|---|
| Sprout (default) | 2992 | 0.084 | 0.007 [0.004, 0.011] | 0.142 [0.086, 0.202] | 2.2 |
| Sprout, high only (agent hook asks) | 127 | 0.004 | 0.024 [0.000, 0.052] | 0.019 [0.000, 0.042] | 1.4 |
| Recent-fix file baseline | 13492 | 0.377 | 0.004 [0.003, 0.006] | 0.387 [0.306, 0.462] | 0.7 |
| Random, same alert rate | n/a | 0.084 | 0.004 | 0.084 | n/a |

Alert budgets: at most this share of all commits is flagged, highest score first. Commits with no signal are never flagged, so fewer alerts may be used.

| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts | Baseline precision | Baseline recall |
|---|---|---|---|---|---|---|
| 5% | 1788 | 0.009 | 0.103 | 1788 | 0.002 | 0.026 |
| 10% | 2992 | 0.007 | 0.142 | 3576 | 0.005 | 0.116 |
| 50% | 2992 | 0.007 | 0.142 | 13492 | 0.004 | 0.387 |

## Positive = later reverted, or fix-inducing: a fix within a year removed a line it added

35,758 commits, 5255 positive.

| Flags | Alerts | Alert rate | Precision | Recall | Median lead (days) |
|---|---|---|---|---|---|
| Sprout (default) | 2992 | 0.084 | 0.318 [0.301, 0.334] | 0.181 [0.171, 0.192] | 2.2 |
| Sprout, high only (agent hook asks) | 127 | 0.004 | 0.307 [0.229, 0.380] | 0.007 [0.005, 0.010] | 1.4 |
| Recent-fix file baseline | 13492 | 0.377 | 0.212 [0.205, 0.219] | 0.545 [0.531, 0.557] | 0.7 |
| Random, same alert rate | n/a | 0.084 | 0.147 | 0.084 | n/a |

Alert budgets: at most this share of all commits is flagged, highest score first. Commits with no signal are never flagged, so fewer alerts may be used.

| Budget | Sprout alerts | Sprout precision | Sprout recall | Baseline alerts | Baseline precision | Baseline recall |
|---|---|---|---|---|---|---|
| 5% | 1788 | 0.351 | 0.120 | 1788 | 0.330 | 0.112 |
| 10% | 2992 | 0.318 | 0.181 | 3576 | 0.302 | 0.206 |
| 50% | 2992 | 0.318 | 0.181 | 13492 | 0.212 | 0.545 |

## Per repository

| Repo | Commits | Reverted | Fix-inducing or reverted | Sprout alerts | Sprout hits (reverted / induced) | Baseline alerts | Baseline hits (reverted / induced) |
|---|---|---|---|---|---|---|---|
| requests | 4884 | 41 | 654 | 367 | 4 / 92 | 1923 | 19 / 367 |
| flask | 3832 | 10 | 531 | 277 | 0 / 63 | 1227 | 2 / 239 |
| attrs | 1838 | 5 | 248 | 156 | 0 / 42 | 420 | 0 / 88 |
| express | 5701 | 20 | 715 | 315 | 2 / 81 | 2401 | 11 / 364 |
| axios | 2082 | 15 | 372 | 218 | 5 / 98 | 711 | 6 / 216 |
| gin | 1807 | 8 | 281 | 212 | 3 / 71 | 627 | 2 / 125 |
| ripgrep | 2314 | 7 | 114 | 75 | 0 / 21 | 400 | 1 / 63 |
| pytest | 13300 | 49 | 2340 | 1372 | 8 / 482 | 5783 | 19 / 1400 |

## Every hit

- requests `91766548d`, reverted by `2c0ff95d4`: review (removes_fix); cites `12f3c65e5`
- requests `f4818b201`, reverted by `a559d62f1`: review (removes_fix); cites `ac0a7ed15`
- requests `9e27326d6`, reverted by `fd13816d0`: review (reintroduces_fixed); cites `567b31080`
- requests `2da7fe085`, reverted by `24bcb9eab`: review (removes_fix); cites `9606f0240`
- express `2bba69f63`, reverted by `c3bd65eda`: review (removes_fix); cites `9c87eed60`
- express `31b2e2d7b`, reverted by `7f049164b`: review (reapplies_reverted); cites `140efb574`
- axios `152b06351`, reverted by `aaed16ca3`: review (removes_fix); cites `839b9ab3e`
- axios `189b34c45`, reverted by `097948698`: review (removes_restored); cites `aaed16ca3`
- axios `c71811b00`, reverted by `c44d2f231`: review (removes_fix); cites `580f1e803`, `a1c8ad008`, `00de614cd`
- axios `e2bed7f84`, reverted by `a40f8d339`: high (reintroduces_fixed); cites `8ff6c19e2`
- axios `694f1eca8`, reverted by `d9b941c30`: review (removes_restored); cites `c44d2f231`
- gin `19f271c86`, reverted by `fabe3df78`: review (removes_fix); cites `b26d956e0`
- gin `041ca04a4`, reverted by `fabe3df78`: review (removes_restored); cites `63b5d1c4c`
- gin `f67d7a90c`, reverted by `29a145c85`: high (reapplies_reverted); cites `3b8150c83`
- pytest `e770db4c9`, reverted by `606d72869`: high (reapplies_reverted); cites `a6dc28313`
- pytest `9fce0bdd8`, reverted by `23a0b532d`: review (removes_fix); cites `6e687c435`, `1c891d7d9`, `94aa76fec`
- pytest `99180939f`, reverted by `cc7f294cf`: review (reintroduces_fixed); cites `31cfbac1f`
- pytest `fb99b5c66`, reverted by `ef112fd7d`: review (removes_fix); cites `930a158a6`
- pytest `2df0d9656`, reverted by `a501518a2`: review (removes_fix); cites `675f8da3a`
- pytest `431ec6d34`, reverted by `90412827c`: review (reintroduces_fixed); cites `60e969853`
- pytest `a98f02d42`, reverted by `dacee1f11`: review (removes_fix); cites `aa10bff75`
- pytest `6c89f9261`, reverted by `303cd0d48`: review (reintroduces_fixed); cites `c69b84f23`, `2a825169b`

## Misses (133 reverted commits with no warning)

- requests `12f3c65e5`, reverted by `91766548d`: low (no finding); cites nothing
- requests `730c0e2e2`, reverted by `b98cc8b4e`: low (no finding); cites nothing
- requests `e2645826b`, reverted by `0e65dff00`: low (no finding); cites nothing
- requests `3550ac747`, reverted by `3843a40f7`: low (no finding); cites nothing
- requests `e28c1c9bf`, reverted by `2621fe2bf`: low (no finding); cites nothing
- requests `9217a2523`, reverted by `be0414272`: low (no finding); cites nothing
- requests `35d5ac6e8`, reverted by `8a81a437d`: low (no finding); cites nothing
- requests `d23294818`, reverted by `6271046a2`: low (no finding); cites nothing
- requests `a453a78c7`, reverted by `53d60cac4`: low (no finding); cites nothing
- requests `62a23bfbd`, reverted by `488a51d61`: low (no finding); cites nothing
- requests `f968fe013`, reverted by `dda9689ca`: low (no finding); cites nothing
- requests `c71f48b5f`, reverted by `a5d462e17`: low (no finding); cites nothing
- requests `c19650b00`, reverted by `5ce25688e`: low (no finding); cites nothing
- requests `544d08d0f`, reverted by `be62645dd`: low (no finding); cites nothing
- requests `178ff62b9`, reverted by `c01bc5be5`: low (no finding); cites nothing

## High-level false alarms (first 15 of 124)

- requests `2c0ff95d4`: high (reapplies_reverted); cites `91766548d`
- requests `a7223f86a`: high (reapplies_reverted); cites `2c0ff95d4`
- requests `67f50a0fe`: high (reapplies_reverted); cites `b98cc8b4e`
- requests `92d57036f`: high (reapplies_reverted, reintroduces_fixed); cites `b98cc8b4e`, `62d29d510`, `5287b8cd9`
- requests `a9ec28a1b`: high (reapplies_reverted); cites `be62645dd`
- requests `e64485787`: high (removes_fix); cites `02f852cc4`
- requests `23051979f`: high (reapplies_reverted); cites `b58318163`
- requests `6597b5383`: high (removes_fix); cites `958845ae3`
- requests `d758f0cf9`: high (reapplies_reverted); cites `5f4d0d08d`
- requests `2297d3340`: high (reapplies_reverted); cites `a559d62f1`
- requests `bfb93d4b7`: high (reintroduces_fixed); cites `0a760ff02`
- requests `083006210`: high (removes_fix); cites `f3eeb3854`
- requests `43ed689d9`: high (reintroduces_fixed); cites `02f852cc4`
- requests `320a10d14`: high (removes_fix); cites `0a760ff02`, `bfb93d4b7`, `9055b33f6`
- requests `8bce583b9`: high (reintroduces_fixed, removes_fix, removes_restored); cites `e8a4784c8`, `24bcb9eab`, `b227e3cb8`
