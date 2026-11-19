"""What a lead's steps were spent on is counted, so that a request that uses all its steps can be understood."""
from __future__ import annotations

import asyncio
import json

from mas.core.task import Task, TaskResult
from mas.core.message import GROUP_MAIN, HUMAN
from mas.eval.harness import EvalRecord, render_report
from tests.test_budget import BudgetCase
from tests.test_requirements import met, reqs
from tests.test_worker import ScriptedTool, call, final
from mas.llm.base import LLMResponse


class StepKindsTest(BudgetCase):
    async def lead(self, script, tools=(), now=None, **settings):
        for key, value in settings.items():
            setattr(self.settings, key, value)
        task = self.task()
        if now is not None:
            self.now[0] = now                                                  # after the clock started, at 0
        worker, _ = self.member(script, list(tools), lead=True)
        return task, await asyncio.wait_for(worker.handle_task(task), 3)

    def kinds(self, result):
        kinds = result.metrics["steps_by_kind"]
        self.assertEqual(sum(kinds.values()), result.steps, kinds)           # every step is counted exactly once
        return kinds

    async def test_tool_steps_and_the_accepted_answer(self):
        _, result = await self.lead([call("write_file", "c1", value="a"), call("write_file", "c2", value="b"), final()],
                                    [ScriptedTool("write_file")])
        self.assertEqual(self.kinds(result), {"tools": 2, "final": 1})

    async def test_a_delegation_step(self):
        # 30 s of 100 left: the call is refused, but it was a step
        _, result = await self.lead([call("call_mate", "c1", goal="review it"), final()], now=70.0, finish_not_before=0.0)
        self.assertEqual(self.kinds(result), {"delegate": 1, "final": 1})

    async def test_each_kind_of_push_is_counted_where_it_was_made(self):
        self.settings.closing_check = True
        self.settings.request_budget_s = 0.0                                    # no time budget: only the closing check
        task = self.task()
        mate = Task("Review the deck", "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN, chain=[HUMAN, "worker"],
                    parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, "FAIL: six errors"))
        worker, _ = self.member([final(), final(), final()], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(self.kinds(result), {"push_closing": 2, "final": 1})   # the check asks twice while a review is open

        self.settings.closing_check = False
        self.settings.requirements_check = True
        _, result = await self.lead([reqs("a"), final(), final(requirements=met("REQ1"))])
        self.assertEqual(self.kinds(result), {"push_requirements": 1, "final": 1})

        self.settings.requirements_check = False
        self.settings.closing_check = True
        self.settings.review_final = True
        _, result = await self.lead([final(artifacts=["deck.html"]), final(artifacts=["deck.html"]),
                                     final(artifacts=["deck.html"])])
        self.assertEqual(self.kinds(result), {"push_review": 2, "final": 1})

        self.settings.review_final = False
        self.settings.request_budget_s = 100.0
        self.settings.finish_not_before = 0.5
        task = self.task()
        mate = Task("Write it", "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN, chain=[HUMAN, "worker"],
                    parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, "done"))
        worker, _ = self.member([final(), final(), final()], lead=True)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(self.kinds(result), {"push_early": 2, "final": 1})

    async def test_an_answer_that_is_not_the_result_json_is_a_format_error_step(self):
        _, result = await self.lead([LLMResponse("not json at all"), final()])
        self.assertEqual(self.kinds(result), {"format_error": 1, "final": 1})

    async def test_a_worker_that_is_not_a_lead_counts_too(self):
        task = self.task()
        worker, _ = self.member([call("write_file", "c1", value="a"), final()], [ScriptedTool("write_file")], lead=False)
        result = await asyncio.wait_for(worker.handle_task(task), 3)
        self.assertEqual(self.kinds(result), {"tools": 1, "final": 1})


class ReportTest(BudgetCase):
    def test_the_report_lists_where_the_leads_steps_went_and_its_own_tools(self):
        record = EvalRecord(scenario="s1", run=1, task_index=1, task_file="02_task_1.md", title="t", completed=True,
                            subtask_total=2, subtask_done=2, duration=10.0, lead="boss", lead_steps=21,
                            timing={"lead": {"llm_s": 5.0}, "team": {"llm_calls": 3, "by_tool": {}},
                                    "lead_steps": {"delegate": 4, "tools": 12, "push_requirements": 2, "final": 3},
                                    "lead_tools": {"read_file": 9, "run_python": 3}})
        report = render_report([record])
        self.assertIn("## Where the lead's steps went", report)
        self.assertIn("| s1 | 1 | 1 | 21 | 4 | 12 | 0 | 2 | 0 | 0 | 0 | 3 | read_file 9, run_python 3 |", report)
        bare = EvalRecord(scenario="s1", run=1, task_index=1, task_file="x", title="t", completed=True)
        self.assertNotIn("Where the lead's steps went", render_report([bare]))

    def test_the_timing_keeps_the_leads_steps_and_tools(self):
        from types import SimpleNamespace
        from mas.eval.harness import _timing
        lead_task = SimpleNamespace(id="t1", parent_id=None)
        mate_task = SimpleNamespace(id="t2", parent_id="t1")
        metrics = {"t1": {"llm_s": 1.0, "llm_calls": 5, "tool_s": 0.5, "steps_by_kind": {"tools": 3, "final": 1},
                          "by_tool": {"read_file": {"calls": 3, "s": 0.1}}},
                   "t2": {"llm_s": 2.0, "llm_calls": 4, "by_tool": {"web_search": {"calls": 2, "s": 1.0}}}}
        system = SimpleNamespace(state=SimpleNamespace(
            by_root=lambda root: [lead_task, mate_task], result=lambda tid: SimpleNamespace(metrics=metrics[tid])))
        timing = _timing(system, "R1", 10.0)
        self.assertEqual(timing["lead_steps"], {"tools": 3, "final": 1})
        self.assertEqual(timing["lead_tools"], {"read_file": 3})                    # the teammate's tools are not the lead's
        self.assertEqual(timing["team"]["by_tool"]["web_search"]["calls"], 2)
        json.dumps(timing)                                                           # it goes into results.json
