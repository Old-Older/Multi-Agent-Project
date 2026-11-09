"""Router behaviour (design §2.1, §5, §7)."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import HitlKind
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType, dm_channel
from mas.core.router import Router
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.sandbox.base import ExecResult, Sandbox

AGENTS = ["orchestrator", "researcher", "coder", "writer", "human"]


class FakeSandbox(Sandbox):
    """Real directory, just enough for file hand-over."""

    def resolve(self, rel):
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise PermissionError(rel)
        return p

    def read_text(self, rel): return self.resolve(rel).read_text()

    def write_text(self, rel, content):
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def delete(self, rel): self.resolve(rel).unlink()
    def list_dir(self, rel="."): return sorted(x.name for x in self.resolve(rel).iterdir())
    def exists(self, rel): return self.resolve(rel).exists()

    async def exec(self, cmd, timeout=60.0, env=None): return ExecResult(0, "", "")

    def import_file(self, src, name=None):
        dest = self.root / "inbox" / (name or src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        return f"inbox/{dest.name}"


def result_msg(agent: str, assign: Message, result: TaskResult) -> Message:
    return Message(MsgType.TASK_RESULT, agent, assign.channel, payload={"result": result.to_dict()},
                   reply_to=assign.id, receiver=assign.sender)


class RouterTestBase(unittest.IsolatedAsyncioTestCase):
    timeout = 2.0

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bus = InMemoryBus()
        for a in AGENTS:
            self.bus.join(a, GROUP_MAIN)
        self.state = StateTable()
        self.sandboxes = {a: FakeSandbox(a, self.tmp / a) for a in ("researcher", "coder", "writer")}
        self.settings = Settings(subtask_timeout_s=self.timeout)
        self.router = Router(self.bus, self.state, self.sandboxes, self.settings)
        self.workers: list[asyncio.Task] = []
        self.seen: dict[str, list[Task]] = {}

    async def asyncTearDown(self):
        for w in self.workers:
            w.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start_worker(self, name, handler=None):
        """A fake agent: on TASK_ASSIGN for it, calls handler(task) and publishes the result.
        handler=None means it never answers."""
        self.seen[name] = []

        async def loop():
            q = self.bus.subscribe(name)
            while True:
                msg = await q.get()
                if msg.type == MsgType.TASK_ASSIGN and msg.receiver == name:
                    task = Task.from_dict(msg.payload["task"])
                    self.seen[name].append(task)
                    if handler:
                        res = await handler(task)
                        await self.bus.publish(result_msg(name, msg, res))
        self.workers.append(asyncio.create_task(loop()))

    @staticmethod
    def ok(summary="done", **kw):
        async def h(task):
            return TaskResult(task.id, True, summary, **kw)
        return h

    async def call(self, target="coder", goal="写脚本", requester="orchestrator", parent=None,
                   root="R1", origin=GROUP_MAIN, **kw):
        return await self.router.dispatch(
            requester=requester, target=target, goal=goal, parent=parent, session_id=origin,
            root_id=root, origin_channel=origin, **kw)

    def assigns(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 100) if m.type == MsgType.TASK_ASSIGN]


class DispatchTest(RouterTestBase):
    async def test_success_flow(self):
        self.start_worker("coder", self.ok("脚本写好了", artifacts=["a.py"]))
        r = await self.call()
        self.assertTrue(r.success)
        self.assertEqual(r.artifacts, ["a.py"])
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.DONE)
        [a] = self.assigns()
        self.assertEqual((a.sender, a.receiver, a.mentions, a.content),
                         ("orchestrator", "coder", ["coder"], "@coder 写脚本"))
        task = self.seen["coder"][0]
        self.assertEqual((task.chain, task.depth, task.requester), (["orchestrator"], 0, "orchestrator"))

    async def test_board_learns_task_and_result(self):
        self.start_worker("coder", self.ok("好了", artifacts=["a.py"]))
        self.router.board(GROUP_MAIN).start_root("R1", "写脚本")
        await self.call()
        text = self.router.board(GROUP_MAIN).render()
        self.assertIn("coder「写脚本」→ a.py", text)

    async def test_failure_and_decline_are_results_not_exceptions(self):
        async def fail(task): return TaskResult(task.id, False, "", error="boom", failure_mode=FailureMode.CRASH)
        async def decline(task): return TaskResult(task.id, False, "不会", declined=True, suggest="coder")
        self.start_worker("coder", fail)
        self.start_worker("writer", decline)
        r1, r2 = await self.call("coder"), await self.call("writer", goal="跑代码")
        self.assertEqual(self.state.get(r1.task_id).status, TaskStatus.FAILED)
        self.assertEqual(self.state.get(r2.task_id).status, TaskStatus.DECLINED)

    async def test_parallel_dispatch(self):
        async def slow(task):
            await asyncio.sleep(0.05)
            return TaskResult(task.id, True, task.assignee)
        for n in ("coder", "writer", "researcher"):
            self.start_worker(n, slow)
        rs = await asyncio.gather(*(self.call(n, goal=f"g-{n}") for n in ("coder", "writer", "researcher")))
        self.assertEqual(sorted(r.summary for r in rs), ["coder", "researcher", "writer"])

    async def test_dm_origin_stays_out_of_group(self):
        self.start_worker("coder", self.ok())
        dm = dm_channel("human", "coder")
        self.bus.join("human", dm)
        r = await self.call(requester="human", origin=dm)
        self.assertTrue(r.success)
        self.assertEqual(self.assigns(GROUP_MAIN), [])
        self.assertEqual(len(self.assigns(dm_channel("human", "coder"))), 1)

    async def test_timeout_then_late_result_is_ignored(self):
        self.router.settings.subtask_timeout_s = 0.05
        self.start_worker("coder")                       # never answers
        r = await self.call()
        self.assertEqual(r.failure_mode, FailureMode.TIMEOUT)
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.FAILED)
        self.assertEqual(self.router._task_waiters, {})
        assign = self.assigns()[0]
        await self.bus.publish(result_msg("coder", assign, TaskResult(r.task_id, True, "太晚了")))
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.FAILED)

    async def test_status_messages_update_state(self):
        async def h(task):
            await self.bus.publish(Message(MsgType.STATUS, "coder", GROUP_MAIN, payload={
                "task_id": task.id, "status": "running", "note": "开始", "public": False}))
            self.assertEqual(self.state.get(task.id).status, TaskStatus.RUNNING)
            return TaskResult(task.id, True, "ok")
        self.start_worker("coder", h)
        r = await self.call()
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.DONE)


class LimitTest(RouterTestBase):
    async def assertRefused(self, r, text, target=None):
        self.assertFalse(r.success)
        self.assertIn(text, r.error)
        self.assertEqual(r.failure_mode, FailureMode.TOOL_ERROR)
        if target:
            self.assertEqual(self.seen[target], [])      # the target was never contacted

    async def test_unknown_or_forbidden_target(self):
        self.start_worker("coder", self.ok())
        for t in ("nobody", "orchestrator", "human"):
            await self.assertRefused(await self.call(t), "unknown agent")
        self.assertEqual(self.state.by_root("R1"), [])   # nothing registered

    async def test_cycle(self):
        for n in ("coder", "researcher"):
            self.start_worker(n, self.ok())
        parent = Task(goal="x", assignee="coder", requester="orchestrator", session_id=GROUP_MAIN,
                      root_id="R1", origin_channel=GROUP_MAIN, chain=["orchestrator"])
        await self.assertRefused(await self.call("coder", requester="coder", parent=parent), "cycle", "coder")
        await self.assertRefused(await self.call("coder", requester="coder"), "cycle", "coder")
        await self.assertRefused(await self.call("orchestrator", requester="coder", parent=parent), "unknown agent")

    async def test_depth(self):
        self.settings.max_delegation_depth = 1
        self.start_worker("writer", self.ok())
        deep = Task(goal="x", assignee="researcher", requester="coder", session_id=GROUP_MAIN,
                    root_id="R1", origin_channel=GROUP_MAIN, chain=["orchestrator", "coder"])
        await self.assertRefused(await self.call("writer", requester="researcher", parent=deep), "depth", "writer")
        shallow = Task(goal="x", assignee="coder", requester="orchestrator", session_id=GROUP_MAIN,
                       root_id="R1", origin_channel=GROUP_MAIN, chain=["orchestrator"])
        self.assertTrue((await self.call("writer", requester="coder", parent=shallow)).success)

    async def test_delegations_per_task(self):
        for n in ("researcher", "writer"):
            self.start_worker(n, self.ok())
        parent = Task(goal="x", assignee="coder", requester="orchestrator", session_id=GROUP_MAIN,
                      root_id="R1", origin_channel=GROUP_MAIN, chain=["orchestrator"])
        self.settings.max_delegations_per_task = 2
        self.assertTrue((await self.call("researcher", goal="a", requester="coder", parent=parent)).success)
        self.assertTrue((await self.call("writer", goal="b", requester="coder", parent=parent)).success)
        await self.assertRefused(await self.call("researcher", goal="c", requester="coder", parent=parent),
                                 "already delegated")

    async def test_same_goal_retries(self):
        async def fail(task): return TaskResult(task.id, False, "", error="x")
        self.start_worker("coder", fail)
        for _ in range(3):                                # first try + 2 retries
            self.assertEqual((await self.call()).error, "x")
        await self.assertRefused(await self.call(), "tried 3 times")
        self.assertEqual((await self.call(goal="另一个目标")).error, "x")   # different goal is fine
        self.assertEqual((await self.call(root="R2")).error, "x")           # other root is fine

    async def test_declined_does_not_use_up_retries(self):
        async def decline(task): return TaskResult(task.id, False, "no", declined=True)
        self.start_worker("writer", decline)
        for _ in range(5):
            self.assertTrue((await self.call("writer")).declined)

    async def test_cancelled_root_refuses_new_calls(self):
        self.start_worker("coder", self.ok())
        self.router.cancel_root("R1")
        await self.assertRefused(await self.call(), "cancelled", "coder")
        self.assertTrue((await self.call(root="R2")).success)


class FilesTest(RouterTestBase):
    async def test_copies_from_producer_of_the_artifact(self):
        self.sandboxes["researcher"].write_text("notes.md", "要点")
        self.start_worker("researcher", self.ok(artifacts=["notes.md"]))
        self.start_worker("coder", self.ok())
        await self.call("researcher", goal="调研")
        r = await self.call("coder", goal="写脚本", files=["notes.md"])
        self.assertTrue(r.success)
        self.assertEqual((self.tmp / "coder" / "inbox" / "notes.md").read_text(), "要点")
        self.assertEqual(self.seen["coder"][0].files, ["notes.md"])

    async def test_copies_from_requesters_own_sandbox(self):
        self.sandboxes["coder"].write_text("sub/data.txt", "d")
        self.start_worker("writer", self.ok())
        r = await self.call("writer", requester="coder", files=["sub/data.txt"])
        self.assertTrue(r.success)
        self.assertEqual((self.tmp / "writer" / "inbox" / "data.txt").read_text(), "d")

    async def test_missing_or_escaping_file_is_refused(self):
        self.start_worker("coder", self.ok())
        for name in ("nope.md", "../secret"):
            r = await self.call("coder", files=[name])
            self.assertIn("file not found", r.error)
        self.assertEqual(self.seen["coder"], [])
        self.assertEqual(self.state.by_root("R1"), [])


class HitlTest(RouterTestBase):
    def make_task(self, origin=GROUP_MAIN, assignee="coder") -> Task:
        t = Task(goal="push", assignee=assignee, requester="orchestrator", session_id=origin,
                 root_id="R1", origin_channel=origin)
        self.state.register(t)
        return t

    def answer(self, channel, request_id, text):
        return self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, channel,
                                        payload={"request_id": request_id, "answer": text}))

    async def test_request_and_answer(self):
        t = self.make_task()
        fut = asyncio.create_task(self.router.request_human(t, HitlKind.APPROVAL, "git push 吗？", ["yes", "no"]))
        await asyncio.sleep(0.01)
        [req] = [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST]
        self.assertEqual(req.payload, {"request_id": "h1", "task_id": t.id, "kind": "approval",
                                       "question": "git push 吗？", "options": ["yes", "no"]})
        self.assertEqual((req.sender, req.receiver, req.content), ("coder", HUMAN, "@human git push 吗？ [yes / no]"))
        self.assertEqual(t.status, TaskStatus.WAITING_HUMAN)
        self.assertFalse(fut.done())
        await self.answer(GROUP_MAIN, "h1", "yes")
        self.assertEqual(await asyncio.wait_for(fut, 1), "yes")
        self.assertEqual(t.status, TaskStatus.RUNNING)

    async def test_numbering_and_parallel_requests(self):
        a, b = self.make_task(), self.make_task(assignee="writer")
        fa = asyncio.create_task(self.router.request_human(a, HitlKind.APPROVAL, "q1"))
        fb = asyncio.create_task(self.router.request_human(b, HitlKind.CLARIFY, "q2"))
        await asyncio.sleep(0.01)
        await self.answer(GROUP_MAIN, "h2", "二")
        self.assertEqual(await asyncio.wait_for(fb, 1), "二")
        self.assertFalse(fa.done())                      # h1 keeps waiting, others are not blocked
        await self.answer(GROUP_MAIN, "h1", "一")
        self.assertEqual(await asyncio.wait_for(fa, 1), "一")

    async def test_dm_session_has_its_own_numbers_and_stays_in_dm(self):
        dm = dm_channel("coder", "human")
        self.bus.join("human", dm)
        g, d = self.make_task(), self.make_task(origin=dm)
        fg = asyncio.create_task(self.router.request_human(g, HitlKind.ADVICE, "群里问"))
        fd = asyncio.create_task(self.router.request_human(d, HitlKind.ADVICE, "私聊问"))
        await asyncio.sleep(0.01)
        self.assertEqual([m.payload["request_id"] for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST], ["h1"])
        self.assertEqual([m.payload["request_id"] for m in self.bus.history(dm) if m.type == MsgType.HITL_REQUEST], ["h1"])
        await self.answer(dm, "h1", "私聊答")             # same id, other session: only the DM one wakes up
        self.assertEqual(await asyncio.wait_for(fd, 1), "私聊答")
        self.assertFalse(fg.done())
        fg.cancel()

    async def test_unknown_response_is_ignored(self):
        await self.answer(GROUP_MAIN, "h99", "x")

    async def test_cancel_releases_waiters(self):
        t = self.make_task()
        fut = asyncio.create_task(self.router.request_human(t, HitlKind.APPROVAL, "q"))
        await asyncio.sleep(0.01)
        self.router.cancel_root("R1")
        self.assertEqual(await asyncio.wait_for(fut, 1), "cancelled")
        self.assertEqual(t.status, TaskStatus.CANCELLED)   # stays cancelled, not set back to running


class CancelTest(RouterTestBase):
    async def test_cancel_releases_pending_dispatch(self):
        self.start_worker("coder")                       # never answers
        pending = asyncio.create_task(self.call())
        await asyncio.sleep(0.01)
        self.router.cancel_root("R1")
        r = await asyncio.wait_for(pending, 1)
        self.assertEqual((r.success, r.error), (False, "cancelled"))
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.CANCELLED)
        assign = self.assigns()[0]
        await self.bus.publish(result_msg("coder", assign, TaskResult(r.task_id, True, "late")))
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.CANCELLED)
        self.assertEqual(self.state.result(r.task_id).summary, "late")

    async def test_cancel_only_touches_its_root(self):
        self.start_worker("coder")
        p1 = asyncio.create_task(self.call(root="R1", goal="a"))
        p2 = asyncio.create_task(self.call(root="R2", goal="b"))
        await asyncio.sleep(0.01)
        self.router.cancel_root("R1")
        await asyncio.wait_for(p1, 1)
        self.assertFalse(p2.done())
        self.assertEqual([t.status for t in self.state.by_root("R2")], [TaskStatus.ASSIGNED])
        p2.cancel()


class DirectTaskAndBoardTest(RouterTestBase):
    async def test_open_direct_task_in_dm(self):
        dm = dm_channel("coder", "human")
        msg = Message(MsgType.CHAT, HUMAN, dm, "修一下这个 bug", receiver="coder")
        self.router.board(dm).on_message(msg)             # the bus observer saw it first
        task = self.router.open_direct_task(msg, "coder")
        self.assertEqual((task.assignee, task.requester, task.chain, task.origin_channel, task.session_id),
                         ("coder", HUMAN, [HUMAN], dm, dm))
        self.assertEqual(task.goal, "修一下这个 bug")
        self.assertIs(self.state.get(task.id), task)
        board = self.router.board(dm)
        self.assertEqual(board.roots[task.root_id].human_messages, ["修一下这个 bug"])
        self.assertIn("coder 执行中「修一下这个 bug」", board.render())

    async def test_open_direct_task_strips_mention(self):
        msg = Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "@coder 写个脚本", mentions=["coder"], receiver="coder")
        task = self.router.open_direct_task(msg, "coder")
        self.assertEqual(task.goal, "写个脚本")
        self.assertEqual(task.session_id, GROUP_MAIN)

    async def test_new_root_ids_are_per_session(self):
        r = self.router
        self.assertEqual([r.new_root_id("a"), r.new_root_id("a"), r.new_root_id("b")], ["R1", "R2", "R1"])

    async def test_session_and_board(self):
        r = self.router
        self.assertEqual(r.session_of(GROUP_MAIN), GROUP_MAIN)
        self.assertNotEqual(r.session_of(dm_channel("human", "coder")), r.session_of(GROUP_MAIN))
        self.assertIs(r.board(GROUP_MAIN), r.board(GROUP_MAIN))
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "你好"))   # reaches the board via the observer
        self.assertEqual(r.board(GROUP_MAIN)._pending_human, ["你好"])
        self.assertEqual(r.board(dm_channel("human", "coder"))._pending_human, [])


if __name__ == "__main__":
    unittest.main()
