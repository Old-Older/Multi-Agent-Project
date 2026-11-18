"""The Python tool runs programs through LocalSandbox and reports their diagnostics."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mas.sandbox.base import LocalSandbox
from mas.tools.python import RunPython


class RunPythonTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sandbox = LocalSandbox("developer", Path(temp.name) / "workspace")
        self.tool = RunPython()

    async def test_script_runs_in_workspace_with_literal_arguments_and_utf8_streams(self):
        self.sandbox.write_text(
            "source files/检查.py",
            "import json, os, sys\n"
            "print(os.path.basename(os.getcwd()))\n"
            "print(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
            "print('提示', file=sys.stderr)\n",
        )
        args = ["two words", "", 'quoted "here"', "; echo nope", "中文"]
        with patch.object(self.sandbox, "exec", wraps=self.sandbox.exec) as execute:
            result = await self.tool.run(self.sandbox, path="source files/检查.py", args=args)
        self.assertEqual(execute.await_args.args[0][0], sys.executable)
        self.assertTrue(result.ok, result.output)
        self.assertIn("exit code 0", result.output)
        self.assertIn("workspace", result.output)
        self.assertIn(json.dumps(args, ensure_ascii=False), result.output)
        self.assertIn("stderr:\n提示", result.output)
        self.assertEqual(result.files_written, [])
        self.assertEqual(result.refs, {})

    async def test_script_named_dash_is_not_standard_input(self):
        self.sandbox.write_text("-", "print('ran the script')\n")
        result = await self.tool.run(self.sandbox, path="-")
        self.assertTrue(result.ok, result.output)
        self.assertIn("ran the script", result.output)

    async def test_unittest_module_reports_passing_and_failing_workspace_tests(self):
        path = "checks/test_sample.py"
        args = ["discover", "-s", "checks"]
        self.sandbox.write_text(
            path, "import unittest\nclass Example(unittest.TestCase):\n"
                  "    def test_sum(self):\n        self.assertEqual(1 + 1, 2)\n",
        )
        passed = await self.tool.run(self.sandbox, module="unittest", args=args)
        self.assertTrue(passed.ok, passed.output)
        self.assertIn("Ran 1 test", passed.output)
        self.sandbox.write_text(
            path, "import unittest\nclass Example(unittest.TestCase):\n"
                  "    def test_failure(self):\n        self.fail('sample failure')\n",
        )
        failed = await self.tool.run(self.sandbox, module="unittest", args=args)
        self.assertFalse(failed.ok)
        self.assertIn("exit code 1", failed.output)
        self.assertIn("sample failure", failed.output)

    async def test_missing_script_and_module_return_diagnostics(self):
        for arguments, name in (({"path": "absent.py"}, "absent.py"),
                                ({"module": "mas_missing_workspace_module"}, "mas_missing_workspace_module")):
            with self.subTest(arguments=arguments):
                failed = await self.tool.run(self.sandbox, **arguments)
                self.assertFalse(failed.ok)
                self.assertIn(name, failed.output)
                self.assertIn("stderr:", failed.output)

    async def test_timeout_stops_a_real_local_script(self):
        self.sandbox.write_text("sleep.py", "import time\ntime.sleep(120)\n")
        result = await self.tool.run(self.sandbox, path="sleep.py", timeout=0.15)
        self.assertFalse(result.ok)
        self.assertIn("timed out after 0.15s", result.output)
        self.assertIn("exit code -1", result.output)

    async def test_invalid_model_arguments_are_rejected_before_execution(self):
        invalid = [
            {}, {"path": "a.py", "module": "a"}, {"code": "print(1)"},
            {"path": str(self.sandbox.root / "test.py")}, {"path": "../outside.py"},
            {"path": None}, {"path": ""}, {"module": None}, {"module": "-c"},
            {"module": "bad..name"}, {"module": "unittest", "shell": True},
            {"path": "x.py", "args": "two words"}, {"path": "x.py", "args": [None]},
            {"path": "x.py", "args": ["nul\0"]},
        ]
        invalid.extend({"path": "x.py", "timeout": timeout} for timeout in
                       (0, -1, True, "1", float("nan"), float("inf")))
        with patch.object(self.sandbox, "exec") as execute:
            for kwargs in invalid:
                with self.subTest(kwargs=kwargs):
                    result = await self.tool.run(self.sandbox, **kwargs)
                    self.assertFalse(result.ok)
                    self.assertTrue(result.output.startswith("run_python:"))
            execute.assert_not_awaited()

    def test_advertises_exclusive_entry_points_and_timeout(self):
        spec = self.tool.spec()
        self.assertEqual(spec.name, "run_python")
        self.assertEqual(spec.parameters["oneOf"], [{"required": ["path"]}, {"required": ["module"]}])
        self.assertFalse(spec.parameters["additionalProperties"])
        self.assertEqual(spec.parameters["properties"]["timeout"]["default"], 60)

    async def test_backend_without_exec_returns_an_observation(self):
        with patch.object(self.sandbox, "exec", side_effect=NotImplementedError):
            result = await self.tool.run(self.sandbox, module="unittest")
        self.assertFalse(result.ok)
        self.assertIn("does not support exec", result.output)
