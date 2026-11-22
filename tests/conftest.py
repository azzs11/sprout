"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.fixtures.builder import SCENARIOS, RepoBuilder


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[str], RepoBuilder]:
    """Build a named fixture scenario in a fresh temporary folder."""

    def _make(name: str) -> RepoBuilder:
        return SCENARIOS[name](tmp_path / name)

    return _make


@pytest.fixture(autouse=True)
def _stable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Rich output predictable: fixed width, no colour."""
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
