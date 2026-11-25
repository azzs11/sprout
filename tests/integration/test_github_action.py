"""The GitHub Action: the PR comment body, and check.sh/comment.sh run against a fake ``gh``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sprout.cli.risk_markdown import MARKER, card_markdown
from sprout.core.index.store import Store
from sprout.models import Commit, Label, Person, RiskCard, RiskFinding, RiskKind, RiskLevel, Verdict
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
ACTION = Path(__file__).resolve().parents[2] / "integrations" / "github-action"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the action's scripts run in bash on Linux")

FAKE_GH = """#!/usr/bin/env bash
# Records each call; answers the comment listing with $FAKE_EXISTING (an id or nothing).
echo "$*" >> "$FAKE_LOG"
for arg in "$@"; do case "$arg" in body=@*) cp "${arg#body=@}" "$FAKE_LOG.body" ;; esac; done
if [ "$1" = api ] && [ "$2" = --paginate ]; then printf '%s\\n' "$FAKE_EXISTING"; fi
"""


# ----- comment body -------------------------------------------------------------------


def finding(summary: str, *, security: bool = False) -> RiskFinding:
    person = Person(name="Ada", email="ada@example.com")
    when = datetime(2024, 1, 1, tzinfo=UTC)
    commit = Commit(
        hash="a" * 40, short_hash="aaaaaaa", author=person, authored_at=when, committer=person,
        committed_at=when, summary=summary, message=summary, parents=[],
    )  # fmt: skip
    return RiskFinding(
        commit=commit,
        kind=RiskKind.REMOVES_FIX,
        level=RiskLevel.HIGH if security else RiskLevel.REVIEW,
        labels=[Label.FIX, *([Label.SECURITY] if security else [])],
        matched=2,
        total=2,
        examples=["-if token is None:", "-    raise ```` oops"],
        paths=["a.py"],
        reason="Thanks @octocat for <b>reporting</b> it",
    )


def card(*findings: RiskFinding) -> RiskCard:
    level = max(
        (f.level for f in findings),
        key=[RiskLevel.LOW, RiskLevel.REVIEW, RiskLevel.HIGH].index,
        default=RiskLevel.LOW,
    )
    verdict = {
        RiskLevel.LOW: Verdict.PROCEED,
        RiskLevel.REVIEW: Verdict.REVIEW,
        RiskLevel.HIGH: Verdict.STOP,
    }[level]
    return RiskCard(
        level=level, verdict=verdict, findings=list(findings), checked_lines=4, method="risk@2"
    )


def test_no_findings_means_no_comment() -> None:
    assert card_markdown(card()) == ""


def test_comment_escapes_untrusted_commit_text() -> None:
    body = card_markdown(
        card(finding("fix | split @maintainers <script>x</script>", security=True))
    )
    assert body.startswith(MARKER + "\n### Sprout history check: ▲ high")
    assert "▲ high (security)" in body
    assert "fix \\| split @​maintainers &lt;script&gt;" in body  # no cell break, ping or HTML
    assert "@octocat" not in body
    assert "````diff\n-if token is None:\n-    raise ` ` ` ` oops\n````" in body
    assert 'sprout ack aaaaaaa -m "why"' in body
    assert "aaaaaaaaaaaa " in body  # a bare hash, which GitHub links


# ----- check.sh / comment.sh ------------------------------------------------------------


@pytest.fixture
def pr(make_repo: MakeRepo) -> tuple[RepoBuilder, str, str]:
    """A base branch with history, and a PR branch that re-applies a reverted change."""
    repo = make_repo("payments")
    base = repo.head()
    repo.checkout("pr", create=True)
    path = repo.root / "src/payments.py"
    path.write_text(path.read_text().replace("RETRIES = 3", "RETRIES = 0"))
    head = repo.commit("perf: drop retries again")
    return repo, base, head


def run_check(
    root: Path,
    base: str,
    head: str,
    tmp_path: Path,
    *,
    existing: str = "",
    fail_on: str = "security",
) -> tuple[int, str, list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    sprout_bin = Path(sys.executable).parent
    log, summary = tmp_path / "gh.log", tmp_path / "summary.md"
    log.unlink(missing_ok=True)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{sprout_bin}{os.pathsep}{os.environ['PATH']}",
        "SPROUT_BASE": base,
        "SPROUT_HEAD": head,
        "SPROUT_PR": "7",
        "SPROUT_FAIL_ON": fail_on,
        "SPROUT_COMMENT": "true",
        "SPROUT_EMBED_MODEL": "none",
        "GITHUB_REPOSITORY": "octo/shop",
        "GITHUB_STEP_SUMMARY": str(summary),
        "RUNNER_TEMP": str(tmp_path),
        "FAKE_LOG": str(log),
        "FAKE_EXISTING": existing,
    }
    done = subprocess.run(
        ["bash", str(ACTION / "check.sh")], cwd=root, env=env, capture_output=True, text=True
    )
    calls = log.read_text().splitlines() if log.exists() else []
    body = Path(f"{log}.body").read_text() if Path(f"{log}.body").exists() else ""
    written = summary.read_text() if summary.exists() else ""
    return done.returncode, done.stdout + done.stderr + written, calls, body


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_posts_a_comment_and_writes_the_summary(
    pr: tuple[RepoBuilder, str, str], tmp_path: Path
) -> None:
    repo, base, head = pr
    code, out, calls, body = run_check(repo.root, base, head, tmp_path)
    assert code == 0, out  # high, but not a security fix: fail-on=security lets it pass
    assert any(c.startswith("api -X POST repos/octo/shop/issues/7/comments") for c in calls), calls
    assert body.startswith(MARKER)
    assert "re-applies code that this revert removed" in body
    assert "### Sprout history check" in out  # the job summary


def test_updates_in_place_and_fail_on_any(pr: tuple[RepoBuilder, str, str], tmp_path: Path) -> None:
    repo, base, head = pr
    code, out, calls, _ = run_check(repo.root, base, head, tmp_path, existing="42", fail_on="any")
    assert code == 1, out
    assert any(c.startswith("api -X PATCH repos/octo/shop/issues/comments/42") for c in calls), (
        calls
    )
    assert "::error::Sprout" in out


def test_a_clean_pr_removes_the_old_comment(make_repo: MakeRepo, tmp_path: Path) -> None:
    repo = make_repo("payments")
    base = repo.head()
    repo.checkout("pr", create=True)
    head = repo.write("NOTES.md", "Release notes for the shop.\n").commit("docs: add notes")
    code, out, calls, _ = run_check(repo.root, base, head, tmp_path, existing="42")
    assert code == 0, out
    assert any(c.startswith("api -X DELETE repos/octo/shop/issues/comments/42") for c in calls), (
        calls
    )
    assert "no past fix, revert or security commit warns" in out


def test_security_fix_fails_by_default_and_never_is_never(
    make_repo: MakeRepo, tmp_path: Path
) -> None:
    repo = make_repo("payments")
    base = repo.head()
    repo.checkout("pr", create=True)
    head = repo.write(
        "src/auth.py", "def verify_token(token):\n    return token.startswith('t_')\n"
    ).commit("simplify")
    assert run_check(repo.root, base, head, tmp_path)[0] == 1
    assert run_check(repo.root, base, head, tmp_path, fail_on="never")[0] == 0
    code, out, _, _ = run_check(repo.root, base, head, tmp_path, fail_on="sometimes")
    assert code == 1
    assert "fail-on must be security, any or never" in out


def test_only_base_history_counts(pr: tuple[RepoBuilder, str, str], tmp_path: Path) -> None:
    repo, base, head = pr
    run_check(repo.root, base, head, tmp_path)
    with Store.open(repo.root, create=False) as store:
        assert store.db.execute("SELECT 1 FROM commits WHERE hash = ?", (head,)).fetchone() is None
        assert store.db.execute("SELECT 1 FROM commits WHERE hash = ?", (base,)).fetchone()


def test_shallow_clones_get_a_clear_error(pr: tuple[RepoBuilder, str, str], tmp_path: Path) -> None:
    repo, base, head = pr
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo.root}", str(shallow)], check=True
    )
    code, out, _, _ = run_check(shallow, base, head, tmp_path)
    assert code == 1
    assert "fetch-depth: 0" in out
