"""An invitation to consult the requester is taken up with ONE question, asked before the work is handed out."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent, _Run
from mas.app import build_system
from mas.config import Settings
from mas.core.board import HitlEntry
from mas.core.human import AutoResponder
from mas.core.lead import CHOOSE_LEAD
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from tests.test_budget import BudgetCase
from tests.test_requirements import Recorder, met, reqs
from tests.test_worker import final

TOPIC = "Consult the requester about the choice of story and the audience's needs."


class ConsultGateTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.settings.requirements_check = True
        self.settings.finish_not_before = 0.0

    async def lead(self, script, now=70.0):
        task = self.task()
        self.now[0] = now                                  # 30 s of 100 left: a delegation that gets through is refused for time
        worker, llm = self.member(script, lead=True)
        return task, worker, await asyncio.wait_for(worker.handle_task(task), 3), llm

    def observations(self, llm):
        return [json.loads(m["content"]) for m in llm.calls[-1][0] if m["role"] == "tool"]

    async def test_the_first_delegation_is_held_back_once_and_every_call_of_that_reply_with_it(self):
        two = LLMResponse("", [ToolCall("c1", "call_mate", {"goal": "research it"}),
                               ToolCall("c2", "call_mate", {"goal": "write it"})])
        _, _, result, llm = await self.lead([reqs(TOPIC, "ten slides"), two, LLMResponse("", [
            ToolCall("c3", "call_mate", {"goal": "research it"})]), final(requirements=met("REQ2"))])
        held1, held2, passed = self.observations(llm)
        for held in (held1, held2):
            self.assertFalse(held["ok"])
            self.assertIn("Not yet. The request invites you to consult the human (" + TOPIC, held["output"])
            self.assertIn("ask ONE question now with ask_human", held["output"])
        self.assertIn("Not enough time left", passed["output"])                   # the next reply is not held back: it went on
        self.assertTrue(result.success)

    async def test_without_an_invitation_nothing_is_held_back(self):
        _, _, result, llm = await self.lead([reqs("ten slides"), LLMResponse("", [
            ToolCall("c1", "call_mate", {"goal": "write it"})]), final(requirements=met("REQ1"))])
        self.assertIn("Not enough time left", self.observations(llm)[0]["output"])

    async def test_a_lead_that_never_asked_has_it_reported_as_not_met_and_is_not_sent_back_for_it(self):
        _, _, result, llm = await self.lead([reqs(TOPIC, "ten slides"), final(requirements=met("REQ2"))])
        self.assertEqual(len(llm.calls), 2)                                      # the list, the answer: no push about REQ1
        by_id = {e["id"]: e for e in result.requirements}
        self.assertEqual((by_id["REQ1"]["status"], by_id["REQ1"]["evidence"]), ("not_met", "the human was not asked anything"))
        self.assertIn("- REQ1 (" + TOPIC + "): not met. the human was not asked anything", result.summary)
        self.assertEqual(by_id["REQ2"]["status"], "met")

    async def test_a_question_put_to_the_human_by_a_teammate_counts_too(self):
        task = self.task()
        self.router.set_requirements(task.root_id, [TOPIC])
        self.router.board(GROUP_MAIN).hitl["h1"] = HitlEntry("h1", task.root_id, "Which  story do you prefer?")
        worker, _ = self.member([final()], lead=True)
        run = _Run(deadline=time.perf_counter() + 30)
        self.assertEqual(worker._human_asked(task, run), "Which story do you prefer?")
        self.assertEqual(worker._consult_gate(task, run), "")
        # a question of another request does not count
        self.router.board(GROUP_MAIN).hitl["h1"].root_id = "R99"
        self.assertEqual(worker._human_asked(task, run), "")
        self.assertNotEqual(worker._consult_gate(task, run), "")

    async def test_the_extraction_asks_for_one_requirement_for_all_the_invitations(self):
        task = self.task()
        worker, llm = self.member([reqs(TOPIC)], lead=True)
        await worker._extract_requirements(task, _Run(deadline=time.perf_counter() + 30))
        prompt = llm.calls[0][0][0]["content"]
        self.assertIn("write ONE requirement for all such invitations", prompt)
        self.assertIn("starting with the words 'Consult the requester about'", prompt)
        self.assertNotIn("leave out what is only permitted", prompt)


class ConsultEndToEndTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    async def run_request(self, steps):
        """The lead's `steps` ((tool, arguments), one per reply), then it answers. Returns (what the teammate was given,
        the lead's observations, the final outcome, the number of questions the human was asked)."""
        log, seen = [], []

        def brain(messages, tools):
            system = messages[0]["content"]
            if "You assign the lead" in system:
                return LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "lead"})])
            if "You list what a request explicitly requires" in system:
                return reqs(TOPIC, "at most 150 words")
            tool_messages = [m for m in messages if m["role"] == "tool"]
            if len(tool_messages) < len(steps):
                name, args = steps[len(tool_messages)]
                return LLMResponse("", [ToolCall(f"c{len(tool_messages)}", name, args)])
            seen.extend(json.loads(m["content"]) for m in tool_messages)
            return LLMResponse(json.dumps({"success": True, "summary": "done", "requirements": met("REQ2")}))

        def factory(role, parts):
            if role.agent_id == "lead":
                return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm, [], parts.sandbox,
                                   parts.memory, peers=parts.peers)
            return Recorder(role.agent_id, parts.bus, parts.router, parts.settings, log=log)

        team = {n: RoleConfig(n, n.title(), f"{n} works.", f"You are {n}.", []) for n in ("lead", "mate")}
        settings = Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=10,
                            lead_timeout_s=20, closing_check=False)
        human = AutoResponder()
        system = build_system(settings, MockLLM(responder=brain), human, roles=team, worker_factory=factory)
        system.start()
        answering = asyncio.create_task(human.run(system.bus))                   # the human who answers every question
        started = time.monotonic()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "do it"))
            while not system.requests.outcomes and time.monotonic() - started < 10:
                await asyncio.sleep(0.01)
        finally:
            answering.cancel()
            await asyncio.gather(answering, return_exceptions=True)
            await system.stop()
        outcome = system.requests.outcomes["R1"]
        self.assertTrue(outcome.success)
        asked = [m for m in system.bus.history(GROUP_MAIN, 1000) if m.type == MsgType.HITL_REQUEST]
        return log, seen, outcome, len(asked)

    async def test_one_question_first_and_then_the_work_goes_out_with_nothing_held_back(self):
        log, seen, outcome, asked = await self.run_request([
            ("ask_human", {"question": "Which story, for whom? My default: the exam-detector test, for students."}),
            ("call_mate", {"goal": "Write the note"})])
        self.assertEqual(asked, 1)
        self.assertEqual(len(log), 1)                                            # the teammate was given its work
        self.assertTrue(seen[1]["ok"])                                           # nothing was held back
        self.assertNotIn("Requirements not met", outcome.summary)                # the invitation was taken up

    async def test_a_lead_that_goes_straight_to_the_work_is_held_back_once_and_then_it_is_reported(self):
        log, seen, outcome, asked = await self.run_request([
            ("call_mate", {"goal": "Write the note"}), ("call_mate", {"goal": "Write the note"})])
        self.assertEqual(asked, 0)
        self.assertFalse(seen[0]["ok"])
        self.assertIn("Not yet. The request invites you to consult the human", seen[0]["output"])
        self.assertTrue(seen[1]["ok"])                                           # held back once, not twice
        self.assertEqual(len(log), 1)                                            # the work was done once
        self.assertIn("- REQ1 (" + TOPIC + "): not met. the human was not asked anything", outcome.summary)

    async def test_the_lead_that_asks_after_being_held_back_is_not_held_back_again(self):
        log, seen, outcome, asked = await self.run_request([
            ("call_mate", {"goal": "Write the note"}),
            ("ask_human", {"question": "Which story? Default: the detector test."}),
            ("call_mate", {"goal": "Write the note"})])
        self.assertEqual((asked, len(log)), (1, 1))
        self.assertFalse(seen[0]["ok"])
        self.assertTrue(seen[2]["ok"])
        self.assertNotIn("Requirements not met", outcome.summary)


if __name__ == "__main__":
    unittest.main()
