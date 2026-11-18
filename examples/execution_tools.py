"""Run an offline Worker smoke test with `python -m examples.execution_tools`."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.app import WorkerParts, build_system
from mas.config import Settings
from mas.core.human import CliHumanIO
from mas.core.message import HUMAN, dm_channel
from mas.core.task import TaskResult
from mas.llm.base import ChatMessage, FunctionSpec, LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.tools.files import DeleteFile, ListFiles, ReadFile, WriteFile
from mas.tools.git import Git
from mas.tools.python import RunPython
from mas.tools.web import FetchURL, WebSearch


def execution_worker_factory(role: RoleConfig, parts: WorkerParts) -> WorkerAgent:
    """Pass as build_system's worker_factory to register the tools in each role's order."""
    constructors = {
        ReadFile.name: ReadFile, WriteFile.name: WriteFile,
        DeleteFile.name: DeleteFile, ListFiles.name: ListFiles,
        RunPython.name: RunPython, FetchURL.name: FetchURL,
        Git.name: lambda: Git(github_token=parts.settings.github_token),
        WebSearch.name: lambda: WebSearch(api_key=parts.settings.search_api_key),
    }
    tools = []
    for name in role.tool_names:
        if name not in constructors:
            raise ValueError(f"unknown tool {name!r} configured for {role.agent_id}")
        tools.append(constructors[name]())
    return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm,
                       tools, parts.sandbox, parts.memory)


def _report_test(messages: list[ChatMessage], tools: list[FunctionSpec] | None) -> LLMResponse:
    if tools is None:  # The Worker also requests a reflection after a failed task.
        return LLMResponse("Use the reported test diagnostics to investigate the failure.")
    observation = json.loads(messages[-1]["content"])
    report = {"success": observation["ok"], "summary": observation["output"]}
    if not observation["ok"]:
        report.update(error=observation["output"], failure_mode="tool_error")
    return LLMResponse(json.dumps(report))


async def run_example(root: Path) -> TaskResult:
    settings = Settings(workspaces_dir=root / "workspaces", data_dir=root / "data")
    role = RoleConfig("tester", "Tester", "Runs workspace tests.", "", ["run_python"])
    llm = MockLLM(script=[LLMResponse("", [
        ToolCall("check", "run_python", {"module": "unittest", "args": ["test_example"]}),
    ])], responder=_report_test)
    human = CliHumanIO(read_line=lambda: asyncio.sleep(0, result=None))
    system = build_system(settings, llm, human, roles={role.agent_id: role},
                          worker_factory=execution_worker_factory)
    system.sandboxes[role.agent_id].write_text(
        "test_example.py", "import unittest\n\nclass AdditionTest(unittest.TestCase):\n"
                           "    def test_add(self):\n        self.assertEqual(2 + 3, 5)\n",
    )
    channel = dm_channel(HUMAN, role.agent_id)
    system.start()
    try:
        result = await system.router.dispatch(
            requester=HUMAN, target=role.agent_id, goal="Run test_example and report its output.",
            session_id=channel, origin_channel=channel, root_id=system.router.new_root_id(),
        )
        if not result.success:
            raise RuntimeError(result.error or result.summary)
        return result
    finally:
        await system.stop()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        print(asyncio.run(run_example(Path(temporary))).summary)
