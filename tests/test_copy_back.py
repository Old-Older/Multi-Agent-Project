"""A lead that delegates reads what its teammate wrote: the files arrive in its inbox with the answer."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.app import build_system
from mas.config import Settings
from mas.core.human import AutoResponder
from mas.core.lead import CHOOSE_LEAD
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.task import Task, TaskResult
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
import asyncio
import time

TEAM = {n: RoleConfig(n, n.title(), f"{n} works.", f"You are {n}.", []) for n in ("lead", "mate")}


class Writer(Agent):
    """A teammate that writes files in its workspace and reports them."""

    def __init__(self, *args, sandbox, **kw):
        super().__init__(*args, **kw)
        self.sandbox = sandbox

    async def handle_task(self, task: Task) -> TaskResult:
        self.sandbox.write_text("report.md", "# Report\n" + "long text " * 400)       # ~4 KB: more than a reply keeps
        self.sandbox.write_text("check.py", "print('scratch')")
        return TaskResult(task.id, True, "wrote the report", artifacts=["report.md", "check.py"])


class CopyBackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    async def test_the_lead_gets_the_file_and_is_told_where_it_is(self):
        seen: list[dict] = []

        def brain(messages, tools):
            if "You assign the lead" in messages[0]["content"]:
                return LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "lead"})])
            tool_messages = [m for m in messages if m["role"] == "tool"]
            if not tool_messages:
                return LLMResponse("", [ToolCall("c1", "call_mate", {"goal": "write the report"})])
            seen.extend(json.loads(m["content"]) for m in tool_messages)
            return LLMResponse(json.dumps({"success": True, "summary": "all done"}))

        lead_box = {}

        def factory(role, parts):
            if role.agent_id == "lead":
                lead_box["sandbox"] = parts.sandbox
                return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm, [], parts.sandbox,
                                   parts.memory, peers=parts.peers)
            return Writer(role.agent_id, parts.bus, parts.router, parts.settings, sandbox=parts.sandbox)

        settings = Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=10,
                            lead_timeout_s=20, closing_check=False)
        system = build_system(settings, MockLLM(responder=brain), AutoResponder(), roles=TEAM, worker_factory=factory)
        system.start()
        started = time.monotonic()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "do it"))
            while not system.requests.outcomes and time.monotonic() - started < 10:
                await asyncio.sleep(0.01)
        finally:
            await system.stop()
        self.assertTrue(system.requests.outcomes["R1"].success)
        sandbox = lead_box["sandbox"]
        self.assertTrue(sandbox.read_text("inbox/report.md").startswith("# Report"))
        self.assertEqual(len(sandbox.read_text("inbox/report.md")), len("# Report\n" + "long text " * 400))   # whole
        self.assertFalse(sandbox.exists("inbox/check.py"))                    # the script stays with its author
        note = seen[0]["note"]
        self.assertIn("now in your inbox/: report.md", note)
        self.assertNotIn("check.py", note)


if __name__ == "__main__":
    unittest.main()
