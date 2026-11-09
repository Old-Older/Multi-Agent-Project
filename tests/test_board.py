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
        self.assertIn("暂无内容", SessionBoard("s3").render())

    def test_human_message_is_adopted_not_duplicated(self):
        b = SessionBoard("s3")
        b.on_message(human("调研 X"))            # the bus observer sees it first
        b.start_root("R1", "调研 X")
        self.assertEqual(b.roots["R1"].human_messages, ["调研 X"])

    def test_interjection_and_slash_commands(self):
        b = SessionBoard("s3")
        b.start_root("R1", "调研 X")
        b.on_message(human("脚本用 Python 3.11"))
        b.on_message(human("/status"))
        self.assertEqual(b.roots["R1"].human_messages, ["调研 X", "脚本用 Python 3.11"])
        self.assertIn('（插话）"脚本用 Python 3.11"', b.render())

    def test_agent_chat_is_ignored(self):
        b = SessionBoard("s3")
        b.start_root("R1", "x")
        b.on_message(Message(MsgType.CHAT, "coder", GROUP_MAIN, "我来做"))
        self.assertEqual(b.roots["R1"].human_messages, ["x"])

    def test_full_flow_render(self):
        b = SessionBoard("s3")
        b.start_root("R1", "调研 X 并写示例脚本")
        t1, t2, t3 = mk("调研 X 的用法", "researcher"), mk("写文档", "writer"), mk("写示例脚本并推送", "coder")
        for t in (t1, t2, t3):
            b.on_message(assign(t))
        b.on_message(result(TaskResult(
            t1.id, True, "认证用 token，速率 60 次/分钟", artifacts=["notes.md"],
            refs={"url": "https://x"}, open_issues=["未处理限流"])))
        b.on_message(result(TaskResult(
            t2.id, False, "需要运行代码", declined=True, suggest="coder", error="需要运行代码。其他")))
        b.on_message(Message(MsgType.HITL_REQUEST, "router", GROUP_MAIN, payload={
            "request_id": "h1", "task_id": t3.id, "kind": "approval",
            "question": "确认 git push？", "options": []}))
        b.set_plan("R1", "t3 完成后汇总")
        text = b.render()
        for needle in (f"{t1.id} researcher「调研 X 的用法」→ notes.md", "url=https://x",
                       "要点：认证用 token", f"{t2.id} writer 拒绝：需要运行代码，建议 coder",
                       f"{t3.id} coder 执行中", "h1 等待人类：确认 git push？",
                       f"遗留（{t1.id}）：未处理限流", "剩余计划：t3 完成后汇总"):
            self.assertIn(needle, text)
        b.on_message(Message(MsgType.HITL_RESPONSE, "human", GROUP_MAIN,
                             payload={"request_id": "h1", "answer": "yes"}))
        text = b.render()
        self.assertIn("h1「确认 git push？」→ yes", text)
        self.assertNotIn("等待人类", text)

    def test_failed_task_listed(self):
        b = SessionBoard("s3")
        b.start_root("R1", "x")
        t = mk("跑测试", "coder")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, False, "", error="timeout")))
        self.assertIn(f"{t.id} coder 失败：timeout", b.render())

    def test_earlier_roots_become_one_line(self):
        b = SessionBoard("s3")
        b.start_root("R1", "整理会议纪要")
        b.finish_root("R1", "已归纳 5 项决议。还有细节", ["minutes.md", "todo.md"])
        b.on_message(human("把纪要翻译成英文"))
        b.start_root("R2", "把纪要翻译成英文")
        text = b.render()
        self.assertIn("根任务 R2", text)
        self.assertIn("R1 已归纳 5 项决议 → minutes.md, todo.md", text)
        self.assertNotIn("还有细节", text)

    def test_cancelled_root_falls_back_to_human_text(self):
        b = SessionBoard("s3")
        b.start_root("R1", "整理会议纪要" * 20)
        b.roots["R1"].finished = True
        b.start_root("R2", "新任务")
        self.assertIn("R1 " + ("整理会议纪要" * 20)[:40], b.render())
        self.assertNotIn(("整理会议纪要" * 20)[:41], b.render())

    def test_compression_keeps_protected_info(self):
        b = SessionBoard("s3", max_chars=700)
        for i in range(6):
            b.start_root(f"R{i}", f"早先任务 {i}")
            b.finish_root(f"R{i}", f"做完了第 {i} 件事" + "细节" * 30, [f"out{i}.md"])
        b.start_root("R9", "当前任务原话")
        t = mk("写脚本", "coder", root="R9")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, True, "很长的摘要" * 100, artifacts=["a.py"],
                                       open_issues=["要补测试"])))
        text = b.render()
        self.assertLessEqual(len(text), 700)
        self.assertIn("另有", text)
        self.assertIn("当前任务原话", text)
        self.assertIn(t.id, text)
        self.assertIn("a.py", text)
        self.assertIn("要补测试", text)

    def test_summary_truncation_when_still_too_long(self):
        b = SessionBoard("s3", max_chars=300)
        b.start_root("R1", "x")
        t = mk("写脚本", "coder")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, True, "很长的摘要" * 200, artifacts=["a.py"])))
        text = b.render()
        self.assertLessEqual(len(text), 300)
        self.assertIn("a.py", text)

    def test_direct_task_opens_root_from_pending_human(self):
        b = SessionBoard("s3")
        b.on_message(human("帮我写个脚本"))
        b.on_message(assign(mk("写脚本", "coder", root="R7")))
        self.assertEqual(b.roots["R7"].human_messages, ["帮我写个脚本"])

    def test_save_load_roundtrip(self):
        b = SessionBoard("s3")
        b.start_root("R1", "调研 X")
        t = mk("调研", "researcher")
        b.on_message(assign(t))
        b.on_message(result(TaskResult(t.id, True, "ok", artifacts=["n.md"], refs={"k": "v"})))
        b.set_plan("R1", "汇总")
        b.on_message(human("pending later"))   # R1 unfinished -> interjection
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sessions" / "s3" / "board.json"
            b.save(path)
            loaded = SessionBoard.load(path)
        self.assertEqual(loaded.render(), b.render())
        self.assertEqual(loaded.max_chars, b.max_chars)


if __name__ == "__main__":
    unittest.main()
