"""Orchestrator: the request loop, /status, /cancel, interjections (design §2, §3)."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.orchestrator import Orchestrator
from mas.agents.roles import ROLES
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CANCELLED_ANSWER
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType, dm_channel
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.llm.base import LLMError, LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.memory.base import Memory
from tests.test_router import FakeSandbox


class Worker(Agent):
    def __init__(self, *args, handler, **kw):
        super().__init__(*args, **kw)
        self.handler = handler
        self.tasks: list[Task] = []

    async def handle_task(self, task: Task) -> TaskResult:
        self.tasks.append(task)
        return await self.handler(task)


def call(id_, name, **args) -> ToolCall:
    return ToolCall(id_, name, args)


def reply(text="", *calls) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=list(calls))


def finish(summary="all done", deliverables=None, id_="f") -> ToolCall:
    return call(id_, "finish", summary=summary, deliverables=deliverables or [])


async def _until(cond, timeout=2.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class OrchestratorTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bus = InMemoryBus()
        for a in ("human", "orchestrator", "researcher", "coder", "writer"):
            self.bus.join(a, GROUP_MAIN)
        self.state = StateTable()
        self.sandboxes = {a: FakeSandbox(a, self.tmp / "ws" / a) for a in ("researcher", "coder", "writer")}
        self.settings = Settings(subtask_timeout_s=2.0, data_dir=self.tmp / "data")
        self.router = Router(self.bus, self.state, self.sandboxes, self.settings)
        self.memories: dict[str, Memory] = {}
        self.running: list[asyncio.Task] = []
        self.workers: dict[str, Worker] = {}

    async def asyncTearDown(self):
        for t in self.running:
            t.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, script=None, responder=None, workers=None):
        """Start the Orchestrator (with a scripted LLM) and the workers {name: handler}."""
        self.llm = MockLLM(script=script, responder=responder)
        self.orch = Orchestrator(self.bus, self.router, self.settings, self.llm, ROLES, self.memories)
        self.running.append(asyncio.create_task(self.orch.run()))
        for name, handler in (workers or {"coder": self.ok(), "writer": self.ok(), "researcher": self.ok()}).items():
            w = Worker(name, self.bus, self.router, self.settings, handler=handler)
            self.workers[name] = w
            self.running.append(asyncio.create_task(w.run()))

    @staticmethod
    def ok(summary="done", **kw):
        async def h(task):
            return TaskResult(task.id, True, summary, **kw)
        return h

    def writes(self, name, file, content, summary="written"):
        """A worker that writes `file` into its workspace and reports it as an artifact."""
        async def h(task):
            self.sandboxes[name].write_text(file, content)
            return TaskResult(task.id, True, summary, artifacts=[file])
        return h

    async def say(self, text, channel=GROUP_MAIN, **kw):
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, text, **kw))

    def finals(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 200) if m.payload.get("final")]

    def chats(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 200) if m.type == MsgType.CHAT and m.sender == "orchestrator"]

    async def final(self, channel=GROUP_MAIN, n=1):
        await _until(lambda: len(self.finals(channel)) >= n)
        return self.finals(channel)[n - 1]

    def tool_results(self, call_index=-1):
        """The tool messages the LLM saw in its `call_index`-th call."""
        messages, _ = self.llm.calls[call_index]
        return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


class LoopTest(OrchestratorTestBase):
    async def test_a_simple_request(self):
        self.start([reply("Remaining steps: write a script", call("1", "call_coder", goal="write a script")),
                    reply("", finish("script ready", ["a.py"]))],
                   workers={"coder": self.writes("coder", "a.py", "print(1)", "wrote a.py")})
        await self.say("write a script")
        final = await self.final()
        self.assertEqual(final.content.split("\n")[0], "@human script ready")
        self.assertEqual((final.sender, final.receiver, final.payload["success"], final.payload["rounds"]),
                         ("orchestrator", HUMAN, True, 2))
        out = self.settings.output_dir / "R1"
        self.assertEqual((out / "a.py").read_text(), "print(1)")
        self.assertIn(f"Deliverables: a.py (collected in {out})", final.content)
        self.assertEqual(final.payload["deliverables"], ["a.py"])
        outcome = self.orch.outcomes["R1"]
        self.assertEqual((outcome.success, outcome.rounds, outcome.failure_mode, outcome.deliverables),
                         (True, 2, None, ["a.py"]))
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.DONE])
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertEqual(self.orch._runs, {})                          # nothing left running

    async def test_what_the_llm_sees(self):
        self.start([reply("Remaining steps: write a script", call("1", "call_coder", goal="write a script")), reply("", finish())],
                   workers={"coder": self.writes("coder", "a.py", "x", "very long details" * 400)})
        await self.say("write a script")
        await self.final()
        first, tools = self.llm.calls[0]
        self.assertEqual([m["role"] for m in first], ["system", "user"])
        self.assertIn("Human request: write a script", first[1]["content"])
        self.assertIn("Session board", first[1]["content"])
        self.assertEqual([t.name for t in tools], ["call_researcher", "call_coder", "call_writer", "ask_human", "finish"])
        second, _ = self.llm.calls[1]
        self.assertEqual([m["role"] for m in second], ["system", "user", "assistant", "tool"])
        self.assertEqual(second[2]["tool_calls"][0]["function"]["name"], "call_coder")
        self.assertEqual(second[2]["content"], "Remaining steps: write a script")
        seen = json.loads(second[3]["content"])
        self.assertEqual((seen["success"], seen["artifacts"]), (True, ["a.py"]))
        self.assertLessEqual(len(seen["summary"]), self.settings.result_summary_max_chars)   # a summary, not the full text
        self.assertEqual(second[3]["tool_call_id"], "1")

    async def test_the_plan_line_goes_to_the_board(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("Remaining steps: write a script, then the docs", call("1", "call_coder", goal="write a script")), reply("", finish())],
                   workers={"coder": slow})
        await self.say("do something")
        await _until(lambda: self.workers["coder"].tasks)
        self.assertEqual(self.router.board(GROUP_MAIN).roots["R1"].plan, "Remaining steps: write a script, then the docs")
        gate.set()
        await self.final()

    async def test_calls_in_one_round_run_in_parallel(self):
        gate = asyncio.Event()
        order: list[str] = []

        async def first(task):
            order.append("coder started")
            await gate.wait()                               # only released once the writer has started
            order.append("coder done")
            return TaskResult(task.id, True, "code")

        async def second(task):
            order.append("writer started")
            gate.set()
            return TaskResult(task.id, True, "docs")
        self.start([reply("", call("1", "call_coder", goal="write code"), call("2", "call_writer", goal="write the docs")),
                    reply("", finish())], workers={"coder": first, "writer": second})
        await self.say("code and docs")
        await self.final()
        self.assertEqual(order[:2], ["coder started", "writer started"])
        results = self.tool_results()
        self.assertEqual([r["summary"] for r in results], ["code", "docs"])        # in the order of the calls

    async def test_a_declined_task_is_reassigned(self):
        async def decline(task):
            return TaskResult(task.id, False, "needs to run code", declined=True, suggest="coder", error="needs to run code")
        self.start([reply("", call("1", "call_writer", goal="run the tests")),
                    reply("", call("2", "call_coder", goal="run the tests")), reply("", finish())],
                   workers={"writer": decline, "coder": self.ok("tests finished")})
        await self.say("run the tests")
        await self.final()
        declined = self.tool_results(1)[0]
        self.assertEqual((declined["declined"], declined["suggest"], declined["reason"]), (True, "coder", "needs to run code"))
        self.assertEqual({t.assignee: t.status for t in self.state.by_root("R1")},
                         {"writer": TaskStatus.DECLINED, "coder": TaskStatus.DONE})

    async def test_a_failure_is_an_observation_not_an_exception(self):
        async def fail(task):
            return TaskResult(task.id, False, "", error="pip timed out", failure_mode=FailureMode.TOOL_ERROR)
        self.start([reply("", call("1", "call_coder", goal="install packages")), reply("", finish("could not install"))],
                   workers={"coder": fail})
        await self.say("install packages")
        final = await self.final()
        self.assertEqual(self.tool_results(1), [{"success": False, "error": "pip timed out"}])
        self.assertEqual(final.payload["success"], True)           # the LLM chose to finish and say so

    async def test_files_are_handed_to_the_next_agent(self):
        self.start([reply("", call("1", "call_researcher", goal="research")),
                    reply("", call("2", "call_coder", goal="write a script", files=["notes.md"])), reply("", finish())],
                   workers={"researcher": self.writes("researcher", "notes.md", "key points"), "coder": self.ok()})
        await self.say("research and write a script")
        await self.final()
        self.assertEqual((self.tmp / "ws" / "coder" / "inbox" / "notes.md").read_text(), "key points")

    async def test_rounds_run_out(self):
        self.settings.max_orchestrator_rounds = 2
        self.start(responder=lambda m, t: reply("", call(str(len(m)), "call_coder", goal=f"step {len(m)}")),
                   workers={"coder": self.writes("coder", "part.md", "half-finished work", "did part of it")})
        await self.say("a very big task")
        final = await self.final()
        self.assertEqual(len(self.llm.calls), 2)
        self.assertEqual((final.payload["success"], final.payload["failure_mode"], final.payload["rounds"]),
                         (False, "max_rounds", 2))
        self.assertIn("Used all 2 rounds", final.content)
        self.assertIn("did part of it", final.content)                     # what was done is reported
        self.assertTrue((self.settings.output_dir / "R1" / "part.md").exists())    # and the partial files kept
        self.assertEqual(self.orch.outcomes["R1"].failure_mode, FailureMode.MAX_ROUNDS)

    async def test_text_without_tools_is_taken_as_the_answer(self):
        self.start([reply("1+1 equals 2")])
        await self.say("What is 1+1?")
        final = await self.final()
        self.assertEqual((final.content, final.payload["success"]), ("@human 1+1 equals 2", True))
        self.assertEqual(self.state.by_root("R1"), [])

    async def test_an_empty_response_costs_a_round_and_gets_a_nudge(self):
        self.start([reply(""), reply("", finish("finished"))])
        await self.say("do something")
        final = await self.final()
        self.assertEqual(final.payload["rounds"], 2)
        self.assertIn("Please call a tool", self.llm.calls[1][0][-1]["content"])

    async def test_bad_tool_calls_are_observations(self):
        self.start([reply("", call("1", "call_nobody", goal="x"), call("2", "call_coder"), call("3", "dance")),
                    reply("", finish())])
        await self.say("do something")
        await self.final()
        errors = [r["error"] for r in self.tool_results(1)]
        self.assertEqual(errors, ["no such agent: nobody", "missing argument goal", "no such tool: dance"])

    async def test_finish_must_be_called_alone(self):
        self.start([reply("", call("1", "call_coder", goal="write a script"), finish("too early")),
                    reply("", finish("got it right this time"))])
        await self.say("write a script")
        final = await self.final()
        self.assertEqual(final.content.split("\n")[0], "@human got it right this time")
        self.assertIn("finish must be called alone", self.tool_results(1)[1]["error"])

    async def test_a_missing_deliverable_is_reported(self):
        self.start([reply("", finish("finished", ["ghost.md"]))])
        await self.say("do something")
        final = await self.final()
        self.assertIn("files not found: ghost.md", final.content)
        self.assertEqual(final.payload["deliverables"], [])

    async def test_an_llm_error_ends_the_request_with_a_report(self):
        def boom(messages, tools):
            raise LLMError("429 rate limited")
        self.start(responder=boom)
        await self.say("do something")
        final = await self.final()
        self.assertEqual((final.payload["success"], final.payload["failure_mode"]), (False, "crash"))
        self.assertIn("LLM call failed: 429 rate limited", final.content)

    async def test_a_bug_does_not_leave_the_root_open(self):
        def bug(messages, tools):
            raise ValueError("program bug")
        self.start(responder=bug)
        with self.assertLogs("mas.agents.base", level="ERROR"):
            await self.say("do something")
            await _until(lambda: [m for m in self.chats() if "internal error" in m.content])
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertEqual((self.orch._runs, self.orch.outcomes["R1"].failure_mode), ({}, FailureMode.CRASH))

    async def test_the_second_request_sees_the_first_on_the_board(self):
        self.start([reply("", finish("meeting minutes are ready", [])), reply("", finish("translated"))])
        await self.say("summarize the meeting minutes")
        await self.final()
        await self.say("translate the minutes from just now into English")
        await self.final(n=2)
        second_first_call = self.llm.calls[1][0][1]["content"]
        self.assertIn("R1 meeting minutes are ready", second_first_call)
        self.assertEqual(sorted(self.orch.outcomes), ["R1", "R2"])


class ClarifyTest(OrchestratorTestBase):
    async def test_ask_human_and_use_the_answer(self):
        self.start([reply("", call("1", "ask_human", question="which version?", options=["3.10", "3.11"])),
                    reply("", call("2", "call_coder", goal="write the script with 3.11")), reply("", finish())])
        await self.say("write a script")
        await _until(lambda: [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST])
        [req] = [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST]
        self.assertEqual((req.sender, req.payload["task_id"], req.payload["kind"], req.payload["options"]),
                         ("orchestrator", None, "clarify", ["3.10", "3.11"]))
        self.assertEqual(self.state.by_root("R1"), [])                # a question is not a task
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN,
                                       payload={"request_id": "h1", "answer": "3.11"}))
        await self.final()
        self.assertEqual(self.tool_results(1), [{"answer": "3.11"}])
        self.assertIn("h1 \"which version?\" -> 3.11", self.router.board(GROUP_MAIN).render())    # the board kept the decision


class MessagesTest(OrchestratorTestBase):
    def orch_for_rules(self) -> Orchestrator:
        return Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES, {})

    def test_which_messages_are_for_the_orchestrator(self):
        o = self.orch_for_rules()
        chat = lambda **kw: Message(MsgType.CHAT, **{"sender": HUMAN, "channel": GROUP_MAIN, "content": "hi", **kw})
        self.assertTrue(o.should_handle(chat()))                                   # no @: the Orchestrator answers
        self.assertTrue(o.should_handle(chat(receiver="orchestrator")))
        self.assertTrue(o.should_handle(chat(mentions=["orchestrator"])))
        self.assertFalse(o.should_handle(chat(mentions=["coder"], receiver="coder")))   # @coder: only coder
        self.assertFalse(o.should_handle(chat(mentions=["coder", "writer"])))
        self.assertFalse(o.should_handle(chat(sender="coder")))                    # agents' chat is ignored
        self.assertFalse(o.should_handle(chat(sender="orchestrator")))
        self.assertFalse(o.should_handle(chat(channel=dm_channel(HUMAN, "coder"))))   # someone else's DM

    async def test_dm_to_the_orchestrator_runs_in_that_session(self):
        dm = dm_channel(HUMAN, "orchestrator")
        self.start([reply("the answer in the DM")])
        await self.say("hello", channel=dm, receiver="orchestrator")
        final = await self.final(channel=dm)
        self.assertEqual(final.channel, dm)
        self.assertEqual(self.finals(GROUP_MAIN), [])
        self.assertTrue(self.router.board(dm).roots["R1"].finished)

    async def test_a_mention_goes_to_the_worker_not_the_orchestrator(self):
        self.start([reply("should not be called")])
        await self.say("@coder write a script", mentions=["coder"], receiver="coder")
        await _until(lambda: self.workers["coder"].tasks)
        self.assertEqual(self.llm.calls, [])


class InterjectionTest(OrchestratorTestBase):
    async def test_a_message_while_a_root_runs_is_an_addition_not_a_new_root(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("", call("1", "call_coder", goal="write a script")), reply("", finish("switched to 3.11"))],
                   workers={"coder": slow})
        await self.say("write a script")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("use Python 3.11 for the script")
        await asyncio.sleep(0.02)
        self.assertEqual(list(self.router.board(GROUP_MAIN).roots), ["R1"])      # still one root
        self.assertIn("use Python 3.11 for the script", self.router.board(GROUP_MAIN).render())
        gate.set()
        await self.final()
        second, _ = self.llm.calls[1]
        self.assertEqual(second[-1], {"role": "user", "content": "(Human addition) use Python 3.11 for the script"})
        self.assertEqual(len(self.llm.calls), 2)

    async def test_after_it_finished_the_next_message_is_a_new_request(self):
        self.start([reply("", finish("one")), reply("", finish("two"))])
        await self.say("first thing")
        await self.final()
        await self.say("second thing")
        await self.final(n=2)
        self.assertEqual(sorted(self.orch.outcomes), ["R1", "R2"])


class StatusTest(OrchestratorTestBase):
    async def test_status_answers_from_the_state_table_without_the_llm(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("", call("1", "call_coder", goal="write a script")), reply("", finish())], workers={"coder": slow})
        await self.say("write a script")
        await _until(lambda: self.workers["coder"].tasks)
        calls_before = len(self.llm.calls)
        await self.say("/status", receiver="orchestrator")
        await _until(lambda: [m for m in self.chats() if "1 in progress" in m.content])
        [status] = [m for m in self.chats() if "in progress" in m.content]
        self.assertIn("R1: 1 task, 1 in progress", status.content)
        self.assertIn("coder [running] \"write a script\"", status.content)
        self.assertEqual(len(self.llm.calls), calls_before)                         # no LLM call
        gate.set()
        await self.final()

    async def test_status_with_nothing_to_report(self):
        self.start([])
        await self.say("/status", receiver="orchestrator")
        await _until(lambda: self.chats())
        self.assertEqual(self.chats()[0].content, "No tasks in this session yet.")

    async def test_a_root_that_has_sent_nothing_yet_is_mentioned(self):
        gate = asyncio.Event()

        self.start(script=[reply("", finish())])
        self.orch.llm.chat = lambda messages, tools=None, temperature=0.2: _wait_then(gate, reply("", finish()))
        await self.say("do something")
        await _until(lambda: self.orch._runs)
        self.assertIn("R1 is being worked on; no task has been sent out yet.", self.orch.status_text(GROUP_MAIN))
        gate.set()
        await self.final()


async def _wait_then(gate, value):
    await gate.wait()
    return value


class CancelTest(OrchestratorTestBase):
    async def test_cancel_stops_the_running_request(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "too late")
        self.start([reply("", call("1", "call_coder", goal="write a script")), reply("", finish("should not get here"))],
                   workers={"coder": slow})
        await self.say("write a script")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: [m for m in self.chats() if m.payload.get("cancelled_roots")])
        [notice] = [m for m in self.chats() if m.payload.get("cancelled_roots")]
        self.assertEqual((notice.content, notice.payload["cancelled_roots"]), ("Cancelled R1", ["R1"]))
        await _until(lambda: not self.orch._runs)
        self.assertEqual(len(self.llm.calls), 1)                                     # the loop did not go on
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.CANCELLED])
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertEqual(self.orch.outcomes["R1"].summary, "Cancelled")
        self.assertEqual(self.finals(), [])                                          # no "all done" report
        gate.set()                                                                   # the worker finishes anyway
        await asyncio.sleep(0.05)
        self.assertEqual(self.state.by_root("R1")[0].status, TaskStatus.CANCELLED)

    async def test_cancel_while_the_llm_is_thinking(self):
        gate = asyncio.Event()
        self.start([])
        self.orch.llm.chat = lambda messages, tools=None, temperature=0.2: _wait_then(gate, reply("", finish()))
        await self.say("do something")
        await _until(lambda: self.orch._runs)
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: not self.orch._runs)
        [notice] = [m for m in self.chats() if m.payload.get("cancelled_roots")]
        self.assertEqual(notice.payload["cancelled_roots"], ["R1"])                  # a root with no task yet
        self.assertIn("R1", self.router._cancelled_roots)                            # so its further calls are refused
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)

    async def test_cancel_releases_a_pending_clarification(self):
        self.start([reply("", call("1", "ask_human", question="which version?"))])
        await self.say("write a script")
        await _until(lambda: [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST])
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: not self.orch._runs)
        self.assertEqual(self.router._hitl_waiters, {})

    async def test_cancel_with_nothing_running(self):
        self.start([])
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: self.chats())
        self.assertEqual((self.chats()[0].content, self.chats()[0].payload), ("No unfinished task to cancel", {"cancelled_roots": []}))

    async def test_a_new_request_after_a_cancel_works(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("", call("1", "call_coder", goal="write a script")), reply("", finish("second one done"))],
                   workers={"coder": slow})
        await self.say("first time")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: not self.orch._runs)
        await self.say("second time")
        final = await self.final()
        self.assertEqual(final.payload["root_id"], "R2")
        self.assertEqual(final.content.split("\n")[0], "@human second one done")


class SpecsTest(OrchestratorTestBase):
    class FakeMemory(Memory):
        def __init__(self, text="", fail=False):
            self.text, self.fail = text, fail

        def add(self, exp): ...
        def recall(self, query, k=3): return []

        def profile(self, max_chars=300):
            if self.fail:
                raise NotImplementedError
            return self.text

    def specs(self):
        return {s.name: s for s in Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES,
                                                self.memories).function_specs(GROUP_MAIN)}

    def test_profiles_are_appended_to_the_tool_descriptions(self):
        self.memories = {"coder": self.FakeMemory("Recent performance: code 8/10 succeeded.")}
        specs = self.specs()
        self.assertIn("Recent performance: code 8/10 succeeded.", specs["call_coder"].description)
        self.assertIn(ROLES["coder"].capability, specs["call_coder"].description)
        self.assertNotIn("Recent performance", specs["call_writer"].description)                # no memory: no profile
        self.assertEqual(list(specs), ["call_researcher", "call_coder", "call_writer", "ask_human", "finish"])

    def test_a_memory_that_cannot_give_a_profile_does_not_break_anything(self):
        self.memories = {"coder": self.FakeMemory(fail=True)}
        with self.assertLogs("mas.agents.orchestrator", level="ERROR"):
            self.assertEqual(self.specs()["call_coder"].description, ROLES["coder"].capability)

    def test_the_system_prompt_names_the_agents_and_the_rules(self):
        text = Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES, {}).system_prompt()
        for needle in ("call_coder", "call_researcher", "call_writer", "same round", "finish", "Remaining steps", "declined"):
            self.assertIn(needle, text)

    async def test_handle_task_is_never_used(self):
        o = Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES, {})
        with self.assertRaises(NotImplementedError):
            await o.handle_task(Task(goal="x", assignee="orchestrator", requester="human", session_id="s",
                                     root_id="R1", origin_channel=GROUP_MAIN))


if __name__ == "__main__":
    unittest.main()
