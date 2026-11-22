"""Build small git repositories with known, reproducible history.

Each scenario uses fixed identities and timestamps, so commit hashes are identical on
every machine. Run ``python -m tests.fixtures.builder OUT_DIR`` to build all scenarios
into a folder you can inspect by hand.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

AUTHOR = ("Ada Lovelace", "ada@example.com")
BASE_TIME = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)


class RepoBuilder:
    """Drive the git CLI to create a repository step by step."""

    def __init__(self, root: Path, *, branch: str = "main") -> None:
        self.root = root
        self._tick = 0
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "--quiet", f"--initial-branch={branch}")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str, stdin: bytes | None = None) -> str:
        """Run git in the repository with an isolated, deterministic environment."""
        when = (BASE_TIME + timedelta(hours=self._tick)).isoformat()
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": AUTHOR[0],
            "GIT_AUTHOR_EMAIL": AUTHOR[1],
            "GIT_COMMITTER_NAME": AUTHOR[0],
            "GIT_COMMITTER_EMAIL": AUTHOR[1],
            "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_DATE": when,
        }
        done = subprocess.run(
            ["git", *args], cwd=self.root, env=env, input=stdin, capture_output=True, check=True
        )
        return done.stdout.decode("utf-8", errors="replace").strip()

    def write(self, path: str, content: str | bytes) -> RepoBuilder:
        """Write a file (text is written as UTF-8 with ``\\n`` line endings)."""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        target.write_bytes(data)
        return self

    def remove(self, path: str) -> RepoBuilder:
        """Delete a file from the working tree."""
        (self.root / path).unlink()
        return self

    def move(self, old: str, new: str) -> RepoBuilder:
        """Rename a file with ``git mv``."""
        (self.root / new).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", old, new)
        return self

    def stage(self, *paths: str) -> RepoBuilder:
        """Stage specific paths."""
        self.git("add", "--", *paths)
        return self

    def commit(self, message: str | bytes, *, encoding: str | None = None) -> str:
        """Stage everything and commit. Returns the new commit's full hash."""
        self.git("add", "--all")
        self._tick += 1
        raw = message.encode(encoding or "utf-8") if isinstance(message, str) else message
        config = ["-c", f"i18n.commitEncoding={encoding}"] if encoding else []
        self.git(*config, "commit", "--quiet", "--allow-empty", "--file=-", stdin=raw)
        return self.head()

    def checkout(self, branch: str, *, create: bool = False) -> RepoBuilder:
        """Switch branch, optionally creating it."""
        self.git("checkout", "--quiet", *(["-b"] if create else []), branch)
        return self

    def merge(self, branch: str, message: str) -> str:
        """Merge ``branch`` with a merge commit. Returns the merge commit's hash."""
        self._tick += 1
        self.git("merge", "--quiet", "--no-ff", "-m", message, branch)
        return self.head()

    def revert(self, rev: str) -> str:
        """Revert a commit. Returns the revert commit's hash."""
        self._tick += 1
        self.git("revert", "--no-edit", rev)
        return self.head()

    def head(self) -> str:
        """Full hash of HEAD."""
        return self.git("rev-parse", "HEAD")


# ----- scenarios ------------------------------------------------------------------


def empty(root: Path) -> RepoBuilder:
    """A freshly initialised repository with no commits and no files."""
    return RepoBuilder(root)


def unborn_with_changes(root: Path) -> RepoBuilder:
    """No commits yet, one staged file and one untracked file."""
    repo = RepoBuilder(root)
    repo.write("staged.txt", "staged\n").stage("staged.txt")
    repo.write("untracked.txt", "untracked\n")
    return repo


def linear(root: Path) -> RepoBuilder:
    """Three commits on main touching two files."""
    repo = RepoBuilder(root)
    repo.write("app.py", "def main():\n    return 1\n").commit("feat: add app")
    repo.write("README.md", "# demo\n").commit("docs: add readme")
    repo.write("app.py", "def main():\n    return 2\n").commit("fix: return 2 from main")
    return repo


def renames(root: Path) -> RepoBuilder:
    """A file renamed across folders, then edited."""
    repo = RepoBuilder(root)
    repo.write("old/name.py", "x = 1\ny = 2\nz = 3\n").commit("feat: add name.py")
    repo.move("old/name.py", "new/place.py")
    repo.commit("refactor: move name.py to new/place.py")
    repo.write("new/place.py", "x = 1\ny = 2\nz = 4\n").commit("fix: z is 4")
    return repo


def merge(root: Path) -> RepoBuilder:
    """A feature branch merged into main with a merge commit."""
    repo = RepoBuilder(root)
    repo.write("core.py", "core = 1\n").commit("feat: core")
    repo.checkout("feature", create=True)
    repo.write("feature.py", "feature = 1\n").commit("feat: feature")
    repo.checkout("main")
    repo.write("core.py", "core = 2\n").commit("fix: core is 2")
    repo.merge("feature", "Merge branch 'feature'")
    return repo


def revert(root: Path) -> RepoBuilder:
    """A risky change that was later reverted."""
    repo = RepoBuilder(root)
    repo.write("retry.py", "RETRIES = 3\n").commit("feat: retry payments three times")
    bad = repo.write("retry.py", "RETRIES = 0\n").commit("perf: disable retries")
    repo.revert(bad)
    return repo


def binary(root: Path) -> RepoBuilder:
    """A binary file added and then changed."""
    repo = RepoBuilder(root)
    repo.write("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x01").commit("feat: add logo")
    repo.write("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x02").commit("chore: update logo")
    return repo


def non_utf8(root: Path) -> RepoBuilder:
    """Latin-1 file content and a Latin-1 encoded commit message."""
    repo = RepoBuilder(root)
    repo.write("menu.txt", "caf\xe9\n".encode("latin-1"))
    repo.commit("feat: add caf\xe9 menu", encoding="ISO-8859-1")
    return repo


PAYMENTS_V1 = """class PaymentClient:
    RETRIES = 3

    def charge(self, amount):
        for attempt in range(self.RETRIES):
            if self._send(amount):
                return True
        return False

    def _send(self, amount):
        return amount > 0
"""


def payments(root: Path) -> RepoBuilder:
    """Realistic history for search: retries, a revert, an issue-linked fix, a security fix."""
    repo = RepoBuilder(root)
    repo.write("src/payments.py", PAYMENTS_V1)
    repo.commit(
        "feat(payments): retry failed charges three times\n\nThe card network drops ~1% of requests."
    )
    repo.write("README.md", "# shop\n").commit("docs: add readme")
    repo.write("src/payments.py", PAYMENTS_V1.replace("RETRIES = 3", "RETRIES = 0"))
    bad = repo.commit("perf(payments): disable charge retries to cut latency")
    repo.revert(bad)
    repo.write("src/auth.py", "def verify_token(token):\n    return token.startswith('t_')\n")
    repo.commit("feat(auth): add verify_token")
    repo.write(
        "src/auth.py",
        "def verify_token(token):\n    return bool(token) and token.startswith('t_')\n",
    )
    repo.commit("fix(auth): reject empty tokens in verify_token (#42)\n\nFixes #42.")
    repo.write(
        "src/auth.py",
        "import hmac\n\ndef verify_token(token):\n    return hmac.compare_digest(token[:2], 't_')\n",
    )
    repo.commit("fix(auth): compare tokens in constant time to prevent timing attacks")
    return repo


def lineage(root: Path) -> RepoBuilder:
    """One line created, its file renamed, then the line changed with a stated reason."""
    repo = RepoBuilder(root)
    code = "def charge(amount):\n    retries = 3\n    return send(amount, retries)\n"
    repo.write("src/pay.py", code).commit("feat: add charge with retries")
    repo.move("src/pay.py", "src/payments/core.py")
    repo.commit("refactor: move pay.py into the payments package")
    repo.write("src/payments/core.py", code.replace("retries = 3", "retries = 5"))
    repo.commit(
        "fix(payments): raise retries to 5\n\n"
        "We raised the limit because the card network times out under load (#7)."
    )
    repo.write("VERSION", "1.0.1\n").commit("chore: bump version")
    return repo


SCENARIOS: dict[str, Callable[[Path], RepoBuilder]] = {
    "lineage": lineage,
    "payments": payments,
    "empty": empty,
    "unborn_with_changes": unborn_with_changes,
    "linear": linear,
    "renames": renames,
    "merge": merge,
    "revert": revert,
    "binary": binary,
    "non_utf8": non_utf8,
}


def build_all(out: Path) -> None:
    """Build every scenario into ``out/<name>``."""
    for name, build in SCENARIOS.items():
        build(out / name)
        print(f"built {out / name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m tests.fixtures.builder OUT_DIR")
    build_all(Path(sys.argv[1]))
