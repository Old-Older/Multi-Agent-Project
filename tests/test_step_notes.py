"""The status line of a step says which tools the member is about to use, not only the step number."""
from __future__ import annotations

import asyncio
import json
import unittest

from mas.agents.worker import WorkerAgent
from mas.core.message import MsgType
from mas.llm.base import LLMResponse, ToolCall
from tests import test_worker
from tests.test_worker import ScriptedTool, final


class Harness(unittest.IsolatedAsyncioTestCase):
    """The worker set-up of tests/test_worker.py, without inheriting (and so running again) its tests."""
    setUp = test_worker.WorkerTest.setUp
    asyncTearDown = test_worker.WorkerTest.asyncTearDown
    worker = test_worker.WorkerTest.worker
    task = test_worker.WorkerTest.task
    messages = test_worker.WorkerTest.messages


def calls(*specs):
    return LLMResponse("", [ToolCall(f"c{n}", name, args) for n, (name, args) in enumerate(specs)])


class DescribeTest(unittest.TestCase):
    describe = staticmethod(WorkerAgent._describe_calls)

    def test_a_file_tool_names_its_file_and_a_search_its_query(self):
        text = self.describe(4, [ToolCall("a", "edit_file", {"path": "report.md", "old": "x", "new": "y"}),
                                 ToolCall("b", "web_search", {"query": "HKUST AI policy"}),
                                 ToolCall("c", "fetch_url", {"url": "https://example.org/a"}),
                                 ToolCall("d", "run_python", {"path": "count.py", "args": ["-v"]})])
        self.assertEqual(text, "Step 4: edit_file report.md; web_search 'HKUST AI policy'; fetch_url https://example.org/a "
                               "(+1 more)")

    def test_a_delegation_names_the_teammate_and_starts_its_goal(self):
        text = self.describe(2, [ToolCall("a", "call_reporter", {"goal": "Find the most recent HKUST event " + "x" * 200})])
        self.assertTrue(text.startswith("Step 2: call_reporter 'Find the most recent HKUST event "), text)
        self.assertLessEqual(len(text), 160)

    def test_a_call_without_a_known_argument_is_just_its_name(self):
        self.assertEqual(self.describe(1, [ToolCall("a", "ask_human", {"question": "Which story?"})]),
                         "Step 1: ask_human 'Which story?'")
        self.assertEqual(self.describe(1, [ToolCall("a", "custom_tool", {})]), "Step 1: custom_tool")
        self.assertEqual(self.describe(1, [ToolCall("a", "edit_file", {}, "{broken", malformed=True)]), "Step 1: edit_file")


class StepNoteTest(Harness):
    async def test_the_note_of_a_step_with_tools_says_which(self):
        tool = ScriptedTool("write_file")
        worker, _ = self.worker([calls(("write_file", {"path": "a.md", "content": "x"})), final()], [tool])
        await asyncio.wait_for(worker.handle_task(self.task()), 2)
        notes = [m.payload["note"] for m in self.messages(MsgType.STATUS)]
        self.assertIn("Worker step 1", notes)                                 # before the model answers: nothing to say yet
        self.assertIn("Step 1: write_file a.md", notes)

    async def test_a_final_answer_adds_no_tool_note(self):
        worker, _ = self.worker([final()], [])
        await asyncio.wait_for(worker.handle_task(self.task()), 2)
        notes = [m.payload["note"] for m in self.messages(MsgType.STATUS)]
        self.assertFalse([n for n in notes if n.startswith("Step ")], notes)


class ParallelJobsTest(Harness):
    """The lead gives one teammate two jobs at once: both reach 'Step 1' together, so the lines carry the job's number."""

    async def run_jobs(self, goals):
        def brain(messages, specs):
            if any(m["role"] == "tool" for m in messages):
                return final()
            goal = json.loads(messages[1]["content"])["goal"]
            return calls(("write_file", {"path": goal + ".md", "content": "x"}))
        async def slow(sandbox, kwargs):
            await asyncio.sleep(0.02)                      # the first job is still at work when the second one starts
        worker, _ = self.worker([], [ScriptedTool("write_file", [], hook=slow)], brain)
        tasks = [self.task(goal=goal) for goal in goals]
        await asyncio.wait_for(asyncio.gather(*(worker.handle_task(task) for task in tasks)), 2)
        return worker, [m.payload["note"] for m in self.messages(MsgType.STATUS)]

    async def test_two_jobs_at_once_are_told_apart(self):
        _, notes = await self.run_jobs(["a", "b"])
        self.assertIn("Step 1: write_file a.md", notes)                    # alone when it began: no number yet
        self.assertIn("#2 Worker step 1", notes)                           # the second job began while it was running
        self.assertIn("#2 Step 1: write_file b.md", notes)
        self.assertIn("#1 Worker step 2", notes)                           # and from then on the first one is numbered too

    async def test_a_job_on_its_own_has_no_number_and_the_count_is_released_afterwards(self):
        worker, notes = await self.run_jobs(["a"])
        self.assertIn("Step 1: write_file a.md", notes)
        self.assertFalse([n for n in notes if n.startswith("#")], notes)
        self.assertEqual(worker._jobs, {})
        worker2, _ = await self.run_jobs(["c", "d"])
        self.assertEqual(worker2._jobs, {})
