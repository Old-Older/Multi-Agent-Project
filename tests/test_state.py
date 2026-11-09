"""StateTable behaviour (design §4)."""
from __future__ import annotations

import unittest

from mas.core.message import GROUP_MAIN
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus


def mk(goal="写脚本", assignee="coder", session="s1", root="r1") -> Task:
    return Task(goal=goal, assignee=assignee, requester="orchestrator",
                session_id=session, root_id=root, origin_channel=GROUP_MAIN)


class StateTableTest(unittest.TestCase):
    def test_register_get_and_duplicate(self):
        st, t = StateTable(), mk()
        st.register(t)
        self.assertIs(st.get(t.id), t)
        with self.assertRaises(ValueError):
            st.register(t)
        with self.assertRaises(KeyError):
            st.get("nope")

    def test_update_status(self):
        st, t = StateTable(), mk()
        st.register(t)
        st.update(t.id, TaskStatus.RUNNING, "开始")
        self.assertEqual(st.get(t.id).status, TaskStatus.RUNNING)
        self.assertEqual(st.active("s1"), [t])

    def test_finish_sets_final_status(self):
        st = StateTable()
        a, b, c = mk(), mk(), mk()
        for t in (a, b, c):
            st.register(t)
        st.finish(TaskResult(a.id, True, "ok"))
        st.finish(TaskResult(b.id, False, "x", error="boom", failure_mode=FailureMode.CRASH))
        st.finish(TaskResult(c.id, False, "不会", declined=True, suggest="writer"))
        self.assertEqual([t.status for t in (a, b, c)],
                         [TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.DECLINED])
        self.assertEqual(st.result(a.id).summary, "ok")
        self.assertIsNone(st.result("nope"))
        self.assertEqual(st.active("s1"), [])

    def test_cancelled_survives_late_result(self):
        st, t = StateTable(), mk()
        st.register(t)
        st.update(t.id, TaskStatus.CANCELLED)
        st.finish(TaskResult(t.id, True, "late"))
        self.assertEqual(t.status, TaskStatus.CANCELLED)
        self.assertIsNotNone(st.result(t.id))

    def test_by_root_and_active_are_scoped(self):
        st = StateTable()
        a, b, c = mk(root="r1"), mk(root="r2"), mk(session="s2", root="r3")
        for t in (a, b, c):
            st.register(t)
        self.assertEqual(st.by_root("r1"), [a])
        self.assertEqual(st.active("s1"), [a, b])
        self.assertEqual(st.active("s2"), [c])

    def test_status_text(self):
        st = StateTable()
        self.assertIn("没有任务", st.status_text("s1"))
        a, b = mk(goal="调研"), mk(goal="写脚本")
        st.register(a)
        st.register(b)
        st.update(b.id, TaskStatus.WAITING_HUMAN, "等待确认 git push")
        text = st.status_text("s1")
        self.assertIn(a.id, text)
        self.assertIn("waiting_human", text)
        self.assertIn("等待确认 git push", text)
        self.assertIn("进行中 2 个", text)


class StatusTextTest(unittest.TestCase):
    def table(self):
        st = StateTable()
        self.tasks = {}
        for name, root, status in [("a", "R1", TaskStatus.DONE), ("b", "R1", TaskStatus.DONE),
                                   ("c", "R2", TaskStatus.DONE), ("d", "R2", TaskStatus.FAILED),
                                   ("e", "R2", TaskStatus.DECLINED), ("f", "R3", TaskStatus.RUNNING),
                                   ("g", "R3", TaskStatus.DONE)]:
            t = mk(goal=f"目标{name}", root=root)
            st.register(t)
            st.update(t.id, status)
            self.tasks[name] = t
        return st

    def test_current_root_in_detail_earlier_roots_one_line_each(self):
        text = self.table().status_text("s1")
        lines = text.split("\n")
        self.assertEqual(lines[0], "R3：任务 2 个，进行中 1 个：")
        self.assertIn(f"{self.tasks['f'].id} coder [running]「目标f」", lines[1])
        self.assertIn(f"{self.tasks['g'].id} coder [done]「目标g」", lines[2])
        self.assertEqual(lines[3:], ["更早的请求：", "  R1：2 个任务，全部完成", "  R2：3 个任务，完成 1、失败 1、拒绝 1"])
        for name in "abcde":                              # earlier tasks are not listed one by one
            self.assertNotIn(self.tasks[name].id, text)

    def test_the_answer_does_not_grow_with_finished_requests(self):
        st = StateTable()
        for i in range(1, 31):
            t = mk(root=f"R{i}")
            st.register(t)
            st.finish(TaskResult(t.id, True, "ok"))
        text = st.status_text("s1")
        self.assertLess(len(text.split("\n")), 35)
        self.assertEqual(text.split("\n")[0], "R30：任务 1 个，进行中 0 个：")     # nothing running: the latest root

    def test_a_finished_latest_root_gives_way_to_an_older_running_one(self):
        st = StateTable()
        old, new = mk(root="R1"), mk(root="R2")
        st.register(old), st.register(new)
        st.update(old.id, TaskStatus.RUNNING)
        st.finish(TaskResult(new.id, True, "ok"))
        self.assertTrue(st.status_text("s1").startswith("R1：任务 1 个，进行中 1 个："))

    def test_other_sessions_are_not_mixed_in(self):
        st = StateTable()
        st.register(mk(session="s1", root="R1")), st.register(mk(session="s2", root="R2"))
        self.assertNotIn("R2", st.status_text("s1"))


if __name__ == "__main__":
    unittest.main()
