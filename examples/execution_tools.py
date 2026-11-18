"""Run an offline Worker smoke test with `python -m examples.execution_tools`."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.app import WorkerParts, build_system, default_worker_factory
from mas.config import Settings
from mas.core.human import CliHumanIO
from mas.core.message import HUMAN, dm_channel
from mas.core.task import TaskResult
from mas.llm.base import ChatMessage, FunctionSpec, LLMResponse, ToolCall
from mas.llm.mock import MockLLM


def execution_worker_factory(role: RoleConfig, parts: WorkerParts) -> WorkerAgent:
    """Kept for the examples: the default factory already registers every tool in each role's order."""
    return default_worker_factory(role, parts)


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
