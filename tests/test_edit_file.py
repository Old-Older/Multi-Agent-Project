"""edit_file: change a file by exact replacement, all or nothing, and say truthfully what happened."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mas.sandbox.base import LocalSandbox
from mas.tools.files import EditFile

DOC = "# Title\n\nThe index fell 34% from its record.\nThe index fell 34% in five months.\n\n## Risks\n\nTaiwan.\n"


class EditFileTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sandbox = LocalSandbox("agent", Path(self.tmp.name))
        self.sandbox.write_text("doc.md", DOC)

    async def edit(self, **kwargs):
        return await EditFile().run(self.sandbox, path=kwargs.pop("path", "doc.md"), **kwargs)

    def text(self):
        return self.sandbox.read_text("doc.md")

    async def test_one_edit_is_made_and_confirmed_with_the_new_size(self):
        result = await self.edit(old="## Risks", new="## Key risks")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(self.text(), DOC.replace("## Risks", "## Key risks"))
        self.assertEqual(result.output, f"Applied 1 edit to doc.md: {len(DOC)} characters before, now {len(DOC) + 4} "
                                        "characters, 18 words, 8 lines.")
        self.assertEqual(result.files_written, ["doc.md"])

    async def test_several_edits_are_applied_in_order_and_a_later_one_sees_an_earlier_one(self):
        result = await self.edit(edits=[{"old": "Taiwan.", "new": "Taiwan and export controls."},
                                        {"old": "export controls", "new": "export-control escalation"}])
        self.assertTrue(result.ok, result.output)
        self.assertIn("Taiwan and export-control escalation.", self.text())
        self.assertTrue(result.output.startswith("Applied 2 edits to doc.md"))

    async def test_if_one_edit_cannot_be_made_nothing_is_changed_and_it_says_which(self):
        result = await self.edit(edits=[{"old": "# Title", "new": "# New title"},
                                        {"old": "The index fell 35% from its record.", "new": "x"}])
        self.assertFalse(result.ok)
        self.assertIn("edit 2 of 2 not applied", result.output)
        self.assertIn("Nothing was changed", result.output)
        self.assertIn("The closest line in the file is: 'The index fell 34% from its record.'", result.output)
        self.assertEqual(self.text(), DOC)                                      # not even the first edit was kept

    async def test_a_text_that_occurs_twice_needs_to_be_longer_or_to_say_all(self):
        result = await self.edit(old="The index fell 34%", new="The index fell 36%")
        self.assertFalse(result.ok)
        self.assertIn("occurs 2 times", result.output)
        self.assertEqual(self.text(), DOC)
        result = await self.edit(old="The index fell 34%", new="The index fell 36%", all=True)
        self.assertTrue(result.ok, result.output)
        self.assertEqual(self.text().count("36%"), 2)
        result = await self.edit(edits=[{"old": "fell 36%", "new": "fell 34%", "all": True}])
        self.assertTrue(result.ok, result.output)

    async def test_new_may_be_empty_to_delete_and_unicode_is_kept(self):
        self.sandbox.write_text("zh.md", "第一段。\n第二段：港元。\n")
        result = await EditFile().run(self.sandbox, path="zh.md", old="第二段：港元。\n", new="")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(self.sandbox.read_text("zh.md"), "第一段。\n")

    async def test_a_whitespace_difference_is_a_miss_that_shows_the_closest_line(self):
        result = await self.edit(old="The  index fell 34% in five months.", new="x")
        self.assertFalse(result.ok)
        self.assertIn("must match exactly, whitespace included", result.output)

    async def test_bad_arguments_are_errors_and_change_nothing(self):
        cases = ({}, {"old": "a"}, {"new": "a"}, {"old": "", "new": "a"}, {"edits": []}, {"edits": "x"},
                 {"edits": [{"old": "a"}]}, {"edits": [{"old": "a", "new": 1}]}, {"edits": [{"old": "a", "new": "b", "x": 1}]},
                 {"edits": [{"old": "# Title", "new": "x"}], "old": "a", "new": "b"}, {"old": "a", "new": "b", "extra": 1},
                 {"edits": [{"old": "a", "new": "b", "all": "yes"}]})
        for kwargs in cases:
            result = await self.edit(**kwargs)
            self.assertFalse(result.ok, kwargs)
            self.assertEqual(self.text(), DOC, kwargs)
        self.assertFalse((await EditFile().run(self.sandbox, path="", old="a", new="b")).ok)
        self.assertFalse((await EditFile().run(self.sandbox, old="a", new="b")).ok)

    async def test_a_missing_file_or_a_path_outside_the_workspace_is_refused(self):
        self.assertIn("FileNotFoundError", (await self.edit(path="nope.md", old="a", new="b")).output)
        outside = await self.edit(path="../secret.md", old="a", new="b")
        self.assertFalse(outside.ok)
        self.assertIn("outside workspace", outside.output)

    async def test_it_is_a_tool_with_a_schema_the_model_can_see(self):
        spec = EditFile().spec()
        self.assertEqual(spec.name, "edit_file")
        self.assertEqual(spec.parameters["required"], ["path"])
        self.assertIn("edits", spec.parameters["properties"])
        self.assertFalse(EditFile.requires_approval)


if __name__ == "__main__":
    unittest.main()
