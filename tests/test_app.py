"""Assembling the system (mas/app.py), the demo (mas/demo.py) and the entry point (python -m mas)."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from mas.agents.base import Agent
from mas.agents.roles import ROLES
from mas.app import System, WorkerParts, build_system, build_tools, default_worker_factory, make_human, make_llm
from mas.__main__ import configure_logging, parse_args
from mas.config import Settings
from mas.core.human import AutoResponder, CliHumanIO
from mas.core.lead import CHOOSE_LEAD
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR, MsgType
from mas.core.task import Task, TaskResult, TaskStatus
from mas.demo import DemoSandbox, DemoWorker, build_demo_system, demo_brain, demo_settings
from mas.llm.base import LLMResponse
from mas.llm.deepseek import DeepSeekClient
from mas.llm.hkgai import HKGAIClient
from mas.llm.mock import MockLLM
from mas.memory.base import JsonlMemory

ROOT = Path(__file__).resolve().parent.parent


async def _until(cond, timeout=5.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class TmpDirTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = Settings(data_dir=self.tmp / "data", workspaces_dir=self.tmp / "ws")
        # These tests use queues or pipes, never an interactive terminal.
        stdin = patch("sys.stdin", io.StringIO())
        stdin.start()
        self.addCleanup(stdin.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class WiringTest(TmpDirTest):
    class Stub(Agent):
        async def handle_task(self, task):
            return TaskResult(task.id, True, "ok")

    def build(self, **kw):
        return build_system(self.settings, MockLLM(), CliHumanIO(), roles=ROLES, worker_factory=lambda role, parts: self.Stub(
            role.agent_id, parts.bus, parts.router, parts.settings),
            sandbox_factory=lambda agent_id, root: DemoSandbox(agent_id, root), **kw)

    def test_everybody_is_in_the_group_and_shares_one_bus_and_router(self):
        s = self.build()
        self.assertEqual(sorted(s.bus.members(GROUP_MAIN)),
                         sorted([HUMAN, "researcher", "coder", "writer"]))
        self.assertEqual(sorted(s.workers), ["coder", "researcher", "writer"])
        self.assertIs(s.requests.router, s.router)
        self.assertTrue(all(w.router is s.router and w.bus is s.bus for w in s.workers.values()))
        self.assertIs(s.router.state, s.state)

    def test_one_workspace_and_one_memory_per_role(self):
        s = self.build()
        self.assertEqual(s.router.sandboxes, s.sandboxes)
        self.assertEqual(s.sandboxes["coder"].root, self.tmp / "ws" / "coder")
        self.assertEqual({r: m.path for r, m in s.memories.items()},
                         {r: self.settings.memory_dir / f"{r}.jsonl" for r in ROLES})
        self.assertTrue(all(isinstance(m, JsonlMemory) for m in s.memories.values()))

    def test_the_factories_and_the_roles_can_be_replaced(self):
        seen = []

        def factory(role, parts):
            seen.append((role.agent_id, type(parts), parts.sandbox.agent_id, parts.memory.path.name))
            return self.Stub(role.agent_id, parts.bus, parts.router, parts.settings)
        only = {"coder": ROLES["coder"]}
        s = build_system(self.settings, MockLLM(), CliHumanIO(), roles=only, worker_factory=factory,
                         sandbox_factory=lambda a, r: DemoSandbox(a, r))
        self.assertEqual(seen, [("coder", WorkerParts, "coder", "coder.jsonl")])
        self.assertEqual(list(s.workers), ["coder"])
        self.assertEqual(list(s.requests.roles), ["coder"])

    def test_the_default_worker_is_the_worker_agent(self):
        from mas.agents.worker import WorkerAgent
        s = build_system(self.settings, MockLLM(), CliHumanIO(), roles=ROLES,
                         sandbox_factory=lambda a, r: DemoSandbox(a, r))
        self.assertTrue(all(isinstance(w, WorkerAgent) for w in s.workers.values()))
        self.assertEqual(s.workers["coder"].role, ROLES["coder"])
        self.assertEqual(list(s.workers["coder"].tools),
                         ["read_file", "write_file", "delete_file", "list_files", "run_python", "git"])
        self.assertEqual(list(s.workers["researcher"].tools),
                         ["web_search", "fetch_url", "read_file", "write_file", "list_files"])
        self.assertEqual(list(s.workers["writer"].tools), ["read_file", "write_file", "list_files"])

    async def test_default_system_tools_write_and_read_real_workspace_files(self):
        s = build_system(self.settings, MockLLM(), CliHumanIO(), roles=ROLES)
        for name, worker in s.workers.items():
            with self.subTest(role=name):
                sb = s.sandboxes[name]
                written = await worker.tools["write_file"].run(sb, path="nested/notes.md", content=f"{name} 中文笔记")
                self.assertTrue(written.ok, written.output)
                self.assertEqual(written.files_written, ["nested/notes.md"])
                read = await worker.tools["read_file"].run(sb, path=written.files_written[0])
                self.assertTrue(read.ok, read.output)
                self.assertEqual(read.output, f"{name} 中文笔记")

    def test_build_tools_builds_every_tool_a_role_names(self):
        configured = {name: list(role.tool_names) for name, role in ROLES.items()}
        with self.assertNoLogs("mas.app", level="WARNING"):
            tools = {name: build_tools(role, replace(self.settings, search_api_key="key")) for name, role in ROLES.items()}
        self.assertEqual([t.name for t in tools["coder"]],
                         ["read_file", "write_file", "delete_file", "list_files", "run_python", "git"])
        self.assertEqual([t.name for t in tools["researcher"]],
                         ["web_search", "fetch_url", "read_file", "write_file", "list_files"])
        self.assertEqual([t.name for t in tools["writer"]], ["read_file", "write_file", "list_files"])
        self.assertEqual({name: role.tool_names for name, role in ROLES.items()}, configured)

    def test_the_keys_in_the_settings_reach_the_tools_that_need_them(self):
        settings = replace(self.settings, search_api_key="brave-key", github_token="gh-token")
        role = replace(ROLES["coder"], tool_names=["web_search", "git", "run_python"])
        search, git, python = build_tools(role, settings)
        self.assertEqual(search._api_key, "brave-key")
        self.assertEqual(git._github_token, "gh-token")
        self.assertTrue(git.requires_approval)                      # a push waits for the human
        self.assertFalse(python.requires_approval)

    def test_the_early_stop_nudges_default_to_on_and_the_environment_can_turn_them_off(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual((settings.early_stop_nudges, settings.research_note_after, settings.research_note_every),
                         (True, 6, 2))
        for value, expected in (("0", False), ("off", False), ("false", False), ("1", True), ("on", True)):
            with patch.dict(os.environ, {"EARLY_STOP_NUDGES": value}, clear=True):
                self.assertEqual(Settings.from_env().early_stop_nudges, expected, value)

    def test_web_search_without_a_key_still_works_through_the_keyless_search(self):
        role = replace(ROLES["researcher"], tool_names=["fetch_url", "web_search"])
        with self.assertNoLogs("mas.app", level="WARNING"):
            with self.assertLogs("mas.app", level="INFO") as logs:
                tools = build_tools(role, replace(self.settings, search_api_key=""))
        self.assertEqual([t.name for t in tools], ["fetch_url", "web_search"])
        self.assertEqual(len(logs.records), 1)
        self.assertIn("keyless", logs.output[0])

    def test_build_tools_preserves_configured_order_and_returns_fresh_instances(self):
        role = replace(ROLES["writer"], tool_names=["list_files", "read_file", "write_file"])
        first, second = build_tools(role, self.settings), build_tools(role, self.settings)
        self.assertEqual([tool.name for tool in first], role.tool_names)
        self.assertTrue(all(a is not b for a, b in zip(first, second)))

    def test_build_tools_rejects_unknown_names(self):
        role = replace(ROLES["writer"], tool_names=["read_file", "write_flie"])
        with self.assertRaisesRegex(ValueError, "unknown tool 'write_flie'"):
            build_tools(role, self.settings)

    def test_the_default_sandbox_follows_the_settings(self):
        from mas.sandbox.base import DockerSandbox, LocalSandbox
        self.assertTrue(all(type(sb) is LocalSandbox for sb in build_system(self.settings, MockLLM(), CliHumanIO(), roles=ROLES).sandboxes.values()))
        self.settings.sandbox_backend = "docker"
        self.assertTrue(all(type(sb) is DockerSandbox for sb in build_system(self.settings, MockLLM(), CliHumanIO(), roles=ROLES).sandboxes.values()))

    def test_making_the_llm_and_the_human(self):
        with self.assertRaises(SystemExit) as e:
            make_llm(Settings())
        self.assertIn("HKGAI_API_KEY", str(e.exception))
        self.assertIn("--demo", str(e.exception))
        with self.assertRaisesRegex(SystemExit, "HKGAI_MODEL is not set"):
            make_llm(Settings(hkgai_api_key="fixture", hkgai_model=""))
        with self.assertRaisesRegex(SystemExit, "LLM_PROVIDER=hkgai or LLM_PROVIDER=deepseek"):
            make_llm(Settings(llm_provider="openai"))
        self.assertIsInstance(make_human(Settings()), CliHumanIO)
        self.assertIsInstance(make_human(Settings(auto_hitl=True)), AutoResponder)

    def test_default_provider_ignores_other_providers_settings(self):
        other = {"DEEPSEEK_API_KEY": "other-fixture", "DEEPSEEK_MODEL": "other-model",
                 "DEEPSEEK_BASE_URL": "https://other.invalid"}
        with patch.dict(os.environ, other, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.llm_provider, "hkgai")
        self.assertEqual(settings.hkgai_base_url, "https://api1.hkgai.net/v1")
        self.assertEqual(settings.hkgai_model, "t2_hkgai-v3_fp8_1m_e7")
        self.assertEqual(settings.hkgai_api_key, "")
        with self.assertRaisesRegex(SystemExit, "HKGAI_API_KEY is not set"):
            make_llm(settings)
        llm = make_llm(replace(settings, hkgai_api_key="fixture"))
        self.assertEqual((llm.model, llm.base_url), (settings.hkgai_model, settings.hkgai_base_url))

    def test_deepseek_is_used_only_when_asked_for(self):
        env = {"DEEPSEEK_API_KEY": "ds-fixture", "HKGAI_API_KEY": "hk-fixture"}
        with patch.dict(os.environ, env, clear=True):
            default = make_llm(Settings.from_env())
            chosen = make_llm(Settings.from_env(llm_provider="deepseek"))
        self.assertIs(type(default), HKGAIClient)
        self.assertIsInstance(chosen, DeepSeekClient)
        self.assertEqual((chosen.api_key, chosen.model, chosen.base_url),
                         ("ds-fixture", "deepseek-chat", "https://api.deepseek.com/v1"))
        self.assertEqual(chosen.thinking, "off")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k", "DEEPSEEK_THINKING": "default"}, clear=True):
            self.assertEqual(make_llm(Settings.from_env(llm_provider="deepseek")).thinking, "default")

    def test_deepseek_settings_come_from_the_environment_and_errors_name_deepseek(self):
        env = {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "ds-fixture", "DEEPSEEK_MODEL": "deepseek-reasoner",
               "DEEPSEEK_BASE_URL": "https://gateway.invalid/v1"}
        with patch.dict(os.environ, env, clear=True):
            llm = make_llm(Settings.from_env())
        self.assertEqual((llm.api_key, llm.model, llm.base_url),
                         ("ds-fixture", "deepseek-reasoner", "https://gateway.invalid/v1"))
        with self.assertRaisesRegex(SystemExit, "DEEPSEEK_API_KEY is not set"):
            make_llm(Settings(llm_provider="deepseek", hkgai_api_key="set-but-not-used"))
        with self.assertRaisesRegex(SystemExit, "DEEPSEEK_MODEL is not set"):
            make_llm(Settings(llm_provider="deepseek", deepseek_api_key="x", deepseek_model=""))

    def test_hkgai_factory_uses_account_settings_and_model_override(self):
        env = {"HKGAI_API_KEY": "fixture", "HKGAI_MODEL": "account-model",
               "HKGAI_BASE_URL": "https://gateway.invalid/v1"}
        with patch.dict(os.environ, env, clear=True):
            llm = make_llm(Settings.from_env())
            selected = make_llm(Settings.from_env(hkgai_model="selected-model"))
        self.assertIsInstance(llm, HKGAIClient)
        self.assertEqual((llm.api_key, llm.model, llm.base_url),
                         ("fixture", "account-model", "https://gateway.invalid/v1"))
        self.assertEqual(selected.model, "selected-model")


class LifecycleTest(TmpDirTest):
    async def test_start_and_stop(self):
        s = build_demo_system(demo_settings(self.settings, self.tmp), delay=0)
        tasks = s.start()
        self.assertEqual(sorted(t.get_name() for t in tasks),
                         sorted(f"agent:{a}" for a in ("researcher", "coder", "writer")))
        await asyncio.sleep(0.01)
        self.assertTrue(all(not t.done() for t in tasks))
        await s.stop()
        self.assertTrue(all(t.done() for t in tasks))
        self.assertEqual(s._tasks, [])

    async def test_run_ends_when_the_human_quits_and_stops_the_agents(self):
        lines: asyncio.Queue = asyncio.Queue()
        s = build_demo_system(demo_settings(self.settings, self.tmp), delay=0, read_line=lines.get, write=lambda t: None)
        runner = asyncio.create_task(s.run())
        await asyncio.sleep(0.02)
        agent_tasks = list(s._tasks)
        await lines.put("/quit")
        await asyncio.wait_for(runner, 2)
        self.assertTrue(all(t.done() for t in agent_tasks))


class BrainTest(unittest.TestCase):
    def lead(self, request):
        """Who the demo's "LLM" names as the lead of `request`."""
        messages = [{"role": "system", "content": "rules"},
                    {"role": "user", "content": f"Team members:\n- coder\n\nRequest from the human:\n{request}"}]
        [call] = demo_brain(messages, None).tool_calls
        self.assertEqual(call.name, CHOOSE_LEAD)
        return call.arguments["agent_id"]

    def test_the_first_agent_the_request_needs_leads(self):
        self.assertEqual(self.lead("write a python script"), "coder")
        self.assertEqual(self.lead("research X and write a summary"), "researcher")
        self.assertEqual(self.lead("write a script and the docs"), "coder")
        self.assertEqual(self.lead("do something"), "writer")                       # nothing recognised
        self.assertEqual(self.lead("写个脚本并整理文档"), "coder")


class SandboxTest(TmpDirTest):
    async def test_files_only_and_nothing_leaves_the_workspace(self):
        sb = DemoSandbox("coder", self.tmp / "ws")
        sb.write_text("sub/a.txt", "héllo")
        self.assertEqual((sb.read_text("sub/a.txt"), sb.exists("sub/a.txt"), sb.list_dir("sub")), ("héllo", True, ["a.txt"]))
        with self.assertRaises(PermissionError):
            sb.resolve("../outside")
        sb.delete("sub/a.txt")
        self.assertFalse(sb.exists("sub/a.txt"))
        self.assertEqual((await sb.exec(["ls"])).returncode, 1)
        src = self.tmp / "x.md"
        src.write_text("from another agent")
        self.assertEqual(sb.import_file(src), "inbox/x.md")
        self.assertEqual(sb.read_text("inbox/x.md"), "from another agent")


class DemoFlowTest(TmpDirTest):
    """The whole system with the demo parts, driven through the command line."""

    async def asyncSetUp(self):
        self.lines: asyncio.Queue = asyncio.Queue()
        self.out: list[str] = []
        self.settings = demo_settings(Settings(), self.tmp)
        self.system = build_demo_system(self.settings, delay=0, read_line=self.lines.get, write=self.out.append)
        self.runner = asyncio.create_task(self.system.run())
        await asyncio.sleep(0.02)

    async def asyncTearDown(self):
        await self.lines.put("/quit")
        await asyncio.wait_for(self.runner, 3)

    async def say(self, text):
        await self.lines.put(text)

    def shown(self, needle):
        return [o for o in self.out if needle in o]

    def finals(self):
        return [m for m in self.system.bus.history(GROUP_MAIN, 500) if m.payload.get("final")]

    async def request(self, text, n):
        await self.say(text)
        await _until(lambda: len(self.finals()) >= n)
        return self.finals()[n - 1]

    async def test_a_request_that_needs_two_agents(self):
        final = await self.request("write a python script that prints hello and a document summarizing it", 1)
        self.assertEqual((final.payload["success"], final.sender), (True, "coder"))    # the first agent it needs leads
        files = sorted(p.name for p in Path(final.payload["output_dir"]).iterdir())
        self.assertEqual((len(files), files[0].startswith("document-"), files[1].startswith("script-")), (2, True, True))
        self.assertEqual(self.system.requests.outcomes["R1"].deliverables, final.payload["deliverables"])
        await _until(lambda: self.shown("Deliverables:"))                        # the command line shows messages a moment later
        self.assertEqual(len(self.shown("Done:")), 1)                            # the teammate reported to the lead in the group
        self.assertEqual({t.assignee for t in self.system.state.by_root("R1")}, {"coder", "writer"})
        coder, writer = (self.system.memories[a].all() for a in ("coder", "writer"))
        self.assertEqual([(e.success, e.tags) for e in coder], [(True, ["code", "file"])])      # every agent remembers its task
        self.assertEqual([(e.success, e.tags) for e in writer], [(True, ["file", "doc"])])

    async def test_a_job_the_writer_cannot_do_is_reassigned(self):
        final = await self.request("run the tests", 1)
        self.assertEqual(final.payload["success"], True)
        self.assertEqual({t.assignee: t.status for t in self.system.state.by_root("R1")},
                         {"writer": TaskStatus.DONE, "coder": TaskStatus.DONE})     # the lead (writer) passed the job on
        self.assertEqual(final.sender, "writer")

    async def test_a_risky_step_waits_for_the_human(self):
        await self.say("write a script and push it to github")
        await _until(lambda: self.shown("asks for approval"))
        self.assertEqual(self.finals(), [])
        self.assertEqual([t.status for t in self.system.state.by_root("R1")], [TaskStatus.WAITING_HUMAN])
        await self.say("/status")
        await _until(lambda: self.shown("R1: 1 task, 1 in progress"))
        await self.say("/reply yes")
        await _until(lambda: self.finals())
        self.assertTrue(self.finals()[0].payload["success"])

    async def test_a_refusal_is_remembered_and_shown_next_time(self):
        await self.say("write a script and push it")
        await _until(lambda: self.shown("asks for approval"))
        await self.say("/reply no")
        final = await _wait_final(self, 1)
        self.assertIn("the human did not approve", final.content)
        memory = self.system.memories["coder"].all()
        self.assertEqual([(e.success, e.tags, e.lesson[:20]) for e in memory], [(False, ["git"], "the human did not ap")])
        self.assertIn("git 0/1 succeeded", self.system.memories["coder"].profile())
        await self.say("write a script and push it again")                           # similar goal: the lesson is recalled
        await _until(lambda: len(self.shown("asks for approval")) >= 2)
        await self.say("/reply yes")
        final = await _wait_final(self, 2)
        self.assertIn("remembering: the human did not approve a risky step", final.content)

    async def test_cancel_stops_everything_and_clears_the_request(self):
        await self.say("write a script and push it")
        await _until(lambda: self.shown("asks for approval"))
        await self.say("/cancel")
        await _until(lambda: self.shown("Cancelled R1"))
        await _until(lambda: not self.system.requests._runs)
        self.assertEqual([t.status for t in self.system.state.by_root("R1")], [TaskStatus.CANCELLED])
        self.assertEqual(self.finals(), [])
        self.assertEqual(self.system.human._pending, {})                           # the CLI forgot the open request
        self.assertEqual(self.system.router._hitl_waiters, {})
        final = await self.request("write a script", 1)                             # and the system is still usable
        self.assertEqual(final.payload["root_id"], "R2")

    async def test_a_direct_message_to_one_agent(self):
        await self.say("/dm researcher find out about decorators")
        await _until(lambda: self.shown("researcher finished"))
        self.assertTrue(self.shown("(DM·researcher)"))
        self.assertEqual(self.finals(), [])                                        # no request layer involved
        [task] = self.system.state.by_root("R1")
        self.assertEqual((task.assignee, task.requester, task.status), ("researcher", HUMAN, TaskStatus.DONE))

    async def test_status_after_several_requests_stays_short(self):
        for n in range(1, 5):
            await self.request("write a script", n)
        await self.say("/status")
        await _until(lambda: self.shown("Earlier requests:"))
        text = self.shown("Earlier requests:")[0]
        self.assertEqual(text.count("\n"), 1 + 1 + 3)                               # current root + header + 3 earlier lines


class SlowDemoTest(TmpDirTest):
    async def test_cancel_in_the_middle_of_the_work_stops_the_worker(self):
        lines: asyncio.Queue = asyncio.Queue()
        system = build_demo_system(demo_settings(Settings(), self.tmp), delay=0.15, read_line=lines.get,
                                   write=lambda text: None)
        runner = asyncio.create_task(system.run())
        await asyncio.sleep(0.02)
        await lines.put("write a script")
        await _until(lambda: system.state.by_root("R1") and system.state.by_root("R1")[0].status == TaskStatus.RUNNING)
        await lines.put("/cancel")
        await _until(lambda: not system.requests._runs)
        await asyncio.sleep(0.7)                                       # long enough for the worker to have finished
        self.assertEqual(list((self.tmp / "demo" / "workspaces").glob("coder/*")), [])        # it stopped: no file
        self.assertEqual(system.memories["coder"].all(), [])                                  # and no memory of a success
        self.assertEqual(system.state.by_root("R1")[0].status, TaskStatus.CANCELLED)
        await lines.put("/quit")
        await asyncio.wait_for(runner, 3)


async def _wait_final(test, n):
    await _until(lambda: len(test.finals()) >= n)
    return test.finals()[n - 1]


class LoggingTest(TmpDirTest):
    def setUp(self):
        super().setUp()
        self.root_logger = logging.getLogger()
        self.saved = (list(self.root_logger.handlers), self.root_logger.level)

    def tearDown(self):
        for h in list(self.root_logger.handlers):
            self.root_logger.removeHandler(h)
            h.close()
        for h in self.saved[0]:
            self.root_logger.addHandler(h)
        self.root_logger.setLevel(self.saved[1])
        super().tearDown()

    def kinds(self):
        return sorted(type(h).__name__ for h in self.root_logger.handlers)

    def test_an_error_goes_to_the_file_only(self):
        configure_logging(self.tmp / "logs" / "mas.log")                # the folder is created
        self.assertEqual(self.kinds(), ["FileHandler"])
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("mas.agents.base").exception("coder crashed on task t1")
        text = (self.tmp / "logs" / "mas.log").read_text(encoding="utf-8")
        self.assertIn("ERROR mas.agents.base: coder crashed on task t1", text)
        self.assertIn("ValueError: boom", text)                          # with the stack trace

    def test_verbose_also_prints_on_the_screen(self):
        configure_logging(self.tmp / "mas.log", verbose=True)
        self.assertEqual(self.kinds(), ["FileHandler", "StreamHandler"])

    def test_calling_it_twice_does_not_double_the_lines(self):
        configure_logging(self.tmp / "mas.log")
        configure_logging(self.tmp / "mas.log")
        logging.getLogger("x").warning("once")
        self.assertEqual((self.tmp / "mas.log").read_text().count("once"), 1)

    def test_configuring_again_replaces_the_old_setup(self):
        configure_logging(self.tmp / "first.log")
        configure_logging(self.tmp / "second.log", verbose=True)
        self.assertEqual(self.kinds(), ["FileHandler", "StreamHandler"])
        logging.getLogger("x").warning("only the new file")
        self.assertEqual(((self.tmp / "first.log").read_text(), "only the new file" in (self.tmp / "second.log").read_text()), ("", True))

    def test_info_messages_are_kept_in_the_file(self):
        configure_logging(self.tmp / "mas.log")
        logging.getLogger("x").info("something happened")
        self.assertIn("INFO x: something happened", (self.tmp / "mas.log").read_text())

    def test_a_log_file_that_cannot_be_written_falls_back_to_the_screen(self):
        blocker = self.tmp / "file"
        blocker.write_text("not a folder")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            configure_logging(blocker / "mas.log")                       # a folder cannot be made below a file
        self.assertEqual(self.kinds(), ["StreamHandler"])
        self.assertIn("cannot write the log file", err.getvalue())


class EntryPointTest(TmpDirTest):
    def test_arguments(self):
        a = parse_args([])
        self.assertEqual((a.demo, a.data_dir, a.delay, a.keep, a.verbose), (False, None, 0.4, False, False))
        a = parse_args(["--demo", "--data-dir", "x", "--delay", "0", "--keep", "-v"])
        self.assertEqual((a.demo, a.data_dir, a.delay, a.keep, a.verbose), (True, Path("x"), 0.0, True, True))

    def test_demo_settings_keep_everything_under_data_dir_demo(self):
        s = demo_settings(Settings(), self.tmp)
        self.assertEqual((s.data_dir, s.workspaces_dir, s.memory_dir, s.output_dir),
                         (self.tmp / "demo", self.tmp / "demo" / "workspaces", self.tmp / "demo" / "memory",
                          self.tmp / "demo" / "output"))

    def test_python_dash_m_mas_demo_runs_a_request_end_to_end(self):
        """The real program, started like a user would: a request goes in, files and a report come out."""
        env = dict(os.environ, PYTHONPATH=str(ROOT), HKGAI_API_KEY="", HKGAI_MODEL="", PYTHONIOENCODING="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "mas", "--demo", "--data-dir", str(self.tmp), "--delay", "0"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             cwd=self.tmp, env=env)
        output: queue.Queue = queue.Queue()

        def read_output():
            try:
                for line in p.stdout:
                    output.put(line)
            finally:
                output.put(None)

        # Windows select() accepts sockets only, so read the pipe in a separate thread.
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            p.stdin.write("write a python script that prints hello\n")
            p.stdin.flush()
            seen = ""
            deadline = time.monotonic() + 20
            while "Deliverables:" not in seen and time.monotonic() < deadline:
                try:
                    line = output.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    break
                seen += line
            p.stdin.write("/quit\n")
            p.stdin.flush()
            p.wait(timeout=10)
        finally:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
            p.stdin.close()
            reader.join(timeout=5)
            p.stdout.close()
        self.assertFalse(reader.is_alive())
        self.assertIn("[coder] @human coder finished 'write a python script that prints hello'", seen)
        self.assertNotIn("[orchestrator]", seen.split("> ", 1)[-1])                       # the request layer stays silent
        self.assertIn("Deliverables: script-", seen)
        self.assertEqual(p.returncode, 0)
        outputs = list((self.tmp / "demo" / "output").glob("R1-*/script-*.py"))
        self.assertEqual(len(outputs), 1)

    def run_demo(self, *args):
        """Start the demo and quit at once. Returns the process."""
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "mas", "--demo", "--data-dir", str(self.tmp), "--delay", "0", *args],
                              input="/quit\n", capture_output=True, text=True, cwd=self.tmp, env=env, timeout=30)

    def test_the_demo_starts_clean_unless_told_to_keep_the_old_data(self):
        marker = self.tmp / "demo" / "memory" / "coder.jsonl"
        marker.parent.mkdir(parents=True)
        marker.write_text("an old memory\n")
        self.assertEqual(self.run_demo("--keep").returncode, 0)
        self.assertTrue(marker.exists())                               # --keep: still there
        self.assertEqual(self.run_demo().returncode, 0)
        self.assertFalse(marker.exists())                              # default: gone

    def test_the_log_goes_to_a_file_not_to_the_screen_unless_verbose(self):
        quiet = self.run_demo()
        log = self.tmp / "mas.log"
        self.assertTrue(log.exists())
        self.assertNotIn("INFO", quiet.stderr + quiet.stdout)
        self.assertNotIn("Traceback", quiet.stderr + quiet.stdout)

    def test_the_log_is_a_file_and_stays_out_of_the_cleared_demo_folder(self):
        self.run_demo()
        self.assertTrue((self.tmp / "mas.log").exists())               # next to demo/, so clearing demo/ keeps it
        self.assertFalse((self.tmp / "demo" / "mas.log").exists())

    def test_without_a_team_the_real_system_says_what_to_do(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), HKGAI_API_KEY="", LLM_PROVIDER="")
        r = subprocess.run([sys.executable, "-m", "mas", "--data-dir", str(self.tmp)], input="", capture_output=True,
                           text=True, cwd=self.tmp, env=env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--team", r.stderr + r.stdout)

    def test_without_a_key_the_real_system_says_what_to_do(self):
        team = self.tmp / "team.md"
        team.write_text("## Writer (writer)\n\n```text\nYou write.\n```\n")
        env = dict(os.environ, PYTHONPATH=str(ROOT), HKGAI_API_KEY="", LLM_PROVIDER="")
        r = subprocess.run([sys.executable, "-m", "mas", "--team", str(team), "--data-dir", str(self.tmp)], input="", capture_output=True,
                           text=True, cwd=self.tmp, env=env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("HKGAI_API_KEY is not set", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
