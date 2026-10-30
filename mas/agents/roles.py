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
        capability="搜索网络、抓取网页、收集并整理资料，结果写成 .md/.txt。不运行代码。",
        system_prompt="",             # TODO(LI Heyang)
        tool_names=["web_search", "fetch_url", "read_file", "write_file", "list_files"],
    ),
    "coder": RoleConfig(
        agent_id="coder",
        display_name="Coder",
        capability="编写并运行 Python 代码，文件增删改查，Git 提交与推送。",
        system_prompt="",
        tool_names=["read_file", "write_file", "delete_file", "list_files",
                    "run_python", "git"],
    ),
    "writer": RoleConfig(
        agent_id="writer",
        display_name="Writer",
        capability="撰写和修改 Markdown / 纯文本文档。不上网、不运行代码。",
        system_prompt="",
        tool_names=["read_file", "write_file", "list_files"],
    ),
}
