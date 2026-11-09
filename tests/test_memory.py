"""JsonlMemory: add, recall, profile (design §8, D13, D5)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.agents.orchestrator import Orchestrator
from mas.agents.roles import ROLES
from mas.config import Settings
from mas.core.bus import InMemoryBus
from mas.core.message import GROUP_MAIN
from mas.core.router import Router
from mas.core.state import StateTable
from mas.llm.mock import MockLLM
from mas.memory.base import (PROFILE_WINDOW, Experience, JsonlMemory, keywords, tags_for_tools)


def exp(task_id, goal="write a script", tags=("code",), success=True, summary="done", lesson="", ts=0.0):
    return Experience(task_id, goal, list(tags), success, summary, lesson, ts)


class MemoryTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.mem = JsonlMemory.for_agent(self.tmp / "memory", "coder")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class StorageTest(MemoryTestBase):
    def test_one_json_line_per_experience_in_the_agents_file(self):
        self.mem.add(exp("t1", lesson="先装依赖"))
        self.mem.add(exp("t2", success=False))
        self.assertEqual(self.mem.path, self.tmp / "memory" / "coder.jsonl")
        lines = self.mem.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l)["task_id"] for l in lines], ["t1", "t2"])
        self.assertIn("先装依赖", lines[0])                       # readable, not \u escaped

    def test_roundtrip_keeps_every_field(self):
        e = Experience("t1", "write a script", ["code", "git"], False, "summary", "lesson", 123.5)
        self.mem.add(e)
        self.assertEqual(JsonlMemory(self.mem.path).all(), [e])         # a fresh object reads the file

    def test_empty_or_missing_file(self):
        self.assertEqual((self.mem.all(), self.mem.recall("anything"), self.mem.profile()), ([], [], ""))

    def test_a_bad_line_is_skipped_not_fatal(self):
        self.mem.add(exp("t1"))
        with self.mem.path.open("a", encoding="utf-8") as f:
            f.write("not json\n{\"task_id\": \"x\"}\n\n")                # garbage, wrong fields, blank line
        self.mem.add(exp("t2"))
        with self.assertLogs("mas.memory.base", level="WARNING") as logs:
            ids = [e.task_id for e in self.mem.all()]
        self.assertEqual(ids, ["t1", "t2"])
        self.assertEqual(len(logs.records), 2)

    def test_the_later_line_of_a_task_wins_and_counts_as_newest(self):
        """A worker may record the failure first and add the lesson after the reflection."""
        self.mem.add(exp("t1", success=False))
        self.mem.add(exp("t2"))
        self.mem.add(exp("t1", success=False, lesson="check the proxy first"))
        got = self.mem.all()
        self.assertEqual([(e.task_id, e.lesson) for e in got], [("t2", ""), ("t1", "check the proxy first")])

    def test_clear_forgets_everything_and_the_memory_keeps_working(self):
        self.mem.add(exp("t1", success=False, lesson="a lesson"))
        self.mem.clear()
        self.assertEqual((self.mem.all(), self.mem.recall("script"), self.mem.profile(), self.mem.path.exists()),
                         ([], [], "", False))
        self.mem.clear()                                               # nothing to clear: not an error
        self.mem.add(exp("t2"))
        self.assertEqual([e.task_id for e in self.mem.all()], ["t2"])

    def test_clear_only_touches_its_own_agent(self):
        other = JsonlMemory.for_agent(self.tmp / "memory", "writer")
        self.mem.add(exp("t1")), other.add(exp("t2"))
        self.mem.clear()
        self.assertEqual([e.task_id for e in other.all()], ["t2"])

    def test_memory_of_two_agents_is_separate(self):
        other = JsonlMemory.for_agent(self.tmp / "memory", "writer")
        self.mem.add(exp("t1"))
        self.assertEqual(other.all(), [])


class KeywordsTest(unittest.TestCase):
    def test_ascii_words_are_lowercased_and_stop_words_dropped(self):
        self.assertEqual(keywords("Write the Script, please! run_python v2"), {"write", "script", "run_python", "v2"})

    def test_chinese_text_gives_character_pairs(self):
        self.assertEqual(keywords("写脚本"), {"写脚", "脚本"})
        self.assertEqual(keywords("写"), set())                                       # one character is too common
        self.assertEqual(keywords("用 Python 写脚本"), {"python", "写脚", "脚本"})

    def test_nothing_to_match(self):
        self.assertEqual(keywords("   ... "), set())


class RecallTest(MemoryTestBase):
    def test_most_overlapping_first_and_at_most_k(self):
        self.mem.add(exp("t1", goal="write a script that scrapes a web page"))      # web, page
        self.mem.add(exp("t2", goal="write the docs"))                              # nothing in common
        self.mem.add(exp("t3", goal="scrape a web page with javascript rendering"))  # scrape, web, page
        self.assertEqual([e.task_id for e in self.mem.recall("scrape a web page", k=5)], ["t3", "t1"])
        self.assertEqual([e.task_id for e in self.mem.recall("scrape a web page", k=1)], ["t3"])

    def test_no_shared_keyword_means_nothing_is_recalled(self):
        self.mem.add(exp("t1", goal="write the docs", tags=("doc",), summary="ok"))
        self.assertEqual(self.mem.recall("run the tests"), [])
        self.assertEqual(self.mem.recall(""), [])
        self.assertEqual(self.mem.recall("write", k=0), [])

    def test_case_and_punctuation_do_not_matter(self):
        self.mem.add(exp("t1", goal="Push to GitHub"))
        self.assertEqual([e.task_id for e in self.mem.recall("push, to github!")], ["t1"])

    def test_goal_and_tags_count_more_than_summary_and_lesson(self):
        self.mem.add(exp("in-goal", goal="deploy the site", tags=("file",), summary="ok", success=True))
        self.mem.add(exp("in-summary", goal="unrelated", tags=("file",), summary="mentions deploy", success=True))   # newer
        self.assertEqual([e.task_id for e in self.mem.recall("deploy")], ["in-goal", "in-summary"])

    def test_the_lesson_is_searched_too(self):
        self.mem.add(exp("t1", goal="install things", success=False, lesson="the proxy blocks pypi"))
        self.assertEqual([e.task_id for e in self.mem.recall("pypi")], ["t1"])

    def test_a_lesson_is_worth_a_point_and_ties_go_to_the_newer_one(self):
        self.mem.add(exp("old-no-lesson", goal="write a script"))
        self.mem.add(exp("lesson", goal="write a script", success=False, lesson="use utf-8"))
        self.mem.add(exp("newer-no-lesson", goal="write a script"))
        self.assertEqual([e.task_id for e in self.mem.recall("write a script", k=3)],
                         ["lesson", "newer-no-lesson", "old-no-lesson"])

    def test_chinese_goals_are_found_by_chinese_queries(self):
        self.mem.add(exp("t1", goal="写一个爬虫脚本"))
        self.mem.add(exp("t2", goal="整理会议纪要"))
        self.assertEqual([e.task_id for e in self.mem.recall("写爬虫")], ["t1"])


class ProfileTest(MemoryTestBase):
    def test_counts_per_tag_most_used_first(self):
        for i in range(8):
            self.mem.add(exp(f"c{i}", tags=("code",), success=i != 3))        # 7 of 8
        self.mem.add(exp("g1", tags=("code", "git")))                         # counts for both tags
        self.mem.add(exp("g2", tags=("git",)))
        self.assertEqual(self.mem.profile(),
                         "Recent performance: code 8/9 succeeded, git 2/2 succeeded.")

    def test_known_weak_spots_are_the_lessons_of_recent_failures(self):
        self.mem.add(exp("t1", success=False, lesson="pip install times out"))
        self.mem.add(exp("t2", success=True, lesson="a lesson on a success is ignored"))
        self.mem.add(exp("t3", success=False, lesson="pages that need JS rendering fail"))
        self.mem.add(exp("t4", success=False, lesson="pip install times out"))        # same lesson again: shown once
        self.mem.add(exp("t5", success=False))                                        # a failure without a lesson
        self.assertEqual(self.mem.profile(),
                         "Recent performance: code 1/5 succeeded. Known weak spots: "
                         "pip install times out; pages that need JS rendering fail.")

    def test_at_most_three_lessons(self):
        for i in range(5):
            self.mem.add(exp(f"t{i}", success=False, lesson=f"lesson {i}"))
        self.assertTrue(self.mem.profile().endswith("Known weak spots: lesson 4; lesson 3; lesson 2."))

    def test_only_the_latest_window_counts(self):
        for i in range(PROFILE_WINDOW):
            self.mem.add(exp(f"old{i}", success=False, lesson="an old problem"))
        for i in range(PROFILE_WINDOW):
            self.mem.add(exp(f"new{i}", success=True))
        self.assertEqual(self.mem.profile(), f"Recent performance: code {PROFILE_WINDOW}/{PROFILE_WINDOW} succeeded.")

    def test_untagged_experiences_count_as_other(self):
        self.mem.add(exp("t1", tags=()))
        self.assertEqual(self.mem.profile(), "Recent performance: other 1/1 succeeded.")

    def test_never_longer_than_max_chars(self):
        for i in range(6):
            self.mem.add(exp(f"t{i}", tags=(f"tag{i}",), success=False, lesson="a fairly long lesson about what went wrong " * 3))
        for limit in (300, 120, 60, 10):
            text = self.mem.profile(limit)
            self.assertLessEqual(len(text), limit, limit)
        self.assertNotIn("weak spots", self.mem.profile(150))      # a lesson that does not fit is left out, not cut
        self.assertTrue(self.mem.profile(10).endswith("…"))

    def test_a_lesson_that_does_not_fit_is_skipped_but_shorter_ones_still_show(self):
        self.mem.add(exp("t1", success=False, lesson="short"))
        self.mem.add(exp("t2", success=False, lesson="x" * 200))                 # the newest, too long
        text = self.mem.profile(110)
        self.assertEqual(text, "Recent performance: code 0/2 succeeded. Known weak spots: short.")


class TagsTest(unittest.TestCase):
    def test_tags_from_tools_in_order_of_first_use(self):
        self.assertEqual(tags_for_tools(["write_file", "run_python", "git", "run_python"]), ["file", "code", "git"])
        self.assertEqual(tags_for_tools(["web_search", "fetch_url"]), ["search"])

    def test_documents_are_tagged_doc(self):
        self.assertEqual(tags_for_tools(["write_file"], ["notes.md"]), ["file", "doc"])
        self.assertEqual(tags_for_tools([], ["a.TXT"]), ["doc"])
        self.assertEqual(tags_for_tools(["write_file"], ["a.py"]), ["file"])

    def test_unknown_tools_add_nothing(self):
        self.assertEqual(tags_for_tools(["read_group", "decline"]), [])


class EvolutionTest(MemoryTestBase):
    """The report's story: the same kind of task twice, the second time with the lesson."""

    def test_a_failure_changes_what_is_recalled_and_what_the_orchestrator_sees(self):
        self.mem.add(exp("t1", goal="fetch the docs page and save it", tags=("search",), success=False,
                         summary="the page came back empty", lesson="this site needs JavaScript, use another source"))
        recalled = self.mem.recall("fetch the pricing page and save it")
        self.assertEqual([e.lesson for e in recalled], ["this site needs JavaScript, use another source"])
        self.assertIn("search 0/1 succeeded", self.mem.profile())
        self.mem.add(exp("t2", goal="fetch the pricing page and save it", tags=("search",), success=True))
        self.assertIn("search 1/2 succeeded", self.mem.profile())
        self.assertEqual({e.task_id for e in self.mem.recall("fetch the pricing page")}, {"t1", "t2"})   # the lesson is still there

    def test_the_orchestrator_shows_the_profile_in_the_tool_description(self):
        self.mem.add(exp("t1", success=False, lesson="installing packages times out"))
        bus = InMemoryBus()
        bus.join("orchestrator", GROUP_MAIN)
        settings = Settings(data_dir=self.tmp / "data")
        orch = Orchestrator(bus, Router(bus, StateTable(), {}, settings), settings, MockLLM(), ROLES,
                            {"coder": self.mem})
        specs = {s.name: s for s in orch.function_specs(GROUP_MAIN)}
        self.assertIn("Recent performance: code 0/1 succeeded. Known weak spots: installing packages times out.",
                      specs["call_coder"].description)
        self.assertEqual(specs["call_writer"].description, ROLES["writer"].capability)     # no memory, no profile
        self.assertLessEqual(len(self.mem.profile(settings.profile_max_chars)), settings.profile_max_chars)


if __name__ == "__main__":
    unittest.main()
