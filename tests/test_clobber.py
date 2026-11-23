"""A script that overwrites what a member just wrote, and two calls that go round and round, are called out.

Final run of 2026-11-23, scenario 1 task 2: the developer edited booking_app.py into a 47 KB app with the dashboard, then ran
its own copy_in.py (inbox -> workspace) twice more, which put the 27 KB old copy back. It reported "done", the lead received
the old file, and ran "test, copy_in, test, copy_in ..." twenty times: every copy_in counted as a change, so the repeat guard
never fired."""
from __future__ import annotations

import asyncio
import json
import unittest

from mas.tools.base import ToolResult
from tests import test_worker
from tests.test_worker import ScriptedTool, call, final


class Harness(unittest.IsolatedAsyncioTestCase):
    """The worker set-up of tests/test_worker.py, without inheriting (and so running again) its tests."""
    setUp = test_worker.WorkerTest.setUp
    asyncTearDown = test_worker.WorkerTest.asyncTearDown
    worker = test_worker.WorkerTest.worker
    task = test_worker.WorkerTest.task


def writes(name, path, text):
    """A write tool that really puts `text` into `path`."""
    async def hook(sandbox, kwargs):
        sandbox.write_text(path, text)
    return ScriptedTool(name, [ToolResult(True, "ok", files_written=[path])], hook=hook)


def overwrites(path, text):
    """run_python of a script that puts `text` over `path`."""
    async def hook(sandbox, kwargs):
        sandbox.write_text(path, text)
    return ScriptedTool("run_python", [ToolResult(True, "copied")] * 9, hook=hook)


class ClobberTest(Harness):
    async def observations(self, script, tools):
        worker, llm = self.worker([*script, final()], tools)
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        return [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]

    async def test_a_script_that_puts_an_older_copy_over_a_file_the_member_wrote_is_called_out(self):
        edit = writes("edit_file", "app.py", "new " * 5000)
        python = overwrites("app.py", "old " * 3000)
        written, ran = await self.observations(
            [call("edit_file", "e1", value="dashboard"), call("run_python", "r1", value="copy_in.py")], [edit, python])
        self.assertNotIn("note", written)
        self.assertIn("app.py was changed by this call", ran["note"])
        self.assertIn("20000 characters when you last wrote it (step 1) and now has 12000", ran["note"])
        self.assertIn("overwrote your edits", ran["note"])
        self.assertTrue(ran["ok"])                                           # the call itself is not refused

    async def test_a_script_that_leaves_the_file_alone_says_nothing(self):
        edit = writes("edit_file", "app.py", "new")
        python = overwrites("other.txt", "x")
        _, ran = await self.observations(
            [call("edit_file", "e1", value="x"), call("run_python", "r1", value="check.py")], [edit, python])
        self.assertNotIn("note", ran)

    async def test_the_note_comes_once_and_the_newer_content_is_the_one_remembered(self):
        edit = writes("edit_file", "app.py", "v1")
        python = overwrites("app.py", "v2 longer")
        _, first, second = await self.observations(
            [call("edit_file", "e1", value="x"), call("run_python", "r1", value="a.py"),
             call("run_python", "r2", value="b.py")], [edit, python])
        self.assertIn("was changed by this call", first["note"])
        self.assertNotIn("note", second)                                     # same content again: nothing new to say

    async def test_a_file_deleted_by_a_script_is_called_out_too(self):
        edit = writes("write_file", "app.py", "new")

        async def delete(sandbox, kwargs):
            sandbox.delete("app.py")
        python = ScriptedTool("run_python", [ToolResult(True, "cleaned")], hook=delete)
        _, ran = await self.observations(
            [call("write_file", "w1", value="x"), call("run_python", "r1", value="clean.py")], [edit, python])
        self.assertIn("app.py is gone after this call", ran["note"])

    async def test_files_the_member_did_not_write_are_not_watched(self):
        self.sandbox.write_text("inbox_copy.py", "from a teammate")
        python = overwrites("inbox_copy.py", "changed")
        (ran,) = await self.observations([call("run_python", "r1", value="x.py")], [python])
        self.assertNotIn("note", ran)


class CycleTest(Harness):
    def script(self, rounds):
        return [call(name, f"c{n}{i}", value=arg) for n in range(rounds)
                for i, (name, arg) in enumerate([("run_python", "test.py"), ("run_python", "copy_in.py")])]

    async def run_cycle(self, rounds, outputs=None):
        results = outputs or [ToolResult(False, "exit code 1: 404"), ToolResult(True, "copied")] * rounds
        python = ScriptedTool("run_python", results)
        worker, llm = self.worker([*self.script(rounds), final()], [python])
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        return [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]

    async def test_two_calls_repeated_three_times_with_the_same_answers_are_called_out(self):
        seen = await self.run_cycle(3)
        self.assertTrue(all("going round in circles" not in o.get("note", "") for o in seen[:5]))
        self.assertIn("going round in circles", seen[5]["note"])
        self.assertIn("3 times", seen[5]["note"])

    async def test_two_rounds_are_not_a_loop(self):
        seen = await self.run_cycle(2)
        self.assertTrue(all("going round in circles" not in o.get("note", "") for o in seen))

    async def test_a_changing_answer_is_progress_not_a_loop(self):
        results = []
        for n in range(4):
            results += [ToolResult(False, f"exit code 1: {10 - n * 3} tests fail"), ToolResult(True, "patched")]
        seen = await self.run_cycle(4, results)
        self.assertTrue(all("going round in circles" not in o.get("note", "") for o in seen))

    async def test_times_in_the_output_do_not_hide_a_loop(self):
        results = []
        for n in range(3):
            results += [ToolResult(False, f"Ran 3 tests in 0.0{n + 1}s: FAILED"), ToolResult(True, "copied")]
        seen = await self.run_cycle(3, results)
        self.assertIn("going round in circles", seen[5]["note"])

    async def test_the_guard_can_be_switched_off(self):
        self.settings.cycle_limit = 0
        seen = await self.run_cycle(4)
        self.assertTrue(all("going round in circles" not in o.get("note", "") for o in seen))
