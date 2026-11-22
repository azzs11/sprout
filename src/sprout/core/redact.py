"""Remove secrets from text before it is sent to any language model.

Patterns favour recall: a false positive only hides a few characters from a summary,
while a miss could send a live credential to a remote API.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
    ),
    ("aws-key-id", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("stripe-key", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
)

# key = "value" style assignments: only the value is replaced.
_ASSIGNMENT = re.compile(
    r"(?P<key>(?i:[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|client[_-]?secret|auth)[\w.-]*))"
    r"(?P<kq>[\"']?)(?P<sep>\s*[:=]\s*|\s*=>\s*)"
    r"(?P<quote>[\"']?)(?P<value>[^\s\"',;()]{8,})"
)
_CODE_PATH = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/\s:@]+):(?P<pw>[^/\s@]+)@"
)


def redact(text: str) -> tuple[str, int]:
    """Return ``text`` with secrets replaced by ``[REDACTED:<kind>]`` and how many were found."""
    count = 0

    def _sub(kind: str) -> str:
        nonlocal count
        count += 1
        return f"[REDACTED:{kind}]"

    for kind, pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda _m, k=kind: _sub(k), text)

    def _assignment(match: re.Match[str]) -> str:
        value = match["value"]
        rest = match.string[match.end() :]
        looks_like_code = not match["quote"] and (
            _CODE_PATH.fullmatch(value) is not None or rest.startswith("(")
        )
        if value.startswith("[REDACTED") or looks_like_code:
            return match[0]
        return f"{match['key']}{match['kq']}{match['sep']}{match['quote']}{_sub('secret')}"

    text = _ASSIGNMENT.sub(_assignment, text)
    text = _URL_CREDENTIALS.sub(lambda m: f"{m['scheme']}{m['user']}:{_sub('password')}@", text)
    return text, count
