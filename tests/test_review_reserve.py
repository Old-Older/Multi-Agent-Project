"""A review that does not pass: how it is read, the time added for the fix and the re-check, and the closing check."""
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
from mas.core.router import Router
from mas.core.task import Task, TaskResult
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from tests.test_budget import BudgetCase
from tests.test_worker import final, prompt_text

REVIEW = "Review the deck"


def verdict(text, goal=REVIEW, **fields):
    return Router.review_verdict(goal, TaskResult("t", True, text, **fields))


class ReadingAVerdictTest(unittest.TestCase):
    def test_what_fails(self):
        for text in ("Verdict: FAIL with six concrete errors.",
                     "PASS on points 1 to 5, FAIL on point 6.",                 # one failing point fails the review
                     "Final check: APPROVE WITH CHANGES. Re-send the revised file.",
                     "Verdict: approve with conditions, the stress test is understated.",
                     "REJECTED: the figures are wrong.",
                     "The deck is not publishable as it is.",
                     "三項不通過，請修改。",
                     "Top 5 fixes: (1) correct the FX claim ...",
                     "Remaining must-fix items: 1) the 2025 row is duplicated."):
            self.assertEqual(verdict(text), "fail", text)

    def test_what_passes(self):
        for text in ("PASS on all six points.", "Approved. No must-fix items remain.", "Verdict: APPROVE", "LGTM",
                     "全部通過，沒有需要修改的地方。"):
            self.assertEqual(verdict(text), "pass", text)

    def test_what_is_not_a_verdict(self):
        self.assertIsNone(verdict("Reviewed the deck and wrote review.md with my notes."))
        self.assertIsNone(verdict("FAIL", goal="Write a one-page brief on memory prices"))        # not a review
        self.assertIsNone(verdict("FAIL", goal="Produce a brief ... " + "x" * 200 + " verify the numbers"))   # said late
        self.assertIsNone(Router.review_verdict(REVIEW, TaskResult("t", False, "FAIL", error="boom")))
        self.assertIsNone(Router.review_verdict(REVIEW, TaskResult("t", True, "FAIL", declined=True)))
        self.assertEqual(verdict("all fine", open_issues=["FAIL: row 3"]), "fail")


class OpenReviewsTest(unittest.TestCase):
    def setUp(self):
        from mas.core.bus import InMemoryBus
        from mas.core.state import StateTable
        self.state = StateTable()
        self.router = Router(InMemoryBus(), self.state, {}, Settings())

    def done(self, assignee, goal, summary, root="R1"):
        task = Task(goal, assignee, "lead", GROUP_MAIN, root, GROUP_MAIN, chain=[HUMAN, "lead"])
        self.state.register(task)
        self.state.finish(TaskResult(task.id, True, summary))

    def test_a_failed_review_stays_open_until_the_same_reviewer_passes_it(self):
        self.done("risk", "Review the deck", "FAIL: six errors")
        self.assertEqual(len(self.router.open_reviews("R1")), 1)
        self.assertIn("risk's latest verdict is not a pass: FAIL: six errors", self.router.open_reviews("R1")[0])
        self.done("marketing", "Update the deck text", "done, FAIL is not a word I use")      # not a review
        self.assertEqual(len(self.router.open_reviews("R1")), 1)
        self.done("risk", "Re-check items 1 to 6", "PASS on all six")
        self.assertEqual(self.router.open_reviews("R1"), [])

    def test_reviewers_and_requests_are_kept_apart(self):
        self.done("risk", "Review the deck", "FAIL: six errors")
        self.done("marketing", "Review the deck", "PASS")                                    # another reviewer passing
        self.done("risk", "Review the memo", "FAIL: bad", root="R2")
        self.assertEqual(len(self.router.open_reviews("R1")), 1)
        self.assertEqual(len(self.router.open_reviews("R2")), 1)
        self.assertEqual(self.router.open_reviews("R3"), [])


class ReserveTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.settings.request_budget_s = 270.0
        self.settings.review_reserve_s = 120.0
        self.settings.max_review_extensions = 2

    def test_time_is_topped_up_to_the_reserve_not_added_on_top(self):
        self.router.start_clock("R1")
        self.now[0] = 211.0                                                  # 59 s left of 270
        self.assertEqual(self.router.grant_review_reserve("R1"), 61.0)
        self.assertEqual(self.router.time_left("R1"), 120.0)
        self.assertEqual(self.router.grant_review_reserve("R1"), 0.0)       # already enough: nothing more
        self.now[0] = 280.0                                                  # 51 s left again
        self.assertEqual(self.router.grant_review_reserve("R1"), 69.0)      # the second and last time
        self.now[0] = 340.0
        self.assertEqual(self.router.grant_review_reserve("R1"), 0.0)       # used up
        self.assertEqual(self.router.time_left("R1"), 60.0)

    def test_no_time_is_added_without_a_budget_or_when_it_is_switched_off(self):
        self.router.start_clock("R1")
        self.now[0] = 250.0
        self.settings.review_reserve_s = 0.0
        self.assertEqual(self.router.grant_review_reserve("R1"), 0.0)
        self.settings.review_reserve_s, self.settings.request_budget_s = 120.0, 0.0
        self.assertEqual(self.router.grant_review_reserve("R1"), 0.0)
        self.assertIsNone(self.router.time_left("R1"))


class ClosingCheckWithReviewsTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.settings.closing_check = True
        self.settings.request_budget_s = 0.0

    def mate(self, task, goal, summary):
        mate = Task(goal, "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN, chain=[HUMAN, "worker"],
                    parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, summary))

    async def test_a_review_nobody_cleared_is_put_to_the_lead_and_asked_about_twice(self):
        task = self.task()
        self.mate(task, "Review the deck", "Verdict: FAIL, six errors")
        worker, llm = self.member([final(summary="a"), final(summary="b"), final(summary="c")], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual((result.summary, len(llm.calls)), ("c", 3))
        asked = prompt_text(llm.calls[1][0])
        self.assertIn("REVIEW NOT CLEARED: mate's latest verdict is not a pass: Verdict: FAIL, six errors", asked)
        self.assertIn("1a.", asked)

    async def test_a_cleared_review_is_not_mentioned(self):
        task = self.task()
        self.mate(task, "Review the deck", "FAIL: six errors")
        self.mate(task, "Re-check the six items", "PASS")
        worker, llm = self.member([final(summary="a"), final(summary="b")], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual((result.summary, len(llm.calls)), ("b", 2))          # the single check
        asked = prompt_text(llm.calls[1][0])
        self.assertNotIn("REVIEW NOT CLEARED: mate", asked)                     # no flagged line, only the explanation
        self.assertIn("none flagged", asked)


class UnreviewedFilesTest(OpenReviewsTest):
    def done(self, assignee, goal, summary, root="R1", handed=(), artifacts=(), success=True):
        task = Task(goal, assignee, "lead", GROUP_MAIN, root, GROUP_MAIN, chain=[HUMAN, "lead"])
        self.state.register(task)
        self.state.finish(TaskResult(task.id, success, summary, artifacts=list(artifacts)))
        if handed:
            self.router._handed[task.id] = {name: (Path(name), None) for name in handed}

    def test_a_file_given_to_a_reviewer_is_reviewed_and_another_one_is_not(self):
        self.done("risk", "Review the proposal", "PASS", handed=["proposal.md"])
        self.assertEqual(self.router.unreviewed("R1", ["proposal.md", "deck.html"]), ["deck.html"])

    def test_names_are_compared_by_base_name_and_scripts_are_not_deliverables(self):
        self.done("risk", "Re-check the deck", "PASS", handed=["inbox/deck.html"])
        self.assertEqual(self.router.unreviewed("R1", ["deck.html", "check.py", "build.sh"]), [])

    def test_what_a_reviewer_wrote_needs_no_review_itself(self):
        self.done("risk", "Review the proposal", "PASS", handed=["proposal.md"], artifacts=["risk_review.md"])
        self.assertEqual(self.router.unreviewed("R1", ["proposal.md", "risk_review.md"]), [])

    def test_a_failed_task_or_one_that_is_not_a_review_or_another_request_does_not_count(self):
        self.done("risk", "Review the proposal", "", handed=["a.md"], success=False)
        self.done("marketing", "Write the intro from the proposal", "done", handed=["b.md"])
        self.done("risk", "Review the memo", "PASS", handed=["c.md"], root="R2")
        self.assertEqual(self.router.unreviewed("R1", ["a.md", "b.md", "c.md"]), ["a.md", "b.md", "c.md"])


class UnreviewedDeliverableTest(BudgetCase):
    """The sixth real run: the deck was handed in with 42 s left and nobody had reviewed it."""

    def setUp(self):
        super().setUp()
        self.settings.request_budget_s = 270.0
        self.settings.min_delegation_s = 80.0
        self.settings.closing_check = True
        self.settings.finish_not_before = 0.0

    def deck(self, **fields):
        return final(summary="deck", artifacts=["deck.html"], **fields)

    async def test_a_lead_with_an_unreviewed_deliverable_gets_time_and_is_sent_to_a_reviewer_twice_at_most(self):
        task = self.task()
        self.now[0] = 228.0                                                   # 42 s left of 270
        worker, llm = self.member([self.deck(), self.deck(), self.deck(), self.deck()], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 3)                                   # handed in the third time
        self.assertTrue(result.success)
        first, second = prompt_text(llm.calls[1][0]), prompt_text(llm.calls[2][0])
        self.assertIn("deck.html has not been reviewed", first)
        self.assertIn("Time was added for exactly this: about 120 s are left", first)
        self.assertIn("begin its answer with PASS or FAIL", first)
        self.assertEqual(second.count("has not been reviewed"), 2)
        self.assertIn("About 120 s are left", second)                         # nothing more to add the second time

    async def test_a_deliverable_a_reviewer_has_seen_is_not_sent_back(self):
        task = self.task()
        mate = Task("Review the deck", "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN,
                    chain=[HUMAN, "worker"], parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, "PASS"))
        self.router._handed[mate.id] = {"deck.html": (Path("deck.html"), None)}
        worker, llm = self.member([self.deck(), self.deck()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertNotIn("has not been reviewed", prompt_text(llm.calls[-1][0]))

    async def test_no_push_when_no_review_could_be_started(self):
        task = self.task()
        self.settings.review_reserve_s = 0.0                                  # no time can be added
        self.now[0] = 250.0                                                   # 20 s left, under the 80 s a delegation needs
        worker, llm = self.member([self.deck(), self.deck()], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 1)
        self.assertTrue(result.success)

    async def test_switched_off_or_nothing_listed_or_no_budget_to_top_up(self):
        self.settings.review_final = False
        worker, llm = self.member([self.deck()], lead=True)
        await asyncio.wait_for(worker.handle_task(self.task()), 3)
        self.assertEqual(len(llm.calls), 1)

        self.settings.review_final = True
        worker, llm = self.member([final(summary="nothing to review")], lead=True)
        await asyncio.wait_for(worker.handle_task(self.task()), 3)
        self.assertEqual(len(llm.calls), 1)

        self.settings.request_budget_s = 0.0                                  # no budget: pushed all the same, no time added
        worker, llm = self.member([self.deck(), self.deck(), self.deck()], lead=True)
        await asyncio.wait_for(worker.handle_task(self.task()), 3)
        self.assertEqual(len(llm.calls), 3)
        self.assertNotIn("Time was added", prompt_text(llm.calls[1][0]))


class Reviewer(Agent):
    """A reviewer that answers from a list and takes the given seconds on the test's clock."""

    def __init__(self, *args, clock, answers, **kw):
        super().__init__(*args, **kw)
        self.clock, self.answers = clock, answers

    async def handle_task(self, task: Task) -> TaskResult:
        text, seconds = self.answers.pop(0)
        self.clock[0] += seconds
        return TaskResult(task.id, True, text)


class FixAndRecheckFitsTest(unittest.IsolatedAsyncioTestCase):
    """The fifth real run: the reviewer's FAIL came with 59 s left, less than a delegation needs, so the fix was
    never checked."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    async def run_request(self, **settings):
        now = [0.0]
        seen: list[dict] = []

        def brain(messages, tools):
            if "You assign the lead" in messages[0]["content"]:
                return LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "lead"})])
            tool_messages = [m for m in messages if m["role"] == "tool"]
            if len(tool_messages) == 0:
                return LLMResponse("", [ToolCall("c1", "call_reviewer", {"goal": REVIEW})])
            if len(tool_messages) == 1:
                seen.append(json.loads(tool_messages[0]["content"]))
                return LLMResponse("", [ToolCall("c2", "call_reviewer", {"goal": "Re-check items 1 and 2 of the deck"})])
            seen.append(json.loads(tool_messages[1]["content"]))
            return LLMResponse(json.dumps({"success": True, "summary": "done"}))

        answers = [("Verdict: FAIL. 1) wrong share 2) unverified claim", 211.0), ("PASS on items 1 and 2", 30.0)]

        def factory(role, parts):
            if role.agent_id == "lead":
                return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm, [], parts.sandbox,
                                   parts.memory, peers=parts.peers)
            return Reviewer(role.agent_id, parts.bus, parts.router, parts.settings, clock=now, answers=answers)

        team = {n: RoleConfig(n, n.title(), f"{n} works.", f"You are {n}.", []) for n in ("lead", "reviewer")}
        defaults = dict(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=10,
                        lead_timeout_s=20, request_budget_s=270.0, closing_check=False, finish_not_before=0.0)
        system = build_system(Settings(**{**defaults, **settings}), MockLLM(responder=brain), AutoResponder(),
                              roles=team, worker_factory=factory)
        system.router.clock = lambda: now[0]
        system.start()
        started = time.monotonic()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "do it"))
            while not system.requests.outcomes and time.monotonic() - started < 10:
                await asyncio.sleep(0.01)
        finally:
            await system.stop()
        self.assertTrue(system.requests.outcomes["R1"].success)
        return seen

    async def test_the_failed_review_gets_time_for_the_fix_and_the_recheck(self):
        first, second = await self.run_request()
        self.assertIn("This review did not pass", first["note"])
        self.assertIn("The request's time was extended: about 120 s are left", first["note"])
        self.assertTrue(second["ok"])
        self.assertEqual(second["summary"], "PASS on items 1 and 2")           # the re-check ran

    async def test_without_the_reserve_the_recheck_is_refused_for_lack_of_time(self):
        first, second = await self.run_request(review_reserve_s=0.0)
        self.assertIn("No extra time can be added now (about 59 s are left)", first["note"])
        self.assertFalse(second["ok"])
        self.assertIn("Not enough time left", second["output"])


if __name__ == "__main__":
    unittest.main()
