"""Before the lead's first delegations go out, every requirement must have a task that helps meet it."""
from __future__ import annotations

import asyncio
import json
import time

from mas.agents.worker import _Run
from mas.llm.base import LLMResponse, ToolCall
from tests.test_budget import BudgetCase
from tests.test_requirements import met, reqs
from tests.test_worker import final

TOPIC = "Consult the requester about the story."
SEND = lambda cid="c1", goal="research it": LLMResponse("", [ToolCall(cid, "call_mate", {"goal": goal})])  # noqa: E731


class CoverageGateTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.settings.requirements_check = True
        self.settings.finish_not_before = 0.0

    async def lead(self, script):
        task = self.task()
        self.now[0] = 70.0                       # a delegation that gets through is refused for time, which is enough here
        worker, llm = self.member(script, lead=True)
        return task, worker, await asyncio.wait_for(worker.handle_task(task), 3), llm

    def observations(self, llm):
        return [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]

    async def test_a_requirement_no_task_covers_holds_the_reply_back_once(self):
        _, _, result, llm = await self.lead([
            reqs("ten slides", "include quotes from students"), SEND(), LLMResponse('["REQ2"]'),
            SEND("c2", "research and write"), final(requirements=met("REQ1", "REQ2"))])
        held, passed = self.observations(llm)
        self.assertFalse(held["ok"])
        self.assertIn("No task in your reply helps meet REQ2", held["output"])
        self.assertIn("REQ2: include quotes from students", held["output"])
        self.assertIn("Not enough time left", passed["output"])                  # the next reply is not held back
        self.assertTrue(result.success)

    async def test_when_every_requirement_is_covered_nothing_is_held_back(self):
        _, _, _, llm = await self.lead([reqs("ten slides"), SEND(), LLMResponse("[]"), final(requirements=met("REQ1"))])
        self.assertIn("Not enough time left", self.observations(llm)[0]["output"])

    async def test_a_list_widened_by_the_humans_answer_is_shown_to_the_lead_once(self):
        task = self.task()
        worker, llm = self.member([reqs("ten slides, with student voices"), LLMResponse("[]")], lead=True)
        self.router.set_requirements(task.root_id, ["ten slides"])
        run = _Run(deadline=time.perf_counter() + 30)
        run.human_qa = [("Anything to add?", "student voices")]
        call = ToolCall("c1", "call_mate", {"goal": "research it"})
        held = await worker._coverage_gate(task, [call], run)
        self.assertIn("includes what the human answered", held)
        self.assertIn("REQ1: ten slides, with student voices", held)
        self.assertEqual(await worker._coverage_gate(task, [call], run), "")     # once

    async def test_the_check_is_skipped_for_a_teammate_with_the_switch_off_and_while_the_human_is_still_to_be_asked(self):
        task = self.task()
        worker, llm = self.member([LLMResponse('["REQ1"]')], lead=True)
        call = ToolCall("c1", "call_mate", {"goal": "x"})
        self.router.set_requirements(task.root_id, [TOPIC, "ten slides"])
        self.assertEqual(await worker._coverage_gate(task, [call], _Run(deadline=time.perf_counter() + 30)), "")
        self.assertEqual(len(llm.calls), 0)                                      # the consult gate comes first
        self.router.set_requirements(task.root_id, ["ten slides"])
        self.settings.coverage_check = False
        self.assertEqual(await worker._coverage_gate(task, [call], _Run(deadline=time.perf_counter() + 30)), "")
        self.assertEqual(len(llm.calls), 0)

    async def test_ids_the_judge_invents_are_ignored_and_a_failed_judge_holds_nothing(self):
        task = self.task()
        self.router.set_requirements(task.root_id, ["ten slides"])
        call = ToolCall("c1", "call_mate", {"goal": "x"})
        worker, _ = self.member([LLMResponse('["REQ9"]')], lead=True)
        self.assertEqual(await worker._uncovered_requirements(task, [call], _Run(deadline=time.perf_counter() + 30)), [])
        worker, _ = self.member([LLMResponse("no idea")], lead=True)
        self.assertEqual(await worker._uncovered_requirements(task, [call], _Run(deadline=time.perf_counter() + 30)), [])

    def trace(self):
        path = self.settings.data_dir / "tool_calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    async def test_the_decision_is_recorded_with_what_was_uncovered_and_whether_the_list_changed(self):
        task = self.task()
        worker, _ = self.member([LLMResponse('["REQ2"]')], lead=True)
        self.router.set_requirements(task.root_id, ["ten slides", "include quotes from students"])
        call = ToolCall("c1", "call_mate", {"goal": "research it"})
        held = await worker._coverage_gate(task, [call], _Run(deadline=time.perf_counter() + 30))
        (record,) = self.trace()
        self.assertEqual((record["tool"], record["ok"]), ("coverage_gate", False))
        self.assertEqual(record["arguments"]["uncovered"], ["REQ2"])
        self.assertFalse(record["arguments"]["list_changed"])
        self.assertEqual(record["arguments"]["requirements"]["REQ2"], "include quotes from students")
        self.assertEqual(record["result"], held)

    async def test_a_reply_that_goes_out_as_it_was_is_recorded_too(self):
        task = self.task()
        worker, _ = self.member([LLMResponse("[]")], lead=True)
        self.router.set_requirements(task.root_id, ["ten slides"])
        call = ToolCall("c1", "call_mate", {"goal": "write it"})
        self.assertEqual(await worker._coverage_gate(task, [call], _Run(deadline=time.perf_counter() + 30)), "")
        (record,) = self.trace()
        self.assertEqual((record["ok"], record["result"], record["arguments"]["uncovered"]), (True, "sent as it was", []))
