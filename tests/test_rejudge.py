"""Grading archived runs again with the grader that sees whole files."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mas.eval.rejudge import locate, main, render, rejudge_run, split_requests
from mas.llm.base import LLMResponse
from mas.llm.mock import MockLLM

ROOT = Path(__file__).resolve().parents[1]

TRANSCRIPT = """# Transcript: scenario_3_x 2-run1

## Conversation

### 00:00:01 (+00:00) · human → the team

> Make a deck.
> It must be in HTML.
>
> Use 10 slides.

### 00:00:02 (+00:01) · request R1 handed to its lead boss (task `t1`)

### 00:00:30 (+00:29) · boss → human · FINAL REPLY to R1 · done

> @human Done, see deck.html.

### 00:01:00 (+01:00) · human → the team

> Now add a risk slide.

### 00:01:05 (+01:05) · boss → human · FINAL REPLY to R2 · done

> @human Added.

## How the requests ended

| request | lead |
|---|---|
| R1 | boss |
"""


def record(task_index, score=6, passed=False):
    return {"scenario": "scenario_3_x 2", "task_index": task_index, "title": f"task {task_index}", "judged": passed,
            "score": score, "judge_notes": "the file is cut"}


class SplitTest(unittest.TestCase):
    def test_each_request_gets_its_prompt_and_its_own_dialogue(self):
        first, second = split_requests(TRANSCRIPT)
        self.assertEqual(first[0], "Make a deck.\nIt must be in HTML.\n\nUse 10 slides.")
        self.assertIn("FINAL REPLY to R1", first[1])
        self.assertNotIn("risk slide", first[1])
        self.assertEqual(second[0], "Now add a risk slide.")
        self.assertIn("FINAL REPLY to R2", second[1])
        self.assertNotIn("How the requests ended", second[1])
        self.assertEqual(split_requests("# nothing here"), [])

    def test_the_real_archived_transcripts_split_into_their_requests(self):
        path = ROOT / "docs/runs/2026-11-19-round10-full-all3/scenario2/transcript.md"
        if not path.is_file():
            self.skipTest("the archive is not there")
        requests = split_requests(path.read_text(encoding="utf-8"))
        self.assertEqual(len(requests), 2)
        self.assertIn("news report", requests[0][0].lower())
        self.assertIn("fact-check", requests[1][0].lower())
        self.assertIn("FINAL REPLY to R2", requests[1][1])


class RejudgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run_dir = self.tmp / "round"
        (self.run_dir / "scenario3" / "R1-output").mkdir(parents=True)
        (self.run_dir / "scenario3" / "R2-output").mkdir()
        (self.run_dir / "scenario3" / "transcript.md").write_text(TRANSCRIPT, encoding="utf-8")
        (self.run_dir / "scenario3" / "R1-output" / "deck.html").write_text("<p>" + "x" * 30000 + "END-OF-DECK</p>")
        (self.run_dir / "results.json").write_text(json.dumps({"records": [record(1), record(2, 9, True)]}))
        self.prompts = []

        def grader(messages, tools):
            self.prompts.append(messages[1]["content"])
            return LLMResponse('{"passed": true, "score": 8, "notes": "whole file read"}')
        self.llm = MockLLM(responder=grader)

    async def test_every_task_is_graded_again_on_the_whole_file_and_its_own_dialogue(self):
        rows = await rejudge_run(self.run_dir, self.llm)
        self.assertEqual([(r["old_score"], r["new_score"], r["new_passed"]) for r in rows], [(6, 8, True), (9, 8, True)])
        first = self.prompts[0]
        self.assertIn("REQUEST:\nMake a deck.", first)
        self.assertIn("END-OF-DECK", first)                                  # the end of a 30,000-character file is there
        self.assertNotIn("risk slide", first)                                # not the second request's dialogue
        self.assertIn("(no files were delivered)", self.prompts[1])          # task 2 delivered nothing in this archive

    async def test_a_request_without_a_transcript_or_beyond_it_is_reported_not_graded(self):
        (self.run_dir / "results.json").write_text(json.dumps({"records": [record(3)]}))
        rows = await rejudge_run(self.run_dir, self.llm)
        self.assertEqual((rows[0]["new_score"], rows[0]["new_notes"]), (None, "the request is not in the archived transcript"))
        (self.run_dir / "scenario3" / "transcript.md").unlink()
        rows = await rejudge_run(self.run_dir, self.llm)
        self.assertEqual(rows[0]["new_notes"], "no transcript archived for this request")
        self.assertEqual(self.prompts, [])                                   # the grader was never asked

    def test_the_first_archives_keep_everything_in_the_run_folder(self):
        old = self.tmp / "old"
        (old / "R1-task1-output").mkdir(parents=True)
        (old / "transcript.md").write_text(TRANSCRIPT)
        transcript, files = locate(old, "3", 1)
        self.assertEqual((transcript.name, files.name), ("transcript.md", "R1-task1-output"))
        self.assertEqual(locate(old, "3", 2)[1], None)

    async def test_the_table_shows_both_marks(self):
        rows = await rejudge_run(self.run_dir, self.llm)
        table = render("round", rows)
        self.assertIn("| scenario_3_x 2 | 1 | not met (6/10) | met (8/10) |", table)
        self.assertIn("| scenario_3_x 2 | 2 | met (9/10) | met (8/10) |", table)
        self.assertIn("whole file read", table)

    def test_the_command_line_writes_the_two_files_and_skips_a_folder_without_results(self):
        from unittest.mock import patch
        empty = self.tmp / "empty"
        empty.mkdir()
        with patch("mas.app.make_llm", return_value=self.llm):
            self.assertEqual(main([str(self.run_dir), str(empty)]), 0)
        self.assertTrue((self.run_dir / "rejudged.json").is_file())
        self.assertIn("graded then", (self.run_dir / "rejudged.md").read_text(encoding="utf-8"))
        self.assertFalse((empty / "rejudged.md").exists())


if __name__ == "__main__":
    unittest.main()
