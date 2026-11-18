"""Git integration tests run entirely in throwaway local repositories."""
import base64
import os
import re
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from mas.sandbox.base import ExecResult, LocalSandbox
from mas.tools.git import Git


@unittest.skipUnless(shutil.which("git"), "git executable is required")
class GitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sandbox = LocalSandbox("test", self.root / "workspace")
        self.tool = Git()

    async def call(self, action, **kwargs):
        return await self.tool.run(self.sandbox, action=action, **kwargs)

    async def git(self, *args):
        result = await self.sandbox.exec(["git", *args])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    async def test_approved_operations_on_a_temporary_repo_and_bare_remote(self):
        self.assertTrue(self.tool.requires_approval)
        self.assertEqual(self.tool.spec().name, "git")
        self.assertTrue((await self.call("init")).ok)
        await self.git("config", "user.name", "Tool Test")
        await self.git("config", "user.email", "test@example.invalid")
        await self.git("config", "commit.gpgsign", "false")
        self.sandbox.write_text("-notes v1.txt", "review me\n")
        self.sandbox.write_text("other.txt", "leave untracked\n")
        self.assertIn("-notes v1.txt", (await self.call("status")).output)
        self.assertTrue((await self.call("add", paths=["-notes v1.txt"])).ok)
        self.assertIn("+review me", (await self.call("diff", staged=True)).output)
        committed = await self.call("commit", message="First revision")
        self.assertTrue(committed.ok, committed.output)
        sha = await self.git("rev-parse", "HEAD")
        self.assertEqual(committed.refs, {"commit": sha})
        self.assertIn("First revision", (await self.call("log")).output)
        self.assertIn("?? other.txt", (await self.call("status")).output)
        self.sandbox.write_text("-notes v1.txt", "new revision\n")
        self.assertIn("+new revision", (await self.call("diff")).output)
        failed = await self.call("commit", message="Nothing staged")
        self.assertFalse(failed.ok)
        self.assertFalse(failed.refs)

        bare = str(self.root / "remote.git")
        await self.git("init", "--bare", bare)
        await self.git("remote", "add", "team", bare)
        pushed = await self.call("push", remote="team")
        self.assertTrue(pushed.ok, pushed.output)
        branch = await self.git("symbolic-ref", "HEAD")
        self.assertEqual(await self.git("--git-dir", bare, "rev-parse", branch), sha)

        # Only this test redirects the HTTPS remote to a throwaway file transport.
        clone = LocalSandbox("colleague", self.root / "checkout")
        url = "https://github.com/example/offline.git"
        git_config = {
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_VALUE_0": url,
            "GIT_CONFIG_KEY_0": f"url.{Path(bare).as_uri()}.insteadOf", "GIT_ALLOW_PROTOCOL": "file",
        }
        with patch.dict(os.environ, git_config):
            copied = await Git("unit-fixture").run(clone, action="clone", url=url)
        self.assertTrue(copied.ok, copied.output)
        self.assertEqual(await self.git("-C", str(clone.root), "rev-parse", "HEAD"), sha)
        self.assertEqual(clone.read_text("-notes v1.txt").splitlines(), ["review me"])
        self.assertIn(url, clone.read_text(".git/config"))
        self.assertNotIn("extraheader", clone.read_text(".git/config").lower())
        self.assertNotIn("unit-fixture", clone.read_text(".git/config"))
        self.assertTrue((await self.tool.run(clone, action="status")).ok)

    async def test_clone_rejects_nonempty_workspace_and_unsafe_urls(self):
        with patch.object(self.sandbox, "exec", new_callable=AsyncMock) as run:
            for url in [None, "", "file:///repo.git", "http://github.com/a/b", "git@github.com:a/b",
                        "https://user:private@github.com/a/b", "https://github.com/a?token=private",
                        "https://github.com/a#private", "https://github.com:private/a",
                        "https://github.com\\@example.com/a", "https://github.com/\na"]:
                with self.subTest(url=url):
                    result = await self.call("clone", url=url)
                    self.assertFalse(result.ok)
                    self.assertNotIn("private", result.output)
            self.sandbox.write_text(".existing", "preserve")
            denied = await self.call("clone", url="https://github.com/example/repo.git")
            self.assertFalse(denied.ok)
            self.assertIn("empty workspace", denied.output)
            self.assertEqual(self.sandbox.read_text(".existing"), "preserve")
            run.assert_not_awaited()

    async def test_github_token_only_in_scoped_environment_for_clone_and_push(self):
        credential = "fixture-token"
        encoded = base64.b64encode(f"x-access-token:{credential}".encode()).decode("ascii")
        tool = Git(github_token=credential)
        for url, authenticated in [("https://github.com/one/repo", True),
                                   ("https://github.com:443/one/repo", True),
                                   ("https://github.com.example.org/one/repo", False),
                                   ("https://github.com:8443/one/repo", False)]:
            with self.subTest(url=url):
                # Even a remote that echoes the credentials must not place them in observations.
                failed = ExecResult(1, encoded, credential)
                with patch.object(self.sandbox, "exec", new=AsyncMock(return_value=failed)) as run:
                    result = await tool.run(self.sandbox, action="clone", url=url)
                self.assertFalse(result.ok)
                self.assertNotIn(credential, result.output)
                self.assertNotIn(encoded, result.output)
                command = run.await_args.args[0]
                env = run.await_args.kwargs["env"]
                self.assertNotIn(credential, " ".join(command))
                self.assertNotIn(encoded, " ".join(command))
                self.assertEqual("MAS_GIT_AUTH_HEADER" in env, authenticated)
                if authenticated:
                    self.assertEqual(env["MAS_GIT_AUTH_HEADER"], "Authorization: Basic " + encoded)
                    self.assertIn("--config-env=http.https://github.com/.extraHeader=MAS_GIT_AUTH_HEADER",
                                  command)
                    self.assertIn("http.https://github.com/.followRedirects=false", command)

        self.assertTrue((await self.call("init")).ok)
        urls = ["https://github.com/one/repo", "https://mirror.example.org/one/repo"]
        for targets in [urls[:1], urls[1:], urls]:
            with self.subTest(targets=targets):
                responses = [ExecResult(0, "\n".join(targets), ""), ExecResult(0, credential, encoded)]
                with patch.object(self.sandbox, "exec", new=AsyncMock(side_effect=responses)) as run:
                    result = await tool.run(self.sandbox, action="push")
                self.assertTrue(result.ok)
                self.assertNotIn(credential, result.output)
                self.assertNotIn(encoded, result.output)
                lookup, push = run.await_args_list
                self.assertNotIn("MAS_GIT_AUTH_HEADER", lookup.kwargs["env"])
                self.assertEqual("MAS_GIT_AUTH_HEADER" in push.kwargs["env"], targets == urls[:1])
                self.assertNotIn(encoded, " ".join(push.args[0]))

    async def test_workspace_never_discovers_parent_repository(self):
        await self.git("init", str(self.root))
        self.sandbox.write_text("note.txt", "do not stage in parent")
        for action, args in (("status", {}), ("add", {"paths": ["note.txt"]})):
            result = await self.call(action, **args)
            self.assertFalse(result.ok)
            self.assertIn("init first", result.output)
        self.assertTrue((await self.call("init")).ok)
        self.assertTrue(self.sandbox.exists(".git/HEAD"))
        self.assertEqual(await self.git("-C", str(self.root), "diff", "--cached", "--name-only"), "")

    async def test_rejects_invalid_arguments_and_gitfile_redirection(self):
        self.assertTrue((await self.call("init")).ok)
        for kwargs in [
            {}, {"action": "reset"}, {"action": "status", "args": ["--help"]},
            {"action": "add"}, {"action": "add", "paths": ["../outside"]},
            {"action": "add", "paths": [str(self.root)]}, {"action": "add", "paths": "foo"},
            {"action": "commit", "message": " "}, {"action": "diff", "staged": "false"},
            {"action": "push", "remote": "--force"}, {"action": "push", "remote": "file:///repo"},
            {"action": "push", "remote": "unconfigured"},
        ]:
            with self.subTest(kwargs=kwargs):
                result = await self.tool.run(self.sandbox, **kwargs)
                self.assertFalse(result.ok)
        linked = LocalSandbox("linked", self.root / "linked")
        linked.write_text(".git", f"gitdir: {self.sandbox.resolve('.git')}")
        with patch.object(linked, "exec", new_callable=AsyncMock) as run:
            self.assertFalse((await self.tool.run(linked, action="status")).ok)
            run.assert_not_awaited()

    async def test_push_errors_return_without_remote_secrets(self):
        self.assertTrue((await self.call("init")).ok)
        for code, timed_out in ((1, False), (-1, True)):
            with self.subTest(code=code):
                responses = [ExecResult(0, "origin\n", ""),
                             ExecResult(code, "", "https://user:fake@example.invalid", timed_out)]
                with patch.object(self.sandbox, "exec", new=AsyncMock(side_effect=responses)):
                    result = await self.call("push")
                self.assertFalse(result.ok)
                self.assertNotIn("fake", result.output)
                self.assertRegex(result.output, re.compile("timed out|exit 1"))
