"""Terminal task results remain authoritative across delayed agent execution."""
from __future__ import annotations

import asyncio
import unittest

from mas.agents.base import Agent
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus


class RecordingAgent(Agent):
    def __init__(self, *args, handler=None):
        super().__init__(*args)
        self.handler = handler
        self.handled = []

    async def handle_task(self, task):
        self.handled.append(task.id)
        if self.handler:
            return await self.handler(task)
        return TaskResult(task.id, True, "executed")


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(poll(), 1)


class TaskLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = InMemoryBus()
        for name in (HUMAN, "orchestrator", "worker"):
            self.bus.join(name, GROUP_MAIN)
        self.state = StateTable()
        self.settings = Settings(subtask_timeout_s=0.05)
        self.router = Router(self.bus, self.state, {}, self.settings)
        self.agent = RecordingAgent("worker", self.bus, self.router, self.settings)
        self.running = []

    async def asyncTearDown(self):
        for task in self.running:
            task.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.running.append(task)
        return task

    def task(self):
        task = Task("work", "worker", "orchestrator", GROUP_MAIN, "R1", GROUP_MAIN)
        self.state.register(task)
        return task

    async def dispatch(self):
        return await self.router.dispatch(
            requester="orchestrator", target="worker", goal="work", session_id=GROUP_MAIN,
            root_id="R1", origin_channel=GROUP_MAIN)

    def messages(self, kind):
        return [message for message in self.bus.history(GROUP_MAIN, 100) if message.type == kind]

    async def ask(self, task_id=None, root_id="R1"):
        return await self.router.request_human(
            session_id=GROUP_MAIN, root_id=root_id, origin_channel=GROUP_MAIN,
            requester="worker", kind=HitlKind.APPROVAL, question="proceed?", task_id=task_id)

    def assert_no_human_request(self):
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])
        self.assertEqual(self.router._hitl_waiters, {})
        self.assertEqual(self.router._hitl_root, {})
        self.assertEqual(self.router._hitl_counter, {})

    async def test_expired_queued_assignment_never_calls_handler(self):
        timeout = await self.dispatch()  # TASK_ASSIGN remains queued; no agent loop is running.
        self.assertEqual(timeout.failure_mode, FailureMode.TIMEOUT)
        [assignment] = self.messages(MsgType.TASK_ASSIGN)
        await self.agent.on_message(assignment)
        self.assertEqual(self.agent.handled, [])
        [reply] = self.messages(MsgType.TASK_RESULT)
        result = TaskResult.from_dict(reply.payload["result"])
        self.assertEqual((result.success, result.failure_mode), (False, FailureMode.TIMEOUT))
        self.assertEqual(self.router.board(GROUP_MAIN).tasks[result.task_id].state, "failed")
        self.assertEqual(self.router._task_budgets, {})
        self.assert_no_human_request()

    async def test_handler_returning_after_timeout_cannot_publish_success(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow(task):
            entered.set()
            await release.wait()
            return TaskResult(task.id, True, "late success", artifacts=["late.txt"])

        self.agent.handler = slow
        self.spawn(self.agent.run())
        dispatched = self.spawn(self.dispatch())
        await asyncio.wait_for(entered.wait(), 1)
        result = await asyncio.wait_for(dispatched, 1)
        self.assertEqual(result.failure_mode, FailureMode.TIMEOUT)
        release.set()
        await until(lambda: self.messages(MsgType.TASK_RESULT))
        [reply] = self.messages(MsgType.TASK_RESULT)
        late = TaskResult.from_dict(reply.payload["result"])
        self.assertFalse(late.success)
        self.assertEqual(late.failure_mode, FailureMode.TIMEOUT)
        self.assertEqual(late.artifacts, [])
        self.assertEqual(self.state.result(result.task_id).failure_mode, FailureMode.TIMEOUT)
        self.assertEqual(self.router.board(GROUP_MAIN).tasks[result.task_id].state, "failed")

    def test_terminal_snapshot_preserves_failure_and_copies_metadata(self):
        task = self.task()
        saved = TaskResult(task.id, False, "partial work", artifacts=["part.txt"],
                           refs={"commit": "original"}, open_issues=["unfinished"],
                           error="execution timed out", failure_mode=FailureMode.TIMEOUT)
        self.state.finish(saved)
        snapshot = self.agent._terminal_result(task)
        self.assertEqual(snapshot, saved)
        self.assertIsNot(snapshot, saved)
        snapshot.artifacts.append("later.txt")
        snapshot.refs["commit"] = "changed"
        snapshot.open_issues.clear()
        snapshot.error = "changed"
        self.assertEqual((saved.artifacts, saved.refs, saved.open_issues, saved.error),
                         (["part.txt"], {"commit": "original"}, ["unfinished"], "execution timed out"))

    def test_user_cancellation_overrides_a_stored_late_success(self):
        task = self.task()
        self.router.cancel_root(task.root_id)
        self.state.finish(TaskResult(task.id, True, "late success"))
        result = self.agent._terminal_result(task)
        self.assertEqual((result.success, result.error, result.failure_mode),
                         (False, CANCELLED_ANSWER, None))

    async def test_terminal_and_unknown_tasks_cannot_open_human_requests(self):
        for success, declined in ((False, False), (True, False), (False, True)):
            with self.subTest(success=success, declined=declined):
                task = self.task()
                self.state.finish(TaskResult(task.id, success, "finished", declined=declined))
                self.assertEqual(await asyncio.wait_for(self.ask(task.id), 1), CANCELLED_ANSWER)
        self.assertEqual(await asyncio.wait_for(self.ask("unknown-task"), 1), CANCELLED_ANSWER)
        self.assert_no_human_request()

    async def test_cancelled_root_cannot_open_a_taskless_human_request(self):
        self.router.cancel_root("R1")
        self.assertEqual(await asyncio.wait_for(self.ask(), 1), CANCELLED_ANSWER)
        self.assert_no_human_request()

    async def test_expired_clock_blocks_approval_before_dispatch_resumes(self):
        self.settings.subtask_timeout_s = 1
        dispatched = self.spawn(self.dispatch())
        await until(lambda: self.messages(MsgType.TASK_ASSIGN))
        [assignment] = self.messages(MsgType.TASK_ASSIGN)
        task_id = assignment.payload["task"]["id"]
        # Force the clock past its deadline without yielding to the dispatch
        # waiter; this is the boundary between expiry and state publication.
        self.router._task_budgets[task_id].deadline = asyncio.get_running_loop().time() - 1
        self.assertEqual(await self.ask(task_id), CANCELLED_ANSWER)
        self.assertEqual(self.state.get(task_id).status, TaskStatus.FAILED)
        self.assertEqual(self.state.result(task_id).failure_mode, FailureMode.TIMEOUT)
        self.assert_no_human_request()
        result = await asyncio.wait_for(dispatched, 1)
        self.assertEqual(result.failure_mode, FailureMode.TIMEOUT)
        self.assertIsNone(self.router._remaining_execution(task_id))
        self.assertEqual(self.router._task_waiters, {})

    async def test_remaining_budget_pauses_for_human_and_cleans_up(self):
        self.settings.subtask_timeout_s = 0.5
        dispatched = self.spawn(self.dispatch())
        await until(lambda: self.messages(MsgType.TASK_ASSIGN))
        [assignment] = self.messages(MsgType.TASK_ASSIGN)
        task_id = assignment.payload["task"]["id"]
        asking = self.spawn(self.ask(task_id))
        await until(lambda: self.messages(MsgType.HITL_REQUEST))
        before = self.router._remaining_execution(task_id)
        await asyncio.sleep(0.06)
        self.assertEqual(self.router._remaining_execution(task_id), before)
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN,
                                       payload={"request_id": "h1", "answer": "yes"}))
        self.assertEqual(await asyncio.wait_for(asking, 1), "yes")
        resumed = self.router._remaining_execution(task_id)
        self.assertLessEqual(resumed, before)
        await asyncio.sleep(0.06)
        self.assertLess(self.router._remaining_execution(task_id), resumed - 0.02)
        await self.bus.publish(Message(MsgType.TASK_RESULT, "worker", GROUP_MAIN,
                                       payload={"result": TaskResult(task_id, True, "done").to_dict()}))
        self.assertTrue((await asyncio.wait_for(dispatched, 1)).success)
        self.assertIsNone(self.router._remaining_execution(task_id))


if __name__ == "__main__":
    unittest.main()
