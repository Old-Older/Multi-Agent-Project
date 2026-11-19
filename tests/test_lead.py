"""Coordination "lead": choosing the lead (cache, fallback) and a request led by a worker."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.agents.roles import ROLES
from mas.app import build_system
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import HitlRequest, HumanIO
from mas.core.lead import CHOOSE_LEAD, LeadSelector
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.llm.base import LLMError, LLMResponse, ToolCall
from mas.llm.mock import MockLLM

WRITER = "Writes and edits Markdown"          # a phrase only the writer's capability contains
CODER = "Writes and runs Python code"


def call(id_, name, **args) -> ToolCall:
    return ToolCall(id_, name, args)


def reply(text="", *calls) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=list(calls))


def done(summary, artifacts=()) -> LLMResponse:
    return reply(json.dumps({"success": True, "summary": summary, "artifacts": list(artifacts)}))


async def _until(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class LeadSelectorTest(unittest.IsolatedAsyncioTestCase):
    def selector(self, *script, **kw) -> tuple[LeadSelector, MockLLM]:
        llm = MockLLM(script=list(script), **kw)
        return LeadSelector(llm, ROLES), llm

    async def test_the_llm_names_the_lead_and_the_choice_is_cached_per_session(self):
        sel, llm = self.selector(reply("", call("1", CHOOSE_LEAD, agent_id="coder", reason="code")))
        self.assertEqual(await sel.choose("s1", "build a thing"), "coder")
        self.assertEqual(await sel.choose("s1", "and now something else"), "coder")
        self.assertEqual(len(llm.calls), 1)                       # the second request cost no LLM call
        sel.llm = MockLLM([reply("", call("2", CHOOSE_LEAD, agent_id="writer"))])
        self.assertEqual(await sel.choose("s2", "write docs"), "writer")   # another session decides afresh

    async def test_the_prompt_shows_every_role(self):
        sel, llm = self.selector(reply("", call("1", CHOOSE_LEAD, agent_id="writer")))
        await sel.choose("s", "write a report")
        messages, tools = llm.calls[0]
        text = " ".join(m["content"] for m in messages)
        for role in ROLES.values():
            self.assertIn(role.agent_id, text)
            self.assertIn(role.capability, text)
        self.assertIn("write a report", text)
        self.assertEqual([t.name for t in tools], [CHOOSE_LEAD])

    async def test_an_llm_error_falls_back_to_the_first_role_and_is_not_cached(self):
        def failing(messages, tools):
            raise LLMError("down")
        sel, _ = self.selector(responder=failing)
        self.assertEqual(await sel.choose("s", "x"), "researcher")           # first role of ROLES
        self.assertNotIn("s", sel.cache)
        sel.llm = MockLLM([reply("", call("1", CHOOSE_LEAD, agent_id="writer"))])
        self.assertEqual(await sel.choose("s", "x"), "writer")               # next request asks again

    async def test_unusable_answers_fall_back(self):
        for response in (reply("I think the best one is somebody"), reply("", call("1", CHOOSE_LEAD, agent_id="nobody")),
                         reply("", call("1", "other_tool", agent_id="coder")), reply("")):
            sel, _ = self.selector(response)
            self.assertEqual(await sel.choose("s", "x"), "researcher")
            self.assertNotIn("s", sel.cache)

    async def test_a_plain_answer_that_is_just_an_id_is_accepted(self):
        sel, _ = self.selector(reply(" `coder`. "))
        self.assertEqual(await sel.choose("s", "x"), "coder")

    async def test_a_single_role_leads_without_a_call(self):
        llm = MockLLM()
        sel = LeadSelector(llm, {"coder": ROLES["coder"]})
        self.assertEqual(await sel.choose("s", "x"), "coder")
        self.assertEqual(llm.calls, [])

    async def test_a_team_needs_a_role(self):
        with self.assertRaises(ValueError):
            LeadSelector(MockLLM(), {})


class ScriptedHuman(HumanIO):
    """A human that answers every question with the next scripted answer and keeps what it saw."""

    def __init__(self, answers=()) -> None:
        self.answers = list(answers)
        self.seen: list[Message] = []

    async def run(self, bus) -> None:
        inbox = bus.subscribe(HUMAN)
        while True:
            await self.handle_incoming(bus, await inbox.get())

    async def show(self, msg: Message) -> None:
        self.seen.append(msg)

    async def answer(self, req: HitlRequest) -> str:
        return self.answers.pop(0) if self.answers else "ok"


class LeadSystemBase(unittest.IsolatedAsyncioTestCase):
    """A real system (bus, router, workers with real workspaces); only the LLM is scripted."""

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws",
                                 subtask_timeout_s=10.0, lead_timeout_s=20.0)
        self.lead_choices = 0
        self.human = ScriptedHuman()
        self.system = build_system(self.settings, MockLLM(responder=self.brain), self.human, roles=ROLES)
        self.tasks = [asyncio.create_task(self.human.run(self.system.bus))]
        self.system.start()

    async def asyncTearDown(self):
        await self.system.stop()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # the "LLM": one function that plays the selector, the writer (lead) and the coder
    def brain(self, messages, tools):
        system = messages[0]["content"]
        if "You assign the lead" in system:
            self.lead_choices += 1
            return reply("", call("c", CHOOSE_LEAD, agent_id="writer"))
        user = messages[1]["content"]
        tool_results = [m["content"] for m in messages if m["role"] == "tool"]
        if CODER in system:
            if not tool_results:
                return reply("", call("w", "write_file", path="script.py", content="print(1)\n"))
            return done("wrote script.py", ["script.py"])
        assert WRITER in system, system[:200]
        if "ask me" in user:
            if not tool_results:
                return reply("", call("q", "ask_human", question="Which room size?", options=["small", "large"]))
            return done(f"planned with answer {json.loads(tool_results[0])['output']}")
        if "extend" in user:
            if not tool_results:
                return reply("", call("d", "call_coder", goal="extend the script", files=["script.py"]))
            return done("extended", ["script.py"])
        if not tool_results:
            return reply("", call("d", "call_coder", goal="write script.py"))
        return done("Built script.py", ["script.py"])

    async def ask(self, text, n=1):
        await self.system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, text))
        await _until(lambda: len(self.finals()) >= n)
        return self.finals()[n - 1]

    def finals(self):
        return [m for m in self.system.bus.history(GROUP_MAIN, 500) if m.payload.get("final")]

    def of(self, type_):
        return [m for m in self.system.bus.history(GROUP_MAIN, 500) if m.type == type_]


class LeadRequestTest(LeadSystemBase):
    async def test_the_lead_delegates_and_reports_in_its_own_name(self):
        final = await self.ask("build me a script")
        self.assertEqual(final.sender, "writer")                  # the lead speaks, not the Orchestrator
        self.assertEqual(final.receiver, HUMAN)
        self.assertEqual(final.payload["lead"], "writer")
        self.assertTrue(final.payload["success"])
        self.assertEqual(final.payload["deliverables"], ["script.py"])
        out = Path(final.payload["output_dir"]) / "script.py"
        self.assertEqual(out.read_text(), "print(1)\n")            # written by the coder, collected from its workspace
        assigns = {(m.sender, m.receiver) for m in self.of(MsgType.TASK_ASSIGN)}
        self.assertEqual(assigns, {("orchestrator", "writer"), ("writer", "coder")})
        tasks = {t.assignee: t for t in self.system.state.by_root(final.payload["root_id"])}
        self.assertEqual(tasks["writer"].chain, ["orchestrator"])
        self.assertEqual(tasks["coder"].chain, ["orchestrator", "writer"])
        self.assertIn("lead", final.payload)

    async def test_the_lead_is_chosen_once_per_session(self):
        await self.ask("build me a script")
        await self.ask("extend it", n=2)
        self.assertEqual(self.lead_choices, 1)
        self.assertEqual(self.finals()[1].sender, "writer")

    async def test_a_follow_up_request_finds_the_files_of_the_first_one(self):
        first = await self.ask("build me a script")
        second = await self.ask("extend it", n=2)
        self.assertNotEqual(first.payload["root_id"], second.payload["root_id"])
        self.assertTrue(second.payload["success"], second.content)
        self.assertEqual(self.system.sandboxes["coder"].read_text("inbox/script.py"), "print(1)\n")

    async def test_the_lead_asks_the_human_in_its_own_name(self):
        self.human.answers = ["large"]
        final = await self.ask("plan it, but ask me first")
        requests = [m for m in self.human.seen if m.type == MsgType.HITL_REQUEST]
        self.assertEqual([m.sender for m in requests], ["writer"])
        self.assertEqual(requests[0].payload["kind"], "clarify")
        self.assertIn("large", final.content)


class LeadFailureTest(LeadSystemBase):
    def brain(self, messages, tools):
        system = messages[0]["content"]
        if "You assign the lead" in system:
            return reply("", call("c", CHOOSE_LEAD, agent_id="writer"))
        if CODER in system:
            return reply(json.dumps({"success": False, "summary": "", "error": "tests keep failing"}))
        tool_results = [m["content"] for m in messages if m["role"] == "tool"]
        if not tool_results:
            return reply("", call("d", "call_coder", goal="write script.py"))
        return reply(json.dumps({"success": False, "summary": "The coder could not finish.", "error": "coder failed",
                                 "failure_mode": "wrong_output"}))

    async def test_a_failed_lead_reports_the_failure(self):
        final = await self.ask("build me a script")
        self.assertFalse(final.payload["success"])
        self.assertEqual(final.payload["failure_mode"], "wrong_output")
        self.assertEqual(final.sender, "writer")
        self.assertEqual(final.payload["deliverables"], [])
        self.assertEqual(self.system.requests.outcomes[final.payload["root_id"]].success, False)


if __name__ == "__main__":
    unittest.main()
