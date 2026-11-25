"""``.sprout-acks.toml``: commits whose warnings the team switched off, with the reason why.

The file is meant to be committed, so the whole team shares it and changes to it are reviewed.
Only the standard library is used: the hooks read it on every check.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from sprout.errors import SproutError
from sprout.models import Ack

ACK_FILE = ".sprout-acks.toml"
_HEADER = """\
# Commits whose Sprout warnings no longer apply. Managed by `sprout ack` and `sprout supersede`;
# commit this file so the whole team shares it.
"""


def load(root: Path) -> list[Ack]:
    """Entries in ``root/.sprout-acks.toml`` (none if the file does not exist).

    Raises:
        SproutError: the file is not valid TOML or has an invalid entry.
    """
    path = root / ACK_FILE
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return [Ack.model_validate(entry) for entry in data.get("ack", [])]
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise SproutError(
            f"{path} could not be read: {exc}",
            hint=f"Fix the file, or delete it to turn every warning back on ({ACK_FILE}).",
        ) from None


def ignored(root: Path) -> frozenset[str]:
    """Hashes whose findings are hidden. A broken file hides nothing (warnings stay on)."""
    try:
        return frozenset(a.commit for a in load(root))
    except SproutError:
        return frozenset()


def save(root: Path, acks: list[Ack]) -> Path:
    """Write ``acks`` (sorted by date, then commit); delete the file when there are none."""
    path = root / ACK_FILE
    if not acks:
        path.unlink(missing_ok=True)
        return path
    blocks = [_entry(a) for a in sorted(acks, key=lambda a: (a.date, a.commit))]
    path.write_text(_HEADER + "".join(blocks), encoding="utf-8", newline="\n")
    return path


def upsert(acks: list[Ack], new: Ack) -> list[Ack]:
    """``acks`` with ``new`` replacing any entry for the same commit."""
    return [a for a in acks if a.commit != new.commit] + [new]


def _entry(ack: Ack) -> str:
    fields = {k: v for k, v in ack.model_dump(mode="json").items() if v is not None}
    lines = "".join(f"{k} = {toml_string(str(v))}\n" for k, v in fields.items())
    return f"\n[[ack]]\n{lines}"


def toml_string(text: str) -> str:
    """A TOML basic string for ``text``.

    JSON's escaping is close but not enough: TOML forbids a raw U+007F and has no surrogate
    pairs. So non-ASCII text is written as is, and U+007F is escaped by hand.
    """
    body = json.dumps(text, ensure_ascii=False)[1:-1]
    return '"' + body.replace("\x7f", "\\u007f") + '"'
