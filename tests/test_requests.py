"""RequestTracker: one request from arrival to final reply, /status, /cancel, additions, files."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.agents.base import Agent
from mas.agents.roles import ROLES
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
from mas.core.lead import CHOOSE_LEAD
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR, Message, MsgType, dm_channel
from mas.core.requests import RequestTracker
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from tests.test_router import FakeSandbox


class Worker(Agent):
    def __init__(self, *args, handler, **kw):
        super().__init__(*args, **kw)
        self.handler = handler
        self.tasks: list[Task] = []

    async def handle_task(self, task: Task) -> TaskResult:
        self.tasks.append(task)
        return await self.handler(self, task)


def choose(agent_id: str) -> LLMResponse:
    return LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": agent_id})])


async def _until(cond, timeout=2.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class TrackerTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bus = InMemoryBus()
        for a in ("human", "researcher", "coder", "writer"):
            self.bus.join(a, GROUP_MAIN)
        self.state = StateTable()
        self.sandboxes = {a: FakeSandbox(a, self.tmp / "ws" / a) for a in ("researcher", "coder", "writer")}
        self.settings = Settings(subtask_timeout_s=2.0, lead_timeout_s=3.0, data_dir=self.tmp / "data")
        self.router = Router(self.bus, self.state, self.sandboxes, self.settings)
        self.running: list[asyncio.Task] = []
        self.workers: dict[str, Worker] = {}

    async def asyncTearDown(self):
        await self.tracker.stop()
        for t in self.running:
            t.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, handlers=None, lead="coder", llm=None):
        """A tracker whose lead is `lead`, and workers {name: async handler(worker, task)}."""
        self.llm = llm or MockLLM(responder=lambda messages, tools: choose(lead))
        self.tracker = RequestTracker(self.bus, self.router, self.settings, self.llm, ROLES)
        for name in ("researcher", "coder", "writer"):
            w = Worker(name, self.bus, self.router, self.settings, handler=(handlers or {}).get(name, self.ok()))
            self.workers[name] = w
            self.running.append(asyncio.create_task(w.run()))

    @staticmethod
    def ok(summary="done", **kw):
        async def h(worker, task):
            return TaskResult(task.id, True, summary, **kw)
        return h

    def writes(self, file, content, summary="written"):
        async def h(worker, task):
            worker.router.sandboxes[worker.agent_id].write_text(file, content)
            return TaskResult(task.id, True, summary, artifacts=[file])
        return h

    @staticmethod
    def written(sandbox, name, seconds):
        """Set when a file was written, relative to now: two writes of one test can fall on the same clock tick."""
        when = time.time() + seconds
        os.utime(sandbox.resolve(name), (when, when))

    async def say(self, text, channel=GROUP_MAIN, **kw):
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, text, **kw))

    def finals(self):
        return [m for m in self.bus.history(GROUP_MAIN, 200) if m.payload.get("final")]

    def says(self, sender=ORCHESTRATOR):
        return [m for m in self.bus.history(GROUP_MAIN, 200) if m.type == MsgType.CHAT and m.sender == sender]

    async def final(self, n=1):
        await _until(lambda: len(self.finals()) >= n)
        return self.finals()[n - 1]


class RequestTest(TrackerTestBase):
    async def test_a_simple_request(self):
        self.start({"coder": self.writes("a.py", "print(1)", "wrote a.py")})
        await self.say("write a script")
        final = await self.final()
        self.assertEqual(final.content.split("\n")[0], "@human wrote a.py")
        self.assertEqual((final.sender, final.receiver, final.payload["success"], final.payload["lead"]),
                         ("coder", HUMAN, True, "coder"))
        self.assertIsNone(final.payload["failure_mode"])
        self.assertGreater(final.payload["duration"], 0)
        out = Path(final.payload["output_dir"])
        self.assertEqual((out.parent, re.fullmatch(r"R1-\d{8}-\d{6}", out.name) is not None),
                         (self.settings.output_dir, True))                  # data/output/<root>-<start time>
        self.assertEqual((out / "a.py").read_text(), "print(1)")
        self.assertIn(f"Deliverables: a.py (collected in {out})", final.content)
        self.assertEqual(final.payload["deliverables"], ["a.py"])
        outcome = self.tracker.outcomes["R1"]
        self.assertEqual((outcome.success, outcome.lead, outcome.deliverables), (True, "coder", ["a.py"]))

    async def test_the_request_goes_to_the_lead_whole_and_the_lead_is_not_an_orchestrator_agent(self):
        self.start()
        await self.say("write a script")
        await self.final()
        [task] = self.state.by_root("R1")
        self.assertEqual((task.assignee, task.requester, task.chain, task.goal),
                         ("coder", ORCHESTRATOR, [ORCHESTRATOR], "write a script"))
        self.assertEqual([t.id for t in self.workers["coder"].tasks], [task.id])
        self.assertNotIn(ORCHESTRATOR, self.bus.members(GROUP_MAIN))

    async def test_the_lead_is_chosen_once_and_the_second_request_continues_with_it(self):
        self.start({"coder": self.writes("a.py", "x")})
        await self.say("write a script")
        await self.final()
        await self.say("now extend it")
        await self.final(2)
        self.assertEqual(len(self.llm.calls), 1)                   # the second request cost no selection
        self.assertEqual([t.root_id for t in self.workers["coder"].tasks], ["R1", "R2"])
        self.assertIn("R1", self.router.board(GROUP_MAIN).render())

    async def test_without_a_lead_choice_the_first_role_leads(self):
        self.start(llm=MockLLM(responder=lambda m, t: LLMResponse("no idea")))
        await self.say("anything")
        final = await self.final()
        self.assertEqual(final.sender, "researcher")             # the first role of ROLES

    async def test_files_written_by_teammates_are_collected_when_the_lead_lists_none(self):
        async def lead(worker, task):
            await worker.call_agent(task, "writer", "write the doc")
            await worker.call_agent(task, "researcher", "find sources")
            return TaskResult(task.id, True, "all done")
        self.start({"coder": lead, "writer": self.writes("notes.md", "from writer"),
                    "researcher": self.writes("notes.md", "from researcher")})
        await self.say("do it")
        final = await self.final()
        out = Path(final.payload["output_dir"])
        self.assertEqual(sorted(final.payload["deliverables"]), ["notes.md", "researcher_notes.md"])   # no overwriting
        self.assertEqual((out / "notes.md").read_text(), "from writer")
        self.assertEqual((out / "researcher_notes.md").read_text(), "from researcher")

    async def test_only_the_files_the_lead_lists_are_delivered_even_from_teammates(self):
        async def lead(worker, task):
            await worker.call_agent(task, "writer", "write the doc")
            return TaskResult(task.id, True, "all done", artifacts=["final.md"])
        async def writer(worker, task):
            worker.router.sandboxes["writer"].write_text("final.md", "F")
            worker.router.sandboxes["writer"].write_text("scratch.md", "S")
            return TaskResult(task.id, True, "ok", artifacts=["final.md", "scratch.md"])
        self.start({"coder": lead, "writer": writer})
        await self.say("do it")
        final = await self.final()
        self.assertEqual(final.payload["deliverables"], ["final.md"])

    async def delivered(self, handlers, *requests):
        """The text of report.md as the human received it for the last of `requests`."""
        self.start(handlers)
        for n, text in enumerate(requests, 1):
            await self.say(text)
            final = await self.final(n)
        return (Path(final.payload["output_dir"]) / "report.md").read_text()

    async def test_the_leads_revision_of_a_teammates_draft_is_what_is_delivered(self):
        """On the course test set an editor wrote the draft, the lead revised its own copy through two review rounds,
        and the human received the first draft: a teammate's file of the same name always won."""
        async def lead(worker, task):
            await worker.call_agent(task, "writer", "draft the report")
            self.sandboxes["coder"].write_text("report.md", "revised after the reviews")
            self.written(self.sandboxes["coder"], "report.md", 60)
            await worker.call_agent(task, "researcher", "Review the revised report", files=["report.md"])
            return TaskResult(task.id, True, "ready", artifacts=["report.md"])
        text = await self.delivered({"coder": lead, "writer": self.writes("report.md", "first draft")}, "write the report")
        self.assertEqual(text, "revised after the reviews")
        self.assertEqual(self.sandboxes["researcher"].read_text("inbox/report.md"), text)    # what was reviewed

    async def test_the_text_a_teammate_was_given_to_revise_is_not_newer_than_its_revision(self):
        async def lead(worker, task):
            self.sandboxes["coder"].write_text("report.md", "the lead's outline")
            await worker.call_agent(task, "writer", "turn report.md into the full report", files=["report.md"])
            self.written(self.sandboxes["coder"], "report.md", 60)      # copied again later: still the old text
            return TaskResult(task.id, True, "ready", artifacts=["report.md"])
        text = await self.delivered({"coder": lead, "writer": self.writes("report.md", "the full report")}, "write it")
        self.assertEqual(text, "the full report")

    async def test_an_older_copy_of_the_lead_does_not_hide_what_a_teammate_wrote_since(self):
        async def lead(worker, task):
            if task.root_id == "R1":
                self.sandboxes["coder"].write_text("report.md", "last week's report")
                self.written(self.sandboxes["coder"], "report.md", -60)
            else:
                await worker.call_agent(task, "writer", "write this week's report")
            return TaskResult(task.id, True, "ready", artifacts=["report.md"])
        text = await self.delivered({"coder": lead, "writer": self.writes("report.md", "this week's report")},
                                    "write the report", "now this week's")
        self.assertEqual(text, "this week's report")

    async def test_a_missing_deliverable_is_reported(self):
        self.start({"coder": self.ok("done", artifacts=["ghost.md"])})
        await self.say("write it")
        final = await self.final()
        self.assertTrue(final.payload["success"])
        self.assertEqual(final.payload["deliverables"], [])
        self.assertEqual(final.payload["output_dir"], "")
        self.assertIn("(files not found: ghost.md)", final.content)

    async def test_a_failed_lead_is_reported_with_its_failure_mode(self):
        async def failing(worker, task):
            return TaskResult(task.id, False, "I tried.", error="tests keep failing",
                              failure_mode=FailureMode.WRONG_OUTPUT)
        self.start({"coder": failing})
        await self.say("write it")
        final = await self.final()
        self.assertEqual((final.payload["success"], final.payload["failure_mode"]), (False, "wrong_output"))
        self.assertIn("I tried.", final.content)
        self.assertIn("tests keep failing", final.content)
        self.assertFalse(self.tracker.outcomes["R1"].success)

    async def test_a_lead_that_crashes_ends_the_request_with_a_report(self):
        async def boom(worker, task):
            raise RuntimeError("kaput")
        self.start({"coder": boom})
        await self.say("write it")
        final = await self.final()
        self.assertEqual((final.payload["success"], final.payload["failure_mode"]), (False, "crash"))
        self.assertIn("kaput", final.content)

    async def test_a_bug_does_not_leave_the_root_open(self):
        self.start()
        with patch.object(Router, "dispatch", side_effect=RuntimeError("bug")):
            await self.say("write it")
            await _until(lambda: "R1" in self.tracker.outcomes)
        outcome = self.tracker.outcomes["R1"]
        self.assertEqual((outcome.success, outcome.failure_mode), (False, FailureMode.CRASH))
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertTrue(any("could not be handled" in m.content for m in self.says()))
        await self.say("try again")                           # and the next request still works
        await self.final()

    async def test_the_output_dir_is_not_reused_by_a_run_that_starts_in_the_same_second(self):
        self.start({"coder": self.writes("a.py", "x")})
        run = self.tracker._begin(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "x"), GROUP_MAIN)
        first = self.tracker._output_dir(run)
        first.mkdir(parents=True)
        self.assertEqual(self.tracker._output_dir(run), first.with_name(first.name + "-2"))
        self.tracker._runs.clear()


class IsRequestTest(unittest.TestCase):
    def test_which_messages_are_requests(self):
        def msg(**kw):
            base = dict(type=MsgType.CHAT, sender=HUMAN, channel=GROUP_MAIN, content="x")
            return Message(**{**base, **kw})
        is_request = RequestTracker.is_request
        self.assertTrue(is_request(msg()))
        self.assertTrue(is_request(msg(receiver=ORCHESTRATOR)))
        self.assertFalse(is_request(msg(mentions=["coder"])))
        self.assertFalse(is_request(msg(receiver="coder")))
        self.assertFalse(is_request(msg(sender="coder")))
        self.assertFalse(is_request(msg(channel=dm_channel(HUMAN, "coder"))))
        self.assertFalse(is_request(msg(type=MsgType.TASK_ASSIGN)))


class MessagesTest(TrackerTestBase):
    async def test_a_mention_goes_to_the_worker_not_the_request_layer(self):
        self.start()
        await self.say("@coder write a script", mentions=["coder"], receiver="coder")
        await _until(lambda: self.workers["coder"].tasks)
        self.assertEqual(self.tracker.outcomes, {})
        self.assertEqual(self.workers["coder"].tasks[0].requester, HUMAN)
        self.assertEqual(len(self.llm.calls), 0)


class AdditionTest(TrackerTestBase):
    async def test_a_message_while_a_request_runs_is_an_addition_not_a_new_root(self):
        release = asyncio.Event()

        async def slow(worker, task):
            await release.wait()
            return TaskResult(task.id, True, "done")
        self.start({"coder": slow})
        await self.say("write a script")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("use Python 3.11")
        await asyncio.sleep(0.05)
        self.assertEqual([t.root_id for t in self.state.in_session(GROUP_MAIN)], ["R1"])
        self.assertIn("use Python 3.11", self.router.board(GROUP_MAIN).roots["R1"].human_messages)
        release.set()
        await self.final()
        self.assertEqual(len(self.finals()), 1)

    async def test_after_it_finished_the_next_message_is_a_new_request(self):
        self.start()
        await self.say("one")
        await self.final()
        await self.say("two")
        second = await self.final(2)
        self.assertEqual(second.payload["root_id"], "R2")


class StatusTest(TrackerTestBase):
    async def test_status_answers_from_the_state_table_without_the_llm(self):
        release = asyncio.Event()

        async def slow(worker, task):
            await release.wait()
            return TaskResult(task.id, True, "done")
        self.start({"coder": slow})
        await self.say("write a script")
        await _until(lambda: self.workers["coder"].tasks)
        calls = len(self.llm.calls)
        await self.say("/status")
        await _until(lambda: any("R1" in m.content for m in self.says()))
        text = next(m.content for m in self.says() if "R1" in m.content)
        self.assertIn("coder", text)
        self.assertEqual(len(self.llm.calls), calls)                 # no LLM call for /status
        release.set()
        await self.final()

    async def test_status_with_nothing_to_report(self):
        self.start()
        await self.say("/status")
        await _until(lambda: self.says())
        self.assertEqual(self.says()[0].content, "No tasks in this session yet.")

    async def test_a_root_that_has_sent_nothing_yet_is_mentioned(self):
        gate = asyncio.Event()

        self.start()
        real = self.tracker.selector.choose

        async def choose_slowly(session, request):
            await gate.wait()
            return await real(session, request)
        self.tracker.selector.choose = choose_slowly
        await self.say("write a script")
        await _until(lambda: self.tracker._runs)
        await self.say("/status")
        await _until(lambda: self.says())
        self.assertIn("R1 is being worked on; no task has been sent out yet.", self.says()[0].content)
        gate.set()
        await self.final()


class CancelTest(TrackerTestBase):
    async def test_cancel_stops_the_running_request(self):
        started = asyncio.Event()

        async def slow(worker, task):
            started.set()
            await asyncio.sleep(10)
            return TaskResult(task.id, True, "late")
        self.start({"coder": slow})
        await self.say("write a script")
        await started.wait()
        await self.say("/cancel")
        await _until(lambda: any(m.payload.get("cancelled_roots") for m in self.says()))
        notice = next(m for m in self.says() if m.payload.get("cancelled_roots"))
        self.assertEqual((notice.content, notice.payload["cancelled_roots"]), ("Cancelled R1", ["R1"]))
        await _until(lambda: not self.tracker._runs)
        self.assertEqual(self.finals(), [])                          # a cancelled request gets no final reply
        self.assertEqual((self.tracker.outcomes["R1"].success, self.tracker.outcomes["R1"].summary), (False, "Cancelled"))

    async def test_cancel_with_nothing_running(self):
        self.start()
        await self.say("/cancel")
        await _until(lambda: self.says())
        self.assertEqual(self.says()[0].content, "No unfinished task to cancel")

    async def test_cancel_releases_a_pending_clarification(self):
        answers: list[str] = []

        async def asking(worker, task):
            answers.append(await worker.ask_human(task, "which version?", HitlKind.CLARIFY))
            return TaskResult(task.id, False, "", error="cancelled")
        self.start({"coder": asking})
        await self.say("write a script")
        await _until(lambda: any(m.type == MsgType.HITL_REQUEST for m in self.bus.history(GROUP_MAIN, 50)))
        await self.say("/cancel")
        await _until(lambda: answers)
        self.assertEqual(answers, [CANCELLED_ANSWER])

    async def test_a_new_request_after_a_cancel_works(self):
        started = asyncio.Event()
        calls = []

        async def worker(w, task):
            calls.append(task.id)
            if len(calls) == 1:
                started.set()
                await asyncio.sleep(10)
            return TaskResult(task.id, True, "fine")
        self.start({"coder": worker})
        await self.say("first")
        await started.wait()
        await self.say("/cancel")
        await _until(lambda: not self.tracker._runs)
        await self.say("second")
        final = await self.final()
        self.assertEqual((final.payload["root_id"], final.payload["success"]), ("R2", True))


if __name__ == "__main__":
    unittest.main()
