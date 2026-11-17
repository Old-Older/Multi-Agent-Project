"""Worker integration regressions using real local files, tools and routing."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, TaskResult, TaskStatus
from mas.llm.base import LLMResponse, ToolCall
from mas.memory.base import JsonlMemory
from mas.sandbox.base import LocalSandbox
from mas.tools.files import DeleteFile, ReadFile, WriteFile
from tests.test_worker import SnapshotLLM, call, final, prompt_text, until


class WorkerRegressionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.settings = Settings(data_dir=root / "data", workspaces_dir=root / "workspaces",
                                 subtask_timeout_s=2)
        self.bus = InMemoryBus()
        for member in (HUMAN, "worker", "upstream"):
            self.bus.join(member, GROUP_MAIN)
        self.state = StateTable()
        self.sandbox = LocalSandbox("worker", self.settings.workspaces_dir / "worker")
        self.upstream = LocalSandbox("upstream", self.settings.workspaces_dir / "upstream")
        self.router = Router(self.bus, self.state,
                             {"worker": self.sandbox, "upstream": self.upstream}, self.settings)
        self.memory = JsonlMemory.for_agent(self.settings.memory_dir, "worker")
        self.workers = []
        self.background = []

    async def asyncTearDown(self):
        for pending in self.background:
            pending.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        # Direct handle_task tests do not use Worker.run's production cleanup.
        reflections = [pending for worker in self.workers for pending in worker._reflections]
        for pending in reflections:
            pending.cancel()
        await asyncio.gather(*reflections, return_exceptions=True)

    def worker(self, script=(), *, llm=None, tools=None):
        if llm is None:
            llm = SnapshotLLM(list(script), lambda messages, specs: LLMResponse("Check the input first."))
        role = RoleConfig("worker", "Worker", "Uses its supplied tools.", "")
        worker = WorkerAgent(role, self.bus, self.router, self.settings, llm,
                             [ReadFile(), WriteFile(), DeleteFile()] if tools is None else tools,
                             self.sandbox, self.memory)
        self.workers.append(worker)
        return worker, llm

    def task(self, goal="update the files"):
        return self.router.open_direct_task(
            Message(MsgType.CHAT, HUMAN, GROUP_MAIN, goal, receiver="worker"), "worker")

    def spawn(self, coroutine):
        pending = asyncio.create_task(coroutine)
        self.background.append(pending)
        return pending

    def messages(self, kind):
        return [message for message in self.bus.history(GROUP_MAIN, 100) if message.type == kind]

    async def run_with_answer(self, worker, task, answer):
        before = len(self.messages(MsgType.HITL_REQUEST))
        pending = self.spawn(worker.handle_task(task))
        await until(lambda: len(self.messages(MsgType.HITL_REQUEST)) > before)
        request = self.messages(MsgType.HITL_REQUEST)[-1]
        await self.bus.publish(Message(
            MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN, reply_to=request.id,
            payload={"request_id": request.payload["request_id"], "answer": answer}))
        return await asyncio.wait_for(pending, 2)

    async def test_denial_stops_the_batch_and_returns_every_tool_observation(self):
        self.sandbox.write_text("keep.txt", "Important original contents")
        worker, llm = self.worker([
            LLMResponse("", [
                ToolCall("delete", "delete_file", {"path": "keep.txt"}),
                ToolCall("overwrite", "write_file", {"path": "keep.txt", "content": ""}),
            ]),
            call("read_file", "replan", path="keep.txt"),
            final(summary="Kept the original contents."),
        ])
        result = await self.run_with_answer(worker, self.task("remove keep.txt"), "no")
        self.assertTrue(result.success)
        self.assertEqual(self.sandbox.read_text("keep.txt"), "Important original contents")
        observations = [message for message in llm.calls[1][0] if message["role"] == "tool"]
        self.assertEqual([message["tool_call_id"] for message in observations], ["delete", "overwrite"])
        self.assertTrue(all(json.loads(message["content"])["ok"] is False for message in observations))
        replanned = [message for message in llm.calls[2][0]
                     if message["role"] == "tool" and message["tool_call_id"] == "replan"]
        self.assertEqual(len(replanned), 1)
        self.assertIn("Important original contents", replanned[0]["content"])

    async def test_assignment_delivered_after_router_timeout_cannot_start_execution(self):
        self.settings.subtask_timeout_s = 0.05
        write = WriteFile()
        worker, llm = self.worker([
            call("write_file", path="too-late.txt", content="must not be written"), final(),
        ], tools=[write, DeleteFile()])
        result = await self.router.dispatch(requester="upstream", target="worker", goal="write a file",
                                            session_id=GROUP_MAIN, root_id=self.router.new_root_id(),
                                            origin_channel=GROUP_MAIN)
        self.assertEqual(result.failure_mode, FailureMode.TIMEOUT)
        [assignment] = self.messages(MsgType.TASK_ASSIGN)
        with mock.patch.object(write, "run", wraps=write.run) as run:
            await asyncio.wait_for(worker.on_message(assignment), 2)
            run.assert_not_called()
        self.assertEqual(llm.calls, [])
        self.assertFalse(self.sandbox.exists("too-late.txt"))
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])
        self.assertEqual(self.memory.all(), [])
        self.assertEqual(self.state.get(result.task_id).status, TaskStatus.FAILED)
        saved = self.state.result(result.task_id)
        self.assertEqual((saved.success, saved.failure_mode, saved.error),
                         (False, FailureMode.TIMEOUT, result.error))

    async def test_human_advice_stops_the_old_batch_before_replanning(self):
        self.sandbox.write_text("keep.txt", "Important original contents")
        advice = "Stop this plan. Leave keep.txt unchanged."
        worker, llm = self.worker([
            LLMResponse("", [
                ToolCall("read", "read_file", {"path": "missing.txt"}),
                ToolCall("retry", "read_file", {"path": "missing.txt"}),
                ToolCall("overwrite", "write_file", {"path": "keep.txt", "content": ""}),
            ]),
            call("read_file", "replan", path="keep.txt"),
            final(summary="Kept the original contents."),
        ])
        result = await self.run_with_answer(worker, self.task(), advice)
        self.assertTrue(result.success)
        self.assertEqual(self.sandbox.read_text("keep.txt"), "Important original contents")
        observations = [message for message in llm.calls[1][0] if message["role"] == "tool"]
        self.assertEqual([message["tool_call_id"] for message in observations], ["read", "retry", "overwrite"])
        self.assertEqual(json.loads(observations[1]["content"])["human_advice"], advice)
        self.assertTrue(json.loads(observations[2]["content"])["skipped"])
        replanned = [message for message in llm.calls[2][0]
                     if message["role"] == "tool" and message["tool_call_id"] == "replan"]
        self.assertEqual(len(replanned), 1)
        self.assertIn("Important original contents", replanned[0]["content"])

    async def test_worker_uses_remaining_dispatch_budget_and_cancels_the_llm(self):
        entered, cancelled, never = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class BlockingLLM(SnapshotLLM):
            async def chat(self, messages, tools=None, temperature=0.2):
                entered.set()
                try:
                    await never.wait()
                finally:
                    cancelled.set()

        worker, _ = self.worker(llm=BlockingLLM([]))
        dispatched = self.spawn(self.router.dispatch(
            requester="upstream", target="worker", goal="work with little budget left",
            session_id=GROUP_MAIN, root_id=self.router.new_root_id(), origin_channel=GROUP_MAIN))
        await until(lambda: self.messages(MsgType.TASK_ASSIGN))
        [assignment] = self.messages(MsgType.TASK_ASSIGN)
        task_id = assignment.payload["task"]["id"]
        # Simulate time already spent in the queue. Dispatch is still waiting on
        # its original timer, so only the Worker's shared budget can stop the LLM.
        self.router._task_budgets[task_id].deadline = asyncio.get_running_loop().time() + 0.1
        running = self.spawn(worker.on_message(assignment))
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(running, 1)
        result = await asyncio.wait_for(dispatched, 1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual((result.success, result.failure_mode), (False, FailureMode.TIMEOUT))
        self.assertEqual(self.state.result(task_id).failure_mode, FailureMode.TIMEOUT)
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])

    async def test_router_timeout_during_llm_response_prevents_tool_execution(self):
        entered, release = asyncio.Event(), asyncio.Event()

        class DelayedLLM(SnapshotLLM):
            async def chat(self, messages, tools=None, temperature=0.2):
                entered.set()
                await release.wait()
                return await super().chat(messages, tools, temperature)

        llm = DelayedLLM([call("write_file", path="too-late.txt", content="must not be written"), final()])
        worker, _ = self.worker(llm=llm)
        task = self.task()
        pending = self.spawn(worker.handle_task(task))
        await asyncio.wait_for(entered.wait(), 2)
        timeout = TaskResult(task.id, False, "", error="router deadline reached", failure_mode=FailureMode.TIMEOUT)
        self.state.finish(timeout)
        release.set()
        result = await asyncio.wait_for(pending, 2)
        self.assertEqual((result.success, result.failure_mode), (False, FailureMode.TIMEOUT))
        self.assertFalse(self.sandbox.exists("too-late.txt"))
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])
        self.assertEqual(self.memory.all(), [])
        self.assertEqual(self.state.result(task.id).failure_mode, FailureMode.TIMEOUT)

    async def test_router_source_names_are_mapped_to_readable_inbox_paths(self):
        self.upstream.write_text("sources/input.txt", "content from the upstream workspace")
        worker, llm = self.worker([
            call("read_file", path="inbox/input.txt"), final(summary="Read the supplied file."),
        ])
        self.spawn(worker.run())
        result = await self.router.dispatch(requester="upstream", target="worker", goal="read the supplied file",
                                            files=["sources/input.txt"], session_id=GROUP_MAIN,
                                            root_id=self.router.new_root_id(), origin_channel=GROUP_MAIN)
        self.assertTrue(result.success)
        self.assertEqual(self.state.get(result.task_id).files, ["sources/input.txt"])
        self.assertIn("inbox/input.txt", prompt_text(llm.calls[0][0]))
        observation = next(message for message in llm.calls[1][0] if message["role"] == "tool")
        self.assertTrue(json.loads(observation["content"])["ok"])
        self.assertIn("content from the upstream workspace", observation["content"])

    async def test_deleted_outputs_are_omitted_even_when_the_model_lists_them(self):
        for claimed_artifacts in ([], ["temp.txt"]):
            with self.subTest(claimed_artifacts=claimed_artifacts):
                worker, _ = self.worker([
                    call("write_file", path="temp.txt", content="temporary"),
                    call("delete_file", "delete", path="temp.txt"),
                    final(artifacts=claimed_artifacts),
                ])
                result = await self.run_with_answer(worker, self.task(), "yes")
                self.assertTrue(result.success)
                self.assertFalse(self.sandbox.exists("temp.txt"))
                self.assertEqual(result.artifacts, [])

    async def test_denied_delete_preserves_the_existing_output(self):
        worker, _ = self.worker([
            call("write_file", path="temp.txt", content="keep this"),
            call("delete_file", "delete", path="temp.txt"), final(artifacts=[]),
        ])
        result = await self.run_with_answer(worker, self.task(), "no")
        self.assertTrue(result.success)
        self.assertEqual(result.artifacts, ["temp.txt"])
        self.assertEqual(self.sandbox.read_text("temp.txt"), "keep this")

    async def test_deleted_then_recreated_output_is_reported_once(self):
        worker, _ = self.worker([
            call("write_file", path="temp.txt", content="original"),
            call("delete_file", "delete", path="temp.txt"),
            call("write_file", "recreate", path="temp.txt", content="new contents"),
            final(artifacts=["./temp.txt", "temp.txt"]),
        ])
        result = await self.run_with_answer(worker, self.task(), "yes")
        self.assertTrue(result.success)
        self.assertEqual(result.artifacts, ["temp.txt"])
        self.assertEqual(self.sandbox.read_text("temp.txt"), "new contents")

    async def test_outputs_are_normalized_deduplicated_and_confined_to_workspace(self):
        outside = self.sandbox.root.parent / "outside.txt"
        outside.write_text("outside this worker", encoding="utf-8")
        worker, _ = self.worker([
            call("write_file", path="note.txt", content="saved"),
            final(artifacts=["./note.txt", "folder/../note.txt", "note.txt", "missing.txt", "../outside.txt"]),
        ])
        result = await worker.handle_task(self.task())
        self.assertTrue(result.success)
        self.assertEqual(result.artifacts, ["note.txt"])


if __name__ == "__main__":
    unittest.main()
