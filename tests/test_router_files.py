"""File hand-off through the real bus, router and local workspaces."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.message import GROUP_MAIN, Message, MsgType
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.sandbox.base import LocalSandbox


class LocalFileHandoffTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.sandboxes = {
            name: LocalSandbox(name, root / name)
            for name in ("researcher", "coder", "writer")
        }
        self.bus = InMemoryBus()
        for name in ("orchestrator", "researcher", "coder", "writer", "human"):
            self.bus.join(name, GROUP_MAIN)
        self.state = StateTable()
        self.router = Router(self.bus, self.state, self.sandboxes,
                             Settings(subtask_timeout_s=1.0))
        self.workers: list[asyncio.Task] = []
        self.seen: dict[str, list[Task]] = {}

    async def asyncTearDown(self):
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    def start_worker(self, name, handler):
        """Only Worker is replaced: assignments and results use the actual bus."""
        self.seen[name] = []

        async def loop():
            inbox = self.bus.subscribe(name)
            while True:
                msg = await inbox.get()
                if msg.type != MsgType.TASK_ASSIGN or msg.receiver != name:
                    continue
                task = Task.from_dict(msg.payload["task"])
                self.seen[name].append(task)
                result = handler(task)
                await self.bus.publish(Message(
                    MsgType.TASK_RESULT, name, msg.channel,
                    payload={"result": result.to_dict()},
                    reply_to=msg.id, receiver=msg.sender))

        self.workers.append(asyncio.create_task(loop()))

    async def dispatch(self, target, *, goal="process files", files=None,
                       requester="orchestrator", root_id="R1"):
        return await asyncio.wait_for(self.router.dispatch(
            requester=requester, target=target, goal=goal, files=files,
            session_id=GROUP_MAIN, root_id=root_id, origin_channel=GROUP_MAIN), 3)

    def assignments_to(self, name):
        return [msg for msg in self.bus.history(GROUP_MAIN, 100)
                if msg.type == MsgType.TASK_ASSIGN and msg.receiver == name]

    def assert_failed(self, result, prefix):
        self.assertFalse(result.success)
        self.assertEqual(result.failure_mode, FailureMode.TOOL_ERROR)
        self.assertTrue(result.error.startswith(prefix), result.error)
        self.assertEqual(self.state.get(result.task_id).status, TaskStatus.FAILED)
        self.assertEqual(self.state.result(result.task_id), result)

    async def test_result_artifact_is_located_and_copied_before_assignment(self):
        text = "调研笔记：中文内容\n第二行\n"

        def research(task):
            self.sandboxes["researcher"].write_text("notes.md", text)
            return TaskResult(task.id, True, "research complete", artifacts=["notes.md"])

        def code(task):
            # This read happens while handling TASK_ASSIGN, proving the copy
            # completed before the downstream worker received its task.
            content = self.sandboxes["coder"].read_text("inbox/notes.md")
            return TaskResult(task.id, True, content)

        self.start_worker("researcher", research)
        self.start_worker("coder", code)
        upstream = await self.dispatch("researcher", goal="research")
        self.assertTrue(upstream.success)
        self.assertEqual(self.state.result(upstream.task_id).artifacts, ["notes.md"])
        self.assertEqual(self.router.locate_file("notes.md", "orchestrator", "R1"),
                         self.sandboxes["researcher"].resolve("notes.md"))

        downstream = await self.dispatch("coder", files=upstream.artifacts)
        self.assertTrue(downstream.success)
        self.assertEqual(downstream.summary, text)
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/notes.md"), text)
        self.assertEqual(self.sandboxes["researcher"].read_text("notes.md"), text)
        self.assertEqual(self.seen["coder"][0].files, ["notes.md"])
        self.assertEqual(self.state.get(downstream.task_id).status, TaskStatus.DONE)
        self.assertEqual(len(self.assignments_to("coder")), 1)

    async def test_requesters_file_takes_precedence_and_nested_name_is_flattened(self):
        self.sandboxes["researcher"].write_text("research/notes.md", "upstream")
        self.start_worker("researcher", lambda task: TaskResult(
            task.id, True, "done", artifacts=["research/notes.md"]))
        await self.dispatch("researcher")
        self.sandboxes["writer"].write_text("research/notes.md", "requester's own copy")
        self.start_worker("coder", lambda task: TaskResult(
            task.id, True, self.sandboxes["coder"].read_text("inbox/notes.md")))

        self.assertEqual(self.router.locate_file("research/notes.md", "writer", "R1"),
                         self.sandboxes["writer"].resolve("research/notes.md"))
        result = await self.dispatch("coder", requester="writer", files=["research/notes.md"])
        self.assertTrue(result.success)
        self.assertEqual(result.summary, "requester's own copy")
        # The current Router retains source names in Task.files and copies by
        # basename; the Worker must read inbox/<basename>, not task.files[0].
        self.assertEqual(self.seen["coder"][0].files, ["research/notes.md"])
        self.assertFalse(self.sandboxes["coder"].exists("inbox/research/notes.md"))

    async def test_unreported_and_other_root_files_are_not_discovered(self):
        self.sandboxes["researcher"].write_text("notes.md", "exists but not yet reported")
        self.assertIsNone(self.router.locate_file("notes.md", "orchestrator", "R1"))
        result = await self.dispatch("coder", files=["notes.md"])
        self.assert_failed(result, "refused: file not found:")
        self.assertEqual(self.assignments_to("coder"), [])

        self.start_worker("researcher", lambda task: TaskResult(
            task.id, True, "done", artifacts=["notes.md"]))
        await self.dispatch("researcher", root_id="R2")
        self.assertIsNone(self.router.locate_file("notes.md", "orchestrator", "R1"))
        self.assertIsNotNone(self.router.locate_file("notes.md", "orchestrator", "R2"))
        result = await self.dispatch("coder", files=["notes.md"], root_id="R1")
        self.assert_failed(result, "refused: file not found:")
        self.assertEqual(self.assignments_to("coder"), [])

    async def test_deleted_artifact_is_refused_without_contacting_downstream(self):
        self.sandboxes["researcher"].write_text("notes.md", "temporary")
        self.start_worker("researcher", lambda task: TaskResult(
            task.id, True, "done", artifacts=["notes.md"]))
        await self.dispatch("researcher")
        self.sandboxes["researcher"].delete("notes.md")

        self.assertIsNone(self.router.locate_file("notes.md", "orchestrator", "R1"))
        result = await self.dispatch("coder", files=["notes.md"])
        self.assert_failed(result, "refused: file not found:")
        self.assertEqual(self.assignments_to("coder"), [])
        self.assertFalse(self.sandboxes["coder"].exists("inbox/notes.md"))

    async def test_escaping_artifact_is_refused_even_when_reported(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("must stay outside", encoding="utf-8")
        names = ["../outside.txt", str(outside)]
        self.start_worker("researcher", lambda task: TaskResult(
            task.id, True, "bad artifact paths", artifacts=names))
        await self.dispatch("researcher")

        for name in names:
            with self.subTest(path=name):
                self.assertIsNone(self.router.locate_file(name, "orchestrator", "R1"))
                result = await self.dispatch("coder", files=[name])
                self.assert_failed(result, "refused: file not found:")
        self.assertEqual(self.assignments_to("coder"), [])
        self.assertEqual(outside.read_text(encoding="utf-8"), "must stay outside")

    async def test_existing_inbox_file_fails_handoff_without_overwriting(self):
        self.sandboxes["researcher"].write_text("notes.md", "new content")
        self.sandboxes["coder"].write_text("inbox/notes.md", "already imported")
        self.start_worker("researcher", lambda task: TaskResult(
            task.id, True, "done", artifacts=["notes.md"]))
        await self.dispatch("researcher")

        result = await self.dispatch("coder", files=["notes.md"])
        self.assert_failed(result, "cannot hand over files:")
        self.assertEqual(self.assignments_to("coder"), [])
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/notes.md"), "already imported")
        self.assertEqual(self.sandboxes["researcher"].read_text("notes.md"), "new content")


if __name__ == "__main__":
    unittest.main()
