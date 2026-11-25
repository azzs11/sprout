"""Add or remove Sprout's entry in each agent's project-level MCP config.

Other servers and keys are kept as they are. A file that is not plain JSON (VS Code allows
comments) is never rewritten: the user gets the exact entry to paste instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sprout.errors import SproutError
from sprout.models import Agent, ConfigAction, ConfigChange, ServerCommand

SERVER_NAME = "sprout"


@dataclass(frozen=True)
class _Format:
    path: str
    key: str  # the object that holds servers
    typed: bool  # entries carry "type": "stdio"


_FORMATS = {
    Agent.CLAUDE: _Format(".mcp.json", "mcpServers", typed=False),
    Agent.CURSOR: _Format(".cursor/mcp.json", "mcpServers", typed=False),
    Agent.VSCODE: _Format(".vscode/mcp.json", "servers", typed=True),
}

JsonObject = dict[str, object]


def entry(agent: Agent, server: ServerCommand) -> JsonObject:
    """Sprout's server entry in ``agent``'s format."""
    item: JsonObject = {"command": server.command, "args": server.args}
    return {"type": "stdio", **item} if _FORMATS[agent].typed else item


def add_server(root: Path, agent: Agent, server: ServerCommand) -> ConfigChange:
    """Write or refresh Sprout's entry in ``agent``'s config under ``root``.

    Raises:
        SproutError: the existing file is not plain JSON, so it is left untouched.
    """
    fmt = _FORMATS[agent]
    path = root / fmt.path
    data = _load(path, agent, server)
    servers = _servers(data, fmt, path)
    wanted = entry(agent, server)
    if servers.get(SERVER_NAME) == wanted:
        action = ConfigAction.UNCHANGED
    else:
        action = ConfigAction.UPDATED if SERVER_NAME in servers else ConfigAction.ADDED
        servers[SERVER_NAME] = wanted
        data[fmt.key] = servers
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return ConfigChange(agent=agent, path=fmt.path, action=action)


def remove_server(root: Path, agent: Agent) -> ConfigChange:
    """Remove Sprout's entry; delete the file if nothing else was in it."""
    fmt = _FORMATS[agent]
    path = root / fmt.path
    if not path.is_file():
        return ConfigChange(agent=agent, path=fmt.path, action=ConfigAction.ABSENT)
    data = _load(path, agent, None)
    servers = _servers(data, fmt, path)
    if SERVER_NAME not in servers:
        return ConfigChange(agent=agent, path=fmt.path, action=ConfigAction.ABSENT)
    del servers[SERVER_NAME]
    if not servers and set(data) <= {fmt.key}:
        path.unlink()
        if path.parent != root and not any(path.parent.iterdir()):
            path.parent.rmdir()  # .cursor/ or .vscode/ held only this file
        return ConfigChange(agent=agent, path=fmt.path, action=ConfigAction.DELETED_FILE)
    data[fmt.key] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return ConfigChange(agent=agent, path=fmt.path, action=ConfigAction.REMOVED)


def _load(path: Path, agent: Agent, server: ServerCommand | None) -> JsonObject:
    if not path.is_file():
        return {}
    try:
        data: object = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    loaded = _as_object(data)
    if loaded is None:
        raise SproutError(
            f"{path} is not plain JSON, so Sprout left it unchanged.",
            hint=_paste_hint(agent, server),
        )
    return loaded


def _servers(data: JsonObject, fmt: _Format, path: Path) -> JsonObject:
    servers = _as_object(data.get(fmt.key, {}))
    if servers is None:
        raise SproutError(f'"{fmt.key}" in {path} is not an object.', hint="Fix or remove it.")
    return servers


def _as_object(value: object) -> JsonObject | None:
    """``value`` as a JSON object (keys are always strings in JSON), or None if it is not one."""
    if not isinstance(value, dict):
        return None
    return {str(k): v for k, v in cast("dict[object, object]", value).items()}


def _paste_hint(agent: Agent, server: ServerCommand | None) -> str:
    if server is None:
        return f'Remove the "{SERVER_NAME}" entry from it by hand.'
    snippet = json.dumps({SERVER_NAME: entry(agent, server)})
    return f'Add this under "{_FORMATS[agent].key}" by hand: {snippet}'
