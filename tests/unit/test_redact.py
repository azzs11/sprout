"""Secret-redaction tests with planted credentials (all fake)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sprout.core.redact import redact

# Built by concatenation so secret scanners do not flag this file.
PLANTED = {
    "aws-key-id": "AKIA" + "IOSFODNN7EXAMPLE",
    "github-token": "ghp_" + "a" * 36,
    "github-pat": "github_pat_" + "B" * 30,
    "slack-token": "xoxb-" + "1234567890-abcdef",
    "stripe-key": "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
    "google-api-key": "AIza" + "SyD" + "x" * 32,
    "anthropic-key": "sk-ant-" + "api03-" + "z" * 40,
    "openai-key": "sk-proj-" + "Q" * 40,
    "jwt": "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "s" * 20,
}


@pytest.mark.parametrize("name", sorted(PLANTED))
def test_planted_secret_is_removed(name: str) -> None:
    secret = PLANTED[name]
    text = f"+    client = Client({secret!r})\n"
    cleaned, count = redact(text)
    assert secret not in cleaned
    assert count >= 1
    assert "[REDACTED:" in cleaned


def test_private_key_block() -> None:
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"
    cleaned, _ = redact(f"before\n{block}\nafter")
    assert "MIIEow" not in cleaned
    assert cleaned.startswith("before")
    assert cleaned.endswith("after")


def test_truncated_private_key_block_is_still_removed() -> None:
    cleaned, _ = redact("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA")
    assert "b3BlbnNz" not in cleaned


@pytest.mark.parametrize(
    "line",
    [
        'DB_PASSWORD = "hunter2hunter2"',
        "api_key: 9f8e7d6c5b4a39281706",
        "SECRET_TOKEN=abcdefghijklmnop",
        '"client_secret" => "qwertyuiopasdf"',
    ],
)
def test_assignment_values_are_removed(line: str) -> None:
    cleaned, count = redact(line)
    assert count == 1
    value = line.split("=")[-1].split(":")[-1].strip(" >\"'")
    assert value not in cleaned


def test_url_credentials() -> None:
    cleaned, _ = redact("postgres://admin:s3cr3tpass@db.internal:5432/app")
    assert "s3cr3tpass" not in cleaned
    assert "postgres://admin:" in cleaned


@pytest.mark.parametrize(
    "line",
    [
        "def get_token(self):",
        "password_min_length = 8",
        "token = request.headers.get(auth_header)",
        "fix: retry payments three times",
    ],
)
def test_ordinary_code_is_kept(line: str) -> None:
    cleaned, count = redact(line)
    assert (cleaned, count) == (line, 0)


@given(st.text(max_size=400))
def test_redact_never_crashes_and_is_idempotent(text: str) -> None:
    once, _ = redact(text)
    twice, count = redact(once)
    assert twice == once
    assert count == 0
