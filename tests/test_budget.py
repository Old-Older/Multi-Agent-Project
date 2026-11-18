"""The request's time budget, the research limit and the lead's closing check."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult
from mas.llm.base import LLMResponse
from mas.memory.base import JsonlMemory
from tests.test_worker import MemorySandbox, ScriptedTool, SnapshotLLM, call, final, prompt_text, until


class BudgetCase(unittest.IsolatedAsyncioTestCase):
    """One worker (or lead) and a clock the test moves by hand."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.settings = Settings(data_dir=root / "data", workspaces_dir=root / "workspaces", request_budget_s=100.0,
                                 lead_wrapup_s=10.0, worker_wrapup_s=50.0, min_delegation_s=60.0, closing_check=False)
        self.bus = InMemoryBus()
        for member in (HUMAN, "worker", "mate"):
            self.bus.join(member, GROUP_MAIN)
        self.state = StateTable()
        self.sandbox = MemorySandbox(root / "workspace")
        self.router = Router(self.bus, self.state, {"worker": self.sandbox}, self.settings)
        self.now = [0.0]
        self.router.clock = lambda: self.now[0]
        self.memory = JsonlMemory.for_agent(self.settings.memory_dir, "worker")
        self.workers = []

    async def asyncTearDown(self):
        pending = [p for w in self.workers for p in w._reflections]
        for p in pending:
            p.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def task(self, goal="write a note"):
        root = self.router.new_root_id(GROUP_MAIN)
        task = Task(goal, "worker", HUMAN, GROUP_MAIN, root, GROUP_MAIN, chain=[HUMAN])
        self.state.register(task)
        board = self.router.board(GROUP_MAIN)
        board.start_root(root, goal)
        board.add_task(task)
        self.router.start_clock(root)
        return task

    def member(self, script, tools=(), lead=False):
        llm = SnapshotLLM(script, lambda messages, specs: LLMResponse("Check inputs first."))
        role = RoleConfig("worker", "Worker", "Uses the supplied tools.", "Follow this task carefully.")
        peers = {"worker": role, "mate": RoleConfig("mate", "Mate", "Helps.", "")} if lead else None
        worker = WorkerAgent(role, self.bus, self.router, self.settings, llm, list(tools), self.sandbox, self.memory,
                             peers=peers)
        self.workers.append(worker)
        return worker, llm

    def clock_tool(self, *times):
        """A tool whose calls move the clock to `times`, one per call."""
        queue = list(times)

        async def hook(sandbox, kwargs):
            if queue:
                self.now[0] = queue.pop(0)
        return ScriptedTool("write_file", hook=hook)


class TimeBudgetTest(BudgetCase):
    async def test_there_is_no_budget_unless_one_is_set(self):
        self.settings.request_budget_s = 0.0
        self.assertIsNone(self.router.time_left("R1"))

    async def test_time_left_counts_down_and_does_not_count_the_wait_for_the_human(self):
        self.now[0] = 0.0
        self.router.start_clock("R1")
        self.now[0] = 10.0
        self.assertEqual(self.router.time_left("R1"), 90.0)
        asked = asyncio.create_task(self.router.request_human(
            session_id=GROUP_MAIN, root_id="R1", origin_channel=GROUP_MAIN, requester="worker",
            kind=__import__("mas.core.human", fromlist=["HitlKind"]).HitlKind.CLARIFY, question="which?"))
        await until(lambda: [m for m in self.bus.history(GROUP_MAIN, 50) if m.type == MsgType.HITL_REQUEST])
        self.now[0] = 40.0                                         # the human takes 30 s
        request = [m for m in self.bus.history(GROUP_MAIN, 50) if m.type == MsgType.HITL_REQUEST][-1]
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN, reply_to=request.id,
                                       payload={"request_id": request.payload["request_id"], "answer": "this"}))
        await asyncio.wait_for(asked, 2)
        self.now[0] = 45.0
        self.assertEqual(self.router.time_left("R1"), 100 + 30 - 45)

    async def test_when_the_time_is_up_a_member_gets_no_tools_and_is_asked_for_its_result(self):
        task = self.task()
        worker, llm = self.member([call("write_file", "c1", value="a"), final(summary="what I had")],
                                  [self.clock_tool(60.0)])             # 40 s left: under the 50 s a worker needs
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertTrue(result.success)
        self.assertEqual(result.summary, "what I had")
        first, second = llm.calls
        self.assertTrue(first[1])                                       # tools on the first step
        self.assertEqual(second[1], [])                                 # none on the second
        self.assertIn("Time is up", prompt_text(second[0]))

    async def test_a_member_that_keeps_asking_for_tools_after_the_time_is_up_is_stopped(self):
        task = self.task()
        script = [call("write_file", "c1", value="a")] + [call("write_file", f"x{n}", value="b") for n in range(5)]
        worker, llm = self.member(script, [self.clock_tool(60.0)])
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertFalse(result.success)
        self.assertEqual(result.failure_mode, FailureMode.TIMEOUT)
        self.assertEqual(len(llm.calls), 4)                             # the first step, then three answers refused

    async def test_a_lead_is_told_when_half_and_when_three_quarters_of_the_time_is_gone(self):
        task = self.task()
        worker, llm = self.member([call("write_file", "c1", value="a"), call("write_file", "c2", value="b"), final()],
                                  [self.clock_tool(55.0, 80.0)], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        texts = [prompt_text(messages) for messages, _ in llm.calls]
        self.assertNotIn("Time check", texts[0])
        self.assertIn("Stop opening new lines of research", texts[1])
        self.assertNotIn("No new research and no new reviews", texts[1])
        self.assertIn("No new research and no new reviews", texts[2])
        self.assertEqual(texts[2].count("Time check"), 2)               # each reminder once

    async def test_nobody_starts_a_delegation_with_too_little_time_left(self):
        task = self.task()
        self.now[0] = 70.0                                               # 30 s left, less than min_delegation_s
        worker, llm = self.member([call("call_mate", "c1", goal="review it"), final()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        observation = json.loads([m for m in llm.calls[1][0] if m["role"] == "tool"][0]["content"])
        self.assertFalse(observation["ok"])
        self.assertIn("Not enough time left", observation["output"])
        self.assertEqual([m for m in self.bus.history(GROUP_MAIN, 50) if m.type == MsgType.TASK_ASSIGN], [])

    async def test_a_member_is_told_its_budgets_at_the_start(self):
        task = self.task()
        worker, llm = self.member([final()])
        await asyncio.wait_for(worker.handle_task(task), 3)
        start = json.loads([m for m in llm.calls[0][0] if m["role"] == "user"][0]["content"])
        self.assertEqual(start["limits"], {"seconds_left_for_the_whole_request": 100,
                                           "searches_and_page_fetches_for_this_task": 14})


class FinishNotTooEarlyTest(BudgetCase):
    def mate_has_worked(self, task):
        mate = Task("work", "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN, chain=[HUMAN, "worker"],
                    parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, "done"))

    async def test_a_lead_that_hands_in_early_is_sent_back_twice_and_then_let_go(self):
        task = self.task()
        self.mate_has_worked(task)
        worker, llm = self.member([final(summary="a"), final(summary="b"), final(summary="c"), final(summary="d")],
                                  lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual((result.summary, len(llm.calls)), ("c", 3))
        pushed = prompt_text(llm.calls[1][0])
        self.assertIn("handing in with 100 s of the request's 100 s unused", pushed)
        self.assertIn("unverified, missing or only approximate", pushed)
        self.assertEqual(prompt_text(llm.calls[2][0]).count("unused, so there is time"), 2)

    async def test_a_lead_that_hands_in_after_half_the_time_is_not_sent_back(self):
        task = self.task()
        self.mate_has_worked(task)
        worker, llm = self.member([call("write_file", "c1", value="a"), final(summary="a")],
                                  [self.clock_tool(60.0)], lead=True)           # 40 s left of 100: over half used
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual((result.summary, len(llm.calls)), ("a", 2))

    async def test_no_push_without_a_budget_a_teammate_or_when_it_is_switched_off(self):
        task = self.task()
        worker, llm = self.member([final()], lead=True)                         # nobody was asked to do anything
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 1)

        task = self.task()
        self.mate_has_worked(task)
        self.settings.finish_not_before = 0.0
        worker, llm = self.member([final()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 1)

        self.settings.finish_not_before = 0.5
        self.settings.request_budget_s = 0.0
        task = self.task()
        self.mate_has_worked(task)
        worker, llm = self.member([final()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 1)


class ResearchLimitTest(BudgetCase):
    async def test_the_search_after_the_limit_is_refused_and_not_run(self):
        self.settings.research_max_calls = 3
        task = self.task()
        fetch = ScriptedTool("fetch_url")
        worker, llm = self.member([call("fetch_url", f"c{n}", value=f"page {n}") for n in range(1, 6)] + [final()], [fetch])
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertTrue(result.success)
        self.assertEqual(len(fetch.calls), 3)
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        self.assertEqual([o.get("limit", False) for o in seen], [False, False, False, True, True])
        self.assertIn("Research limit reached", seen[3]["output"])

    async def test_zero_means_no_limit(self):
        self.settings.research_max_calls = 0
        fetch = ScriptedTool("fetch_url")
        worker, _ = self.member([call("fetch_url", f"c{n}", value=f"p{n}") for n in range(1, 16)] + [final()], [fetch])
        self.settings.max_worker_steps = 30
        await asyncio.wait_for(worker.handle_task(self.task()), 3)
        self.assertEqual(len(fetch.calls), 15)


class ClosingCheckTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.settings.closing_check = True
        self.settings.request_budget_s = 0.0

    def teammate_result(self, task, summary, success=True, handed=None, **fields):
        mate = Task("review", "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN, chain=[HUMAN, "worker"],
                    parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, success, summary, **fields))
        if handed:
            self.router._handed[mate.id] = handed
        return mate

    def proposal(self, text):
        path = Path(self.tmp.name) / "proposal.md"
        path.write_text(text)
        return path

    async def test_work_done_on_a_changed_file_is_listed_and_asked_about_again_if_still_out_of_date(self):
        from mas.core.router import _digest
        path = self.proposal("65% stocks")
        task = self.task()
        self.teammate_result(task, "wrote it", artifacts=["intro.md"], handed={"proposal.md": (path, _digest(path))})
        path.write_text("55% stocks")                                      # the lead changed the proposal afterwards
        worker, llm = self.member([final(summary="a"), final(summary="b"), final(summary="c"), final(summary="d")],
                                  lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(result.summary, "c")                            # checked twice, not a third time
        self.assertEqual(len(llm.calls), 3)
        asked = prompt_text(llm.calls[1][0])
        self.assertIn("OUT OF DATE: mate's work (intro.md) was done on an earlier version of proposal.md", asked)
        self.assertIn("1b.", asked)

    async def test_nothing_out_of_date_means_a_single_check(self):
        from mas.core.router import _digest
        path = self.proposal("same")
        task = self.task()
        self.teammate_result(task, "wrote it", artifacts=["intro.md"], handed={"proposal.md": (path, _digest(path))})
        worker, llm = self.member([final(summary="a"), final(summary="b"), final(summary="c")], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual((result.summary, len(llm.calls)), ("b", 2))

    async def test_a_lead_is_asked_once_to_check_the_loose_ends_with_what_its_teammates_reported(self):
        task = self.task()
        self.teammate_result(task, "the investment_proposal.md in my inbox is the OLD, unrevised version")
        worker, llm = self.member([final(summary="first"), final(summary="second")], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(result.summary, "second")
        asked = prompt_text(llm.calls[1][0])
        self.assertIn("check the loose ends", asked)
        self.assertIn("mate may have hit a problem", asked)
        self.assertIn("OLD, unrevised version", asked)
        self.assertNotIn("check the loose ends", prompt_text(llm.calls[0][0]))

    async def test_a_failed_teammate_and_open_issues_are_listed(self):
        task = self.task()
        self.teammate_result(task, "", success=False, error="no result within 900s")
        self.teammate_result(task, "done", open_issues=["Chinese version missing"])
        worker, llm = self.member([final(), final()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        asked = prompt_text(llm.calls[1][0])
        self.assertIn("mate FAILED: no result within 900s", asked)
        self.assertIn("mate left open: Chinese version missing", asked)

    async def test_the_lead_can_fix_things_after_the_check_and_is_not_checked_again(self):
        task = self.task()
        self.teammate_result(task, "fine")
        worker, llm = self.member([final(), call("write_file", "c1", value="fix"), final(summary="fixed"), final()], [
            ScriptedTool("write_file")], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(result.summary, "fixed")
        self.assertEqual(len(llm.calls), 3)
        self.assertEqual(prompt_text(llm.calls[2][0]).count("check the loose ends"), 1)

    async def test_nothing_to_check_when_no_teammate_was_asked_or_the_check_is_off_or_time_is_up(self):
        worker, llm = self.member([final()], lead=True)
        await asyncio.wait_for(worker.handle_task(self.task()), 3)
        self.assertEqual(len(llm.calls), 1)                              # a lead that delegated nothing

        self.settings.closing_check = False
        task = self.task()
        self.teammate_result(task, "fine")
        worker, llm = self.member([final()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 1)                              # switched off

        self.settings.closing_check = True
        self.settings.request_budget_s = 100.0
        task = self.task()
        self.teammate_result(task, "fine")
        worker, llm = self.member([call("write_file", "c1", value="a"), final()], [self.clock_tool(95.0)], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 2)                              # 5 s left: no time for a check


if __name__ == "__main__":
    unittest.main()
