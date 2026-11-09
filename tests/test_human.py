"""CliHumanIO and the HumanIO helpers (design §3.6, §7)."""
from __future__ import annotations

import asyncio
import unittest

from mas.agents.base import Agent
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CliHumanIO, HitlKind, HumanIO
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR, Message, MsgType, dm_channel
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import Task, TaskResult, TaskStatus

AGENTS = ["orchestrator", "researcher", "coder", "writer"]


def hitl_request(sender="coder", channel=GROUP_MAIN, rid="h1", question="git push 吗？", options=None,
                 kind="approval", task_id="t1") -> Message:
    return Message(MsgType.HITL_REQUEST, sender, channel, content=f"@human {question}", receiver=HUMAN,
                   mentions=[HUMAN], payload={"request_id": rid, "task_id": task_id, "root_id": "R1",
                                              "kind": kind, "question": question, "options": options or []})


class CliBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = InMemoryBus()
        for a in AGENTS + [HUMAN]:
            self.bus.join(a, GROUP_MAIN)
        self.out: list[str] = []
        self.lines: asyncio.Queue[str | None] = asyncio.Queue()
        self.cli = CliHumanIO(read_line=self.lines.get, write=self.out.append)
        self.runner = asyncio.create_task(self.cli.run(self.bus))
        await asyncio.sleep(0)

    async def asyncTearDown(self):
        self.runner.cancel()
        await asyncio.gather(self.runner, return_exceptions=True)

    async def type(self, line: str):
        """The human types a line; wait until the CLI has handled it."""
        await self.lines.put(line)
        await _settle()

    async def feed(self, msg: Message):
        """A message arrives from the bus; wait until it has been shown."""
        await self.bus.publish(msg)
        await _settle()

    def sent(self, channel=GROUP_MAIN, type_=MsgType.CHAT):
        return [m for m in self.bus.history(channel, 100) if m.sender == HUMAN and m.type == type_]


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0.005)


class InputTest(CliBase):
    async def test_plain_text_goes_to_the_group_for_the_orchestrator(self):
        await self.type("调研 X 并写个脚本")
        [m] = self.sent()
        self.assertEqual((m.channel, m.receiver, m.mentions), (GROUP_MAIN, None, []))

    async def test_a_single_mention_directs_the_message(self):
        await self.type("@coder 写个脚本")
        [m] = self.sent()
        self.assertEqual((m.receiver, m.mentions, m.content), ("coder", ["coder"], "@coder 写个脚本"))

    async def test_two_mentions_have_no_single_receiver_and_unknown_names_are_not_mentions(self):
        await self.type("@coder @writer 一起做，@nobody 别管")
        [m] = self.sent()
        self.assertEqual((m.receiver, m.mentions), (None, ["coder", "writer"]))

    async def test_dm(self):
        await self.type("/dm coder 修一下这个 bug")
        [m] = self.sent(dm_channel(HUMAN, "coder"))
        self.assertEqual((m.receiver, m.content), ("coder", "修一下这个 bug"))
        self.assertEqual(self.sent(), [])                  # nothing leaks into the group

    async def test_dm_errors(self):
        await self.type("/dm nobody hi")
        await self.type("/dm coder")
        self.assertIn("没有这个 agent：nobody", self.out[-2])
        self.assertIn("researcher", self.out[-2])
        self.assertIn("用法", self.out[-1])
        self.assertEqual(self.sent(dm_channel(HUMAN, "nobody")), [])

    async def test_status_and_cancel_go_to_the_orchestrator(self):
        await self.type("/status")
        await self.type("/cancel")
        self.assertEqual([(m.content, m.receiver) for m in self.sent()],
                         [("/status", ORCHESTRATOR), ("/cancel", ORCHESTRATOR)])

    async def test_cancel_with_an_agent_name_goes_to_that_dm(self):
        await self.type("/cancel coder")
        [m] = self.sent(dm_channel(HUMAN, "coder"))
        self.assertEqual((m.content, m.receiver), ("/cancel", "coder"))
        self.assertEqual(self.sent(), [])

    async def test_cancel_without_an_agent_name_goes_to_the_orchestrator(self):
        await self.type("/cancel")
        await self.type("/cancel R2")                      # not an agent: passed on as it is
        await self.type("/cancel nobody")
        self.assertEqual([(m.content, m.receiver) for m in self.sent()],
                         [("/cancel", ORCHESTRATOR), ("/cancel R2", ORCHESTRATOR), ("/cancel nobody", ORCHESTRATOR)])

    async def test_help_unknown_command_and_blank_lines(self):
        await self.type("/help")
        self.assertIn("/reply", self.out[-1])
        await self.type("/nope")
        self.assertIn("不认识的命令 /nope", self.out[-1])
        n = len(self.out)
        await self.type("   ")
        self.assertEqual(len(self.out), n)

    async def test_quit_and_end_of_input_stop_run(self):
        await self.type("/quit")
        await asyncio.wait_for(self.runner, 1)
        q: asyncio.Queue = asyncio.Queue()
        cli2 = CliHumanIO(read_line=q.get, write=lambda s: None)
        run2 = asyncio.create_task(cli2.run(self.bus))
        await q.put(None)                                  # end of input
        await asyncio.wait_for(run2, 1)


class CancelNoticeTest(CliBase):
    def notice(self, roots, channel=GROUP_MAIN, sender="orchestrator"):
        return Message(MsgType.CHAT, sender, channel, content=f"已取消 {', '.join(roots)}",
                       receiver=HUMAN, payload={"cancelled_roots": roots})

    async def test_requests_of_cancelled_roots_are_dropped(self):
        dm = dm_channel(HUMAN, "coder")
        await self.feed(hitl_request(rid="h1"))                                         # group, R1
        await self.feed(hitl_request(rid="h2", sender="writer"))                         # group, R1
        r2 = hitl_request(rid="h3"); r2.payload["root_id"] = "R2"
        await self.feed(r2)                                                              # group, R2
        await self.feed(hitl_request(channel=dm, rid="h1"))                              # a DM's R1
        await self.feed(self.notice(["R1"]))
        self.assertEqual(sorted(self.cli._pending), sorted([(GROUP_MAIN, "h3"), (dm, "h1")]))
        self.assertEqual(self.out[-1], "[orchestrator] 已取消 R1")                        # the notice itself is shown
        await self.type("/reply h1 yes")                                                 # h1 is the DM's now
        self.assertEqual([m.channel for m in self.bus.history(dm) if m.type == MsgType.HITL_RESPONSE], [dm])
        await self.type("/reply h2 yes")
        self.assertIn("没有等待回答的请求 h2", self.out[-1])

    async def test_a_dropped_request_sends_no_response(self):
        await self.feed(hitl_request())
        await self.feed(self.notice(["R1"]))
        await _settle()
        self.assertEqual([m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_RESPONSE], [])

    async def test_an_empty_notice_changes_nothing(self):
        await self.feed(hitl_request())
        await self.feed(self.notice([]))
        self.assertEqual(len(self.cli._pending), 1)


class ShutdownTest(CliBase):
    async def test_open_requests_are_dropped_when_run_ends(self):
        await self.feed(hitl_request())
        self.assertEqual(len(self.cli._pending), 1)
        await self.type("/quit")
        await asyncio.wait_for(self.runner, 1)
        self.assertEqual((self.cli._pending, self.cli._answering()), ({}, set()))


class OutputTest(CliBase):
    async def test_what_is_shown(self):
        await self.feed(Message(MsgType.CHAT, "orchestrator", GROUP_MAIN, "好的，我来安排"))
        await self.feed(Message(MsgType.TASK_ASSIGN, "orchestrator", GROUP_MAIN, "@coder 写脚本", receiver="coder"))
        await self.feed(Message(MsgType.STATUS, "coder", GROUP_MAIN, "coder：收到 t1：写脚本",
                                payload={"task_id": "t1", "status": "running", "note": "", "public": True}))
        await self.feed(Message(MsgType.TASK_RESULT, "coder", GROUP_MAIN, "@orchestrator 完成：好了"))
        self.assertEqual(self.out[1:], [
            "[orchestrator] 好的，我来安排",
            "[orchestrator] @coder 写脚本",
            "· coder：收到 t1：写脚本",
            "[coder] @orchestrator 完成：好了"])

    async def test_what_is_not_shown(self):
        n = len(self.out)
        await self.feed(Message(MsgType.STATUS, "coder", GROUP_MAIN, "",
                                payload={"task_id": "t1", "status": "running", "note": "第 3 步", "public": False}))
        await self.feed(Message(MsgType.HITL_RESPONSE, "human", GROUP_MAIN, payload={"request_id": "h1", "answer": "y"}))
        await self.feed(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "我自己说的话"))     # own messages echo back
        self.assertEqual(len(self.out), n)

    async def test_a_status_is_only_shown_when_it_is_public(self):
        n = len(self.out)
        await self.feed(Message(MsgType.STATUS, "coder", GROUP_MAIN, "coder：第 3 步",
                                payload={"task_id": "t1", "status": "running", "note": "第 3 步", "public": False}))
        self.assertEqual(len(self.out), n)

    async def test_dm_messages_are_tagged_with_the_agent(self):
        dm = dm_channel(HUMAN, "coder")
        await self.feed(Message(MsgType.TASK_RESULT, "coder", dm, "@human 完成：修好了", receiver=HUMAN))
        self.assertEqual(self.out[-1], "(私聊·coder) [coder] @human 完成：修好了")

    async def test_hitl_request_text(self):
        await self.feed(hitl_request(options=["yes", "no"]))
        self.assertEqual(self.out[-1], "? [h1] coder 请求批准：git push 吗？　可选：yes / no\n   回复：/reply h1 <回答>")
        await self.feed(hitl_request(sender="orchestrator", rid="h2", kind="clarify", question="哪个版本？", task_id=None))
        self.assertIn("需要澄清：哪个版本？", self.out[-1])
        await self.feed(hitl_request(channel=dm_channel(HUMAN, "coder"), rid="h1", kind="advice", question="换方法？"))
        self.assertTrue(self.out[-1].startswith("(私聊·coder) ? [h1] coder 请求帮助：换方法？"))
        self.assertTrue(self.out[-1].endswith("回复：/reply coder:h1 <回答>"))


class ReplyTest(CliBase):
    def responses(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 100) if m.type == MsgType.HITL_RESPONSE]

    async def test_reply_publishes_a_response_in_the_requests_channel(self):
        req = hitl_request()
        await self.feed(req)
        self.assertEqual(self.responses(), [])
        await self.type("/reply h1 yes")
        [r] = self.responses()
        self.assertEqual((r.sender, r.receiver, r.reply_to, r.payload), (HUMAN, "coder", req.id,
                                                                    {"request_id": "h1", "answer": "yes"}))
        self.assertEqual(self.out[-1], "已回复 h1：yes")

    async def test_the_answer_may_contain_spaces(self):
        await self.feed(hitl_request(kind="clarify", question="哪个版本？"))
        await self.type("/reply h1 用 Python 3.11，别用 3.12")
        self.assertEqual(self.responses()[0].payload["answer"], "用 Python 3.11，别用 3.12")

    async def test_the_id_can_be_left_out_when_one_request_is_open(self):
        await self.feed(hitl_request())
        await self.type("/reply yes")
        self.assertEqual(self.responses()[0].payload["answer"], "yes")

    async def test_several_requests_can_be_open_and_are_answered_by_id(self):
        await self.feed(hitl_request(rid="h1"))
        await self.feed(hitl_request(sender="writer", rid="h2", question="删除 old.md 吗？"))
        await self.type("/reply no")                       # ambiguous without an id
        self.assertIn("请写上编号", self.out[-1])
        self.assertEqual(self.responses(), [])
        await self.type("/reply h2 no")
        self.assertEqual([(r.receiver, r.payload["request_id"]) for r in self.responses()], [("writer", "h2")])
        await self.type("/reply h1 yes")
        self.assertEqual(len(self.responses()), 2)

    async def test_group_and_dm_requests_with_the_same_id(self):
        dm = dm_channel(HUMAN, "coder")
        await self.feed(hitl_request(rid="h1", question="群里的"))
        await self.feed(hitl_request(channel=dm, rid="h1", question="私聊的"))
        await self.type("/reply h1 群答")                  # a bare id means the group's
        self.assertEqual([r.payload["answer"] for r in self.responses(GROUP_MAIN)], ["群答"])
        self.assertEqual(self.responses(dm), [])
        await self.type("/reply coder:h1 私答")
        self.assertEqual([r.payload["answer"] for r in self.responses(dm)], ["私答"])

    async def test_a_bare_id_that_only_exists_in_a_dm_finds_it(self):
        dm = dm_channel(HUMAN, "coder")
        await self.feed(hitl_request(channel=dm, rid="h1"))
        await self.type("/reply h1 yes")
        self.assertEqual(len(self.responses(dm)), 1)

    async def test_two_dm_requests_with_the_same_id_need_the_agent_name(self):
        await self.feed(hitl_request(channel=dm_channel(HUMAN, "coder"), rid="h1"))
        await self.feed(hitl_request(sender="writer", channel=dm_channel(HUMAN, "writer"), rid="h1"))
        await self.type("/reply h1 yes")
        self.assertIn("coder:h1 或 writer:h1", self.out[-1])
        self.assertEqual(self.responses(dm_channel(HUMAN, "coder")), [])

    async def test_reply_errors(self):
        await self.type("/reply h1 yes")
        self.assertIn("没有等待回答的请求 h1", self.out[-1])
        await self.type("/reply yes")
        self.assertIn("现在没有等待回答的请求", self.out[-1])
        await self.feed(hitl_request())
        await self.type("/reply h1")
        self.assertIn("请写上回答", self.out[-1])
        await self.type("/reply h9 yes")
        self.assertIn("等待中：h1", self.out[-1])
        self.assertEqual(self.responses(), [])

    async def test_a_request_can_only_be_answered_once(self):
        await self.feed(hitl_request())
        await self.type("/reply h1 yes")
        await self.type("/reply h1 no")
        self.assertEqual([r.payload["answer"] for r in self.responses()], ["yes"])


class IntegrationTest(unittest.IsolatedAsyncioTestCase):
    """The CLI together with the Router and an agent that asks for approval."""

    async def test_an_agent_asks_and_the_human_answers_from_the_cli(self):
        bus = InMemoryBus()
        for a in AGENTS + [HUMAN]:
            bus.join(a, GROUP_MAIN)
        state = StateTable()
        settings = Settings(subtask_timeout_s=2.0)
        router = Router(bus, state, {}, settings)
        out: list[str] = []
        lines: asyncio.Queue = asyncio.Queue()
        cli = CliHumanIO(read_line=lines.get, write=out.append)

        class Pusher(Agent):
            async def handle_task(self, task: Task) -> TaskResult:
                answer = await self.ask_human(task, "git push 吗？", HitlKind.APPROVAL, ["yes", "no"])
                return TaskResult(task.id, answer == "yes", f"人类说 {answer}")
        coder = Pusher("coder", bus, router, settings)
        running = [asyncio.create_task(cli.run(bus)), asyncio.create_task(coder.run())]
        try:
            dispatch = asyncio.create_task(router.dispatch(
                requester="orchestrator", target="coder", goal="写脚本并推送", session_id=GROUP_MAIN,
                root_id="R1", origin_channel=GROUP_MAIN))
            await _until(lambda: any("请求批准" in o for o in out))
            [task] = state.by_root("R1")
            self.assertEqual(task.status, TaskStatus.WAITING_HUMAN)
            self.assertFalse(dispatch.done())
            await lines.put("/reply h1 yes")
            result = await asyncio.wait_for(dispatch, 2)
            self.assertEqual((result.success, result.summary), (True, "人类说 yes"))
            self.assertEqual(task.status, TaskStatus.DONE)
            self.assertTrue(any("[orchestrator] @coder 写脚本并推送" == o for o in out))
            self.assertTrue(any("@orchestrator 完成：人类说 yes" in o for o in out))
        finally:
            for t in running:
                t.cancel()
            await asyncio.gather(*running, return_exceptions=True)


class DmCancelIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """/dm a task, the agent asks for approval, then /cancel <agent>: nothing is left waiting."""

    async def test_cancel_releases_the_agent_and_clears_the_cli(self):
        bus = InMemoryBus()
        for a in AGENTS + [HUMAN]:
            bus.join(a, GROUP_MAIN)
        state = StateTable()
        settings = Settings(subtask_timeout_s=2.0)
        router = Router(bus, state, {}, settings)
        out: list[str] = []
        lines: asyncio.Queue = asyncio.Queue()
        cli = CliHumanIO(read_line=lines.get, write=out.append)
        answers: list[str] = []

        class Pusher(Agent):
            async def handle_task(self, task: Task) -> TaskResult:
                answer = await self.ask_human(task, "git push 吗？", HitlKind.APPROVAL)
                answers.append(answer)
                return TaskResult(task.id, False, "已取消", error="cancelled")
        coder = Pusher("coder", bus, router, settings)
        running = [asyncio.create_task(cli.run(bus)), asyncio.create_task(coder.run())]
        try:
            await lines.put("/dm coder 写脚本并推送")
            await _until(lambda: any("请求批准" in o for o in out))
            self.assertEqual(len(cli._pending), 1)
            await lines.put("/cancel coder")
            await _until(lambda: answers)
            self.assertEqual(answers, ["cancelled"])                  # CANCELLED_ANSWER, not "yes"
            await _until(lambda: not cli._pending)
            self.assertTrue(any(o.endswith("已取消 R1") for o in out))
            [task] = state.by_root("R1")
            self.assertEqual(task.status, TaskStatus.CANCELLED)
        finally:
            for t in running:
                t.cancel()
            await asyncio.gather(*running, return_exceptions=True)


class DefaultReaderTest(unittest.IsolatedAsyncioTestCase):
    def test_without_a_terminal_the_plain_reader_is_used(self):
        import sys
        from contextlib import nullcontext
        from unittest import mock

        from mas.core.human import _stdin_line, default_reader
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            reader, patch = default_reader()
        self.assertIs(reader, _stdin_line)
        self.assertIs(patch, nullcontext)

    def test_injected_reader_needs_no_stdout_patch(self):
        from contextlib import nullcontext
        self.assertIs(CliHumanIO(read_line=asyncio.Queue().get)._patch_stdout, nullcontext)

    def test_without_prompt_toolkit_it_falls_back_to_input(self):
        import builtins
        import sys
        from contextlib import nullcontext
        from unittest import mock

        from mas.core.human import _stdin_line, default_reader
        real_import = builtins.__import__

        def no_prompt_toolkit(name, *a, **kw):
            if name.startswith("prompt_toolkit"):
                raise ImportError(name)
            return real_import(name, *a, **kw)
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.__import__", side_effect=no_prompt_toolkit):
            reader, patch = default_reader()
        self.assertIs(reader, _stdin_line)
        self.assertIs(patch, nullcontext)

    @unittest.skipUnless(__import__("importlib").util.find_spec("prompt_toolkit"), "prompt_toolkit is not installed")
    async def test_prompt_reader_reads_a_line_and_ends_on_ctrl_d(self):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        from mas.core.human import PromptReader
        with create_pipe_input() as inp:
            reader = PromptReader(PromptSession(input=inp, output=DummyOutput()))
            inp.send_text("/status\n")
            self.assertEqual(await asyncio.wait_for(reader(), 2), "/status")
            inp.send_text("\x04")                                  # Ctrl-D on an empty line
            self.assertIsNone(await asyncio.wait_for(reader(), 2))


class HelperTest(unittest.IsolatedAsyncioTestCase):
    async def test_request_from_and_handle_incoming_work_for_any_humanio(self):
        """AutoResponder (LI Heyang) can reuse handle_incoming: it only has to implement
        show() and answer()."""
        bus = InMemoryBus()
        bus.join(HUMAN, GROUP_MAIN)
        bus.join("coder", GROUP_MAIN)
        seen: list[str] = []

        class Auto(HumanIO):
            async def run(self, bus): ...
            async def show(self, msg): seen.append(msg.type.value)
            async def answer(self, req):
                return "yes" if req.kind == HitlKind.APPROVAL else "按原描述执行"
        auto = Auto()
        req = hitl_request(kind="approval", options=["yes", "no"])
        parsed = HumanIO.request_from(req)
        self.assertEqual((parsed.request_id, parsed.agent_id, parsed.task_id, parsed.channel, parsed.kind, parsed.options),
                         ("h1", "coder", "t1", GROUP_MAIN, HitlKind.APPROVAL, ["yes", "no"]))
        await auto.handle_incoming(bus, req)
        await _until(lambda: [m for m in bus.history(GROUP_MAIN) if m.type == MsgType.HITL_RESPONSE])
        [resp] = [m for m in bus.history(GROUP_MAIN) if m.type == MsgType.HITL_RESPONSE]
        self.assertEqual((resp.payload, resp.reply_to, resp.receiver), ({"request_id": "h1", "answer": "yes"}, req.id, "coder"))
        self.assertEqual(seen, ["hitl_request"])
        await auto.handle_incoming(bus, Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "自己的话"))
        self.assertEqual(seen, ["hitl_request"])           # own messages are skipped

    def test_orchestrator_clarification_has_an_empty_task_id(self):
        req = HumanIO.request_from(hitl_request(sender="orchestrator", kind="clarify", task_id=None))
        self.assertEqual((req.task_id, req.kind), ("", HitlKind.CLARIFY))

    def test_the_request_carries_its_root(self):
        self.assertEqual(HumanIO.request_from(hitl_request()).root_id, "R1")


async def _until(cond, timeout=2.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


if __name__ == "__main__":
    unittest.main()
