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
from mas.core.task import Task, TaskResult, TaskStatus


class DummyAgent(Agent):
    async def handle_task(self, task: Task) -> TaskResult:
        return TaskResult(task.id, True, "ok")


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


if __name__ == "__main__":
    unittest.main()
