"""SessionBoard behaviour (design §3.1, D17)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mas.core.board import SessionBoard
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.task import Task, TaskResult


def human(text: str) -> Message:
    return Message(MsgType.CHAT, HUMAN, GROUP_MAIN, text)


def assign(task: Task) -> Message:
    return Message(MsgType.TASK_ASSIGN, "orchestrator", GROUP_MAIN,
                   payload={"task": task.to_dict()}, receiver=task.assignee)


def result(r: TaskResult) -> Message:
    return Message(MsgType.TASK_RESULT, "x", GROUP_MAIN, payload={"result": r.to_dict()})


def mk(goal, assignee, root="R1") -> Task:
    return Task(goal=goal, assignee=assignee, requester="orchestrator",
                session_id="s3", root_id=root, origin_channel=GROUP_MAIN)


class BoardTest(unittest.TestCase):
    def test_empty(self):
        self.assertIn("nothing yet", SessionBoard("s3").render())

    def test_human_message_is_adopted_not_duplicated(self):
        b = SessionBoard("s3")
        b.on_message(human("research X"))            # the bus observer sees it first
        b.start_root("R1", "research X")
        self.assertEqual(b.roots["R1"].human_messages, ["research X"])

    def test_interjection_and_slash_commands(self):
        b = SessionBoard("s3")
        b.start_root("R1", "research X")
        b.on_message(human("use Python 3.11 for the script"))
        b.on_message(human("/status"))
        self.assertEqual(b.roots["R1"].human_messages, ["research X", "use Python 3.11 for the script"])
        self.assertIn('(interjection) "use Python 3.11 for the script"', b.render())

    def test_agent_chat_is_ignored(self):
        b = SessionBoard("s3")
        b.start_root("R1", "x")
        b.on_message(Message(MsgType.CHAT, "coder", GROUP_MAIN, "I'll do it"))
        self.assertEqual(b.roots["R1"].human_messages, ["x"])

    def test_full_flow_render(self):
        b = SessionBoard("s3")
        b.start_root("R1", "research X and write an example script")
        t1, t2, t3 = mk("research how to use X", "researcher"), mk("write the docs", "writer"), mk("write an example script and push it", "coder")
        for t in (t1, t2, t3):
            b.on_message(assign(t))
        b.on_message(result(TaskResult(
            t1.id, True, "auth uses a token, rate limit 60 calls/minute", artifacts=["notes.md"],
            refs={"url": "https://x"}, open_issues=["rate limiting not handled"])))
        b.on_message(result(TaskResult(
            t2.id, False, "needs to run code", declined=True, suggest="coder", error="Needs to run code. Other")))
        b.on_message(Message(MsgType.HITL_REQUEST, "router", GROUP_MAIN, payload={
            "request_id": "h1", "task_id": t3.id, "kind": "approval",
            "question": "confirm git push?", "options": []}))
        b.set_plan("R1", "summarize after t3 is done")
        text = b.render()
        for needle in (f"{t1.id} researcher \"research how to use X\" -> notes.md", "url=https://x",
                       "key points: auth uses a token", f"{t2.id} writer declined: Needs to run code, suggest coder",
                       f"{t3.id} coder running", "h1 waiting for the human: confirm git push?",
                       f"left over ({t1.id}): rate limiting not handled", "remaining plan: summarize after t3 is done"):
            self.assertIn(needle, text)
        b.on_message(Message(MsgType.HITL_RESPONSE, "human", GROUP_MAIN,
                             payload={"request_id": "h1", "answer": "yes"}))
        text = b.render()
        self.assertIn("h1 \"confirm git push?\" -> yes", text)
        self.assertNotIn("waiting for the human", text)

    def test_failed_task_listed(self):
        b = SessionBoard("s3")
        b.start_root("R1", "x")
        t = mk("run the tests", "coder")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, False, "", error="timeout")))
        self.assertIn(f"{t.id} coder failed: timeout", b.render())

    def test_earlier_roots_become_one_line(self):
        b = SessionBoard("s3")
        b.start_root("R1", "summarize the meeting minutes")
        b.finish_root("R1", "Summarized 5 decisions. More details", ["minutes.md", "todo.md"])
        b.on_message(human("translate the minutes into English"))
        b.start_root("R2", "translate the minutes into English")
        text = b.render()
        self.assertIn("root R2", text)
        self.assertIn("R1 Summarized 5 decisions -> minutes.md, todo.md", text)
        self.assertNotIn("More details", text)

    def test_cancelled_root_falls_back_to_human_text(self):
        b = SessionBoard("s3")
        b.start_root("R1", "summarize the meeting minutes" * 20)
        b.roots["R1"].finished = True
        b.start_root("R2", "new task")
        self.assertIn("R1 " + ("summarize the meeting minutes" * 20)[:40], b.render())
        self.assertNotIn(("summarize the meeting minutes" * 20)[:41], b.render())

    def test_compression_keeps_protected_info(self):
        b = SessionBoard("s3", max_chars=700)
        for i in range(6):
            b.start_root(f"R{i}", f"earlier task {i}")
            b.finish_root(f"R{i}", f"did thing {i}" + "details" * 30, [f"out{i}.md"])
        b.start_root("R9", "current task wording")
        t = mk("write a script", "coder", root="R9")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, True, "a very long summary" * 100, artifacts=["a.py"],
                                       open_issues=["tests still to add"])))
        text = b.render()
        self.assertLessEqual(len(text), 700)
        self.assertIn("more earlier", text)
        self.assertIn("current task wording", text)
        self.assertIn(t.id, text)
        self.assertIn("a.py", text)
        self.assertIn("tests still to add", text)

    def test_summary_truncation_when_still_too_long(self):
        b = SessionBoard("s3", max_chars=300)
        b.start_root("R1", "x")
        t = mk("write a script", "coder")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, True, "a very long summary" * 200, artifacts=["a.py"])))
        text = b.render()
        self.assertLessEqual(len(text), 300)
        self.assertIn("a.py", text)

    def test_direct_task_opens_root_from_pending_human(self):
        b = SessionBoard("s3")
        b.on_message(human("help me write a script"))
        b.on_message(assign(mk("write a script", "coder", root="R7")))
        self.assertEqual(b.roots["R7"].human_messages, ["help me write a script"])

    def test_save_load_roundtrip(self):
        b = SessionBoard("s3")
        b.start_root("R1", "research X")
        t = mk("research", "researcher")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, True, "ok", artifacts=["n.md"], refs={"k": "v"})))
        b.set_plan("R1", "summarize")
        b.on_message(human("pending later"))   # R1 unfinished -> interjection
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sessions" / "s3" / "board.json"
            b.save(path)
            loaded = SessionBoard.load(path)
        self.assertEqual(loaded.render(), b.render())
        self.assertEqual(loaded.max_chars, b.max_chars)


if __name__ == "__main__":
    unittest.main()
