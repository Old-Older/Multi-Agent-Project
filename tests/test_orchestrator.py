"""Orchestrator: the request loop, /status, /cancel, interjections (design §2, §3)."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.orchestrator import Orchestrator
from mas.agents.roles import ROLES
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CANCELLED_ANSWER
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType, dm_channel
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.llm.base import LLMError, LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.memory.base import Memory
from tests.test_router import FakeSandbox


class Worker(Agent):
    def __init__(self, *args, handler, **kw):
        super().__init__(*args, **kw)
        self.handler = handler
        self.tasks: list[Task] = []

    async def handle_task(self, task: Task) -> TaskResult:
        self.tasks.append(task)
        return await self.handler(task)


def call(id_, name, **args) -> ToolCall:
    return ToolCall(id_, name, args)


def reply(text="", *calls) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=list(calls))


def finish(summary="全部完成", deliverables=None, id_="f") -> ToolCall:
    return call(id_, "finish", summary=summary, deliverables=deliverables or [])


async def _until(cond, timeout=2.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class OrchestratorTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bus = InMemoryBus()
        for a in ("human", "orchestrator", "researcher", "coder", "writer"):
            self.bus.join(a, GROUP_MAIN)
        self.state = StateTable()
        self.sandboxes = {a: FakeSandbox(a, self.tmp / "ws" / a) for a in ("researcher", "coder", "writer")}
        self.settings = Settings(subtask_timeout_s=2.0, data_dir=self.tmp / "data")
        self.router = Router(self.bus, self.state, self.sandboxes, self.settings)
        self.memories: dict[str, Memory] = {}
        self.running: list[asyncio.Task] = []
        self.workers: dict[str, Worker] = {}

    async def asyncTearDown(self):
        for t in self.running:
            t.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, script=None, responder=None, workers=None):
        """Start the Orchestrator (with a scripted LLM) and the workers {name: handler}."""
        self.llm = MockLLM(script=script, responder=responder)
        self.orch = Orchestrator(self.bus, self.router, self.settings, self.llm, ROLES, self.memories)
        self.running.append(asyncio.create_task(self.orch.run()))
        for name, handler in (workers or {"coder": self.ok(), "writer": self.ok(), "researcher": self.ok()}).items():
            w = Worker(name, self.bus, self.router, self.settings, handler=handler)
            self.workers[name] = w
            self.running.append(asyncio.create_task(w.run()))

    @staticmethod
    def ok(summary="完成", **kw):
        async def h(task):
            return TaskResult(task.id, True, summary, **kw)
        return h

    def writes(self, name, file, content, summary="写好了"):
        """A worker that writes `file` into its workspace and reports it as an artifact."""
        async def h(task):
            self.sandboxes[name].write_text(file, content)
            return TaskResult(task.id, True, summary, artifacts=[file])
        return h

    async def say(self, text, channel=GROUP_MAIN, **kw):
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, channel, text, **kw))

    def finals(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 200) if m.payload.get("final")]

    def chats(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 200) if m.type == MsgType.CHAT and m.sender == "orchestrator"]

    async def final(self, channel=GROUP_MAIN, n=1):
        await _until(lambda: len(self.finals(channel)) >= n)
        return self.finals(channel)[n - 1]

    def tool_results(self, call_index=-1):
        """The tool messages the LLM saw in its `call_index`-th call."""
        messages, _ = self.llm.calls[call_index]
        return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


class LoopTest(OrchestratorTestBase):
    async def test_a_simple_request(self):
        self.start([reply("剩余步骤：写脚本", call("1", "call_coder", goal="写脚本")),
                    reply("", finish("脚本写好了", ["a.py"]))],
                   workers={"coder": self.writes("coder", "a.py", "print(1)", "写好了 a.py")})
        await self.say("写个脚本")
        final = await self.final()
        self.assertEqual(final.content.split("\n")[0], "@human 脚本写好了")
        self.assertEqual((final.sender, final.receiver, final.payload["success"], final.payload["rounds"]),
                         ("orchestrator", HUMAN, True, 2))
        out = self.settings.output_dir / "R1"
        self.assertEqual((out / "a.py").read_text(), "print(1)")
        self.assertIn(f"交付物：a.py（已汇总到 {out}）", final.content)
        self.assertEqual(final.payload["deliverables"], ["a.py"])
        outcome = self.orch.outcomes["R1"]
        self.assertEqual((outcome.success, outcome.rounds, outcome.failure_mode, outcome.deliverables),
                         (True, 2, None, ["a.py"]))
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.DONE])
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertEqual(self.orch._runs, {})                          # nothing left running

    async def test_what_the_llm_sees(self):
        self.start([reply("剩余步骤：写脚本", call("1", "call_coder", goal="写脚本")), reply("", finish())],
                   workers={"coder": self.writes("coder", "a.py", "x", "很长的细节" * 400)})
        await self.say("写个脚本")
        await self.final()
        first, tools = self.llm.calls[0]
        self.assertEqual([m["role"] for m in first], ["system", "user"])
        self.assertIn("人类的请求：写个脚本", first[1]["content"])
        self.assertIn("会话看板", first[1]["content"])
        self.assertEqual([t.name for t in tools], ["call_researcher", "call_coder", "call_writer", "ask_human", "finish"])
        second, _ = self.llm.calls[1]
        self.assertEqual([m["role"] for m in second], ["system", "user", "assistant", "tool"])
        self.assertEqual(second[2]["tool_calls"][0]["function"]["name"], "call_coder")
        self.assertEqual(second[2]["content"], "剩余步骤：写脚本")
        seen = json.loads(second[3]["content"])
        self.assertEqual((seen["success"], seen["artifacts"]), (True, ["a.py"]))
        self.assertLessEqual(len(seen["summary"]), self.settings.result_summary_max_chars)   # a summary, not the full text
        self.assertEqual(second[3]["tool_call_id"], "1")

    async def test_the_plan_line_goes_to_the_board(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("剩余步骤：写脚本，再写文档", call("1", "call_coder", goal="写脚本")), reply("", finish())],
                   workers={"coder": slow})
        await self.say("做事")
        await _until(lambda: self.workers["coder"].tasks)
        self.assertEqual(self.router.board(GROUP_MAIN).roots["R1"].plan, "剩余步骤：写脚本，再写文档")
        gate.set()
        await self.final()

    async def test_calls_in_one_round_run_in_parallel(self):
        gate = asyncio.Event()
        order: list[str] = []

        async def first(task):
            order.append("coder started")
            await gate.wait()                               # only released once the writer has started
            order.append("coder done")
            return TaskResult(task.id, True, "代码")

        async def second(task):
            order.append("writer started")
            gate.set()
            return TaskResult(task.id, True, "文档")
        self.start([reply("", call("1", "call_coder", goal="写代码"), call("2", "call_writer", goal="写文档")),
                    reply("", finish())], workers={"coder": first, "writer": second})
        await self.say("代码和文档")
        await self.final()
        self.assertEqual(order[:2], ["coder started", "writer started"])
        results = self.tool_results()
        self.assertEqual([r["summary"] for r in results], ["代码", "文档"])        # in the order of the calls

    async def test_a_declined_task_is_reassigned(self):
        async def decline(task):
            return TaskResult(task.id, False, "需要运行代码", declined=True, suggest="coder", error="需要运行代码")
        self.start([reply("", call("1", "call_writer", goal="跑一下测试")),
                    reply("", call("2", "call_coder", goal="跑一下测试")), reply("", finish())],
                   workers={"writer": decline, "coder": self.ok("跑完了")})
        await self.say("跑测试")
        await self.final()
        declined = self.tool_results(1)[0]
        self.assertEqual((declined["declined"], declined["suggest"], declined["reason"]), (True, "coder", "需要运行代码"))
        self.assertEqual({t.assignee: t.status for t in self.state.by_root("R1")},
                         {"writer": TaskStatus.DECLINED, "coder": TaskStatus.DONE})

    async def test_a_failure_is_an_observation_not_an_exception(self):
        async def fail(task):
            return TaskResult(task.id, False, "", error="pip 超时", failure_mode=FailureMode.TOOL_ERROR)
        self.start([reply("", call("1", "call_coder", goal="装包")), reply("", finish("没能装上"))],
                   workers={"coder": fail})
        await self.say("装包")
        final = await self.final()
        self.assertEqual(self.tool_results(1), [{"success": False, "error": "pip 超时"}])
        self.assertEqual(final.payload["success"], True)           # the LLM chose to finish and say so

    async def test_files_are_handed_to_the_next_agent(self):
        self.start([reply("", call("1", "call_researcher", goal="调研")),
                    reply("", call("2", "call_coder", goal="写脚本", files=["notes.md"])), reply("", finish())],
                   workers={"researcher": self.writes("researcher", "notes.md", "要点"), "coder": self.ok()})
        await self.say("调研并写脚本")
        await self.final()
        self.assertEqual((self.tmp / "ws" / "coder" / "inbox" / "notes.md").read_text(), "要点")

    async def test_rounds_run_out(self):
        self.settings.max_orchestrator_rounds = 2
        self.start(responder=lambda m, t: reply("", call(str(len(m)), "call_coder", goal=f"步骤{len(m)}")),
                   workers={"coder": self.writes("coder", "part.md", "半成品", "做了一部分")})
        await self.say("很大的任务")
        final = await self.final()
        self.assertEqual(len(self.llm.calls), 2)
        self.assertEqual((final.payload["success"], final.payload["failure_mode"], final.payload["rounds"]),
                         (False, "max_rounds", 2))
        self.assertIn("已用完 2 轮", final.content)
        self.assertIn("做了一部分", final.content)                     # what was done is reported
        self.assertTrue((self.settings.output_dir / "R1" / "part.md").exists())    # and the partial files kept
        self.assertEqual(self.orch.outcomes["R1"].failure_mode, FailureMode.MAX_ROUNDS)

    async def test_text_without_tools_is_taken_as_the_answer(self):
        self.start([reply("1+1 等于 2")])
        await self.say("1+1 等于几？")
        final = await self.final()
        self.assertEqual((final.content, final.payload["success"]), ("@human 1+1 等于 2", True))
        self.assertEqual(self.state.by_root("R1"), [])

    async def test_an_empty_response_costs_a_round_and_gets_a_nudge(self):
        self.start([reply(""), reply("", finish("好了"))])
        await self.say("做事")
        final = await self.final()
        self.assertEqual(final.payload["rounds"], 2)
        self.assertIn("请调用一个工具", self.llm.calls[1][0][-1]["content"])

    async def test_bad_tool_calls_are_observations(self):
        self.start([reply("", call("1", "call_nobody", goal="x"), call("2", "call_coder"), call("3", "dance")),
                    reply("", finish())])
        await self.say("做事")
        await self.final()
        errors = [r["error"] for r in self.tool_results(1)]
        self.assertEqual(errors, ["没有这个 agent：nobody", "缺少参数 goal", "没有这个工具：dance"])

    async def test_finish_must_be_called_alone(self):
        self.start([reply("", call("1", "call_coder", goal="写脚本"), finish("太早了")),
                    reply("", finish("这回对了"))])
        await self.say("写脚本")
        final = await self.final()
        self.assertEqual(final.content.split("\n")[0], "@human 这回对了")
        self.assertIn("finish 要单独调用", self.tool_results(1)[1]["error"])

    async def test_a_missing_deliverable_is_reported(self):
        self.start([reply("", finish("好了", ["ghost.md"]))])
        await self.say("做事")
        final = await self.final()
        self.assertIn("找不到这些文件：ghost.md", final.content)
        self.assertEqual(final.payload["deliverables"], [])

    async def test_an_llm_error_ends_the_request_with_a_report(self):
        def boom(messages, tools):
            raise LLMError("429 限流")
        self.start(responder=boom)
        await self.say("做事")
        final = await self.final()
        self.assertEqual((final.payload["success"], final.payload["failure_mode"]), (False, "crash"))
        self.assertIn("调用 LLM 失败：429 限流", final.content)

    async def test_a_bug_does_not_leave_the_root_open(self):
        def bug(messages, tools):
            raise ValueError("程序 bug")
        self.start(responder=bug)
        with self.assertLogs("mas.agents.base", level="ERROR"):
            await self.say("做事")
            await _until(lambda: [m for m in self.chats() if "内部出错" in m.content])
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertEqual((self.orch._runs, self.orch.outcomes["R1"].failure_mode), ({}, FailureMode.CRASH))

    async def test_the_second_request_sees_the_first_on_the_board(self):
        self.start([reply("", finish("会议纪要整理好了", [])), reply("", finish("已翻译"))])
        await self.say("整理会议纪要")
        await self.final()
        await self.say("把刚才的纪要翻译成英文")
        await self.final(n=2)
        second_first_call = self.llm.calls[1][0][1]["content"]
        self.assertIn("R1 会议纪要整理好了", second_first_call)
        self.assertEqual(sorted(self.orch.outcomes), ["R1", "R2"])


class ClarifyTest(OrchestratorTestBase):
    async def test_ask_human_and_use_the_answer(self):
        self.start([reply("", call("1", "ask_human", question="哪个版本？", options=["3.10", "3.11"])),
                    reply("", call("2", "call_coder", goal="用 3.11 写脚本")), reply("", finish())])
        await self.say("写个脚本")
        await _until(lambda: [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST])
        [req] = [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST]
        self.assertEqual((req.sender, req.payload["task_id"], req.payload["kind"], req.payload["options"]),
                         ("orchestrator", None, "clarify", ["3.10", "3.11"]))
        self.assertEqual(self.state.by_root("R1"), [])                # a question is not a task
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN,
                                       payload={"request_id": "h1", "answer": "3.11"}))
        await self.final()
        self.assertEqual(self.tool_results(1), [{"answer": "3.11"}])
        self.assertIn("h1「哪个版本？」→ 3.11", self.router.board(GROUP_MAIN).render())    # the board kept the decision


class MessagesTest(OrchestratorTestBase):
    def orch_for_rules(self) -> Orchestrator:
        return Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES, {})

    def test_which_messages_are_for_the_orchestrator(self):
        o = self.orch_for_rules()
        chat = lambda **kw: Message(MsgType.CHAT, **{"sender": HUMAN, "channel": GROUP_MAIN, "content": "hi", **kw})
        self.assertTrue(o.should_handle(chat()))                                   # no @: the Orchestrator answers
        self.assertTrue(o.should_handle(chat(receiver="orchestrator")))
        self.assertTrue(o.should_handle(chat(mentions=["orchestrator"])))
        self.assertFalse(o.should_handle(chat(mentions=["coder"], receiver="coder")))   # @coder: only coder
        self.assertFalse(o.should_handle(chat(mentions=["coder", "writer"])))
        self.assertFalse(o.should_handle(chat(sender="coder")))                    # agents' chat is ignored
        self.assertFalse(o.should_handle(chat(sender="orchestrator")))
        self.assertFalse(o.should_handle(chat(channel=dm_channel(HUMAN, "coder"))))   # someone else's DM

    async def test_dm_to_the_orchestrator_runs_in_that_session(self):
        dm = dm_channel(HUMAN, "orchestrator")
        self.start([reply("DM 里的回答")])
        await self.say("你好", channel=dm, receiver="orchestrator")
        final = await self.final(channel=dm)
        self.assertEqual(final.channel, dm)
        self.assertEqual(self.finals(GROUP_MAIN), [])
        self.assertTrue(self.router.board(dm).roots["R1"].finished)

    async def test_a_mention_goes_to_the_worker_not_the_orchestrator(self):
        self.start([reply("不该被调用")])
        await self.say("@coder 写个脚本", mentions=["coder"], receiver="coder")
        await _until(lambda: self.workers["coder"].tasks)
        self.assertEqual(self.llm.calls, [])


class InterjectionTest(OrchestratorTestBase):
    async def test_a_message_while_a_root_runs_is_an_addition_not_a_new_root(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("", call("1", "call_coder", goal="写脚本")), reply("", finish("已改成 3.11"))],
                   workers={"coder": slow})
        await self.say("写个脚本")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("脚本用 Python 3.11")
        await asyncio.sleep(0.02)
        self.assertEqual(list(self.router.board(GROUP_MAIN).roots), ["R1"])      # still one root
        self.assertIn("脚本用 Python 3.11", self.router.board(GROUP_MAIN).render())
        gate.set()
        await self.final()
        second, _ = self.llm.calls[1]
        self.assertEqual(second[-1], {"role": "user", "content": "（人类补充）脚本用 Python 3.11"})
        self.assertEqual(len(self.llm.calls), 2)

    async def test_after_it_finished_the_next_message_is_a_new_request(self):
        self.start([reply("", finish("一")), reply("", finish("二"))])
        await self.say("第一件")
        await self.final()
        await self.say("第二件")
        await self.final(n=2)
        self.assertEqual(sorted(self.orch.outcomes), ["R1", "R2"])


class StatusTest(OrchestratorTestBase):
    async def test_status_answers_from_the_state_table_without_the_llm(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("", call("1", "call_coder", goal="写脚本")), reply("", finish())], workers={"coder": slow})
        await self.say("写个脚本")
        await _until(lambda: self.workers["coder"].tasks)
        calls_before = len(self.llm.calls)
        await self.say("/status", receiver="orchestrator")
        await _until(lambda: [m for m in self.chats() if "进行中 1 个" in m.content])
        [status] = [m for m in self.chats() if "进行中" in m.content]
        self.assertIn("R1：任务 1 个，进行中 1 个", status.content)
        self.assertIn("coder [running]「写脚本」", status.content)
        self.assertEqual(len(self.llm.calls), calls_before)                         # no LLM call
        gate.set()
        await self.final()

    async def test_status_with_nothing_to_report(self):
        self.start([])
        await self.say("/status", receiver="orchestrator")
        await _until(lambda: self.chats())
        self.assertEqual(self.chats()[0].content, "当前会话还没有任务。")

    async def test_a_root_that_has_sent_nothing_yet_is_mentioned(self):
        gate = asyncio.Event()

        self.start(script=[reply("", finish())])
        self.orch.llm.chat = lambda messages, tools=None, temperature=0.2: _wait_then(gate, reply("", finish()))
        await self.say("做事")
        await _until(lambda: self.orch._runs)
        self.assertIn("R1 正在处理，还没有派出任务。", self.orch.status_text(GROUP_MAIN))
        gate.set()
        await self.final()


async def _wait_then(gate, value):
    await gate.wait()
    return value


class CancelTest(OrchestratorTestBase):
    async def test_cancel_stops_the_running_request(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "太晚了")
        self.start([reply("", call("1", "call_coder", goal="写脚本")), reply("", finish("不该走到这里"))],
                   workers={"coder": slow})
        await self.say("写个脚本")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: [m for m in self.chats() if m.payload.get("cancelled_roots")])
        [notice] = [m for m in self.chats() if m.payload.get("cancelled_roots")]
        self.assertEqual((notice.content, notice.payload["cancelled_roots"]), ("已取消 R1", ["R1"]))
        await _until(lambda: not self.orch._runs)
        self.assertEqual(len(self.llm.calls), 1)                                     # the loop did not go on
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.CANCELLED])
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)
        self.assertEqual(self.orch.outcomes["R1"].summary, "已取消")
        self.assertEqual(self.finals(), [])                                          # no "all done" report
        gate.set()                                                                   # the worker finishes anyway
        await asyncio.sleep(0.05)
        self.assertEqual(self.state.by_root("R1")[0].status, TaskStatus.CANCELLED)

    async def test_cancel_while_the_llm_is_thinking(self):
        gate = asyncio.Event()
        self.start([])
        self.orch.llm.chat = lambda messages, tools=None, temperature=0.2: _wait_then(gate, reply("", finish()))
        await self.say("做事")
        await _until(lambda: self.orch._runs)
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: not self.orch._runs)
        [notice] = [m for m in self.chats() if m.payload.get("cancelled_roots")]
        self.assertEqual(notice.payload["cancelled_roots"], ["R1"])                  # a root with no task yet
        self.assertIn("R1", self.router._cancelled_roots)                            # so its further calls are refused
        self.assertTrue(self.router.board(GROUP_MAIN).roots["R1"].finished)

    async def test_cancel_releases_a_pending_clarification(self):
        self.start([reply("", call("1", "ask_human", question="哪个版本？"))])
        await self.say("写个脚本")
        await _until(lambda: [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST])
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: not self.orch._runs)
        self.assertEqual(self.router._hitl_waiters, {})

    async def test_cancel_with_nothing_running(self):
        self.start([])
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: self.chats())
        self.assertEqual((self.chats()[0].content, self.chats()[0].payload), ("没有进行中的任务可以取消", {"cancelled_roots": []}))

    async def test_a_new_request_after_a_cancel_works(self):
        gate = asyncio.Event()

        async def slow(task):
            await gate.wait()
            return TaskResult(task.id, True, "ok")
        self.start([reply("", call("1", "call_coder", goal="写脚本")), reply("", finish("第二次做完了"))],
                   workers={"coder": slow})
        await self.say("第一次")
        await _until(lambda: self.workers["coder"].tasks)
        await self.say("/cancel", receiver="orchestrator")
        await _until(lambda: not self.orch._runs)
        await self.say("第二次")
        final = await self.final()
        self.assertEqual(final.payload["root_id"], "R2")
        self.assertEqual(final.content.split("\n")[0], "@human 第二次做完了")


class SpecsTest(OrchestratorTestBase):
    class FakeMemory(Memory):
        def __init__(self, text="", fail=False):
            self.text, self.fail = text, fail

        def add(self, exp): ...
        def recall(self, query, k=3): return []

        def profile(self, max_chars=300):
            if self.fail:
                raise NotImplementedError
            return self.text

    def specs(self):
        return {s.name: s for s in Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES,
                                                self.memories).function_specs(GROUP_MAIN)}

    def test_profiles_are_appended_to_the_tool_descriptions(self):
        self.memories = {"coder": self.FakeMemory("近期表现：code 8/10 成功。")}
        specs = self.specs()
        self.assertIn("近期表现：code 8/10 成功。", specs["call_coder"].description)
        self.assertIn(ROLES["coder"].capability, specs["call_coder"].description)
        self.assertNotIn("近期表现", specs["call_writer"].description)                # no memory: no profile
        self.assertEqual(list(specs), ["call_researcher", "call_coder", "call_writer", "ask_human", "finish"])

    def test_a_memory_that_cannot_give_a_profile_does_not_break_anything(self):
        self.memories = {"coder": self.FakeMemory(fail=True)}
        with self.assertLogs("mas.agents.orchestrator", level="ERROR"):
            self.assertEqual(self.specs()["call_coder"].description, ROLES["coder"].capability)

    def test_the_system_prompt_names_the_agents_and_the_rules(self):
        text = Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES, {}).system_prompt()
        for needle in ("call_coder", "call_researcher", "call_writer", "同一轮", "finish", "剩余步骤", "declined"):
            self.assertIn(needle, text)

    async def test_handle_task_is_never_used(self):
        o = Orchestrator(self.bus, self.router, self.settings, MockLLM(), ROLES, {})
        with self.assertRaises(NotImplementedError):
            await o.handle_task(Task(goal="x", assignee="orchestrator", requester="human", session_id="s",
                                     root_id="R1", origin_channel=GROUP_MAIN))


if __name__ == "__main__":
    unittest.main()
