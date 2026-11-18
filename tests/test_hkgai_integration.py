"""Offline, two-round HKGAI chat through a real Worker and workspace tool."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from openai import AsyncOpenAI

from mas.agents.roles import RoleConfig
from mas.app import build_system, make_llm
from mas.config import Settings
from mas.core.human import CliHumanIO
from mas.core.message import HUMAN, Message, MsgType, dm_channel
from tests.test_hkgai import completion


class HKGAIWorkerIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_worker_returns_tool_observation_to_the_course_model(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        settings = Settings(hkgai_api_key="offline-fixture", data_dir=root / "data",
                            workspaces_dir=root / "workspaces")
        client = make_llm(settings)
        role = RoleConfig("reader", "Reader", "Reads a workspace file.", "", ["read_file"])
        human = CliHumanIO(read_line=AsyncMock(return_value=None))
        system = build_system(settings, client, human, roles={role.agent_id: role})
        system.sandboxes[role.agent_id].write_text("note.txt", "session notes")
        channel = dm_channel(HUMAN, role.agent_id)
        task = system.router.open_direct_task(
            Message(MsgType.CHAT, HUMAN, channel, "Read note.txt", receiver=role.agent_id), role.agent_id)

        requested_call = {"type": "function", "id": "read-17", "function": {
            "name": "read_file", "arguments": '{"path":"note.txt",}',
        }}
        final_text = json.dumps({"success": True, "summary": "Read the notes."})
        replies = [completion(None, [requested_call]), completion(final_text)]
        requests = []

        def handle(request):
            requests.append(request)
            if len(requests) > len(replies):
                return httpx.Response(400)
            return httpx.Response(200, json=replies[len(requests) - 1])

        def offline_sdk(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))

        with patch("mas.llm.hkgai.AsyncOpenAI", side_effect=offline_sdk):
            result = await system.workers[role.agent_id].handle_task(task)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.summary, "Read the notes.")
        self.assertEqual(len(requests), 2)
        first, second = [json.loads(request.content) for request in requests]
        for request, payload in zip(requests, (first, second)):
            self.assertEqual(str(request.url), "https://api1.hkgai.net/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer offline-fixture")
            self.assertEqual(payload["model"], "t2_hkgai-v3_fp8_1m_e7")
        self.assertIn("read_file", [tool["function"]["name"] for tool in first["tools"]])
        assistant, observation = second["messages"][-2:]
        self.assertEqual(assistant["role"], "assistant")
        call, = assistant["tool_calls"]
        self.assertEqual(call["id"], "read-17")
        self.assertEqual(call["function"]["name"], "read_file")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "note.txt"})
        self.assertEqual(observation["role"], "tool")
        self.assertEqual(observation["tool_call_id"], call["id"])
        tool_result = json.loads(observation["content"])
        self.assertTrue(tool_result["ok"])
        self.assertEqual(tool_result["output"], "session notes")
