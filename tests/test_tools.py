"""File tools against a real LocalSandbox, including model argument failures."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.sandbox.base import LocalSandbox
from mas.tools import DeleteFile, ListFiles, ReadFile, Tool, ToolResult, WriteFile
from mas.tools.files import cut_write


class FileToolsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sandbox = LocalSandbox("coder", self.root / "coder")

    def assertFailure(self, result, contains=None):
        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.ok)
        self.assertEqual(result.files_written, [])
        self.assertEqual(result.refs, {})
        if contains:
            self.assertIn(contains, result.output)

    async def test_write_read_overwrite_list_and_delete(self):
        result = await WriteFile().run(self.sandbox, path="资料/笔记.md", content="中文笔记\n第二行")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.files_written, ["资料/笔记.md"])
        self.assertEqual(result.refs, {})
        read = await ReadFile().run(self.sandbox, path="资料/笔记.md")
        self.assertTrue(read.ok, read.output)
        self.assertEqual(read.output, "中文笔记\n第二行")
        self.assertEqual(read.files_written, [])
        self.assertTrue((await WriteFile().run(self.sandbox, path="资料/笔记.md", content="更新")).ok)
        self.assertEqual((await ReadFile().run(self.sandbox, path="资料/笔记.md")).output, "更新")
        self.assertEqual(json.loads((await ListFiles().run(self.sandbox)).output), ["资料"])
        self.assertEqual(json.loads((await ListFiles().run(self.sandbox, path="资料")).output), ["笔记.md"])
        deleted = await DeleteFile().run(self.sandbox, path="资料/笔记.md")
        self.assertTrue(deleted.ok, deleted.output)
        self.assertEqual(deleted.files_written, [])
        self.assertFalse(self.sandbox.exists("资料/笔记.md"))

    async def test_written_artifact_is_the_canonical_workspace_relative_path(self):
        result = await WriteFile().run(self.sandbox, path="sub/../file.txt", content="")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.files_written, ["file.txt"])
        self.assertEqual(self.sandbox.read_text(result.files_written[0]), "")

    async def test_list_is_sorted_immediate_entries_only(self):
        self.sandbox.write_text("z.txt", "")
        self.sandbox.write_text("a/nested.txt", "")
        result = await ListFiles().run(self.sandbox)
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output), ["a", "z.txt"])

    async def test_missing_paths_return_failure(self):
        for tool in (ReadFile(), DeleteFile(), ListFiles()):
            with self.subTest(tool=tool.name):
                self.assertFailure(await tool.run(self.sandbox, path="missing"), "FileNotFoundError")

    async def test_directories_and_non_text_files_return_failure(self):
        self.sandbox.write_text("sub/file", "x")
        for tool in (ReadFile(), WriteFile(), DeleteFile()):
            with self.subTest(tool=tool.name):
                kwargs = {"path": "sub"}
                if isinstance(tool, WriteFile):
                    kwargs["content"] = "bad"
                self.assertFailure(await tool.run(self.sandbox, **kwargs))
        self.assertFailure(await ListFiles().run(self.sandbox, path="sub/file"))
        (self.sandbox.root / "binary").write_bytes(b"\xff\xfe")
        self.assertFailure(await ReadFile().run(self.sandbox, path="binary"), "UnicodeDecodeError")
        self.assertEqual(self.sandbox.read_text("sub/file"), "x")

    async def test_paths_outside_workspace_fail_for_every_tool(self):
        outside = self.root / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        for path in ("../outside.txt", str(outside)):
            for tool in (ReadFile(), WriteFile(), DeleteFile(), ListFiles()):
                with self.subTest(path=path, tool=tool.name):
                    kwargs = {"path": path}
                    if isinstance(tool, WriteFile):
                        kwargs["content"] = "bad"
                    self.assertFailure(await tool.run(self.sandbox, **kwargs), "PermissionError")
        self.assertEqual(outside.read_text(encoding="utf-8"), "private")

    async def test_schema_and_runtime_arguments_agree(self):
        for tool in (ReadFile(), WriteFile(), DeleteFile(), ListFiles()):
            with self.subTest(tool=tool.name):
                self.assertIsInstance(tool, Tool)
                schema = tool.spec().to_openai()["function"]["parameters"]
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(schema["properties"]["path"]["type"], "string")
                self.assertEqual(schema["properties"]["path"]["minLength"], 1)
                required = [] if isinstance(tool, ListFiles) else ["path"]
                if isinstance(tool, WriteFile):
                    required.append("content")
                    self.assertEqual(schema["properties"]["content"]["type"], "string")
                self.assertEqual(schema["required"], required)
                valid = {"path": "file.txt"}
                if isinstance(tool, WriteFile):
                    valid["content"] = "hello"
                for name in required:
                    invalid = {k: v for k, v in valid.items() if k != name}
                    self.assertFailure(await tool.run(self.sandbox, **invalid), "missing required argument")
                self.assertFailure(await tool.run(self.sandbox, **dict(valid, extra="x")), "unknown arguments")
                for value in (None, 1, True, [], {}):
                    self.assertFailure(await tool.run(self.sandbox, **dict(valid, path=value)), "path must be a string")
                self.assertFailure(await tool.run(self.sandbox, **dict(valid, path="")), "path must not be empty")
                self.assertFailure(await tool.run(self.sandbox, **dict(valid, path="bad\x00path")))
        self.assertEqual(ListFiles.parameters["properties"]["path"]["default"], ".")
        self.assertFailure(await WriteFile().run(self.sandbox, path="file.txt", content=None), "content must be a string")
        self.assertFalse(self.sandbox.exists("file.txt"))

    async def test_failed_write_does_not_claim_an_artifact(self):
        with patch.object(self.sandbox, "write_text", side_effect=PermissionError("access denied")):
            self.assertFailure(await WriteFile().run(self.sandbox, path="file.txt", content="x"), "access denied")
        self.assertFalse(self.sandbox.exists("file.txt"))

    async def test_a_long_file_is_written_in_parts_with_append(self):
        first, second = "<html>\n第一部分\n", "第二部分\n</html>\n"
        self.assertEqual((await WriteFile().run(self.sandbox, path="deck.html", content=first)).output, "Wrote deck.html")
        result = await WriteFile().run(self.sandbox, path="deck.html", content=second, append=True)
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.files_written, ["deck.html"])
        self.assertEqual(self.sandbox.read_text("deck.html"), first + second)
        self.assertEqual(result.output, f"Appended {len(second)} characters to deck.html: it now has "
                                        f"{len(first + second)} characters, 4 lines.")
        self.assertTrue((await WriteFile().run(self.sandbox, path="deck.html", content="x", append=False)).ok)
        self.assertEqual(self.sandbox.read_text("deck.html"), "x")            # without append the file is replaced

    async def test_append_needs_an_existing_file_and_a_boolean(self):
        self.assertFailure(await WriteFile().run(self.sandbox, path="new.txt", content="x", append=True), "does not exist")
        self.assertFalse(self.sandbox.exists("new.txt"))
        for value in (None, 1, "true", []):
            self.assertFailure(await WriteFile().run(self.sandbox, path="new.txt", content="x", append=value),
                               "append must be true or false")
        self.assertFalse(self.sandbox.exists("new.txt"))
        self.assertFailure(await ReadFile().run(self.sandbox, path="new.txt", append=True), "unknown arguments")
        schema = WriteFile().spec().to_openai()["function"]["parameters"]
        self.assertEqual(schema["properties"]["append"]["type"], "boolean")
        self.assertEqual(schema["required"], ["path", "content"])

    def test_what_arrived_of_a_write_that_was_cut_off(self):
        cut = '{"path": "notes/deck.html", "content": "<html>\\n<body>\\n<h1>T\\u4e2d \\"q\\"</h1>\\n<p>half a li'
        self.assertEqual(cut_write(cut), ("notes/deck.html", '<html>\n<body>\n<h1>T中 "q"</h1>\n', False))
        self.assertEqual(cut_write('{"path": "a.md", "append": true, "content": "one\\ntwo\\nthr'),
                         ("a.md", "one\ntwo\n", True))
        self.assertEqual(cut_write('{"path": "a.md", "content": "a long first line without a break\\'),
                         ("a.md", "a long first line without a break", False))      # nothing to cut back to
        self.assertEqual(cut_write('{"path": "a.md", "content": "ends in half an escape \\u4e'),
                         ("a.md", "ends in half an escape ", False))
        for other in ('{"path": "a.md", "content": "whole"}',                     # not cut: the string is closed
                      '{"content": "the path comes after the content and never arr',
                      '{"path": "a.md", "content": "',                            # nothing arrived
                      '{"path": "a.md", "conte', "", "not json at all"):
            self.assertIsNone(cut_write(other), other)

    def test_names_and_approval_contract(self):
        tools = [ReadFile(), WriteFile(), DeleteFile(), ListFiles()]
        self.assertEqual([tool.name for tool in tools], ["read_file", "write_file", "delete_file", "list_files"])
        self.assertEqual([tool.requires_approval for tool in tools], [False, False, True, False])
        for tool in tools:
            spec = tool.spec()
            self.assertEqual(spec.name, tool.name)
            self.assertTrue(spec.description)
            self.assertEqual(json.loads(json.dumps(spec.parameters)), tool.parameters)


if __name__ == "__main__":
    unittest.main()


class ReadWindowTest(unittest.IsolatedAsyncioTestCase):
    """A long file is read in pieces that say how to continue, so a worker need not write a script to read it."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        from mas.sandbox.base import LocalSandbox
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sandbox = LocalSandbox("a", self.tmp)

    async def test_a_short_file_comes_back_whole_and_unchanged(self):
        self.sandbox.write_text("n.md", "short\n")
        self.assertEqual((await ReadFile().run(self.sandbox, path="n.md")).output, "short\n")

    async def test_a_long_file_is_read_piece_by_piece_until_the_end(self):
        from mas.tools.files import READ_WINDOW
        text = "".join(f"{n:05d}" for n in range(2000))                # 10000 characters
        self.sandbox.write_text("big.md", text)
        got, offset = "", 0
        for _ in range(10):
            result = await ReadFile().run(self.sandbox, path="big.md", offset=offset)
            self.assertTrue(result.ok, result.output)
            body, _, note = result.output.partition("\n[")
            got += body
            self.assertLessEqual(len(result.output), 4000)            # survives the worker's own clipping
            if "to continue" not in note:
                self.assertIn("end of file", note)
                break
            offset = int(note.split("offset=")[1].split(" ")[0])
            self.assertEqual(offset, len(got))
        self.assertEqual(got, text)
        self.assertEqual(READ_WINDOW, 3500)

    async def test_a_bad_offset_is_a_failure_the_model_can_read(self):
        self.sandbox.write_text("n.md", "x" * 4000)
        for offset in (-1, True, "3", 1.5):
            result = await ReadFile().run(self.sandbox, path="n.md", offset=offset)
            self.assertFalse(result.ok)
            self.assertIn("offset must be a non-negative integer", result.output)
        past = await ReadFile().run(self.sandbox, path="n.md", offset=9999)
        self.assertFalse(past.ok)
        self.assertIn("past the end", past.output)
