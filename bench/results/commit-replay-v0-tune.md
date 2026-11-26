# commit-replay-v0, tune split (60 commits, qwen2.5-coder:7b)

Sprout commit b386e6bfb1a18112fc5bc826452049bb0f954097-dirty; prompts commit_message@1, commit_diff_only@1.

| Metric | Sprout | Diff-only | Skeleton | Author |
|---|---|---|---|---|
| Subject formatted like the author's (share of 4 checks) | 0.879 | 0.875 | 0.887 | 0.963 |
| ... type prefix exactly when the author used one | 0.850 | 0.850 | 0.850 | 1.000 |
| ... same capitalisation as the author | 0.750 | 0.783 | 0.750 | 1.000 |
| ... full stop exactly when the author used one | 0.950 | 0.950 | 0.950 | 1.000 |
| ... within the repo's usual length | 0.967 | 0.917 | 1.000 | 0.850 |
| Same Conventional Commit type as the author | 0.000 | 0.111 | 0.000 | 1.000 |
| ROUGE-L F1 with the author's subject (caveat in the card) | 0.253 | 0.241 | 0.133 | 1.000 |
| Has a body | 0.333 | 0.683 | 0.000 | 0.117 |
| Body's first line repeats the subject | 0.017 | 0.000 | 0.000 | 0.033 |
| States a reason (strong causal word) | 0.017 | 0.050 | 0.000 | 0.033 |
| Question asks why, not what changed | 0.983 | - | - | - |
| Model reply usable | 0.983 | 1.000 | 1.000 | 1.000 |

Sprout minus diff-only, mean and 95% bootstrap interval over tasks:

- style: 0.004 [-0.021, 0.033]
- rouge_l: 0.012 [-0.029, 0.058]
- restates: 0.017 [0.000, 0.050]
- gives_reason: -0.033 [-0.100, 0.033]

Median seconds per draft: {'sprout': 9.8, 'diff_only': 3.19}

## Per repository

| Repo | Sprout style | Diff-only style | Sprout ROUGE-L | Diff-only ROUGE-L |
|---|---|---|---|---|
| click | 0.875 | 0.887 | 0.271 | 0.252 |
| cobra | 0.800 | 0.787 | 0.237 | 0.222 |
| httpx | 0.963 | 0.950 | 0.251 | 0.249 |
