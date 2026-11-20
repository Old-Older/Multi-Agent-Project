"""The generic Worker executes injected tools without a fixed set of roles or an API."""
from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import HitlKind
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType, dm_channel
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.memory.base import Experience, JsonlMemory
from mas.sandbox.base import ExecResult, Sandbox
from mas.tools.base import Tool, ToolResult


def final(success=True, summary="done", **fields):
    return LLMResponse(json.dumps({"success": success, "summary": summary, **fields}))


def call(name, call_id="c1", **arguments):
    return LLMResponse("", [ToolCall(call_id, name, arguments)])


def prompt_text(messages):
    return "\n".join(str(message.get("content", "")) for message in messages)


def own_steps(llm):
    """The model calls of the worker's loop. A failed task also starts a background call that reflects on the
    failure; whether it has reached the model when handle_task returns depends on the event loop."""
    return [made for made in llm.calls if not made[0][0]["content"].startswith("Write one short, actionable sentence")]


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(poll(), 2)


class SnapshotLLM(MockLLM):
    async def chat(self, messages, tools=None, temperature=0.2):
        # MockLLM stores references; snapshots let tests inspect each actual request.
        return await super().chat(copy.deepcopy(messages), tools, temperature)


class MemorySandbox(Sandbox):
    """No process execution and no access outside the test's in-memory files."""

    def __init__(self, root):
        super().__init__("worker", root)
        self.files = {}

    def resolve(self, rel):
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise PermissionError(rel)
        return path

    def read_text(self, rel):
        return self.files[rel]

    def write_text(self, rel, content):
        self.resolve(rel)
        self.files[rel] = content

    def delete(self, rel):
        del self.files[rel]

    def list_dir(self, rel="."):
        return sorted(self.files)

    def exists(self, rel):
        return rel in self.files

    async def exec(self, cmd, timeout=60.0, env=None):
        return ExecResult(1, "", "process execution is disabled in this test")

    def import_file(self, src, name=None):
        raise AssertionError("these tests do not transfer files between agents")


class ScriptedTool(Tool):
    description = "A deterministic tool supplied by the caller."
    parameters = {"type": "object", "properties": {"value": {"type": "string"}}}

    def __init__(self, name="write_file", results=None, *, approval=False, hook=None):
        self.name = name
        self.results = list(results or [ToolResult(True, "ok")])
        self.requires_approval = approval
        self.hook = hook
        self.calls = []

    async def run(self, sandbox, **kwargs):
        self.calls.append((sandbox, kwargs))
        if self.hook:
            await self.hook(sandbox, kwargs)
        result = self.results.pop(0) if self.results else ToolResult(True, "ok")
        # Reported artifacts must exist, just as they do after a real write tool.
        for path in result.files_written:
            if not sandbox.exists(path):
                sandbox.write_text(path, "test artifact")
        return result


class WorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        # closing_check off: the scripts here end a lead's run with one final answer (tests/test_budget.py covers the check)
        self.settings = Settings(data_dir=root / "data", workspaces_dir=root / "workspaces", closing_check=False, request_budget_s=0.0,
                                 requirements_check=False)
        self.bus = InMemoryBus()
        for member in (HUMAN, "worker"):
            self.bus.join(member, GROUP_MAIN)
        self.state = StateTable()
        self.sandbox = MemorySandbox(root / "workspace")
        self.router = Router(self.bus, self.state, {"worker": self.sandbox}, self.settings)
        self.memory = JsonlMemory.for_agent(self.settings.memory_dir, "worker")
        self.background = []
        self.workers = []

    async def asyncTearDown(self):
        for pending in self.background:
            pending.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        # Direct handle_task tests do not enter run(), which owns production shutdown.
        reflections = [pending for worker in self.workers for pending in worker._reflections]
        for pending in reflections:
            pending.cancel()
        await asyncio.gather(*reflections, return_exceptions=True)

    def worker(self, script, tools=(), responder=None):
        llm = SnapshotLLM(script, responder or (lambda messages, specs: LLMResponse("Check inputs first.")))
        role = RoleConfig("worker", "Worker", "Uses the supplied tools.", "Follow this task carefully.")
        worker = WorkerAgent(role, self.bus, self.router, self.settings, llm,
                             list(tools), self.sandbox, self.memory)
        self.workers.append(worker)
        return worker, llm

    def task(self, goal="write a note", origin=GROUP_MAIN, **fields):
        root = self.router.new_root_id(origin)
        task = Task(goal, "worker", HUMAN, origin, root, origin, chain=[HUMAN], **fields)
        self.state.register(task)
        board = self.router.board(origin)
        board.start_root(root, goal)
        board.add_task(task)
        return task

    def spawn(self, coroutine):
        pending = asyncio.create_task(coroutine)
        self.background.append(pending)
        return pending

    def messages(self, kind, channel=GROUP_MAIN):
        return [message for message in self.bus.history(channel, 100) if message.type == kind]

    async def answer_request(self, answer, channel=GROUP_MAIN):
        await until(lambda: self.messages(MsgType.HITL_REQUEST, channel))
        request = self.messages(MsgType.HITL_REQUEST, channel)[-1]
        await self.bus.publish(Message(
            MsgType.HITL_RESPONSE, HUMAN, channel, reply_to=request.id,
            payload={"request_id": request.payload["request_id"], "answer": answer}))
        return request

    def test_specs_use_only_injected_tools_and_generic_virtual_tools(self):
        tool = ScriptedTool("custom_tool")
        worker, _ = self.worker([], [tool])
        names = {spec.name for spec in worker.function_specs(self.task())}
        self.assertEqual(names, {"custom_tool", "decline", "read_group"})
        self.assertEqual(worker.agent_id, "worker")
        self.assertFalse(any(name.startswith("call_") for name in names))

    async def test_tool_protocol_and_metadata_are_preserved(self):
        tool = ScriptedTool(results=[ToolResult(True, "file saved", ["note.md"], {"commit": "real"})])
        worker, llm = self.worker([
            call("write_file", value="hello"),
            final(artifacts=["note.md"], refs={"commit": "invented", "url": "https://example.test"},
                  open_issues=["review wording"]),
        ], [tool])
        task = self.task()
        result = await worker.handle_task(task)
        self.assertTrue(result.success)
        self.assertEqual(result.task_id, task.id)
        self.assertEqual(result.artifacts, ["note.md"])
        self.assertEqual(result.refs, {"commit": "real", "url": "https://example.test"})
        self.assertEqual(result.open_issues, ["review wording"])
        self.assertEqual(tool.calls, [(self.sandbox, {"value": "hello"})])
        messages = llm.calls[1][0]
        assistant = next(message for message in messages if message.get("tool_calls"))
        observation = next(message for message in messages if message["role"] == "tool")
        self.assertEqual(assistant["tool_calls"][0]["id"], observation["tool_call_id"])
        self.assertEqual(json.loads(observation["content"])["ok"], True)
        self.assertIn("file saved", observation["content"])
        self.assertEqual(len(llm.calls), 2)  # success does not spend a call on reflection
        [experience] = self.memory.all()
        self.assertTrue(experience.success)
        self.assertEqual(set(experience.tags), {"file", "doc"})

    async def test_memory_write_failure_does_not_discard_success_or_artifacts(self):
        tool = ScriptedTool(results=[ToolResult(True, "saved", ["note.md"], {"revision": "abc123"})])
        worker, llm = self.worker([call(tool.name), final(summary="note saved")], [tool])
        with mock.patch.object(self.memory, "add", side_effect=OSError("storage unavailable")), \
                mock.patch.object(worker, "reflect", wraps=worker.reflect) as reflection, \
                self.assertLogs("mas.agents.worker", level="WARNING"):
            result = await worker.handle_task(self.task())
        self.assertEqual((result.success, result.summary), (True, "note saved"))
        self.assertEqual((result.artifacts, result.refs), (["note.md"], {"revision": "abc123"}))
        self.assertIsNone(result.failure_mode)
        reflection.assert_not_called()
        self.assertEqual(len(llm.calls), 2)

    async def test_tools_in_one_batch_execute_in_order(self):
        order = []

        async def effect(sandbox, kwargs):
            order.append("start " + kwargs["value"])
            await asyncio.sleep(0)
            order.append("end " + kwargs["value"])

        tool = ScriptedTool(hook=effect)
        worker, _ = self.worker([
            LLMResponse("", [ToolCall("one", tool.name, {"value": "one"}),
                             ToolCall("two", tool.name, {"value": "two"})]), final(),
        ], [tool])
        self.assertTrue((await worker.handle_task(self.task())).success)
        self.assertEqual(order, ["start one", "end one", "start two", "end two"])

    async def test_one_tool_failure_is_an_observation_and_can_recover(self):
        tool = ScriptedTool(results=[ToolResult(False, "invalid path"), ToolResult(True, "saved")])
        worker, llm = self.worker([call(tool.name), call(tool.name, "retry"), final()], [tool])
        self.assertTrue((await worker.handle_task(self.task())).success)
        self.assertIn("invalid path", prompt_text(llm.calls[1][0]))
        self.assertEqual(len(tool.calls), 2)
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])

    async def test_tool_exceptions_are_recoverable_and_observations_are_bounded(self):
        self.settings.tool_output_max_chars = 64

        async def effect(sandbox, kwargs):
            if kwargs["value"] == "bad":
                raise ValueError("invalid input " + "x" * 1000)

        tool = ScriptedTool(results=[ToolResult(True, "saved " + "y" * 1000)], hook=effect)
        worker, llm = self.worker([
            call(tool.name, value="bad"), call(tool.name, "retry", value="good"), final(),
        ], [tool])
        self.assertTrue((await worker.handle_task(self.task())).success)
        observations = [json.loads(message["content"]) for message in llm.calls[2][0]
                        if message["role"] == "tool"]
        self.assertEqual([observation["ok"] for observation in observations], [False, True])
        self.assertIn("ValueError", observations[0]["output"])
        for observation in observations:
            self.assertLessEqual(len(observation["output"]), self.settings.tool_output_max_chars)
        self.assertEqual(len(tool.calls), 2)

    async def test_tool_timeout_is_recoverable_without_exhausting_worker_budget(self):
        async def effect(sandbox, kwargs):
            if kwargs["value"] == "first":
                raise TimeoutError("remote request timed out")

        tool = ScriptedTool(hook=effect)
        worker, llm = self.worker([
            call(tool.name, value="first"), call(tool.name, "retry", value="second"), final(),
        ], [tool])
        result = await worker.handle_task(self.task())
        self.assertTrue(result.success)
        self.assertIsNone(result.failure_mode)
        self.assertEqual(len(tool.calls), 2)
        observations = [json.loads(message["content"]) for message in llm.calls[2][0]
                        if message["role"] == "tool"]
        self.assertEqual([observation["ok"] for observation in observations], [False, True])
        self.assertIn("TimeoutError", observations[0]["output"])
        self.assertIn("remote request timed out", observations[0]["output"])

    async def test_two_consecutive_tool_failures_give_the_model_a_hint_and_do_not_bother_the_human(self):
        tool = ScriptedTool(results=[ToolResult(False, "bad input"), ToolResult(False, "still bad")])
        worker, llm = self.worker([call(tool.name), call(tool.name, "retry"), final()], [tool])
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertTrue(result.success)
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])               # a failing tool is not a question for the human
        observations = [json.loads(m["content"]) for m in llm.calls[2][0] if m["role"] == "tool"]
        self.assertNotIn("hint", observations[0])
        self.assertIn("failed twice in a row", observations[1]["hint"])

    async def test_the_model_is_told_the_budget_and_the_last_step_has_no_tools(self):
        self.settings.max_worker_steps = 5
        tool = ScriptedTool(results=[ToolResult(True, "ok")] * 5)
        script = [call(tool.name, f"c{n}") for n in range(1, 5)] + [final(False, "ran out, partly done")]
        worker, llm = self.worker(script, [tool])
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertEqual((result.success, result.summary), (False, "ran out, partly done"))   # a result, not "step limit reached"
        sent = [(call_[1], prompt_text(call_[0])) for call_ in own_steps(llm)]
        self.assertEqual(len(sent), 5)
        self.assertNotIn("Budget:", sent[0][1])
        self.assertIn("Budget: 3 steps left", sent[1][1])
        self.assertTrue(all(specs for specs, _ in sent[:4]))
        self.assertEqual(sent[4][0], [])                                      # the last step: no tools, so it must answer
        self.assertIn("last step", sent[4][1])

    async def test_every_tool_call_is_recorded_with_its_arguments_and_outcome(self):
        tool = ScriptedTool("run_python", [ToolResult(False, "exit 1: boom"), ToolResult(True, "ok")])
        worker, _ = self.worker([call(tool.name, "c1", value="x" * 900), call(tool.name, "c2", value="short"), final()],
                                [tool])
        task = self.task()
        self.assertTrue((await asyncio.wait_for(worker.handle_task(task), 2)).success)
        lines = (self.settings.data_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
        first, second = (json.loads(line) for line in lines)
        self.assertEqual((first["agent"], first["root"], first["task"], first["step"], first["tool"], first["ok"]),
                         ("worker", task.root_id, task.id, 1, "run_python", False))
        self.assertEqual(first["result"], "exit 1: boom")
        self.assertTrue(first["arguments"]["value"].endswith("… (900 characters)"))           # long values are cut
        self.assertEqual((second["step"], second["ok"], second["arguments"]), (2, True, {"value": "short"}))

    async def test_a_call_cut_off_at_the_output_limit_is_not_run_and_the_model_is_told_to_write_in_parts(self):
        """On the course test set a 26 000-character write_file ended at the output limit. Its arguments became {},
        the tool answered 'missing required argument: path', and the member repeated the call until its time was up."""
        tool = ScriptedTool()
        self.sandbox.write_text("deck.html", "the version that is there")
        cut = [LLMResponse("", [ToolCall(f"c{n}", tool.name, {}, '{"path": "deck.html", "content": "<html>\\n<bo',
                                         malformed=True)], finish_reason="length") for n in (1, 2)]
        worker, llm = self.worker([*cut, call(tool.name, "c3", value="part 1"), final()], [tool])
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertTrue(result.success)
        self.assertEqual([kwargs for _, kwargs in tool.calls], [{"value": "part 1"}])     # the cut calls never ran
        self.assertEqual(self.sandbox.read_text("deck.html"), "the version that is there")    # and replaced nothing
        first, second = [json.loads(m["content"]) for m in llm.calls[2][0] if m["role"] == "tool"]
        self.assertFalse(first["ok"])
        self.assertIn("cut off", first["output"])
        self.assertIn("append set to true", first["output"])
        self.assertNotIn("missing required argument", first["output"])
        self.assertNotIn("in a row", first["output"])
        self.assertIn("reply number 2 in a row that was cut off: do NOT send that content in one call again",
                      second["output"])

    async def test_what_arrived_of_a_cut_off_write_of_a_new_file_is_kept_and_the_member_continues_from_there(self):
        """Round 15: told only that its call was cut off, a lead wrote a 25 000-character deck from the start three
        times in a row, each time to the same limit."""
        tool = ScriptedTool(results=[ToolResult(True, "Wrote deck.html", files_written=["deck.html"])])
        raw = '{"path": "deck.html", "content": "<html>\\n<body>\\n<h1>Outlook</h1>\\n<p>The first half of a sen'
        cut = LLMResponse("", [ToolCall("c1", tool.name, {}, raw, malformed=True)], finish_reason="length")
        worker, llm = self.worker([cut, final()], [tool])
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertEqual([kwargs for _, kwargs in tool.calls],
                         [{"path": "deck.html", "content": "<html>\n<body>\n<h1>Outlook</h1>\n"}])    # whole lines only
        self.assertEqual(result.artifacts, ["deck.html"])
        observation = json.loads([m for m in llm.calls[1][0] if m["role"] == "tool"][0]["content"])
        self.assertEqual((observation["ok"], observation["partial"]), (False, True))
        self.assertIn("31 characters were written to deck.html", observation["output"])
        self.assertIn("the file now ends with: '<h1>Outlook</h1>'", observation["output"])
        self.assertIn("NOT complete", observation["output"])
        self.assertIn("append set to true", observation["output"])
        self.assertNotIn("hint", observation)                                 # it made progress: not a failed call

    async def test_the_same_call_with_the_same_answer_is_noted_and_then_no_longer_run(self):
        """Round 15: a lead ran one word count 37 times in a row and got 974 every time, until its steps were gone."""
        count = ScriptedTool("run_python", [ToolResult(True, "974")] * 9)
        edit = ScriptedTool("edit_file", [ToolResult(True, "ok", files_written=["report.md"])])
        same = [call("run_python", f"c{n}", value="count.py") for n in range(1, 5)]
        worker, llm = self.worker([*same, call("edit_file", "e1", value="trim"), call("run_python", "c9", value="count.py"),
                                   final()], [count, edit])
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        self.assertEqual(len(count.calls), 3)                                 # twice, then once more after the edit
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        first, second, third, fourth, _, after_edit = seen
        self.assertNotIn("note", first)
        self.assertIn("same run_python call as step 1, with the same answer", second["note"])
        self.assertEqual((third["ok"], third["repeat"]), (False, True))
        self.assertIn("has been made 2 times since anything changed (first at step 1)", third["output"])
        self.assertIn("'974'", third["output"])
        self.assertIn("failed twice in a row", fourth["hint"])                # refused again: the usual escalation
        self.assertEqual((after_edit["ok"], after_edit["output"]), (True, "974"))
        self.assertNotIn("note", after_edit)                                  # the file changed: counting again is new

    async def test_a_check_that_fails_the_same_way_after_another_script_ran_is_not_a_repeat(self):
        python = ScriptedTool("run_python", [ToolResult(False, "exit code 1: 2 tests fail"), ToolResult(True, "patched"),
                                             ToolResult(False, "exit code 1: 2 tests fail"), ToolResult(True, "patched"),
                                             ToolResult(False, "exit code 1: 2 tests fail")])
        script = [call("run_python", f"c{n}", value=name) for n, name in enumerate(["test.py", "fix.py"] * 2 + ["test.py"])]
        worker, llm = self.worker([*script, final()], [python])
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        self.assertEqual(len(python.calls), 5)                                # every one of them ran
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        self.assertTrue(all("note" not in observation and "repeat" not in observation for observation in seen))

    async def test_reading_the_same_file_again_is_a_repeat_only_while_nothing_was_written(self):
        read = ScriptedTool("read_file", [ToolResult(True, "the text")] * 9)
        write = ScriptedTool("write_file", [ToolResult(True, "ok", files_written=["a.md"])])
        script = [call("read_file", "r1", value="a.md"), call("read_file", "r2", value="a.md"),
                  call("write_file", "w1", value="new"), call("read_file", "r3", value="a.md")]
        self.settings.repeat_limit = 1
        worker, llm = self.worker([*script, call("read_file", "r4", value="a.md"), final()], [read, write])
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        self.assertEqual([observation.get("repeat", False) for observation in seen], [False, True, False, False, True])
        self.assertEqual(len(read.calls), 2)                                  # with a limit of 1 the second is refused

    async def test_arguments_that_are_not_json_are_called_that_and_twice_in_a_row_gets_the_usual_hint(self):
        tool = ScriptedTool()
        broken = [LLMResponse("", [ToolCall(f"c{n}", tool.name, {}, "{'value': oops", malformed=True)]) for n in (1, 2)]
        worker, llm = self.worker([*broken, final()], [tool])
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        self.assertEqual(tool.calls, [])
        first, second = [json.loads(m["content"]) for m in llm.calls[2][0] if m["role"] == "tool"]
        self.assertIn("not a valid JSON object", first["output"])
        self.assertNotIn("cut off", first["output"])
        self.assertNotIn("hint", first)
        self.assertIn("failed twice in a row", second["hint"])

    async def test_a_repeated_search_runs_again_and_says_it_is_a_repeat_but_a_failed_one_is_simply_retried(self):
        search = ScriptedTool("web_search", [ToolResult(False, "no engine answered"), ToolResult(True, "found"),
                                             ToolResult(True, "found")])
        worker, llm = self.worker([call("web_search", "c1", value="HBM pricing"),
                                   call("web_search", "c2", value="HBM pricing"),
                                   call("web_search", "c3", value="HBM pricing"), final()], [search])
        self.assertTrue((await asyncio.wait_for(worker.handle_task(self.task()), 2)).success)
        self.assertEqual(len(search.calls), 3)                                     # nothing was blocked
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        self.assertNotIn("note", seen[0])                                           # the failure
        self.assertNotIn("note", seen[1])                                           # the retry is the first success
        self.assertIn("same web_search call as step 2", seen[2]["note"])           # only now is it a repeat

    async def test_a_long_run_of_research_gets_a_reminder_to_stop(self):
        fetch = ScriptedTool("fetch_url")
        script = [call("fetch_url", f"c{n}", value=f"page {n}") for n in range(1, 21)] + [final()]
        self.settings.max_worker_steps = 40
        self.settings.research_max_calls = 0                      # no hard limit here: only the reminders are tested
        self.settings.research_note_after, self.settings.research_note_every = 12, 6
        worker, llm = self.worker(script, [fetch])
        await asyncio.wait_for(worker.handle_task(self.task()), 5)
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        self.assertEqual([n for n, o in enumerate(seen, 1) if "note" in o], [12, 18])   # after 12, then every 6
        self.assertIn("stop researching", seen[11]["note"])

    async def test_the_thresholds_come_from_the_settings(self):
        self.settings.research_note_after, self.settings.research_note_every = 3, 2
        fetch = ScriptedTool("fetch_url")
        worker, llm = self.worker([call("fetch_url", f"c{n}", value=f"p{n}") for n in range(1, 8)] + [final()], [fetch])
        await asyncio.wait_for(worker.handle_task(self.task()), 5)
        seen = [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]
        self.assertEqual([n for n, o in enumerate(seen, 1) if "note" in o], [3, 5, 7])

    async def test_the_nudges_can_be_switched_off_but_the_budget_warning_stays(self):
        self.settings.early_stop_nudges = False
        self.settings.max_worker_steps = 10
        self.settings.research_note_after = 2
        search = ScriptedTool("web_search")
        worker, llm = self.worker([call("web_search", f"c{n}", value="same") for n in range(1, 9)] + [final()], [search])
        await asyncio.wait_for(worker.handle_task(self.task()), 5)
        text = prompt_text([m for messages, _ in llm.calls for m in messages])
        for gone in ("Progress check", "stop researching", "same web_search call"):
            self.assertNotIn(gone, text)
        self.assertIn("Budget:", text)                                               # the safety net is not optional

    async def test_halfway_with_no_file_written_the_worker_is_asked_to_write_what_it_has(self):
        self.settings.max_worker_steps = 10
        search = ScriptedTool("web_search")
        script = [call("web_search", f"c{n}", value=f"q{n}") for n in range(1, 7)] + [final()]
        worker, llm = self.worker(script, [search])
        await asyncio.wait_for(worker.handle_task(self.task()), 5)
        asked = [n for n, (messages, _) in enumerate(llm.calls, 1) if "Progress check" in prompt_text(messages)]
        self.assertEqual(asked[0], 5)                                              # step 5 of 10
        self.assertNotIn("Progress check", prompt_text(llm.calls[3][0]))

    async def test_no_progress_check_once_a_file_has_been_written(self):
        self.settings.max_worker_steps = 10
        writer = ScriptedTool("write_file", [ToolResult(True, "wrote", ["notes.md"])])
        search = ScriptedTool("web_search")
        script = [call("write_file", "c0", value="x")] + [call("web_search", f"c{n}", value=f"q{n}") for n in range(1, 6)] + [final()]
        worker, llm = self.worker(script, [writer, search])
        await asyncio.wait_for(worker.handle_task(self.task()), 5)
        self.assertFalse(any("Progress check" in prompt_text(messages) for messages, _ in llm.calls))

    def lead(self, script, tools):
        llm = SnapshotLLM(script, lambda messages, specs: LLMResponse("Check inputs first."))
        role = RoleConfig("worker", "Worker", "Uses the supplied tools.", "Follow this task carefully.")
        mate = RoleConfig("mate", "Mate", "Helps.", "")
        lead = WorkerAgent(role, self.bus, self.router, self.settings, llm, list(tools), self.sandbox, self.memory,
                           peers={"worker": role, "mate": mate})
        self.workers.append(lead)
        return lead, llm

    async def test_halfway_a_lead_with_no_deliverable_anywhere_is_told_to_get_one_written(self):
        self.settings.max_lead_steps = 10
        search = ScriptedTool("web_search")
        lead, llm = self.lead([call("web_search", f"c{n}", value=f"q{n}") for n in range(1, 7)] + [final()], [search])
        await asyncio.wait_for(lead.handle_task(self.task()), 5)
        asked = [n for n, (messages, _) in enumerate(llm.calls, 1)
                 if "no file exists yet for this request" in prompt_text(messages)]
        self.assertEqual(asked[0], 5)

    async def test_a_lead_is_not_nagged_once_a_teammate_has_written_a_file(self):
        self.settings.max_lead_steps = 10
        task = self.task()
        mate = Task("write it", "mate", "worker", GROUP_MAIN, task.root_id, GROUP_MAIN, chain=[HUMAN, "worker"],
                    parent_id=task.id)
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, "done", artifacts=["deck.html"]))
        search = ScriptedTool("web_search")
        lead, llm = self.lead([call("web_search", f"c{n}", value=f"q{n}") for n in range(1, 7)] + [final()], [search])
        await asyncio.wait_for(lead.handle_task(task), 5)
        self.assertFalse(any("no file exists yet" in prompt_text(messages) for messages, _ in llm.calls))

    async def test_a_lead_delivers_the_files_it_lists_and_not_its_scratch_files(self):
        writer = ScriptedTool("write_file", [ToolResult(True, "wrote", ["deck.html"]), ToolResult(True, "wrote", ["fix2.py"]),
                                             ToolResult(True, "wrote", ["check.py"])])
        mate = Task("write the notes", "mate", "worker", GROUP_MAIN, "R1", GROUP_MAIN, chain=[HUMAN, "worker"], parent_id="t0")
        task = self.task()
        mate.root_id = task.root_id
        self.state.register(mate)
        self.state.finish(TaskResult(mate.id, True, "done", artifacts=["notes.md"]))
        lead, _ = self.lead([call("write_file", "c1", value="a"), call("write_file", "c2", value="b"),
                             call("write_file", "c3", value="c"),
                             final(artifacts=["deck.html", "notes.md", "not-there.md"])], [writer])
        result = await asyncio.wait_for(lead.handle_task(task), 2)
        self.assertEqual(result.artifacts, ["deck.html", "notes.md"])      # no fix2.py, no check.py, nothing that does not exist

    async def test_a_lead_that_lists_nothing_falls_back_to_everything_it_wrote(self):
        writer = ScriptedTool("write_file", [ToolResult(True, "wrote", ["deck.html"]), ToolResult(True, "wrote", ["fix2.py"])])
        lead, _ = self.lead([call("write_file", "c1", value="a"), call("write_file", "c2", value="b"), final()], [writer])
        result = await asyncio.wait_for(lead.handle_task(self.task()), 2)
        self.assertEqual(result.artifacts, ["deck.html", "fix2.py"])

    async def test_an_ordinary_worker_still_reports_every_file_it_wrote(self):
        writer = ScriptedTool("write_file", [ToolResult(True, "wrote", ["a.md"]), ToolResult(True, "wrote", ["b.md"])])
        worker, _ = self.worker([call("write_file", "c1", value="a"), call("write_file", "c2", value="b"),
                                 final(artifacts=["a.md"])], [writer])
        self.assertEqual((await asyncio.wait_for(worker.handle_task(self.task()), 2)).artifacts, ["a.md", "b.md"])

    async def test_the_instructions_tell_a_worker_to_stop_when_it_can_answer(self):
        worker, llm = self.worker([final()], [])
        await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertIn("Stop as soon as you can answer the task", prompt_text(llm.calls[0][0]))

    async def test_denied_approval_never_runs_the_tool(self):
        tool = ScriptedTool("delete_file", approval=True)
        worker, _ = self.worker([call(tool.name), final(False, "permission denied")], [tool])
        pending = self.spawn(worker.handle_task(self.task()))
        request = await self.answer_request("no")
        self.assertEqual(request.payload["kind"], HitlKind.APPROVAL.value)
        self.assertFalse((await asyncio.wait_for(pending, 2)).success)
        self.assertEqual(tool.calls, [])

    async def test_a_file_the_task_wrote_itself_can_be_deleted_without_asking(self):
        writer = ScriptedTool("write_file", [ToolResult(True, "wrote", ["scratch.py"])])
        delete = ScriptedTool("delete_file", approval=True)
        worker, _ = self.worker([call("write_file", "c1", value="x"), call("delete_file", "c2", path="./scratch.py"),
                                 final()], [writer, delete])
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertTrue(result.success)
        self.assertEqual([kw["path"] for _, kw in delete.calls], ["./scratch.py"])         # it ran
        self.assertEqual(self.messages(MsgType.HITL_REQUEST), [])                           # and nobody was asked

    async def test_any_other_file_still_needs_the_humans_approval(self):
        writer = ScriptedTool("write_file", [ToolResult(True, "wrote", ["scratch.py"])])
        delete = ScriptedTool("delete_file", approval=True)
        worker, _ = self.worker([call("write_file", "c1", value="x"), call("delete_file", "c2", path="report.md"),
                                 final()], [writer, delete])
        pending = self.spawn(worker.handle_task(self.task()))
        request = await self.answer_request("no")
        self.assertEqual(request.payload["kind"], HitlKind.APPROVAL.value)
        await asyncio.wait_for(pending, 2)
        self.assertEqual(delete.calls, [])

    async def test_the_instructions_say_that_workspaces_are_private(self):
        worker, llm = self.worker([final()], [])
        worker.peers = {"worker": worker.role, "mate": RoleConfig("mate", "Mate", "Helps.", "")}
        await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertIn("list every file it needs in\n`files`", prompt_text(llm.calls[0][0]))

    async def test_approved_tool_runs_after_the_answer(self):
        tool = ScriptedTool("delete_file", approval=True)
        worker, _ = self.worker([call(tool.name), final()], [tool])
        pending = self.spawn(worker.handle_task(self.task()))
        await until(lambda: self.messages(MsgType.HITL_REQUEST))
        self.assertEqual(tool.calls, [])
        await self.answer_request("yes")
        self.assertTrue((await asyncio.wait_for(pending, 2)).success)
        self.assertEqual(len(tool.calls), 1)

    async def test_human_wait_does_not_consume_active_execution_budget(self):
        self.settings.subtask_timeout_s = 0.2
        tool = ScriptedTool("delete_file", approval=True)
        worker, _ = self.worker([call(tool.name), final()], [tool])
        task = self.task()
        pending = self.spawn(worker.handle_task(task))
        await until(lambda: self.messages(MsgType.HITL_REQUEST))
        await asyncio.sleep(self.settings.subtask_timeout_s * 1.5)
        self.assertFalse(pending.done())
        self.assertEqual(self.state.get(task.id).status, TaskStatus.WAITING_HUMAN)
        await self.answer_request("yes")
        result = await asyncio.wait_for(pending, 2)
        self.assertTrue(result.success)
        self.assertGreater(result.duration, self.settings.subtask_timeout_s)
        self.assertEqual(len(tool.calls), 1)

    async def test_cancel_while_waiting_for_approval_stops_without_memory(self):
        tool = ScriptedTool("delete_file", approval=True)
        worker, llm = self.worker([call(tool.name)], [tool])
        task = self.task()
        pending = self.spawn(worker.handle_task(task))
        await until(lambda: self.messages(MsgType.HITL_REQUEST))
        self.router.cancel_root(task.root_id)
        result = await asyncio.wait_for(pending, 2)
        self.assertEqual((result.success, result.error), (False, "cancelled"))
        self.assertEqual((tool.calls, self.memory.all()), ([], []))
        self.assertEqual(len(llm.calls), 1)

    async def test_task_cancelled_before_first_step_does_not_call_llm(self):
        worker, llm = self.worker([final()])
        task = self.task()
        self.router.cancel_root(task.root_id)
        result = await worker.handle_task(task)
        self.assertEqual(result.error, "cancelled")
        self.assertEqual((llm.calls, self.memory.all()), ([], []))

    async def test_active_timeout_stops_the_tool_and_preserves_partial_work(self):
        self.settings.subtask_timeout_s = 0.2
        interrupted = asyncio.Event()

        async def block(sandbox, kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()

        write = ScriptedTool(results=[ToolResult(True, "saved", ["partial.md"], {"revision": "1"})])
        slow = ScriptedTool("slow_tool", hook=block)
        worker, _ = self.worker([
            LLMResponse("", [ToolCall("write", write.name, {}), ToolCall("slow", slow.name, {})]),
        ], [write, slow])
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertEqual((result.success, result.failure_mode), (False, FailureMode.TIMEOUT))
        self.assertEqual((result.artifacts, result.refs), (["partial.md"], {"revision": "1"}))
        self.assertTrue(interrupted.is_set())
        [experience] = self.memory.all()
        self.assertFalse(experience.success)
        self.assertEqual(experience.task_id, result.task_id)

    async def test_asyncio_cancellation_propagates_without_recording_failure(self):
        started, interrupted = asyncio.Event(), asyncio.Event()

        async def block(sandbox, kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()

        tool = ScriptedTool(hook=block)
        worker, llm = self.worker([call(tool.name)], [tool])
        pending = self.spawn(worker.handle_task(self.task()))
        await asyncio.wait_for(started.wait(), 2)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        await asyncio.sleep(0)
        self.assertTrue(interrupted.is_set())
        self.assertEqual(self.memory.all(), [])
        self.assertEqual(len(llm.calls), 1)

    async def test_max_steps_preserves_partial_artifacts(self):
        self.settings.max_worker_steps = 1
        tool = ScriptedTool(results=[ToolResult(True, "partial", ["partial.md"])])
        worker, _ = self.worker([call(tool.name)], [tool])
        result = await worker.handle_task(self.task())
        self.assertEqual((result.success, result.failure_mode, result.steps),
                         (False, FailureMode.MAX_STEPS, 1))
        self.assertEqual(result.artifacts, ["partial.md"])
        self.assertFalse(self.memory.all()[0].success)

    async def test_invalid_final_output_gets_two_chances_to_correct(self):
        worker, llm = self.worker([LLMResponse("not JSON"), LLMResponse('{"success": "yes"}'), final()])
        self.assertTrue((await worker.handle_task(self.task())).success)
        self.assertEqual(len(llm.calls), 3)
        self.assertGreater(len(llm.calls[1][0]), len(llm.calls[0][0]))

    async def test_three_invalid_final_outputs_return_format_failure(self):
        worker, llm = self.worker([LLMResponse("[]"), final(refs=[]), final(open_issues="not a list")])
        result = await worker.handle_task(self.task())
        self.assertEqual((result.success, result.failure_mode, result.steps),
                         (False, FailureMode.LLM_FORMAT, 3))
        self.assertEqual(len(llm.calls), 3)

    async def test_decline_is_terminal_and_not_a_failed_experience(self):
        worker, llm = self.worker([call("decline", reason="requires an unavailable capability")])
        result = await worker.handle_task(self.task())
        self.assertTrue(result.declined)
        self.assertFalse(result.success)
        self.assertEqual(self.memory.all(), [])
        self.assertEqual(len(llm.calls), 1)

    async def test_decline_after_work_is_rejected_and_model_can_continue(self):
        tool = ScriptedTool()
        worker, llm = self.worker([
            call(tool.name), call("decline", "late", reason="changed my mind"), final(),
        ], [tool])
        result = await worker.handle_task(self.task())
        self.assertTrue(result.success)
        self.assertFalse(result.declined)
        self.assertEqual(len(llm.calls), 3)

    async def test_decline_mixed_with_real_work_does_not_execute_that_work(self):
        tool = ScriptedTool()
        worker, _ = self.worker([
            LLMResponse("", [ToolCall("decline", "decline", {"reason": "unsupported"}),
                             ToolCall("write", tool.name, {})]), final(),
        ], [tool])
        await worker.handle_task(self.task())
        self.assertEqual(tool.calls, [])

    async def test_unknown_delegation_name_is_not_dispatched(self):
        worker, llm = self.worker([call("call_someone", goal="help"), final()])
        task = self.task()
        self.assertTrue((await worker.handle_task(task)).success)
        self.assertEqual(len(self.state.by_root(task.root_id)), 1)
        self.assertIn("call_someone", prompt_text(llm.calls[1][0]))

    async def test_initial_context_and_new_human_messages_reach_the_llm(self):
        self.memory.add(Experience("earlier", "write a note", ["doc"], False, "wrong encoding",
                                   "Always use UTF-8 for the note."))

        async def human_addition(sandbox, kwargs):
            await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "请保留原始标题"))

        tool = ScriptedTool(hook=human_addition)
        worker, llm = self.worker([call(tool.name), final()], [tool])
        task = self.task(context="Use a short introduction.", files=["inbox/source.txt"])
        await worker.handle_task(task)
        initial = prompt_text(llm.calls[0][0])
        for value in (task.goal, task.context, "inbox/source.txt", "Always use UTF-8"):
            self.assertIn(value, initial)
        self.assertNotIn("请保留原始标题", initial)
        self.assertIn("请保留原始标题", prompt_text(llm.calls[1][0]))

    async def test_read_group_reads_the_current_dm_without_group_messages(self):
        channel = dm_channel(HUMAN, "worker")
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "group-only marker"))
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, "private detail"))
        worker, llm = self.worker([call("read_group", limit=10), final()])
        await worker.handle_task(self.task(origin=channel))
        observations = [message["content"] for message in llm.calls[1][0] if message["role"] == "tool"]
        self.assertIn("private detail", "\n".join(observations))
        self.assertNotIn("group-only marker", "\n".join(observations))

    async def test_failure_returns_before_reflection_and_updates_one_experience(self):
        worker, llm = self.worker([final(False, "failed to read input", failure_mode="tool_error"),
                                   LLMResponse("Check that the input file exists first.")])
        started, release = asyncio.Event(), asyncio.Event()
        original = worker.reflect

        async def blocked_reflection(task, result):
            started.set()
            await release.wait()
            await original(task, result)

        worker.reflect = blocked_reflection
        result = await asyncio.wait_for(worker.handle_task(self.task()), 2)
        self.assertFalse(result.success)
        await asyncio.wait_for(started.wait(), 2)
        self.assertEqual(self.memory.all()[0].lesson, "")
        release.set()
        await until(lambda: self.memory.all()[0].lesson)
        [experience] = self.memory.all()
        self.assertEqual(experience.task_id, result.task_id)
        self.assertIn("input file exists", experience.lesson)
        self.assertEqual(len(llm.calls), 2)

    async def test_private_message_uses_base_task_registration_and_reply(self):
        worker, _ = self.worker([final(summary="private response")])
        channel = dm_channel(HUMAN, "worker")
        self.spawn(worker.run())
        request = Message(MsgType.CHAT, HUMAN, channel, "write a note", receiver="worker")
        await self.bus.publish(request)
        await until(lambda: self.messages(MsgType.TASK_RESULT, channel))
        [reply] = self.messages(MsgType.TASK_RESULT, channel)
        self.assertEqual((reply.sender, reply.receiver, reply.reply_to), ("worker", HUMAN, request.id))
        result = TaskResult.from_dict(reply.payload["result"])
        self.assertEqual((result.success, result.summary), (True, "private response"))
        self.assertEqual(self.state.get(result.task_id).status, TaskStatus.DONE)
        self.assertEqual(self.messages(MsgType.TASK_RESULT), [])

    async def test_shutdown_cancels_pending_failure_reflection(self):
        worker, _ = self.worker([final(False, "failed")])
        started, interrupted = asyncio.Event(), asyncio.Event()

        async def blocked_reflection(task, result):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()

        worker.reflect = blocked_reflection
        channel = dm_channel(HUMAN, "worker")
        runner = self.spawn(worker.run())
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, "write a note", receiver="worker"))
        await until(lambda: self.messages(MsgType.TASK_RESULT, channel))
        await asyncio.wait_for(started.wait(), 2)
        runner.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(runner, 2)
        self.assertTrue(interrupted.is_set())
        [experience] = self.memory.all()
        self.assertFalse(experience.success)
        self.assertEqual(experience.lesson, "")

    async def test_private_cancel_command_interrupts_approval(self):
        tool = ScriptedTool("delete_file", approval=True)
        worker, _ = self.worker([call(tool.name)], [tool])
        channel = dm_channel(HUMAN, "worker")
        self.spawn(worker.run())
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, "remove the file", receiver="worker"))
        await until(lambda: self.messages(MsgType.HITL_REQUEST, channel))
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, "/cancel", receiver="worker"))
        await until(lambda: self.messages(MsgType.TASK_RESULT, channel))
        notices = [message for message in self.messages(MsgType.CHAT, channel)
                   if message.payload.get("cancelled_roots")]
        self.assertEqual(len(notices), 1)
        [reply] = self.messages(MsgType.TASK_RESULT, channel)
        result = TaskResult.from_dict(reply.payload["result"])
        self.assertEqual(result.error, "cancelled")
        self.assertEqual((tool.calls, self.memory.all()), ([], []))


if __name__ == "__main__":
    unittest.main()
