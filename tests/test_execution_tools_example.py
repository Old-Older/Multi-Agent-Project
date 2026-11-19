"""The opt-in factory exercises real Worker selection, execution and approval."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.execution_tools import execution_worker_factory, run_example
from mas.agents.roles import RoleConfig
from mas.app import build_system
from mas.config import Settings
from mas.core.human import CliHumanIO, HitlKind
from mas.core.message import HUMAN, Message, MsgType, dm_channel
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.tools.base import ToolResult
from mas.tools.git import Git
from mas.tools.python import RunPython
from mas.tools.web import WebSearch


class ExecutionExampleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def system(self, names, llm):
        settings = Settings(workspaces_dir=self.root / "workspaces", data_dir=self.root / "data",
                            search_api_key="offline-unit-test", github_token="offline-git-test",
                            requirements_check=False)
        role = RoleConfig("custom", "Custom", "Run configured tools.", "", names)
        human = CliHumanIO(read_line=lambda: asyncio.sleep(0, result=None))
        return build_system(settings, llm, human, roles={"custom": role},
                            worker_factory=execution_worker_factory)

    async def test_example_reports_the_actual_unittest_output(self):
        result = await run_example(self.root)
        self.assertTrue(result.success, result.error)
        self.assertIn("Ran 1 test", result.summary)
        self.assertIn("exit code 0", result.summary)

    async def test_failed_tool_cannot_be_reported_as_a_passing_test(self):
        with patch.object(RunPython, "run", return_value=ToolResult(False, "sample failure")):
            with self.assertRaisesRegex(RuntimeError, "sample failure"):
                await run_example(self.root)

    def test_custom_role_selects_registered_tools_in_order_and_receives_search_config(self):
        names = ["fetch_url", "git", "read_file", "run_python", "list_files", "web_search",
                 "delete_file", "write_file"]
        with patch.object(WebSearch, "__init__", return_value=None) as construct_search, \
                patch.object(Git, "__init__", return_value=None) as construct_git:
            worker = self.system(names, MockLLM()).workers["custom"]
        construct_search.assert_called_once_with(api_key="offline-unit-test", deepseek_key="")
        construct_git.assert_called_once_with(github_token="offline-git-test")
        self.assertEqual(list(worker.tools), names)
        self.assertTrue(worker.tools["git"].requires_approval)
        with self.assertRaisesRegex(ValueError, "unknown tool"):
            self.system(["undefined"], MockLLM())

    async def test_denied_git_call_never_executes(self):
        llm = MockLLM([
            LLMResponse("", [ToolCall("init", "git", {"action": "init"})]),
            LLMResponse(json.dumps({"success": True, "summary": "Left the workspace unchanged."})),
        ])
        system = self.system(["git"], llm)
        sandbox = system.sandboxes["custom"]
        self.assertEqual(list(system.workers["custom"].tools), ["git"])
        channel = dm_channel(HUMAN, "custom")
        inbox = system.bus.subscribe(HUMAN)
        system.start()
        self.addAsyncCleanup(system.stop)
        pending = asyncio.create_task(system.router.dispatch(
            requester=HUMAN, target="custom", goal="Consider initializing a repository.",
            session_id=channel, origin_channel=channel, root_id=system.router.new_root_id(),
        ))
        try:
            with patch.object(sandbox, "exec", wraps=sandbox.exec) as execute:
                request = await asyncio.wait_for(inbox.get(), 5)
                while request.type != MsgType.HITL_REQUEST:
                    request = await asyncio.wait_for(inbox.get(), 5)
                self.assertEqual(request.payload["kind"], HitlKind.APPROVAL.value)
                self.assertIn("git", request.payload["question"])
                execute.assert_not_awaited()
                await system.bus.publish(Message(
                    MsgType.HITL_RESPONSE, HUMAN, channel, receiver="custom", reply_to=request.id,
                    payload={"request_id": request.payload["request_id"], "answer": "no"},
                ))
                await asyncio.wait_for(pending, 5)
                execute.assert_not_awaited()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        observation = json.loads(llm.calls[1][0][-1]["content"])
        self.assertFalse(observation["ok"])
        self.assertTrue(observation["approval_denied"])
        self.assertFalse(sandbox.exists(".git"))
