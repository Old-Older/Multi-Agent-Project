"""Loading the team: who is in it and what each member is responsible for.

Owner: JIAN Yimin.

The user defines the agents. A team file is Markdown in the format of the course's
`01_role_initialization.md`:

    | Agent ID | Role |
    |---|---|
    | `lead` | Technical Lead |

    ## Technical Lead (lead)

    ```text
    You are the technical lead of a software development team. ...
    ```

The table fixes the order of the members (the first is the fallback lead, see mas/core/lead.py);
every `## <Role name> (<agent id>)` heading is followed by a fenced block with that member's
prompt. Nothing else is read, so a different number of members or different roles need no code.
"""
from __future__ import annotations

import re
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.core.message import HUMAN, ORCHESTRATOR

ROLE_FILE = "01_role_initialization.md"

# What every member can use. The scenarios do not say who needs what, and a tool that is not
# used costs nothing; `git` asks the human before it pushes.
DEFAULT_TOOLS = ["read_file", "write_file", "delete_file", "list_files",
                 "run_python", "web_search", "fetch_url", "git"]

_ID = re.compile(r"^[A-Za-z][\w-]*$")
_HEADING = re.compile(r"^##\s+(.+?)\s*\(\s*([^()\s]+)\s*\)\s*$")
_ROW = re.compile(r"^\|\s*`?([^|`]+?)`?\s*\|\s*(.+?)\s*\|\s*$")
_CAPABILITY_CHARS = 500


def load_team(path: str | Path, tool_names: list[str] | None = None) -> dict[str, RoleConfig]:
    """The team described by a team file, or by the role file inside a scenario folder."""
    path = Path(path)
    if path.is_dir():
        path = path / ROLE_FILE
    if not path.is_file():
        raise ValueError(f"team file not found: {path}")
    return parse_team(path.read_text(encoding="utf-8"), tool_names)


def parse_team(text: str, tool_names: list[str] | None = None) -> dict[str, RoleConfig]:
    tools = list(DEFAULT_TOOLS if tool_names is None else tool_names)
    lines = text.splitlines()
    prompts: dict[str, tuple[str, str]] = {}                 # agent id -> (role name, prompt)
    i = 0
    while i < len(lines):
        heading = _HEADING.match(lines[i].strip())
        i += 1
        if not heading:
            continue
        name, agent_id = heading.group(1).strip(), heading.group(2).strip()
        block = _fenced_block(lines, i)
        if block is None:
            continue                                         # a heading that is not a role
        prompt, i = block
        if agent_id in prompts:
            raise ValueError(f"agent {agent_id!r} is defined twice")
        prompts[agent_id] = (name, prompt)
    if not prompts:
        raise ValueError("no members found: expected '## <Role name> (<agent id>)' headings, each followed by a fenced prompt")
    listed = _table_ids(lines)
    order = [a for a in listed if a in prompts] + [a for a in prompts if a not in listed]
    team: dict[str, RoleConfig] = {}
    for agent_id in order:
        if not _ID.match(agent_id) or agent_id in (HUMAN, ORCHESTRATOR):
            raise ValueError(f"{agent_id!r} cannot be an agent id")
        name, prompt = prompts[agent_id]
        capability = " ".join(prompt.split())
        if len(capability) > _CAPABILITY_CHARS:
            capability = capability[:_CAPABILITY_CHARS - 1] + "…"
        # The prompt is the member's identity; `capability` is what its teammates see of it.
        team[agent_id] = RoleConfig(agent_id=agent_id, display_name=name, capability=capability,
                                    system_prompt=prompt, tool_names=list(tools))
    return team


def _fenced_block(lines: list[str], start: int) -> tuple[str, int] | None:
    """The first fenced code block after `start` and before the next heading: (its text, the
    index after it)."""
    i = start
    while i < len(lines) and not lines[i].strip().startswith("```"):
        if lines[i].startswith("#"):
            return None
        i += 1
    if i >= len(lines):
        return None
    i += 1
    body = []
    while i < len(lines) and not lines[i].strip().startswith("```"):
        body.append(lines[i])
        i += 1
    text = "\n".join(body).strip()
    return (text, i + 1) if text else None


def _table_ids(lines: list[str]) -> list[str]:
    """Agent ids in the order of the member table (empty if there is none)."""
    ids: list[str] = []
    in_table = False
    for line in lines:
        row = _ROW.match(line.strip())
        if row is None:
            if in_table:
                break
            continue
        first = row.group(1).strip()
        if first.lower().startswith("agent id"):
            in_table = True
        elif in_table and not set(first) <= set("-: "):
            ids.append(first)
    return ids
