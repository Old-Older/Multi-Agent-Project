"""Run the local web interface over HTTP with real workers and a scripted model."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.config import Settings
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.scenario import parse_task_markdown
from mas.team import parse_team
from mas.web import create_server


TEAM = """## Editor (editor)

```text
You edit and deliver the requested file.
```
"""


class WebTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = Settings(data_dir=Path(tmp.name) / "data", workspaces_dir=Path(tmp.name) / "workspaces",
                            hkgai_api_key="test-only-server-key", hkgai_model="test-course-model",
                            request_budget_s=0, closing_check=False, requirements_check=False)
        self.server = create_server(settings, port=0)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, method, path, payload=None, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            headers = {"Origin": self.origin if origin is None else origin}
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode()
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def json(self, method, path, payload=None):
        status, _, body = self.request(method, path, payload)
        self.assertTrue(200 <= status < 300, (status, body))
        return json.loads(body)

    def poll(self, path, ready):
        deadline = time.monotonic() + 8
        while True:
            state = self.json("GET", path)
            if ready(state):
                return state
            if time.monotonic() >= deadline:
                self.fail(f"Timed out waiting for run: {state}")
            time.sleep(0.02)

    def test_task_waits_for_an_answer_and_delivers_a_download(self):
        llm = MockLLM([
            LLMResponse("", [ToolCall("q", "ask_human", {"question": "Which colour?"})]),
            LLMResponse("", [ToolCall("w", "write_file", {"path": "colour.txt", "content": "Blue"})]),
            LLMResponse(json.dumps({"success": True, "summary": "Created the colour note.", "artifacts": ["colour.txt"]})),
            LLMResponse(json.dumps({"success": True, "summary": "Second task complete."})),
        ])
        with patch("mas.web_runner.make_llm", return_value=llm):
            tasks = ["# First\n```text\nAsk for my colour and write it in colour.txt.\n```",
                     "# Second\n```text\nConfirm the first task is complete.\n```"]
            run = self.json("POST", "/api/runs", {"roles": TEAM, "tasks": tasks})
            path = f"/api/runs/{run['id']}"
            waiting = self.poll(path, lambda s: s["question"])
            question = waiting["question"]
            self.assertEqual((waiting["status"], question["text"]), ("waiting", "Which colour?"))
            self.assertFalse(waiting["results"])
            self.json("POST", path + "/answer", {"id": question["id"], "answer": "Blue"})
            done = self.poll(path, lambda s: s["status"] in ("completed", "failed"))
        self.assertEqual(done["status"], "completed", done["error"])
        self.assertEqual([r["title"] for r in done["results"]], ["First", "Second"])
        self.assertTrue(done["events"])
        self.assertTrue(all(result["success"] for result in done["results"]), done["results"])
        self.assertIn("Blue", json.dumps(llm.calls[1][0]))
        artifact = done["results"][0]["files"][0]
        status, headers, body = self.request("GET", artifact["url"])
        self.assertEqual((status, body), (200, b"Blue"))
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_unknown_run_and_invalid_input(self):
        status, _, _ = self.request("GET", "/api/runs/unknown")
        self.assertEqual(status, 404)
        with patch("mas.web_runner.make_llm") as factory:
            status, _, _ = self.request("POST", "/api/runs", {"roles": "A heading is missing.", "tasks": ["Do it"]})
            self.assertEqual(status, 400)
            factory.assert_not_called()

    def test_examples_supply_complete_roles_and_tasks(self):
        items = self.json("GET", "/api/examples")["examples"]
        self.assertEqual(len(items), 3)
        for item in items:
            with self.subTest(example=item["name"]):
                self.assertTrue(parse_team(item["roles"]))
                self.assertEqual(len(item["tasks"]), 2)
                for markdown in item["tasks"]:
                    self.assertIsNotNone(parse_task_markdown(markdown, "task.md"))

    def test_cross_origin_run_rejected(self):
        with patch("mas.web_runner.make_llm") as factory:
            status, _, _ = self.request("POST", "/api/runs", {"roles": TEAM, "tasks": ["Do it"]},
                                        origin="https://elsewhere.example")
            self.assertEqual(status, 403)
            factory.assert_not_called()

    def test_config_exposes_provider_readiness_and_presets(self):
        config = self.json("GET", "/api/config")
        self.assertEqual(config["provider"], "hkgai")
        self.assertEqual(config["providers"]["hkgai"]["model"], "test-course-model")
        self.assertIs(config["providers"]["hkgai"]["has_key"], True)
        self.assertIs(config["providers"]["deepseek"]["has_key"], False)
        self.assertNotIn("test-only-server-key", json.dumps(config))
        self.assertEqual(config["presets"]["environment"]["budget"], 0)
        for preset, expected in [("fast", (270, 14, 0.5)), ("full", (900, 28, 0))]:
            settings = config["presets"][preset]
            self.assertEqual((settings["budget"], settings["research"], settings["min_use"]), expected)

    def test_run_uses_its_own_configuration_and_keeps_keys_out_of_responses(self):
        options = {"provider": "deepseek", "model": "test-run-model", "key_source": "custom",
                   "api_key": "test-only-run-key", "preset": "custom", "budget": 311, "research": 8, "min_use": 0}
        tasks = ["Confirm receipt."]
        model = MockLLM([LLMResponse('{"success":true,"summary":"Received."}')])
        with patch("mas.web_runner.make_llm", return_value=model) as make_llm:
            run = self.json("POST", "/api/runs", {"roles": TEAM, "tasks": tasks, "config": options})
            settings = make_llm.call_args.args[0]
            self.assertEqual((settings.llm_provider, settings.deepseek_model, settings.deepseek_api_key),
                             ("deepseek", "test-run-model", "test-only-run-key"))
            self.assertEqual((settings.request_budget_s, settings.research_max_calls, settings.finish_not_before),
                             (311, 8, 0))
            path = f"/api/runs/{run['id']}"
            done = self.poll(path, lambda s: s["status"] in ("completed", "failed"))
        self.assertEqual(done["status"], "completed", done["error"])
        inputs = self.json("GET", path + "/inputs")
        self.assertEqual((inputs["roles"], inputs["tasks"]), (TEAM, tasks))
        for field in ("provider", "model", "preset", "budget", "research", "min_use"):
            self.assertEqual(inputs["config"][field], options[field])
        defaults = self.json("GET", "/api/config")
        self.assertEqual(defaults["provider"], "hkgai")
        self.assertIs(defaults["providers"]["deepseek"]["has_key"], False)
        for response in (run, done, inputs, defaults):
            text = json.dumps(response)
            self.assertNotIn("test-only-run-key", text)
            self.assertNotIn("test-only-server-key", text)

    def test_full_preset_uses_the_server_credential(self):
        model = MockLLM([LLMResponse('{"success":true,"summary":"Received."}')])
        with patch("mas.web_runner.make_llm", return_value=model) as make_llm:
            config = {"provider": "hkgai", "key_source": "server", "preset": "full"}
            run = self.json("POST", "/api/runs", {"roles": TEAM, "tasks": ["Confirm receipt."], "config": config})
            settings = make_llm.call_args.args[0]
            self.assertEqual((settings.hkgai_api_key, settings.hkgai_model),
                             ("test-only-server-key", "test-course-model"))
            self.assertEqual((settings.request_budget_s, settings.research_max_calls, settings.finish_not_before),
                             (900, 28, 0))
            done = self.poll(f"/api/runs/{run['id']}", lambda s: s["status"] in ("completed", "failed"))
        self.assertEqual(done["status"], "completed", done["error"])

    def test_unknown_preset_rejected_before_model_creation(self):
        with patch("mas.web_runner.make_llm") as make_llm:
            status, _, _ = self.request("POST", "/api/runs", {
                "roles": TEAM, "tasks": ["Confirm receipt."], "config": {"preset": "unknown"},
            })
            self.assertEqual(status, 400)
            make_llm.assert_not_called()
