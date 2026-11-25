# Pull request history check (GitHub Action)

The Sprout action checks each pull request against the base branch's git history, using the same check as `sprout risk`. When the change undoes a past fix or re-applies a reverted change, the action posts one comment that cites the commits. It updates that comment on later pushes and deletes it once the pull request is clean. When there is nothing to cite, it stays silent. No model and no external service is used: the check runs on the workflow's runner.

```yaml
# .github/workflows/sprout.yml
name: History check
on: pull_request

permissions:
  contents: read
  pull-requests: write   # to post the comment

jobs:
  sprout:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0     # Sprout needs the full history
      - uses: azzs11/sprout@v0.7
```

`v0.7` is the first release with the action. Pin a tag or a commit SHA rather than `main`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `fail-on` | `security` | Fail the check when a past security fix is undone (`security`), on any finding (`any`), or `never`. |
| `comment` | `true` | Post, update or remove the pull request comment. The job summary is always written. |
| `python-version` | `3.12` | Python used to run Sprout. |

## How it works

1. It installs Sprout with uv, then restores `.sprout/` from the Actions cache, keyed on the base commit.
2. It runs `sprout index --rev <base>`. Only the base branch's history counts as evidence; the pull request's own commits are never treated as history.
3. It checks `git diff <base>...<head>` with `sprout risk --markdown`.
4. It writes the result to the job summary and keeps one comment on the pull request.

Commit messages are treated as untrusted text. `@mentions` are defused so the comment never pings anyone, HTML is escaped, and inputs reach the scripts as environment variables.

**Forks.** Pull requests from forks get a read-only token, so the comment cannot be posted. The job summary still has the result, and the action only warns.

**Acknowledged commits.** Commits listed in `.sprout-acks.toml` (see `sprout ack`) are not reported.
