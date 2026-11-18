"""File hand-off through the real bus, router and local workspaces."""
from __future__ import annotations

import asyncio
import json
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

    async def test_a_newer_file_replaces_the_old_copy_in_the_inbox(self):
        """import_file never overwrites, but a hand-over of the same name must not fail or leave the old version:
        the teammate asked for this file, so it gets the requester's current one."""
        self.sandboxes["researcher"].write_text("notes.md", "new content")
        self.sandboxes["coder"].write_text("inbox/notes.md", "already imported")
        self.start_worker("researcher", lambda task: TaskResult(
            task.id, True, "done", artifacts=["notes.md"]))
        self.start_worker("coder", lambda task: TaskResult(task.id, True, "got it"))
        await self.dispatch("researcher")

        result = await self.dispatch("coder", files=["notes.md"])
        self.assertTrue(result.success, result.error)
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/notes.md"), "new content")
        self.assertEqual(self.sandboxes["researcher"].read_text("notes.md"), "new content")

    # ---- what the requester meant to hand over --------------------------------------------

    def coder_sees(self):
        """Start a coder that reports what its inbox holds."""
        def code(task):
            inbox = self.sandboxes["coder"].root / "inbox"
            files = {p.name: p.read_text() for p in inbox.glob("*")} if inbox.exists() else {}
            return TaskResult(task.id, True, json.dumps(files))
        self.start_worker("coder", code)

    async def test_a_file_the_goal_names_is_handed_over_even_when_files_leaves_it_out(self):
        self.sandboxes["researcher"].write_text("proposal.md", "the proposal")
        self.coder_sees()
        result = await self.dispatch("coder", requester="researcher", goal="Review proposal.md and report")
        self.assertEqual(json.loads(result.summary), {"proposal.md": "the proposal"})
        self.assertEqual(self.state.get(result.task_id).files, ["proposal.md"])

    async def test_a_changed_file_replaces_the_old_copy_the_teammate_already_has(self):
        """The failure of the third real run: the reviewer got the revised proposal's OLD copy."""
        self.sandboxes["researcher"].write_text("proposal.md", "version 1")
        self.coder_sees()
        first = await self.dispatch("coder", requester="researcher", goal="review it", files=["proposal.md"])
        self.assertEqual(json.loads(first.summary), {"proposal.md": "version 1"})
        self.sandboxes["researcher"].write_text("proposal.md", "version 2, revised")
        second = await self.dispatch("coder", requester="researcher", goal="Final sign-off on the revised proposal")
        self.assertEqual(json.loads(second.summary), {"proposal.md": "version 2, revised"})   # not listed, not named
        self.assertEqual(self.state.get(second.task_id).files, ["proposal.md"])

    async def test_an_unchanged_copy_is_left_alone_and_nothing_is_added(self):
        self.sandboxes["researcher"].write_text("proposal.md", "same")
        self.sandboxes["coder"].write_text("inbox/proposal.md", "same")
        self.sandboxes["coder"].write_text("inbox/other.md", "from elsewhere")      # the requester has no such file
        self.coder_sees()
        result = await self.dispatch("coder", requester="researcher", goal="check it")
        self.assertEqual(json.loads(result.summary), {"proposal.md": "same", "other.md": "from elsewhere"})
        self.assertEqual(self.state.get(result.task_id).files, [])

    async def test_a_name_that_is_not_a_file_of_the_requester_is_ignored(self):
        self.sandboxes["researcher"].write_text("notes.md", "n")
        self.coder_sees()
        result = await self.dispatch("coder", requester="researcher",
                                     goal="Write report.md using ../notes.md and /etc/hosts.txt, not missing.md")
        self.assertTrue(result.success)
        self.assertEqual(json.loads(result.summary), {})
        self.assertEqual(self.state.get(result.task_id).files, [])

    async def test_a_requester_without_a_workspace_hands_over_only_what_it_lists(self):
        self.sandboxes["coder"].write_text("inbox/notes.md", "old")
        self.coder_sees()
        result = await self.dispatch("coder", goal="Use notes.md")          # requester "orchestrator"
        self.assertEqual(json.loads(result.summary), {"notes.md": "old"})
        self.assertEqual(self.state.get(result.task_id).files, [])


    # ---- copy_back: what a teammate reported goes to whoever asked ----------------------------

    async def ask_researcher(self, files: dict[str, str], requester="coder", **reported):
        """`requester` delegates to the researcher, who writes `files` and reports them (or `reported['artifacts']`)."""
        def research(task):
            for name, text in files.items():
                self.sandboxes["researcher"].write_text(name, text)
            return TaskResult(task.id, True, "done", artifacts=reported.get("artifacts", list(files)))
        self.start_worker("researcher", research)
        return await self.dispatch("researcher", requester=requester, goal="research it")

    async def test_the_files_a_teammate_reported_are_copied_to_the_requesters_inbox(self):
        result = await self.ask_researcher({"brief.md": "调研：中文内容\n第二行\n", "data.json": "{}"})
        copied = self.router.copy_back("coder", result)
        self.assertEqual(copied, ["brief.md", "data.json"])
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/brief.md"), "调研：中文内容\n第二行\n")
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/data.json"), "{}")
        self.assertEqual(self.sandboxes["researcher"].read_text("brief.md"), "调研：中文内容\n第二行\n")   # the original stays

    async def test_scripts_are_not_copied_back(self):
        result = await self.ask_researcher({"brief.md": "b", "check.py": "print(1)", "run.sh": "ls", "tool.PY": "x"})
        self.assertEqual(self.router.copy_back("coder", result), ["brief.md"])
        self.assertFalse(self.sandboxes["coder"].exists("inbox/check.py"))
        self.assertFalse(self.sandboxes["coder"].exists("inbox/tool.PY"))

    async def test_only_the_last_files_are_copied_when_there_are_many(self):
        files = {f"part{n}.md": str(n) for n in range(1, 10)}
        result = await self.ask_researcher(files)
        copied = self.router.copy_back("coder", result, limit=4)
        self.assertEqual(copied, ["part6.md", "part7.md", "part8.md", "part9.md"])
        self.assertEqual(self.sandboxes["coder"].list_dir("inbox"), copied)
        self.assertEqual(len(self.router.copy_back("writer", result)), 6)         # the default limit

    async def test_a_file_over_the_size_limit_is_left_behind(self):
        result = await self.ask_researcher({"small.md": "ok", "big.md": "x" * 100})
        self.assertEqual(self.router.copy_back("coder", result, max_bytes=50), ["small.md"])
        self.assertFalse(self.sandboxes["coder"].exists("inbox/big.md"))

    async def test_a_newer_copy_replaces_the_one_already_in_the_inbox(self):
        self.sandboxes["coder"].write_text("inbox/brief.md", "old")
        result = await self.ask_researcher({"brief.md": "new"})
        self.assertEqual(self.router.copy_back("coder", result), ["brief.md"])
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/brief.md"), "new")

    async def test_nothing_is_copied_for_a_declined_task_or_a_requester_without_workspace_or_oneself(self):
        result = await self.ask_researcher({"brief.md": "b"})
        self.assertEqual(self.router.copy_back("orchestrator", result), [])      # no workspace to copy into
        self.assertEqual(self.router.copy_back("researcher", result), [])        # its own files
        declined = TaskResult(result.task_id, False, "", error="no", declined=True, artifacts=["brief.md"])
        self.assertEqual(self.router.copy_back("coder", declined), [])
        self.assertEqual(self.router.copy_back("coder", TaskResult("t-unknown", True, "x", artifacts=["brief.md"])), [])

    async def test_a_reported_file_that_is_missing_or_odd_is_skipped_without_failing(self):
        result = await self.ask_researcher({"brief.md": "b"}, artifacts=["gone.md", "../etc.md", "inbox/x.md", "brief.md", "sub"])
        self.sandboxes["researcher"].write_text("sub/deep.md", "d")
        self.assertEqual(self.router.copy_back("coder", result), ["brief.md"])
        nested = TaskResult(result.task_id, True, "", artifacts=["sub/deep.md"])
        self.assertEqual(self.router.copy_back("coder", nested), ["deep.md"])     # by its base name
        self.assertEqual(self.sandboxes["coder"].read_text("inbox/deep.md"), "d")


    # ---- stale_work: work done on a file that changed afterwards ---------------------------

    def writes(self, name, artifacts):
        def handler(task):
            return TaskResult(task.id, True, "done", artifacts=artifacts)
        self.start_worker(name, handler)

    async def test_work_done_on_an_older_version_of_a_file_is_found(self):
        """The fourth real run: the client letter was written from proposal v1, then the proposal became v2."""
        self.sandboxes["researcher"].write_text("proposal.md", "65% stocks")
        self.writes("coder", ["intro.md"])
        self.writes("writer", ["review.md"])
        await self.dispatch("coder", requester="researcher", goal="write the intro", files=["proposal.md"])
        self.assertEqual(self.router.stale_work("R1"), [])                   # nothing has changed yet
        self.sandboxes["researcher"].write_text("proposal.md", "55% stocks")
        await self.dispatch("writer", requester="researcher", goal="review it", files=["proposal.md"])
        self.assertEqual(self.router.stale_work("R1"),
                         ["coder's work (intro.md) was done on an earlier version of proposal.md, which has changed since"])

    async def test_a_teammate_that_got_the_new_version_afterwards_is_not_out_of_date(self):
        self.sandboxes["researcher"].write_text("proposal.md", "v1")
        self.writes("coder", ["intro.md"])
        await self.dispatch("coder", requester="researcher", goal="write the intro", files=["proposal.md"])
        self.sandboxes["researcher"].write_text("proposal.md", "v2")
        self.assertEqual(len(self.router.stale_work("R1")), 1)
        await self.dispatch("coder", requester="researcher", goal="update the intro to v2", files=["proposal.md"])
        self.assertEqual(self.router.stale_work("R1"), [])

    async def test_other_requests_failed_tasks_and_deleted_files_do_not_count(self):
        self.sandboxes["researcher"].write_text("proposal.md", "v1")
        self.start_worker("coder", lambda task: TaskResult(task.id, False, "", error="boom"))
        self.writes("writer", ["review.md"])
        await self.dispatch("coder", requester="researcher", goal="try", files=["proposal.md"])
        await self.dispatch("writer", requester="researcher", goal="review", files=["proposal.md"], root_id="R2")
        self.sandboxes["researcher"].write_text("proposal.md", "v2")
        self.assertEqual(self.router.stale_work("R1"), [])                   # that task failed: nothing was built on it
        self.assertEqual(len(self.router.stale_work("R2")), 1)               # a different request
        self.sandboxes["researcher"].delete("proposal.md")
        self.assertEqual(self.router.stale_work("R2"), [])                   # gone: cannot tell


if __name__ == "__main__":
    unittest.main()
