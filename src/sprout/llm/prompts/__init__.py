"""Versioned prompt files. Each ``*.md`` has front matter, a system part and a user part."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from string import Template

_FRONT_MATTER = re.compile(r"\A---\n(?P<meta>.*?)\n---\n", re.DOTALL)
_SECTIONS = re.compile(r"^=== (system|user) ===\n", re.MULTILINE)


@dataclass(frozen=True)
class Prompt:
    """A loaded prompt file."""

    name: str
    version: int
    system: str
    user: Template

    @property
    def id(self) -> str:
        """``name@version``, recorded with every output the prompt produces."""
        return f"{self.name}@{self.version}"

    def render(self, **values: str) -> str:
        """Fill the user template. ``$`` placeholders, so code braces are left alone."""
        return self.user.safe_substitute(values)


@cache
def load_prompt(name: str) -> Prompt:
    """Load ``prompts/<name>.md`` from the installed package."""
    text = files("sprout.llm.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
    return parse_prompt(text, name)


def parse_prompt(text: str, name: str) -> Prompt:
    """Parse a prompt file's text (front matter, ``=== system ===``, ``=== user ===``)."""
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ValueError(f"prompt {name} has no front matter")
    meta = dict(line.split(": ", 1) for line in match["meta"].splitlines() if ": " in line)
    parts = _SECTIONS.split(text[match.end() :])
    sections = dict(zip(parts[1::2], parts[2::2], strict=True))
    return Prompt(
        name=meta.get("name", name),
        version=int(meta.get("version", "0")),
        system=sections["system"].strip(),
        user=Template(sections["user"].strip()),
    )
