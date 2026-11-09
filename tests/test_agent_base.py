"""Agent base class helpers that the Worker relies on (cancel checks, asking the human)."""
from __future__ import annotations

import asyncio
import unittest

from mas.agents.base import Agent
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType, dm_channel
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus


class DummyAgent(Agent):
    """handler(task) decides what handle_task does; chat_handler overrides handle_chat."""

    def __init__(self, *args, handler=None, chat_handler=None, **kw):
        super().__init__(*args, **kw)
        self.handler = handler
        self.chat_handler = chat_handler
        self.handled: list[str] = []

    async def handle_task(self, task: Task) -> TaskResult:
        self.handled.append(task.id)
        if self.handler:
            return await self.handler(task)
        return TaskResult(task.id, True, "ok")

    async def handle_chat(self, msg: Message) -> None:
        if self.chat_handler:
            return await self.chat_handler(msg)
        await super().handle_chat(msg)


class AgentBaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = InMemoryBus()
        for a in ("human", "coder"):
            self.bus.join(a, GROUP_MAIN)
        self.state = StateTable()
        self.settings = Settings()
        self.router = Router(self.bus, self.state, {}, self.settings)
        self.agent = DummyAgent("coder", self.bus, self.router, self.settings)

    def task(self, origin=GROUP_MAIN) -> Task:
        t = Task(goal="push", assignee="coder", requester="orchestrator", session_id=origin,
                 root_id="R1", origin_channel=origin, chain=["orchestrator"])
        self.state.register(t)
        return t

    def test_is_cancelled(self):
        t = self.task()
        self.assertFalse(self.agent.is_cancelled(t))
        self.state.update(t.id, TaskStatus.RUNNING)
        self.assertFalse(self.agent.is_cancelled(t))
        self.router.cancel_root("R1")
        self.assertTrue(self.agent.is_cancelled(t))

    def test_is_cancelled_for_unknown_task_is_false(self):
        ghost = Task(goal="x", assignee="coder", requester="orchestrator", session_id="s",
                     root_id="R9", origin_channel=GROUP_MAIN)
        self.assertFalse(self.agent.is_cancelled(ghost))

    async def test_ask_human_fills_the_request_from_the_task(self):
        dm = dm_channel("coder", "human")
        self.bus.join("human", dm)
        t = self.task(origin=dm)
        fut = asyncio.create_task(self.agent.ask_human(t, "push?", HitlKind.APPROVAL, ["yes", "no"]))
        await asyncio.sleep(0.01)
        [req] = [m for m in self.bus.history(dm) if m.type == MsgType.HITL_REQUEST]
        self.assertEqual((req.sender, req.channel), ("coder", dm))
        self.assertEqual(req.payload["task_id"], t.id)
        self.assertEqual(t.status, TaskStatus.WAITING_HUMAN)
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, dm,
                                       payload={"request_id": "h1", "answer": "yes"}))
        self.assertEqual(await asyncio.wait_for(fut, 1), "yes")

    async def test_ask_human_returns_the_cancel_marker(self):
        t = self.task()
        fut = asyncio.create_task(self.agent.ask_human(t, "push?", HitlKind.APPROVAL))
        await asyncio.sleep(0.01)
        self.router.cancel_root("R1")
        answer = await asyncio.wait_for(fut, 1)
        self.assertEqual(answer, CANCELLED_ANSWER)
        self.assertNotEqual(answer, "yes")


class RunLoopTest(unittest.IsolatedAsyncioTestCase):
    """Agent.run / on_message / report_status with a real bus and Router."""

    async def asyncSetUp(self):
        self.bus = InMemoryBus()
        for a in ("human", "orchestrator", "coder", "writer"):
            self.bus.join(a, GROUP_MAIN)
        self.state = StateTable()
        self.settings = Settings(subtask_timeout_s=2.0)
        self.router = Router(self.bus, self.state, {}, self.settings)
        self.running: list[asyncio.Task] = []

    async def asyncTearDown(self):
        for t in self.running:
            t.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)

    def start(self, name="coder", **kw) -> DummyAgent:
        agent = DummyAgent(name, self.bus, self.router, self.settings, **kw)
        self.running.append(asyncio.create_task(agent.run()))
        return agent

    async def dispatch(self, target="coder", goal="写脚本", root="R1", origin=GROUP_MAIN, requester="orchestrator"):
        return await self.router.dispatch(requester=requester, target=target, goal=goal, session_id=origin,
                                          root_id=root, origin_channel=origin)

    def of_type(self, channel, type_):
        return [m for m in self.bus.history(channel, 100) if m.type == type_]

    async def test_task_roundtrip(self):
        self.start(handler=lambda t: _ret(TaskResult(t.id, True, "脚本写好了", artifacts=["a.py"])))
        r = await self.dispatch()
        self.assertEqual((r.success, r.summary, r.artifacts), (True, "脚本写好了", ["a.py"]))
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.DONE)
        [assign] = self.of_type(GROUP_MAIN, MsgType.TASK_ASSIGN)
        [res] = self.of_type(GROUP_MAIN, MsgType.TASK_RESULT)
        self.assertEqual((res.sender, res.receiver, res.reply_to), ("coder", "orchestrator", assign.id))
        self.assertEqual(res.content, "@orchestrator 完成：脚本写好了（文件：a.py）")
        self.assertGreater(r.duration, 0)                  # filled in when the worker did not

    async def test_received_status_is_public_and_updates_the_table(self):
        seen = {}

        async def h(task):
            seen["status"] = self.state.get(task.id).status
            return TaskResult(task.id, True, "ok")
        self.start(handler=h)
        await self.dispatch()
        self.assertEqual(seen["status"], TaskStatus.RUNNING)    # set by the STATUS message
        [st] = self.of_type(GROUP_MAIN, MsgType.STATUS)
        self.assertTrue(st.payload["public"])
        self.assertEqual(st.content, "coder：收到 " + st.payload["task_id"] + "：写脚本")

    async def test_report_status_not_public_has_no_chat_text(self):
        agent = DummyAgent("coder", self.bus, self.router, self.settings)
        t = Task(goal="g", assignee="coder", requester="orchestrator", session_id=GROUP_MAIN,
                 root_id="R1", origin_channel=GROUP_MAIN)
        self.state.register(t)
        await agent.report_status(t, TaskStatus.RUNNING, "第 3 步")
        [st] = self.of_type(GROUP_MAIN, MsgType.STATUS)
        self.assertEqual((st.content, st.payload["public"], t.status), ("", False, TaskStatus.RUNNING))

    async def test_messages_for_others_are_ignored(self):
        coder, writer = self.start("coder"), self.start("writer")
        await self.dispatch("coder")
        await asyncio.sleep(0.02)
        self.assertEqual((len(coder.handled), len(writer.handled)), (1, 0))

    async def test_tasks_run_in_parallel(self):
        gate = asyncio.Event()
        started: list[str] = []

        async def h(task):
            started.append(task.goal)
            if task.goal == "first":
                await gate.wait()                           # blocks until the second one has started
            else:
                gate.set()
            return TaskResult(task.id, True, task.goal)
        self.start(handler=h)
        rs = await asyncio.wait_for(asyncio.gather(self.dispatch(goal="first"), self.dispatch(goal="second")), 2)
        self.assertEqual(sorted(r.summary for r in rs), ["first", "second"])
        self.assertEqual(started, ["first", "second"])

    async def test_a_crash_becomes_a_failed_result_and_the_agent_survives(self):
        calls = []

        async def h(task):
            calls.append(task.goal)
            if task.goal == "boom":
                raise ValueError("坏了")
            return TaskResult(task.id, True, "fine")
        self.start(handler=h)
        with self.assertLogs("mas.agents.base", level="ERROR"):
            bad = await self.dispatch(goal="boom")
        self.assertEqual((bad.success, bad.failure_mode, bad.error), (False, FailureMode.CRASH, "ValueError: 坏了"))
        self.assertEqual(self.state.get(bad.task_id).status, TaskStatus.FAILED)
        self.assertTrue((await self.dispatch(goal="ok")).success)      # still alive
        self.assertEqual(calls, ["boom", "ok"])

    async def test_a_task_cancelled_before_it_starts_is_not_run(self):
        agent = DummyAgent("coder", self.bus, self.router, self.settings)
        t = Task(goal="g", assignee="coder", requester="orchestrator", session_id=GROUP_MAIN,
                 root_id="R1", origin_channel=GROUP_MAIN)
        self.state.register(t)
        self.router.cancel_root("R1")
        res = await agent._execute(t, reply_to="x", receiver="orchestrator")
        self.assertEqual((res.success, res.error, agent.handled), (False, "cancelled", []))
        self.assertEqual(t.status, TaskStatus.CANCELLED)

    async def test_summary_is_clipped_and_task_id_corrected(self):
        self.settings.result_summary_max_chars = 20
        self.start(handler=lambda t: _ret(TaskResult("wrong-id", True, "很长" * 50)))
        r = await self.dispatch()
        self.assertEqual(len(r.summary), 20)
        self.assertTrue(r.summary.endswith("…"))
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.DONE)    # matched the real task

    async def test_dm_task_stays_in_the_dm(self):
        dm = dm_channel("human", "coder")
        self.bus.join("human", dm)
        self.start()
        r = await self.dispatch(requester="human", origin=dm)
        self.assertTrue(r.success)
        for type_ in (MsgType.TASK_ASSIGN, MsgType.STATUS, MsgType.TASK_RESULT):
            self.assertEqual(len(self.of_type(dm, type_)), 1, type_)
            self.assertEqual(self.of_type(GROUP_MAIN, type_), [], type_)

    async def test_human_dm_becomes_a_direct_task(self):
        dm = dm_channel("coder", "human")
        self.bus.join("human", dm)
        agent = self.start(handler=lambda t: _ret(TaskResult(t.id, True, "修好了", refs={"commit": "abc"})))
        msg = Message(MsgType.CHAT, HUMAN, dm, "修一下这个 bug", receiver="coder")
        await self.bus.publish(msg)
        await _until(lambda: self.of_type(dm, MsgType.TASK_RESULT))
        [res] = self.of_type(dm, MsgType.TASK_RESULT)
        self.assertEqual((res.receiver, res.reply_to, res.content), (HUMAN, msg.id, "@human 完成：修好了"))
        [task] = self.state.by_root("R1")
        self.assertEqual((task.goal, task.requester, task.status), ("修一下这个 bug", HUMAN, TaskStatus.DONE))
        board = self.router.board(dm)
        self.assertEqual(board.roots["R1"].human_messages, ["修一下这个 bug"])
        self.assertEqual(agent.handled, [task.id])

    async def test_mention_in_the_group_is_a_direct_task(self):
        self.start()
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "@coder 写个脚本",
                                       mentions=["coder"]))
        await _until(lambda: self.of_type(GROUP_MAIN, MsgType.TASK_RESULT))
        [task] = self.state.by_root("R1")
        self.assertEqual((task.goal, task.origin_channel), ("写个脚本", GROUP_MAIN))

    async def test_slash_commands_and_agent_chat_are_ignored_by_default(self):
        agent = self.start()
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "/status", receiver="coder"))
        await self.bus.publish(Message(MsgType.CHAT, "writer", GROUP_MAIN, "@coder 帮个忙", mentions=["coder"]))
        await asyncio.sleep(0.05)
        self.assertEqual((agent.handled, self.state.by_root("R1")), ([], []))

    async def test_cancel_in_a_dm_cancels_the_tasks_of_that_chat(self):
        dm = dm_channel("coder", "human")
        self.bus.join("human", dm)
        gate = asyncio.Event()
        seen = {}

        async def slow(task):
            await gate.wait()
            seen["cancelled"] = self.router.state.get(task.id).status      # what the worker would see
            return TaskResult(task.id, True, "late")
        agent = self.start(handler=slow)
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, dm, "做个长任务", receiver="coder"))
        await _until(lambda: agent.handled)
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, dm, "/cancel", receiver="coder"))
        await _until(lambda: [m for m in self.of_type(dm, MsgType.CHAT) if m.sender == "coder"])
        [notice] = [m for m in self.of_type(dm, MsgType.CHAT) if m.sender == "coder"]
        self.assertEqual((notice.content, notice.receiver, notice.payload), ("已取消 R1", HUMAN, {"cancelled_roots": ["R1"]}))
        [task] = self.state.by_root("R1")
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertTrue(agent.is_cancelled(task))
        gate.set()                                                          # the worker finishes anyway
        await _until(lambda: self.of_type(dm, MsgType.TASK_RESULT))
        self.assertEqual(task.status, TaskStatus.CANCELLED)                 # and the status stays cancelled

    async def test_cancel_with_nothing_running_says_so(self):
        self.start()
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "/cancel", receiver="coder"))
        await _until(lambda: [m for m in self.of_type(GROUP_MAIN, MsgType.CHAT) if m.sender == "coder"])
        [notice] = [m for m in self.of_type(GROUP_MAIN, MsgType.CHAT) if m.sender == "coder"]
        self.assertEqual((notice.content, notice.payload), ("没有进行中的任务可以取消", {"cancelled_roots": []}))

    async def test_a_crash_in_handle_chat_is_reported_in_the_chat(self):
        async def bad(msg):
            raise RuntimeError("聊天出错")
        agent = self.start(chat_handler=bad)
        with self.assertLogs("mas.agents.base", level="ERROR"):
            await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "你好", receiver="coder"))
            await _until(lambda: [m for m in self.of_type(GROUP_MAIN, MsgType.CHAT) if m.sender == "coder"])
        [err] = [m for m in self.of_type(GROUP_MAIN, MsgType.CHAT) if m.sender == "coder"]
        self.assertIn("RuntimeError: 聊天出错", err.content)
        self.assertTrue((await self.dispatch()).success)           # the loop is still running

    async def test_cancelling_run_cancels_the_handlers_in_flight(self):
        cancelled = asyncio.Event()

        async def h(task):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise
        agent = DummyAgent("coder", self.bus, self.router, self.settings, handler=h)
        runner = asyncio.create_task(agent.run())
        pending = asyncio.create_task(self.dispatch())
        await _until(lambda: agent.handled)
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        self.assertTrue(cancelled.is_set())
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def _ret(value):
    return value


async def _until(cond, timeout=2.0):
    """Wait until cond() is truthy."""
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


if __name__ == "__main__":
    unittest.main()
