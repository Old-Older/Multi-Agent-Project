"""Browser runs use the real workers, bus and output collector with a scripted model."""
import asyncio
import io
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.config import Settings
from mas.core.human import HitlKind, HitlRequest
from mas.llm.base import LLMError, LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.web_runner import RunManager, _default_answer, _Run, _scenario
from mas.web_config import resolve_config

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
            run_id = self.manager.start(TEAM, ["# First\n\n```text\nMake a note.\n```", "Review it."],
                                        {"interaction": "manual"})
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
        self.assertEqual([r["default_title"] for r in state["results"]], [False, True])
        self.assertEqual(state["questions"], [])
        file = state["results"][0]["files"][0]
        path = self.manager.artifact(run_id, file["id"])
        self.assertEqual(path.read_text(), "blue")
        # Resolve both sides: the temp directory is reached through a symbolic link on macOS (/var -> /private/var) and may be
        # an 8.3 short name on Windows, so the two spellings of one directory are compared as the same path.
        self.assertTrue(path.resolve().is_relative_to((self.root / "web-runs" / run_id / "output").resolve()))
        with self.assertRaises(KeyError):
            self.manager.artifact(run_id, "../.env")
        self.assertIn("hitl_response", [event["kind"] for event in state["events"]])

    def test_server_shutdown_cancels_a_pending_human_question(self):
        script = MockLLM([LLMResponse("", [ToolCall("ask", "ask_human", {"question": "Which title?"})])])
        with patch("mas.web_runner.make_llm", return_value=script):
            run_id = self.manager.start(TEAM, ["Make a note"], {"interaction": "manual"})
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

    def test_presets_match_the_documented_run_and_keep_environment_untouched(self):
        base = Settings(request_budget_s=72, research_max_calls=7, research_note_after=4,
                        research_note_every=3, finish_not_before=0.2, hkgai_api_key="local-course-key")
        for preset, expected in [("environment", (72, 7, 0.2, 4, 3)), ("fast", (270, 14, 0.5, 6, 2)),
                                 ("full", (900, 28, 0, 17, 4))]:
            settings, public = resolve_config(base, {"preset": preset})
            self.assertEqual((settings.request_budget_s, settings.research_max_calls, settings.finish_not_before,
                              settings.research_note_after, settings.research_note_every), expected)
            self.assertEqual(settings.hkgai_api_key, "local-course-key")
            self.assertNotIn("local-course-key", str(public))
        self.assertEqual(base.request_budget_s, 72)

    def test_custom_config_rejects_nonfinite_fractional_and_unexpected_values(self):
        valid = {"preset": "custom", "budget": 0, "research": 0, "min_use": 0}
        for bad in ({"budget": True}, {"budget": float("nan")}, {"budget": float("inf")}, {"budget": -1},
                    {"research": 0.4}, {"research": False}, {"min_use": 1}, {"min_use": -0.1},
                    {"provider": ["deepseek"]}, {"api_key": "unused"}, {"key_source": "custom"},
                    {"key_source": "custom", "api_key": "invalid\nkey"}, {"model": "\n"},
                    {"api_base": "https://invalid.invalid/"}, {"interaction": True}, {"interaction": ["auto"]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolve_config(self.manager.settings, {**valid, **bad})
        settings, _ = resolve_config(self.manager.settings, {**valid, "research": 40})
        self.assertEqual((settings.research_note_after, settings.research_note_every), (24, 6))

    def test_provider_exception_with_credentials_is_kept_out_of_run_files_and_logs(self):
        key = "test-ephemeral-provider-key"
        options = {"key_source": "custom", "api_key": key}

        def failure(messages, tools):
            raise LLMError("rejected Authorization header " + key)

        recorded = io.StringIO()
        handler = logging.StreamHandler(recorded)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        with patch("mas.web_runner.make_llm", return_value=MockLLM(responder=failure)):
            run_id = self.manager.start(TEAM, ["Make a note."], options)
            result = self.wait(run_id, lambda state: state["status"] == "failed")
            self.manager.close()
        self.assertNotIn(key, str(result))
        self.assertNotIn(key, str(self.manager.inputs(run_id)))
        self.assertNotIn(key, recorded.getvalue())
        self.assertEqual(self.manager.settings.hkgai_api_key, "")
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(key.encode(), path.read_bytes())
        with patch("mas.web_runner.make_llm", side_effect=ValueError("invalid " + key)):
            with self.assertRaises(ValueError) as caught:
                self.manager.start(TEAM, ["Make a note."], options)
        self.assertNotIn(key, str(caught.exception))

    def test_default_answer_honours_unambiguous_labels_and_question_defaults(self):
        for kind, prompt, options, expected in [
            (HitlKind.CLARIFY, "Which settings?",
             ["Use all three defaults", "Defaults, but shorter"], "Use all three defaults"),
            (HitlKind.CLARIFY, "请选择。", ["自定义", "沿用方案（推荐）"], "沿用方案（推荐）"),
            (HitlKind.ADVICE, "Choose a format. Default: PDF.", ["TXT", "PDF"], "PDF"),
            (HitlKind.CLARIFY, "请选择。默认选项为蓝色。", ["蓝色", "红色"], "蓝色"),
            (HitlKind.APPROVAL, "Approve?", ["yes (recommended)", "no"], "no"),
            (HitlKind.ADVICE, "Retry?", [], "try a different approach"),
            (HitlKind.CLARIFY, "Which?", ["A (default)", "B (recommended)"], "proceed as described"),
        ]:
            with self.subTest(prompt=prompt, options=options):
                req = HitlRequest("h1", "writer", "t1", "group:main", kind, prompt, options)
                self.assertEqual(_default_answer(req), expected)

    def test_switch_resolves_parallel_questions_and_preserves_a_manual_answer(self):
        async def choices():
            tasks = ["Make a note."]
            run = _Run(self.root, _scenario(TEAM, tasks), TEAM, tasks, {"interaction": "manual"})
            queries = [HitlRequest(f"h{i}", "writer", "t1", "group:main", HitlKind.CLARIFY,
                                   "Which format?", ["TXT", "PDF (default)"]) for i in range(4)]
            waiting = [asyncio.create_task(run.answer(q)) for q in queries[:3]]
            await asyncio.sleep(0)
            self.assertEqual(len(run.snapshot()["questions"]), 3)
            run.reply("h1", "TXT")
            run.enable_auto()
            run.enable_auto()
            self.assertEqual(await asyncio.gather(*waiting), ["PDF (default)", "TXT", "PDF (default)"])
            self.assertEqual(await run.answer(queries[-1]), "PDF (default)")
            self.assertEqual(run.snapshot()["questions"], [])
        asyncio.run(choices())
