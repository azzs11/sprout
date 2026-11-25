"""Regression Memory: line fingerprints, diff parsing and the risk@2 matching rules."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sprout.core.git import open_repo
from sprout.core.index import lines
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.core.risk.check import DF_MAX, check_changes
from sprout.core.risk.patch import parse_unified
from sprout.models import ChangedLine, RiskCard, RiskKind, RiskLevel, Verdict
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def index(repo: RepoBuilder) -> Store:
    store = Store.open(repo.root, create=True)
    build_index(open_repo(repo.root), store)
    return store


def check_worktree(repo: RepoBuilder) -> RiskCard:
    with index(repo) as store:
        return check_changes(store, open_repo(repo.root).uncommitted_lines(staged_only=False))


def edit(repo: RepoBuilder, path: str, old: str, new: str) -> None:
    file = repo.root / path
    text = file.read_text()
    assert old in text
    file.write_text(text.replace(old, new))


@pytest.fixture
def payments(make_repo: MakeRepo) -> RepoBuilder:
    return make_repo("payments")


# ----- normalisation ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("    RETRIES   =  0  ", "RETRIES = 0"),
        ("}", None),
        ("pass", None),
        ("x = 1", None),
        ("-- --- ++", None),
        ("\treturn hmac.compare_digest(a, b)", "return hmac.compare_digest(a, b)"),
    ],
)
def test_normalize(text: str, expected: str | None) -> None:
    assert lines.normalize(text) == expected


def test_line_hash_is_stable_and_fits_sqlite() -> None:
    h = lines.line_hash("RETRIES = 0")
    assert h == lines.line_hash("RETRIES = 0")
    assert h != lines.line_hash("RETRIES = 3")
    assert -(2**63) <= h < 2**63


# ----- unified diffs ------------------------------------------------------------------

GIT_DIFF = """\
diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,3 @@
 keep = 1
-RETRIES = 3
+RETRIES = 0
 tail = 2
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+print("hello")
+print("world")
\\ No newline at end of file
"""

PLAIN_DIFF = """\
--- old/q.sql\t2024-01-01
+++ new/q.sql\t2024-01-02
@@ -1,2 +1,1 @@
--- a comment that starts like a header
 SELECT 1;
--- old/r.sql
+++ new/r.sql
@@ -5 +5 @@
-DELETE FROM t
+DELETE FROM t WHERE id = 1
"""


def test_parse_git_diff() -> None:
    got = parse_unified(GIT_DIFF)
    assert [(c.path, c.added, c.text, c.line) for c in got] == [
        ("src/a.py", False, "RETRIES = 3", 2),
        ("src/a.py", True, "RETRIES = 0", 2),
        ("new.py", True, 'print("hello")', 1),
        ("new.py", True, 'print("world")', 2),
    ]


def test_parse_plain_diff_uses_hunk_counts_not_header_guessing() -> None:
    got = parse_unified(PLAIN_DIFF)
    assert [(c.path, c.added, c.text) for c in got] == [
        ("old/q.sql", False, "-- a comment that starts like a header"),
        ("old/r.sql", False, "DELETE FROM t"),
        ("new/r.sql", True, "DELETE FROM t WHERE id = 1"),
    ]


# ----- fingerprints in the index --------------------------------------------------------


def test_only_fix_security_and_revert_commits_are_fingerprinted(payments: RepoBuilder) -> None:
    with index(payments) as store:
        rows = store.db.execute(
            "SELECT c.summary FROM line_commits l JOIN commits c ON c.id = l.commit_id"
        ).fetchall()
        assert lines.count_pending(store) == 0
    summaries = sorted(r[0] for r in rows)
    assert len(summaries) == 3
    assert summaries[0].startswith('Revert "perf(payments)')
    assert all("feat" not in s for s in summaries)


def test_new_rules_rebuild_fingerprints(
    payments: RepoBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    index(payments).close()
    monkeypatch.setattr(lines, "LINES_VERSION", "test-2")
    with index(payments) as store:
        assert store.get_meta("lines_version") == "test-2"
        assert store.count("SELECT count(*) FROM line_commits") == 3


def test_huge_commits_keep_no_lines(make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lines, "MAX_LINES", 3)
    repo = make_repo("empty")
    repo.write("a.py", "".join(f"value_{i} = {i}\n" for i in range(10))).commit("fix: everything")
    with index(repo) as store:
        assert store.db.execute("SELECT kept FROM line_commits").fetchone()[0] == 0


# ----- matching -----------------------------------------------------------------------


def test_reapplying_a_reverted_change_is_high(payments: RepoBuilder) -> None:
    edit(payments, "src/payments.py", "RETRIES = 3", "RETRIES = 0")
    card = check_worktree(payments)
    assert (card.level, card.verdict) == (RiskLevel.HIGH, Verdict.STOP)
    [finding] = card.findings
    assert finding.kind is RiskKind.REAPPLIES_REVERTED
    assert finding.commit.summary.startswith('Revert "perf(payments)')
    assert finding.examples == ["+RETRIES = 0", "-RETRIES = 3"]
    assert len(finding.reverts) == 1
    assert len(finding.reverts[0]) == 40


def test_changing_restored_code_asks_for_review(payments: RepoBuilder) -> None:
    edit(payments, "src/payments.py", "RETRIES = 3", "RETRIES = 4")
    card = check_worktree(payments)
    assert card.level is RiskLevel.REVIEW
    assert card.findings[0].kind is RiskKind.REMOVES_RESTORED


def test_undoing_a_security_fix_is_high(payments: RepoBuilder) -> None:
    (payments.root / "src/auth.py").write_text(
        "def verify_token(token):\n    return bool(token) and token.startswith('t_')\n"
    )
    card = check_worktree(payments)
    assert card.level is RiskLevel.HIGH
    top = card.findings[0]
    assert top.kind is RiskKind.REMOVES_FIX
    assert "timing attacks" in top.commit.summary
    assert "-import hmac" in top.examples


def test_reintroducing_a_fixed_bug(payments: RepoBuilder) -> None:
    (payments.root / "src/auth.py").write_text(
        "import hmac\n\ndef verify_token(token):\n    return token.startswith('t_')\n"
        "    # was: return hmac.compare_digest(token[:2], 't_')\n"
    )
    kinds = {f.commit.summary: f.kind for f in check_worktree(payments).findings}
    assert (
        kinds["fix(auth): reject empty tokens in verify_token (#42)"] is RiskKind.REINTRODUCES_FIXED
    )


def test_unrelated_and_moved_code_stays_silent(payments: RepoBuilder) -> None:
    edit(
        payments,
        "src/payments.py",
        "    def charge(self, amount):",
        "    # charges a card\n    def charge(self, amount):",
    )
    edit(payments, "src/payments.py", "        return amount > 0", "        return 0 < amount")
    assert check_worktree(payments).findings == []
    auth = (payments.root / "src/auth.py").read_text()
    (payments.root / "src/auth.py").write_text(auth.replace("import hmac\n", "") + "import hmac\n")
    assert check_worktree(payments).findings == []  # the guard line moved, it was not removed


def test_a_relanded_change_no_longer_warns(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("cfg.py", "TIMEOUT_SECONDS = 30\n").commit("feat: add timeout")
    bad = repo.write("cfg.py", "TIMEOUT_SECONDS = 5\n").commit("perf: lower the timeout")
    revert = repo.revert(bad)
    repo.revert(revert)  # re-land: TIMEOUT_SECONDS = 5 is wanted again
    repo.write("cfg.py", "TIMEOUT_SECONDS = 7\n").commit("tune timeout")
    (repo.root / "cfg.py").write_text("TIMEOUT_SECONDS = 5\n")
    card = check_worktree(repo)
    assert all(f.kind is not RiskKind.REAPPLIES_REVERTED for f in card.findings), card.findings


def test_long_lines_match_across_renames_short_ones_do_not(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    long_line = "    return session.retry(policy=ExponentialBackoff(max_tries=5))"
    repo.write("old.py", f"def go(session):\n{long_line}\nLIMIT = 10\n").commit("feat: go")
    repo.write("old.py", "def go(session):\n    return session.send()\nLIMIT = 99\n")
    repo.commit("fix: stop retrying non-idempotent requests")
    repo.move("old.py", "new.py")
    repo.commit("refactor: rename module")
    (repo.root / "new.py").write_text(f"def go(session):\n{long_line}\nLIMIT = 10\n")
    [finding] = check_worktree(repo).findings
    assert finding.kind is RiskKind.REINTRODUCES_FIXED
    assert finding.examples == [
        f"+{long_line.strip()}"
    ]  # LIMIT = 10 is too short to follow a rename


def test_lines_in_many_signal_commits_are_too_common(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    for i in range(DF_MAX + 1):
        repo.write("log.py", f"logger.debug('step')\nvalue_{i} = {i}\n").commit(f"fix: step {i}")
        repo.write("log.py", f"value_{i} = {i}\n").commit(f"fix: drop debug {i}")
    (repo.root / "log.py").write_text(f"logger.debug('step')\nvalue_{DF_MAX} = {DF_MAX}\n")
    assert check_worktree(repo).findings == []


def test_staged_only(payments: RepoBuilder) -> None:
    edit(payments, "src/payments.py", "RETRIES = 3", "RETRIES = 0")
    git = open_repo(payments.root)
    assert git.uncommitted_lines(staged_only=True) == []
    payments.stage("src/payments.py")
    staged = git.uncommitted_lines(staged_only=True)
    assert {(c.added, c.text.strip()) for c in staged} == {
        (True, "RETRIES = 0"),
        (False, "RETRIES = 3"),
    }


def test_no_fingerprints_yet_says_so(make_repo: MakeRepo) -> None:
    repo = make_repo("linear")  # feat/fix history, but the fix only touches a short line
    with index(repo) as store:
        store.db.execute("DELETE FROM line_commits")
        card = check_changes(
            store, [ChangedLine(path="app.py", added=True, text="return 2", line=2)]
        )
    assert card.level is RiskLevel.LOW
    assert card.notes == ["The index has no fix, security or revert lines yet: run sprout index."]


def test_before_ignores_history_that_had_not_happened_yet(payments: RepoBuilder) -> None:
    edit(payments, "src/payments.py", "RETRIES = 3", "RETRIES = 0")
    changed = open_repo(payments.root).uncommitted_lines(staged_only=False)
    revert_at = int(payments.git("log", "-1", "--format=%ct", "--grep=^Revert").strip())
    with index(payments) as store:
        assert check_changes(store, changed, before=revert_at).findings == []
        assert check_changes(store, changed, before=revert_at + 1).level is RiskLevel.HIGH


def test_removing_a_fix_counts_only_when_it_undoes_the_fix(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("io.py", "def read(path):\n    return open(path).read()\n").commit("feat: read")
    guarded = (
        "def read(path):\n"
        "    if path is None:\n"
        "        raise ValueError('path is required')\n"
        "    with open(path, encoding='utf-8') as handle:\n"
        "        return handle.read()\n"
    )
    repo.write("io.py", guarded).commit("fix: reject a missing path and close the file")
    file = repo.root / "io.py"
    file.write_text(guarded.replace("'path is required'", "'give a path'"))
    assert check_worktree(repo).findings == []  # edits one of four fix lines: churn, not undo
    file.write_text(
        "def read(path):\n    with open(path, encoding='utf-8') as handle:\n        return handle.read()\n"
    )
    [finding] = check_worktree(repo).findings  # removes the check: two of four lines
    assert finding.kind is RiskKind.REMOVES_FIX


def test_removing_a_one_line_guard_warns(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("api.py", "def get(user):\n    return user.name\n").commit("feat: get")
    repo.write(
        "api.py", "def get(user):\n    assert user is not None, 'no user'\n    return user.name\n"
    )
    repo.commit("fix: fail clearly without a user")
    (repo.root / "api.py").write_text("def get(user):\n    return user.name\n")
    [finding] = check_worktree(repo).findings
    assert (finding.kind, finding.matched, finding.total) == (RiskKind.REMOVES_FIX, 1, 1)
