"""The evaluation harness: records, summary, report, the simulated human and the grader."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mas.agents.base import Agent
from mas.config import Settings
from mas.core.human import HitlKind, HitlRequest
from mas.core.lead import CHOOSE_LEAD
from mas.core.task import FailureMode, Task, TaskResult
from mas.eval.harness import EvalRecord, render_report, run_scenario, run_suite, save_results, summarize
from mas.eval.judge import judge_task, parse_verdict, read_deliverables
from mas.eval.simulated_human import FALLBACK_ANSWER, SimulatedHuman
from mas.llm.base import LLMError, LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.scenario import load_scenario
from tests.test_app import ROOT
from tests.test_scenario import make_scenario


def rec(**kw) -> EvalRecord:
    base = dict(scenario="s1", run=1, task_index=1, task_file="02_task_1.md", title="t", completed=True,
                subtask_total=2, subtask_done=2, duration=10.0, lead="boss")
    return EvalRecord(**{**base, **kw})


class SummaryTest(unittest.TestCase):
    def test_rates_times_and_failure_modes(self):
        records = [rec(duration=10), rec(task_index=2, duration=30, subtask_done=1),
                   rec(scenario="s2", completed=False, failure_mode="timeout", duration=60, subtask_total=3,
                       subtask_done=0),
                   rec(scenario="s2", task_index=2, completed=False, failure_mode="no_result", duration=0,
                       subtask_total=0, subtask_done=0)]
        s = summarize(records)
        o = s["overall"]
        self.assertEqual((o["requests"], o["completed"], o["completion_rate"]), (4, 2, 0.5))
        self.assertEqual((o["subtasks"], o["subtasks_done"], o["subtask_completion_rate"]), (7, 3, 0.4286))
        self.assertEqual(o["duration_s"], {"mean": 33.33, "median": 30, "max": 60})     # a request with no result has no time
        self.assertEqual(s["failure_modes"], {"timeout": 1, "no_result": 1})
        self.assertEqual(s["by_scenario"]["s1"]["completion_rate"], 1.0)
        self.assertEqual(s["by_scenario"]["s2"]["completion_rate"], 0.0)
        self.assertEqual(list(s["by_run"]), [1])

    def test_grades_and_an_empty_list(self):
        records = [rec(judged=True, score=8), rec(task_index=2, judged=False, score=4), rec(task_index=3)]
        o = summarize(records)["overall"]
        self.assertEqual((o["judged"], o["judged_passed"], o["judged_pass_rate"], o["mean_score"]), (2, 1, 0.5, 6.0))
        empty = summarize([])["overall"]
        self.assertEqual((empty["requests"], empty["completion_rate"], empty["mean_score"]), (0, 0.0, None))

    def test_runs_are_compared(self):
        records = [rec(run=1, completed=False, failure_mode="max_steps", judged=False, score=3),
                   rec(run=2, judged=True, score=8)]
        s = summarize(records)
        self.assertEqual([s["by_run"][1]["completed"], s["by_run"][2]["completed"]], [0, 1])
        report = render_report(records)
        self.assertIn("By run", report)

    def test_the_report_says_what_it_found(self):
        records = [rec(), rec(task_index=2, completed=False, failure_mode="timeout", duration=61.5, judge_notes="no file")]
        report = render_report(records, title="My run", info={"model provider": "deepseek"})
        for piece in ("# My run", "model provider: deepseek", "Requests: **1/2 completed (50%)**", "Failure modes: timeout 1",
                      "| s1 | 1 | 2. t | boss | FAILED | timeout | 61.5 |", "no file"):
            self.assertIn(piece, report)


class Member(Agent):
    """A team member that only pretends: the lead asks a question and delegates, others write a file."""
    mode = "ok"

    async def handle_task(self, task: Task) -> TaskResult:
        if self.agent_id == "boss" and task.parent_id is None:
            if self.mode == "hang":
                await asyncio.sleep(30)
            if self.mode == "fail":
                return TaskResult(task.id, False, "gave up", error="no luck", failure_mode=FailureMode.WRONG_OUTPUT)
            await self.ask_human(task, "How big?", HitlKind.CLARIFY)
            helped = await self.call_agent(task, "worker", f"help with: {task.goal}")
            return TaskResult(task.id, helped.success, f"Done '{task.goal}'")
        self.router.sandboxes[self.agent_id].write_text(f"{task.id}.md", f"notes for {task.goal}")
        return TaskResult(task.id, True, "helped", artifacts=[f"{task.id}.md"])


class RunScenarioTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.scenario = load_scenario(make_scenario(self.tmp))
        self.settings = Settings(subtask_timeout_s=5.0, lead_timeout_s=10.0)
        self.llm = MockLLM(responder=lambda m, t: LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "boss"})]))

    def options(self, mode="ok"):
        Member.mode = mode
        self.addCleanup(setattr, Member, "mode", "ok")
        return dict(worker_factory=lambda role, parts: Member(role.agent_id, parts.bus, parts.router, parts.settings))

    async def test_one_record_per_task_with_what_the_code_measured(self):
        records = await run_scenario(self.scenario, self.settings, self.llm, out_dir=self.tmp / "out",
                                     timeout=20, **self.options())
        self.assertEqual([(r.task_index, r.completed, r.lead, r.subtask_total, r.subtask_done, r.hitl_count)
                          for r in records], [(1, True, "boss", 1, 1, 1), (2, True, "boss", 1, 1, 1)])
        for r in records:
            self.assertGreaterEqual(r.duration, 0)
            self.assertEqual((r.scenario, r.run, r.failure_mode), ("scenario_x 2", 1, None))
            self.assertEqual(len(r.deliverables), 1)
            self.assertTrue((Path(r.output_dir) / r.deliverables[0]).exists())
        self.assertIn("Done 'Do the first thing.'", records[0].summary)
        self.assertTrue(list((self.tmp / "out" / "scenario_x 2" / "run1" / "data" / "transcripts").glob("*.md")))

    async def test_a_failed_request_is_recorded_with_its_failure_mode(self):
        records = await run_scenario(self.scenario, self.settings, self.llm, out_dir=self.tmp / "out",
                                     timeout=20, **self.options("fail"))
        self.assertEqual([(r.completed, r.failure_mode, r.subtask_total) for r in records],
                         [(False, "wrong_output", 0)] * 2)
        self.assertEqual(summarize(records)["failure_modes"], {"wrong_output": 2})

    async def test_a_scenario_that_does_not_finish_in_time_is_a_failure_not_a_hang(self):
        records = await run_scenario(self.scenario, self.settings, self.llm, out_dir=self.tmp / "out",
                                     timeout=1.0, **self.options("hang"))
        self.assertEqual([(r.completed, r.failure_mode) for r in records],
                         [(False, "timeout"), (False, "no_result")])      # the first was cut short, the second never began
        self.assertIn("did not finish within 1s", records[0].notes[0])
        self.assertIn("did not finish within 1s", records[1].notes[0])

    async def test_a_suite_runs_every_scenario_and_run_and_saves_the_results(self):
        records = await run_suite([self.scenario], self.settings, self.llm, out_dir=self.tmp / "out", repeat=2,
                                  timeout=20, **self.options())
        self.assertEqual([(r.run, r.task_index) for r in records], [(1, 1), (1, 2), (2, 1), (2, 2)])
        data, report = save_results(records, self.tmp / "out", info={"x": 1})
        saved = json.loads(data.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["records"]), 4)
        self.assertEqual(saved["summary"]["overall"]["completion_rate"], 1.0)
        self.assertIn("Requests: **4/4 completed (100%)**", report.read_text(encoding="utf-8"))

    async def test_memory_is_shared_between_runs_only_when_asked(self):
        from mas.agents.roles import RoleConfig
        from mas.scenario import Scenario, ScenarioTask
        team = {"dev": RoleConfig("dev", "Developer", "Writes code.", "You are the developer.", [])}
        scenario = Scenario("solo", team, [ScenarioTask("02_task_1.md", "Build", "Build a booking system")])
        prompts: list[dict] = []

        def brain(messages, tools):
            prompts.append(json.loads(messages[1]["content"]))
            return LLMResponse(json.dumps({"success": True, "summary": "built it"}))
        for keep in (False, True):
            prompts.clear()
            await run_suite([scenario], self.settings, MockLLM(responder=brain), out_dir=self.tmp / f"out{keep}",
                            repeat=2, keep_memory=keep, timeout=20)
            self.assertEqual(prompts[0]["past_experiences"], [])
            self.assertEqual(len(prompts[1]["past_experiences"]), 1 if keep else 0)


class SimulatedHumanTest(unittest.IsolatedAsyncioTestCase):
    def req(self, kind=HitlKind.CLARIFY, question="How much risk can you take?", options=None):
        return HitlRequest("h1", "risk", "t1", "group:main", kind, question, options or [], "R1")

    async def test_clarifying_questions_are_answered_by_the_llm_with_the_request_and_history(self):
        llm = MockLLM(script=[LLMResponse("  Moderate,  I can lose 20%.\n"), LLMResponse("Ten years.")])
        human = SimulatedHuman(llm)
        human.set_request("I am 25 and have HKD 1,000,000")
        self.assertEqual(await human.answer(self.req()), "Moderate, I can lose 20%.")
        self.assertEqual(await human.answer(self.req(question="How long?", options=["5 years", "10 years"])), "Ten years.")
        first, second = (c[0][1]["content"] for c in llm.calls)
        self.assertIn("I am 25 and have HKD 1,000,000", first)
        self.assertIn("Q: How much risk can you take?\nA: Moderate, I can lose 20%.", second)
        self.assertIn("Options: 5 years / 10 years", second)
        self.assertEqual((human.hitl_count, human.llm_calls), (2, 2))

    async def test_approvals_and_advice_need_no_model(self):
        llm = MockLLM()
        human = SimulatedHuman(llm)
        self.assertEqual(await human.answer(self.req(HitlKind.APPROVAL, "git push?")), "yes")
        self.assertIn("simpler approach", await human.answer(self.req(HitlKind.ADVICE, "it failed twice")))
        self.assertEqual(llm.calls, [])

    async def test_a_failing_model_falls_back_to_the_default(self):
        def broken(messages, tools):
            raise LLMError("down")
        human = SimulatedHuman(MockLLM(responder=broken))
        self.assertEqual(await human.answer(self.req()), FALLBACK_ANSWER)
        self.assertEqual(await SimulatedHuman(MockLLM(script=[LLMResponse("")])).answer(self.req()), FALLBACK_ANSWER)


class JudgeTest(unittest.IsolatedAsyncioTestCase):
    def test_a_verdict_is_found_in_fenced_or_wrapped_text(self):
        v = parse_verdict('Here you go:\n```json\n{"requirements": [{"item": "HTML slides", "met": true}], '
                          '"passed": true, "score": 8, "notes": "good"}\n```')
        self.assertEqual((v.passed, v.score, v.notes, v.requirements), (True, 8, "good", [{"item": "HTML slides", "met": True}]))
        v = parse_verdict('{"passed": false, "score": 99, "notes": "x"}')
        self.assertEqual((v.passed, v.score), (False, None))                         # an impossible score is dropped
        for text in ("no json here", '{"passed": "yes"}', "{broken"):
            self.assertEqual((parse_verdict(text).passed, parse_verdict(text).score), (None, None))

    def test_deliverables_are_read_clipped_and_binary_files_are_only_named(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "a.md").write_text("hello")
        (tmp / "big.txt").write_text("x" * 20000)
        (tmp / "pic.png").write_bytes(b"\x89PNG")
        got = read_deliverables(tmp)
        self.assertEqual(got["a.md"], "hello")
        self.assertTrue(got["big.txt"].endswith("…(cut)") and len(got["big.txt"]) < 8100)
        self.assertEqual(got["pic.png"], "(not a text file)")
        self.assertEqual(read_deliverables(""), {})
        self.assertEqual(read_deliverables(tmp / "missing"), {})

    async def test_the_grader_sees_the_request_the_dialogue_and_the_files(self):
        llm = MockLLM(script=[LLMResponse('{"passed": true, "score": 7, "notes": "ok"}')])
        v = await judge_task(llm, "Make slides", "lead: done", {"deck.html": "<h1>x</h1>"})
        self.assertEqual((v.passed, v.score), (True, 7))
        prompt = llm.calls[0][0][1]["content"]
        for piece in ("Make slides", "lead: done", "### deck.html", "<h1>x</h1>"):
            self.assertIn(piece, prompt)

    async def test_a_failing_grader_gives_no_verdict_instead_of_an_error(self):
        def broken(messages, tools):
            raise LLMError("down")
        v = await judge_task(MockLLM(responder=broken), "r", "d", {})
        self.assertEqual((v.passed, v.score), (None, None))


class CommandLineTest(unittest.TestCase):
    def test_a_bad_scenario_folder_says_why(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), HKGAI_API_KEY="", DEEPSEEK_API_KEY="", LLM_PROVIDER="")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = subprocess.run([sys.executable, "-m", "mas.eval", str(Path(tmp) / "nope")], capture_output=True, text=True,
                           cwd=tmp, env=env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("scenario folder not found", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()


class TimingTest(unittest.IsolatedAsyncioTestCase):
    """Where a request's time went is measured by the workers and reported by the harness."""

    async def test_a_worker_reports_where_its_time_went(self):
        import json as _json

        from mas.agents.roles import RoleConfig
        from mas.agents.worker import WorkerAgent
        from mas.app import build_system
        from mas.core.human import AutoResponder
        from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
        from mas.tools.base import Tool, ToolResult

        class Slow(Tool):
            name, description = "slow_tool", "waits a little"
            parameters = {"type": "object", "properties": {}, "additionalProperties": False}

            async def run(self, sandbox, **kw):
                await asyncio.sleep(0.15)
                return ToolResult(True, "ok")

        calls = []

        def brain(messages, tools):
            calls.append(1)
            if len(calls) <= 2:
                return LLMResponse("", [ToolCall(f"c{len(calls)}", "slow_tool", {})])
            return LLMResponse(_json.dumps({"success": True, "summary": "done"}))
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        team = {"dev": RoleConfig("dev", "Developer", "Writes code.", "You are the developer.", [])}
        settings = Settings(data_dir=tmp / "data", workspaces_dir=tmp / "ws", subtask_timeout_s=5, lead_timeout_s=10)
        system = build_system(settings, MockLLM(responder=brain), AutoResponder(), roles=team,
                              worker_factory=lambda role, parts: WorkerAgent(
                                  role, parts.bus, parts.router, parts.settings, parts.llm, [Slow()],
                                  parts.sandbox, parts.memory, peers=parts.peers))
        system.start()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "do it"))
            for _ in range(300):
                if system.requests.outcomes:
                    break
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.05)
        finally:
            await system.stop()
        [task] = system.state.by_root("R1")
        m = system.state.result(task.id).metrics
        self.assertEqual((m["llm_calls"], m["by_tool"]["slow_tool"]["calls"]), (3, 2))
        self.assertGreaterEqual(m["tool_s"], 0.3)
        self.assertGreaterEqual(m["by_tool"]["slow_tool"]["s"], 0.3)
        self.assertEqual((m["delegation_s"], m["human_s"]), (0.0, 0.0))

    def test_the_report_shows_the_time_composition(self):
        r = rec(timing={"lead": {"llm_s": 100.0, "tool_s": 20.0, "delegation_s": 300.0, "human_s": 5.0, "other_s": 1.0},
                        "team": {"llm_s": 400.0, "llm_calls": 60, "tool_s": 250.0,
                                 "by_tool": {"web_search": {"calls": 30, "s": 180.0}}}}, duration=426.0)
        report = render_report([r])
        self.assertIn("## Where the time went", report)
        self.assertIn("| s1 | 1 | 1 | 426 | 100 | 20 | 300 | 5 | 60 | 400 | 250 | 30 | 180 |", report)
        self.assertNotIn("Where the time went", render_report([rec()]))                   # nothing measured: no section

    async def test_the_harness_puts_the_lead_and_team_times_in_the_record(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        scenario = load_scenario(make_scenario(tmp))
        llm = MockLLM(responder=lambda m, t: LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "boss"})]))

        class Timed(Member):
            async def handle_task(self, task):
                result = await super().handle_task(task)
                result.metrics = {"llm_s": 2.0, "llm_calls": 3, "tool_s": 1.0, "delegation_s": 4.0 if task.parent_id is None else 0.0,
                                  "human_s": 0.5 if task.parent_id is None else 0.0,
                                  "by_tool": {"web_search": {"calls": 2, "s": 1.0}}}
                return result
        records = await run_scenario(scenario, Settings(subtask_timeout_s=5.0, lead_timeout_s=10.0), llm, out_dir=tmp / "out",
                                     timeout=20, worker_factory=lambda role, parts: Timed(
                                         role.agent_id, parts.bus, parts.router, parts.settings))
        t = records[0].timing
        self.assertEqual((t["lead"]["llm_s"], t["lead"]["delegation_s"], t["lead"]["human_s"]), (2.0, 4.0, 0.5))
        self.assertEqual((t["team"]["llm_calls"], t["team"]["llm_s"], t["team"]["by_tool"]["web_search"]),
                         (6, 4.0, {"calls": 4, "s": 2.0}))                    # the lead and its one teammate
