"""Transcript: the conversation of a run as Markdown."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mas.core.bus import InMemoryBus
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR, Message, MsgType, dm_channel
from mas.core.task import FailureMode
from mas.core.transcript import Transcript


def outcome(success=True, lead="lead", failure=None, duration=12.34, deliverables=("a.md",)):
    return SimpleNamespace(success=success, lead=lead, failure_mode=failure, duration=duration,
                           deliverables=list(deliverables))


class TranscriptTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bus = InMemoryBus()
        self.outcomes: dict = {}
        self.t = Transcript(self.bus, title="Transcript: demo", team={"lead": "Technical Lead", "dev": "Developer"},
                            path=self.tmp / "out" / "t.md", outcomes=lambda: self.outcomes)

    async def say(self, type_, sender, content="", channel=GROUP_MAIN, **kw):
        await self.bus.publish(Message(type_, sender, channel, content, **kw))

    async def test_the_whole_dialogue_in_order(self):
        task = {"id": "t1", "root_id": "R1", "goal": "write the code", "files": ["spec.md"]}
        await self.say(MsgType.CHAT, HUMAN, "Build me a booking system")
        await self.say(MsgType.TASK_ASSIGN, ORCHESTRATOR, "@lead Build me a booking system", receiver="lead",
                       payload={"task": {**task, "id": "t0", "goal": "Build me a booking system"}})
        await self.say(MsgType.HITL_REQUEST, "lead", "@human How many rooms?", receiver=HUMAN,
                       payload={"request_id": "h1", "kind": "clarify", "question": "How many rooms?",
                                "options": ["few", "many"]})
        await self.say(MsgType.HITL_RESPONSE, HUMAN, "/reply h1 about twenty", receiver="lead",
                       payload={"request_id": "h1", "answer": "about twenty"})
        await self.say(MsgType.TASK_ASSIGN, "lead", "@dev write the code", receiver="dev", payload={"task": task})
        await self.say(MsgType.STATUS, "dev", "dev: working", payload={"task_id": "t1", "status": "running",
                                                                          "note": "", "public": True})
        await self.say(MsgType.TASK_RESULT, "dev", "@lead Done: code written", receiver="lead",
                       payload={"result": {"task_id": "t1", "success": True, "artifacts": ["app.py"]}})
        await self.say(MsgType.TASK_RESULT, "lead", "@orchestrator Done: built", receiver=ORCHESTRATOR,
                       payload={"result": {"task_id": "t0", "success": True}})
        self.outcomes["R1"] = outcome()
        await self.say(MsgType.CHAT, "lead", "@human It is built.", receiver=HUMAN,
                       payload={"final": True, "root_id": "R1", "success": True, "failure_mode": None})
        text = self.t.render()
        order = ["Build me a booking system", "handed to its lead lead", "lead asks the human · h1 (clarify)",
                 "How many rooms?", "Options: few / many", "human answers · h1", "about twenty",
                 "lead delegates to dev · task `t1`", "Files handed over: spec.md",
                 "dev reports to lead · task `t1` · done", "Files: app.py",
                 "lead → human · FINAL REPLY to R1 · done", "It is built."]
        positions = [text.index(piece) for piece in order]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("working", text)                          # STATUS lines are left out
        self.assertNotIn("Done: built", text)                      # the lead's result to the request layer is not repeated
        self.assertIn("- `lead`: Technical Lead", text)
        self.assertIn("| R1 | lead | done | - | 12.3 | a.md |", text)

    async def test_failures_and_private_chats(self):
        self.outcomes["R1"] = outcome(False, failure=FailureMode.TIMEOUT, deliverables=())
        await self.say(MsgType.CHAT, "dev", "Hello", channel=dm_channel(HUMAN, "dev"), receiver=HUMAN)
        await self.say(MsgType.CHAT, "lead", "@human gave up", receiver=HUMAN,
                       payload={"final": True, "root_id": "R1", "success": False, "failure_mode": "timeout"})
        text = self.t.render()
        self.assertIn("in the private chat", text)
        self.assertIn("FINAL REPLY to R1 · failed (timeout)", text)
        self.assertIn("| R1 | lead | failed | timeout | 12.3 | - |", text)

    async def test_the_file_is_written_when_a_request_ends_and_can_be_saved_again(self):
        await self.say(MsgType.CHAT, HUMAN, "hi")
        self.assertFalse((self.tmp / "out" / "t.md").exists())
        await self.say(MsgType.CHAT, "lead", "@human done", receiver=HUMAN, payload={"final": True, "root_id": "R1"})
        self.assertIn("done", (self.tmp / "out" / "t.md").read_text(encoding="utf-8"))
        other = self.t.save(self.tmp / "copy.md")
        self.assertEqual(other, self.tmp / "copy.md")
        self.assertTrue(other.exists())

    async def test_an_empty_run_and_an_unwritable_path(self):
        self.assertIn("(nothing was said)", self.t.render())
        blocker = self.tmp / "file"
        blocker.write_text("x")
        self.assertIsNone(self.t.save(blocker / "inside" / "t.md"))      # a directory cannot be made: no exception
        self.assertIsNone(Transcript(self.bus).save())


if __name__ == "__main__":
    unittest.main()
