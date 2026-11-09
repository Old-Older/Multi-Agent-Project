"""Worker role configuration (design §1).

Owner: LI Heyang.

The three workers are one WorkerAgent class with different RoleConfig.
`capability` is what the Orchestrator sees in the call_<agent> tool
description; the memory profile is appended to it at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoleConfig:
    agent_id: str
    display_name: str
    capability: str                   # one or two sentences: what it can and cannot do
    system_prompt: str
    tool_names: list[str] = field(default_factory=list)


ROLES: dict[str, RoleConfig] = {
    "researcher": RoleConfig(
        agent_id="researcher",
        display_name="Researcher",
        capability="Searches the web, fetches pages, collects and organizes material; results are written as .md/.txt. Does not run code.",
        system_prompt="",             # TODO(LI Heyang)
        tool_names=["web_search", "fetch_url", "read_file", "write_file", "list_files"],
    ),
    "coder": RoleConfig(
        agent_id="coder",
        display_name="Coder",
        capability="Writes and runs Python code, creates/reads/updates/deletes files, commits and pushes with Git.",
        system_prompt="",
        tool_names=["read_file", "write_file", "delete_file", "list_files",
                    "run_python", "git"],
    ),
    "writer": RoleConfig(
        agent_id="writer",
        display_name="Writer",
        capability="Writes and edits Markdown / plain-text documents. Does not browse the web or run code.",
        system_prompt="",
        tool_names=["read_file", "write_file", "list_files"],
    ),
}
