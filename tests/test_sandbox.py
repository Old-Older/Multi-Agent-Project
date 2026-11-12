"""Real local files and short-lived processes; no network or model required."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mas.sandbox import ExecResult, LocalSandbox


class WorkspaceMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name).resolve()
        self.sandbox = LocalSandbox("coder", self.directory / "coder")

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable on this host: {exc}")


class LocalFilesTest(WorkspaceMixin, unittest.TestCase):
    def test_workspace_is_created_and_root_is_absolute(self):
        self.assertTrue(self.sandbox.root.is_dir())
        self.assertTrue(self.sandbox.root.is_absolute())
        self.assertEqual(self.sandbox.resolve("."), self.sandbox.root)
        self.assertEqual(self.sandbox.agent_id, "coder")

    def test_utf8_nested_write_overwrite_list_exists_delete(self):
        s = self.sandbox
        content = "研究结果：你好\n第二行\r\n"
        s.write_text("nested/notes.md", content)
        self.assertEqual(s.read_text("nested/notes.md"), content)
        self.assertEqual(s.resolve("nested/notes.md").read_bytes(), content.encode("utf-8"))
        s.write_text("nested/notes.md", "更新")
        s.write_text(".hidden", "")
        s.write_text("a.txt", "a")
        self.assertEqual(s.read_text("nested/notes.md"), "更新")
        self.assertEqual(s.list_dir(), [".hidden", "a.txt", "nested"])
        self.assertEqual(s.list_dir("nested"), ["notes.md"])
        self.assertTrue(s.exists("nested"))
        self.assertTrue(s.exists("nested/notes.md"))
        s.delete("nested/notes.md")
        self.assertFalse(s.exists("nested/notes.md"))
        self.assertEqual(s.list_dir("nested"), [])

    def test_missing_paths_and_directory_errors(self):
        s = self.sandbox
        self.assertFalse(s.exists("missing/file"))
        for operation in (s.read_text, s.delete, s.list_dir):
            with self.subTest(operation=operation.__name__), self.assertRaises(FileNotFoundError):
                operation("missing")
        s.write_text("file.txt", "text")
        with self.assertRaises(NotADirectoryError):
            s.list_dir("file.txt")
        with self.assertRaises(IsADirectoryError):
            s.delete(".")
        # Windows reports opening a directory as PermissionError; both are OSError.
        with self.assertRaises(OSError):
            s.read_text(".")
        with self.assertRaises(OSError):
            s.write_text(".", "text")
        with self.assertRaises(OSError):
            s.write_text("file.txt/child", "text")

    def test_outside_paths_rejected_by_every_file_operation(self):
        outside = self.directory / "secret.txt"
        outside.write_text("keep", encoding="utf-8")
        s = self.sandbox
        for name in ("../secret.txt", str(outside)):
            for operation in (s.resolve, s.read_text, s.delete, s.list_dir, s.exists,
                              lambda p: s.write_text(p, "changed")):
                with self.subTest(name=name, operation=operation), self.assertRaises(PermissionError):
                    operation(name)
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_normalized_and_inside_absolute_paths(self):
        self.sandbox.write_text("folder/../notes.md", "ok")
        self.assertEqual(self.sandbox.resolve("./notes.md"), self.sandbox.root / "notes.md")
        self.assertEqual(self.sandbox.read_text(str(self.sandbox.root / "notes.md")), "ok")

    def test_invalid_paths_and_content(self):
        for name in ("", "a\0b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.sandbox.resolve(name)
        with self.assertRaises(TypeError):
            self.sandbox.resolve(None)
        with self.assertRaises(TypeError):
            self.sandbox.write_text("bad.txt", 12)
        self.assertFalse(self.sandbox.exists("bad.txt"))
        if os.name == "nt":
            for name in ("NUL", "CON/child.txt", "file.txt:secret", "trailing.", "space ", "dir./file"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.sandbox.resolve(name)

    @unittest.skipUnless(os.name == "nt", "Windows normalizes newly created paths")
    def test_root_is_canonical_after_windows_directory_creation(self):
        sandbox = LocalSandbox("other", self.directory / "workspace.")
        self.assertEqual(sandbox.root, (self.directory / "workspace").resolve())
        self.assertEqual(sandbox.resolve("."), sandbox.root)
        sandbox.write_text("notes.txt", "ok")
        self.assertEqual(sandbox.read_text("notes.txt"), "ok")

    def test_symlink_escape_including_nonexistent_child(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "secret").write_text("keep", encoding="utf-8")
        self.symlink(self.sandbox.root / "link", outside, directory=True)
        for name in ("link/secret", "link/new/nested.txt"):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.sandbox.resolve(name)
        with self.assertRaises(PermissionError):
            self.sandbox.write_text("link/new.txt", "bad")
        self.assertFalse((outside / "new.txt").exists())

    def test_workspace_prefix_is_not_a_boundary(self):
        sibling = self.directory / "coder-other"
        with self.assertRaises(PermissionError):
            self.sandbox.resolve(str(sibling / "file"))


class ImportFileTest(WorkspaceMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.source = LocalSandbox("researcher", self.directory / "researcher")
        self.source.write_text("notes.md", "研究笔记\n")

    def test_copy_between_real_agents_and_custom_nested_name(self):
        src = self.source.resolve("notes.md")
        imported = self.sandbox.import_file(src)
        self.assertEqual(imported, "inbox/notes.md")
        self.assertEqual(self.sandbox.read_text(imported), self.source.read_text("notes.md"))
        self.assertTrue(src.exists())
        other = self.sandbox.import_file(src, "research/renamed.md")
        self.assertEqual(other, "inbox/research/renamed.md")
        self.assertEqual(self.sandbox.read_text(other), "研究笔记\n")

    def test_import_is_binary_safe(self):
        src = self.directory / "binary.dat"
        src.write_bytes(b"\x00\xff\r\n")
        result = self.sandbox.import_file(src)
        self.assertEqual(self.sandbox.resolve(result).read_bytes(), src.read_bytes())

    def test_missing_source_directory_and_collision(self):
        with self.assertRaises(FileNotFoundError):
            self.sandbox.import_file(self.directory / "missing")
        with self.assertRaises(IsADirectoryError):
            self.sandbox.import_file(self.source.root)
        src = self.source.resolve("notes.md")
        target = self.sandbox.import_file(src)
        self.source.write_text("notes.md", "new")
        with self.assertRaises(FileExistsError):
            self.sandbox.import_file(src)
        self.assertEqual(self.sandbox.read_text(target), "研究笔记\n")
        self.assertEqual(self.source.read_text("notes.md"), "new")

    def test_import_target_must_stay_in_inbox(self):
        src = self.source.resolve("notes.md")
        for name in ("../leak.md", "../../leak.md", ".", str(self.directory / "absolute.md")):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.sandbox.import_file(src, name)
        for name in ("", "bad\0name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.sandbox.import_file(src, name)
        self.assertFalse((self.directory / "leak.md").exists())

    def test_symlink_cannot_redirect_target_outside_inbox(self):
        self.sandbox.write_text("other/keep.txt", "keep")
        (self.sandbox.root / "inbox").mkdir()
        self.symlink(self.sandbox.root / "inbox" / "redirect", self.sandbox.root / "other", True)
        with self.assertRaises(PermissionError):
            self.sandbox.import_file(self.source.resolve("notes.md"), "redirect/notes.md")
        self.assertFalse(self.sandbox.exists("other/notes.md"))

    def test_copy_failure_removes_partial_destination(self):
        def fail(source, destination):
            destination.write(b"partial")
            raise OSError("simulated full disk")
        with patch("mas.sandbox.base.shutil.copyfileobj", side_effect=fail):
            with self.assertRaisesRegex(OSError, "full disk"):
                self.sandbox.import_file(self.source.resolve("notes.md"))
        self.assertFalse(self.sandbox.exists("inbox/notes.md"))

    def test_close_failure_removes_destination_without_poisoning_retry(self):
        original_open = Path.open

        class FailOnClose:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self.stream.__enter__()

            def __exit__(self, *exc):
                self.stream.__exit__(*exc)
                raise OSError("simulated flush failure")

        def open_with_close_failure(path, mode="r", *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            return FailOnClose(stream) if mode == "xb" else stream

        with patch.object(Path, "open", open_with_close_failure):
            with self.assertRaisesRegex(OSError, "flush failure"):
                self.sandbox.import_file(self.source.resolve("notes.md"))
        self.assertFalse(self.sandbox.exists("inbox/notes.md"))
        self.assertEqual(self.sandbox.import_file(self.source.resolve("notes.md")), "inbox/notes.md")


class LocalExecTest(WorkspaceMixin, unittest.IsolatedAsyncioTestCase):
    async def run_python(self, code, **kwargs):
        return await self.sandbox.exec([sys.executable, "-X", "utf8", "-c", code], **kwargs)

    async def test_cwd_utf8_stdout_stderr_and_exit_status(self):
        result = await self.run_python(
            "import os, sys; print(os.getcwd()); print('你好'); print('错误', file=sys.stderr)")
        self.assertIsInstance(result, ExecResult)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        lines = result.stdout.splitlines()
        self.assertEqual(Path(lines[0]), self.sandbox.root)
        self.assertEqual(lines[1], "你好")
        self.assertEqual(result.stderr.strip(), "错误")
        failed = await self.run_python("import sys; print('failed', file=sys.stderr); sys.exit(7)")
        self.assertEqual((failed.returncode, failed.timed_out), (7, False))
        self.assertEqual(failed.stderr.strip(), "failed")

    async def test_env_inherited_and_overridden_without_mutating_parent(self):
        with patch.dict(os.environ, {"MAS_TEST_KEEP": "inherited", "MAS_TEST_OVERRIDE": "parent"}):
            result = await self.run_python(
                "import os, json; print(json.dumps([os.getenv('MAS_TEST_KEEP'), os.getenv('MAS_TEST_OVERRIDE')]))",
                env={"MAS_TEST_OVERRIDE": "子进程"})
            self.assertEqual(json.loads(result.stdout), ["inherited", "子进程"])
            self.assertEqual(os.environ["MAS_TEST_OVERRIDE"], "parent")

    async def test_argument_list_does_not_invoke_shell(self):
        literal = "hello world; & echo should-not-run"
        result = await self.sandbox.exec([sys.executable, "-c", "import sys; print(sys.argv[1])", literal])
        self.assertEqual(result.stdout.strip(), literal)
        self.assertEqual(result.returncode, 0)

    async def test_launch_failure_is_result(self):
        result = await self.sandbox.exec([str(self.directory / "no-such-program")])
        self.assertEqual(result.returncode, 127)
        self.assertFalse(result.timed_out)
        self.assertTrue(result.stderr)

    async def test_timeout_keeps_partial_output_and_stops_process(self):
        result = await self.run_python(
            "import time; print('started', flush=True); time.sleep(2); open('late.txt', 'w').write('bad')",
            timeout=0.5)
        self.assertEqual((result.returncode, result.timed_out), (-1, True))
        self.assertIn("started", result.stdout)
        await asyncio.sleep(1.7)
        self.assertFalse(self.sandbox.exists("late.txt"))

    async def assert_descendant_stopped(self, parent_exits=False, cancel=False):
        # A child inherits output pipes. Even if its parent exits early, exec
        # must time out and kill the child rather than hang collecting output.
        child = "import time; time.sleep(2); open('child-late.txt', 'w').write('bad')"
        parent = ("import subprocess, sys, time; "
                  f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                  "open('ready.txt', 'w').write('ready'); "
                  + ("" if parent_exits else "time.sleep(30)"))
        running = asyncio.create_task(self.run_python(parent, timeout=0.8 if not cancel else 30))
        try:
            async def ready():
                while not self.sandbox.exists("ready.txt"):
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(ready(), 3)
            if cancel:
                running.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(running, 5)
            else:
                result = await asyncio.wait_for(running, 5)
                self.assertEqual((result.returncode, result.timed_out), (-1, True))
        finally:
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
        await asyncio.sleep(2.1)
        self.assertFalse(self.sandbox.exists("child-late.txt"))

    async def test_timeout_cleans_child_process(self):
        await self.assert_descendant_stopped()

    async def test_timeout_cleans_child_after_parent_exit(self):
        await self.assert_descendant_stopped(parent_exits=True)

    async def test_cancellation_cleans_process_tree(self):
        await self.assert_descendant_stopped(cancel=True)

    async def test_invalid_command_timeout_and_env(self):
        for cmd in ([], "echo unsafe", [1], [""], ["a\0b"]):
            with self.subTest(cmd=cmd), self.assertRaises(ValueError):
                await self.sandbox.exec(cmd)
        for timeout in (0, -1, float("inf"), float("nan"), True, "1"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                await self.sandbox.exec([sys.executable], timeout=timeout)
        for env in ({"X": 1}, {"bad=name": "x"}, {"": "x"}, {"X": "\0"}, []):
            with self.subTest(env=env), self.assertRaises(ValueError):
                await self.sandbox.exec([sys.executable], env=env)


if __name__ == "__main__":
    unittest.main()
