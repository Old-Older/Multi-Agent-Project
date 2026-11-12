"""File tools against a real LocalSandbox, including model argument failures."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.sandbox.base import LocalSandbox
from mas.tools import DeleteFile, ListFiles, ReadFile, Tool, ToolResult, WriteFile


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
