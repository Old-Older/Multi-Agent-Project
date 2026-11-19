"""The request's requirements (listed, passed on, checked by the lead) and the limit on review rounds."""
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
from mas.agents.worker import WorkerAgent, _Run
from mas.app import build_system
from mas.config import Settings
from mas.core.human import AutoResponder
from mas.core.lead import CHOOSE_LEAD
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.task import Task, TaskResult
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from tests.test_budget import BudgetCase
from tests.test_worker import call, final, prompt_text


def reqs(*items):
    """The model's answer to 'what does this request require?'."""
    return LLMResponse(json.dumps(list(items)))


def met(*ids, status="met"):
    return [{"id": i, "status": status, "evidence": f"checked {i}"} for i in ids]


class ParsingTest(unittest.TestCase):
    parse = staticmethod(WorkerAgent._parse_requirement_list)

    def test_a_list_in_whatever_wrapping_the_model_chose(self):
        for text in ('["a", "b"]', '```json\n["a", "b"]\n```', 'Here is the list: ["a", "b"] — done.'):
            self.assertEqual(self.parse(text, 12), ["a", "b"], text)

    def test_what_is_not_a_list_gives_none(self):
        for text in ("", "no requirements", '{"a": 1}', "[1, 2]", "[]", '["", "  "]'):
            self.assertEqual(self.parse(text, 12), [], text)

    def test_duplicates_are_dropped_whitespace_is_tidied_and_the_list_is_capped(self):
        self.assertEqual(self.parse('["a  b", "a b", "c"]', 12), ["a b", "c"])
        self.assertEqual(self.parse(json.dumps([f"r{n}" for n in range(30)]), 5), ["r0", "r1", "r2", "r3", "r4"])

    def test_the_leads_report_is_read_leniently(self):
        got = WorkerAgent._parse_reported_requirements([
            {"id": "req1", "status": "Met", "evidence": "ok"},
            {"id": 2, "status": "not met"},
            {"id": "REQ3", "status": "partial"},
            {"id": "REQ4", "status": "maybe"},                 # not a status: left out
            {"status": "met"}, "REQ5: met", {"id": "REQ6", "status": "unverified", "evidence": "x " * 400},
        ])
        self.assertEqual([(e["id"], e["status"]) for e in got],
                         [("REQ1", "met"), ("2", "not_met"), ("REQ3", "not_met"), ("REQ6", "unverified")])
        self.assertEqual(len(got[-1]["evidence"]), 300)
        self.assertEqual(WorkerAgent._parse_reported_requirements(None), [])
        self.assertEqual(WorkerAgent._parse_reported_requirements({"id": "REQ1"}), [])


class RequirementsCheckTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.settings.requirements_check = True
        self.settings.request_budget_s = 0.0

    async def lead(self, script, **limits):
        for key, value in limits.items():
            setattr(self.settings, key, value)
        task = self.task()
        worker, llm = self.member(script, lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        return task, result, llm

    async def test_the_requirements_are_listed_first_and_given_to_the_lead(self):
        task, result, llm = await self.lead([reqs("two slides", "in Chinese"),
                                             final(requirements=met("REQ1", "REQ2"))])
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("You list what a request explicitly requires", llm.calls[0][0][0]["content"])
        self.assertEqual(llm.calls[0][1], [])                                   # a plain question: no tools
        start = json.loads([m for m in llm.calls[1][0] if m["role"] == "user"][0]["content"])
        self.assertEqual(start["requirements"], {"REQ1": "two slides", "REQ2": "in Chinese"})
        self.assertEqual(self.router.requirements(task.root_id), ["two slides", "in Chinese"])
        self.assertEqual(result.summary, "done")                                # all met: nothing added to the reply
        self.assertEqual([e["status"] for e in result.requirements], ["met", "met"])

    async def test_a_lead_that_did_not_report_them_is_sent_back_once_to_check_the_files(self):
        _, result, llm = await self.lead([reqs("a", "b"), final(), final(requirements=met("REQ1", "REQ2"))])
        self.assertEqual(len(llm.calls), 3)
        asked = prompt_text(llm.calls[2][0])
        self.assertIn("Requirements check. You did not report the status of REQ1, REQ2.", asked)
        self.assertIn("REQ1: a", asked)
        self.assertIn("count with run_python", asked)
        self.assertEqual(len(result.requirements), 2)

    async def test_what_stays_unmet_after_two_rounds_is_shown_to_the_human(self):
        not_met = final(requirements=[*met("REQ2"), {"id": "REQ1", "status": "not_met", "evidence": "226 words"}])
        _, result, llm = await self.lead([reqs("a social post of 120 to 180 words", "b"), not_met, not_met, not_met])
        self.assertEqual(len(llm.calls), 4)                                     # list, answer, two pushes
        self.assertIn("You reported REQ1 as not met.", prompt_text(llm.calls[2][0]))
        self.assertTrue(result.success)
        self.assertIn("Requirements not met or not verified:", result.summary)
        self.assertIn("- REQ1 (a social post of 120 to 180 words): not met. 226 words", result.summary)
        self.assertNotIn("REQ2", result.summary.split("Requirements not met")[1])
        self.assertEqual(result.open_issues, ["- REQ1 (a social post of 120 to 180 words): not met. 226 words"])

    async def test_a_target_the_lead_set_itself_is_reported_too(self):
        own = {"id": "own1", "status": "not_met", "requirement": "social post of 120 to 180 words", "evidence": "226 words"}
        _, result, llm = await self.lead([reqs("a"), final(requirements=[*met("REQ1"), own])])
        self.assertEqual(len(llm.calls), 2)                                    # not a reason to send it back
        self.assertIn("- OWN1 (social post of 120 to 180 words): not met. 226 words", result.summary)
        ignored = {"id": "OWN2", "status": "not_met", "evidence": "no text"}   # nothing to say what it was: left out
        _, result, _ = await self.lead([reqs("a"), final(requirements=[*met("REQ1"), ignored])])
        self.assertNotIn("OWN2", result.summary)

    async def test_unverified_is_accepted_but_shown(self):
        _, result, llm = await self.lead([reqs("a"), final(requirements=met("REQ1", status="unverified"))])
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("REQ1 (a): not verified. checked REQ1", result.summary)

    async def test_nothing_to_check_when_nothing_was_listed_or_it_is_switched_off(self):
        _, result, llm = await self.lead([LLMResponse("no idea"), final()])
        self.assertEqual(len(llm.calls), 2)                                     # the question, the answer
        self.assertNotIn("requirements", json.loads([m for m in llm.calls[1][0] if m["role"] == "user"][0]["content"]))

        _, result, llm = await self.lead([final()], requirements_check=False)
        self.assertEqual(len(llm.calls), 1)

    async def test_a_failing_model_call_for_the_list_does_not_stop_the_request(self):
        task = self.task()
        worker, llm = self.member([final()], lead=True)

        async def failing(messages, tools=None, temperature=0.2):
            if "You list what a request explicitly requires" in messages[0]["content"]:
                raise RuntimeError("boom")
            return LLMResponse(json.dumps({"success": True, "summary": "done"}))
        worker.llm.chat = failing
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertTrue(result.success)

    async def test_no_push_for_a_final_answer_on_the_last_steps_or_when_time_is_out(self):
        _, result, llm = await self.lead([reqs("a"), final()], max_lead_steps=2)    # the answer is on step 1 of 2
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(result.success)

        self.settings.max_lead_steps = 60
        self.settings.request_budget_s = 100.0
        task = self.task()
        self.now[0] = 80.0                                                          # 20 s left, under the wrap-up time
        worker, llm = self.member([reqs("a"), final()], lead=True)
        await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(llm.calls), 2)

    async def test_what_the_human_answered_can_add_requirements(self):
        task = self.task()
        self.router.set_requirements(task.root_id, ["a"])
        worker, llm = self.member([reqs("a", "for students")], lead=True)
        run = _Run(deadline=time.perf_counter() + 30)
        run.human_qa = [("Who is it for?", "students")]
        parsed = TaskResult(task.id, True, "done", requirements=met("REQ1"))
        pushed = await worker._requirements_push(task, run, parsed, 10)
        self.assertIn("The human also said", llm.calls[0][0][1]["content"])
        self.assertIn("Who is it for? -> students", llm.calls[0][0][1]["content"])
        self.assertIn("You did not report the status of REQ2.", pushed)
        self.assertEqual(self.router.requirements(task.root_id), ["a", "for students"])

    async def test_the_reply_to_the_human_is_not_cut_short_but_a_teammates_report_is(self):
        long = "x" * 4000
        _, result, _ = await self.lead([reqs(), final(summary=long)])
        self.assertEqual(len(result.summary), 4000)
        self.settings.requirements_check = False
        task = self.task()
        worker, _ = self.member([final(summary=long)], lead=False)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(len(result.summary), self.settings.result_summary_max_chars)


class Recorder(Agent):
    """A teammate that records what it was told and answers at once."""

    def __init__(self, *args, log, **kw):
        super().__init__(*args, **kw)
        self.log = log

    async def handle_task(self, task: Task) -> TaskResult:
        self.log.append((task.goal, task.context))
        return TaskResult(task.id, True, "PASS: nothing to fix")


class WithTeammatesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    async def run_request(self, steps, **settings):
        """The lead's `steps` ((tool name, arguments) pairs, one per reply), then it answers. Returns what it saw."""
        log, seen = [], []

        def brain(messages, tools):
            system = messages[0]["content"]
            if "You assign the lead" in system:
                return LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "lead"})])
            if "You list what a request explicitly requires" in system:
                return reqs("at most 150 words", "mention the date")
            tool_messages = [m for m in messages if m["role"] == "tool"]
            if len(tool_messages) < len(steps):
                name, args = steps[len(tool_messages)]
                return LLMResponse("", [ToolCall(f"c{len(tool_messages)}", name, args)])
            seen.extend(json.loads(m["content"]) for m in tool_messages)
            return LLMResponse(json.dumps({"success": True, "summary": "done", "requirements": met("REQ1", "REQ2")}))

        def factory(role, parts):
            if role.agent_id == "lead":
                parts.sandbox.write_text("deck.html", "<html>v1</html>")
                return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm, [], parts.sandbox,
                                   parts.memory, peers=parts.peers)
            return Recorder(role.agent_id, parts.bus, parts.router, parts.settings, log=log)

        team = {n: RoleConfig(n, n.title(), f"{n} works.", f"You are {n}.", []) for n in ("lead", "mate")}
        defaults = dict(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=10,
                        lead_timeout_s=20, closing_check=False)
        system = build_system(Settings(**{**defaults, **settings}), MockLLM(responder=brain), AutoResponder(),
                              roles=team, worker_factory=factory)
        system.start()
        started = time.monotonic()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "do it"))
            while not system.requests.outcomes and time.monotonic() - started < 10:
                await asyncio.sleep(0.01)
        finally:
            await system.stop()
        self.assertTrue(system.requests.outcomes["R1"].success)
        return log, seen

    async def test_every_teammate_is_told_the_requirements_of_the_whole_request(self):
        log, _ = await self.run_request([("call_mate", {"goal": "Write the note", "context": "for the staff"})])
        goal, context = log[0]
        self.assertTrue(context.startswith("for the staff\n"))
        self.assertIn("Requirements of the whole request (meet those that concern your part", context)
        self.assertIn("REQ1: at most 150 words REQ2: mention the date", context)

    async def test_nothing_is_added_when_the_check_is_off(self):
        log, _ = await self.run_request([("call_mate", {"goal": "Write the note", "context": "for the staff"})],
                                        requirements_check=False)
        self.assertEqual(log[0][1], "for the staff")

    async def test_a_second_review_of_the_same_file_is_told_to_batch_and_a_fourth_is_refused(self):
        review = lambda goal: ("call_mate", {"goal": goal, "files": ["deck.html"]})       # noqa: E731
        log, seen = await self.run_request([
            review("Review the deck"), review("Re-check the deck"), review("Check the deck again"),
            review("Confirm the deck once more")], requirements_check=False)
        self.assertEqual(len(log), 3)                                          # the fourth never reached the teammate
        self.assertNotIn("note", seen[0])
        self.assertIn("This was review round 2 of mate on the same file (at most 3)", seen[1]["note"])
        self.assertIn("round 3", seen[2]["note"])
        self.assertFalse(seen[3]["ok"])
        self.assertIn("already been asked 3 times in this request to review the same file (at most 3)", seen[3]["output"])

    async def test_the_limit_can_be_lifted_and_other_files_or_work_are_not_counted(self):
        write = lambda n: ("call_mate", {"goal": f"Write part {n}", "files": ["deck.html"]})    # noqa: E731
        log, seen = await self.run_request([write(1), write(2), write(3), write(4)], requirements_check=False)
        self.assertEqual(len(log), 4)                                          # not reviews: no limit
        log, seen = await self.run_request(
            [("call_mate", {"goal": f"Review the deck {n}", "files": ["deck.html"]}) for n in range(5)],
            requirements_check=False, max_review_rounds=0)
        self.assertEqual(len(log), 5)                                          # 0: no limit


class ReviewRoundsCountTest(unittest.TestCase):
    def setUp(self):
        from mas.core.bus import InMemoryBus
        from mas.core.state import StateTable
        self.state = StateTable()
        self.router = Router(InMemoryBus(), self.state, {}, Settings())

    def asked(self, assignee, goal, files, root="R1", error=None):
        task = Task(goal, assignee, "lead", GROUP_MAIN, root, GROUP_MAIN, chain=[HUMAN, "lead"])
        self.state.register(task)
        self.state.finish(TaskResult(task.id, error is None, "x", error=error))
        self.router._handed[task.id] = {f: (Path(f), None) for f in files}

    def test_the_same_reviewer_and_the_same_file_are_counted(self):
        self.asked("risk", "Review the deck", ["deck.html"])
        self.asked("risk", "Final consistency check on the deck", ["inbox/deck.html", "brief.md"])
        self.asked("marketing", "Review the deck", ["deck.html"])               # another reviewer
        self.asked("risk", "Write a risk memo", ["deck.html"])                  # not a review
        self.asked("risk", "Review the deck", ["deck.html"], root="R2")         # another request
        self.asked("risk", "Review the memo", ["memo.md"])                      # another file
        self.assertEqual(self.router.review_rounds("R1", "risk", ["deck.html"]), 2)
        self.assertEqual(self.router.review_rounds("R1", "risk", ["memo.md"]), 1)
        self.assertEqual(self.router.review_rounds("R1", "risk", ["deck.html", "memo.md"]), 2)
        self.assertEqual(self.router.review_rounds("R1", "risk", []), 0)

    def test_a_refused_review_does_not_count(self):
        self.asked("risk", "Review the deck", ["deck.html"], error="refused: unknown agent")
        self.assertEqual(self.router.review_rounds("R1", "risk", ["deck.html"]), 0)

    def test_what_counts_as_asking_for_a_review(self):
        for goal in ("Review the deck", "Re-check items 1 and 2", "Final consistency check on the files",
                     "Please verify the numbers", "Fact-check the claim", "Sign-off on the revised proposal",
                     "Re-run the consistency check on the UPDATED file"):
            self.assertTrue(Router.is_review_request(goal), goal)
        for goal in ("Write a one-page memo", "Produce a brief; check the sources as you go", "Draft the intro",
                     "Update the deck to match the review", "Write a short review of the film",
                     "Draft a checklist for the release"):
            self.assertFalse(Router.is_review_request(goal), goal)


from mas.core.router import Router  # noqa: E402  (used by the tests above)

if __name__ == "__main__":
    unittest.main()
