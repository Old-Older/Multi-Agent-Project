"""Smoke tests for the interface skeleton.

They pin the contracts both members code against: if one of these breaks,
an interface changed and the other member needs to know.
Run: python -m unittest   (or pytest)
"""
from __future__ import annotations

import asyncio
import json
import unittest

from mas.agents.roles import ROLES
from mas.agents.virtual_tools import call_agent_spec, target_of
from mas.config import Settings
from mas.core.message import (GROUP_MAIN, Message, MsgType, dm_channel,
                              dm_members, is_group)
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.llm.base import LLMResponse, ToolCall
from mas.llm.mock import MockLLM


def make_task(**kw) -> Task:
    base = dict(goal="写一个脚本", assignee="coder", requester="orchestrator",
                session_id="s1", root_id="r1", origin_channel=GROUP_MAIN)
    return Task(**{**base, **kw})


class MessageTest(unittest.TestCase):
    def test_dm_channel_is_order_independent(self):
        self.assertEqual(dm_channel("human", "coder"), dm_channel("coder", "human"))
        self.assertEqual(dm_channel("human", "coder"), "dm:coder:human")
        self.assertEqual(dm_members("dm:coder:human"), ("coder", "human"))

    def test_group_detection(self):
        self.assertTrue(is_group(GROUP_MAIN))
        self.assertFalse(is_group(dm_channel("a", "b")))

    def test_message_defaults(self):
        m = Message(MsgType.CHAT, sender="human", channel=GROUP_MAIN, content="hi")
        self.assertIsNone(m.receiver)
        self.assertEqual(m.mentions, [])
        self.assertTrue(m.id)


class TaskTest(unittest.TestCase):
    def test_task_roundtrip_is_json_serializable(self):
        t = make_task(chain=["orchestrator", "coder"], files=["notes.md"])
        d = json.loads(json.dumps(t.to_dict()))
        self.assertEqual(Task.from_dict(d), t)

    def test_depth(self):
        self.assertEqual(make_task().depth, 0)
        self.assertEqual(make_task(chain=["orchestrator", "coder", "researcher"]).depth, 2)

    def test_result_roundtrip(self):
        r = TaskResult("t1", False, "超时", error="timeout",
                       failure_mode=FailureMode.TIMEOUT, open_issues=["未推送"])
        d = json.loads(json.dumps(r.to_dict()))
        self.assertEqual(TaskResult.from_dict(d), r)

    def test_finished_states(self):
        self.assertTrue(TaskStatus.DECLINED.finished)
        self.assertFalse(TaskStatus.WAITING_HUMAN.finished)


class VirtualToolTest(unittest.TestCase):
    def test_call_agent_spec_is_openai_function(self):
        spec = call_agent_spec(ROLES["coder"], profile="近期表现：code 8/10")
        o = spec.to_openai()
        self.assertEqual(o["type"], "function")
        self.assertEqual(o["function"]["name"], "call_coder")
        self.assertIn("近期表现", o["function"]["description"])
        self.assertEqual(o["function"]["parameters"]["required"], ["goal"])

    def test_target_of(self):
        self.assertEqual(target_of("call_researcher"), "researcher")
        self.assertIsNone(target_of("write_file"))


class MockLLMTest(unittest.TestCase):
    def test_script_then_responder(self):
        llm = MockLLM(
            script=[LLMResponse("", [ToolCall("1", "finish", {"summary": "ok"})])],
            responder=lambda msgs, tools: LLMResponse("fallback"))
        r1 = asyncio.run(llm.chat([{"role": "user", "content": "x"}]))
        r2 = asyncio.run(llm.chat([{"role": "user", "content": "y"}]))
        self.assertEqual(r1.tool_calls[0].name, "finish")
        self.assertEqual(r2.text, "fallback")
        self.assertEqual(len(llm.calls), 2)


class SettingsTest(unittest.TestCase):
    def test_defaults_match_design(self):
        s = Settings()
        self.assertEqual(s.max_orchestrator_rounds, 8)
        self.assertEqual(s.max_worker_steps, 12)
        self.assertEqual(s.max_delegation_depth, 2)
        self.assertEqual(s.memory_dir.name, "memory")

    def test_overrides_and_unknown_keys(self):
        self.assertEqual(Settings.from_env(sandbox_backend="docker").sandbox_backend, "docker")
        with self.assertRaises(TypeError):
            Settings.from_env(no_such_setting=1)


class ImportTest(unittest.TestCase):
    def test_every_module_imports(self):
        import mas.agents.orchestrator  # noqa: F401
        import mas.agents.worker  # noqa: F401
        import mas.core.board  # noqa: F401
        import mas.core.bus  # noqa: F401
        import mas.core.human  # noqa: F401
        import mas.core.router  # noqa: F401
        import mas.core.state  # noqa: F401
        import mas.eval.harness  # noqa: F401
        import mas.llm.deepseek  # noqa: F401
        import mas.memory.base  # noqa: F401
        import mas.sandbox.base  # noqa: F401
        import mas.tools.base  # noqa: F401


if __name__ == "__main__":
    unittest.main()
