"""Router behaviour (design §2.1, §5, §7)."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
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

    async def call(self, target="coder", goal="write a script", requester="orchestrator", parent=None,
                   root="R1", origin=GROUP_MAIN, **kw):
        return await self.router.dispatch(
            requester=requester, target=target, goal=goal, parent=parent, session_id=origin,
            root_id=root, origin_channel=origin, **kw)

    def assigns(self, channel=GROUP_MAIN):
        return [m for m in self.bus.history(channel, 100) if m.type == MsgType.TASK_ASSIGN]


class DispatchTest(RouterTestBase):
    async def test_success_flow(self):
        self.start_worker("coder", self.ok("script ready", artifacts=["a.py"]))
        r = await self.call()
        self.assertTrue(r.success)
        self.assertEqual(r.artifacts, ["a.py"])
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.DONE)
        [a] = self.assigns()
        self.assertEqual((a.sender, a.receiver, a.mentions, a.content),
                         ("orchestrator", "coder", ["coder"], "@coder write a script"))
        task = self.seen["coder"][0]
        self.assertEqual((task.chain, task.depth, task.requester), (["orchestrator"], 0, "orchestrator"))

    async def test_board_learns_task_and_result(self):
        self.start_worker("coder", self.ok("finished", artifacts=["a.py"]))
        self.router.board(GROUP_MAIN).start_root("R1", "write a script")
        await self.call()
        text = self.router.board(GROUP_MAIN).render()
        self.assertIn("coder \"write a script\" -> a.py", text)

    async def test_failure_and_decline_are_results_not_exceptions(self):
        async def fail(task): return TaskResult(task.id, False, "", error="boom", failure_mode=FailureMode.CRASH)
        async def decline(task): return TaskResult(task.id, False, "cannot", declined=True, suggest="coder")
        self.start_worker("coder", fail)
        self.start_worker("writer", decline)
        r1, r2 = await self.call("coder"), await self.call("writer", goal="run code")
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
        await self.bus.publish(result_msg("coder", assign, TaskResult(r.task_id, True, "too late")))
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.FAILED)

    async def test_timeout_does_not_run_while_waiting_for_a_human(self):
        self.router.settings.subtask_timeout_s = 0.05
        answered = asyncio.Event()

        async def asks(task):
            answer = await self.router.request_human(
                session_id=task.session_id, root_id=task.root_id, origin_channel=task.origin_channel,
                requester=task.assignee, kind=HitlKind.APPROVAL, question="push?", task_id=task.id)
            answered.set()
            return TaskResult(task.id, True, f"human said {answer}")
        self.start_worker("coder", asks)
        pending = asyncio.create_task(self.call())
        await asyncio.sleep(0.25)                          # five timeouts' worth
        self.assertFalse(pending.done())
        [t] = self.state.by_root("R1")
        self.assertEqual(t.status, TaskStatus.WAITING_HUMAN)
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN,
                                       payload={"request_id": "h1", "answer": "yes"}))
        r = await asyncio.wait_for(pending, 1)
        self.assertEqual((r.success, r.summary), (True, "human said yes"))
        self.assertEqual(t.status, TaskStatus.DONE)

    async def test_timeout_runs_again_after_the_human_answered(self):
        self.router.settings.subtask_timeout_s = 0.05

        async def asks_then_hangs(task):
            await self.router.request_human(
                session_id=task.session_id, root_id=task.root_id, origin_channel=task.origin_channel,
                requester=task.assignee, kind=HitlKind.APPROVAL, question="?", task_id=task.id)
            await asyncio.sleep(10)
        self.start_worker("coder", asks_then_hangs)
        pending = asyncio.create_task(self.call())
        await asyncio.sleep(0.12)
        await self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, GROUP_MAIN,
                                       payload={"request_id": "h1", "answer": "yes"}))
        r = await asyncio.wait_for(pending, 1)
        self.assertEqual(r.failure_mode, FailureMode.TIMEOUT)

    async def test_cancel_ends_a_wait_for_a_human(self):
        self.router.settings.subtask_timeout_s = 0.05

        async def asks(task):
            return TaskResult(task.id, True, str(await self.router.request_human(
                session_id=task.session_id, root_id=task.root_id, origin_channel=task.origin_channel,
                requester=task.assignee, kind=HitlKind.APPROVAL, question="?", task_id=task.id)))
        self.start_worker("coder", asks)
        pending = asyncio.create_task(self.call())
        await asyncio.sleep(0.12)
        self.router.cancel_root("R1")
        r = await asyncio.wait_for(pending, 1)
        self.assertEqual(r.error, "cancelled")

    async def test_status_messages_update_state(self):
        async def h(task):
            await self.bus.publish(Message(MsgType.STATUS, "coder", GROUP_MAIN, payload={
                "task_id": task.id, "status": "running", "note": "started", "public": False}))
            self.assertEqual(self.state.get(task.id).status, TaskStatus.RUNNING)
            return TaskResult(task.id, True, "ok")
        self.start_worker("coder", h)
        r = await self.call()
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.DONE)


class LimitTest(RouterTestBase):
    async def assertRefused(self, r, text, target=None):
        self.assertFalse(r.success)
        self.assertIn(text, r.error)
        self.assertTrue(r.error.startswith("refused:"))
        self.assertEqual(r.failure_mode, FailureMode.TOOL_ERROR)
        self.assertEqual(self.state.get(r.task_id).status, TaskStatus.FAILED)   # visible in /status
        self.assertEqual(self.state.result(r.task_id), r)
        if target:
            self.assertEqual(self.seen[target], [])      # the target was never contacted

    async def test_unknown_or_forbidden_target(self):
        self.start_worker("coder", self.ok())
        for t in ("nobody", "orchestrator", "human"):
            await self.assertRefused(await self.call(t), "unknown agent")
        self.assertEqual([t.assignee for t in self.state.by_root("R1")], ["nobody", "orchestrator", "human"])
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.FAILED] * 3)
        self.assertEqual(self.assigns(), [])             # nothing was sent to anyone

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
        self.assertEqual((await self.call(goal="another goal")).error, "x")   # different goal is fine
        self.assertEqual((await self.call(root="R2")).error, "x")           # other root is fine

    async def test_declined_does_not_use_up_retries(self):
        async def decline(task): return TaskResult(task.id, False, "no", declined=True)
        self.start_worker("writer", decline)
        for _ in range(5):
            self.assertTrue((await self.call("writer")).declined)

    async def test_refusals_do_not_use_up_retries_or_delegations(self):
        self.start_worker("coder", self.ok())
        for _ in range(5):                                # refused again and again, e.g. a bad file
            await self.assertRefused(await self.call(files=["nope.md"]), "file not found")
        self.assertTrue((await self.call()).success)      # the same goal still gets all its tries
        parent = Task(goal="x", assignee="writer", requester="orchestrator", session_id=GROUP_MAIN,
                      root_id="R1", origin_channel=GROUP_MAIN, chain=["orchestrator"])
        self.settings.max_delegations_per_task = 1
        for _ in range(3):
            await self.assertRefused(await self.call("nobody", requester="writer", parent=parent), "unknown agent")
        self.assertTrue((await self.call("coder", goal="another", requester="writer", parent=parent)).success)

    async def test_refused_task_is_linked_to_its_parent_and_chain(self):
        parent = Task(goal="x", assignee="coder", requester="orchestrator", session_id=GROUP_MAIN,
                      root_id="R1", origin_channel=GROUP_MAIN, chain=["orchestrator"])
        r = await self.call("coder", requester="coder", parent=parent)       # a cycle
        t = self.state.get(r.task_id)
        self.assertEqual((t.parent_id, t.chain, t.requester, t.assignee),
                         (parent.id, ["orchestrator", "coder"], "coder", "coder"))

    async def test_cancelled_root_refuses_new_calls(self):
        self.start_worker("coder", self.ok())
        self.router.cancel_root("R1")
        await self.assertRefused(await self.call(), "cancelled", "coder")
        self.assertTrue((await self.call(root="R2")).success)
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.FAILED])


class FilesTest(RouterTestBase):
    async def test_copies_from_producer_of_the_artifact(self):
        self.sandboxes["researcher"].write_text("notes.md", "key points")
        self.start_worker("researcher", self.ok(artifacts=["notes.md"]))
        self.start_worker("coder", self.ok())
        await self.call("researcher", goal="research")
        r = await self.call("coder", goal="write a script", files=["notes.md"])
        self.assertTrue(r.success)
        self.assertEqual((self.tmp / "coder" / "inbox" / "notes.md").read_text(), "key points")
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
        self.assertEqual([t.status for t in self.state.by_root("R1")], [TaskStatus.FAILED] * 2)


class HitlTest(RouterTestBase):
    def make_task(self, origin=GROUP_MAIN, assignee="coder") -> Task:
        t = Task(goal="push", assignee=assignee, requester="orchestrator", session_id=origin,
                 root_id="R1", origin_channel=origin)
        self.state.register(t)
        return t

    def ask(self, task, kind, question, options=None):
        """What Agent.ask_human does: fill the arguments from the task."""
        return self.router.request_human(
            session_id=task.session_id, root_id=task.root_id, origin_channel=task.origin_channel,
            requester=task.assignee, kind=kind, question=question, options=options, task_id=task.id)

    def answer(self, channel, request_id, text):
        return self.bus.publish(Message(MsgType.HITL_RESPONSE, HUMAN, channel,
                                        payload={"request_id": request_id, "answer": text}))

    async def test_request_and_answer(self):
        t = self.make_task()
        fut = asyncio.create_task(self.ask(t, HitlKind.APPROVAL, "git push?", ["yes", "no"]))
        await asyncio.sleep(0.01)
        [req] = [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST]
        self.assertEqual(req.payload, {"request_id": "h1", "task_id": t.id, "root_id": "R1", "kind": "approval",
                                       "question": "git push?", "options": ["yes", "no"]})
        self.assertEqual((req.sender, req.receiver, req.content), ("coder", HUMAN, "@human git push? [yes / no]"))
        self.assertEqual(t.status, TaskStatus.WAITING_HUMAN)
        self.assertFalse(fut.done())
        await self.answer(GROUP_MAIN, "h1", "yes")
        self.assertEqual(await asyncio.wait_for(fut, 1), "yes")
        self.assertEqual(t.status, TaskStatus.RUNNING)

    async def test_numbering_and_parallel_requests(self):
        a, b = self.make_task(), self.make_task(assignee="writer")
        fa = asyncio.create_task(self.ask(a, HitlKind.APPROVAL, "q1"))
        fb = asyncio.create_task(self.ask(b, HitlKind.CLARIFY, "q2"))
        await asyncio.sleep(0.01)
        await self.answer(GROUP_MAIN, "h2", "two")
        self.assertEqual(await asyncio.wait_for(fb, 1), "two")
        self.assertFalse(fa.done())                      # h1 keeps waiting, others are not blocked
        await self.answer(GROUP_MAIN, "h1", "one")
        self.assertEqual(await asyncio.wait_for(fa, 1), "one")

    async def test_dm_session_has_its_own_numbers_and_stays_in_dm(self):
        dm = dm_channel("coder", "human")
        self.bus.join("human", dm)
        g, d = self.make_task(), self.make_task(origin=dm)
        fg = asyncio.create_task(self.ask(g, HitlKind.ADVICE, "asked in the group"))
        fd = asyncio.create_task(self.ask(d, HitlKind.ADVICE, "asked in the DM"))
        await asyncio.sleep(0.01)
        self.assertEqual([m.payload["request_id"] for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST], ["h1"])
        self.assertEqual([m.payload["request_id"] for m in self.bus.history(dm) if m.type == MsgType.HITL_REQUEST], ["h1"])
        await self.answer(dm, "h1", "DM answer")             # same id, other session: only the DM one wakes up
        self.assertEqual(await asyncio.wait_for(fd, 1), "DM answer")
        self.assertFalse(fg.done())
        fg.cancel()

    async def test_unknown_response_is_ignored(self):
        await self.answer(GROUP_MAIN, "h99", "x")

    async def test_cancel_releases_waiters(self):
        t = self.make_task()
        fut = asyncio.create_task(self.ask(t, HitlKind.APPROVAL, "q"))
        await asyncio.sleep(0.01)
        self.router.cancel_root("R1")
        self.assertEqual(await asyncio.wait_for(fut, 1), CANCELLED_ANSWER)
        self.assertEqual(t.status, TaskStatus.CANCELLED)   # stays cancelled, not set back to running

    async def test_orchestrator_clarification_has_no_task(self):
        self.router.board(GROUP_MAIN).start_root("R1", "write a script")   # the Orchestrator opens the root first
        fut = asyncio.create_task(self.router.request_human(
            session_id=GROUP_MAIN, root_id="R1", origin_channel=GROUP_MAIN, requester="orchestrator",
            kind=HitlKind.CLARIFY, question="which version do you want?", options=["3.10", "3.11"]))
        await asyncio.sleep(0.01)
        [req] = [m for m in self.bus.history(GROUP_MAIN) if m.type == MsgType.HITL_REQUEST]
        self.assertEqual((req.sender, req.payload["task_id"], req.payload["root_id"]), ("orchestrator", None, "R1"))
        self.assertEqual(self.state.by_root("R1"), [])        # no fake task in the table
        self.assertIn("h1", self.router.board(GROUP_MAIN).render())   # but the board shows it
        await self.answer(GROUP_MAIN, "h1", "3.11")
        self.assertEqual(await asyncio.wait_for(fut, 1), "3.11")

    async def test_cancel_releases_orchestrator_clarification(self):
        fut = asyncio.create_task(self.router.request_human(
            session_id=GROUP_MAIN, root_id="R1", origin_channel=GROUP_MAIN, requester="orchestrator",
            kind=HitlKind.CLARIFY, question="?"))
        other = asyncio.create_task(self.router.request_human(
            session_id=GROUP_MAIN, root_id="R2", origin_channel=GROUP_MAIN, requester="orchestrator",
            kind=HitlKind.CLARIFY, question="?"))
        await asyncio.sleep(0.01)
        self.router.cancel_root("R1")
        self.assertEqual(await asyncio.wait_for(fut, 1), CANCELLED_ANSWER)
        self.assertFalse(other.done())                        # another root is untouched
        other.cancel()


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


class CancelSessionTest(RouterTestBase):
    def task(self, session, root, assignee="coder", status=TaskStatus.RUNNING):
        t = Task(goal="g" + root, assignee=assignee, requester="human", session_id=session, root_id=root,
                 origin_channel=session)
        self.state.register(t)
        self.state.update(t.id, status)
        return t

    async def test_cancels_every_unfinished_root_of_the_session_only(self):
        dm, other = dm_channel("human", "coder"), dm_channel("human", "writer")
        a, b = self.task(dm, "R1"), self.task(dm, "R2")
        done = self.task(dm, "R3", status=TaskStatus.DONE)
        mine_elsewhere = self.task(other, "R9")      # root ids are unique across sessions
        self.assertEqual(self.router.cancel_session(dm), ["R1", "R2"])
        self.assertEqual([t.status for t in (a, b, done, mine_elsewhere)],
                         [TaskStatus.CANCELLED, TaskStatus.CANCELLED, TaskStatus.DONE, TaskStatus.RUNNING])
        self.assertEqual(self.router.cancel_session(dm), [])      # nothing left to cancel

    async def test_a_root_with_several_tasks_is_listed_once(self):
        dm = dm_channel("human", "coder")
        self.task(dm, "R1"), self.task(dm, "R1", assignee="researcher")
        self.assertEqual(self.router.cancel_session(dm), ["R1"])


class DirectTaskAndBoardTest(RouterTestBase):
    async def test_open_direct_task_in_dm(self):
        dm = dm_channel("coder", "human")
        msg = Message(MsgType.CHAT, HUMAN, dm, "fix this bug", receiver="coder")
        self.router.board(dm).on_message(msg)             # the bus observer saw it first
        task = self.router.open_direct_task(msg, "coder")
        self.assertEqual((task.assignee, task.requester, task.chain, task.origin_channel, task.session_id),
                         ("coder", HUMAN, [HUMAN], dm, dm))
        self.assertEqual(task.goal, "fix this bug")
        self.assertIs(self.state.get(task.id), task)
        board = self.router.board(dm)
        self.assertEqual(board.roots[task.root_id].human_messages, ["fix this bug"])
        self.assertIn("coder running \"fix this bug\"", board.render())

    async def test_open_direct_task_strips_mention(self):
        msg = Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "@coder write a script", mentions=["coder"], receiver="coder")
        task = self.router.open_direct_task(msg, "coder")
        self.assertEqual(task.goal, "write a script")
        self.assertEqual(task.session_id, GROUP_MAIN)

    async def test_root_ids_are_unique_across_sessions(self):
        r = self.router
        self.assertEqual([r.new_root_id("a"), r.new_root_id("a"), r.new_root_id("b")], ["R1", "R2", "R3"])

    async def test_cancelling_a_root_does_not_touch_other_sessions(self):
        r = self.router
        dm = dm_channel(HUMAN, "coder")
        group = Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "@coder write a script", receiver="coder")
        private = Message(MsgType.CHAT, HUMAN, dm, "fix a bug", receiver="coder")
        t1, t2 = r.open_direct_task(group, "coder"), r.open_direct_task(private, "coder")
        self.assertNotEqual(t1.root_id, t2.root_id)
        r.cancel_root(t1.root_id)
        self.assertEqual((t1.status, t2.status), (TaskStatus.CANCELLED, TaskStatus.ASSIGNED))

    async def test_session_and_board(self):
        r = self.router
        self.assertEqual(r.session_of(GROUP_MAIN), GROUP_MAIN)
        self.assertNotEqual(r.session_of(dm_channel("human", "coder")), r.session_of(GROUP_MAIN))
        self.assertIs(r.board(GROUP_MAIN), r.board(GROUP_MAIN))
        await self.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, "hello"))   # reaches the board via the observer
        self.assertEqual(r.board(GROUP_MAIN)._pending_human, ["hello"])
        self.assertEqual(r.board(dm_channel("human", "coder"))._pending_human, [])


if __name__ == "__main__":
    unittest.main()
