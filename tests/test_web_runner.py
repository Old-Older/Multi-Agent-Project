"""Browser runs use the real workers, bus and output collector with a scripted model."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.config import Settings
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.web_runner import RunManager

TEAM = "## Writer (writer)\n\n```text\nWrite a short note.\n```"


class WebRunnerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.manager = RunManager(Settings(data_dir=self.root, requirements_check=False,
                                           closing_check=False, request_budget_s=0))
        self.addCleanup(self.manager.close)

    def wait(self, run_id, predicate):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            snapshot = self.manager.snapshot(run_id)
            if predicate(snapshot):
                return snapshot
            time.sleep(.01)
        self.fail(str(self.manager.snapshot(run_id)))

    def test_questions_keep_the_run_open_and_each_task_has_its_own_output(self):
        script = MockLLM([
            LLMResponse("", [ToolCall("ask", "ask_human", {"question": "Which colour?", "options": ["red", "blue"]})]),
            LLMResponse("", [ToolCall("write", "write_file", {"path": "note.txt", "content": "blue"})]),
            LLMResponse('{"success":true,"summary":"Saved.","artifacts":["note.txt"]}'),
            LLMResponse('{"success":false,"summary":"Incomplete."}'),
            LLMResponse("Check the requirements."),
        ])
        with patch("mas.web_runner.make_llm", return_value=script):
            run_id = self.manager.start(TEAM, ["# First\n\n```text\nMake a note.\n```", "Review it."])
            state = self.wait(run_id, lambda snapshot: snapshot["questions"])
            question = state["questions"][0]
            self.assertEqual(self.manager.active_id(), run_id)
            self.assertEqual(self.manager.inputs(run_id)["roles"], TEAM)
            self.assertEqual(self.manager.inputs(run_id)["tasks"][-1], "Review it.")
            self.assertEqual((question["sender"], question["options"]), ("writer", ["red", "blue"]))
            self.assertIn("task_assign", [event["kind"] for event in state["events"]])
            with self.assertRaises(RuntimeError):
                self.manager.start(TEAM, ["another"])
            self.manager.reply(run_id, question["id"], "blue")
            with self.assertRaises(ValueError):
                self.manager.reply(run_id, question["id"], "red")
            state = self.wait(run_id, lambda snapshot: snapshot["status"] != "running")
        self.assertEqual(state["status"], "failed")
        self.assertEqual([r["success"] for r in state["results"]], [True, False])
        self.assertEqual([r["title"] for r in state["results"]], ["First", "任务 2"])
        self.assertEqual(state["questions"], [])
        file = state["results"][0]["files"][0]
        path = self.manager.artifact(run_id, file["id"])
        self.assertEqual(path.read_text(), "blue")
        self.assertTrue(path.is_relative_to(self.root / "web-runs" / run_id / "output"))
        with self.assertRaises(KeyError):
            self.manager.artifact(run_id, "../.env")
        self.assertIn("hitl_response", [event["kind"] for event in state["events"]])

    def test_server_shutdown_cancels_a_pending_human_question(self):
        script = MockLLM([LLMResponse("", [ToolCall("ask", "ask_human", {"question": "Which title?"})])])
        with patch("mas.web_runner.make_llm", return_value=script):
            run_id = self.manager.start(TEAM, ["Make a note"])
            self.wait(run_id, lambda state: state["questions"])
            self.manager.close()
        self.assertIsNone(self.manager.active_id())
        state = self.manager.snapshot(run_id)
        self.assertEqual((state["status"], state["questions"]), ("failed", []))

    def test_invalid_inputs_do_not_start_a_wait_for_a_final_reply(self):
        for roles, tasks in [(TEAM, ["/status"]), (TEAM, ["```\n\n```"]), (TEAM, []),
                             (TEAM.replace("(writer)", "(CON)"), ["x"]), (TEAM + "\n" + TEAM.upper(), ["x"])]:
            with self.subTest(roles=roles, tasks=tasks), self.assertRaises(ValueError):
                self.manager.start(roles, tasks)
        with self.assertRaisesRegex(ValueError, "HKGAI_API_KEY"):
            self.manager.start(TEAM, ["real task"])
