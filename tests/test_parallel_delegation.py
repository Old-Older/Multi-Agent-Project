"""Delegations a lead sends in one reply run at the same time: different teammates, and several jobs of one teammate."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
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

TEAM = {n: RoleConfig(n, n.title(), f"{n} works.", f"You are {n}.", []) for n in ("lead", "a", "b", "c")}
PAUSE = 0.4


class Sleeper(Agent):
    """A teammate that takes PAUSE seconds, and records when."""

    def __init__(self, *args, log, fail=(), **kw):
        super().__init__(*args, **kw)
        self.log, self.fail = log, fail

    async def handle_task(self, task: Task) -> TaskResult:
        started = time.monotonic()
        await asyncio.sleep(PAUSE)
        self.log.append((self.agent_id, task.goal, started, time.monotonic(), task.context))
        if task.goal in self.fail:
            return TaskResult(task.id, False, "", error="could not do it")
        return TaskResult(task.id, True, f"{self.agent_id} did {task.goal}")


class ParallelDelegationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log: list[tuple] = []
        self.lead_calls: list[list[dict]] = []              # the tool messages the lead saw at each of its steps

    async def run_lead(self, calls: list[tuple[str, str]], fail=(), cancel_after: float | None = None,
                       **settings_overrides) -> float:
        """The lead sends `calls` ((teammate, goal) pairs) in ONE reply, then answers. Returns the seconds it took."""
        def brain(messages, tools):
            if "You assign the lead" in messages[0]["content"]:
                return LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "lead"})])
            seen = [m for m in messages if m["role"] == "tool"]
            self.lead_calls.append(seen)
            if not seen:
                return LLMResponse("", [ToolCall(f"call{i}", f"call_{who}", {"goal": goal})
                                        for i, (who, goal) in enumerate(calls)])
            return LLMResponse(json.dumps({"success": True, "summary": "all done"}))

        def factory(role, parts):
            if role.agent_id == "lead":
                return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm, [], parts.sandbox,
                                   parts.memory, peers=parts.peers)
            return Sleeper(role.agent_id, parts.bus, parts.router, parts.settings, log=self.log, fail=fail)
        settings = Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=10,
                            lead_timeout_s=20, requirements_check=False, **settings_overrides)
        system = build_system(settings, MockLLM(responder=brain), AutoResponder(), roles=TEAM, worker_factory=factory)
        system.start()
        started = time.monotonic()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "do it"))
            if cancel_after is not None:
                await asyncio.sleep(cancel_after)
                await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "/cancel"))
            while not system.requests.outcomes and time.monotonic() - started < 15:
                await asyncio.sleep(0.01)
            elapsed = time.monotonic() - started
            await asyncio.sleep(0.05)
        finally:
            await system.stop()
        if cancel_after is None:
            self.assertTrue(system.requests.outcomes["R1"].success)
        self.system = system
        return elapsed

    async def test_jobs_for_different_teammates_run_at_the_same_time(self):
        elapsed = await self.run_lead([("a", "one"), ("b", "two"), ("c", "three")])
        self.assertLess(elapsed, 3 * PAUSE * 0.8)                              # not 1.2 s one after the other
        starts, ends = [r[2] for r in self.log], [r[3] for r in self.log]
        self.assertEqual(len(self.log), 3)
        self.assertLess(max(starts), min(ends))                                # every one began before any ended

    async def test_the_lead_gets_every_answer_in_the_order_it_asked(self):
        await self.run_lead([("c", "third"), ("a", "first"), ("b", "second")])
        seen = self.lead_calls[-1]
        self.assertEqual([m["tool_call_id"] for m in seen], ["call0", "call1", "call2"])
        self.assertEqual([json.loads(m["content"])["summary"] for m in seen],
                         ["c did third", "a did first", "b did second"])

    async def test_jobs_for_one_teammate_run_at_the_same_time_too(self):
        elapsed = await self.run_lead([("a", "x"), ("a", "y"), ("b", "z")])
        a = sorted((r for r in self.log if r[0] == "a"), key=lambda r: r[2])
        self.assertLess(a[1][2], a[0][3])                                      # the second began before the first ended
        self.assertLess(elapsed, 2 * PAUSE * 0.8)                              # all three took about one PAUSE

    async def test_parallel_jobs_of_one_teammate_are_told_to_name_their_files_apart(self):
        await self.run_lead([("a", "x"), ("a", "y"), ("b", "z")])
        contexts = {r[1]: r[4] for r in self.log}
        self.assertIn("'job1_'", contexts["x"])
        self.assertIn("'job2_'", contexts["y"])
        self.assertEqual(contexts["z"], "")                                    # a teammate with one job hears nothing

    async def test_a_teammate_does_at_most_as_many_jobs_at_once_as_the_setting_allows(self):
        elapsed = await self.run_lead([("a", str(n)) for n in range(4)], max_parallel_per_teammate=2)
        self.assertEqual(len(self.log), 4)
        at_once = max(sum(1 for r in self.log if r[2] <= t < r[3]) for t in [r[2] + 0.01 for r in self.log])
        self.assertEqual(at_once, 2)
        self.assertGreaterEqual(elapsed, 2 * PAUSE)                            # two rounds of two
        self.assertLess(elapsed, 3 * PAUSE * 0.95)

    async def test_one_failing_job_does_not_stop_the_others(self):
        await self.run_lead([("a", "ok-1"), ("b", "bad"), ("c", "ok-2")], fail={"bad"})
        seen = {m["tool_call_id"]: json.loads(m["content"]) for m in self.lead_calls[-1]}
        self.assertEqual([seen[k]["ok"] for k in ("call0", "call1", "call2")], [True, False, True])
        self.assertEqual(seen["call1"]["error"], "could not do it")
        self.assertEqual(len(self.log), 3)

    async def test_cancelling_stops_all_the_jobs_and_the_lead(self):
        elapsed = await self.run_lead([("a", "one"), ("b", "two"), ("c", "three")], cancel_after=0.15)
        self.assertLess(elapsed, PAUSE)                                         # it did not wait for the teammates
        self.assertEqual(len(self.lead_calls), 1)                              # and the lead never took another step
        outcome = self.system.requests.outcomes["R1"]
        self.assertEqual((outcome.success, outcome.summary), (False, "Cancelled"))

    async def test_the_time_waited_is_the_wall_clock_not_the_sum(self):
        await self.run_lead([("a", "one"), ("b", "two"), ("c", "three")])
        [task] = [t for t in self.system.state.by_root("R1") if t.parent_id is None]
        waited = self.system.state.result(task.id).metrics["delegation_s"]
        self.assertGreaterEqual(waited, PAUSE * 0.9)
        self.assertLess(waited, 3 * PAUSE * 0.8)


if __name__ == "__main__":
    unittest.main()
