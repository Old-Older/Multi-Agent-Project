"""An agent's memory outlives the run: a new process with the same data directory still has it."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.app import build_system
from mas.config import Settings
from mas.core.human import AutoResponder
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.llm.base import LLMResponse
from mas.llm.mock import MockLLM

TEAM = {"dev": RoleConfig("dev", "Developer", "Writes code.", "You are the developer.", ["write_file"])}


class MemoryAcrossSessionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.prompts: list[dict] = []                       # what the worker was told at the start of each task

    def settings(self) -> Settings:
        return Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=5.0,
                        lead_timeout_s=10.0)

    def brain(self, outcome: dict):
        def respond(messages, tools):
            self.prompts.append(json.loads(messages[1]["content"]))
            return LLMResponse(json.dumps(outcome))
        return respond

    async def one_session(self, request: str, outcome: dict) -> None:
        """A whole program run: build the system, ask once, wait for the answer, shut down."""
        system = build_system(self.settings(), MockLLM(responder=self.brain(outcome)), AutoResponder(), roles=TEAM)
        system.start()
        try:
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, request))
            for _ in range(500):
                if system.requests.outcomes:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
        finally:
            await system.stop()

    async def test_what_an_agent_learned_in_one_run_is_there_in_the_next(self):
        await self.one_session("Build a meeting room booking system with a dashboard",
                               {"success": True, "summary": "Built the booking system with Flask and SQLite"})
        self.assertEqual(self.prompts[0]["past_experiences"], [])                     # the first run starts empty
        self.assertTrue((self.tmp / "data" / "memory" / "dev.jsonl").exists())        # and leaves a file behind

        await self.one_session("Extend the booking system with a usage dashboard",
                               {"success": True, "summary": "Added the dashboard"})
        remembered = self.prompts[1]["past_experiences"]
        self.assertEqual([(e["goal"], e["success"]) for e in remembered],
                         [("Build a meeting room booking system with a dashboard", True)])
        self.assertIn("Flask and SQLite", remembered[0]["summary"])

    async def test_a_failure_and_its_lesson_are_remembered_too(self):
        await self.one_session("Fetch the pricing page and save it",
                               {"success": False, "summary": "", "error": "the page came back empty",
                                "failure_mode": "tool_error"})
        await asyncio.sleep(0.1)                                                       # the lesson is written afterwards
        await self.one_session("Fetch the pricing page again", {"success": True, "summary": "ok"})
        [e] = self.prompts[-1]["past_experiences"]
        self.assertFalse(e["success"])
        self.assertIn("empty", e["summary"] + e["lesson"])

    async def test_another_data_directory_is_another_memory(self):
        await self.one_session("Build a booking system", {"success": True, "summary": "done"})
        other = Settings(data_dir=self.tmp / "elsewhere", workspaces_dir=self.tmp / "ws2", subtask_timeout_s=5.0,
                         lead_timeout_s=10.0)
        system = build_system(other, MockLLM(responder=self.brain({"success": True, "summary": "x"})),
                              AutoResponder(), roles=TEAM)
        self.assertEqual(system.memories["dev"].all(), [])


if __name__ == "__main__":
    unittest.main()
