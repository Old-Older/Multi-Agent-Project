"""Scenarios (mas/scenario.py), the AutoResponder, and an unattended run end to end."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mas.agents.base import Agent
from mas.app import build_system
from mas.config import Settings
from mas.core.human import AutoResponder, HitlKind, HitlRequest
from mas.core.lead import CHOOSE_LEAD
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.task import Task, TaskResult
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.scenario import driver_for, load_scenario
from tests.test_app import ROOT

ROLES_MD = """# Scenario X: A Team

| Agent ID | Role |
|---|---|
| `boss` | Boss |
| `worker` | Worker |

## Boss (boss)

```text
You are the boss. You set the goals.
```

## Worker (worker)

```text
You are the worker. You do the work.
```
"""


def make_scenario(root: Path, tasks=("Do the first thing.", "Now do the second thing.")) -> Path:
    folder = root / "scenario_x 2"
    folder.mkdir()
    (folder / "01_role_initialization.md").write_text(ROLES_MD, encoding="utf-8")
    for n, prompt in enumerate(tasks, 1):
        (folder / f"{n + 1:02d}_task_{n}.md").write_text(
            f"# Scenario X, Task {n}: Thing {n}\n\n```text\n{prompt}\n```\n", encoding="utf-8")
    (folder / "README.md").write_text("```text\nnot a task\n```\n")
    return folder


class LoadScenarioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_team_and_the_tasks_in_file_order(self):
        s = load_scenario(make_scenario(self.tmp, ("one", "two", "three")))
        self.assertEqual(s.name, "scenario_x 2")
        self.assertEqual(list(s.team), ["boss", "worker"])
        self.assertEqual([(t.file, t.title, t.prompt) for t in s.tasks],
                         [("02_task_1.md", "Scenario X, Task 1: Thing 1", "one"),
                          ("03_task_2.md", "Scenario X, Task 2: Thing 2", "two"),
                          ("04_task_3.md", "Scenario X, Task 3: Thing 3", "three")])

    def test_a_folder_without_tasks_or_without_a_team_is_refused(self):
        folder = make_scenario(self.tmp, ())
        with self.assertRaisesRegex(ValueError, "no task found"):
            load_scenario(folder)
        with self.assertRaisesRegex(ValueError, "scenario folder not found"):
            load_scenario(self.tmp / "nope")
        (folder / "01_role_initialization.md").unlink()
        with self.assertRaisesRegex(ValueError, "team file not found"):
            load_scenario(folder)


class AutoResponderTest(unittest.IsolatedAsyncioTestCase):
    async def test_it_answers_every_request_and_counts_them(self):
        bus = _bus()
        human = AutoResponder()
        runner = asyncio.create_task(human.run(bus))
        try:
            for rid, kind in (("h1", "clarify"), ("h2", "approval"), ("h3", "advice")):
                await bus.publish(Message(MsgType.HITL_REQUEST, "boss", GROUP_MAIN, "?", receiver=HUMAN,
                                          payload={"request_id": rid, "task_id": None, "root_id": "R1", "kind": kind,
                                                   "question": "q", "options": []}))
            await _until(lambda: len([m for m in bus.history(GROUP_MAIN, 50) if m.type == MsgType.HITL_RESPONSE]) == 3)
            answers = {m.payload["request_id"]: m.payload["answer"]
                       for m in bus.history(GROUP_MAIN, 50) if m.type == MsgType.HITL_RESPONSE}
            self.assertEqual(answers, {"h1": "proceed as described", "h2": "yes", "h3": "try a different approach"})
            self.assertEqual(human.hitl_count, 3)
            self.assertEqual(len(human.shown), 3)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def test_submit_posts_as_the_human(self):
        bus = _bus()
        mid = await AutoResponder().submit(bus, "do it", GROUP_MAIN)
        [m] = bus.history(GROUP_MAIN, 5)
        self.assertEqual((m.id, m.sender, m.content, m.type), (mid, HUMAN, "do it", MsgType.CHAT))


def _bus():
    from mas.core.bus import InMemoryBus
    bus = InMemoryBus()
    bus.join(HUMAN, GROUP_MAIN)
    return bus


async def _until(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class RunScenarioTest(unittest.IsolatedAsyncioTestCase):
    """A whole unattended run: both tasks, the lead asking a question, the transcript."""

    class Member(Agent):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.goals: list[str] = []

        async def handle_task(self, task: Task) -> TaskResult:
            self.goals.append(task.goal)
            if self.agent_id == "boss" and task.parent_id is None:
                answer = await self.ask_human(task, "How big?", HitlKind.CLARIFY)
                helped = await self.call_agent(task, "worker", f"help with: {task.goal}")
                return TaskResult(task.id, helped.success, f"Done '{task.goal}' (asked: {answer}; {helped.summary})")
            self.router.sandboxes[self.agent_id].write_text(f"{task.id}.md", "x")
            return TaskResult(task.id, True, "helped", artifacts=[f"{task.id}.md"])

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.scenario = load_scenario(make_scenario(self.tmp))
        self.settings = Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws", subtask_timeout_s=5.0,
                                 lead_timeout_s=10.0)
        llm = MockLLM(responder=lambda m, t: LLMResponse("", [ToolCall("c", CHOOSE_LEAD, {"agent_id": "boss"})]))
        self.system = build_system(self.settings, llm, AutoResponder(), roles=self.scenario.team,
                                   worker_factory=lambda role, parts: self.Member(role.agent_id, parts.bus, parts.router,
                                                                                   parts.settings),
                                   run_name=self.scenario.name)

    async def test_both_tasks_are_posted_one_after_the_other_to_the_same_group(self):
        said = []
        await asyncio.wait_for(self.system.run(driver_for(self.scenario, announce=said.append), until_driver_done=True), 15)
        finals = [m for m in self.system.bus.history(GROUP_MAIN, 500) if m.payload.get("final")]
        self.assertEqual([f.payload["root_id"] for f in finals], ["R1", "R2"])
        self.assertTrue(all(f.payload["success"] and f.sender == "boss" for f in finals))
        self.assertIn("Done 'Do the first thing.' (asked: proceed as described;", finals[0].content)
        self.assertIn("Done 'Now do the second thing.'", finals[1].content)
        self.assertEqual(self.system.workers["boss"].goals, ["Do the first thing.", "Now do the second thing."])
        self.assertEqual(self.system.human.hitl_count, 2)
        self.assertEqual(len(said), 2)
        self.assertIn("Task 1/2: Scenario X, Task 1: Thing 1", said[0])

    async def test_the_transcript_is_written_and_names_everything(self):
        await asyncio.wait_for(self.system.run(driver_for(self.scenario, announce=lambda t: None),
                                               until_driver_done=True), 15)
        path = self.system.transcript.path
        self.assertEqual(path.parent, self.settings.data_dir / "transcripts")
        self.assertTrue(path.name.startswith("scenario_x 2-"))
        text = path.read_text(encoding="utf-8")
        for piece in ("Do the first thing.", "Now do the second thing.", "boss asks the human · h1 (clarify)",
                      "human answers · h1", "proceed as described", "boss delegates to worker",
                      "FINAL REPLY to R1", "FINAL REPLY to R2", "| R1 | boss | done |", "| R2 | boss | done |"):
            self.assertIn(piece, text)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT), HKGAI_API_KEY="", LLM_PROVIDER="")
        r = subprocess.run([sys.executable, "-m", "mas", "--data-dir", str(self.tmp / "data"), *args], input="",
                           capture_output=True, text=True, cwd=self.tmp, env=env, timeout=30)
        return r.returncode, r.stderr + r.stdout

    def test_auto_needs_a_scenario(self):
        code, out = self.run_cli("--auto")
        self.assertNotEqual(code, 0)
        self.assertIn("--scenario", out)

    def test_a_bad_scenario_says_why(self):
        code, out = self.run_cli("--scenario", str(self.tmp / "nope"))
        self.assertNotEqual(code, 0)
        self.assertIn("scenario folder not found", out)

    def test_a_good_scenario_gets_as_far_as_asking_for_the_key(self):
        code, out = self.run_cli("--scenario", str(make_scenario(self.tmp)))
        self.assertNotEqual(code, 0)
        self.assertIn("HKGAI_API_KEY is not set", out)


if __name__ == "__main__":
    unittest.main()
